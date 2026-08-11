"""
Core mechanics functions, built directly off the accuracy/damage formulas
documented in QED1224/Toontown-Resources. See data/ for confidence tags
on the underlying numbers.

SOLO-TOON SIMPLIFICATIONS (read before extending to multi-toon parties):

1. PrevHits ("stun") bonus is a same-ROUND bonus between different toons'
   (or a multi-target attack's) sequential hits. A solo toon only takes
   one action per round, so there is no "previous attack this round" to
   inherit a bonus from -- calc_bonus() always returns 0 here. This is
   correct for solo play, NOT a placeholder. Re-enable it if you extend
   to multiple toons acting in the same round.

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


def calc_bonus(track: Track) -> int:
    """PrevHits + luredRatio bonus. See module docstring: always 0 for a
    solo toon acting once per round. Extend this when adding party play."""
    return 0


def calc_toon_accuracy(track: Track, level: int, toon: ToonState,
                        target_cogs, lure_tree_planted: bool = False) -> int:
    if track == Track.TRAP:
        return 100  # [CONFIRMED] trap is always-hit
    acc = (calc_prop_acc(track, level, lure_tree_planted)
           + calc_track_exp(toon, track)
           + calc_tgt_def(track, target_cogs)
           + calc_bonus(track))
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

    dmg_entry = table["damage"][attack_name][rel_level]
    dmg = dmg_entry if isinstance(dmg_entry, int) else random.randint(*dmg_entry)
    acc = table["accuracy"][attack_name][rel_level]
    return dmg, acc


# ---------------------------------------------------------------------
# Lure wake-up
# ---------------------------------------------------------------------

def lure_wakeup_chance(atk_acc_before_bonus: int) -> int:
    """[CONFIRMED] wakeupChance = 100 - (atkAcc * 2), using the pre-bonus
    accuracy value (propAcc + trackExp + tgtDef only)."""
    return 100 - (atk_acc_before_bonus * 2)


def lure_wakes_up(atk_acc_before_bonus: int) -> bool:
    chance = lure_wakeup_chance(atk_acc_before_bonus)
    return random.randint(0, 99) < chance
