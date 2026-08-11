"""
Sellbot cog attack tables.

Each cog entry:
  "levels":        list of absolute levels this cog can appear at; index
                   into the per-attack lists is (cog.level - levels[0])
  "freq":          {attack_name: [freq% at each relative level]}
  "damage":        {attack_name: [(min,max) or fixed int, at each relative level]}
  "accuracy":      {attack_name: [accuracy% at each relative level]}
  "group_attacks": set of attack names that hit all toons

Source: QED1224/Toontown-Resources strategy-guide README, **master branch**
(the default branch has dropped the appendices) -- Appendix A for freq,
Appendix B for damage, Appendix C for accuracy. "group_attacks" comes from
Appendix B's Single/Group "Type" column, not from guesswork.

[CONFIRMED] except where noted: every number below was transcribed
mechanically from those tables and cross-checked (frequencies sum to
100 at every level; freq/damage/accuracy key sets and lengths agree).

A `None` in an otherwise-filled list is a per-cell [TODO]: the guide's value
for that one cell is missing or self-contradictory, and it was left blank
rather than guessed at. Those cells are called out in comments where they
appear. mechanics.cog_attack_damage_and_accuracy only null-checks the table
as a whole, so a None cell surfaces as a TypeError at use time -- loud, which
is the intent; it must never be silently replaced with a plausible number.
"""

