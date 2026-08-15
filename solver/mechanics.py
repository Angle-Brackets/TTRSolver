"""
Core mechanics functions, built directly off the accuracy/damage formulas
documented in QED1224/Toontown-Resources. See data/ for confidence tags
on the underlying numbers.

SOLO-TOON SIMPLIFICATIONS (read before extending to multi-toon parties):

1. PrevHits ("stun") bonus is mostly a same-ROUND bonus between different
   toons' (or a multi-target attack's) sequential hits. A solo toon takes
   one action per round, so that half has nothing to inherit from and
   stays 0 until there are other toons.

   TRAP IS THE EXCEPTION, and this said otherwise for a long time. The
   wiki is explicit that Lure's PrevHits from Trap "remain across
   multiple rounds, as long as Trap is present", so a solo toon that
   traps and then lures collects +10 -- see calc_prev_hits_bonus. That
   is the commonest solo line there is and it was being rolled ten
   points short of what the game gives it.

   The OTHER half of the `bonus` term, luredRatio, is not a same-round
   effect and does apply to a solo toon -- see calc_lured_ratio_bonus().

2. Trap+Lure combo damage (the classic burst combo) is NOT the same thing
   as the PrevHits bonus above. It's a persistent, cross-round trigger:
   trap sits on a cog until a Lure knocks that cog onto it. That part IS
   modeled here (see simulator._resolve_toon_action's LURE branch).

3. Cog target selection is trivial for a single toon (there's only one
   toon to target), so pick_cog_target() below is a stub that always
   returns the lone toon. The proportional-damage weighting algorithm
   from the source doc is noted in a comment for when you add toons.
"""
import math
import random
from typing import Tuple

from . import data
from .state import Track, CogState, ToonState


# ---------------------------------------------------------------------
# Toon attack accuracy
# ---------------------------------------------------------------------

def calc_prop_acc(track: Track, level: int, lure_tree_planted: bool = False) -> int:
    """propAcc for a gag, organic or not. Only Lure's accuracy changes when
    organic, which Gag.prop_accuracy already knows -- no special-case here."""
    return data.gag(track, level).prop_accuracy(organic=lure_tree_planted)


def calc_track_exp(toon: ToonState, track: Track) -> int:
    """trackExp = (toon's training level in track - 1) * 10, halved for Toon-Up.
    Toon-Up halving per [CONFIRMED] source note."""
    trained_level = toon.track_exp.get(track, 0)
    if trained_level <= 0:
        return 0
    val = (trained_level - 1) * 10
    if track == Track.TOON_UP:
        val = val // 2
    return val


def cog_rank(cog: CogState) -> int:
    """The cog's rank (a.k.a. tier) on its department's corporate ladder,
    1-8. [CONFIRMED] TTR wiki: rank is position on the ladder, and the
    lowest level a cog can appear at equals that position -- Flunky is
    tier 1 and starts at level 1, Pencil Pusher tier 2 at level 2, and so
    on for all 32 cogs. So the first entry of its "levels" list is its
    rank, with no extra table needed.
    """
    return data.cog(cog.department, cog.cog_type).rank


def calc_tgt_def(track: Track, target_cogs) -> int:
    """For group attacks, uses the strongest (highest-level) cog's defense,
    since every active cog is in the target list. [CONFIRMED]

    tgtDef depends on the cog's RANK as well as its level: the wiki's table
    marks levels 4 and 5 with a second value used by rank-1 cogs. This
    previously always took the rank-1 branch, which understated the defense
    of every non-rank-1 cog at those two levels by 3 and 5 points -- a
    level-4 Micromanager was scored -12 instead of -15.
    """
    if not target_cogs:
        return 0
    if track == Track.TOON_UP:
        return 0
    strongest = max(target_cogs, key=lambda c: c.level)
    return data.tgt_def(strongest.level, cog_rank(strongest))


# [CONFIRMED] TTR wiki (Accuracy#PrevHits): "PrevHits is incremented by
# the number of previous hits x 25 (excluding Trap) on the target(s) in
# the current round, with a bonus of +75 being possible with three prior
# hits."
PREV_HIT_STEP = 25
PREV_HIT_MAX = 75


