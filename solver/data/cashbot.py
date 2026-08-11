"""
Cashbot cog attack tables.

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

Cashbot came through the audit better than any other department: every
damage number the guide had matches the wiki exactly. The only corrections
are three new attacks (Nickel and Dime, Money Talks, Embezzle) plus Synergy
on Robber Baron.
"""

CASHBOT_COGS = {
    "short_change": {
        # Wiki: https://toontownrewritten.wiki/Short_Change
        "levels": [1, 2, 3, 4, 5],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "watercooler":  [20, 20, 20, 20, 20],
            "bounce_check": [15, 15, 15, 15, 15],
            "clip_on_tie":  [25, 25, 25, 25, 25],
            "pick_pocket":  [40, 40, 40, 40, 40],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "watercooler":  [ 2,  2,  3,  4,  6],
            "bounce_check": [ 3,  5,  7,  9, 11],
            "clip_on_tie":  [ 1,  1,  2,  2,  3],
            "pick_pocket":  [ 2,  2,  3,  4,  6],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "watercooler":  [50, 50, 50, 50, 50],
            "bounce_check": [75, 80, 85, 90, 95],
            "clip_on_tie":  [50, 50, 50, 50, 50],
            "pick_pocket":  [95, 95, 95, 95, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "penny_pincher": {
        # Wiki: https://toontownrewritten.wiki/Penny_Pincher
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had
        #     three. Nickel and Dime is new in 4.0.0, so the split below
        #     predates the pool change.
        "levels": [2, 3, 4, 5, 6],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "bounce_check":  [45, 45, 45, 45, 45],
            "freeze_assets": [20, 20, 20, 20, 20],
            "finger_wag":    [35, 35, 35, 35, 35],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "bounce_check":  [ 4,  5,  6,  8, 12],
            "freeze_assets": [ 2,  3,  4,  6,  9],
            "finger_wag":    [ 1,  2,  3,  4,  6],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "bounce_check":  [75, 75, 75, 75, 75],
            "freeze_assets": [75, 75, 75, 75, 75],
            "finger_wag":    [50, 50, 50, 50, 50],
        },
        # [CONFIRMED] wiki: the three modeled attacks are all "One Toon".
        "group_attacks": set(),
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Nickel_and_Dime -- Penny Pincher's signature
            # group attack, added in TTR 4.0.0. No frequency is published.
            "nickel_and_dime": {"damage": [3, 4, 6, 7, 9], "group": True},
        },
    },
    "tightwad": {
        # Wiki: https://toontownrewritten.wiki/Tightwad
        # NOT a transcription error: unlike every other cog, Tightwad's
        #     frequencies are not smooth across levels -- each level has one
        #     attack spiking to 60-75% while the rest sit at 5%, and which
        #     attack spikes moves as the level goes up. Verified against
        #     Appendix A cell by cell; every level still totals 100. The wiki
        #     publishes no frequencies, so it can neither confirm nor deny
        #     this shape.
        "levels": [3, 4, 5, 6, 7],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "fired":         [75,  5,  5,  5,  5],
            "glower_power":  [10, 15, 20, 25, 30],
            "finger_wag":    [ 5, 70,  5,  5,  5],
            "freeze_assets": [ 5,  5, 65,  5, 30],
            "bounce_check":  [ 5,  5,  5, 60, 30],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "fired":         [ 3,  4,  5,  5,  6],
            "glower_power":  [ 3,  4,  6,  9, 12],
            "finger_wag":    [ 3,  3,  4,  4,  5],
            "freeze_assets": [ 3,  4,  6,  9, 12],
            "bounce_check":  [ 5,  6,  9, 13, 18],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "fired":         [75, 75, 75, 75, 75],
            "glower_power":  [95, 95, 95, 95, 95],
            "finger_wag":    [75, 75, 75, 75, 75],
            "freeze_assets": [75, 75, 75, 75, 75],
            "bounce_check":  [75, 75, 75, 75, 75],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all five "One Toon"
        "unmodeled_attacks": {},
    },
    "bean_counter": {
        # Wiki: https://toontownrewritten.wiki/Bean_Counter
        # The wiki notes this is "the only Cog to have four attacks with the
        # same damage values across eight levels" -- the identical rows below
        # are real, not a copy-paste slip.
        "levels": [4, 5, 6, 7, 8],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "audit":     [20, 20, 20, 20, 20],
            "calculate": [25, 25, 25, 25, 25],
            "tabulate":  [25, 25, 25, 25, 25],
            "write_off": [30, 30, 30, 30, 30],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "audit":     [ 4,  6,  9, 12, 15],
            "calculate": [ 4,  6,  9, 12, 15],
            "tabulate":  [ 4,  6,  9, 12, 15],
            "write_off": [ 4,  6,  9, 12, 15],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "audit":     [95, 95, 95, 95, 95],
            "calculate": [75, 75, 75, 75, 75],
            "tabulate":  [75, 75, 75, 75, 75],
            "write_off": [95, 95, 95, 95, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "number_cruncher": {
        # Wiki: https://toontownrewritten.wiki/Number_Cruncher
        "levels": [5, 6, 7, 8, 9],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "audit":     [15, 15, 15, 15, 15],
            "calculate": [30, 30, 30, 30, 30],
            "crunch":    [35, 35, 35, 35, 35],
            "tabulate":  [20, 20, 20, 20, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "audit":     [ 5,  6,  8, 10, 12],
            "calculate": [ 6,  7,  9, 11, 13],
            "crunch":    [ 8,  9, 11, 13, 15],
            "tabulate":  [ 5,  6,  7,  8,  9],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "audit":     [60, 75, 80, 85, 90],
            "calculate": [50, 65, 70, 75, 80],
            "crunch":    [60, 65, 75, 80, 85],
            "tabulate":  [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "money_bags": {
        # Wiki: https://toontownrewritten.wiki/Money_Bags
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had
        #     three. Money Talks is new in 4.0.0.
        "levels": [6, 7, 8, 9, 10],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "liquidate":    [30, 30, 30, 30, 30],
            "market_crash": [45, 45, 45, 45, 45],
            "power_tie":    [25, 25, 25, 25, 25],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "liquidate":    [10, 12, 14, 16, 18],
            "market_crash": [ 8, 10, 12, 14, 16],
            "power_tie":    [ 6,  7,  8,  9, 10],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "liquidate":    [60, 75, 80, 85, 90],
            "market_crash": [60, 65, 70, 75, 80],
            "power_tie":    [60, 65, 75, 85, 90],
        },
        # [CONFIRMED] wiki: the three modeled attacks are all "One Toon".
        "group_attacks": set(),
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Money_Talks -- Money Bags' signature group
            # attack, added in TTR 4.0.0. No frequency is published.
            "money_talks": {"damage": [9, 11, 12, 14, 15], "group": True},
        },
    },
    "loan_shark": {
        # Wiki: https://toontownrewritten.wiki/Loan_Shark
        "levels": [7, 8, 9, 10, 11],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "bite":          [30, 30, 30, 30, 30],
            "chomp":         [35, 35, 35, 35, 35],
            "play_hardball": [20, 20, 20, 20, 20],
            "write_off":     [15, 15, 15, 15, 15],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "bite":          [10, 11, 13, 15, 16],
            "chomp":         [12, 15, 18, 21, 24],
            "play_hardball": [ 9, 11, 12, 13, 15],
            "write_off":     [ 6,  8, 10, 12, 14],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "bite":          [60, 75, 80, 85, 90],
            "chomp":         [60, 70, 75, 80, 90],
            "play_hardball": [55, 65, 75, 85, 95],
            "write_off":     [70, 75, 80, 85, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "robber_baron": {
        # Wiki: https://toontownrewritten.wiki/Robber_Baron
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        #     A 50/50 split over two attacks cannot be right for a
        #     four-attack cog.
        "levels": [8, 9, 10, 11, 12],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "power_trip": [50, 50, 50, 50, 50],
            "tee_off":    [50, 50, 50, 50, 50],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide
            "power_trip": [11, 14, 16, 18, 21],
            "tee_off":    [10, 12, 14, 16, 18],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "power_trip": [60, 65, 70, 75, 80],
            "tee_off":    [60, 65, 75, 85, 90],
        },
        # [CONFIRMED] wiki: Power Trip is "Group", Tee Off "One Toon".
        "group_attacks": {"power_trip"},
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Embezzle (Robber Baron's signature attack,
            # new in TTR 4.0.0) and /Synergy (an existing group attack this
            # cog gained). Neither has a published frequency.
            "embezzle": {"damage": [11, 14, 16, 18, 20], "group": False},
            "synergy":  {"damage": [ 9, 11, 13, 16, 18], "group": True},
        },
    },
}
