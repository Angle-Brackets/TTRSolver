"""
Bossbot cog attack tables.

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

[PARTIAL] two per-cell gaps -- micromanager/brain_storm accuracy and
the_big_cheese/glower_power damage+accuracy. See the comments inline.

A `None` in an otherwise-filled list is a per-cell [TODO]: the guide's value
for that one cell is missing or self-contradictory, and it was left blank
rather than guessed at. Those cells are called out in comments where they
appear. mechanics.cog_attack_damage_and_accuracy only null-checks the table
as a whole, so a None cell surfaces as a TypeError at use time -- loud, which
is the intent; it must never be silently replaced with a plausible number.
"""

BOSSBOT_COGS = {
    "flunky": {
        "levels": [1, 2, 3, 4, 5],
        "freq": {
            "pound_key":   [30, 35, 40, 45, 50],
            "shred":       [10, 15, 20, 25, 30],
            "clip_on_tie": [60, 50, 40, 30, 20],
        },
        "damage": {
            "pound_key":   [2, 2, 3, 4, 6],
            "shred":       [3, 4, 5, 6, 7],
            "clip_on_tie": [1, 1, 2, 2, 3],
        },
        "accuracy": {
            "pound_key":   [75, 75, 80, 80, 90],
            "shred":       [50, 55, 60, 65, 70],
            "clip_on_tie": [75, 80, 85, 90, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "pencil_pusher": {
        # [!] Appendices A and C call this attack "Fountain Pencil"; Appendix B
        #     calls it "Fountain Pen". Same row position in all three tables, so
        #     the numbers are unambiguous -- only the display name conflicts.
        #     Key kept as fountain_pen (Appendix B, and the name the guide uses
        #     for this attack on every other cog).
        "levels": [2, 3, 4, 5, 6],
        "freq": {
            "fountain_pen":   [20, 20, 20, 20, 20],
            "rub_out":        [20, 20, 20, 20, 20],
            "finger_wag":     [35, 30, 25, 20, 15],
            "write_off":      [ 5, 10, 15, 20, 25],
            "fill_with_lead": [20, 20, 20, 20, 20],
        },
        "damage": {
            "fountain_pen":   [ 2,  3,  4,  6,  9],
            "rub_out":        [ 4,  5,  6,  8, 12],
            "finger_wag":     [ 1,  2,  2,  3,  4],
            "write_off":      [ 4,  6,  8, 10, 12],
            "fill_with_lead": [ 3,  4,  5,  6,  7],
        },
        "accuracy": {
            "fountain_pen":   [75, 75, 75, 75, 75],
            "rub_out":        [75, 75, 75, 75, 75],
            "finger_wag":     [75, 75, 75, 75, 75],
            "write_off":      [75, 75, 75, 75, 75],
            "fill_with_lead": [75, 75, 75, 75, 75],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "yesman": {
        "levels": [3, 4, 5, 6, 7],
        "freq": {
            "rubber_stamp":  [35, 35, 35, 35, 35],
            "razzle_dazzle": [25, 20, 15, 10,  5],
            "synergy":       [ 5, 10, 15, 20, 25],
            "tee_off":       [35, 35, 35, 35, 35],
        },
        "damage": {
            "rubber_stamp":  [2, 2, 3, 3, 4],
            "razzle_dazzle": [1, 1, 1, 1, 1],
            "synergy":       [4, 5, 6, 7, 8],
            "tee_off":       [3, 3, 4, 4, 5],
        },
        "accuracy": {
            "rubber_stamp":  [75, 75, 75, 75, 75],
            "razzle_dazzle": [50, 50, 50, 50, 50],
            "synergy":       [50, 60, 70, 80, 90],
            "tee_off":       [50, 60, 70, 80, 90],
        },
        "group_attacks": {"synergy"},  # [CONFIRMED] Appendix B "Type" column
    },
    "micromanager": {
        # [TODO] brain_storm accuracy: the source lists a flat 5 at every level
        #     while all four other Micromanager attacks run 50/60/70/80/90, and no
        #     other attack anywhere in Appendix C is below 10. Left None rather
        #     than "correcting" it to 50 -- needs a second source.
        "levels": [4, 5, 6, 7, 8],
        "freq": {
            "demotion":     [30, 30, 30, 30, 30],
            "finger_wag":   [10, 10, 10, 10, 10],
            "fountain_pen": [15, 15, 15, 15, 15],
            "brain_storm":  [25, 25, 25, 25, 25],
            "buzz_word":    [20, 20, 20, 20, 20],
        },
        "damage": {
            "demotion":     [ 6,  8, 12, 15, 18],
            "finger_wag":   [ 4,  6,  9, 12, 15],
            "fountain_pen": [ 3,  4,  6,  8, 10],
            "brain_storm":  [ 4,  6,  9, 12, 15],
            "buzz_word":    [ 4,  6,  9, 12, 15],
        },
        "accuracy": {
            "demotion":     [  50,   60,   70,   80,   90],
            "finger_wag":   [  50,   60,   70,   80,   90],
            "fountain_pen": [  50,   60,   70,   80,   90],
            "brain_storm":  [None, None, None, None, None],
            "buzz_word":    [  50,   60,   70,   80,   90],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "downsizer": {
        # [!] Appendices A and C spell this "Pinkslip", Appendix B "Pink Slip".
        "levels": [5, 6, 7, 8, 9],
        "freq": {
            "canned":    [25, 25, 25, 25, 25],
            "downsize":  [35, 35, 35, 35, 35],
            "pink_slip": [25, 25, 25, 25, 25],
            "sacked":    [15, 15, 15, 15, 15],
        },
        "damage": {
            "canned":    [ 5,  6,  8, 10, 12],
            "downsize":  [ 8,  9, 11, 13, 15],
            "pink_slip": [ 4,  5,  6,  7,  8],
            "sacked":    [ 5,  6,  7,  8,  9],
        },
        "accuracy": {
            "canned":    [60, 75, 80, 85, 90],
            "downsize":  [50, 65, 70, 75, 80],
            "pink_slip": [60, 65, 75, 80, 85],
            "sacked":    [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "head_hunter": {
        "levels": [6, 7, 8, 9, 10],
        "freq": {
            "fountain_pen": [15, 15, 15, 15, 15],
            "glower_power": [20, 20, 20, 20, 20],
            "half_windsor": [20, 20, 20, 20, 20],
            "head_shrink":  [35, 35, 35, 35, 35],
            "rolodex":      [10, 10, 10, 10, 10],
        },
        "damage": {
            "fountain_pen": [ 5,  6,  8, 10, 12],
            "glower_power": [ 7,  8, 10, 12, 13],
            "half_windsor": [ 8, 10, 12, 14, 16],
            "head_shrink":  [10, 12, 15, 18, 21],
            "rolodex":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {
            "fountain_pen": [60, 75, 80, 85, 90],
            "glower_power": [50, 60, 70, 80, 90],
            "half_windsor": [60, 65, 70, 75, 80],
            "head_shrink":  [65, 75, 80, 85, 95],
            "rolodex":      [60, 65, 70, 75, 80],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "corporate_raider": {
        # [!] 4th attack name conflicts: Appendices A and C say "Rolodex",
        #     Appendix B says "Power Tie". It is the 4th row of a 4-row table in
        #     all three appendices, so the numbers pair up unambiguously; only the
        #     name is in dispute. Key follows the 2-of-3 majority (rolodex); the
        #     damage row below is the one Appendix B labels "Power Tie".
        "levels": [7, 8, 9, 10, 11],
        "freq": {
            "canned":        [20, 20, 20, 20, 20],
            "evil_eye":      [35, 35, 35, 35, 35],
            "play_hardball": [30, 30, 30, 30, 30],
            "rolodex":       [15, 15, 15, 15, 15],
        },
        "damage": {
            "canned":        [ 6,  7,  8,  9, 10],
            "evil_eye":      [12, 15, 18, 21, 24],
            "play_hardball": [ 7,  8, 12, 15, 16],
            "rolodex":       [10, 12, 14, 16, 18],
        },
        "accuracy": {
            "canned":        [60, 75, 80, 85, 90],
            "evil_eye":      [60, 70, 75, 80, 90],
            "play_hardball": [60, 65, 70, 75, 80],
            "rolodex":       [65, 75, 80, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
    "the_big_cheese": {
        # [TODO] glower_power damage + accuracy: the guide gives THREE values per
        #     level ("10, 14, 14" etc). Per the Appendix C footnote, The Big Cheese
        #     has three unused attacks (CigarSmoke, FloodTheMarket, SongAndDance)
        #     that all render as Glower Power but keep their own damage/accuracy,
        #     so a single number per level does not exist. Left None rather than
        #     picking one of the three. (The L9 damage cell also reads "12, 16, 15,"
        #     with a stray trailing comma.)
        "levels": [8, 9, 10, 11, 12],
        "freq": {
            "tee_off":      [50, 50, 50, 50, 50],
            "glower_power": [50, 50, 50, 50, 50],
        },
        "damage": {
            "tee_off":      [   8,   11,   14,   17,   20],
            "glower_power": [None, None, None, None, None],
        },
        "accuracy": {
            "tee_off":      [  55,   65,   70,   75,   80],
            "glower_power": [None, None, None, None, None],
        },
        "group_attacks": set(),  # [CONFIRMED] Appendix B lists every attack as Single
    },
}
