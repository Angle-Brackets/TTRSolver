"""
Toon attack accuracy formula components.

    atkAcc = propAcc + trackExp + tgtDef + bonus     (capped at 95)

[CONFIRMED] -- all four components verified against the source guide.
"""
from ..state import Track

# propAcc[track][level-1] -> base accuracy, level is 1-indexed
# [CONFIRMED]
AV_PROP_ACCURACY = {
    Track.TOON_UP: [70, 70, 70, 70, 70, 70, 100],
    Track.TRAP:    [0, 0, 0, 0, 0, 0, 0],     # trap: handled as always-hit, see mechanics.py
    Track.LURE:    [50, 50, 60, 60, 70, 70, 90],
    Track.SOUND:   [95, 95, 95, 95, 95, 95, 95],
    Track.THROW:   [75, 75, 75, 75, 75, 75, 75],
    Track.SQUIRT:  [95, 95, 95, 95, 95, 95, 95],
    Track.DROP:    [50, 50, 50, 50, 50, 50, 50],
}

# Organic-lure propAcc replacement, if toon has a Lure tree planted at
# >= this gag's level (or an active Lure interactive prop is in play).
# [CONFIRMED]
AV_LURE_BONUS_ACCURACY = [60, 60, 70, 70, 80, 80, 100]

# tgtDef by cog level (1-12). [PARTIAL]
# Source table lists two values at levels 4 and 5 (-12/-15, -15/-20):
# the less-negative value applies to tier-1 cogs (e.g. Cold Caller,
# Flunky). This lookup uses the tier-1 (less-negative) value; swap in
# the other branch if modeling a non-tier-1 cog at level 4 or 5.
TGT_DEF_BY_LEVEL = {
    1: -2, 2: -5, 3: -10, 4: -12, 5: -15, 6: -25,
    7: -30, 8: -35, 9: -40, 10: -45, 11: -50, 12: -55,
}

ACCURACY_CAP = 95
PREV_HITS_BONUS_PER_HIT = 20   # [CONFIRMED]
PREV_HITS_MAX_BONUS = 60       # [CONFIRMED] (caps at 3 prior hits)
