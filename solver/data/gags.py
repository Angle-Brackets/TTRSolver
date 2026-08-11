"""
Gag damage: (min, max) by (track, level). Level 7 gags deal a single
fixed value and hit all cogs.

[PARTIAL] -- cells marked None are TODO. Where present, taken from
cross-referenced wiki tables (not yet verified against the source code's
exp-based formula in mechanics.gag_damage_from_exp).
"""
from ..state import Track

GAG_DAMAGE_MINMAX = {
    Track.THROW: {
        1: (4, 6),      # Cupcake
        2: (8, 10),     # Fruit Pie Slice
        3: (14, 17),    # Cream Pie Slice
        4: (24, 27),    # Whole Fruit Pie
        5: (36, 40),    # Whole Cream Pie
        6: None,        # TODO: source figure (48-100) looked internally
                         # inconsistent with the level 1-5 progression --
                         # re-verify before use
        7: (120, 120),  # Wedding Cake (group)
    },
    Track.SQUIRT: {
        1: (3, 4),      # Squirting Flower -- TODO, only partial figure found
        2: None, 3: None, 4: None, 5: None, 6: None,
        7: (105, 105),  # Geyser (group)
    },
    Track.SOUND: {
        1: (5, 7), 2: (9, 11), 3: (14, 16), 4: (19, 21),
        5: None,        # TODO: source figure (25-50) looked inconsistent
        6: None,
        7: (90, 90),    # Opera Singer (group)
    },
    Track.DROP: {
        1: None, 2: None, 3: None, 4: None, 5: None, 6: None,  # TODO
        7: (180, 180),  # Ocean Liner (group)
    },
    Track.TRAP: {
        # Individual trap gag damages (Banana Peel .. TNT) TODO.
        7: (195, 195),  # Train Tracks (group)
    },
    Track.TOON_UP: {},  # heals, not damage -- TODO, see docs/data-confidence.md
}
