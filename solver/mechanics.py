"""
Core mechanics functions, built directly off the accuracy/damage formulas
documented in QED1224/Toontown-Resources. See data/ for confidence tags
on the underlying numbers.

Solo-toon simplifications, before extending to multi-toon parties:

1. PrevHits ("stun") has two halves. The same-round half is 0 solo
   (nothing to inherit from) EXCEPT for Trap, whose Lure bonus persists
   across rounds -- see calc_prev_hits_bonus. luredRatio, the other
   half, is not a same-round effect and DOES apply solo -- see
   calc_lured_ratio_bonus.
2. Trap+Lure combo damage is a separate, persistent cross-round trigger,
   modeled in simulator._resolve_toon_action's LURE branch.
3. pick_cog_target() is a stub returning the lone toon; the
   proportional-damage weighting for parties is implemented below it.

See docs/mechanics-notes.md for full discovery history.
"""
import math
import random
from typing import Tuple

from . import sos as sos_mod
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
    """Rank (tier) on the department's corporate ladder, 1-8. [CONFIRMED]
    TTR wiki: rank equals the lowest level the cog can appear at (Flunky
    tier 1 starts at level 1, Pencil Pusher tier 2 at level 2, ...), so
    the first entry of "levels" is the rank -- no extra table needed."""
    return data.cog(cog.department, cog.cog_type).rank