def calc_same_round_prev_hits(prior_hits: int) -> int:
    """The stun bonus from attacks that already landed this round.

    Zero for a solo toon, who acts once and has nothing to inherit from;
    this is the half of PrevHits that only a party can earn.

    `prior_hits` counts hits on this attack's target(s) earlier in the
    same round that satisfy the wiki's conditions, which the caller
    checks because they depend on tracks and targets rather than on a
    number: the previous attack must have hit, must have been a
    *different* track, and either attack must affect the group or both
    must share a target. Trap is excluded from the count.
    """
    return min(PREV_HIT_MAX, max(0, prior_hits) * PREV_HIT_STEP)


def calc_prev_hits_bonus(track: Track, level: int = 0, all_cogs=None) -> int:
    """PrevHits half of the `bonus` term.

    THE SOLO CASE IS NOT ALWAYS ZERO, WHICH THIS SAID FOR A LONG TIME.
    The same-round part is: a solo toon acts once per round, so there is
    no previous attack this round to inherit a bonus from, and that half
    stays 0 until there are other toons.

    But Trap's contribution is explicitly cross-round. [CONFIRMED] TTR
    wiki (Accuracy#PrevHits):

      1. "The first Trap gag that is placed grants +10 to PrevHits, but
         only for Lure."
      2. "Further Trap gag placements grant an additional +5 to a group
         Lure gag."
      3. "The PrevHits for Lure remain across multiple rounds, as long as
         Trap is present."

    Point 3 is the one that makes this a solo rule. A toon who traps in
    one round and lures in the next is the commonest solo line there is
    -- it is the line `simulator.legal_actions` offers the pass action
    for -- and it was being rolled at 10 points less accuracy than the
    game gives it.

    Rule 4, "+50 PrevHits when Trap is activated by Lure", is left at 0:
    it is a bonus to attacks landing *after* the trap goes off in the
    same round, and a solo toon has none.

    `all_cogs` is every cog in the battle; without it there is no trap
    state to read and this returns 0, matching the old behaviour for
    callers that pass nothing.
    """
    if track != Track.LURE or not all_cogs:
        return 0
    traps = sum(1 for cog in all_cogs
                if not cog.status.is_dead and cog.status.trapped)
    if not traps:
        return 0
    bonus = data.TRAP_LURE_ACCURACY_BONUS
    if level and data.gag(Track.LURE, level).group:
        # Rule 2 is specific to group Lure; a single-target Lure gets the
        # first trap's +10 and nothing for the rest.
        bonus += data.TRAP_EXTRA_LURE_ACCURACY_BONUS * (traps - 1)
    return bonus


def gets_lured_ratio(track: Track, level: int) -> bool:
    """Which gags receive the luredRatio bonus. [CONFIRMED] TTR wiki
    (Accuracy#luredRatio): "given to all Sound gags, and level 7 Throw or
    Squirt gags when there is a mixed set of lured and un-lured Cogs".

    Narrower than the strategy guide's rule, which was "everything except
    Lure, Toon-Up and Drop" -- that wrongly handed the bonus to ordinary
    single-target Throw/Squirt and to Trap.
    """
    if track == Track.SOUND:
        return True
    return level == 7 and track in (Track.THROW, Track.SQUIRT)


def calc_lured_ratio_bonus(track: Track, level: int, all_cogs) -> int:
    """luredRatio half of the `bonus` term. [CONFIRMED]:

        luredRatio = ([number of cogs lured] / [total cogs]) * 100

    Unlike PrevHits this is NOT a same-round, multi-toon effect -- it is
    read off the battle's current lure state, so a solo toon gets it too.

    `all_cogs` is every cog in the battle, not just this attack's targets:
    the ratio's denominator is the whole battle. Dead cogs are excluded
    from both halves (they have left the battle).

    Rounding: the source expresses this as a percentage and adds it to
    atkAcc; it does not say how a non-integral ratio (e.g. 1 of 3 cogs
    lured -> 33.33) is rounded. We truncate. Only ever a 1-point
    difference, and only for cog counts that don't divide 100.
    """
    if not gets_lured_ratio(track, level):
        return 0
    if not all_cogs:
        return 0
    active = [c for c in all_cogs if not c.status.is_dead]
    if not active:
        return 0
    lured = sum(1 for c in active if c.status.lured)
    return int(lured * 100 / len(active))


