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

# How many candidate plans in each track family get a simulated
# `_quick_score`. Everything past this is dropped unscored -- see
# `plans`. Scoring every playable combo was 28% of the search and its
# results were almost entirely discarded by the truncation.
SCORE_BUDGET = 40

# How many of a toon's candidate actions get a simulated `_greedy_score`
# during a rollout. The rest are ranked by arithmetic alone -- see
# `greedy_plan`.
#
# Swept on the battered position. Rollout quality came out at 74.88 for
# EVERY value from 1 to 6, and search values stayed inside their own
# seed-to-seed spread, while the cost fell steadily:
#
#     shortlist   rollout quality   search    time
#             1             74.88   +91.84   3.51s
#             2             74.88   +91.49   4.12s
#             4             74.88   +91.53   5.25s
#             6             74.88   +91.32   6.30s
#
# Measured separately, `_cheap_score`'s pick agrees with the
# simulation's on 288 of 328 decisions (88%). So the simulation is
# mostly confirming the arithmetic, and 2 keeps a second opinion for the
# 12% at a fifth off the cost.
#
# NOT dropped to 1, and checking that on more positions is what settled
# it. The flat 74.88 above was an artefact of a position where the
# shortlist never changes the plan at all. Across four positions, with
# how often the plan differs between k=1 and k=4:
#
#     position           plans differ    k=1     k=2     k=4     k=6
#     maxed vs 4 big            0/6    87.17   87.17   87.17   87.17
#     midgame vs 3              9/14   75.35   74.49   74.49   74.49
#     weak vs 2 (long)          0/17   88.35   88.35   88.35   88.35
#     mixed cog hp              5/5    91.88   93.42   93.42   93.42
#
# k >= 2 is identical everywhere, so nothing above 2 is worth paying
# for. But k=1 loses 1.54 on the mixed-hp position, where the plan
# differs every single time -- uneven cog health is exactly where
# choosing between two similar-damage options matters, and where the
# arithmetic that cannot see knockback or trap triggers goes wrong.
#
# So the simulation earns its keep, on the positions that discriminate,
# and one position showing it flat was not evidence that it does not.
GREEDY_SHORTLIST = 2


