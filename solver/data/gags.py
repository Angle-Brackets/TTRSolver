"""
Gag damage, heals, organic values and group levels, by (track, level).

[CONFIRMED] from the Toontown Rewritten wiki, except for the two cells
explicitly left None below. Sources, all cross-checked against each other:

  https://toontownrewritten.wiki/Throw     https://toontownrewritten.wiki/Squirt
  https://toontownrewritten.wiki/Sound     https://toontownrewritten.wiki/Drop
  https://toontownrewritten.wiki/Trap      https://toontownrewritten.wiki/Toon-Up
  https://toontownrewritten.wiki/Organic_gags
  ...plus the per-gag infobox on each of the 42 individual gag pages
  (Cupcake, Banana Peel, Toontanic, ...), which carry mindamage/maxdamage
  (or minheal/maxheal) and organic fields of their own.

SOURCE NOTE -- READ THIS BEFORE ADDING TO data/
-----------------------------------------------
This module is now TTR wiki data. It previously came from the QED1224
strategy guide, which describes *Toontown Online* and predates TTR's
rebalancing passes; that transcription was wrong about Sound (shifted a
whole level -- see below), about the level-7 Trap and Drop gags (renamed
*and* renumbered in TTR), and about which levels are group gags for Sound
and Toon-Up. See docs/data-confidence.md.

The wiki blocks ordinary fetches (403) but serves its MediaWiki API:

    curl "https://toontownrewritten.wiki/api.php?action=parse\\
          &page=Throw&prop=wikitext&format=json"

WHAT THE GUIDE HAD WRONG (corrected here)
-----------------------------------------
  * Sound was off by one level. The guide's table started at Whistle
    (5-7) and had no Bike Horn, so every Sound level was shifted down
    one and level 6 was missing entirely.
  * Trap level 7 is Railroad at 200, not "Train Tracks" at 195. 195 was
    the pre-3.0.0 value; 3.0.0 raised it to 200.
  * Drop level 7 is Toontanic at 180, not "Ocean Liner". Damage is
    unchanged, only the name -- "Ocean Liner" and "Train Tracks" are TTO
    names and do not exist on the TTR wiki at all.
  * Throw level 6 "48-100" and Sound level 5 "25-50" had been rejected as
    internally inconsistent. Both are REAL, and both were misfiled.
    48-100 is Birthday Cake (Throw 6) and is correct as written; the
    wide range is deliberate. 25-50 is Foghorn, which is Sound level
    *6*, not 5 -- it looked like a broken progression only because of the
    off-by-one above. Every level-6 gag in the game has a wide range
    (Birthday Cake 48-100, Storm Cloud 36-80, Foghorn 25-50, Grand Piano
    85-170, TNT 90-180, Juggling Cubes 75-105).

WHERE THE GUIDE WAS RIGHT
-------------------------
Of the 14 damage cells the guide had actually populated, 12 survive the
wiki check unchanged: Throw 1-5 and 7, Squirt 1 and 7, Sound 7 (Opera
Singer, 90) and Drop 7 (180 -- right number under the wrong name). Only
two populated cells were wrong: Trap 7 (195, now 200) and the whole
Sound column below level 7, via the off-by-one above.

TTR REBALANCING HISTORY captured here (from each page's own changelog):
  Throw   -- no rebalancing section on the page.
  Squirt  -- no rebalancing section on the page.
  Sound   -- 4.0.0: carry capacity reduced to Trap's pre-3.0.0 capacity;
             exp thresholds for Whistle/Aoogah/Elephant Trunk/Foghorn
             lowered. No damage change.
  Drop    -- 3.0.0: Safe given a damage *range* (like Grand Piano).
             4.0.0: accuracy re-described "low" -> "very low"; organic
             Drop bonus raised 10% -> 15%.
  Trap    -- 3.0.0: Trapdoor 60-70 -> 75-85 (organic 66-77 -> "83-93");
             Railroad 195 -> 200 (organic 214 -> 220); Trap put on the
             same carry capacity as other tracks.
             4.0.0: Trap grants +10% accuracy to Lure against a Trapped
             cog; Quicksand exp threshold 800 -> 500.
             4.0.5: Trap activation stun bonus 30% -> 50%; the passive
             10% Lure accuracy bonus now stacks, +5% per extra trap.
  Toon-Up -- 3.0.0: Pixie Dust 60-70 -> 50-60; Juggling Cubes 90-120 ->
             75-105.
             4.0.0: organic Toon-Up bonus raised 10% -> 20%.
"""
from ..state import Track

