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

    # `None` -- hold this round, spend nothing -- is a real option for a
    # party and has to be offered, because the alternative is forcing a
    # toon with nothing useful to do to waste a gag. It did exactly
    # that: asked a four-toon position where three actions already won
    # the fight, the search had the fourth toon throw Toon-Up at a
    # teammate on FULL LAFF, because a cheap wasted heal was the least
    # bad thing it was allowed to say.
    #
    # No separate "wasted gag" penalty is needed once this exists.
    # `round_reward` already charges `objective.gag_price` for whatever
    # is spent, so a gag that achieves nothing is strictly worse than
    # holding, and the search can now see that. Inventing a waste
    # penalty on top would be double-charging, and would need a number
    # nothing in the game supports.
    #
    # This is NOT the same as `simulator.legal_actions`' pass, which is
    # deliberately offered only when a cog is lured and nothing else is
    # productive -- that narrowness protects the solo search's
    # termination argument. This search is depth-limited and sampled, so
    # it has no such argument to protect.
    per_toon = [candidates(state, i, per_track) + [None]
                for i in range(len(state.toons))]
    if not any(any(a is not None for a in row) for row in per_toon):
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
    # Stratify the slots by which tracks the plan uses, then fill from
    # the best of each stratum, rather than taking a global top-N.
    #
    # This is the same lesson as PER_TRACK, learned again one level up.
    # `_quick_score` plays one round with everything HITTING, so a
    # Trap+Lure plan is scored as though the lure never misses and is
    # paid nothing for the risk. On a maxed four-toon position it ranked
    # every such plan at 1081-1089 and the known-best Sound line at 988,
    # and with a global cut the 60 surviving plans contained 59 Lure+Trap
    # combos and NOT ONE all-Sound plan. The best line was not outranked,
    # it was deleted before it could be sampled.
    #
    # Stratifying does not make `_quick_score` any less optimistic -- it
    # just stops one track family monopolising the shortlist, so the
    # real sampled evaluation gets to see each family's best offering
    # and decide between them on merit.
    strata: Dict[tuple, List] = {}
    for combo in combos:
        if not _playable(state, combo):
            continue
        signature = tuple(sorted({a.track for a in combo if a is not None},
                                 key=lambda t: t.name))
        strata.setdefault(signature, []).append(
            (_quick_score(state, combo), list(combo)))

    for rows in strata.values():
        rows.sort(key=lambda row: -row[0])

    out: List[Sequence[Optional[Action]]] = []
    order = sorted(strata, key=lambda sig: -strata[sig][0][0])
    depth_in_stratum = 0
    while len(out) < max_plans and order:
        progressed = False
        for signature in order:
            rows = strata[signature]
            if depth_in_stratum < len(rows):
                out.append(rows[depth_in_stratum][1])
                progressed = True
                if len(out) >= max_plans:
                    break
        if not progressed:
            break
        depth_in_stratum += 1
    return out


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
    from .. import data

    # Everyone holding is legal but cannot win, and it is the one plan a
    # rollout can spin on. Nothing restocks a pouch, so a round where
    # the whole team passes only feeds the cogs a free turn.
    if all(action is None for action in plan):
        return False

    trapped = set()
    for toon, action in zip(state.toons, plan):
        if action is None:
            continue
        if toon.gag_counts.get((action.track, action.level), 0) <= 0:
            return False
        if toon.track_exp.get(action.track, 0) <= 0:
            return False
        # A cog takes one trap, so a second on the same cog is a wasted
        # gag rather than a strategy.
        #
        # NOTE there is deliberately no matching rule for Lure. There
        # was one, and it was WRONG. [CONFIRMED] TTR wiki (Lure):
        # "Using multiple Lure gags simultaneously increases the
        # accuracy", and the update notes: "Multiple Lure gags of the
        # same type used simultaneously now grant a bonus (20/15/10)%
        # accuracy depending on the gag level discrepancies of the
        # additional Lure gags". Stacking Lure is a real TTR play and
        # the search must be allowed to find it.
        #
        # [TODO] That bonus is not modelled -- see
        # mechanics.MULTI_LURE_ACCURACY_BONUS -- so a stacked Lure is
        # currently searched at single-Lure accuracy and is undervalued.
        # Rejecting it outright was worse: it was unreachable.
        if action.track == Track.TRAP:
            if action.target_index in trapped:
                return False
            trapped.add(action.target_index)

    # Cogs that will be lured by the time Drop resolves: already lured,
    # plus anything this plan's Lures catch. ATTACK_ORDER puts Lure
    # before Drop, so a Drop aimed at one of them is a guaranteed miss.
    lured_after = {i for i, cog in enumerate(state.cogs)
                   if cog.status.lured and not cog.status.is_dead}
    has_lure = has_sound = False
    for action in plan:
        if action is None:
            continue
        if action.track == Track.LURE:
            has_lure = True
            if action.target_index is None:
                lured_after.update(
                    i for i, cog in enumerate(state.cogs)
                    if not cog.status.is_dead)
            else:
                lured_after.add(action.target_index)
        elif action.track == Track.SOUND:
            has_sound = True

    for action in plan:
        if action is None or action.track != Track.DROP:
            continue
        # [CONFIRMED] TTR wiki (Lure): "Drop gags always miss on lured
        # Cogs." The simulator already resolves this correctly; the
        # search was still spending plan slots proposing it, and a
        # verified example had the Drop and the toon doing NOTHING give
        # an identical board.
        if action.target_index is None:
            if all(i in lured_after for i, cog in enumerate(state.cogs)
                   if not cog.status.is_dead):
                return False
        elif action.target_index in lured_after:
            return False

    # [CONFIRMED] TTR wiki (Lure): "Lured Cogs are awakened by Sound
    # gags without a damage bonus." Luring in the same round as Sound
    # therefore buys nothing -- the Sound wakes what the Lure just
    # caught, and does not even collect the lured damage bonus for it.
    # There are niche uses, but the plan is dominated by joining the
    # Sound or throwing an attack gag instead, so it does not earn a
    # slot on a shortlist this narrow.
    if has_lure and has_sound:
        return False

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


