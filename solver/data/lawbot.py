"""
Lawbot cog attack tables.

Each cog entry:
  "levels":            list of absolute levels this cog can appear at; index
                       into the per-attack lists is (cog.level - levels[0])
  "freq":              {attack_name: [freq% at each relative level]}
  "damage":            {attack_name: [(min,max) or fixed int, at each level]}
  "accuracy":          {attack_name: [accuracy% at each relative level]}
  "group_attacks":     set of attack names that hit all toons
  "unmodeled_attacks": {name: {"damage": [...], "group": bool}} -- attacks
                       the wiki confirms this cog really has but which the
                       simulator cannot fire, because no frequency exists
                       for them. The simulator UNDER-estimates any cog that
                       has one.

TWO SOURCES, TWO CONFIDENCE LEVELS
----------------------------------
[CONFIRMED] from the TTR wiki (<https://toontownrewritten.wiki>), each cog's
page cross-checked against each attack's own page: "levels" (the infobox
llevel-hlevel range), "damage", "group_attacks" (the Target row, One Toon vs
Group), and the attack roster.

[UNVERIFIED -- GUIDE-DERIVED] "freq" and "accuracy", still from
QED1224/Toontown-Resources (master branch) Appendices A and C. The wiki
publishes neither number anywhere, so neither could be checked; both are
left exactly as the guide had them and are deliberately NOT [CONFIRMED].
TTR 4.0.0 states that it changed both.

data/bossbot.py carries the full source note: the 4.0.0 changelog quotes,
why the new attacks sit in "unmodeled_attacks" instead of the main tables,
what [FREQ STALE] means, and the over-leveled-cog situation. Read it before
editing any of the four department modules.

A `None` in an otherwise-filled list is a per-cell [TODO]: a value neither
source gives unambiguously, left blank rather than guessed at, and called out
in a comment where it appears. Callers null-check per cell and raise
NotImplementedError naming the cell.
"""

