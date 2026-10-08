"""
Every gag in the game, one `Gag` object each.

Damage, heals, organic values, accuracy, group flag, and (for Lure)
duration in rounds -- all on one object per (track, level), so finding
out what a gag does is one lookup instead of six parallel dicts.

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

SOURCE NOTE -- READ BEFORE ADDING TO data/: this module is TTR wiki
data, not the QED1224 strategy guide, which describes *Toontown Online*
and predates TTR's rebalancing. See docs/data-confidence.md. The wiki
blocks ordinary fetches (403) but serves its MediaWiki API:

    curl "https://toontownrewritten.wiki/api.php?action=parse\\
          &page=Throw&prop=wikitext&format=json"

WHAT THE GUIDE HAD WRONG (corrected here): Sound was off by one level
(the guide's table started at Whistle, missing Bike Horn and level 6
entirely); Trap level 7 is Railroad at 200, not "Train Tracks" at 195
(the pre-3.0.0 value); Drop level 7 is Toontanic at 180, not "Ocean
Liner" (name only, damage unchanged -- both TTO names are absent from
the TTR wiki); and Throw 6 "48-100" / Sound 5 "25-50" had been rejected
as inconsistent but are both real -- 48-100 is Birthday Cake (Throw 6)
correctly, and 25-50 is Foghorn, which is Sound level *6* not 5 (an
artifact of the off-by-one above). Every level-6 gag has a wide range
(Birthday Cake 48-100, Storm Cloud 36-80, Foghorn 25-50, Grand Piano
85-170, TNT 90-180, Juggling Cubes 75-105).

WHERE THE GUIDE WAS RIGHT: of 14 populated damage cells, 12 survive the
wiki check unchanged (Throw 1-5 and 7, Squirt 1 and 7, Sound 7 and Drop
7); only Trap 7 and the Sound column below level 7 were wrong.

TTR REBALANCING HISTORY (from each page's own changelog):
  Sound   -- 4.0.0: carry capacity reduced to Trap's pre-3.0.0 capacity;
             several exp thresholds lowered. No damage change.
  Drop    -- 3.0.0: Safe given a damage *range* (like Grand Piano).
             4.0.0: organic Drop bonus raised 10% -> 15%.
  Trap    -- 3.0.0: Trapdoor 60-70 -> 75-85 (organic "83-93"); Railroad
             195 -> 200 (organic 220); put on the standard carry
             capacity.
             4.0.0: Trap grants +10% accuracy to Lure against a Trapped
             cog; Quicksand exp threshold 800 -> 500.
             4.0.5: Trap activation stun bonus 30% -> 50%; the passive
             10% Lure accuracy bonus now stacks, +5% per extra trap.
  Toon-Up -- 3.0.0: Pixie Dust 60-70 -> 50-60; Juggling Cubes 90-120 ->
             75-105.
             4.0.0: organic Toon-Up bonus raised 10% -> 20%.
  Lure    -- 3.0.0: Presentation 15 -> 8 rounds; Lure Stacking Rounds
             removed (simultaneous Lures no longer accumulate rounds --
             re-luring across rounds also doesn't refresh the counter,
             but that's play knowledge, not wiki-stated; see
             CogStatus.apply_lure).
             3.3.0: Lure gags under 50% base accuracy no longer expire
             early; no current gag is under 50%, so lures always run
             full duration.
             4.0.0: dollar-bill accuracy +10%, multi-Lure +5%,
             Presentation settled at 90%.
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
    # heal=(25, 30) is DERIVED, not read off a page, because the pages
    # disagree -- see the note below the table.
    Gag(Track.TOON_UP, 3, 'Lipstick', accuracy=70, group=False, heal=(25, 30), organic_heal=(30, 36), min_carry=5, max_carry=20),
    Gag(Track.TOON_UP, 4, 'Bamboo Cane', accuracy=70, group=True, heal=(40, 45), organic_heal=(48, 54), min_carry=5, max_carry=15),
    Gag(Track.TOON_UP, 5, 'Pixie Dust', accuracy=70, group=False, heal=(50, 60), organic_heal=(60, 72), min_carry=3, max_carry=7),
    Gag(Track.TOON_UP, 6, 'Juggling Cubes', accuracy=70, group=True, heal=(75, 105), organic_heal=(90, 126), min_carry=3, max_carry=3),
    Gag(Track.TOON_UP, 7, 'High Dive', accuracy=95, group=True, heal=(210, 210), organic_heal=(252, 252), min_carry=1, max_carry=1),

    # --- Trap ------------------------------------------------
    Gag(Track.TRAP, 1, 'Banana Peel', accuracy=0, group=False, damage=(10, 12), organic_damage=(11, 14), min_carry=10, max_carry=30),
    Gag(Track.TRAP, 2, 'Rake', accuracy=0, group=False, damage=(18, 20), organic_damage=(20, 22), min_carry=5, max_carry=25),
    Gag(Track.TRAP, 3, 'Marbles', accuracy=0, group=False, damage=(30, 35), organic_damage=(33, 39), min_carry=5, max_carry=20),
    Gag(Track.TRAP, 4, 'Quicksand', accuracy=0, group=False, damage=(45, 50), organic_damage=(50, 55), min_carry=5, max_carry=15),
    Gag(Track.TRAP, 5, 'Trapdoor', accuracy=0, group=False, damage=(75, 85), organic_damage=(84, 94), min_carry=3, max_carry=7),
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

# Trap 5 (Trapdoor) organic damage: 84-94. The wiki states it three ways
# on an agreed base of 75-85 (Trap page table 83-94, Organic gags page
# and Trapdoor infobox 84-94, Trap page 3.0.0 changelog 83-93). The max
# (94) is undisputed by three of four sources. The min took two
# attempts: deriving it via ceil(base * (100+pct)/100) gives 83 and
# matches 67 of 68 organic values here, but the one exception (Squirt 4
# below) shows that same formula under-reading a minimum by exactly one
# -- so the derivation isn't trusted over two sources saying 84.
# Transcription wins: 84-94. Cross-check: the Organic gags page says "a
# level 8 Cog can be defeated with an organic Trapdoor" (90 hp); 94
# clears it, 83 would not have.

# Toon-Up 3 (Lipstick) heal = (25, 30). [CONFIRMED] by the Lipstick
# page's own infobox (`minheal=25 | maxheal=30 | organic=30-36`), though
# the Toon-Up and Organic gags SUMMARY tables wrongly say 27-30. (It's
# also derivable: `organic = ceil(1.2 x base)` holds for the other six
# Toon-Up gags and inverts (30, 36) to (25, 30) uniquely -- but check the
# gag's own page before trusting a summary table.)

# Lure 7 (Presentation) organic accuracy: 100. The Organic gags page
# contradicts itself -- prose says Lure gains "a flat increase of 10%
# (except Presentation, which increases by 5%)" (=95), but its own table
# and the Presentation infobox both say 100. Tables win per project
# convention. Moot in play either way: a maxed toon hits the 95 cap on
# Presentation before organic applies at all.

# Squirt 4 (Seltzer Bottle) is a real exception to the organic rule:
# base 18-21 -> organic 22-25 per three sources, while the 15% rule
# gives 21-25. Kept as stated -- evidence the formula is an
# approximation, not a law (what settled Trapdoor above).

_BY_KEY: Dict[Tuple[Track, int], Gag] = {g.key: g for g in GAGS}


def gag(track: Track, level: int) -> Gag:
    """The Gag for a (track, level). Raises KeyError for a level outside 1-7."""
    try:
        return _BY_KEY[(track, level)]
    except KeyError:
        # `track` is None for a pass, which has no gag. Formatting
        # `track.value` there raised AttributeError from inside the
        # error path, so the real problem arrived disguised.
        name = track.value if track is not None else "no track (a pass)"
        raise KeyError(f"no gag at {name} level {level}") from None


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

# Level 7 gags are carried outside the pouch and do not count towards its
# total. [CONFIRMED] three ways: the wiki gives level 7s their own limit
# (one each, +1 more via a Ripley ToonTask); a live gag menu showing 75
# carried gags displayed "Total gags 70 / 70", the difference being
# exactly the five level 7s held; and the player confirmed it directly.
# Counting them in was rejecting legal loadouts: a full 80-gag pouch plus
# one level 7 per track came back as "86 gags, but the largest pouch
# holds 80".
POUCH_EXEMPT_LEVEL = 7


# ---------------------------------------------------------------------
# Per-gag carry limits, by how far the track is trained
# ---------------------------------------------------------------------
# A gag's carry limit is not fixed: it rises as you unlock LATER gags in
# the same track. `Gag.min_carry`/`max_carry` are only the two endpoints;
# this table interpolates between them.
#
# [OPEN TOONTOWN SOURCE] `ToontownBattleGlobals.CarryLimits` -- the
# algorithm rather than a description of one, never [CONFIRMED], but the
# wiki corroborates it strongly: each table's DIAGONAL reproduces the
# repo's `min_carry` values and its BOTTOM ROW reproduces `max_carry`,
# both read from the gags' own wiki infoboxes, for all six tracks. See
# tests/test_carry_limits.py, which asserts it rather than trusting this
# comment.
#
# NOTE ON MEASURING A CHANGE LIKE THIS: threading these limits through
# the samplers changes which loadouts toons get, so it changes the
# BUILDINGS -- clear rates before and after are not the same population
# and are not comparable (one set moved 60.8% -> 67.5% and read as a
# gain; it wasn't one). What justifies this table is that it's right,
# not that it scores better on a benchmark it has itself invalidated.
#
# Rows are the highest gag unlocked in the track (1-6), columns are the
# gag's own level (1-6). Unlocking level 7 does not raise the others --
# Open Toontown's seventh row equals its sixth across these columns.
_CARRY_STANDARD = (
    (10,  0,  0,  0, 0, 0),
    (10,  5,  0,  0, 0, 0),
    (15, 10,  5,  0, 0, 0),
    (20, 15, 10,  5, 0, 0),
    (25, 20, 15, 10, 3, 0),
    (30, 25, 20, 15, 7, 3),
)

# TTR rebalanced two tracks in opposite directions, and the wiki records
# both. Trap was BUFFED onto the standard table ("Trap now shares the
# same carry capacity with other gag tracks"), confirmed on all six
# levels, so Trap is not listed here. Sound was NERFED onto Trap's OLD
# numbers, across the whole row: 5 Elephant Trunks and 2 Foghorns at the
# top, 20/15/15/10 below them.
_CARRY_SOUND = (
    ( 5,  0,  0,  0, 0, 0),
    ( 7,  3,  0,  0, 0, 0),
    (10,  7,  3,  0, 0, 0),
    (15, 10,  7,  3, 0, 0),
    (15, 15, 10,  5, 3, 0),
    (20, 15, 15, 10, 5, 2),
)


def carry_limit(track, level: int, unlocked: int) -> int:
    """How many of this gag a toon trained to `unlocked` may hold.

    `unlocked` is the toon's training level in the track, 1-7, which is
    what `ToonState.track_exp` stores.

    Level 7 is always 1 and never scales: it is earned through the
    Sellbot Task Force rather than by training the track, and the one
    ToonTask that raises it is rare enough that modelling the increase
    would describe almost nobody.
    """
    if unlocked <= 0 or level > unlocked:
        return 0
    if level >= POUCH_EXEMPT_LEVEL:
        return 1
    table = _CARRY_SOUND if getattr(track, "value", track) == "sound" \
        else _CARRY_STANDARD
    return table[min(unlocked, 6) - 1][level - 1]


def pouch_total(gag_counts) -> int:
    """Gags counting against the pouch: everything below level 7.

    This is the number the gag menu prints as "Total gags", so it also
    serves as a checksum on anything that reads the menu off the screen.
    """
    return sum(n for (_track, level), n in gag_counts.items()
               if n > 0 and level < POUCH_EXEMPT_LEVEL)


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
    total = pouch_total(gag_counts)
    if total > MAX_POUCH:
        problems.append(
            f"{total} pouch gags, but the largest pouch holds {MAX_POUCH}")
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


# Skill points required to unlock each gag, by track and level.
#
# [CONFIRMED] TTR wiki (Skill points, "Required skill points"). A track
# is fully maxed at 10,000 skill points, which is also the level 7
# threshold -- the last gag unlocks exactly as the bar fills.
#
# This is `minE` in `mechanics.gag_damage_from_exp`: the experience at
# which a gag becomes available and its damage starts climbing.
# Transcribed here because damage in the real game is a deterministic
# step function of track experience, not the linear interpolation
# `mechanics.DAMAGE_TRAINED_FRACTION` stands in for.
#
# `maxE`, where a gag's damage stops climbing, is the NEXT gag's
# threshold. [CONFIRMED] -- every gag infobox carries `prevexp`/`nextexp`
# and `nextexp` IS this number; checked on four tracks (Cupcake, Whole
# Cream Pie, Big Magnet, Foghorn/Grand Piano). Level 7 needs no window:
# those gags have a single fixed damage (min equals max), so the
# zero-width window at 10,000 is harmless.
#
# The widest windows are at level 6 -- Birthday Cake spans 48-100, Grand
# Piano 85-170 -- so that's where training actually decides the damage,
# and where a stand-in of 1.0 flatters an under-trained toon most.
GAG_UNLOCK_EXP = {
    Track.TOON_UP: (
             0,   # 1  Feather
            20,   # 2  Megaphone
           200,   # 3  Lipstick
           800,   # 4  Bamboo Cane
          2000,   # 5  Pixie Dust
          6000,   # 6  Juggling Cubes
         10000,   # 7  High Dive
    ),
    Track.TRAP: (
             0,   # 1  Banana Peel
            20,   # 2  Rake
           100,   # 3  Marbles
           500,   # 4  Quicksand
          2000,   # 5  Trapdoor
          6000,   # 6  TNT
         10000,   # 7  Railroad
    ),
    Track.LURE: (
             0,   # 1  $1 Bill
            20,   # 2  Small Magnet
           100,   # 3  $5 Bill
           800,   # 4  Big Magnet
          2000,   # 5  $10 Bill
          6000,   # 6  Hypno-goggles
         10000,   # 7  Presentation
    ),
    Track.SOUND: (
             0,   # 1  Bike Horn
            20,   # 2  Whistle
           200,   # 3  Bugle
           800,   # 4  Aoogah
          2000,   # 5  Elephant Trunk
          6000,   # 6  Foghorn
         10000,   # 7  Opera Singer
    ),
    Track.THROW: (
             0,   # 1  Cupcake
            10,   # 2  Fruit Pie Slace
            50,   # 3  Cream Pie Slice
           400,   # 4  Whole Fruit Pie
          2000,   # 5  Whole Cream Pie
          6000,   # 6  Birthday Cake
         10000,   # 7  Wedding Cake
    ),
    Track.SQUIRT: (
             0,   # 1  Squirting Flower
            10,   # 2  Glass of Water
            50,   # 3  Squirt Gun
           400,   # 4  Seltzer Bottle
          2000,   # 5  Fire Hose
          6000,   # 6  Storm Cloud
         10000,   # 7  Geyser
    ),
    Track.DROP: (
             0,   # 1  Flower Pot
            20,   # 2  Sandbag
           100,   # 3  Anvil
           500,   # 4  Big Weight
          2000,   # 5  Safe
          6000,   # 6  Grand Piano
         10000,   # 7  Toontanic
    ),
}

TRACK_MAX_EXP = 10_000        # [CONFIRMED] "fully maxed after 10,000"


def gag_unlock_exp(track: Track, level: int) -> int:
    """Skill points needed before this gag is available. [CONFIRMED]."""
    return GAG_UNLOCK_EXP[track][level - 1]


def gag_exp_window(track: Track, level: int):
    """(minE, maxE) -- the experience over which this gag's damage
    climbs from its minimum to its maximum.

    Both ends are [CONFIRMED]: the gag infobox's `prevexp` is minE and
    its `nextexp` is maxE. Level 7 returns a zero-width window, which is
    correct rather than degenerate: those gags have one fixed damage.

    Feeds `mechanics.gag_damage_from_exp`. Nothing calls it in the
    damage path, and that is a DECISION rather than unfinished work:
    wiring it up means `ToonState.track_exp` holding real experience
    instead of a 0-7 training level, which reaches into the live
    readers, for a payoff that's niche (advising a toon whose bar is
    mid-window) when most toons advised are maxed or near it. For
    testing and strategy work, `DAMAGE_TRAINED_FRACTION` is the better
    tool anyway -- sweeping one number answers "how much does this
    depend on being maxed" directly.

    Transcribed, correct, and deliberately unused. Do not "finish" it
    without a live case that needs it.
    """
    low = gag_unlock_exp(track, level)
    if level >= 7:
        return low, low
    return low, gag_unlock_exp(track, level + 1)