def calc_bonus(track: Track, level: int, all_cogs=None) -> int:
    """The full `bonus` term of atkAcc = propAcc + trackExp + tgtDef + bonus.

    `all_cogs` is every cog in the battle. It defaults to None, meaning
    "lure state not supplied", which drops the luredRatio half and leaves
    the old always-0 behaviour for callers that don't pass battle state.
    Deliberately NOT defaulted to the attack's targets: for a single-target
    attack that would compute the ratio over one cog and read 100.
    """
    return (calc_prev_hits_bonus(track, level, all_cogs)
            + calc_lured_ratio_bonus(track, level, all_cogs))


def lure_hit_override(track: Track, target_cogs):
    """Accuracy forced by the targets' lure state, or None for "roll it".
    [CONFIRMED] TTR wiki (Lure):

      - Throw and Squirt get "a 50% damage bonus on guaranteed hits"
        against lured cogs -> 100.
      - "Drop gags always miss on lured Cogs" -> 0.

    Only applies when EVERY target is lured. The wiki's own trivia is
    explicit that a mixed set of lured and un-lured cogs is not guaranteed
    to hit, so a group gag over a partly-lured battle rolls normally.
    """
    if not target_cogs or not all(c.status.lured for c in target_cogs):
        return None
    if track in (Track.THROW, Track.SQUIRT):
        return 100
    if track == Track.DROP:
        return 0
    return None


def calc_toon_accuracy(track: Track, level: int, toon: ToonState,
                        target_cogs, lure_tree_planted: bool = False,
                        all_cogs=None) -> int:
    """Full atkAcc, bonus included, capped at 95. This is the value the
    hit/miss roll uses. For the wake-up input, use
    lure_accuracy_before_bonus() instead -- it is a different number.

    Pass `all_cogs=state.cogs` to get the luredRatio accuracy bonus; without
    it the bonus term is 0, as it was before luredRatio was modeled."""
    if track == Track.TRAP:
        return 100  # [CONFIRMED] trap is always-hit

    forced = lure_hit_override(track, target_cogs)
    if forced is not None:
        return forced

    acc = (calc_prop_acc(track, level, lure_tree_planted)
           + calc_track_exp(toon, track)
           + calc_tgt_def(track, target_cogs)
           + calc_bonus(track, level, all_cogs))

    # [CONFIRMED] TTR wiki: "if atkAcc falls below 5%, it is automatically
    # increased to 5%". The exemption is Drop against a lured cog, which
    # always misses -- and that case has already returned 0 above.
    acc = max(acc, data.ACCURACY_FLOOR)

    # The 95 cap became a SOFT cap in 4.3.3: stun/Lure/Trap bonuses and
    # Toons Hit "can slightly push the final accuracy value higher". The
    # wiki never quantifies "slightly" or gives a replacement ceiling, so
    # there is nothing to model -- this stays a hard cap, which is the
    # pre-4.3.3 rule and the closest defensible approximation. See
    # data.ACCURACY_CAP_IS_SOFT; revisit if a number ever surfaces.
    return min(acc, data.ACCURACY_CAP)


def accuracy_roll(rng=random) -> int:
    """One accuracy die, 0-99.

    Separate from `roll_hit` because a roll is sometimes SHARED. Gags of
    the same track aimed at the same cog resolve on one roll, and a
    group gag rolls once for every target -- so the caller needs the
    number, not just the verdict. `roll_hit` stays for the solo path,
    where one gag means one roll either way.

    `rng` defaults to the global module so every existing caller is
    unchanged. Pass one to make a search reproducible -- see the note on
    `party_search.evaluate`.
    """
    return rng.randint(0, 99)


def roll_hit(accuracy_pct: int, rng=random) -> bool:
    return rng.randint(0, 99) < accuracy_pct