LAWBOT_COGS = {
    "bottom_feeder": {
        # Wiki: https://toontownrewritten.wiki/Bottom_Feeder
        # [!] The wiki contradicts itself on pick_pocket, but only outside the
        #     modeled range: the Bottom Feeder page ends the row ...5, 6, 8 at
        #     levels 6-8 while /Pick_Pocket ends it ...5, 6, 7. Levels 1-5
        #     agree on both pages, so the row below is unaffected.
        "levels": [1, 2, 3, 4, 5],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "rubber_stamp": [20, 20, 20, 20, 20],
            "shred":        [20, 20, 20, 20, 20],
            "watercooler":  [10, 10, 10, 10, 10],
            "pick_pocket":  [50, 50, 50, 50, 50],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "rubber_stamp": [ 2,  3,  4,  5,  6],
            "shred":        [ 2,  4,  6,  8, 10],
            "watercooler":  [ 3,  4,  5,  6,  7],
            "pick_pocket":  [ 1,  1,  2,  2,  3],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "rubber_stamp": [75, 80, 85, 90, 95],
            "shred":        [50, 55, 60, 65, 70],
            "watercooler":  [95, 95, 95, 95, 95],
            "pick_pocket":  [25, 30, 35, 40, 45],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "bloodsucker": {
        # Wiki: https://toontownrewritten.wiki/Bloodsucker
        # [RESOLVED] Appendix A spelled this attack "Withdrawl", B and C
        #     "Withdrawal". The wiki uses Withdrawal, which is the key here.
        "levels": [2, 3, 4, 5, 6],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "eviction_notice": [20, 20, 20, 20, 20],
            "red_tape":        [20, 20, 20, 20, 20],
            "withdrawal":      [10, 10, 10, 10, 10],
            "liquidate":       [50, 50, 50, 50, 50],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "eviction_notice": [ 1,  2,  3,  3,  4],
            "red_tape":        [ 2,  3,  4,  6,  9],
            "withdrawal":      [ 6,  8, 10, 12, 14],
            "liquidate":       [ 2,  3,  4,  6,  9],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "eviction_notice": [75, 75, 75, 75, 75],
            "red_tape":        [75, 75, 75, 75, 75],
            "withdrawal":      [95, 95, 95, 95, 95],
            "liquidate":       [50, 60, 70, 80, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "double_talker": {
        # Wiki: https://toontownrewritten.wiki/Double_Talker
        # [RESOLVED] Appendix A spelled this "Buzzword", B and C "Buzz Word";
        #     the wiki uses Buzz Word. Key is buzz_word package-wide.
        # [CORRECTED] group_attacks was {"buzz_word"} on the strength of
        #     Appendix B's Type column. The wiki says Buzz Word is a single-
        #     target attack: the Double Talker page gives Target = One Toon,
        #     https://toontownrewritten.wiki/Buzz_Word gives Target = One Toon
        #     and files it under Category:Single Cog attacks, and the same
        #     attack is single-target on Micromanager and The Mingler too.
        #     Double Talker now has no group attacks at all.
        "levels": [3, 4, 5, 6, 7],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "rubber_stamp": [ 5,  5,  5,  5,  5],
            "bounce_check": [ 5,  5,  5,  5,  5],
            "buzz_word":    [20, 20, 20, 20, 20],
            "double_talk":  [25, 25, 25, 25, 25],
            "jargon":       [25, 25, 25, 25, 25],
            "mumbo_jumbo":  [20, 20, 20, 20, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "rubber_stamp": [ 1,  1,  1,  1,  1],
            "bounce_check": [ 1,  1,  1,  1,  1],
            "buzz_word":    [ 1,  2,  3,  5,  6],
            "double_talk":  [ 6,  6,  9, 13, 18],
            "jargon":       [ 3,  4,  6,  9, 12],
            "mumbo_jumbo":  [ 3,  4,  6,  9, 12],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "rubber_stamp": [50, 60, 70, 80, 90],
            "bounce_check": [50, 60, 70, 80, 90],
            "buzz_word":    [50, 60, 70, 80, 90],
            "double_talk":  [50, 60, 70, 80, 90],
            "jargon":       [50, 60, 70, 80, 90],
            "mumbo_jumbo":  [50, 60, 70, 80, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all six "One Toon"
        "unmodeled_attacks": {},
    },
    "ambulance_chaser": {
        # Wiki: https://toontownrewritten.wiki/Ambulance_Chaser
        "levels": [4, 5, 6, 7, 8],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "shake":    [15, 15, 15, 15, 15],
            "red_tape": [30, 30, 30, 30, 30],
            "rolodex":  [20, 20, 20, 20, 20],
            "hang_up":  [35, 35, 35, 35, 35],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "shake":    [ 4,  6,  9, 12, 15],
            "red_tape": [ 6,  8, 12, 15, 19],
            "rolodex":  [ 3,  4,  5,  6,  7],
            "hang_up":  [ 2,  3,  4,  5,  6],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "shake":    [75, 75, 75, 75, 75],
            "red_tape": [75, 75, 75, 75, 75],
            "rolodex":  [75, 75, 75, 75, 75],
            "hang_up":  [75, 75, 75, 75, 75],
        },
        "group_attacks": {"shake"},  # [CONFIRMED] wiki: Shake is "Group"
        "unmodeled_attacks": {},
    },
    "backstabber": {
        # Wiki: https://toontownrewritten.wiki/Back_Stabber (the wiki spells
        # the cog's name as two words; the key stays backstabber).
        "levels": [5, 6, 7, 8, 9],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "guilt_trip":        [40, 40, 40, 40, 40],
            "restraining_order": [25, 25, 25, 25, 25],
            "finger_wag":        [35, 35, 35, 35, 35],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "guilt_trip":        [ 8, 11, 13, 15, 18],
            "restraining_order": [ 6,  7,  9, 11, 13],
            "finger_wag":        [ 5,  6,  7,  8,  9],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "guilt_trip":        [60, 75, 80, 85, 90],
            "restraining_order": [50, 65, 70, 75, 90],
            "finger_wag":        [50, 55, 65, 75, 80],
        },
        # [CONFIRMED] wiki: Guilt Trip is "Group", the other two "One Toon".
        "group_attacks": {"guilt_trip"},
        "unmodeled_attacks": {},
    },
    "spin_doctor": {
        # Wiki: https://toontownrewritten.wiki/Spin_Doctor
        # [RESOLVED] Appendix C listed a 5th Spin Doctor attack, "Rolodex"
        #     (60/65/70/75/80), that Appendices A and B did not. It was
        #     omitted here as unselectable. The wiki confirms the omission
        #     was right: Spin Doctor's roster is these four attacks, and
        #     https://toontownrewritten.wiki/Rolodex lists its users as Head
        #     Hunter, Ambulance Chaser, Name Dropper and Telemarketer -- not
        #     Spin Doctor.
        "levels": [6, 7, 8, 9, 10],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "paradigm_shift": [30, 30, 30, 30, 30],
            "quake":          [20, 20, 20, 20, 20],
            "spin":           [35, 35, 35, 35, 35],
            "write_off":      [15, 15, 15, 15, 15],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "paradigm_shift": [ 9, 10, 13, 16, 17],
            "quake":          [ 8, 10, 12, 14, 16],
            "spin":           [10, 12, 15, 18, 20],
            "write_off":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "paradigm_shift": [60, 75, 80, 85, 90],
            "quake":          [60, 65, 70, 75, 80],
            "spin":           [70, 75, 80, 85, 90],
            "write_off":      [60, 65, 75, 85, 90],
        },
        # [CONFIRMED] wiki: Paradigm Shift and Quake are "Group".
        "group_attacks": {"paradigm_shift", "quake"},
        "unmodeled_attacks": {},
    },
    "legal_eagle": {
        # Wiki: https://toontownrewritten.wiki/Legal_Eagle
        "levels": [7, 8, 9, 10, 11],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "evil_eye":      [20, 20, 20, 20, 20],
            "jargon":        [15, 15, 15, 15, 15],
            "legalese":      [35, 35, 35, 35, 35],
            "pecking_order": [30, 30, 30, 30, 30],
        },
        "damage": {  # [CONFIRMED] wiki
            # [CORRECTED] pecking_order level 7 was 12; the wiki gives 15 on
            #     both the Legal Eagle page and /Pecking_Order, making the
            #     row start flat at 15, 15. Levels 8-11 were already right.
            "evil_eye":      [10, 11, 13, 15, 16],
            "jargon":        [ 7,  9, 11, 13, 15],
            "legalese":      [11, 13, 16, 19, 21],
            "pecking_order": [15, 15, 17, 19, 22],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "evil_eye":      [60, 75, 80, 85, 90],
            "jargon":        [60, 70, 75, 80, 90],
            "legalese":      [55, 65, 75, 85, 95],
            "pecking_order": [70, 75, 80, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "big_wig": {
        # Wiki: https://toontownrewritten.wiki/Big_Wig
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        #     A 50/50 split over two attacks cannot be right for a
        #     four-attack cog.
        # finger_wag damage: RESOLVED by triangulation. The wiki appeared to
        #     contradict itself -- the Big Wig page gives 9, 11, 13, 16, 18
        #     while https://toontownrewritten.wiki/Finger_Wag gives
        #     13, 15, 17, 19, 21 for the same five levels.
        #
        #     The Finger_Wag page is misattributing Throw Book's row. Three
        #     independent places agree Big Wig's THROW BOOK damage is exactly
        #     13, 15, 17, 19, 21: the wiki's own Throw Book entry for this
        #     cog (see unmodeled_attacks below), Open Toontown's
        #     SuitBattleGlobals.py, and the pre-rebalance guide -- which also
        #     listed this row under "finger_wag" even though Toontown Online's
        #     Big Wig has no Finger Wag at all, only Power Trip and Throw
        #     Book. So the row was mislabeled at the source and the wiki's
        #     per-attack page inherited the error.
        #
        #     That leaves the Big Wig page's 9, 11, 13, 16, 18 as the only
        #     unexplained-away figure for Finger Wag, and it is monotonic
        #     across the over-level seam where the other row is not. Filled
        #     in from it. [CONFIRMED] wiki, Big Wig page.
        "levels": [8, 9, 10, 11, 12],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "power_trip": [50, 50, 50, 50, 50],
            "finger_wag": [50, 50, 50, 50, 50],
        },
        "damage": {
            "power_trip": [  10,   11,   13,   15,   16],  # [CONFIRMED] wiki
            "finger_wag": [ 9, 11, 13, 16, 18],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "power_trip": [75, 80, 85, 90, 95],
            "finger_wag": [80, 85, 85, 85, 90],
        },
        # [CONFIRMED] wiki: Power Trip is "Group", Finger Wag "One Toon".
        "group_attacks": {"power_trip"},
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Quash (Big Wig's signature group attack, new
            # in TTR 4.0.0) and /Throw_Book (one of two Toontown Online
            # attacks TTR revived in 4.0.0 -- see the Cog attack page's
            # trivia). Neither has a published frequency.
            "quash":      {"damage": [12, 13, 15, 17, 19], "group": True},
            "throw_book": {"damage": [13, 15, 17, 19, 21], "group": False},
        },
    },
}
