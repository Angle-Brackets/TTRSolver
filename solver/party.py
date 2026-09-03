"""Battles with other toons in them, and the two ways to treat them.

WHY THERE ARE TWO MODES
-----------------------
Whether a teammate is something you *choose* or something you *predict*
is not a detail of the search, it is a different problem, and a solver
that assumes the wrong one gives bad advice in the other.

`Mode.PICKUP` is a random group. You control one toon and cannot control
the rest, so their actions are a chance node -- the same shape the cog
phase already has, an outcome distribution over choices you do not make.
Advice is then "the best move given what teammates tend to do".

`Mode.COORDINATED` is an organised team, or one person advising all of
them. Every toon's action is chosen together, which is the only way to
reach the plays that make coordination worth anything -- stacking a
track on one cog for `calc_hp_bonus`, or holding a Trap for somebody
else's Lure.

The distinction is not cosmetic. Searching teammates as choices when you
cannot direct them produces advice like "throw a level 1, my teammate
will throw a level 7 into the same cog for the combo", which assumes an
agreement that does not exist. Modelling them as a distribution when the
team IS coordinating throws away the entire reason to coordinate.

WHAT THE TEAMMATE MODEL IS AND IS NOT
-------------------------------------
`TeammateModel` is the distribution the pickup chance node samples. It
is a **model of people**, not a rule of the game, and nothing in the
wiki or the source can confirm it -- there is no fact of the matter
about what a stranger will throw.

`SensiblePrior` below is therefore a stated guess, written down so it
can be argued with and replaced. It is deliberately crude: real play
data would beat it, and the interface takes a distribution precisely so
a fitted model can be dropped in without touching the search.

Read any pickup-mode number as resting on that guess.
"""
from __future__ import annotations

import random
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from . import (data, facility, mechanics, outcomes as outcomes_mod,
               simulator, unites as unites_mod)
from .data import gags as gags_mod
from .search import expectimax
from .state import Action, BattleState, Track

# `outcomes`, `search.expectimax` and `facility` USED TO BE
# FUNCTION-LOCAL IMPORTS here (in `SensiblePrior._incoming`,
# `SolverPolicy.distribution` and `step`), and none of the three is a
# cycle -- nothing they reach imports `party`. The only two modules that
# import this one are `search.party_search` and `search.hybrid`, and
# neither is reachable from `outcomes` (-> simulator, mechanics, data),
# from `expectimax` (-> outcomes, simulator) or from `facility`
# (-> data, state).
#
# Verified rather than reasoned: every module under solver/ imported in
# its own fresh interpreter, plus `party_search`, `hybrid`, `rl.env`,
# `outcomes` and `expectimax` each imported BEFORE this module.
#
# Why it is worth doing: `_incoming` runs once per cog per candidate
# gag whenever a pickup round samples a teammate, and Python re-runs
# `_handle_fromlist` on every one -- 8,641 import calls from these two
# files in a 4,000-step pickup rollout.


class Mode(str, Enum):
    """Who chooses the teammates' actions."""

    PICKUP = "pickup"            # they do; predict them
    COORDINATED = "coordinated"  # you do; plan for them


# Tracks a teammate is assumed to be trying to do damage with, in the
# order a player reaches for them. Lure and Trap are excluded from the
# prior's first choice not because nobody uses them but because using
# them well depends on what everybody else is doing, which is exactly
# what a pickup group has not agreed.
DAMAGE_TRACKS = (Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP)


class TeammateModel:
    """What a toon you do not control is about to do."""

    def distribution(self, state: BattleState,
                     toon_index: int) -> List[Tuple[float, Optional[Action]]]:
        """(probability, action) pairs summing to 1, for one teammate."""
        raise NotImplementedError

    def sample(self, state: BattleState, toon_index: int,
               rng=random) -> Optional[Action]:
        roll = rng.random()
        running = 0.0
        options = self.distribution(state, toon_index)
        for probability, action in options:
            running += probability
            if roll < running:
                return action
        return options[-1][1] if options else None


# How the prior trades one thing off against another. Not measured --
# see the class docstring -- but each is here because a player visibly
# behaves as if it were.
KILL_BONUS = 60.0        # removing a cog stops it attacking, forever
OVERKILL_WEIGHT = 0.8    # damage past a cog's last hit point is thrown away
SCARCITY_WEIGHT = 45.0   # divided by how many of that gag fit in a pouch
LURE_ROUND_VALUE = 0.85  # of the damage a lured cog would have dealt