# Rounds a rollout will play before giving up and calling the position
# unresolved. A real battle ends well inside this; the cap only stops a
# pathological position (mutual inability to finish) spinning forever.
ROLLOUT_ROUNDS = 12


def rollout_value(state: BattleState, objective, rng,
                  model: Optional[TeammateModel] = None,
                  max_rounds: int = ROLLOUT_ROUNDS) -> float:
    """Value of `state` from playing it out, instead of estimating it.

    WHY THIS EXISTS, AND WHY IT IS THE DEFAULT HERE
    ----------------------------------------------
    `expectimax.heuristic_value` cannot rank party positions. Its
    features pool over the toons, so four maxed pouches pin
    `damage_budget_ratio` at its cap and everything scores near the
    ceiling. Measured over the successor states of three plans on a
    maxed four-toon position, 60 rollouts each:

        2 trap + group lure + group throw   leaf 98.03   87% ended
        2 Foghorn + 2 Aoogah                leaf 98.96   98% ended
        4 Foghorn                           leaf 96.73   95% ended

    A 2.3-point spread across positions differing by eleven points of
    *did you actually win*. At depth 1 that leaf is a constant, so the
    ranking falls entirely to `round_reward` and no continuation is
    visible -- which is fatal for exactly the strategies worth searching
    for, since Lure's whole payoff is in later rounds.

    A rollout cannot saturate, because it does not estimate anything: it
    plays until the battle is over and adds up what happened. The cost
    is that it is noisy and it measures the value of the position *under
    the rollout policy* -- `SensiblePrior`, a guess about people -- not
    under best play. That is a real limitation, but a noisy signal beats
    a constant.

    It also needs no clamping. `fitted.value` is clamped into
    `expectimax._value_bounds` to keep star1 admissible; this search does
    not prune, so there is nothing to keep admissible and nothing is
    given up by letting the number run past +/-100.
    """
    current = state
    total = 0.0
    for _ in range(max_rounds):
        if current.is_terminal():
            break
        mine = None
        if current.active_toons():
            mine = (model or party_mod.DEFAULT_MODEL).sample(current, 0, rng)
        nxt, _healed, _done = party_mod.step(
            current, mine, mode=Mode.PICKUP, model=model, rng=rng)
        laff_lost = sum(max(0, before.laff - after.laff)
                        for before, after in zip(current.toons, nxt.toons))
        total += round_reward(
            objective, laff_lost, _spent(current, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win())
        current = nxt
    return total


def evaluate(state: BattleState, depth: int = 1,
             mode: Mode = Mode.PICKUP,
             model: Optional[TeammateModel] = None,
             objective=None, samples: int = SAMPLES,
             per_track: int = PER_TRACK, max_plans: int = MAX_PLANS,
             leaf: str = "rollout",
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
        if leaf == "rollout":
            return rollout_value(state, objective, rng, model), None
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
                                  samples, per_track, max_plans, leaf, rng)
            total += reward + future
        value = total / samples
        if value > best_value:
            best_value, best_plan = value, plan
    if best_plan is None:
        if leaf == "rollout":
            return rollout_value(state, objective, rng, model), None
        return expectimax.heuristic_value(state), None
    return best_value, best_plan


def best_plan(state: BattleState, **kwargs) -> Optional[Sequence]:
    return evaluate(state, **kwargs)[1]


def describe(plan) -> str:
    if not plan:
        return "(no plan)"
    return ", ".join("sit out" if a is None else a.describe() for a in plan)
