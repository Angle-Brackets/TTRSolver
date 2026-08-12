"""
Every gag in the game, one `Gag` object each.

Damage, heals, organic values, accuracy, group flag, and (for Lure)
duration in rounds -- all on one object per (track, level), so finding
out what a gag does is one lookup instead of six parallel dicts.
Lure used to live in data/lure.py purely because it was the first table
rewritten from the wiki; there was never a reason for it to be separate.

[CONFIRMED] from the Toontown Rewritten wiki, except for the two cells
explicitly left None below. Sources, all cross-checked against each other:

  https://toontownrewritten.wiki/Throw     https://toontownrewritten.wiki/Squirt
  https://toontownrewritten.wiki/Sound     https://toontownrewritten.wiki/Drop
  https://toontownrewritten.wiki/Trap      https://toontownrewritten.wiki/Toon-Up
  https://toontownrewritten.wiki/Lure
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
  Lure    -- 3.0.0: Presentation 15 -> 8 rounds; "Removed the Lure Stacking
             Rounds mechanic that allowed the accumulation of Lure rounds
             ... if multiple Lure Gags are used simultaneously". (Re-luring
             across rounds doesn't refresh the counter either, but that is
             play knowledge, not something the wiki states -- see
             CogStatus.apply_lure.)
             3.3.0: Lure gags with base accuracy below 50% no longer have a
             chance to expire early. No gag is under 50%, so in practice
             lures now always run their full duration.
             4.0.0: dollar-bill accuracy +10%, multi-Lure +5%, Presentation
             settled at 90%.
"""
from typing import Dict, Tuple

from ..state import Track
from .types import Gag

# ---------------------------------------------------------------------
# The gags
# ---------------------------------------------------------------------
# A `None` damage/heal is a documented gap, not an oversight -- see the two
# disputed cells noted below. Gag.damage_at()/heal_at() raise on them.