# ---------------------------------------------------------------------
# Toon attack damage
# ---------------------------------------------------------------------

# Where in a gag's damage range a toon is assumed to sit: 1.0 is fully
# trained, 0.0 is the bottom of the range. The real game derives this
# from earned experience against per-gag minE/maxE thresholds that are
# not transcribed, so it is a single global stand-in.
#
# It is a knob so a search can be run against a PESSIMISTIC assumption
# and the answers compared. That comparison is the only way to ask "how
# much does this recommendation depend on everyone actually being
# maxed", which is the question behind a player's preference for a wide
# damage margin -- see the note on `objective.risk_aversion`. Nothing
# about outcome variance can answer it, because at a fixed fraction the
# damage is deterministic.
DAMAGE_TRAINED_FRACTION = 1.0


def calc_toon_damage(track: Track, level: int,
                      trained_fraction: float = None,
                      organic: bool = False) -> int:
    """Damage dealt by a gag. The real game ties this deterministically to
    the toon's earned experience in the track (see gag_damage_from_exp
    below) -- but we don't have the minE/maxE thresholds transcribed yet.
    As an interim approximation, trained_fraction (0=min dmg, 1=max dmg)
    linearly interpolates the gag's range. Default 1.0 assumes a fully
    maxed track, which is the common "solved" build anyway.
    """
    if trained_fraction is None:
        trained_fraction = DAMAGE_TRAINED_FRACTION
    return data.gag(track, level).damage_at(trained_fraction, organic)


def calc_toon_heal(level: int, hit: bool = True,
                    trained_fraction: float = 1.0, organic: bool = False) -> int:
    """Laff restored by a Toon-Up gag.

    [CONFIRMED] TTR wiki: a Toon-Up gag that "misses" still heals 20% of its
    value, rounded up -- unlike every other track, where a miss does
    nothing. Pass hit=False for that case.
    """
    full = data.gag(Track.TOON_UP, level).heal_at(trained_fraction, organic)
    return full if hit else math.ceil(full * data.TOON_UP_MISS_FRACTION)


KB_BONUS_MULTIPLIER = 0.50   # [CONFIRMED] kbBonus = totalDmgs * 0.50
KB_BONUS_TRACKS = (Track.THROW, Track.SQUIRT)   # [CONFIRMED]


def calc_kb_bonus(track: Track, target_lured: bool, total_damage: int) -> float:
    """Lure knockback bonus damage. [CONFIRMED]:

        "kbBonus should have applied in any case in which a lured target
         was attacked with Throw or Squirt."
        kbBonus = totalDmgs * 0.50

    `totalDmgs` is the damage that track dealt to that lured target this
    round -- for a solo toon that is just the one gag's damage.

    Returned unrounded (the source keeps damage as a float and applies
    gag damage, then hpBonus, then kbBonus as separate instances); the
    caller decides how to land it on an integer HP pool.

    NOT modeled: the long-standing kbBonus mis-indexing bug the guide
    documents (bonus applied to the cog at the target's index in a
    differently-ordered list). It needs >1 cog and a specific ordering
    mismatch, is a bug rather than a mechanic, and TTR may have fixed it.
    """
    if not target_lured or track not in KB_BONUS_TRACKS:
        return 0.0
    return total_damage * KB_BONUS_MULTIPLIER


def calc_hp_bonus(total_damage: int, gags_on_target: int = 1) -> int:
    """The same-track damage bonus, for `gags_on_target` gags of one
    track landing on one cog in one round.

    [CONFIRMED] TTR wiki (Gags): "When two or more of the same gag type
    (excluding Lure, Trap, and Toon-Up) are used on a Cog simultaneously,
    a 20% damage bonus applies." The exclusion list is the wiki's; this
    function is only ever called for damage tracks, and callers must not
    call it for Lure or Trap.

    This is the whole reason coordinating a party is worth anything, and
    it returned 0 unconditionally until multi-toon work began. A search
    over the old rules could not see any value in two toons hitting the
    same cog, so it would have rated four toons stacking Throw exactly
    level with four toons hitting four different cogs.

    `gags_on_target` defaults to 1, which is the solo case and yields 0,
    so nothing about solo play changes.

    ROUNDING IS NOT WIKI-CONFIRMED. The wiki says "a 20% damage bonus"
    and does not say how it rounds; `ceil` comes from the QED1224 source
    doc, which describes Toontown Online. It is kept because a bonus has
    to resolve to a whole number of hit points somehow, and ceil is the
    only reading with a source behind it -- but it is the first thing to
    check if party damage ever reads a point low.
    """
    if gags_on_target < 2:
        return 0
    return math.ceil(total_damage * 0.20)


