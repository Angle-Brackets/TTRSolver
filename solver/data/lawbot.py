"""
Lawbot cog attack tables.

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

LAWBOT_COGS = {
    "bottom_feeder": {
        "levels": [1, 2, 3, 4, 5],
        "freq": {
            "rubber_stamp": [20, 20, 20, 20, 20],
            "shred":        [20, 20, 20, 20, 20],
            "watercooler":  [10, 10, 10, 10, 10],
            "pick_pocket":  [50, 50, 50, 50, 50],
        },
        "damage": {
            "rubber_stamp": [ 2,  3,  4,  5,  6],
            "shred":        [ 2,  4,  6,  8, 10],
            "watercooler":  [ 3,  4,  5,  6,  7],
            "pick_pocket":  [ 1,  1,  2,  2,  3],
        },
        "accuracy": {
            "rubber_stamp": [75, 80, 85, 90, 95],
            "shred":        [50, 55, 60, 65, 70],
            "watercooler":  [95, 95, 95, 95, 95],
            "pick_pocket":  [25, 30, 35, 40, 45],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "bloodsucker": {
        # [!] Appendix A spells this attack "Withdrawl"; B and C spell it
        #     "Withdrawal". Key uses the B/C spelling.
        "levels": [2, 3, 4, 5, 6],
        "freq": {
            "eviction_notice": [20, 20, 20, 20, 20],
            "red_tape":        [20, 20, 20, 20, 20],
            "withdrawal":      [10, 10, 10, 10, 10],
            "liquidate":       [50, 50, 50, 50, 50],
        },
        "damage": {
            "eviction_notice": [ 1,  2,  3,  3,  4],
            "red_tape":        [ 2,  3,  4,  6,  9],
            "withdrawal":      [ 6,  8, 10, 12, 14],
            "liquidate":       [ 2,  3,  4,  6,  9],
        },
        "accuracy": {
            "eviction_notice": [75, 75, 75, 75, 75],
            "red_tape":        [75, 75, 75, 75, 75],
            "withdrawal":      [95, 95, 95, 95, 95],
            "liquidate":       [50, 60, 70, 80, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "double_talker": {
        # [!] Appendix A spells this "Buzzword", B and C "Buzz Word". Key is
        #     buzz_word everywhere in this package.
        "levels": [3, 4, 5, 6, 7],
        "freq": {
            "rubber_stamp": [ 5,  5,  5,  5,  5],
            "bounce_check": [ 5,  5,  5,  5,  5],
            "buzz_word":    [20, 20, 20, 20, 20],
            "double_talk":  [25, 25, 25, 25, 25],
            "jargon":       [25, 25, 25, 25, 25],
            "mumbo_jumbo":  [20, 20, 20, 20, 20],
        },
        "damage": {
            "rubber_stamp": [ 1,  1,  1,  1,  1],
            "bounce_check": [ 1,  1,  1,  1,  1],
            "buzz_word":    [ 1,  2,  3,  5,  6],
            "double_talk":  [ 6,  6,  9, 13, 18],
            "jargon":       [ 3,  4,  6,  9, 12],
            "mumbo_jumbo":  [ 3,  4,  6,  9, 12],
        },
        "accuracy": {
            "rubber_stamp": [50, 60, 70, 80, 90],
            "bounce_check": [50, 60, 70, 80, 90],
            "buzz_word":    [50, 60, 70, 80, 90],
            "double_talk":  [50, 60, 70, 80, 90],
            "jargon":       [50, 60, 70, 80, 90],
            "mumbo_jumbo":  [50, 60, 70, 80, 90],
        },
        "group_attacks": {"buzz_word"},  # [CONFIRMED] Appendix B "Type" column
    },
    "ambulance_chaser": {
        "levels": [4, 5, 6, 7, 8],
        "freq": {
            "shake":    [15, 15, 15, 15, 15],
            "red_tape": [30, 30, 30, 30, 30],
            "rolodex":  [20, 20, 20, 20, 20],
            "hang_up":  [35, 35, 35, 35, 35],
        },
        "damage": {
            "shake":    [ 4,  6,  9, 12, 15],
            "red_tape": [ 6,  8, 12, 15, 19],
            "rolodex":  [ 3,  4,  5,  6,  7],
            "hang_up":  [ 2,  3,  4,  5,  6],
        },
        "accuracy": {
            "shake":    [75, 75, 75, 75, 75],
            "red_tape": [75, 75, 75, 75, 75],
            "rolodex":  [75, 75, 75, 75, 75],
            "hang_up":  [75, 75, 75, 75, 75],
        },
        "group_attacks": {"shake"},  # [CONFIRMED] Appendix B "Type" column
    },
    "backstabber": {
        "levels": [5, 6, 7, 8, 9],
        "freq": {
            "guilt_trip":        [40, 40, 40, 40, 40],
            "restraining_order": [25, 25, 25, 25, 25],
            "finger_wag":        [35, 35, 35, 35, 35],
        },
        "damage": {
            "guilt_trip":        [ 8, 11, 13, 15, 18],
            "restraining_order": [ 6,  7,  9, 11, 13],
            "finger_wag":        [ 5,  6,  7,  8,  9],
        },
        "accuracy": {
            "guilt_trip":        [60, 75, 80, 85, 90],
            "restraining_order": [50, 65, 70, 75, 90],
            "finger_wag":        [50, 55, 65, 75, 80],
        },
        "group_attacks": {"guilt_trip"},  # [CONFIRMED] Appendix B "Type" column
    },
    "spin_doctor": {
        # [!] Appendix C lists a 5th attack for Spin Doctor, "Rolodex"
        #     (60/65/70/75/80), that Appendices A and B do not list at all. Omitted:
        #     the four frequencies below already sum to 100 at every level, so a 5th
        #     attack could never be selected. Flagged rather than invented.
        "levels": [6, 7, 8, 9, 10],
        "freq": {
            "paradigm_shift": [30, 30, 30, 30, 30],
            "quake":          [20, 20, 20, 20, 20],
            "spin":           [35, 35, 35, 35, 35],
            "write_off":      [15, 15, 15, 15, 15],
        },
        "damage": {
            "paradigm_shift": [ 9, 10, 13, 16, 17],
            "quake":          [ 8, 10, 12, 14, 16],
            "spin":           [10, 12, 15, 18, 20],
            "write_off":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {
            "paradigm_shift": [60, 75, 80, 85, 90],
            "quake":          [60, 65, 70, 75, 80],
            "spin":           [70, 75, 80, 85, 90],
            "write_off":      [60, 65, 75, 85, 90],
        },
        "group_attacks": {"paradigm_shift", "quake"},  # [CONFIRMED] Appendix B "Type" column
    },
    "legal_eagle": {
        "levels": [7, 8, 9, 10, 11],
        "freq": {
            "evil_eye":      [20, 20, 20, 20, 20],
            "jargon":        [15, 15, 15, 15, 15],
            "legalese":      [35, 35, 35, 35, 35],
            "pecking_order": [30, 30, 30, 30, 30],
        },
        "damage": {
            "evil_eye":      [10, 11, 13, 15, 16],
            "jargon":        [ 7,  9, 11, 13, 15],
            "legalese":      [11, 13, 16, 19, 21],
            "pecking_order": [12, 15, 17, 19, 22],
        },
        "accuracy": {
            "evil_eye":      [60, 75, 80, 85, 90],
            "jargon":        [60, 70, 75, 80, 90],
            "legalese":      [55, 65, 75, 85, 95],
            "pecking_order": [70, 75, 80, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "big_wig": {
        "levels": [8, 9, 10, 11, 12],
        "freq": {
            "power_trip": [50, 50, 50, 50, 50],
            "finger_wag": [50, 50, 50, 50, 50],
        },
        "damage": {
            "power_trip": [10, 11, 13, 15, 16],
            "finger_wag": [13, 15, 17, 19, 21],
        },
        "accuracy": {
            "power_trip": [75, 80, 85, 90, 95],
            "finger_wag": [80, 85, 85, 85, 90],
        },
        "group_attacks": {"power_trip"},  # [CONFIRMED] Appendix B "Type" column
    },
}