def candidates(state: BattleState, toon_index: int,
               per_track: int = PER_TRACK) -> List[Action]:
    """A few actions per track for one toon, ranked within each track.

    Per *track* rather than overall, so no track is squeezed out by
    another being generally stronger -- Sound gets the same slots as
    Drop. Ranking inside a track uses `SensiblePrior`, which is a guess
    about play and only decides which levels of a track make the
    shortlist, never which track wins.

    Letting `greedy_plan` supply `_cheap_score` as the within-track
    ranking instead was tried and reverted. It saved rotating the state
    and running the prior -- 9.6s to 8.8s on the profile -- and then
    bought NOTHING on the wall clock of either study position, while
    dropping the battered position's depth-1 values by about 0.4. The
    prior orders the levels of a track better than damage arithmetic
    does, which is exactly the job it is still here for.
    """
    rotated = party_mod._as_actor(state, toon_index)
    prior = party_mod.SensiblePrior()
    order = {(a.track, a.level, a.target_index): i
             for i, a in enumerate(prior._candidates(rotated, 0))}
    key = lambda a: order.get((a.track, a.level, a.target_index), 10 ** 6)

    by_track: Dict[Track, List[Action]] = {}
    for action in simulator.legal_actions(rotated):
        if action.is_pass:
            continue
        by_track.setdefault(action.track, []).append(action)

    out: List[Action] = []
    for actions in by_track.values():
        actions.sort(key=key)
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
    # This handles the gag that achieves NOTHING: `round_reward` already
    # charges `gag_price` for what is spent, so once holding is on the
    # menu a useless gag is strictly worse than it, with no extra
    # penalty needed.
    #
    # It does NOT handle the gag that achieves something and throws most
    # of it away -- a Railroad into a five-hit-point cog kills it and
    # discards the rest, and holding is plainly worse than that. That is
    # a separate charge; see `waste_penalty`.
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
    # Collect first, score second, and cap how many combos in each
    # stratum are worth a simulated `_quick_score`. Scoring every
    # playable combo meant ~50k round simulations on a real position,
    # which was 28% of the whole search -- and all but a handful of
    # those scores were thrown away by the truncation below anyway.
    #
    # The cap is per stratum, not global, for the same reason the
    # truncation is: a global budget would be spent entirely on whichever
    # family the enumeration happens to reach first. Within a stratum the
    # order is the prior-ranked candidate order, so the first entries are
    # the plausible ones rather than an arbitrary slice.
    # Keep the arithmetically best SCORE_BUDGET per stratum, NOT the
    # first ones enumerated.
    #
    # Taking the first N was a lexicographic prefix, which is the same
    # bug as the one `max_plans` had, reintroduced one level down while
    # optimising -- and it deleted the same line. On the maxed position
    # `combinations_with_replacement` reaches every combo built from
    # Sound 7 before it reaches [Foghorn, Foghorn, Aoogah, Aoogah], so
    # the Sound stratum's budget was spent entirely on level 7 plans and
    # the known-best line was never scored. It was not outranked; it was
    # not a candidate, and no objective term could reach it -- a
    # `rare_gag_premium` that correctly took the level 7 plan from +92.70
    # to +72.70 changed the chosen plan not at all.
    #
    # `_cheap_score` is pure arithmetic, so ranking every combo with it
    # costs no simulations, and only the survivors get a simulated
    # `_quick_score`.
    cheap: Dict[tuple, List] = {}
    for combo in combos:
        if not _playable(state, combo):
            continue
        signature = tuple(sorted({a.track for a in combo if a is not None},
                                 key=lambda t: t.name))
        rough = sum(_cheap_score(state, i, a)
                    for i, a in enumerate(combo) if a is not None)
        cheap.setdefault(signature, []).append((rough, list(combo)))

    buckets: Dict[tuple, List] = {}
    for signature, rows in cheap.items():
        rows.sort(key=lambda row: -row[0])
        buckets[signature] = [combo for _r, combo in rows[:SCORE_BUDGET]]

    strata: Dict[tuple, List] = {}
    for signature, bucket in buckets.items():
        rows = [(_quick_score(state, combo), combo) for combo in bucket]
        rows.sort(key=lambda row: -row[0])
        strata[signature] = rows

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

    # ... unless something in the same round WAKES the cog first.
    # [CONFIRMED] TTR wiki (Lure): "Lured Cogs are awakened by Sound
    # gags", and ATTACK_ORDER puts SOUND before DROP -- so a Sound this
    # round un-lures the cog in time for the Drop to land on it. Every
    # Sound gag is a group gag, so one anywhere in the plan covers every
    # cog.
    #
    # That makes Sound-then-Drop a real play rather than a wasted gag,
    # and this rule must not ban it. It is a gamble, not a guarantee --
    # a Sound that misses leaves the cog lured and the Drop still misses
    # -- but `_playable` exists to refuse things that CANNOT work, not
    # things that might not.
    if not has_sound:
        for action in plan:
            if action is None or action.track != Track.DROP:
                continue
            # [CONFIRMED] TTR wiki (Lure): "Drop gags always miss on
            # lured Cogs." The simulator already resolves this
            # correctly; the search was still spending plan slots
            # proposing it, and a verified example had the Drop and the
            # toon doing NOTHING give an identical board.
            if action.target_index is None:
                if all(i in lured_after for i, cog in enumerate(state.cogs)
                       if not cog.status.is_dead):
                    return False
            elif action.target_index in lured_after:
                return False

    # A heal with nobody to heal. [CONFIRMED] TTR wiki (Toon-Up):
    # "Toons cannot use Toon-Up gags to restore their own laff" -- so if
    # every OTHER standing toon is already at full laff, the gag is spent
    # for literally nothing, exactly like a Drop on a lured cog.
    #
    # This is what kept a healthy party opening with Toon-Up, and it
    # survived three fixes aimed at it. Holding was added, which made a
    # no-op heal merely equal to holding rather than worse; the
    # heal/damage clamp was corrected, which does not bite when nobody
    # is hurt; and the heal was redirected to teammates, which on a
    # full-laff party is one no-op replacing another -- the position's
    # value did not move by so much as 0.01 across any of them. A no-op
    # has to be refused outright, not merely priced.
    for index, action in enumerate(plan):
        if action is None or action.track != Track.TOON_UP:
            continue
        healable = [other for i, other in enumerate(state.toons)
                    if i != index and other.laff > 0
                    and other.laff < other.max_laff]
        if not healable:
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