def gag_damage_from_exp(exp: int, max_exp: int, min_exp_for_gag: int,
                         min_dmg: int, max_dmg: int) -> int:
    """[CONFIRMED] formula from source, kept for when real exp thresholds
    are transcribed. Not currently wired into calc_toon_damage.
        expVal    = min(exp, maxE)
        expPerHp  = (maxE - minE + 1) / (maxD - minD + 1)
        damage    = floor((expVal - minE) / expPerHp) + minD
    """
    exp_val = min(exp, max_exp)
    exp_per_hp = (max_exp - min_exp_for_gag + 1) / (max_dmg - min_dmg + 1)
    return math.floor((exp_val - min_exp_for_gag) / exp_per_hp) + min_dmg


# ---------------------------------------------------------------------
# Cog attack selection
# ---------------------------------------------------------------------

def pick_cog_attack(cog: CogState, rng=random) -> str:
    """[CONFIRMED] algorithm: cumulative-frequency sample."""
    spec = data.cog(cog.department, cog.cog_type)
    rand_num = rng.randint(0, 99)
    count = 0
    for attack in spec.modeled_attacks:
        count += spec.frequency_at(attack.name, cog.level)
        if rand_num < count:
            return attack.name
    # Shouldn't happen if frequencies sum to 100, but fall back safely.
    return spec.modeled_attacks[0].name


# [OPEN TOONTOWN SOURCE] The chance a cog hits back at someone who has
# damaged it, rather than picking at random. From
# BattleCalculatorAI.__calcSuitTarget: `random.randint(0, 99) < 75`.
REVENGE_CHANCE = 75


def pick_cog_target(cog: CogState, toons, rng=random) -> int:
    """Which toon a cog's single-target attack hits.

    With one toon there is no choice. With more:

      * `REVENGE_CHANCE` per cent of the time, if anyone has damaged
        this cog, pick among those who have, weighted by their share of
        the damage.
      * Otherwise, uniformly among the toons still standing.

    PROVENANCE, WHICH IS WEAKER THAN [CONFIRMED]. The wiki gives only a
    direction -- "It is more likely that a Cog's single attack may
    target a Toon whose gags dealt the most damage to them, though this
    may not always be the case" -- and no numbers. The 75/25 split and
    the proportional weighting come from Open Toontown's
    `BattleCalculatorAI.__calcSuitTarget`, which is Toontown *Online*
    code, the same lineage this project distrusts the QED1224 guide for.
    It is a much better lead than a prose description, because it is the
    algorithm rather than someone's account of it, and the wiki
    corroborates its shape exactly. It is still not TTR.

    TWO ODDITIES IN THAT SOURCE, DELIBERATELY NOT COPIED. What is
    implemented is what the code evidently means.

    `__rememberToonAttack` writes `self.SuitAttackers[suitId] = [toonId,
    damage]` when a later hit is at least as large as an earlier one,
    replacing the per-cog dictionary with a two-element list -- which
    then breaks the `.keys()` calls in the selector. That one looks
    simply wrong.

    The weights are `damage / totalDamage * 100`, and the file is
    Python 2 (it calls `has_key`). If those values are integers that is
    integer division, every term with two or more attackers floors to
    zero, and selection falls through to uniform random -- but the
    operand types were inferred from the arithmetic rather than traced,
    so treat that as a reading and not a finding.

    Either way this implements the intent, on the judgement that TTR has
    most likely fixed anything of the sort in the twenty years since,
    and that reproducing another implementation's accidents would be
    modelling the accident rather than the game. The discrepancy is
    recorded so that a future disagreement with observed play has
    somewhere obvious to start.
    """
    if len(toons) <= 1:
        return 0
    standing = [i for i, toon in enumerate(toons) if toon.laff > 0]
    if not standing:
        return 0

    damage = cog.status.damage_by_toon or {}
    hurt = {i: d for i, d in damage.items() if i in standing and d > 0}
    if not hurt or rng.randint(0, 99) >= REVENGE_CHANCE:
        return rng.choice(standing)

    # Cumulative-frequency sample over shares of the damage dealt, which
    # is `pickFromFreqList` with the division done in floating point.
    total = float(sum(hurt.values()))
    roll = rng.randint(0, 99)
    running = 0.0
    for index in sorted(hurt):
        running += hurt[index] / total * 100.0
        if roll < running:
            return index
    return standing[-1]         # rounding shortfall; the source rerolls


