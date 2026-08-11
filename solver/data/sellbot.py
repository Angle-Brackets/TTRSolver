"""
Sellbot cog attack tables.

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

SELLBOT_COGS = {
    "cold_caller": {
        # Wiki: https://toontownrewritten.wiki/Cold_Caller
        "levels": [1, 2, 3, 4, 5],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "freeze_assets": [ 5, 10, 15, 20, 25],
            "pound_key":     [25, 25, 25, 25, 25],
            "double_talk":   [25, 25, 25, 25, 25],
            "hot_air":       [45, 40, 35, 30, 25],
        },
        "damage": {  # [CONFIRMED] wiki
            # [CORRECTED] freeze_assets was [1, 1, 1, 1, 1] from the guide;
            #     the wiki gives [1, 1, 2, 2, 3] on both the Cold Caller page
            #     and https://toontownrewritten.wiki/Freeze_Assets.
            "freeze_assets": [ 1,  1,  2,  2,  3],
            "pound_key":     [ 2,  2,  3,  4,  5],
            "double_talk":   [ 2,  3,  4,  6,  8],
            "hot_air":       [ 3,  4,  6,  8, 10],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "freeze_assets": [90, 90, 90, 90, 90],
            "pound_key":     [75, 80, 85, 90, 95],
            "double_talk":   [50, 55, 60, 65, 70],
            "hot_air":       [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "telemarketer": {
        # Wiki: https://toontownrewritten.wiki/Telemarketer
        "levels": [2, 3, 4, 5, 6],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "clip_on_tie": [15, 15, 15, 15, 15],
            "pick_pocket": [15, 15, 15, 15, 15],
            "rolodex":     [30, 30, 30, 30, 30],
            "double_talk": [40, 40, 40, 40, 40],
        },
        "damage": {  # [CONFIRMED] wiki
            # [CORRECTED] clip_on_tie was [2, 2, 3, 3, 4] and pick_pocket was
            #     a flat [1, 1, 1, 1, 1]. Both scale in TTR; confirmed on the
            #     Telemarketer page and on /Clip_on_Tie and /Pick_Pocket.
            "clip_on_tie": [ 2,  3,  4,  5,  6],
            "pick_pocket": [ 1,  2,  3,  4,  5],
            "rolodex":     [ 4,  6,  7,  9, 12],
            "double_talk": [ 4,  6,  7,  9, 12],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "clip_on_tie": [75, 75, 75, 75, 75],
            "pick_pocket": [75, 75, 75, 75, 75],
            "rolodex":     [50, 50, 50, 50, 50],
            "double_talk": [75, 80, 85, 90, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "name_dropper": {
        # Wiki: https://toontownrewritten.wiki/Name_Dropper
        "levels": [3, 4, 5, 6, 7],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "razzle_dazzle": [30, 30, 30, 30, 30],
            "rolodex":       [40, 40, 40, 40, 40],
            "synergy":       [15, 15, 15, 15, 15],
            "pick_pocket":   [15, 15, 15, 15, 15],
        },
        "damage": {  # [CONFIRMED] wiki
            # [CORRECTED] pick_pocket was a flat [2, 2, 2, 2, 2]; the wiki
            #     gives [2, 3, 5, 6, 8] on both the cog and /Pick_Pocket.
            "razzle_dazzle": [ 4,  5,  6,  9, 12],
            "rolodex":       [ 5,  6,  7, 10, 14],
            "synergy":       [ 3,  4,  6,  9, 12],
            "pick_pocket":   [ 2,  3,  5,  6,  8],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "razzle_dazzle": [75, 80, 85, 90, 95],
            "rolodex":       [95, 95, 95, 95, 95],
            "synergy":       [50, 50, 50, 50, 50],
            "pick_pocket":   [95, 95, 95, 95, 95],
        },
        "group_attacks": {"synergy"},  # [CONFIRMED] wiki: Synergy is "Group"
        "unmodeled_attacks": {},
    },
    "glad_hander": {
        # Wiki: https://toontownrewritten.wiki/Glad_Hander
        "levels": [4, 5, 6, 7, 8],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "rubber_stamp": [40, 30, 20, 10,  5],
            "fountain_pen": [40, 30, 20, 10,  5],
            "filibuster":   [10, 20, 30, 40, 45],
            "schmooze":     [10, 20, 30, 40, 45],
        },
        "damage": {  # [CONFIRMED] wiki
            # [CORRECTED] The guide had rubber_stamp and fountain_pen getting
            #     *weaker* as the cog levels up ([4,3,3,2,1] and [3,3,2,1,1])
            #     -- the only two decreasing damage rows in the whole data
            #     set. TTR has them increasing like everything else, per both
            #     the Glad Hander page and /Rubber_Stamp and /Fountain_Pen.
            "rubber_stamp": [ 4,  5,  6,  7,  8],
            "fountain_pen": [ 3,  5,  6,  8,  9],
            "filibuster":   [ 4,  6,  9, 12, 15],
            "schmooze":     [ 5,  7, 11, 15, 20],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "rubber_stamp": [90, 70, 50, 30, 10],
            "fountain_pen": [70, 60, 50, 40, 30],
            "filibuster":   [30, 40, 50, 60, 70],
            "schmooze":     [55, 65, 75, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "mover_and_shaker": {
        # Wiki: https://toontownrewritten.wiki/Mover_%26_Shaker
        "levels": [5, 6, 7, 8, 9],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "brain_storm":  [15, 15, 15, 15, 15],
            "half_windsor": [20, 20, 20, 20, 20],
            "quake":        [20, 20, 20, 20, 20],
            "shake":        [25, 25, 25, 25, 25],
            "tremor":       [20, 20, 20, 20, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "brain_storm":  [ 5,  6,  8, 10, 12],
            "half_windsor": [ 6,  9, 11, 13, 16],
            "quake":        [ 9, 12, 15, 18, 21],
            "shake":        [ 6,  8, 10, 12, 14],
            "tremor":       [ 5,  6,  7,  8,  9],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "brain_storm":  [60, 75, 80, 85, 90],
            "half_windsor": [50, 65, 70, 75, 80],
            "quake":        [60, 65, 75, 80, 85],
            "shake":        [70, 75, 80, 85, 90],
            "tremor":       [50, 50, 50, 50, 50],
        },
        # [CONFIRMED] wiki: Quake, Shake and Tremor are all "Group".
        "group_attacks": {"quake", "shake", "tremor"},
        "unmodeled_attacks": {},
    },
    "two_face": {
        # Wiki: https://toontownrewritten.wiki/Two-Face
        "levels": [6, 7, 8, 9, 10],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "evil_eye":      [30, 30, 30, 30, 30],
            "hang_up":       [15, 15, 15, 15, 15],
            "razzle_dazzle": [30, 30, 30, 30, 30],
            "red_tape":      [25, 25, 25, 25, 25],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "evil_eye":      [10, 12, 14, 16, 18],
            "hang_up":       [ 7,  8, 10, 12, 13],
            "razzle_dazzle": [ 8, 10, 12, 14, 16],
            "red_tape":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "evil_eye":      [60, 75, 80, 85, 90],
            "hang_up":       [50, 60, 70, 80, 90],
            "razzle_dazzle": [60, 65, 70, 75, 80],
            "red_tape":      [60, 65, 75, 85, 90],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "the_mingler": {
        # Wiki: https://toontownrewritten.wiki/The_Mingler
        # [CONFLICT -- UNRESOLVED] power_trip. The wiki's Mingler roster has
        #     only FOUR attacks (Buzz Word, Paradigm Shift, Schmooze, Tee
        #     Off), and https://toontownrewritten.wiki/Power_Trip lists its
        #     users as The Big Cheese, Big Wig, Robber Baron and Mr.
        #     Hollywood -- not The Mingler. So TTR appears to have taken
        #     Power Trip off this cog. It is kept in the table anyway,
        #     because removing it means redistributing its 15% frequency
        #     across the other four attacks and that redistribution is a
        #     number no source gives. Leaving 15% of this cog's turns
        #     unallocated would instead dump the shortfall onto whichever
        #     attack happens to be first in the dict, which is worse.
        #     Its damage and accuracy rows below are guide-era TTO values
        #     with no wiki counterpart -- treat this attack as fiction.
        "levels": [7, 8, 9, 10, 11],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "buzz_word":      [20, 20, 20, 20, 20],
            "paradigm_shift": [25, 25, 25, 25, 25],
            "power_trip":     [15, 15, 15, 15, 15],  # [STALE] not on this cog
            "schmooze":       [30, 30, 30, 30, 30],
            "tee_off":        [10, 10, 10, 10, 10],
        },
        "damage": {
            # [CONFIRMED] wiki for the four attacks the wiki lists; they all
            # agree with the guide. power_trip is [UNVERIFIED] -- see above.
            "buzz_word":      [10, 11, 13, 15, 16],
            "paradigm_shift": [12, 15, 18, 21, 24],
            "power_trip":     [10, 13, 14, 15, 18],  # [STALE]
            "schmooze":       [ 7,  8, 12, 15, 16],
            "tee_off":        [ 8,  9, 10, 11, 12],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "buzz_word":      [60, 75, 80, 85, 90],
            "paradigm_shift": [60, 70, 75, 80, 90],
            "power_trip":     [60, 65, 70, 75, 80],  # [STALE]
            "schmooze":       [55, 65, 75, 85, 95],
            "tee_off":        [70, 75, 80, 85, 95],
        },
        # [CONFIRMED] wiki: Paradigm Shift is "Group"; Buzz Word, Schmooze
        # and Tee Off are "One Toon". power_trip retains its group flag from
        # /Power_Trip, which is a group attack wherever it is used.
        "group_attacks": {"paradigm_shift", "power_trip"},
        "unmodeled_attacks": {},
    },
    "mr_hollywood": {
        # Wiki: https://toontownrewritten.wiki/Mr._Hollywood
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        #     A 50/50 split over two attacks cannot be right for a
        #     four-attack cog.
        "levels": [8, 9, 10, 11, 12],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "power_trip":    [50, 50, 50, 50, 50],
            "razzle_dazzle": [50, 50, 50, 50, 50],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide
            "power_trip":    [10, 12, 15, 18, 20],
            "razzle_dazzle": [ 8, 11, 14, 17, 20],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "power_trip":    [55, 65, 75, 85, 95],
            "razzle_dazzle": [70, 75, 85, 90, 95],
        },
        # [CONFIRMED] wiki: Power Trip is "Group", Razzle Dazzle "One Toon".
        "group_attacks": {"power_trip"},
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Beguile (Mr. Hollywood's signature group
            # attack, new in TTR 4.0.0) and /Finger_Wag (an existing attack
            # this cog gained). Neither has a published frequency.
            "beguile":    {"damage": [11, 14, 17, 20, 22], "group": True},
            "finger_wag": {"damage": [ 7,  9, 12, 14, 17], "group": False},
        },
    },
}