def plan_waste(state: BattleState, plan) -> Tuple[float, float]:
    """(damage thrown away, gag price of the plan).

    Waste is damage aimed at hit points that are not there -- a Railroad
    into a five-hit-point cog kills it and discards the rest. The
    objective charged nothing for that: a gag cost its price whether it
    was needed or wasted, so nothing distinguished spending a level 7
    because it was the only thing that would kill the cog from spending
    it because it was in the pouch.

    Straight algebra: for each cog, the damage aimed at it minus the hit
    points it has, when that is positive. A cog's hp clamps at zero, so
    the excess is not readable from the resolved board -- but it does
    not need to be resolved at all, because both quantities are known
    before the round.

    The damage has to be totalled per (track, target) first rather than
    per gag, because `calc_hp_bonus` gives same-track gags on one cog a
    combo bonus on their combined total. Summing gags independently
    would understate the damage and so understate the waste.

    Computed from the plan and assuming it lands, so it measures the
    *choice* rather than the dice. Throwing a Railroad at a nearly-dead
    cog is the same decision whether or not it hits.
    """
    from .. import data
    from .. import mechanics

    live = [(i, cog) for i, cog in enumerate(state.cogs)
            if not cog.status.is_dead]
    if not live:
        return 0.0, 0.0
    toughest = max(cog.hp for _i, cog in live)

    # Single-target gags are grouped per (track, target); group gags are
    # grouped per track, and their waste is counted ONCE against the
    # toughest cog rather than per cog.
    #
    # THIS DISTINCTION IS THE WHOLE CORRECTNESS OF THE MEASURE, and the
    # first version got it wrong. A group gag's damage is uniform by
    # construction: the overkill it does to a weak cog is not a choice
    # anyone made, it is what a group gag IS. Charging for it per cog
    # meant 2 Foghorn + 2 Aoogah -- the known-best line on the maxed
    # position, sized within 3 damage of the toughest cog -- was billed
    # for 84 wasted damage and priced out of its own win.
    #
    # What a player actually chooses about a group gag is how big a one
    # to bring, and the binding constraint is the toughest cog it has to
    # kill. So the waste is `dealt - toughest`, once. 2 Foghorn + 2
    # Aoogah (159 against 156) now wastes 3; 4 Foghorn (240) wastes 84;
    # 4 Opera Singer (432) wastes 276. Which is the real ranking.
    singles: Dict[tuple, List[int]] = {}
    group: Dict[Track, List[int]] = {}
    for toon, action in zip(state.toons, plan):
        if action is None or action.track in (Track.TOON_UP, Track.LURE,
                                              Track.TRAP):
            continue
        try:
            dmg = mechanics.calc_toon_damage(
                action.track, action.level,
                organic=toon.is_organic(action.track))
        except (NotImplementedError, ValueError):
            continue
        if action.target_index is None:
            slot = group.setdefault(action.track, [0, 0])
        else:
            slot = singles.setdefault((action.track, action.target_index),
                                      [0, 0])
        slot[0] += dmg
        slot[1] += 1

    raw = 0
    useful = 0
    for (_track, index), (damage, count) in singles.items():
        total = damage + mechanics.calc_hp_bonus(damage, count)
        raw += total
        if 0 <= index < len(state.cogs):
            useful += min(total, max(0, state.cogs[index].hp))
    for _track, (damage, count) in group.items():
        total = damage + mechanics.calc_hp_bonus(damage, count)
        raw += total
        useful += min(total, toughest)

    price = 0.0
    for toon, action in zip(state.toons, plan):
        if action is None:
            continue
        try:
            limit = data.gag(action.track, action.level).max_carry or 1
        except (NotImplementedError, ValueError):
            limit = 1
        price += 1.0 / limit

    return max(0.0, float(raw - useful)), price


def waste_penalty(objective, state: BattleState, plan) -> float:
    """What this plan is charged for damage it throws away.

    Scaled by the *scarcity* of what was spent, which is the whole
    point: wasting a level 7 (one per pouch) has to hurt far more than
    wasting a level 1 (thirty per pouch), and a flat per-damage charge
    would treat them alike.

    The shape is `weight x wasted_fraction x scarcity`, so a plan whose
    damage is all needed pays nothing however dear its gags -- which is
    exactly the "unless it is the only option" case. A level 7 that is
    the only gag that kills the cog wastes little and is barely touched;
    the same gag into a nearly-dead cog is charged nearly in full.

    `waste_weight` is a CHOSEN number, like every other weight in
    `objective` -- nothing in the game states it. It is not a [TODO]
    standing in for a fact, it is a preference about how to play.
    """
    weight = getattr(objective, "waste_weight", 0.0)
    if not weight:
        return 0.0
    wasted, scarcity = plan_waste(state, plan)
    if wasted <= 0.0 or scarcity <= 0.0:
        return 0.0
    total = wasted + sum(
        cog.hp for cog in state.cogs if not cog.status.is_dead)
    fraction = wasted / total if total > 0 else 0.0

    return weight * fraction * scarcity