def cog_attack_damage_and_accuracy(cog: CogState, attack_name: str, rng=random) -> Tuple[int, int]:
    """Damage and accuracy for one of this cog's attacks at its level.

    Raises NotImplementedError naming the cell if either is a documented
    gap -- without that a None reaches the arithmetic and surfaces as a
    bare TypeError, which reads like a simulator bug rather than a data one.
    """
    spec = data.cog(cog.department, cog.cog_type)
    entry = spec.damage_at(attack_name, cog.level)
    dmg = entry if isinstance(entry, int) else rng.randint(*entry)
    return dmg, spec.accuracy_at(attack_name, cog.level)


# ---------------------------------------------------------------------
# Lure: wake-up, duration, and what ends a lure
# ---------------------------------------------------------------------

def lure_accuracy_before_bonus(track: Track, level: int, toon: ToonState,
                                target_cogs,
                                lure_tree_planted: bool = False) -> int:
    """The `atkAccResult` the source feeds into wakeupChance:

        propAcc + trackExp + tgtDef        (NO bonus term)

    [CONFIRMED]. The guide shows atkAccResult being written *before*
    accuracy bonuses are added -- "Because of this, wakeupChance cannot be
    offset with accuracy bonuses, and is only affected by propAcc,
    trackExp, and tgtDef."

    THE 95 CAP IS DELIBERATELY NOT APPLIED HERE. Reading: the guide only
    ever states the cap in the hit/miss section ("It's important to note,
    however, that atkAcc is capped at 95"), describing the value compared
    against randChoice -- i.e. the post-bonus accuracy. atkAccResult is
    snapshotted earlier, and nothing in the guide caps it. It is also moot
    for the only consumer: wakeupChance = 100 - 2*acc is already <= 0 at
    acc >= 50, so any pre-bonus accuracy that could reach the cap can
    never wake a cog either way. Capping or not capping changes no
    outcome; we don't cap because the source doesn't say to.

    Worked example from the guide (Lureless toon, propAcc 70, level-12
    cog): 70 + 0 + (-55) = 15  ->  wakeupChance 70.
    """
    return (calc_prop_acc(track, level, lure_tree_planted)
            + calc_track_exp(toon, track)
            + calc_tgt_def(track, target_cogs))


def lure_wakeup_chance(atk_acc_before_bonus: int) -> int:
    """[CONFIRMED] wakeupChance = 100 - (atkAcc * 2), using the pre-bonus
    accuracy value (propAcc + trackExp + tgtDef only)."""
    return 100 - (atk_acc_before_bonus * 2)


def lure_wakes_up(atk_acc_before_bonus: int, rng=random) -> bool:
    """[CONFIRMED] rolled once per round per lured cog:
    `random.randint(0, 99) < wakeupChance`."""
    chance = lure_wakeup_chance(atk_acc_before_bonus)
    return rng.randint(0, 99) < chance


# Lure duration and early expiry now come from data/lure.py, which is
# [CONFIRMED] against the TTR wiki. See that module for the rebalancing
# history that makes the old strategy-guide values wrong.
LURE_ROUNDS_BY_LEVEL = {g.level: g.lure_rounds for g in data.gags_in(Track.LURE)}