# In-game gag name by (track, level). [CONFIRMED] -- worth keeping around
# because two of them changed between TTO and TTR and the old names are
# still scattered through comments elsewhere in the codebase.
GAG_NAMES = {
    Track.TOON_UP: {1: "Feather", 2: "Megaphone", 3: "Lipstick",
                    4: "Bamboo Cane", 5: "Pixie Dust", 6: "Juggling Cubes",
                    7: "High Dive"},
    Track.TRAP:    {1: "Banana Peel", 2: "Rake", 3: "Marbles",
                    4: "Quicksand", 5: "Trapdoor", 6: "TNT",
                    7: "Railroad"},        # TTO: "Train Tracks"
    Track.SOUND:   {1: "Bike Horn", 2: "Whistle", 3: "Bugle", 4: "Aoogah",
                    5: "Elephant Trunk", 6: "Foghorn", 7: "Opera Singer"},
    Track.THROW:   {1: "Cupcake", 2: "Fruit Pie Slice", 3: "Cream Pie Slice",
                    4: "Whole Fruit Pie", 5: "Whole Cream Pie",
                    6: "Birthday Cake", 7: "Wedding Cake"},
    Track.SQUIRT:  {1: "Squirting Flower", 2: "Glass of Water",
                    3: "Squirt Gun", 4: "Seltzer Bottle", 5: "Fire Hose",
                    6: "Storm Cloud", 7: "Geyser"},
    Track.DROP:    {1: "Flower Pot", 2: "Sandbag", 3: "Anvil",
                    4: "Big Weight", 5: "Safe", 6: "Grand Piano",
                    7: "Toontanic"},       # TTO: "Ocean Liner"
}

# ---------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------
# (min, max) by (track, level). [CONFIRMED] -- complete, no gaps.
#
# The (min, max) shape SURVIVES the wiki audit: TTR still publishes a
# damage range per gag, and min is what the gag deals when freshly
# unlocked, max when the track is maxed. Gags with a single published
# figure (every level 7, and Drop 1-4, which the Drop page notes "can
# already deal maximum damage") are stored as (x, x), matching the
# convention the old table already used for level 7.
#
# Toon-Up is deliberately absent from this dict -- it heals rather than
# damages. See GAG_HEAL_MINMAX below.
GAG_DAMAGE_MINMAX = {
    Track.THROW: {
        1: (4, 6),      # Cupcake
        2: (8, 10),     # Fruit Pie Slice
        3: (14, 17),    # Cream Pie Slice
        4: (24, 27),    # Whole Fruit Pie
        5: (36, 40),    # Whole Cream Pie
        6: (48, 100),   # Birthday Cake -- the wide range is real, see header
        7: (120, 120),  # Wedding Cake (group)
    },
    Track.SQUIRT: {
        1: (3, 4),      # Squirting Flower
        2: (6, 8),      # Glass of Water
        3: (10, 12),    # Squirt Gun
        4: (18, 21),    # Seltzer Bottle
        5: (27, 30),    # Fire Hose
        6: (36, 80),    # Storm Cloud
        7: (105, 105),  # Geyser (group)
    },
    Track.SOUND: {
        # NOTE the level numbers: the old table was shifted one level
        # down because the guide omitted Bike Horn entirely.
        1: (3, 4),      # Bike Horn
        2: (5, 7),      # Whistle
        3: (9, 11),     # Bugle
        4: (14, 16),    # Aoogah
        5: (19, 21),    # Elephant Trunk
        6: (25, 50),    # Foghorn
        7: (90, 90),    # Opera Singer
    },
    Track.DROP: {
        1: (10, 10),    # Flower Pot
        2: (18, 18),    # Sandbag
        3: (30, 30),    # Anvil
        4: (45, 45),    # Big Weight
        5: (60, 70),    # Safe -- range added in 3.0.0
        6: (85, 170),   # Grand Piano
        7: (180, 180),  # Toontanic (group)
    },
    Track.TRAP: {
        1: (10, 12),    # Banana Peel
        2: (18, 20),    # Rake
        3: (30, 35),    # Marbles
        4: (45, 50),    # Quicksand
        5: (75, 85),    # Trapdoor -- raised from 60-70 in 3.0.0
        6: (90, 180),   # TNT
        7: (200, 200),  # Railroad (group) -- raised from 195 in 3.0.0
    },
    Track.TOON_UP: {},  # heals, not damage -- see GAG_HEAL_MINMAX
}