def round_reward(objective, laff_lost: int, spent, won: bool,
                 lost: bool, toons_lost: int = 0) -> float:
    """What one party round was worth.

    The team's laff and the team's gags, priced by the same objective
    the solo search uses, so a party line and a solo line are at least
    denominated in the same units.
    """
    from ..data.gags import POUCH_EXEMPT_LEVEL

    reward = -objective.laff_weight * float(laff_lost)
    for track, level, count in spent:
        reward -= count * objective.gag_price(track, level)
        if level >= POUCH_EXEMPT_LEVEL:
            reward -= count * getattr(objective, "rare_gag_premium", 0.0)
    # A toon going sad is not just the laff they had left -- it is a
    # combatant, their pouch, and every action they would have taken.
    reward -= toons_lost * getattr(objective, "toon_lost_penalty", 0.0)
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


def greedy_plan(state: BattleState, objective) -> List[Optional[Action]]:
    """A decent action for every toon, chosen rather than sampled.

    WHY THIS IS NOT `SensiblePrior`, WHICH IT USED TO BE
    ----------------------------------------------------
    `SensiblePrior` is a model of *people* -- what a stranger is likely
    to throw. That is exactly right for one job and wrong for another,
    and the two were sharing a policy:

      * PICKUP teammates -- you genuinely cannot control them, so the
        right object is a distribution over what they might do, and no
        amount of cleverness replaces it. `SensiblePrior` keeps this job.

      * The ROLLOUT continuation -- here nothing is being predicted. The
        rollout exists to *estimate the value of a position*, and the
        value of a position is what it is worth under good play, not
        under average play. Estimating it with a model of an average
        stranger systematically undervalues any line whose payoff needs
        follow-through -- which is every Lure strategy there is, and is
        the mechanism behind "no Lure strategy ever appears" in
        docs/party-strategy.md. The plan was scored on a continuation
        that would not carry it out.

    So this is deliberately not a people-model. It takes the best action
    it can see one round ahead under the *objective the search is
    actually optimising*: damage that lands somewhere it is needed, cogs
    killed, minus what it costs and what it throws away. Greedy and
    myopic, and still a much better proxy for "played well from here"
    than a guess about strangers.

    It is not free. A rollout now costs a scan of each toon's candidate
    list per round instead of one weighted draw, which is the reason
    `ROLLOUT_ROUNDS` stays modest.
    """
    plan: List[Optional[Action]] = [None] * len(state.toons)
    working = state.clone()
    for index, toon in enumerate(state.toons):
        if toon.laff <= 0:
            continue
        # Rank every candidate by arithmetic, then SIMULATE only the
        # best few. This was simulating a full round for every candidate
        # of every toon on every round of every rollout -- 117k
        # simulations on one depth-1 search, 46% of its runtime -- to
        # pick one action. The arithmetic gets the shortlist to roughly
        # the right handful; the simulation, which knows about knockback,
        # trap triggers and combo bonuses, still decides between them.
        # Memoised because an action can be scored more than once while
        # the pool is sorted.
        seen: Dict[tuple, float] = {}

        def score_of(action, _cache=seen, _index=index, _state=working):
            key = (action.track, action.level, action.target_index)
            if key not in _cache:
                _cache[key] = _cheap_score(_state, _index, action)
            return _cache[key]

        pool = candidates(working, index, per_track=3)
        pool.sort(key=lambda a: -score_of(a))
        best, best_score = None, 0.0     # 0.0 => holding is the floor
        for action in pool[:GREEDY_SHORTLIST]:
            trial = [None] * len(state.toons)
            trial[index] = action
            score = _greedy_score(working, trial, objective)
            if score > best_score:
                best, best_score = action, score
        plan[index] = best
        if best is not None:
            # Later toons see the earlier ones' choices, so the team does
            # not pile four gags onto a cog the first one already killed.
            try:
                simulator.apply_party_round(
                    working, [a if i == index else None
                              for i, a in enumerate(plan)],
                    hits=[i == index and a is not None
                          for i, a in enumerate(plan)])
            except (NotImplementedError, ValueError, KeyError):
                pass
    return plan