# Positional args are (track, level, display). min_carry/max_carry are
# the per-gag holding limits on a starting and a fully upgraded pouch --
# [CONFIRMED] from each gag's own infobox on the wiki.
GAGS: Tuple[Gag, ...] = (
    # --- Toon Up ---------------------------------------------
    Gag(Track.TOON_UP, 1, 'Feather', accuracy=70, group=False, heal=(8, 10), organic_heal=(10, 12), min_carry=10, max_carry=30),
    Gag(Track.TOON_UP, 2, 'Megaphone', accuracy=70, group=True, heal=(15, 18), organic_heal=(18, 22), min_carry=5, max_carry=25),
    Gag(Track.TOON_UP, 3, 'Lipstick', accuracy=70, group=False, organic_heal=(30, 36), heal=None, min_carry=5, max_carry=20),
    Gag(Track.TOON_UP, 4, 'Bamboo Cane', accuracy=70, group=True, heal=(40, 45), organic_heal=(48, 54), min_carry=5, max_carry=15),
    Gag(Track.TOON_UP, 5, 'Pixie Dust', accuracy=70, group=False, heal=(50, 60), organic_heal=(60, 72), min_carry=3, max_carry=7),
    Gag(Track.TOON_UP, 6, 'Juggling Cubes', accuracy=70, group=True, heal=(75, 105), organic_heal=(90, 126), min_carry=3, max_carry=3),
    Gag(Track.TOON_UP, 7, 'High Dive', accuracy=95, group=True, heal=(210, 210), organic_heal=(252, 252), min_carry=1, max_carry=1),

    # --- Trap ------------------------------------------------
    Gag(Track.TRAP, 1, 'Banana Peel', accuracy=0, group=False, damage=(10, 12), organic_damage=(11, 14), min_carry=10, max_carry=30),
    Gag(Track.TRAP, 2, 'Rake', accuracy=0, group=False, damage=(18, 20), organic_damage=(20, 22), min_carry=5, max_carry=25),
    Gag(Track.TRAP, 3, 'Marbles', accuracy=0, group=False, damage=(30, 35), organic_damage=(33, 39), min_carry=5, max_carry=20),
    Gag(Track.TRAP, 4, 'Quicksand', accuracy=0, group=False, damage=(45, 50), organic_damage=(50, 55), min_carry=5, max_carry=15),
    Gag(Track.TRAP, 5, 'Trapdoor', accuracy=0, group=False, damage=(75, 85), organic_damage=None, min_carry=3, max_carry=7),
    Gag(Track.TRAP, 6, 'TNT', accuracy=0, group=False, damage=(90, 180), organic_damage=(99, 198), min_carry=3, max_carry=3),
    Gag(Track.TRAP, 7, 'Railroad', accuracy=0, group=True, damage=(200, 200), organic_damage=(220, 220), min_carry=1, max_carry=1),

    # --- Lure ------------------------------------------------
    Gag(Track.LURE, 1, '$1 Bill', accuracy=60, group=False, damage=None, organic_accuracy=70, lure_rounds=2, min_carry=10, max_carry=30),
    Gag(Track.LURE, 2, 'Small Magnet', accuracy=55, group=True, damage=None, organic_accuracy=65, lure_rounds=2, min_carry=5, max_carry=25),
    Gag(Track.LURE, 3, '$5 Bill', accuracy=70, group=False, damage=None, organic_accuracy=80, lure_rounds=3, min_carry=5, max_carry=20),
    Gag(Track.LURE, 4, 'Big Magnet', accuracy=65, group=True, damage=None, organic_accuracy=75, lure_rounds=3, min_carry=5, max_carry=15),
    Gag(Track.LURE, 5, '$10 Bill', accuracy=80, group=False, damage=None, organic_accuracy=90, lure_rounds=4, min_carry=3, max_carry=7),
    Gag(Track.LURE, 6, 'Hypno-goggles', accuracy=75, group=True, damage=None, organic_accuracy=85, lure_rounds=4, min_carry=3, max_carry=3),
    Gag(Track.LURE, 7, 'Presentation', accuracy=90, group=True, damage=None, organic_accuracy=100, lure_rounds=8, min_carry=1, max_carry=1),

    # --- Sound -----------------------------------------------
    Gag(Track.SOUND, 1, 'Bike Horn', accuracy=95, group=True, damage=(3, 4), organic_damage=(4, 5), min_carry=5, max_carry=20),
    Gag(Track.SOUND, 2, 'Whistle', accuracy=95, group=True, damage=(5, 7), organic_damage=(6, 8), min_carry=3, max_carry=15),
    Gag(Track.SOUND, 3, 'Bugle', accuracy=95, group=True, damage=(9, 11), organic_damage=(10, 13), min_carry=3, max_carry=15),
    Gag(Track.SOUND, 4, 'Aoogah', accuracy=95, group=True, damage=(14, 16), organic_damage=(16, 18), min_carry=3, max_carry=10),
    Gag(Track.SOUND, 5, 'Elephant Trunk', accuracy=95, group=True, damage=(19, 21), organic_damage=(21, 24), min_carry=3, max_carry=5),
    Gag(Track.SOUND, 6, 'Foghorn', accuracy=95, group=True, damage=(25, 50), organic_damage=(28, 55), min_carry=2, max_carry=2),
    Gag(Track.SOUND, 7, 'Opera Singer', accuracy=95, group=True, damage=(90, 90), organic_damage=(99, 99), min_carry=1, max_carry=1),

    # --- Throw -----------------------------------------------
    Gag(Track.THROW, 1, 'Cupcake', accuracy=75, group=False, damage=(4, 6), organic_damage=(5, 7), min_carry=10, max_carry=30),
    Gag(Track.THROW, 2, 'Fruit Pie Slice', accuracy=75, group=False, damage=(8, 10), organic_damage=(9, 11), min_carry=5, max_carry=25),
    Gag(Track.THROW, 3, 'Cream Pie Slice', accuracy=75, group=False, damage=(14, 17), organic_damage=(16, 19), min_carry=5, max_carry=20),
    Gag(Track.THROW, 4, 'Whole Fruit Pie', accuracy=75, group=False, damage=(24, 27), organic_damage=(27, 30), min_carry=5, max_carry=15),
    Gag(Track.THROW, 5, 'Whole Cream Pie', accuracy=75, group=False, damage=(36, 40), organic_damage=(40, 44), min_carry=3, max_carry=7),
    Gag(Track.THROW, 6, 'Birthday Cake', accuracy=75, group=False, damage=(48, 100), organic_damage=(53, 110), min_carry=3, max_carry=3),
    Gag(Track.THROW, 7, 'Wedding Cake', accuracy=75, group=True, damage=(120, 120), organic_damage=(132, 132), min_carry=1, max_carry=1),

    # --- Squirt ----------------------------------------------
    Gag(Track.SQUIRT, 1, 'Squirting Flower', accuracy=95, group=False, damage=(3, 4), organic_damage=(4, 5), min_carry=10, max_carry=30),
    Gag(Track.SQUIRT, 2, 'Glass of Water', accuracy=95, group=False, damage=(6, 8), organic_damage=(7, 10), min_carry=5, max_carry=25),
    Gag(Track.SQUIRT, 3, 'Squirt Gun', accuracy=95, group=False, damage=(10, 12), organic_damage=(12, 14), min_carry=5, max_carry=20),
    Gag(Track.SQUIRT, 4, 'Seltzer Bottle', accuracy=95, group=False, damage=(18, 21), organic_damage=(22, 25), min_carry=5, max_carry=15),
    Gag(Track.SQUIRT, 5, 'Fire Hose', accuracy=95, group=False, damage=(27, 30), organic_damage=(32, 35), min_carry=3, max_carry=7),
    Gag(Track.SQUIRT, 6, 'Storm Cloud', accuracy=95, group=False, damage=(36, 80), organic_damage=(42, 92), min_carry=3, max_carry=3),
    Gag(Track.SQUIRT, 7, 'Geyser', accuracy=95, group=True, damage=(105, 105), organic_damage=(121, 121), min_carry=0, max_carry=1),

    # --- Drop ------------------------------------------------
    Gag(Track.DROP, 1, 'Flower Pot', accuracy=50, group=False, damage=(10, 10), organic_damage=(12, 12), min_carry=10, max_carry=30),
    Gag(Track.DROP, 2, 'Sandbag', accuracy=50, group=False, damage=(18, 18), organic_damage=(21, 21), min_carry=5, max_carry=25),
    Gag(Track.DROP, 3, 'Anvil', accuracy=50, group=False, damage=(30, 30), organic_damage=(35, 35), min_carry=5, max_carry=20),
    Gag(Track.DROP, 4, 'Big Weight', accuracy=50, group=False, damage=(45, 45), organic_damage=(52, 52), min_carry=5, max_carry=15),
    Gag(Track.DROP, 5, 'Safe', accuracy=50, group=False, damage=(60, 70), organic_damage=(69, 81), min_carry=3, max_carry=7),
    Gag(Track.DROP, 6, 'Grand Piano', accuracy=50, group=False, damage=(85, 170), organic_damage=(98, 196), min_carry=3, max_carry=3),
    Gag(Track.DROP, 7, 'Toontanic', accuracy=50, group=True, damage=(180, 180), organic_damage=(207, 207), min_carry=1, max_carry=1),
)

