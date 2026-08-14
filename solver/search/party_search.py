"""Searching a battle with more than one toon in it.

Structurally the same expectimax the solo solver uses -- MAX over what
you choose, CHANCE over what you do not -- with the party question
answered at the MAX node rather than bolted on:

    Mode.COORDINATED   MAX ranges over the whole team's joint action
    Mode.PICKUP        MAX ranges over YOUR action; the teammates are
                       part of the chance node, sampled from a
                       TeammateModel

That difference is the whole design. Searching teammates as choices you
do not have produces advice that assumes an agreement nobody made;
treating a coordinated team as a distribution throws away the reason
they coordinated. See `solver/party.py`.

WHY THIS SAMPLES INSTEAD OF ENUMERATING
---------------------------------------
The solo search enumerates its chance nodes exactly, which is what makes
`solve()` exact. A party round cannot be: the outcome space is the
accuracy rolls (one per track per target), times each cog's choice of
attack, times its choice of *whom* to hit, times the teammates' actions
in pickup mode. Enumerating that is hopeless, so each chance node is
estimated from `samples` playouts of the round.

The consequence is worth stating plainly: **this is an estimate, and
values from it are not comparable with `expectimax.solve`'s**. Nothing
here is exact and nothing should be labelled as though it were.

COST, AND WHY THE DEFAULTS ARE SMALL
------------------------------------
A coordinated plan is a multiset of actions over four toons, so the
branching is brutal even after the reductions in `plans()`. Depth 1 with
a modest `samples` is affordable; depth 2 multiplies by the branching
again. The defaults are set where a real position answers in seconds,
not where the search is strongest.
"""
from __future__ import annotations

import itertools
import random
from typing import Dict, List, Optional, Sequence, Tuple

from .. import party as party_mod
from .. import simulator
from ..party import Mode, TeammateModel
from ..state import Action, BattleState, Track
from . import expectimax
from . import objective as objective_mod

# Candidate actions kept per track per toon. Two was not enough and the
# mistake is recorded in docs/party-strategy.md: at two, Sound offered
# only levels 7 and 6, so every mixed-level Sound plan -- including the
# best one available -- was unreachable, and the search reported the
# wrong answer with total confidence.
PER_TRACK = 4

# Plans considered at a MAX node, after ranking them cheaply. The joint
# space is far larger than this; the cap is what makes the search
# finish, and it is the first thing to raise when an answer looks wrong.
MAX_PLANS = 60

# Playouts per plan at a chance node.
SAMPLES = 8


def candidates(state: BattleState, toon_index: int,
               per_track: int = PER_TRACK) -> List[Action]:
    """A few actions per track for one toon, ranked within each track.

    Per *track* rather than overall, so no track is squeezed out by
    another being generally stronger -- Sound gets the same slots as
    Drop. Ranking inside a track uses `SensiblePrior`, which is a guess
    about play and only decides which levels of a track make the
    shortlist, never which track wins.
    """
    rotated = party_mod._as_actor(state, toon_index)
    prior = party_mod.SensiblePrior()
    order = {(a.track, a.level, a.target_index): i
             for i, a in enumerate(prior._candidates(rotated, 0))}

    by_track: Dict[Track, List[Action]] = {}
    for action in simulator.legal_actions(rotated):
        if action.is_pass:
            continue
        by_track.setdefault(action.track, []).append(action)

    out: List[Action] = []
    for actions in by_track.values():
        actions.sort(key=lambda a: order.get(
            (a.track, a.level, a.target_index), 10 ** 6))
        out.extend(actions[:per_track])
    return out


def plans(state: BattleState, mode: Mode = Mode.PICKUP,
          per_track: int = PER_TRACK,
          max_plans: int = MAX_PLANS) -> List[Sequence[Optional[Action]]]:
    """The team plans worth considering from this position.

    In pickup mode a "plan" is just your own action with the teammates
    left as None -- they are sampled during the rollout, not chosen.

    In coordinated mode it is every toon's action. Two reductions keep
    that enumerable, and both are approximations rather than facts:

    * Plans are taken as multisets when the toons are interchangeable,
      because {Sound, Sound, Throw} is one plan and not six. Toons with
      different pouches are not interchangeable, so the multiset is
      then only an approximation and the assignment is checked for
      legality when it is applied.
    * `max_plans` truncates what is left.
    """
    if mode is Mode.PICKUP:
        blanks = [None] * (len(state.toons) - 1)
        return [[action] + blanks for action in candidates(state, 0,
                                                           per_track)]

    per_toon = [candidates(state, i, per_track)
                for i in range(len(state.toons))]
    if not all(per_toon):
        return []

    identical = all(t.gag_counts == state.toons[0].gag_counts
                    for t in state.toons)
    if identical:
        combos = itertools.combinations_with_replacement(
            per_toon[0], len(state.toons))
    else:
        combos = itertools.product(*per_toon)

    # Rank before truncating. Taking a prefix of the enumeration is not
    # a filter, it is an alphabetical accident: `combinations_with_
    # replacement` starts with the first candidate repeated, so the
    # first 60 plans were every arrangement of Trap on one cog and the
    # search never saw a Sound plan at all. It then reported a
    # coordinated value BELOW the pickup value, which cannot happen when
    # coordinated may choose strictly more -- the tell that the plan
    # list, not the search, was broken.
    #
    # Ranking is one deterministic all-hit round: damage that lands,
    # minus what it costs. Crude, and only deciding which plans are
    # worth sampling properly.
    scored = []
    for combo in combos:
        if _playable(state, combo):
            scored.append((_quick_score(state, combo), list(combo)))
    scored.sort(key=lambda row: -row[0])
    return [plan for _s, plan in scored[:max_plans]]


