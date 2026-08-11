"""
Cashbot cog attack tables.

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

CASHBOT_COGS = {
    "short_change": {
        "levels": [1, 2, 3, 4, 5],
        "freq": {
            "watercooler":  [20, 20, 20, 20, 20],
            "bounce_check": [15, 15, 15, 15, 15],
            "clip_on_tie":  [25, 25, 25, 25, 25],
            "pick_pocket":  [40, 40, 40, 40, 40],
        },
        "damage": {
            "watercooler":  [ 2,  2,  3,  4,  6],
            "bounce_check": [ 3,  5,  7,  9, 11],
            "clip_on_tie":  [ 1,  1,  2,  2,  3],
            "pick_pocket":  [ 2,  2,  3,  4,  6],
        },
        "accuracy": {
            "watercooler":  [50, 50, 50, 50, 50],
            "bounce_check": [75, 80, 85, 90, 95],
            "clip_on_tie":  [50, 50, 50, 50, 50],
            "pick_pocket":  [95, 95, 95, 95, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "penny_pincher": {
        "levels": [2, 3, 4, 5, 6],
        "freq": {
            "bounce_check":  [45, 45, 45, 45, 45],
            "freeze_assets": [20, 20, 20, 20, 20],
            "finger_wag":    [35, 35, 35, 35, 35],
        },
        "damage": {
            "bounce_check":  [ 4,  5,  6,  8, 12],
            "freeze_assets": [ 2,  3,  4,  6,  9],
            "finger_wag":    [ 1,  2,  3,  4,  6],
        },
        "accuracy": {
            "bounce_check":  [75, 75, 75, 75, 75],
            "freeze_assets": [75, 75, 75, 75, 75],
            "finger_wag":    [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "tightwad": {
        # NOT a transcription error: unlike every other cog, Tightwad's
        #     frequencies are not smooth across levels -- each level has one
        #     attack spiking to 60-75% while the rest sit at 5%, and which attack
        #     spikes moves as the level goes up. Verified against Appendix A cell
        #     by cell; every level still totals 100.
        "levels": [3, 4, 5, 6, 7],
        "freq": {
            "fired":         [75,  5,  5,  5,  5],
            "glower_power":  [10, 15, 20, 25, 30],
            "finger_wag":    [ 5, 70,  5,  5,  5],
            "freeze_assets": [ 5,  5, 65,  5, 30],
            "bounce_check":  [ 5,  5,  5, 60, 30],
        },
        "damage": {
            "fired":         [ 3,  4,  5,  5,  6],
            "glower_power":  [ 3,  4,  6,  9, 12],
            "finger_wag":    [ 3,  3,  4,  4,  5],
            "freeze_assets": [ 3,  4,  6,  9, 12],
            "bounce_check":  [ 5,  6,  9, 13, 18],
        },
        "accuracy": {
            "fired":         [75, 75, 75, 75, 75],
            "glower_power":  [95, 95, 95, 95, 95],
            "finger_wag":    [75, 75, 75, 75, 75],
            "freeze_assets": [75, 75, 75, 75, 75],
            "bounce_check":  [75, 75, 75, 75, 75],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "bean_counter": {
        "levels": [4, 5, 6, 7, 8],
        "freq": {
            "audit":     [20, 20, 20, 20, 20],
            "calculate": [25, 25, 25, 25, 25],
            "tabulate":  [25, 25, 25, 25, 25],
            "write_off": [30, 30, 30, 30, 30],
        },
        "damage": {
            "audit":     [ 4,  6,  9, 12, 15],
            "calculate": [ 4,  6,  9, 12, 15],
            "tabulate":  [ 4,  6,  9, 12, 15],
            "write_off": [ 4,  6,  9, 12, 15],
        },
        "accuracy": {
            "audit":     [95, 95, 95, 95, 95],
            "calculate": [75, 75, 75, 75, 75],
            "tabulate":  [75, 75, 75, 75, 75],
            "write_off": [95, 95, 95, 95, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "number_cruncher": {
        "levels": [5, 6, 7, 8, 9],
        "freq": {
            "audit":     [15, 15, 15, 15, 15],
            "calculate": [30, 30, 30, 30, 30],
            "crunch":    [35, 35, 35, 35, 35],
            "tabulate":  [20, 20, 20, 20, 20],
        },
        "damage": {
            "audit":     [ 5,  6,  8, 10, 12],
            "calculate": [ 6,  7,  9, 11, 13],
            "crunch":    [ 8,  9, 11, 13, 15],
            "tabulate":  [ 5,  6,  7,  8,  9],
        },
        "accuracy": {
            "audit":     [60, 75, 80, 85, 90],
            "calculate": [50, 65, 70, 75, 80],
            "crunch":    [60, 65, 75, 80, 85],
            "tabulate":  [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "money_bags": {
        "levels": [6, 7, 8, 9, 10],
        "freq": {
            "liquidate":    [30, 30, 30, 30, 30],
            "market_crash": [45, 45, 45, 45, 45],
            "power_tie":    [25, 25, 25, 25, 25],
        },
        "damage": {
            "liquidate":    [10, 12, 14, 16, 18],
            "market_crash": [ 8, 10, 12, 14, 16],
            "power_tie":    [ 6,  7,  8,  9, 10],
        },
        "accuracy": {
            "liquidate":    [60, 75, 80, 85, 90],
            "market_crash": [60, 65, 70, 75, 80],
            "power_tie":    [60, 65, 75, 85, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "loan_shark": {
        "levels": [7, 8, 9, 10, 11],
        "freq": {
            "bite":          [30, 30, 30, 30, 30],
            "chomp":         [35, 35, 35, 35, 35],
            "play_hardball": [20, 20, 20, 20, 20],
            "write_off":     [15, 15, 15, 15, 15],
        },
        "damage": {
            "bite":          [10, 11, 13, 15, 16],
            "chomp":         [12, 15, 18, 21, 24],
            "play_hardball": [ 9, 11, 12, 13, 15],
            "write_off":     [ 6,  8, 10, 12, 14],
        },
        "accuracy": {
            "bite":          [60, 75, 80, 85, 90],
            "chomp":         [60, 70, 75, 80, 90],
            "play_hardball": [55, 65, 75, 85, 95],
            "write_off":     [70, 75, 80, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "robber_baron": {
        "levels": [8, 9, 10, 11, 12],
        "freq": {
            "power_trip": [50, 50, 50, 50, 50],
            "tee_off":    [50, 50, 50, 50, 50],
        },
        "damage": {
            "power_trip": [11, 14, 16, 18, 21],
            "tee_off":    [10, 12, 14, 16, 18],
        },
        "accuracy": {
            "power_trip": [60, 65, 70, 75, 80],
            "tee_off":    [60, 65, 75, 85, 90],
        },
        "group_attacks": {"power_trip"},  # [CONFIRMED] Appendix B "Type" column
    },
}