# Two cells no source settles, kept None rather than picked:
#   Trap 5 (Trapdoor) organic damage -- the Trap page says 83-94, the
#     Organic gags page and the Trapdoor infobox say 84-94, and the Trap
#     page's own 3.0.0 changelog says 83-93. Base 75-85 is agreed.
#   Toon-Up 3 (Lipstick) heal -- Toon-Up and Organic gags pages say 27-30,
#     the Lipstick infobox says minheal 25. Organic 30-36 is agreed, and
#     ceil(1.2 * 25) = 30 while ceil(1.2 * 27) = 33, which points at 25 --
#     against the majority. Left open.

_BY_KEY: Dict[Tuple[Track, int], Gag] = {g.key: g for g in GAGS}


def gag(track: Track, level: int) -> Gag:
    """The Gag for a (track, level). Raises KeyError for a level outside 1-7."""
    try:
        return _BY_KEY[(track, level)]
    except KeyError:
        raise KeyError(f"no gag at {track.value} level {level}") from None


def gags_in(track: Track) -> Tuple[Gag, ...]:
    return tuple(g for g in GAGS if g.track == track)


# ---------------------------------------------------------------------
# Organic bonus
# ---------------------------------------------------------------------
# The wiki's stated rule, per track: "increasing the value by N% and then
# rounding up".
#
# Kept as an integer percent rather than a float multiplier on purpose:
# 1.1 * 100 is 110.00000000000001 in binary floating point, so ceil() of it
# gives 111 and silently overstates an organic Birthday Cake. Integer
# arithmetic has no such edge.
#
# Reference only -- each Gag carries its transcribed organic value, and
# Squirt level 4 is a known exception to this formula. Lure gets an
# accuracy bonus instead of a damage one; that's Gag.organic_accuracy.
ORGANIC_BONUS_PCT = {
    Track.TRAP: 10,
    Track.SOUND: 10,
    Track.THROW: 10,
    Track.SQUIRT: 15,     # raised from 10 in 4.0.0
    Track.DROP: 15,       # raised from 10 in 4.0.0
    Track.TOON_UP: 20,    # raised from 10 in 4.0.0
}


