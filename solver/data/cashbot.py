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
from .types import Cog, CogAttack, Department

CASHBOT = Department(
    key="cashbot",
    display="Cashbots",
    cogs=(
        Cog(
            key="short_change",
            display="Short Change",
            department="cashbot",
            levels=(1, 2, 3, 4, 5),
            # Wiki: https://toontownrewritten.wiki/Short_Change
            attacks=(
                CogAttack(
                    "watercooler", "Watercooler",
                    damage=(2, 2, 3, 4, 6),
                    accuracy=(50, 50, 50, 50, 50),
                    frequency=(20, 20, 20, 20, 20),
                ),
                CogAttack(
                    "bounce_check", "Bounce Check",
                    damage=(3, 5, 7, 9, 11),
                    accuracy=(75, 80, 85, 90, 95),
                    frequency=(15, 15, 15, 15, 15),
                ),
                CogAttack(
                    "clip_on_tie", "Clip On Tie",
                    damage=(1, 1, 2, 2, 3),
                    accuracy=(50, 50, 50, 50, 50),
                    frequency=(25, 25, 25, 25, 25),
                ),
                CogAttack(
                    "pick_pocket", "Pick Pocket",
                    damage=(2, 2, 3, 4, 6),
                    accuracy=(95, 95, 95, 95, 95),
                    frequency=(40, 40, 40, 40, 40),
                ),
            ),
    ),
    Cog(
        key="penny_pincher",
        display="Penny Pincher",
        department="cashbot",
        levels=(2, 3, 4, 5, 6),
        # Wiki: https://toontownrewritten.wiki/Penny_Pincher
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had
        # three. Nickel and Dime is new in 4.0.0, so the split below
        # predates the pool change.
        attacks=(
            CogAttack(
                "bounce_check", "Bounce Check",
                damage=(4, 5, 6, 8, 12),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(45, 45, 45, 45, 45),
            ),
            CogAttack(
                "freeze_assets", "Freeze Assets",
                damage=(2, 3, 4, 6, 9),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(1, 2, 3, 4, 6),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "nickel_and_dime", "Nickel And Dime",
                damage=(3, 4, 6, 7, 9),
                group=True, modeled=False,
            ),
        ),
    ),
    Cog(
        key="tightwad",
        display="Tightwad",
        department="cashbot",
        levels=(3, 4, 5, 6, 7),
        # Wiki: https://toontownrewritten.wiki/Tightwad
        # NOT a transcription error: unlike every other cog, Tightwad's
        # frequencies are not smooth across levels -- each level has one
        # attack spiking to 60-75% while the rest sit at 5%, and which
        # attack spikes moves as the level goes up. Verified against
        # Appendix A cell by cell; every level still totals 100. The wiki
        # publishes no frequencies, so it can neither confirm nor deny
        # this shape.
        attacks=(
            CogAttack(
                "fired", "Fired",
                damage=(3, 4, 5, 5, 6),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(75, 5, 5, 5, 5),
            ),
            CogAttack(
                "glower_power", "Glower Power",
                damage=(3, 4, 6, 9, 12),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(10, 15, 20, 25, 30),
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(3, 3, 4, 4, 5),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(5, 70, 5, 5, 5),
            ),
            CogAttack(
                "freeze_assets", "Freeze Assets",
                damage=(3, 4, 6, 9, 12),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(5, 5, 65, 5, 30),
            ),
            CogAttack(
                "bounce_check", "Bounce Check",
                damage=(5, 6, 9, 13, 18),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(5, 5, 5, 60, 30),
            ),
        ),
    ),
    Cog(
        key="bean_counter",
        display="Bean Counter",
        department="cashbot",
        levels=(4, 5, 6, 7, 8),
        # Wiki: https://toontownrewritten.wiki/Bean_Counter
        # The wiki notes this is "the only Cog to have four attacks with the
        # same damage values across eight levels" -- the identical rows below
        # are real, not a copy-paste slip.
        attacks=(
            CogAttack(
                "audit", "Audit",
                damage=(4, 6, 9, 12, 15),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "calculate", "Calculate",
                damage=(4, 6, 9, 12, 15),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "tabulate", "Tabulate",
                damage=(4, 6, 9, 12, 15),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "write_off", "Write Off",
                damage=(4, 6, 9, 12, 15),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(30, 30, 30, 30, 30),
            ),
        ),
    ),
    Cog(
        key="number_cruncher",
        display="Number Cruncher",
        department="cashbot",
        levels=(5, 6, 7, 8, 9),
        # Wiki: https://toontownrewritten.wiki/Number_Cruncher
        attacks=(
            CogAttack(
                "audit", "Audit",
                damage=(5, 6, 8, 10, 12),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "calculate", "Calculate",
                damage=(6, 7, 9, 11, 13),
                accuracy=(50, 65, 70, 75, 80),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "crunch", "Crunch",
                damage=(8, 9, 11, 13, 15),
                accuracy=(60, 65, 75, 80, 85),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "tabulate", "Tabulate",
                damage=(5, 6, 7, 8, 9),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(20, 20, 20, 20, 20),
            ),
        ),
    ),
    Cog(
        key="money_bags",
        display="Money Bags",
        department="cashbot",
        levels=(6, 7, 8, 9, 10),
        # Wiki: https://toontownrewritten.wiki/Money_Bags
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had
        # three. Money Talks is new in 4.0.0.
        attacks=(
            CogAttack(
                "liquidate", "Liquidate",
                damage=(10, 12, 14, 16, 18),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "market_crash", "Market Crash",
                damage=(8, 10, 12, 14, 16),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(45, 45, 45, 45, 45),
            ),
            CogAttack(
                "power_tie", "Power Tie",
                damage=(6, 7, 8, 9, 10),
                accuracy=(60, 65, 75, 85, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "money_talks", "Money Talks",
                damage=(9, 11, 12, 14, 15),
                group=True, modeled=False,
            ),
        ),
    ),
    Cog(
        key="loan_shark",
        display="Loan Shark",
        department="cashbot",
        levels=(7, 8, 9, 10, 11),
        # Wiki: https://toontownrewritten.wiki/Loan_Shark
        attacks=(
            CogAttack(
                "bite", "Bite",
                damage=(10, 11, 13, 15, 16),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "chomp", "Chomp",
                damage=(12, 15, 18, 21, 24),
                accuracy=(60, 70, 75, 80, 90),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "play_hardball", "Play Hardball",
                damage=(9, 11, 12, 13, 15),
                accuracy=(55, 65, 75, 85, 95),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "write_off", "Write Off",
                damage=(6, 8, 10, 12, 14),
                accuracy=(70, 75, 80, 85, 95),
                frequency=(15, 15, 15, 15, 15),
            ),
        ),
    ),
    Cog(
        key="robber_baron",
        display="Robber Baron",
        department="cashbot",
        levels=(8, 9, 10, 11, 12),
        # Wiki: https://toontownrewritten.wiki/Robber_Baron
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        # A 50/50 split over two attacks cannot be right for a
        # four-attack cog.
        attacks=(
            CogAttack(
                "power_trip", "Power Trip",
                damage=(11, 14, 16, 18, 21),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(50, 50, 50, 50, 50),
                group=True,
            ),
            CogAttack(
                "tee_off", "Tee Off",
                damage=(10, 12, 14, 16, 18),
                accuracy=(60, 65, 75, 85, 90),
                frequency=(50, 50, 50, 50, 50),
            ),
            CogAttack(
                "embezzle", "Embezzle",
                damage=(11, 14, 16, 18, 20),
                group=False, modeled=False,
            ),
            CogAttack(
                "synergy", "Synergy",
                damage=(9, 11, 13, 16, 18),
                group=True, modeled=False,
            ),
        ),
    ),
    ),
)

# Backwards-compatible alias; Department indexes by cog key like the old dict.
CASHBOT_COGS = CASHBOT