# Damage when the gag is organic (grown on a gag tree). [CONFIRMED] from
# the per-track tables, the Organic gags page, and the per-gag infoboxes,
# except Trap level 5 -- see the comment there.
#
# The Organic gags page states the rule as: Trap/Sound/Throw ceil(1.1x),
# Squirt/Drop ceil(1.15x), Toon-Up ceil(1.2x). That formula reproduces
# every published figure below except Squirt level 4 (Seltzer Bottle),
# where the formula gives 21 but all three wiki sources say 22. The
# tables win over the prose; the values below are transcribed, never
# computed.
GAG_ORGANIC_DAMAGE_MINMAX = {
    Track.THROW: {
        1: (5, 7), 2: (9, 11), 3: (16, 19), 4: (27, 30),
        5: (40, 44), 6: (53, 110), 7: (132, 132),
    },
    Track.SQUIRT: {
        1: (4, 5),
        2: (7, 10),
        3: (12, 14),
        4: (22, 25),    # min 22 disagrees with the page's own ceil(1.15x)
                        # rule (which gives 21); all three tables say 22
        5: (32, 35), 6: (42, 92), 7: (121, 121),
    },
    Track.SOUND: {
        1: (4, 5), 2: (6, 8), 3: (10, 13), 4: (16, 18),
        5: (21, 24), 6: (28, 55), 7: (99, 99),
    },
    Track.DROP: {
        1: (12, 12), 2: (21, 21), 3: (35, 35), 4: (52, 52),
        5: (69, 81), 6: (98, 196), 7: (207, 207),
    },
    Track.TRAP: {
        1: (11, 14), 2: (20, 22), 3: (33, 39), 4: (50, 55),
        5: None,        # TODO: Trapdoor organic. Three wiki sources give
                        # three different mins/maxes and no two agree:
                        # the Trap page says 83-94, the Organic gags page
                        # and the Trapdoor infobox say 84-94, and the
                        # Trap page's own 3.0.0 changelog says 83-93. The
                        # page's stated ceil(1.1x) rule on 75-85 gives
                        # 83-94, which matches none of them completely.
                        # Not guessing -- needs a fourth source.
        6: (99, 198),
        7: (220, 220),  # Railroad -- raised from 214 in 3.0.0
    },
    Track.TOON_UP: {},  # see GAG_ORGANIC_HEAL_MINMAX
}

# Organic bonus per track, in whole percent -- the form the Organic gags
# page and the 4.0.0 patch notes both state it in ("increasing the damage
# value by 10% and then rounding up the result").
#
# Applied as ceil(x * (100 + pct) / 100). Kept as an integer percent
# rather than a float multiplier on purpose: 1.1 * 100 is 110.00000000000001
# in binary floating point, so ceil() of it gives 111 and silently
# overstates an organic Birthday Cake. Integer arithmetic has no such
# edge. Use organic_value() below rather than rolling your own.
#
# Recorded for reference only -- the tables above are transcribed from the
# wiki, not derived from this, and Squirt level 4 is a known exception.
# Lure gets a flat accuracy bonus instead of a damage bonus and lives in
# data/lure.py.
ORGANIC_BONUS_PCT = {
    Track.TRAP: 10,
    Track.SOUND: 10,
    Track.THROW: 10,
    Track.SQUIRT: 15,     # raised from 10 in 4.0.0
    Track.DROP: 15,       # raised from 10 in 4.0.0
    Track.TOON_UP: 20,    # raised from 10 in 4.0.0
}


