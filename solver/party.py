"""Battles with other toons in them, and the two ways to treat them.

WHY THERE ARE TWO MODES: whether a teammate is something you *choose* or
something you *predict* is a different problem, not a detail of the
search, and assuming the wrong one gives bad advice in the other.

`Mode.PICKUP` is a random group: you control one toon, so the rest are a
chance node (the same shape the cog phase already has), and advice is
"the best move given what teammates tend to do". `Mode.COORDINATED` is
an organised team, or one person advising all of them -- every toon's
action is chosen together, the only way to reach plays that make
coordination worth anything (stacking a track for `calc_hp_bonus`,
holding a Trap for somebody else's Lure).

Searching teammates as choices you can't direct produces advice like
"throw a level 1, my teammate will throw a level 7 for the combo", which
assumes an agreement that doesn't exist; modelling a coordinating team
as a distribution throws away the reason to coordinate.

WHAT THE TEAMMATE MODEL IS AND IS NOT: `TeammateModel` is the
distribution the pickup chance node samples. It's a **model of people**,
not a rule of the game -- nothing in the wiki or the source can confirm
what a stranger will throw. `SensiblePrior` below is a stated guess,
written down so it can be argued with and replaced; the interface takes
a distribution so a model fitted from real play can be dropped in
without touching the search. Read any pickup-mode number as resting on
that guess.
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

# `outcomes`, `search.expectimax` and `facility` are imported at module
# level rather than function-locally: none of the three is a cycle
# (nothing they reach imports `party`, verified by importing every
# module under solver/ in its own fresh interpreter), and a
# function-local import re-runs on every call -- 8,641 import calls from
# these two files in a 4,000-step pickup rollout, since `_incoming` runs
# once per cog per candidate gag whenever a pickup round samples a
# teammate.


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
    which matters most in the long fights a party solver is worth
    having for.

    Four things it weighs:

    * **Overkill is waste.** Only damage up to the cog's remaining
      health counts; the excess is charged for, so the model doesn't
      prefer the biggest gag in the pouch regardless of target.
    * **Rare gags are dear.** Priced by how few fit in a pouch, so a
      level 7 has to earn its place.
    * **Killing is worth more than hurting.** A dead cog never attacks
      again.
    * **Lure is damage prevented.** A lured cog doesn't attack, so a
      Lure is scored by what it stops rather than what it deals.

    `focus` is how much probability the favourite gets -- high enough
    the prediction means something, low enough the search doesn't plan
    around a guess as though it were certain.
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
                    1.0, organic=toon.is_organic(track, level))
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

    The principled version of `SensiblePrior`: instead of hand-scoring
    an imitation of good play, this asks the solver what good play *is*
    and predicts that.

    Costs more: a prior is a scan of the pouch, this is a search per
    teammate per node, so it's for offline work (checking whether a
    known strategy falls out of a coordinated team) rather than the
    15-second live advisor budget.

    `depth` is deliberately shallow -- predicting a teammate as a deeper
    searcher than the person being advised is a strange claim to make
    about a stranger.

    LIMITATION: the state is rotated so the teammate sits at index 0 (the
    search assumes it chooses for `toons[0]`), but `CogStatus.
    damage_by_toon` indices aren't rotated with it, so a cog's memory of
    who hurt it is wrong from the rotated view. This only skews which
    toon a cog is predicted to attack inside the teammate's own
    lookahead, not the round actually played.
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


def assumed_teammates(you, count: int, seed: int = 0) -> list:
    """Stand-ins for teammates a client cannot read -- TTR's, whose gags and
    laff nothing reports.

    NOT FULLY IMPLEMENTED: shelved, and unused by the live panel
    (`overlay.Worker.stand_in_teammates` is off). See docs/roadmap.md.

    A GUESS ABOUT PEOPLE, like `SensiblePrior`, and to stay labelled as one:
    each is built like you (your training levels, a full building
    restock at your pouch size, full laff, no SOS cards, unites or slips),
    on the bet that players group with others near their level. Without
    them the playouts planned as if you must beat every cog alone, only
    taking less damage, and "a teammate covers this, save the gag" could
    not be found. Deterministic in `seed`, so every playout process sees
    the same teammates and builds the same menu.
    """
    from .rl import env as env_mod
    from .state import ToonState

    mates = []
    for i in range(max(0, int(count))):
        mate = ToonState(laff=you.max_laff, max_laff=you.max_laff,
                         track_exp=dict(you.track_exp), gag_counts={},
                         pouch_capacity=you.pouch_capacity)
        env_mod.restock(mate, random.Random(seed * 31 + i),
                        capacity=you.pouch_capacity)
        mates.append(mate)
    return mates


def drawn_teammates(you, count: int, seed: int, street: str = "") -> list:
    """Teammates DRAWN from who plays where, for one rollout: the pickup
    playouts call this with each rollout's seed, so they average over who
    the teammates might be instead of betting on one (`rollout_pickup`).

    A GUESS ABOUT PEOPLE, labelled as one. Each is `env.toon_for_street`
    -- the repo's model of a toon on that street, which built every
    simulated party -- restocked for a building, at full laff. Without a
    street (TTR's boards carry none) the street is drawn from those whose
    playground's laff band holds your max laff, the bet that players
    group near their level. Training varies, which is the point: given a
    fixed teammate, the playouts planned around gags nobody held.
    """
    from . import facility
    from .rl import env as env_mod

    rng = random.Random(seed * 7919 + 17)
    named = [s for s in facility.STREETS if s[0] == street]
    if not named:
        laff = you.max_laff
        named = [s for s in facility.STREETS
                 if facility.PROGRESSION[s[1]]["laff"][0] <= laff
                 <= facility.PROGRESSION[s[1]]["laff"][1]]
    if not named:
        def gap(s):
            low, high = facility.PROGRESSION[s[1]]["laff"]
            return min(abs(you.max_laff - low), abs(you.max_laff - high))
        best = min(gap(s) for s in facility.STREETS)
        named = [s for s in facility.STREETS if gap(s) == best]
    mates = []
    for _ in range(max(0, int(count))):
        mate = env_mod.toon_for_street(rng, rng.choice(named))
        env_mod.restock(mate, rng)
        mate.laff = mate.max_laff
        mates.append(mate)
    return mates


def with_assumed_teammates(state: BattleState, seed: int = 0) -> BattleState:
    """`state` with its count of unseen teammates (`allies_standing`) made
    into `assumed_teammates`. A copy; a board with no count, or that
    already holds its teammates, comes back as it is."""
    allies = int(getattr(state, "allies_standing", 0) or 0)
    if allies <= 0 or len(state.toons) != 1:
        return state
    board = state.clone()
    board.toons = [board.toons[0]] + assumed_teammates(board.toons[0], allies, seed)
    board.allies_standing = 0
    board.assumed_allies = allies
    return board


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


class NetTeammate(TeammateModel):
    """A teammate who plays sensibly for THEIR pouch and the board.

    Even a stranger knows their own gags and laff and can see the cogs.
    This asks the fast network (`search.fastplayer`, a copy of climb) what
    to throw from the teammate's own seat, and spreads the probability
    over its top `k` moves, sharpened or flattened by `temperature`.

    STILL A MODEL OF PEOPLE: it assumes a stranger plays roughly as climb
    would, which nothing can confirm -- the same standing as
    `SensiblePrior`, with the difference that it reacts to the actual
    pouch and board instead of a hand-written scoring of them. Falls back
    to `SensiblePrior` when the network is unavailable.
    """

    def __init__(self, k: int = 4, temperature: float = 1.0):
        self.k = k
        self.temperature = temperature
        self._fallback = SensiblePrior()

    def distribution(self, state: BattleState, toon_index: int
                     ) -> List[Tuple[float, Optional[Action]]]:
        from .search import fastplayer

        if state.toons[toon_index].laff <= 0 or not state.active_cogs():
            return [(1.0, None)]
        if not fastplayer.available():
            return self._fallback.distribution(state, toon_index)
        ranked = fastplayer.ranked(_seat_view(state, toon_index), self.k)
        if not ranked:
            return [(1.0, None)]
        weights = [p ** (1.0 / self.temperature) for _plan, p in ranked]
        total = sum(weights)
        out = []
        for (plan, _p), w in zip(ranked, weights):
            action = plan[0] if plan else None
            if action is not None and action.is_pass:
                action = None
            out.append((w / total, action))
        return out


def _seat_view(state: BattleState, toon_index: int) -> BattleState:
    """That toon alone, the others a count -- the shape the network knows."""
    view = state.clone()
    me = view.toons[toon_index]
    others = sum(1 for i, t in enumerate(view.toons) if i != toon_index and t.laff > 0)
    view.toons = [me]
    view.allies_standing = others + max(0, int(getattr(state, "allies_standing", 0)))
    view.holdout = []
    return view


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
    # before doing anything, so this is the only place `free_passes`
    # decrements -- without it a party could pass forever and the
    # termination measure (gags, lure rounds, free passes) would stop
    # descending. Charged once per round, not per toon, and not at all
    # while a cog is lured, since the lure timer is already descending.
    if not lured_before and any(a is not None and a.is_pass
                                for a in actions):
        nxt.free_passes = max(0, nxt.free_passes - 1)

    if not nxt.is_terminal():
        _party_cog_phase(nxt, healed, rng)
    nxt.round_num += 1

    # THE UNITE COOLDOWN TICKS HERE, at the round boundary, not inside
    # `apply_party_round`: that function also runs on scratch clones
    # (`greedy_plan` prices a plan with it), and a cooldown that ran down
    # during scoring would let a search see a unite it doesn't actually
    # have yet.
    for toon in nxt.toons:
        unites_mod.tick_cooldown(toon)

    # Cogs walk in to replace the dead, at the ROUND BOUNDARY rather than
    # inside `apply_party_round` -- `greedy_plan` calls that on a scratch
    # clone after each toon picks, so reinforcing there would append a
    # cog absent from the real state and make a later toon's target index
    # invalid. The boundary is also right on the merits: a cog that walks
    # in should not be targetable by, or get to swing in, the round it
    # joined.
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
    Cog attacks" (54) -- see `data.GROUP_ATTACKS`.

    One accuracy roll decides a group attack for the whole team, the
    same shape as a toon's group gag: it either connects or it does not.
    """
    damage_taken = [0 for _ in state.toons]
    miss_factor = simulator.cogs_miss_factor(state)
    for cog in state.active_cogs():
        if cog.status.lured and not simulator._tick_lure(cog, rng):
            continue    # lure held: cog skips its attack

        attack_name = mechanics.pick_cog_attack(cog, rng)
        damage, accuracy = mechanics.cog_attack_damage_and_accuracy(
            cog, attack_name, rng)
        accuracy = int(round(accuracy * miss_factor))
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
