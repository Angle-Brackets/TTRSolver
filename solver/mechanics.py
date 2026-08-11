"""
Core mechanics functions, built directly off the accuracy/damage formulas
documented in QED1224/Toontown-Resources. See data/ for confidence tags
on the underlying numbers.

SOLO-TOON SIMPLIFICATIONS (read before extending to multi-toon parties):

1. PrevHits ("stun") bonus is a same-ROUND bonus between different toons'
   (or a multi-target attack's) sequential hits. A solo toon only takes
   one action per round, so there is no "previous attack this round" to
   inherit a bonus from -- calc_prev_hits_bonus() always returns 0 here.
   This is correct for solo play, NOT a placeholder. Re-enable it if you
   extend to multiple toons acting in the same round.

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
    idx = level - 1
    if track == Track.LURE and lure_tree_planted:
        return data.AV_LURE_BONUS_ACCURACY[idx]
    return data.AV_PROP_ACCURACY[track][idx]


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


def calc_tgt_def(track: Track, target_cogs) -> int:
    """For group attacks, uses the strongest (highest-level) cog's defense,
    since every active cog is in the target list. [CONFIRMED]"""
    if not target_cogs:
        return 0
    if track == Track.TOON_UP:
        return 0
    strongest = max(c.level for c in target_cogs)
    return data.TGT_DEF_BY_LEVEL[strongest]


def calc_prev_hits_bonus(track: Track) -> int:
    """PrevHits half of the `bonus` term. See module docstring: always 0
    for a solo toon acting once per round. Extend for party play."""
    return 0


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
    return (calc_prev_hits_bonus(track)
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
    return min(acc, data.ACCURACY_CAP)


def roll_hit(accuracy_pct: int) -> bool:
    return random.randint(0, 99) < accuracy_pct


# ---------------------------------------------------------------------
# Toon attack damage
# ---------------------------------------------------------------------

def calc_toon_damage(track: Track, level: int, trained_fraction: float = 1.0) -> int:
    """Damage dealt by a gag. The real game ties this deterministically to
    the toon's earned experience in the track (see gag_damage_from_exp
    below) -- but we don't have the minE/maxE thresholds transcribed yet.
    As an interim approximation, trained_fraction (0=min dmg, 1=max dmg)
    linearly interpolates the known min/max range. Default 1.0 assumes a
    fully maxed track, which is the common "solved" build anyway.
    """
    entry = data.GAG_DAMAGE_MINMAX.get(track, {}).get(level)
    if entry is None:
        raise NotImplementedError(
            f"Gag damage for {track}/{level} is marked TODO in data/gags.py -- "
            f"fill it in before simulating this gag."
        )
    dmg_min, dmg_max = entry
    return round(dmg_min + (dmg_max - dmg_min) * trained_fraction)


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


def calc_hp_bonus(total_damage: int) -> float:
    """[CONFIRMED] hpBonus = ceil(totalDmgs * 0.20), applied when multiple
    gags of the SAME track hit the SAME target in the same round. A solo
    toon uses one gag per round, so this is always 0 here -- kept for
    party play. Does not apply to Lure or Trap."""
    return 0.0


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

def pick_cog_attack(cog: CogState) -> str:
    """[CONFIRMED] algorithm: cumulative-frequency sample."""
    table = data.COG_DEPARTMENTS[cog.department].get(cog.cog_type)
    if table is None:
        raise NotImplementedError(f"No attack table for cog '{cog.cog_type}'")
    rel_level = cog.level - table["levels"][0]
    rand_num = random.randint(0, 99)
    count = 0
    for attack_name, freqs in table["freq"].items():
        count += freqs[rel_level]
        if rand_num < count:
            return attack_name
    # Shouldn't happen if frequencies sum to 100, but fall back safely.
    return next(iter(table["freq"]))


def pick_cog_target(cog: CogState, toons) -> int:
    """Solo-toon stub: always the lone toon. For multi-toon, the source
    algorithm weights toons by (damage they've dealt to this cog / total
    damage dealt to this cog), sampled the same cumulative-frequency way
    as pick_cog_attack, with a uniform-random fallback if no damage has
    been dealt yet or the sample falls through."""
    return 0


def cog_attack_damage_and_accuracy(cog: CogState, attack_name: str) -> Tuple[int, int]:
    table = data.COG_DEPARTMENTS[cog.department][cog.cog_type]
    rel_level = cog.level - table["levels"][0]

    if table.get("accuracy") is None:
        raise NotImplementedError(
            f"Accuracy table for '{cog.cog_type}' is marked TODO in "
            f"data/{cog.department}.py."
        )

    # Individual cells can be [TODO] even when the table as a whole is
    # populated -- micromanager/brain_storm accuracy and
    # the_big_cheese/glower_power are the live cases. Without this check a
    # None cell reaches the arithmetic and surfaces as a bare TypeError,
    # which reads like a bug in the simulator rather than a documented gap
    # in the data.
    dmg_entry = table["damage"][attack_name][rel_level]
    acc = table["accuracy"][attack_name][rel_level]
    if dmg_entry is None or acc is None:
        missing = "damage" if dmg_entry is None else "accuracy"
        raise NotImplementedError(
            f"{cog.cog_type}/{attack_name} at level {cog.level}: {missing} "
            f"is marked TODO in data/{cog.department}.py."
        )

    dmg = dmg_entry if isinstance(dmg_entry, int) else random.randint(*dmg_entry)
    return dmg, acc


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


def lure_wakes_up(atk_acc_before_bonus: int) -> bool:
    """[CONFIRMED] rolled once per round per lured cog:
    `random.randint(0, 99) < wakeupChance`."""
    chance = lure_wakeup_chance(atk_acc_before_bonus)
    return random.randint(0, 99) < chance


# Lure duration and early expiry now come from data/lure.py, which is
# [CONFIRMED] against the TTR wiki. See that module for the rebalancing
# history that makes the old strategy-guide values wrong.
LURE_ROUNDS_BY_LEVEL = dict(data.LURE_ROUNDS_BY_LEVEL)


def lure_duration_rounds(level: int) -> int:
    """Rounds a Lure of this level holds for -- cog phases the cog skips.
    [CONFIRMED] TTR wiki: 2/2/3/3/4/4/8 by level.

    Note 3.0.0: "Lure gags no longer stack rounds." Re-luring an already
    lured cog overwrites its counter rather than adding to it, which is
    what CogStatus.apply_lure does.
    """
    rounds = LURE_ROUNDS_BY_LEVEL.get(level)
    if rounds is None:
        raise NotImplementedError(f"No lure duration for gag level {level}.")
    return rounds


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
    table = (data.LURE_ORGANIC_ACCURACY if lure_tree_planted
             else data.LURE_BASE_ACCURACY)
    return table[level] < data.EARLY_EXPIRY_ACCURACY_FLOOR


LURE_ENDS_ON_DAMAGE = None
DROP_MISSES_LURED_COGS = None