class SensiblePrior(TeammateModel):
    """A guess at what a reasonable player throws.

    NOT MEASURED, and it cannot be: there is no fact of the matter about
    what a stranger will do. What it encodes is how people visibly play
    -- spend as little as possible and take as little as possible --
    which matters most in exactly the fights where a party solver is
    worth having, the long ones.

    Four things it weighs, and the first two are why the earlier version
    of this was wrong:

    * **Overkill is waste.** A Wedding Cake into a five-hit-point cog
      kills it and throws the rest away. The first version scored on raw
      damage and so actively preferred the biggest gag in the pouch,
      which is the opposite of how anybody plays. Only damage up to the
      cog's remaining health counts, and the excess is charged for.
    * **Rare gags are dear.** A gag is priced by how few fit in a pouch,
      so a level 7 has to earn its place. Nobody opens with their
      Railroad.
    * **Killing is worth more than hurting.** A dead cog never attacks
      again, which is worth more than the hit points suggest.
    * **Lure is damage prevented.** A lured cog does not attack, so a
      Lure is scored by what it stops rather than what it deals -- which
      is why teams lure so much, and why a model that only knew about
      damage tracks would never predict it.

    `focus` is how much probability the favourite gets. High enough that
    the prediction means something, low enough that the search does not
    plan around a guess as though it were certain.
    """

    def __init__(self, focus: float = 0.6):
        if not 0.0 < focus <= 1.0:
            raise ValueError("focus must be in (0, 1]")
        self.focus = focus

    def _incoming(self, cog) -> float:
        try:
            return float(outcomes_mod.worst_case_damage(cog))
        except (NotImplementedError, ValueError):
            return 0.0

    def _scarcity(self, track: Track, level: int, unlocked: int = 6) -> float:
        """How dear this gag is TO ITS HOLDER.

        A carry limit rises as the track is trained, so the same gag is
        scarcer for a toon who has only just unlocked it. Defaults to a
        fully trained track, which is what this assumed before.
        """
        try:
            limit = gags_mod.carry_limit(track, level, unlocked) or 1
        except (NotImplementedError, ValueError):
            return 0.0
        return SCARCITY_WEIGHT / limit

    def _score_damage(self, damage: int, targets) -> float:
        """Progress toward killing, with overkill charged for."""
        score = 0.0
        for cog in targets:
            useful = min(damage, cog.hp)
            score += useful
            if damage >= cog.hp:
                score += KILL_BONUS
            else:
                continue
            score -= OVERKILL_WEIGHT * (damage - cog.hp)
        return score

    def _candidates(self, state: BattleState, toon_index: int) -> List[Action]:
        toon = state.toons[toon_index]
        if toon.laff <= 0:
            return []
        cogs = state.active_cogs()
        if not cogs:
            return []
        where = {id(c): i for i, c in enumerate(state.cogs)}
        scored: List[Tuple[float, int, int, Action]] = []

        for (track, level), count in toon.gag_counts.items():
            if count <= 0 or toon.track_exp.get(track, 0) <= 0:
                continue
            price = self._scarcity(track, level)
            group = simulator.is_group_action(track, level)

            if track == Track.LURE:
                catchable = [c for c in cogs if not c.status.lured]
                if not catchable:
                    continue
                targets = catchable if group else catchable[:1]
                rounds = mechanics.lure_duration_rounds(level)
                value = LURE_ROUND_VALUE * rounds * sum(
                    self._incoming(c) for c in targets)
                index = None if group else where[id(targets[0])]
                scored.append((value - price, level, count,
                               Action(track, level, index)))
                continue

            if track not in DAMAGE_TRACKS:
                # Trap alone and Toon-Up are judgement calls that depend
                # on what everyone else is doing, which is the thing a
                # pickup group has not agreed. Left out rather than
                # guessed at.
                continue

            try:
                damage = data.gag(track, level).damage_at(
                    1.0, organic=toon.is_organic(track))
            except (NotImplementedError, ValueError):
                continue
            if not damage:
                continue

            if group:
                value = self._score_damage(damage, cogs)
                scored.append((value - price, level, count,
                               Action(track, level, None)))
                continue
            for cog in cogs:
                if track == Track.DROP and cog.status.lured:
                    continue          # always misses; nobody aims there
                value = self._score_damage(damage, [cog])
                scored.append((value - price, level, count,
                               Action(track, level, where[id(cog)])))

        # Ties broken toward the cheaper and the more plentiful gag,
        # which is the same instinct the scoring is trying to capture.
        scored.sort(key=lambda row: (-row[0], row[1], -row[2]))
        return [action for _v, _l, _c, action in scored]

    def distribution(self, state: BattleState, toon_index: int
                     ) -> List[Tuple[float, Optional[Action]]]:
        options = self._candidates(state, toon_index)
        if not options:
            # Nothing to throw. Sitting the round out is the honest
            # prediction, not an invented attack.
            return [(1.0, None)]
        if len(options) == 1:
            return [(1.0, options[0])]
        rest = (1.0 - self.focus) / (len(options) - 1)
        return ([(self.focus, options[0])]
                + [(rest, action) for action in options[1:]])