def lure_duration_rounds(level: int) -> int:
    """Rounds a Lure of this level holds for -- cog phases the cog skips.
    [CONFIRMED] TTR wiki: 2/2/3/3/4/4/8 by level.

    This duration is set once, when the lure lands on an un-lured cog, and
    is never extended: re-luring neither stacks (3.0.0 removed that) nor
    refreshes. See CogStatus.apply_lure.
    """
    return data.gag(Track.LURE, level).rounds()


def lure_can_expire_early(level: int, lure_tree_planted: bool = False) -> bool:
    """Whether a lure of this level can end before its rounds run out.

    [CONFIRMED] TTR 3.3.0: "Lure gags with a base accuracy below 50% no
    longer have a chance for Lure effects to expire early."

    In current TTR this is False for every Lure gag -- the lowest base
    accuracy in the game is Small Magnet at 55%. So the wake-up roll below
    is unreachable in practice, and a lure reliably lasts its full
    duration. The threshold is coded rather than hardcoded to False
    because it is a rebalancing knob: a future patch that drops a gag
    under 50% would switch early expiry back on for it.
    """
    base = data.gag(Track.LURE, level).prop_accuracy(organic=lure_tree_planted)
    return base < data.EARLY_EXPIRY_ACCURACY_FLOOR


LURE_ENDS_ON_DAMAGE = None
DROP_MISSES_LURED_COGS = None

# [TODO] Multiple Lure gags thrown in the same round raise each other's
# accuracy, and this is NOT modelled -- a stacked Lure is currently
# searched at single-Lure accuracy and so is undervalued.
#
# [CONFIRMED] that it exists. TTR wiki (Lure), opening paragraph:
# "Using multiple Lure gags simultaneously increases the accuracy." The
# same page's update notes give the shape: "Multiple Lure gags of the
# same type used simultaneously now grant a bonus (20/15/10)% accuracy
# depending on the gag level discrepancies of the additional Lure gags,
# with the bonus being smaller if low-level Lure gags are used."
#
# ELIGIBILITY is now [CONFIRMED] and implemented below in
# `multi_lure_eligible`; only the MAGNITUDE is still open. From the
# v4.0.0 patch notes, which spell out what "of the same type" means:
#
#     Group Lures paired with another Group Lure yield 'Lure Bonus'
#     Dollar Bills paired with another Dollar Bill yield 'Lure Bonus'
#     Group Lures and Dollar Bills used simultaneously do not grant
#     'Lure Bonus'
#
# So it is the targeting class that must match, not the gag: two group
# Lures qualify, two Bills qualify, one of each does not. In this
# track's tables the Bills are exactly the single-target gags (levels
# 1, 3, 5) and the Magnets, Goggles and Presentation the group ones
# (2, 4, 6, 7), so `Gag.group` already carries the distinction.
#
# The same notes settle a neighbouring rule the model happens to get
# right: "Organic Lure now shifts the base accuracy of Lure by an
# additional 10% rather than being an additive bonus during the battle
# calculation". `Gag.prop_accuracy(organic=True)` is a base-accuracy
# shift of exactly +10 for all seven Lure gags, which is that rule --
# and it matters beyond accuracy, because the notes add that the shift
# "better determines who the overriding Lure Gag is".
#
# The DIRECTION is now corroborated, the magnitudes still are not.
# A player's reading is that the bonus is inversely proportional to the
# level gap between the lures -- same level pays most, a wide gap pays
# least -- and the wiki's own qualifier agrees in direction: "with the
# bonus being smaller if low-level Lure gags are used". A cheap lure
# added beside a dear one IS the wide-gap case, so both clauses point
# the same way.
#
# What that still does not give is which of 20/15/10 a given gap
# selects, and the bucket boundaries are the whole content of the rule:
# gap 0/1/2+ is the natural guess and it is a guess. Also unresolved:
# whether "of the same type" means the same gag, the same single/group
# class, or merely both being Lure; and how this composes with the
# Trap+Lure bonus in `calc_prev_hits_bonus`.
#
# Sources chased and exhausted, so the next person need not repeat it:
#   * The Accuracy page names a "Lure bonus" term that may push past the
#     95% soft cap, but gives no formula for it.
#   * Both cited rebalancing PDFs (v4.0.0 and December 2021) are
#     image-based -- their streams decompress to graphics, not text --
#     so the numbers cannot be read out programmatically.
#   * OPEN TOONTOWN IS THE WRONG LEAD HERE, unusually. This is a TTR
#     4.0.0 addition ("now grant"), so it postdates the Toontown Online
#     code entirely and nothing in that lineage can confirm it.
# [ASSUMED] -- NOT [CONFIRMED], and the distinction is the point.
#
# The project owner authorised filling this in on the balance of
# evidence, having read the v4.0.0 patch notes directly. Three
# independent statements point the same way:
#   * "depending on the gag level discrepancies of the additional Lure
#     gags" -- the gap is what indexes it;
#   * "with the bonus being smaller if lower leveled Lure gags are
#     used" -- a cheap Lure beside a dear one is the wide-gap case;
#   * the player's own reading, that it is inversely proportional to
#     the gap.
# Mapping the three published values onto gaps of 0, 1 and 2+ in that
# order is the only assignment consistent with all three. It remains an
# inference about bucket boundaries that no source states.
#
# WHAT WOULD SETTLE IT: throwing two group Lures at known levels and
# recording hit rates over enough trials to separate 20 from 15 from
# 10. Until then treat any result that leans on this as resting on a
# guess, and if measurement contradicts it, change these three numbers
# and nothing else -- that is why they are a table and not inlined.
#
# One neighbouring rule from the same patch IS pinned, and the
# simulator already obeyed it by inference rather than by citation.
# [CONFIRMED] TTR wiki (Lure, 4.0.0 update changes): "High-level Lure
# gags override the base accuracy of low-level Lure gags when used
# simultaneously." That is exactly what `simulator.apply_party_round`
# does when it keys a shared roll on (track, target) and takes
# `max(...)` of the group's accuracies -- see the `best[key]` line
# there, and `test_a_strong_lure_carries_a_weak_one_on_the_same_cog`.
#
# The search DOES allow stacked Lure (`party_search._playable` has no
# rule against it). Rejecting it was a real bug: it made a genuine TTR
# play unreachable. Undervalued and reachable beats correctly valued
# and impossible.
MULTI_LURE_ACCURACY_BONUS = {0: 20, 1: 15}
MULTI_LURE_ACCURACY_BONUS_DEFAULT = 10        # gap of 2 or more