def organic_value(track: Track, value: int) -> int:
    """The organic rule in exact integer arithmetic. Prefer the transcribed
    value on the Gag itself; this is for gags outside the seven-level tables
    (unites, SOS cards) and for spotting typos in them."""
    numerator = value * (100 + ORGANIC_BONUS_PCT[track])
    return -(-numerator // 100)     # ceiling division, no floats


# [CONFIRMED] "Toon-Up gags do not necessarily miss, but rather, provide 20%
# of original values that are rounded up" -- the only track where a miss
# still does something.
TOON_UP_MISS_FRACTION = 0.20

# ---------------------------------------------------------------------
# What a toon may actually carry
# ---------------------------------------------------------------------
# [CONFIRMED] <https://toontownrewritten.wiki/Gags>: "Toons can select up to
# six total gag tracks that they want to train for." Seven tracks exist and
# no toon can have them all -- every loadout gives one up.
MAX_GAG_TRACKS = 6

# [CONFIRMED] <https://toontownrewritten.wiki/Gag_pouch>: pouch capacity by
# upgrade, "allowing Toons to carry up to a total of 80 gags after
# completing every ToonTask". This is a cap on the TOTAL across all tracks,
# not per track.
POUCH_CAPACITIES = {
    "Starting Pouch":  20,
    "Medium Pouch":    25,   # Toontown Central
    "Large Pouch":     30,   # Donald's Dock
    "Small Bag":       35,   # Daisy Gardens
    "Medium Bag":      40,   # Minnie's Melodyland
    "Large Bag":       50,   # The Brrrgh
    "Small Backpack":  60,   # Donald's Dreamland
    "Medium Backpack": 70,   # Donald's Dreamland
    "Large Backpack":  80,   # Bossbot Headquarters
}
MAX_POUCH = max(POUCH_CAPACITIES.values())


def validate_loadout(gag_counts) -> list:
    """Reasons a {(track, level): count} loadout is not legal, or [].

    Checks the two rules the game enforces and a solver could otherwise
    quietly violate -- it is easy to hand the search a toon carrying all
    seven tracks and 200 gags and get advice no real toon could follow.
    """
    problems = []
    carried = {t for (t, _lvl), n in gag_counts.items() if n > 0}
    if len(carried) > MAX_GAG_TRACKS:
        problems.append(
            f"{len(carried)} gag tracks, but a toon can train at most "
            f"{MAX_GAG_TRACKS} of the seven")
    total = sum(n for n in gag_counts.values() if n > 0)
    if total > MAX_POUCH:
        problems.append(
            f"{total} gags, but the largest pouch holds {MAX_POUCH}")
    for (track, level), count in sorted(gag_counts.items()):
        if count < 0:
            problems.append(f"{gag(track, level).display}: negative count")
            continue
        limit = gag(track, level).max_carry
        if limit is not None and count > limit:
            problems.append(
                f"{count} x {gag(track, level).display}, but only {limit} "
                f"fit in the pouch")
    return problems


# [CONFIRMED] TTR 3.3.0: a Lure gag can only expire early if its BASE
# accuracy is under this. The lowest in the game is Small Magnet at 55, so
# nothing qualifies and lures run their full duration. Kept as a threshold
# rather than hardcoded False because it is a balance knob.
EARLY_EXPIRY_ACCURACY_FLOOR = 50
