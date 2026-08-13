"""
Toon attack accuracy formula components. [CONFIRMED] from the Toontown
Rewritten wiki: https://toontownrewritten.wiki/Accuracy

    atkAcc = propAcc + trackExp + tgtDef + bonus

SOURCE NOTE -- READ THIS BEFORE EDITING
---------------------------------------
Every table in this module has now been checked against the TTR wiki's
Accuracy page and the seven per-track pages (Toon-Up, Trap, Lure, Sound,
Throw, Squirt, Drop), which carry the same base-accuracy column. It no
longer relies on the QED1224 strategy guide, which describes *Toontown
Online* and predates TTR's rebalancing. See docs/data-confidence.md.

The wiki blocks ordinary fetches (403) but serves its MediaWiki API:

    curl "https://toontownrewritten.wiki/api.php?action=parse\\
          &page=Accuracy&prop=wikitext&format=json"

Audit result, propAcc: the guide and the wiki agree on six of the seven
tracks. The one guide error was Toon-Up level 7 (High Dive), which the
guide had at 100% and the wiki puts at 95% -- stated twice on the
Toon-Up page ("High Dive has a 95% base accuracy ... the only Toon-Up gag
to have high accuracy") and again in the Accuracy page's own table. The
flat rows really are flat in TTR: Lure and Toon-Up are the only two tracks
whose gags differ from each other, which the Accuracy page says outright
("For all gag tracks besides Toon-Up and Lure, every gag in the same track
have the same propAcc value").

TTR REBALANCING HISTORY captured here (from the Accuracy page's own
"Update changes" section, plus the per-track pages' changelogs):
  4.0.0 -- Several changes to the accuracy *logic* of Lure gags, and a
           cosmetic change to Drop's accuracy description ("low" ->
           "very low"). The Accuracy page is explicit that "No changes
           were made to the actual base accuracy values of Drop gags."
           Same update set PrevHits to 25 per prior hit (see below).
  4.0.0 -- (Trap page) Trap gags give a 10% accuracy bonus to Lure gags
           used on Cogs with the Trapped status effect.
  4.0.5 -- (Trap page) Trap activation stun bonus 30% -> 50%; the passive
           10% Lure accuracy bonus became stackable, +5% per extra Trap.
  4.3.3 -- The 95% hard cap became a *soft* cap: stun bonus, Lure bonus,
           Trap placements and Toons Hit can now push the final accuracy
           past 95. See ACCURACY_CAP_IS_SOFT below.
"""
from ..state import Track
from .gags import gag

# propAcc[track][level-1] -> base accuracy, level is 1-indexed.
#
# [CONFIRMED] -- TTR wiki, Accuracy#propAcc, cross-checked against each
# track's own page (the "Base accuracy" column of its gag table).
#
# Trap is 0% in the table on purpose: the wiki lists every Trap gag at 0%
# base accuracy and handles Trap by a special rule instead -- "When a Trap
# gag is used, atkAcc is automatically set to 100% and atkHit is set to 1."
# mechanics.calc_toon_accuracy implements that short-circuit.
# Derived from the Gag objects rather than restated here: propAcc is a
# property of a gag, and keeping a second copy keyed by track/level is how
# the old parallel-dict layout let Lure drift out of sync in the first place.
AV_PROP_ACCURACY = {
    track: [gag(track, level).accuracy for level in range(1, 8)]
    for track in Track
}

# Organic propAcc, where a track has one. Only Lure does -- every other
# track's organic bonus is damage or healing, so these rows are all None
# and that is a finding, not a gap.
AV_ORGANIC_PROP_ACCURACY = {
    track: [gag(track, level).organic_accuracy for level in range(1, 8)]
    for track in Track
}

ORGANIC_ACCURACY_TRACKS = frozenset({Track.LURE})

# Back-compat alias: the flat level-indexed organic-Lure row that
# mechanics.calc_prop_acc reads today. [CONFIRMED] -- TTR wiki, see
# data/lure.py. Prefer AV_ORGANIC_PROP_ACCURACY for new code.
AV_LURE_BONUS_ACCURACY = AV_ORGANIC_PROP_ACCURACY[Track.LURE]

# trackExp by gag level. [CONFIRMED] -- TTR wiki, Accuracy#trackExp.
# Determined by the *highest gag a Toon has unlocked in the track*, not by
# the level of the gag being thrown. mechanics.calc_track_exp computes the
# same values arithmetically as (trained_level - 1) * 10; this table is the
# citation for that arithmetic.
#
# Special rule [CONFIRMED]: "If a Toon-Up gag is used, trackExp is halved
# for that gag." (mechanics.calc_track_exp already does this.)
TRACK_EXP_BY_LEVEL = {1: 0, 2: 10, 3: 20, 4: 30, 5: 40, 6: 50, 7: 60}