def _cheap_score(state: BattleState, index: int, action: Action) -> float:
    """Rough worth of one action, by arithmetic and no simulation.

    Only ever used to pick which candidates deserve a real
    `_greedy_score`, so it may be crude -- but it must not be
    systematically blind to a track, or that track never reaches the
    shortlist. Hence Lure and Trap get explicit credit instead of
    scoring zero for dealing no damage, which is the mistake that would
    quietly delete the Lure strategies again.
    """
    from .. import data
    from .. import mechanics

    live = [cog for cog in state.cogs if not cog.status.is_dead]
    if not live:
        return 0.0
    toon = state.toons[index]

    try:
        limit = data.gag(action.track, action.level).max_carry or 1
    except (NotImplementedError, ValueError):
        limit = 1
    price = 20.0 / limit + action.level

    if action.track == Track.TOON_UP:
        missing = sum(other.max_laff - other.laff
                      for i, other in enumerate(state.toons)
                      if i != index and other.laff > 0)
        return min(missing, 40.0) - price
    if action.track == Track.LURE:
        caught = (len(live) if action.target_index is None
                  else 1) if any(not c.status.lured for c in live) else 0
        return 25.0 * caught - price
    if action.track == Track.TRAP:
        return 20.0 - price

    try:
        damage = mechanics.calc_toon_damage(
            action.track, action.level, organic=toon.is_organic(action.track))
    except (NotImplementedError, ValueError):
        return float("-inf")

    targets = (live if action.target_index is None
               else [state.cogs[action.target_index]]
               if 0 <= action.target_index < len(state.cogs) else [])
    score = 0.0
    for cog in targets:
        if action.track == Track.DROP and cog.status.lured:
            continue        # always misses -- see `_playable`
        hit = damage
        if action.track in mechanics.KB_BONUS_TRACKS and cog.status.lured:
            hit += int(damage * mechanics.KB_BONUS_MULTIPLIER)
        score += min(hit, max(0, cog.hp))
        if hit >= cog.hp:
            score += 60.0
    return score - price


def _greedy_score(state: BattleState, trial, objective) -> float:
    """One action's worth: useful damage and kills, less cost and waste."""
    wasted, scarcity = plan_waste(state, trial)
    probe = state.clone()
    try:
        simulator.apply_party_round(
            probe, list(trial), hits=[a is not None for a in trial])
    except (NotImplementedError, ValueError, KeyError):
        return float("-inf")
    landed = sum(before.hp - max(0, after.hp)
                 for before, after in zip(state.cogs, probe.cogs))
    killed = sum(1 for before, after in zip(state.cogs, probe.cogs)
                 if not before.status.is_dead and after.status.is_dead)
    lured = sum(1 for before, after in zip(state.cogs, probe.cogs)
                if not before.status.lured and after.status.lured
                and not after.status.is_dead)
    # Price the action directly. This called `_spent`, which diffs every
    # toon's whole gag dictionary against the probe's -- forty-odd
    # lookups to rediscover a fact the caller already had, on a trial
    # where exactly one toon throws exactly one gag.
    price = 0.0
    for action in trial:
        if action is not None:
            price += objective.gag_price(action.track, action.level)
    return (landed + 60.0 * killed + 20.0 * lured
            - 10.0 * price - 0.25 * wasted * scarcity)


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
    the rollout policy* (`greedy_plan`) rather than under best play.
    That is a real limitation, but a noisy signal beats a constant.

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
        joint = greedy_plan(current, objective)
        nxt, _healed, _done = party_mod.step(
            current, joint[0], mode=Mode.COORDINATED, joint=joint, rng=rng)
        laff_lost = sum(max(0, before.laff - after.laff)
                        for before, after in zip(current.toons, nxt.toons))
        total += round_reward(
            objective, laff_lost, _spent(current, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win(),
            toons_lost=sum(1 for b, a in zip(current.toons, nxt.toons)
                           if b.laff > 0 and a.laff <= 0))
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
        # Charged once per plan, not per sample: waste is a property of
        # the choice, not of how the dice fell.
        waste = waste_penalty(objective, state, plan)
        total = 0.0
        for _ in range(samples):
            nxt, _healed, _done = party_mod.step(
                state, plan[0], mode=mode, model=model,
                joint=list(plan) if mode is Mode.COORDINATED else None,
                rng=rng)
            laff_lost = sum(
                max(0, before.laff - after.laff)
                for before, after in zip(state.toons, nxt.toons))
            went_sad = sum(1 for before, after in zip(state.toons, nxt.toons)
                           if before.laff > 0 and after.laff <= 0)
            reward = round_reward(
                objective, laff_lost, _spent(state, nxt),
                won=nxt.is_win(),
                lost=nxt.is_terminal() and not nxt.is_win(),
                toons_lost=went_sad)
            future, _p = evaluate(nxt, depth - 1, mode, model, objective,
                                  samples, per_track, max_plans, leaf, rng)
            total += reward + future
        value = total / samples - waste
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
