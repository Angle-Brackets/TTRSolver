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

from . import data, mechanics, simulator
from .state import Action, BattleState, Track


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


class SensiblePrior(TeammateModel):
    """A guess at what an average player throws.

    THIS IS NOT MEASURED. It says: pick the biggest damage gag you are
    carrying and aim it at the cog you are most likely to kill with it,
    preferring one you can finish outright; failing that, aim at the
    toughest. Most of the mass goes on that choice and the remainder is
    spread over the alternatives, because people are not deterministic
    and a chance node that thinks they are will be confidently wrong.

    `focus` is how much of the mass the favourite gets. High enough that
    the prediction means something, low enough that the search does not
    plan around it as if it were certain.
    """

    def __init__(self, focus: float = 0.6):
        if not 0.0 < focus <= 1.0:
            raise ValueError("focus must be in (0, 1]")
        self.focus = focus

    def _candidates(self, state: BattleState, toon_index: int) -> List[Action]:
        toon = state.toons[toon_index]
        if toon.laff <= 0:
            return []
        cogs = state.active_cogs()
        if not cogs:
            return []
        where = {id(c): i for i, c in enumerate(state.cogs)}

        best: List[Tuple[int, Action]] = []
        for (track, level), count in toon.gag_counts.items():
            if count <= 0 or track not in DAMAGE_TRACKS:
                continue
            if toon.track_exp.get(track, 0) <= 0:
                continue
            try:
                damage = data.gag(track, level).damage_at(
                    1.0, organic=toon.is_organic(track))
            except (NotImplementedError, ValueError):
                continue
            if not damage:
                continue
            if simulator.is_group_action(track, level):
                best.append((damage * len(cogs), Action(track, level, None)))
                continue
            for cog in cogs:
                if track == Track.DROP and cog.status.lured:
                    continue          # always misses; nobody aims there
                # A kill is worth more than the raw number, which is how
                # a player picks: finish something if you can.
                score = damage + (1000 if damage >= cog.hp else 0)
                best.append((score, Action(track, level, where[id(cog)])))

        best.sort(key=lambda pair: -pair[0])
        return [action for _score, action in best]

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
    healed = simulator.apply_party_round(nxt, actions)

    if not nxt.is_terminal():
        _party_cog_phase(nxt, healed, rng)
    nxt.round_num += 1
    return nxt, healed, nxt.is_terminal()


def _party_cog_phase(state: BattleState, healed: List[int], rng) -> None:
    """Cogs attack, choosing whom.

    The same phase as `simulator._resolve_cog_phase`, differing only in
    that the damage now has to land on somebody in particular --
    `mechanics.pick_cog_target`, which prefers whoever hurt this cog
    most.

    [TODO] Group cog attacks. Some attacks hit every toon, and this
    treats all of them as single-target, so a party takes less damage
    here than it should. Fixing it needs a per-attack group flag, which
    the cog tables do not carry -- the solo model never had a use for
    one, since one toon is both the target and the group.
    """
    damage_taken = [0 for _ in state.toons]
    for cog in state.active_cogs():
        if cog.status.lured and not simulator._tick_lure(cog):
            continue    # lure held: cog skips its attack

        attack_name = mechanics.pick_cog_attack(cog)
        damage, accuracy = mechanics.cog_attack_damage_and_accuracy(
            cog, attack_name)
        if not mechanics.roll_hit(accuracy):
            continue
        target = mechanics.pick_cog_target(cog, state.toons, rng)
        damage_taken[target] += damage

    for index, toon in enumerate(state.toons):
        toon.laff = max(0, min(toon.max_laff,
                               toon.laff + healed[index] - damage_taken[index]))