class SolverPolicy(TeammateModel):
    """Assume a teammate plays the objective you are recommending.

    The principled version of the same idea. `SensiblePrior` hand-scores
    an imitation of good play; this asks the solver what good play *is*
    and predicts that -- so a party is modelled as everyone subscribing
    to the same objective rather than as one real player surrounded by
    approximations.

    Better in a way that costs. A prior is a scan of the pouch; this is
    a search per teammate per node, so it is for offline work -- asking
    what a coordinated team should do, checking whether a known strategy
    falls out -- and not for the 15-second budget the live advisor has.

    `depth` is deliberately shallow. A teammate is being *predicted*,
    and predicting them as a deeper searcher than the person you are
    advising is a strange claim to make about a stranger.

    LIMITATION worth knowing: the state is rotated so the teammate sits
    at index 0, because the search assumes it is choosing for `toons[0]`
    -- but `CogStatus.damage_by_toon` indices are not rotated with it,
    so a cog's memory of who hurt it is wrong from the rotated point of
    view. That only skews which toon a cog is predicted to attack
    inside the teammate's own lookahead, not the round actually played.
    """

    def __init__(self, depth: int = 2, objective=None, focus: float = 0.7):
        if not 0.0 < focus <= 1.0:
            raise ValueError("focus must be in (0, 1]")
        self.depth = depth
        self.objective = objective
        self.focus = focus
        self._fallback = SensiblePrior(focus=focus)

    def distribution(self, state: BattleState, toon_index: int
                     ) -> List[Tuple[float, Optional[Action]]]:
        if state.toons[toon_index].laff <= 0 or not state.active_cogs():
            return [(1.0, None)]
        rotated = _as_actor(state, toon_index)
        try:
            action = expectimax.best_action(rotated, depth=self.depth,
                                            objective=self.objective)
        except (NotImplementedError, ValueError, RecursionError):
            return self._fallback.distribution(state, toon_index)
        if action is None:
            return [(1.0, None)]

        # The rest of the mass goes on the prior's alternatives, so the
        # node stays a distribution rather than a claim of certainty.
        others = [a for _p, a in self._fallback.distribution(state, toon_index)
                  if a is not None and a != action]
        if not others:
            return [(1.0, action)]
        share = (1.0 - self.focus) / len(others)
        return [(self.focus, action)] + [(share, a) for a in others]


def _as_actor(state: BattleState, toon_index: int) -> BattleState:
    """The same battle seen from one toon's seat.

    The search chooses for `toons[0]`, so predicting what toon 2 would
    do means handing it a state where toon 2 is toon 0.
    """
    if toon_index == 0:
        return state
    rotated = state.clone()
    order = [toon_index] + [i for i in range(len(state.toons))
                            if i != toon_index]
    rotated.toons = [rotated.toons[i] for i in order]
    return rotated


DEFAULT_MODEL = SensiblePrior()


def teammate_actions(state: BattleState, mine: Optional[Action],
                     mode: Mode = Mode.PICKUP,
                     model: Optional[TeammateModel] = None,
                     rng=random,
                     joint: Optional[Sequence[Optional[Action]]] = None
                     ) -> List[Optional[Action]]:
    """Everybody's action for the round, including yours at index 0.

    In `COORDINATED` mode `joint` supplies the whole team's choices and
    this only checks it; in `PICKUP` mode the teammates are sampled from
    `model`.
    """
    if mode is Mode.COORDINATED:
        if joint is None:
            raise ValueError("coordinated mode needs the team's actions")
        if len(joint) != len(state.toons):
            raise ValueError(
                f"got {len(joint)} actions for {len(state.toons)} toons")
        return list(joint)

    model = model or DEFAULT_MODEL
    actions: List[Optional[Action]] = [mine]
    for index in range(1, len(state.toons)):
        actions.append(model.sample(state, index, rng))
    return actions