def _quick_score(state: BattleState, plan) -> float:
    """One all-hit round, scored on damage landed against gag price.

    Deliberately cheap and deliberately not the real evaluation: it
    decides which plans get sampled, and a plan it ranks badly is never
    looked at again, so it must not be *wrong* -- only rough.
    """
    from .. import data

    probe = state.clone()
    try:
        simulator.apply_party_round(probe, list(plan),
                                    hits=[a is not None for a in plan])
    except (NotImplementedError, ValueError, KeyError):
        return float("-inf")
    landed = sum(max(0, before.hp) - max(0, after.hp)
                 for before, after in zip(state.cogs, probe.cogs))
    killed = sum(1 for before, after in zip(state.cogs, probe.cogs)
                 if not before.status.is_dead and after.status.is_dead)
    price = 0.0
    for track, level, count in _spent(state, probe):
        try:
            limit = data.gag(track, level).max_carry or 1
        except (NotImplementedError, ValueError):
            limit = 1
        price += count * (level + 20.0 / limit)
    lured = sum(1 for before, after in zip(state.cogs, probe.cogs)
                if not before.status.lured and after.status.lured)
    return landed + 120.0 * killed + 25.0 * lured - price


def _playable(state: BattleState, plan) -> bool:
    """Can each toon actually throw what the plan gives them?

    A multiset says what gets thrown, not who throws it, so the same
    gag can land on a toon who has none left -- or twice on a toon
    holding one.
    """
    trapped = set()
    for toon, action in zip(state.toons, plan):
        if action is None:
            continue
        if toon.gag_counts.get((action.track, action.level), 0) <= 0:
            return False
        if toon.track_exp.get(action.track, 0) <= 0:
            return False
        if action.track == Track.TRAP:
            # A cog takes one trap. Two toons trapping the same cog is
            # one wasted gag, and the search should not be spending a
            # plan slot proposing it.
            if action.target_index in trapped:
                return False
            trapped.add(action.target_index)
    return True


def round_reward(objective, laff_lost: int, spent, won: bool,
                 lost: bool) -> float:
    """What one party round was worth.

    The team's laff and the team's gags, priced by the same objective
    the solo search uses, so a party line and a solo line are at least
    denominated in the same units.
    """
    reward = -objective.laff_weight * float(laff_lost)
    for track, level, count in spent:
        reward -= count * objective.gag_price(track, level)
    reward -= objective.turn_cost
    if won:
        reward += objective.win_bonus
    elif lost:
        reward -= objective.loss_penalty
    return reward


def _spent(before: BattleState, after: BattleState):
    out = []
    for old, new in zip(before.toons, after.toons):
        for key, had in old.gag_counts.items():
            used = had - new.gag_counts.get(key, 0)
            if used > 0:
                out.append((key[0], key[1], used))
    return out


def evaluate(state: BattleState, depth: int = 1,
             mode: Mode = Mode.PICKUP,
             model: Optional[TeammateModel] = None,
             objective=None, samples: int = SAMPLES,
             per_track: int = PER_TRACK, max_plans: int = MAX_PLANS,
             rng=random) -> Tuple[float, Optional[Sequence]]:
    """Estimated value of `state`, and the plan that achieves it.

    Returns (value, plan). In pickup mode the plan's first entry is your
    action and the rest are None; in coordinated mode it is the whole
    team's.
    """
    objective = objective or objective_mod.DEFAULT
    if state.is_terminal():
        return 0.0, None
    if depth <= 0:
        return expectimax.heuristic_value(state), None

    best_value, best_plan = float("-inf"), None
    for plan in plans(state, mode, per_track, max_plans):
        total = 0.0
        for _ in range(samples):
            nxt, _healed, _done = party_mod.step(
                state, plan[0], mode=mode, model=model,
                joint=list(plan) if mode is Mode.COORDINATED else None,
                rng=rng)
            laff_lost = sum(
                max(0, before.laff - after.laff)
                for before, after in zip(state.toons, nxt.toons))
            reward = round_reward(
                objective, laff_lost, _spent(state, nxt),
                won=nxt.is_win(),
                lost=nxt.is_terminal() and not nxt.is_win())
            future, _p = evaluate(nxt, depth - 1, mode, model, objective,
                                  samples, per_track, max_plans, rng)
            total += reward + future
        value = total / samples
        if value > best_value:
            best_value, best_plan = value, plan
    if best_plan is None:
        return expectimax.heuristic_value(state), None
    return best_value, best_plan


def best_plan(state: BattleState, **kwargs) -> Optional[Sequence]:
    return evaluate(state, **kwargs)[1]


def describe(plan) -> str:
    if not plan:
        return "(no plan)"
    return ", ".join("sit out" if a is None else a.describe() for a in plan)