def organic_value(track: Track, value: int) -> int:
    """The wiki's stated organic rule, in exact integer arithmetic.

    Prefer the transcribed GAG_ORGANIC_* tables over calling this -- they
    are what the wiki actually publishes, and Squirt level 4 does not
    match this formula. This exists for gags outside the seven-level
    tables (unites, SOS cards) and to check the tables for typos.
    """
    numerator = value * (100 + ORGANIC_BONUS_PCT[track])
    return -(-numerator // 100)     # ceiling division, no floats

# ---------------------------------------------------------------------
# Toon-Up heals
# ---------------------------------------------------------------------
# (min, max) laff restored. [PARTIAL] -- level 3 is genuinely disputed.
#
# Separate dict from GAG_DAMAGE_MINMAX on purpose: Toon-Up targets toons,
# not cogs, and simulator.apply_toon_action needs to branch on it anyway.
GAG_HEAL_MINMAX = {
    1: (8, 10),     # Feather
    2: (15, 18),    # Megaphone
    3: None,        # TODO: Lipstick. The Toon-Up page and the Organic
                    # gags page both say 27-30; the Lipstick infobox says
                    # minheal=25, maxheal=30. The max (30) is agreed. The
                    # min is not, and the tie-breaker points the wrong
                    # way: all three sources agree organic Lipstick is
                    # 30-36, and ceil(1.2 * 25) = 30 while
                    # ceil(1.2 * 27) = 33 -- so the organic column
                    # supports the infobox's 25, not the tables' 27.
                    # Left None rather than picked. The whole cell is
                    # None (not a half-tuple) so callers that interpolate
                    # between min and max can't silently get a bad range.
    4: (40, 45),    # Bamboo Cane
    5: (50, 60),    # Pixie Dust -- lowered from 60-70 in 3.0.0
    6: (75, 105),   # Juggling Cubes -- lowered from 90-120 in 3.0.0
    7: (210, 210),  # High Dive (group)
}

# Organic heal. [CONFIRMED] -- all seven agree across all three sources,
# including level 3, whose base heal is disputed above.
GAG_ORGANIC_HEAL_MINMAX = {
    1: (10, 12),    # Feather
    2: (18, 22),    # Megaphone
    3: (30, 36),    # Lipstick
    4: (48, 54),    # Bamboo Cane
    5: (60, 72),    # Pixie Dust
    6: (90, 126),   # Juggling Cubes
    7: (252, 252),  # High Dive
}

# [CONFIRMED] Toon-Up page: "Unlike other gag tracks, Toon-Up gags do not
# necessarily miss, but rather, provide 20% of original values that are
# rounded up." So a missed Toon-Up still heals ceil(0.20 * heal) -- it is
# NOT a no-op the way a missed damage gag is.
TOON_UP_MISS_FRACTION = 0.20

# ---------------------------------------------------------------------
# Group gags
# ---------------------------------------------------------------------
# Levels whose "Affects" column reads "All Cogs" / "All Toons".
# [CONFIRMED] from every track page and every per-gag infobox.
#
# Two of these contradict simulator.is_group_action as written:
#   * SOUND is group at every level -- the simulator already hardcodes
#     True for Sound, which happens to be right.
#   * TOON_UP is group only at 2/4/6/7, the same zig-zag as Lure. The
#     simulator hardcodes True for all seven Toon-Up levels, which is
#     WRONG for levels 1, 3 and 5 (Feather, Lipstick and Pixie Dust each
#     affect "One Toon").
# Throw/Squirt/Drop/Trap really are level-7-only, so the simulator's
# `level == 7` branch is correct for those four.
# Lure's group levels live in data/lure.py (LURE_GROUP_LEVELS = 2,4,6,7).
GAG_GROUP_LEVELS = {
    Track.TOON_UP: frozenset({2, 4, 6, 7}),   # Megaphone, Bamboo Cane,
                                              # Juggling Cubes, High Dive
    Track.TRAP:    frozenset({7}),            # Railroad
    Track.SOUND:   frozenset({1, 2, 3, 4, 5, 6, 7}),  # every Sound gag
    Track.THROW:   frozenset({7}),            # Wedding Cake
    Track.SQUIRT:  frozenset({7}),            # Geyser
    Track.DROP:    frozenset({7}),            # Toontanic
}