# tgtDef by cog level. [CONFIRMED] for levels 1-12 and 20; levels 13-19 are
# listed by the wiki as literally "Unknown" and are therefore absent here,
# so a lookup for them raises instead of inventing a number.
#
# THE LEVEL 4/5 AMBIGUITY IS RESOLVED. The wiki prints "-12*/-15" at level 4
# and "-15*/-20" at level 5 with the footnote:
#
#   "Rank 1 Cogs used the tgtDef value with the asterisk for the marked
#    levels."
#
# "Rank" here is position on the corporate ladder, which the wiki's
# Corporate ladder page calls tier: "Typically, a Cog's minimum level is the
# same as their tier in the ladder and their maximum level is four levels
# greater. For example, Flunky is the first Cog on the Bossbots' corporate
# ladder, making them tier 1." Rank/tier 1 is therefore exactly Flunky,
# Bottom Feeder, Short Change and Cold Caller.
#
# So the key is (cog level, cog rank), not cog level alone -- and both
# branches are reachable, because a level-4 cog may be a rank-1 Flunky or a
# rank-4 Micromanager. Use tgt_def() below when the rank is known.
#
# TGT_DEF_BY_LEVEL keeps the rank-1 branch at levels 4 and 5, unchanged from
# before this audit, so callers that don't know a cog's rank behave exactly
# as they used to. mechanics.calc_tgt_def is such a caller; a cog's rank is
# available to it as COG_DEPARTMENTS[dept][cog_type]["levels"][0].
TGT_DEF_RANK_1 = {
    1: -2, 2: -5, 3: -10, 4: -12, 5: -15, 6: -25,
    7: -30, 8: -35, 9: -40, 10: -45, 11: -50, 12: -55,
    # 13-19: wiki says "Unknown" -- deliberately omitted.
    20: -65,
}

# Rank 2 and above: same table except at the two asterisked levels.
TGT_DEF_RANK_2_PLUS = {**TGT_DEF_RANK_1, 4: -15, 5: -20}

# Default lookup. Identical to the pre-audit table for levels 1-12, with
# level 20 added.
TGT_DEF_BY_LEVEL = TGT_DEF_RANK_1


def tgt_def(cog_level: int, cog_rank: int = 1) -> int:
    """tgtDef for a cog, disambiguating the level 4/5 rank split.

    `cog_rank` is the cog's tier on the corporate ladder (1-8), i.e. the
    lowest level at which that cog type appears. Defaults to 1 to match
    TGT_DEF_BY_LEVEL.

    Raises KeyError for cog levels 13-19, whose tgtDef the wiki records as
    "Unknown" -- raising is the point, see the no-guessing rule in
    docs/data-confidence.md.
    """
    table = TGT_DEF_RANK_1 if cog_rank == 1 else TGT_DEF_RANK_2_PLUS
    return table[cog_level]


# The 95% accuracy cap. [CONFIRMED] as a value, but read the flag below:
# 4.3.3 turned it from a hard cap into a soft one.
ACCURACY_CAP = 95

# [CONFIRMED] -- TTR wiki, Accuracy, 4.3.3 update: "the battle accuracy
# system's 95% hard cap is now a soft cap ... all accuracy bonuses such as
# stun bonus, Lure bonus, Trap placements, and Toons Hit can slightly push
# the final accuracy value higher than 95%". Restated in the page's own
# special rules: "For all other gags, atkAcc can slightly be pushed higher
# than 95% due to stun bonus, Lure bonus, Trap placements, and Toons Hit."
#
# NOT MODELLED. mechanics.calc_toon_accuracy still applies min(acc, 95)
# unconditionally, which is the pre-4.3.3 behaviour. The wiki does not
# quantify "slightly" -- it never states the post-4.3.3 ceiling, nor
# whether propAcc/trackExp/tgtDef alone can still exceed 95 -- so the exact
# replacement rule is not derivable from this source and no number for it
# is recorded here.
ACCURACY_CAP_IS_SOFT = True

# [CONFIRMED] -- Accuracy#Special rules: "Except when using a Drop gag on
# lured Cogs, if atkAcc falls below 5%, it is automatically increased to
# 5%." (Drop on a lured cog is a guaranteed miss, so the floor cannot
# rescue it.) NOT MODELLED in mechanics.py today.
ACCURACY_FLOOR = 5
ACCURACY_FLOOR_EXEMPT_TRACKS = frozenset({Track.DROP})   # only when lured

# PrevHits, the "stun bonus" half of the `bonus` term.
# [CONFIRMED] -- Accuracy#PrevHits: "PrevHits is incremented by the number
# of previous hits x 25 (excluding Trap) on the target(s) in the current
# round, with a bonus of +75 being possible with three prior hits", cited
# to the 4.0.0 rebalancing patch notes.
#
# CORRECTED BY THIS AUDIT: the strategy guide's 20-per-hit / 60-max are the
# pre-4.0.0 Toontown Online numbers.
PREV_HITS_BONUS_PER_HIT = 25   # was 20 (guide, TTO-era)
PREV_HITS_MAX_BONUS = 75       # was 60 (guide, TTO-era)
PREV_HITS_MAX_PRIOR_HITS = 3   # 3 x 25 = 75, consistent with the above

# Trap handles PrevHits by its own rules. [CONFIRMED] -- Accuracy#PrevHits
# (cited to release notes 367) and corroborated by the Trap page:
#   1. The first Trap placed grants +10 to PrevHits, but only for Lure.
#   2. Further Trap placements grant an additional +5 to a *group* Lure gag.
#   3. Lure's PrevHits from Trap persists across rounds while Trap is present.
#   4. Trap successfully activated by Lure grants +50 PrevHits regardless of
#      how many Traps activated (4.0.5 raised this from 30).
# Rules 1-3 ARE modelled -- see mechanics.calc_prev_hits_bonus, which is
# where the cross-round Trap -> Lure bonus is applied. Rule 4 is not: it
# pays attacks landing after the trap goes off in the same round, and a
# solo toon has none.
TRAP_LURE_ACCURACY_BONUS = 10
TRAP_EXTRA_LURE_ACCURACY_BONUS = 5      # per extra trap, group Lure only
TRAP_ACTIVATION_PREV_HITS = 50