def step(state: BattleState, mine: Optional[Action] = None,
         mode: Mode = Mode.PICKUP,
         model: Optional[TeammateModel] = None,
         joint: Optional[Sequence[Optional[Action]]] = None,
         rng=random) -> Tuple[BattleState, List[int], bool]:
    """One full party round: everyone acts, then the cogs do.

    Returns (next state, laff healed per toon, whether it ended). The
    state is cloned, so the caller's is untouched.

    The cog phase is still the solo one -- see the module note in
    `simulator` -- with the difference that a cog's single-target attack
    now chooses whom to hit, via `mechanics.pick_cog_target`.
    """
    nxt = state.clone()
    actions = teammate_actions(nxt, mine, mode, model, rng, joint)
    lured_before = any(c.status.lured for c in state.active_cogs())
    healed = simulator.apply_party_round(nxt, actions, rng=rng)

    # SPEND THE PASS BUDGET. `apply_party_round` filters passes out
    # before it does anything, so nothing here was decrementing
    # `free_passes` and a party could have passed forever -- the
    # termination measure (gags, lure rounds, free passes) would have
    # stopped descending. Charged once per round rather than per toon,
    # and not at all while a cog is lured, because there the lure timer
    # is already the quantity going down.
    if not lured_before and any(a is not None and a.is_pass
                                for a in actions):
        nxt.free_passes = max(0, nxt.free_passes - 1)

    if not nxt.is_terminal():
        _party_cog_phase(nxt, healed, rng)
    nxt.round_num += 1

    # THE UNITE COOLDOWN TICKS HERE, at the round boundary.
    #
    # `unites.tick_cooldown` had NO CALLER anywhere in `solver/`. Using
    # a unite set `unite_cooldown = COOLDOWN_ROUNDS` and nothing ever
    # decremented it, so `can_use_unite` stayed False for the rest of
    # the battle: one unite per fight, permanently, however many the
    # toon carried.
    #
    # Found in a solo VP trace -- the toon died on round 37 holding
    # SEVEN of its eight unites, having sat on 2 laff for nine straight
    # rounds. In a fight this project's own arithmetic says is decided
    # by laff, that is most of the healing on hand being unreachable.
    #
    # Ticked in `step`, not in `apply_party_round`: the scorers call
    # that one on scratch clones to price a plan, and a cooldown that
    # ran down during scoring would let a search see a unite it cannot
    # actually have yet.
    for toon in nxt.toons:
        unites_mod.tick_cooldown(toon)


    # Cogs walk in to replace the dead, at the ROUND BOUNDARY.
    #
    # This was inside `apply_party_round` and had to move. That function
    # is not only how a round resolves -- `greedy_plan` calls it on a
    # scratch clone after each toon picks, so later toons can see the
    # earlier ones' choices. Reinforcing there appended a cog to the
    # scratch state, so the next toon enumerated a target index that did
    # not exist in the real state, and the plan raised IndexError when
    # applied.
    #
    # The boundary is also where it belongs on the merits: a cog that
    # walks in should not be targetable by gags thrown in the round it
    # joined, nor get to swing in it. Both phases are done by here.
    facility.reinforce(nxt)
    return nxt, healed, nxt.is_terminal()


def _party_cog_phase(state: BattleState, healed: List[int], rng) -> None:
    """Cogs attack, choosing whom.

    The same phase as `simulator._resolve_cog_phase`, differing only in
    that the damage now has to land on somebody in particular --
    `mechanics.pick_cog_target`, which prefers whoever hurt this cog
    most.

    Group attacks hit every standing toon. [CONFIRMED] TTR wiki, which
    classifies all 68 attacks into "Group Cog attacks" (14) and "Single
    Cog attacks" (54) -- see `data.GROUP_ATTACKS`. Before this the party
    took strictly less damage than the game deals, because every attack
    was resolved as single-target.

    One accuracy roll decides a group attack for the whole team, the
    same shape as a toon's group gag: it either connects or it does not.
    """
    damage_taken = [0 for _ in state.toons]
    for cog in state.active_cogs():
        if cog.status.lured and not simulator._tick_lure(cog, rng):
            continue    # lure held: cog skips its attack

        attack_name = mechanics.pick_cog_attack(cog, rng)
        damage, accuracy = mechanics.cog_attack_damage_and_accuracy(
            cog, attack_name, rng)
        if not mechanics.roll_hit(accuracy, rng):
            continue
        if data.is_group_attack(attack_name):
            # Hits everyone still standing. No `pick_cog_target` call --
            # there is no choice of target to make.
            for index, toon in enumerate(state.toons):
                if toon.laff > 0:
                    damage_taken[index] += damage
        else:
            target = mechanics.pick_cog_target(cog, state.toons, rng)
            damage_taken[target] += damage

    for index, toon in enumerate(state.toons):
        # Heal then damage, in that order -- see the note in
        # `simulator.step`. One combined clamp let a Toon-Up thrown by a
        # toon on full laff soak up the round's damage, which is why a
        # healthy four-toon party was being advised to heal.
        toon.laff = min(toon.max_laff, toon.laff + healed[index])
        toon.laff = max(0, toon.laff - damage_taken[index])
