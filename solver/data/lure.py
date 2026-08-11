"""
Lure gag data. [CONFIRMED] from the Toontown Rewritten wiki:
https://toontownrewritten.wiki/Lure

SOURCE NOTE -- READ THIS BEFORE ADDING TO data/
-----------------------------------------------
This module is TTR wiki data. Everything else in data/ came from the
QED1224 strategy guide, which describes *Toontown Online* and predates
TTR's rebalancing passes. Lure is the first table checked against the wiki
and it disagreed with the guide on nearly every value -- durations,
accuracy, and which levels are group gags. Assume the rest of data/ has
the same problem until it's re-verified. See docs/data-confidence.md.

The wiki blocks ordinary fetches (403) but serves its MediaWiki API:

    curl "https://toontownrewritten.wiki/api.php?action=parse\\
          &page=Lure&prop=wikitext&format=json"

TTR REBALANCING HISTORY captured here (from the page's own changelog):
  3.0.0 -- Presentation 15 -> 8 rounds. "Removed the Lure Stacking Rounds
           mechanic that allowed the accumulation of Lure rounds ... if
           multiple Lure Gags are used simultaneously." Note that is about
           SIMULTANEOUS lures; re-luring across rounds doesn't refresh the
           counter either, but that part is play knowledge rather than
           something the wiki states -- see CogStatus.apply_lure.
  3.3.0 -- Lure gags with base accuracy below 50% no longer have a chance
           for Lure effects to expire early.
  4.0.0 -- Dollar Bill gags +10% base accuracy; multi-Lure gags +5%;
           Presentation base accuracy settled at 90%.
"""

# Level -> in-game gag name. Levels are 1-indexed, matching Track/level
# usage everywhere else.
LURE_GAG_NAMES = {
    1: "$1 Bill",
    2: "Small Magnet",
    3: "$5 Bill",
    4: "Big Magnet",
    5: "$10 Bill",
    6: "Hypno-goggles",
    7: "Presentation",
}

# Rounds the lure holds -- cog phases the cog skips. [CONFIRMED]
LURE_ROUNDS_BY_LEVEL = {1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 8}

# propAcc. [CONFIRMED] -- post-4.0.0 values.
# Note the zig-zag: the single-target gag at each odd level is *more*
# accurate than the group gag one level above it. The strategy guide's
# flat [50, 50, 60, 60, 70, 70, 90] is the pre-rebalance TTO table.
LURE_BASE_ACCURACY = {1: 60, 2: 55, 3: 70, 4: 65, 5: 80, 6: 75, 7: 90}

# propAcc when the gag is organic. [CONFIRMED]
LURE_ORGANIC_ACCURACY = {1: 70, 2: 65, 3: 80, 4: 75, 5: 90, 6: 85, 7: 100}

# Which levels hit every cog ("Affects: All Cogs"). [CONFIRMED]
# The magnets and Hypno-goggles are group gags -- it is NOT only level 7,
# which is what the code assumed before this table existed.
LURE_GROUP_LEVELS = frozenset({2, 4, 6, 7})

# 3.3.0: "Lure gags with a base accuracy below 50% no longer have a chance
# for Lure effects to expire early." [CONFIRMED]
#
# Every TTR lure gag is at or above 55% base accuracy, so in practice no
# lure can expire early any more -- see mechanics.lure_can_expire_early.
EARLY_EXPIRY_ACCURACY_FLOOR = 50