def calc_tgt_def(track: Track, target_cogs) -> int:
    """For group attacks, uses the strongest (highest-level) cog's defense,
    since every active cog is in the target list. [CONFIRMED]

    tgtDef depends on the cog's RANK as well as its level, not just level.
    See docs/mechanics-notes.md#calc_tgt_def--the-rank-1-branch-bug.
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
    """The stun bonus from attacks that already landed this round. Zero
    for a solo toon (one action per round, nothing to inherit) -- the
    half of PrevHits only a party can earn.

    `prior_hits` counts hits on this attack's target(s) earlier in the
    same round meeting the wiki's conditions -- caller-checked, since
    they depend on tracks/targets rather than a number: previous attack
    hit, was a *different* track, and either attack is group or both
    share a target. Trap is excluded from the count.
    """
    return min(PREV_HIT_MAX, max(0, prior_hits) * PREV_HIT_STEP)


def calc_prev_hits_bonus(track: Track, level: int = 0, all_cogs=None) -> int:
    """PrevHits half of the `bonus` term. Not always zero for a solo toon:

    [CONFIRMED] TTR wiki (Accuracy#PrevHits): first Trap placement grants
    +10 PrevHits to Lure only; each further Trap placement grants +5 more
    to a GROUP Lure; and this persists across rounds as long as Trap is
    present -- so a solo toon that traps then lures next round gets it.
    Rule 4, "+50 PrevHits when Trap is activated by Lure", is left at 0:
    it applies to attacks landing after the trap fires in the same round,
    which a solo toon never has.

    `all_cogs` is every cog in the battle; without it there is no trap
    state to read and this returns 0.
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
    (Accuracy#luredRatio): all Sound gags, and level 7 Throw or Squirt
    when there is a mixed set of lured and un-lured Cogs.

    Narrower than the strategy guide's rule ("everything except Lure,
    Toon-Up and Drop"), which wrongly handed the bonus to ordinary
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
    `all_cogs` is every cog in the battle, not just this attack's targets
    (the denominator is the whole battle); dead cogs are excluded from
    both halves.

    Truncated, not rounded -- the source doesn't say how a non-integral
    ratio should round, and truncation is only ever a 1-point difference.
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

    `all_cogs` defaults to None ("lure state not supplied"), dropping the
    luredRatio half. Deliberately NOT defaulted to the attack's own
    targets: for a single-target attack that would compute the ratio over
    one cog and read 100."""
    return (calc_prev_hits_bonus(track, level, all_cogs)
            + calc_lured_ratio_bonus(track, level, all_cogs))


def lure_hit_override(track: Track, target_cogs):
    """Accuracy forced by the targets' lure state, or None for "roll it".
    [CONFIRMED] TTR wiki (Lure): Throw/Squirt get "a 50% damage bonus on
    guaranteed hits" against lured cogs -> 100; "Drop gags always miss on
    lured Cogs" -> 0. Only when EVERY target is lured -- the wiki is
    explicit that a mixed lured/un-lured set is not guaranteed, so a
    group gag over a partly-lured battle rolls normally."""
    if not target_cogs or not all(c.status.lured for c in target_cogs):
        return None
    if track in (Track.THROW, Track.SQUIRT):
        return 100
    if track == Track.DROP:
        return 0
    return None


def forced_accuracy(track: Track, target_cogs):
    """Accuracy FIXED by a rule, or None when it has to be rolled up.

    Three outcomes the rules state outright: Trap always hits, Throw and
    Squirt are guaranteed against fully lured cogs, and Drop always
    misses them. Because they are stated rather than computed, nothing
    may adjust them afterwards -- not the same-round stun bonus, not the
    95 cap. Kept as one function so both callers (solo and party) agree.
    """
    if track == Track.TRAP:
        return 100  # [CONFIRMED] trap is always-hit
    return lure_hit_override(track, target_cogs)


def calc_toon_accuracy(track: Track, level: int, toon: ToonState,
                        target_cogs, lure_tree_planted: bool = False,
                        all_cogs=None, toons_hit: bool = False,
                        toons_always_hit: bool = False) -> int:
    """Full atkAcc, bonus included, capped at 95. This is the value the
    hit/miss roll uses. For the wake-up input, use
    lure_accuracy_before_bonus() instead -- it is a different number.

    Pass `all_cogs=state.cogs` to get the luredRatio accuracy bonus; without
    it the bonus term is 0, as it was before luredRatio was modeled.

    `toons_hit` applies the SOS effect of the same name: [CONFIRMED]
    wiki, +75% gag accuracy for 3-5 rounds. A multiplier rather than 75
    points, matching Cogs Miss in `_resolve_cog_phase` -- and applied
    BEFORE the 95 cap, so it cannot push a gag past what the game
    allows."""
    forced = forced_accuracy(track, target_cogs)
    if forced is not None:
        return forced
    if toons_hit and toons_always_hit:
        return 100    # Realms plays Toons Hit as TTO did: every gag lands

    acc = (calc_prop_acc(track, level, lure_tree_planted)
           + calc_track_exp(toon, track)
           + calc_tgt_def(track, target_cogs)
           + calc_bonus(track, level, all_cogs))

    # [CONFIRMED] TTR wiki: "if atkAcc falls below 5%, it is automatically
    # increased to 5%". The exemption is Drop against a lured cog, which
    # always misses -- and that case has already returned 0 above.
    acc = max(acc, data.ACCURACY_FLOOR)

    if toons_hit:
        # [CONFIRMED] wiki: an SOS raises gag accuracy by 75% for 3-5
        # rounds. A multiplier, matching Cogs Miss, not 75 points.
        # Applied BEFORE the cap, same as the stun/Lure bonuses below.
        acc = int(round(acc * (1.0 + sos_mod.ACCURACY_SWING / 100.0)))

    # The 95 cap became SOFT in 4.3.3 (stun/Lure/Trap/Toons Hit can push
    # it higher), but the wiki never quantifies the replacement, so this
    # stays a hard cap as the closest defensible approximation. See
    # data.ACCURACY_CAP_IS_SOFT_IN_GAME.
    return min(acc, data.ACCURACY_CAP)


def accuracy_roll(rng=random) -> int:
    """One accuracy die, 0-99. Separate from `roll_hit` because a roll is
    sometimes SHARED: gags of the same track aimed at the same cog
    resolve on one roll, and a group gag rolls once for every target, so
    the caller needs the number, not just the verdict.

    `rng` defaults to the global module so callers are unaffected; pass
    one for a reproducible search -- see `party_search.evaluate`.
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
# A knob: run the search at a pessimistic fraction and compare answers to
# ask "how much does this recommendation depend on everyone being maxed"
# -- see objective.risk_aversion.
DAMAGE_TRAINED_FRACTION = 1.0


def calc_toon_damage(track: Track, level: int,
                      trained_fraction: float = None,
                      organic: bool = False) -> int:
    """Damage dealt by a gag. The real game ties this deterministically to
    earned experience (see gag_damage_from_exp) via minE/maxE thresholds
    not yet transcribed; as an interim approximation, trained_fraction
    (0=min dmg, 1=max dmg) linearly interpolates the gag's range."""
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
    """Lure knockback bonus damage. [CONFIRMED] kbBonus = totalDmgs * 0.50,
    applying whenever a lured target is hit with Throw or Squirt.
    `total_damage` is that track's damage to the target this round --
    just the one gag's for a solo toon. Returned unrounded; caller lands
    it on an integer HP pool.

    NOT modeled: the guide's kbBonus mis-indexing bug (needs >1 cog and a
    list-ordering mismatch; a TTO-lineage bug, not a mechanic).
    """
    if not target_lured or track not in KB_BONUS_TRACKS:
        return 0.0
    return total_damage * KB_BONUS_MULTIPLIER


def calc_hp_bonus(total_damage: int, gags_on_target: int = 1) -> int:
    """The same-track damage bonus, for `gags_on_target` gags of one
    track landing on one cog in one round.

    [CONFIRMED] TTR wiki (Gags): "When two or more of the same gag type
    (excluding Lure, Trap, and Toon-Up) are used on a Cog simultaneously,
    a 20% damage bonus applies." Callers must not call this for Lure or
    Trap. `gags_on_target` defaults to 1 (solo case), which yields 0.

    PER COG, NOT PER ROUND -- do not copy Toontown Online's bug of
    applying the bonus to every cog a group gag touched just because two
    same-track gags landed somewhere in the round; [CONFIRMED] wrong for
    TTR by the owner from play. `simulator._apply_track_group` keys its
    contributions by cog index for this reason.

    Rounds with `ceil`, which is NOT wiki-confirmed -- it's the QED1224
    (Toontown Online) source's convention, kept for lack of a better one.
    First thing to check if party damage ever reads a point low.
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

    With one toon there is no choice. With more: `REVENGE_CHANCE` per
    cent of the time, if anyone has damaged this cog, pick among those
    who have, weighted by their share of the damage; otherwise uniformly
    among the toons still standing.

    [OPEN TOONTOWN SOURCE], WEAKER THAN [CONFIRMED]. The wiki gives only
    a direction ("more likely to target whoever dealt the most damage,
    though this may not always be the case") with no numbers; the 75/25
    split and proportional weighting come from Open Toontown's
    `BattleCalculatorAI.__calcSuitTarget` (Toontown *Online* code). Two
    oddities in that source are deliberately NOT copied -- a dict-vs-list
    clobber and a probable integer-division bug that would floor
    multi-attacker weights to zero -- on the judgement that what's
    implemented here is what the code evidently means, not its accidents.

    THE MEMORY IS THE WHOLE BATTLE, NOT THE ROUND, which is a third
    thing deliberately not copied from that source: Open Toontown wipes
    its damage record every round, so a cog there forgets who hurt it as
    soon as the round ends. [OWNER]: that's a TTO bug, not a rule -- a
    cog remembers who has been hitting it for the whole fight, so
    `damage_by_toon` accumulates and is never reset. The wiki settles
    nothing either way here; it gives only a direction.

    See docs/mechanics-notes.md#pick_cog_target for full reasoning.
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
    gap, rather than letting a None reach the arithmetic as a bare
    TypeError that reads like a simulator bug."""
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

    [CONFIRMED]: snapshotted before accuracy bonuses are added, so
    "wakeupChance cannot be offset with accuracy bonuses". THE 95 CAP IS
    DELIBERATELY NOT APPLIED HERE -- moot anyway since
    wakeupChance = 100 - 2*acc is already <= 0 at acc >= 50.

    Worked example (Lureless toon, propAcc 70, level-12 cog):
    70 + 0 + (-55) = 15 -> wakeupChance 70.
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


# A PROCESS-WIDE OVERRIDE for a game whose durations differ: only the
# Realms panel sets it (`realms_session.use_realms_rules`), in its own
# processes. TTR's table is never edited for another game.
LURE_ROUNDS_OVERRIDE: dict = {}


def lure_duration_rounds(level: int) -> int:
    """Rounds a Lure of this level holds for -- cog phases the cog skips.
    [CONFIRMED] TTR wiki: 2/2/3/3/4/4/8 by level. Set once, when the lure
    lands on an un-lured cog, and never extended -- re-luring neither
    stacks (3.0.0 removed that) nor refreshes. See CogStatus.apply_lure.
    """
    if level in LURE_ROUNDS_OVERRIDE:
        return LURE_ROUNDS_OVERRIDE[level]
    return data.gag(Track.LURE, level).rounds()


def lure_can_expire_early(level: int, lure_tree_planted: bool = False) -> bool:
    """Whether a lure of this level can end before its rounds run out.

    [CONFIRMED] TTR 3.3.0: Lure gags with base accuracy below 50% no
    longer have a chance to expire early. Currently False for every Lure
    gag -- the lowest base accuracy in the game is Small Magnet at 55% --
    so the wake-up roll is unreachable in practice today. Coded as a
    threshold rather than hardcoded False because it's a rebalancing
    knob: a future gag under 50% would switch this back on.
    """
    if level is None:
        # An SOS lure, which is not a gag and has no level. [CONFIRMED]
        # TTR wiki: all SOS gags have perfect accuracy and cannot miss,
        # and 100 is above EARLY_EXPIRY_ACCURACY_FLOOR, so the answer
        # falls out of the same rule rather than being a new one.
        #
        # `sos.apply` passes level=None on purpose; before this the
        # lookup below raised `no gag at lure level None` the first time
        # a card was played through a cog phase.
        return False
    base = data.gag(Track.LURE, level).prop_accuracy(organic=lure_tree_planted)
    return base < data.EARLY_EXPIRY_ACCURACY_FLOOR


# [CONFIRMED] by the owner from play: ANY attack gag that lands on a
# lured cog wakes it immediately -- not just Sound. Knockback bonus is
# applied FIRST (a Throw/Squirt still gets its +50% against the sleeping
# cog), then the lure ends; if the cog survives it attacks that same
# round, already awake. Drop is the exception that proves it: it always
# MISSES a lured cog, so it never wakes anything.
LURE_ENDS_ON_DAMAGE = True
DROP_MISSES_LURED_COGS = True

# The tracks that DEAL damage, and therefore wake a lured cog when they
# land. Trap and Lure place effects rather than damage; Toon-Up heals.
DAMAGE_TRACKS = (Track.SOUND, Track.THROW, Track.SQUIRT, Track.DROP)

# Multiple Lure gags thrown together raise each other's accuracy.
# Modelled in `multi_lure_bonus`, applied in `simulator.apply_party_round`
# to the shared roll. Two group Lure 6s go from 80% to 95%, measured.
#
# [CONFIRMED] that it exists and its shape. TTR wiki (Lure) update notes:
# "Multiple Lure gags of the same type used simultaneously now grant a
# bonus (20/15/10)% accuracy depending on the gag level discrepancies of
# the additional Lure gags, with the bonus being smaller if low-level
# Lure gags are used."
#
# ELIGIBILITY is [CONFIRMED] (`multi_lure_eligible`): "of the same type"
# means matching TARGETING CLASS, not the same gag -- two group Lures
# qualify, two Dollar Bills qualify, one of each does not.
#
# [ASSUMED] -- NOT [CONFIRMED] -- is which of 20/15/10 a given level gap
# selects. `MULTI_LURE_ACCURACY_BONUS` maps gap 0 -> 20, gap 1 -> 15,
# gap >=2 -> `MULTI_LURE_ACCURACY_BONUS_DEFAULT` (10), owner-authorised
# from the v4.0.0 notes on the reasoning that the bonus is inversely
# proportional to the gap; the bucket boundaries are an inference no
# source states. What would settle it: measured hit rates from two
# group Lures at known levels, enough trials to separate 20/15/10 -- if
# measurement contradicts this table, change it and nothing else. See
# docs/mechanics-notes.md#multi_lure_accuracy_bonus--the-one-assumed-value.
#
# A neighbouring rule from the same patch IS pinned: [CONFIRMED]
# "High-level Lure gags override the base accuracy of low-level Lure
# gags when used simultaneously" is what `simulator.apply_party_round`
# does, keying a shared roll on (track, target) and taking `max(...)`.
#
# The search DOES allow stacked Lure (`party_search._playable` has no
# rule against it) -- rejecting it made a genuine TTR play unreachable.
MULTI_LURE_ACCURACY_BONUS = {0: 20, 1: 15}
MULTI_LURE_ACCURACY_BONUS_DEFAULT = 10        # gap of 2 or more


def multi_lure_eligible(level_a: int, level_b: int) -> bool:
    """Would these two Lures, thrown together, earn the Lure Bonus?
    [CONFIRMED] (see the MULTI_LURE_ACCURACY_BONUS comment above):
    matches on targeting class (group vs single-target), not the gag."""
    return (data.gag(Track.LURE, level_a).group
            == data.gag(Track.LURE, level_b).group)


def multi_lure_bonus(levels) -> int:
    """Accuracy bonus for Lures thrown together, from their level gap.
    Zero unless at least two are eligible (`multi_lure_eligible`,
    [CONFIRMED]); the size is [ASSUMED] (`MULTI_LURE_ACCURACY_BONUS`).

    Gap is measured between the highest Lure and the next highest: the
    notes describe the bonus as coming from "the additional Lure gags"
    against the one that overrides, which for Lure is the most accurate
    and so the highest level.
    """
    levels = sorted(levels, reverse=True)
    if len(levels) < 2:
        return 0
    if not multi_lure_eligible(levels[0], levels[1]):
        return 0
    gap = levels[0] - levels[1]
    return MULTI_LURE_ACCURACY_BONUS.get(gap,
                                         MULTI_LURE_ACCURACY_BONUS_DEFAULT)