def multi_lure_eligible(level_a: int, level_b: int) -> bool:
    """Would these two Lures, thrown together, earn the Lure Bonus?

    [CONFIRMED] TTR v4.0.0 patch notes: two group Lures qualify, two
    Dollar Bills qualify, and a group Lure beside a Bill does not. The
    matching is on targeting class rather than on the gag itself.

    Eligibility is [CONFIRMED]; the magnitude in
    `multi_lure_bonus` is [ASSUMED]. Keep the two apart -- this half
    rests on published text and that half does not.
    """
    return (data.gag(Track.LURE, level_a).group
            == data.gag(Track.LURE, level_b).group)


def multi_lure_bonus(levels) -> int:
    """Accuracy bonus for Lures thrown together, from their level gap.

    Zero unless at least two are eligible -- see `multi_lure_eligible`,
    which is the [CONFIRMED] half. The size is [ASSUMED]: see the note
    on `MULTI_LURE_ACCURACY_BONUS`.

    The gap is measured between the highest Lure and the next highest,
    because the notes describe the bonus as coming from "the additional
    Lure gags" against the one that overrides -- and the overriding gag
    is the most accurate, which for Lure tracks level.
    """
    levels = sorted(levels, reverse=True)
    if len(levels) < 2:
        return 0
    if not multi_lure_eligible(levels[0], levels[1]):
        return 0
    gap = levels[0] - levels[1]
    return MULTI_LURE_ACCURACY_BONUS.get(gap,
                                         MULTI_LURE_ACCURACY_BONUS_DEFAULT)