SELLBOT_COGS = {
    "cold_caller": {
        "levels": [1, 2, 3, 4, 5],
        "freq": {
            "freeze_assets": [ 5, 10, 15, 20, 25],
            "pound_key":     [25, 25, 25, 25, 25],
            "double_talk":   [25, 25, 25, 25, 25],
            "hot_air":       [45, 40, 35, 30, 25],
        },
        "damage": {
            "freeze_assets": [ 1,  1,  1,  1,  1],
            "pound_key":     [ 2,  2,  3,  4,  5],
            "double_talk":   [ 2,  3,  4,  6,  8],
            "hot_air":       [ 3,  4,  6,  8, 10],
        },
        "accuracy": {
            "freeze_assets": [90, 90, 90, 90, 90],
            "pound_key":     [75, 80, 85, 90, 95],
            "double_talk":   [50, 55, 60, 65, 70],
            "hot_air":       [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "telemarketer": {
        "levels": [2, 3, 4, 5, 6],
        "freq": {
            "clip_on_tie": [15, 15, 15, 15, 15],
            "pick_pocket": [15, 15, 15, 15, 15],
            "rolodex":     [30, 30, 30, 30, 30],
            "double_talk": [40, 40, 40, 40, 40],
        },
        "damage": {
            "clip_on_tie": [ 2,  2,  3,  3,  4],
            "pick_pocket": [ 1,  1,  1,  1,  1],
            "rolodex":     [ 4,  6,  7,  9, 12],
            "double_talk": [ 4,  6,  7,  9, 12],
        },
        "accuracy": {
            "clip_on_tie": [75, 75, 75, 75, 75],
            "pick_pocket": [75, 75, 75, 75, 75],
            "rolodex":     [50, 50, 50, 50, 50],
            "double_talk": [75, 80, 85, 90, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "name_dropper": {
        "levels": [3, 4, 5, 6, 7],
        "freq": {
            "razzle_dazzle": [30, 30, 30, 30, 30],
            "rolodex":       [40, 40, 40, 40, 40],
            "synergy":       [15, 15, 15, 15, 15],
            "pick_pocket":   [15, 15, 15, 15, 15],
        },
        "damage": {
            "razzle_dazzle": [ 4,  5,  6,  9, 12],
            "rolodex":       [ 5,  6,  7, 10, 14],
            "synergy":       [ 3,  4,  6,  9, 12],
            "pick_pocket":   [ 2,  2,  2,  2,  2],
        },
        "accuracy": {
            "razzle_dazzle": [75, 80, 85, 90, 95],
            "rolodex":       [95, 95, 95, 95, 95],
            "synergy":       [50, 50, 50, 50, 50],
            "pick_pocket":   [95, 95, 95, 95, 95],
        },
        "group_attacks": {"synergy"},  # [CONFIRMED] Appendix B "Type" column
    },
    "glad_hander": {
        "levels": [4, 5, 6, 7, 8],
        "freq": {
            "rubber_stamp": [40, 30, 20, 10,  5],
            "fountain_pen": [40, 30, 20, 10,  5],
            "filibuster":   [10, 20, 30, 40, 45],
            "schmooze":     [10, 20, 30, 40, 45],
        },
        "damage": {
            "rubber_stamp": [ 4,  3,  3,  2,  1],
            "fountain_pen": [ 3,  3,  2,  1,  1],
            "filibuster":   [ 4,  6,  9, 12, 15],
            "schmooze":     [ 5,  7, 11, 15, 20],
        },
        "accuracy": {
            "rubber_stamp": [90, 70, 50, 30, 10],
            "fountain_pen": [70, 60, 50, 40, 30],
            "filibuster":   [30, 40, 50, 60, 70],
            "schmooze":     [55, 65, 75, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "mover_and_shaker": {
        "levels": [5, 6, 7, 8, 9],
        "freq": {
            "brain_storm":  [15, 15, 15, 15, 15],
            "half_windsor": [20, 20, 20, 20, 20],
            "quake":        [20, 20, 20, 20, 20],
            "shake":        [25, 25, 25, 25, 25],
            "tremor":       [20, 20, 20, 20, 20],
        },
        "damage": {
            "brain_storm":  [ 5,  6,  8, 10, 12],
            "half_windsor": [ 6,  9, 11, 13, 16],
            "quake":        [ 9, 12, 15, 18, 21],
            "shake":        [ 6,  8, 10, 12, 14],
            "tremor":       [ 5,  6,  7,  8,  9],
        },
        "accuracy": {
            "brain_storm":  [60, 75, 80, 85, 90],
            "half_windsor": [50, 65, 70, 75, 80],
            "quake":        [60, 65, 75, 80, 85],
            "shake":        [70, 75, 80, 85, 90],
            "tremor":       [50, 50, 50, 50, 50],
        },
        "group_attacks": {"quake", "shake", "tremor"},  # [CONFIRMED] Appendix B "Type" column
    },
    "two_face": {
        "levels": [6, 7, 8, 9, 10],
        "freq": {
            "evil_eye":      [30, 30, 30, 30, 30],
            "hang_up":       [15, 15, 15, 15, 15],
            "razzle_dazzle": [30, 30, 30, 30, 30],
            "red_tape":      [25, 25, 25, 25, 25],
        },
        "damage": {
            "evil_eye":      [10, 12, 14, 16, 18],
            "hang_up":       [ 7,  8, 10, 12, 13],
            "razzle_dazzle": [ 8, 10, 12, 14, 16],
            "red_tape":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {
            "evil_eye":      [60, 75, 80, 85, 90],
            "hang_up":       [50, 60, 70, 80, 90],
            "razzle_dazzle": [60, 65, 70, 75, 80],
            "red_tape":      [60, 65, 75, 85, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "the_mingler": {
        "levels": [7, 8, 9, 10, 11],
        "freq": {
            "buzz_word":      [20, 20, 20, 20, 20],
            "paradigm_shift": [25, 25, 25, 25, 25],
            "power_trip":     [15, 15, 15, 15, 15],
            "schmooze":       [30, 30, 30, 30, 30],
            "tee_off":        [10, 10, 10, 10, 10],
        },
        "damage": {
            "buzz_word":      [10, 11, 13, 15, 16],
            "paradigm_shift": [12, 15, 18, 21, 24],
            "power_trip":     [10, 13, 14, 15, 18],
            "schmooze":       [ 7,  8, 12, 15, 16],
            "tee_off":        [ 8,  9, 10, 11, 12],
        },
        "accuracy": {
            "buzz_word":      [60, 75, 80, 85, 90],
            "paradigm_shift": [60, 70, 75, 80, 90],
            "power_trip":     [60, 65, 70, 75, 80],
            "schmooze":       [55, 65, 75, 85, 95],
            "tee_off":        [70, 75, 80, 85, 95],
        },
        "group_attacks": {"paradigm_shift", "power_trip"},  # [CONFIRMED] Appendix B "Type" column
    },
    "mr_hollywood": {
        "levels": [8, 9, 10, 11, 12],
        "freq": {
            "power_trip":    [50, 50, 50, 50, 50],
            "razzle_dazzle": [50, 50, 50, 50, 50],
        },
        "damage": {
            "power_trip":    [10, 12, 15, 18, 20],
            "razzle_dazzle": [ 8, 11, 14, 17, 20],
        },
        "accuracy": {
            "power_trip":    [55, 65, 75, 85, 95],
            "razzle_dazzle": [70, 75, 85, 90, 95],
        },
        "group_attacks": {"power_trip"},  # [CONFIRMED] Appendix B "Type" column
    },
}
