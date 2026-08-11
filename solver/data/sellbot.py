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
from .types import Cog, CogAttack, Department

SELLBOT = Department(
    key="sellbot",
    display="Sellbots",
    cogs=(
        Cog(
            key="cold_caller",
            display="Cold Caller",
            department="sellbot",
            levels=(1, 2, 3, 4, 5),
            # Wiki: https://toontownrewritten.wiki/Cold_Caller
            attacks=(
                CogAttack(
                    "freeze_assets", "Freeze Assets",
                    damage=(1, 1, 2, 2, 3),
                    accuracy=(90, 90, 90, 90, 90),
                    frequency=(5, 10, 15, 20, 25),
                ),
                CogAttack(
                    "pound_key", "Pound Key",
                    damage=(2, 2, 3, 4, 5),
                    accuracy=(75, 80, 85, 90, 95),
                    frequency=(25, 25, 25, 25, 25),
                ),
                CogAttack(
                    "double_talk", "Double Talk",
                    damage=(2, 3, 4, 6, 8),
                    accuracy=(50, 55, 60, 65, 70),
                    frequency=(25, 25, 25, 25, 25),
                ),
                CogAttack(
                    "hot_air", "Hot Air",
                    damage=(3, 4, 6, 8, 10),
                    accuracy=(50, 50, 50, 50, 50),
                    frequency=(45, 40, 35, 30, 25),
                ),
            ),
    ),
    Cog(
        key="telemarketer",
        display="Telemarketer",
        department="sellbot",
        levels=(2, 3, 4, 5, 6),
        # Wiki: https://toontownrewritten.wiki/Telemarketer
        attacks=(
            CogAttack(
                "clip_on_tie", "Clip On Tie",
                damage=(2, 3, 4, 5, 6),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "pick_pocket", "Pick Pocket",
                damage=(1, 2, 3, 4, 5),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "rolodex", "Rolodex",
                damage=(4, 6, 7, 9, 12),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "double_talk", "Double Talk",
                damage=(4, 6, 7, 9, 12),
                accuracy=(75, 80, 85, 90, 95),
                frequency=(40, 40, 40, 40, 40),
            ),
        ),
    ),
    Cog(
        key="name_dropper",
        display="Name Dropper",
        department="sellbot",
        levels=(3, 4, 5, 6, 7),
        # Wiki: https://toontownrewritten.wiki/Name_Dropper
        attacks=(
            CogAttack(
                "razzle_dazzle", "Razzle Dazzle",
                damage=(4, 5, 6, 9, 12),
                accuracy=(75, 80, 85, 90, 95),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "rolodex", "Rolodex",
                damage=(5, 6, 7, 10, 14),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(40, 40, 40, 40, 40),
            ),
            CogAttack(
                "synergy", "Synergy",
                damage=(3, 4, 6, 9, 12),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(15, 15, 15, 15, 15),
                group=True,
            ),
            CogAttack(
                "pick_pocket", "Pick Pocket",
                damage=(2, 3, 5, 6, 8),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(15, 15, 15, 15, 15),
            ),
        ),
    ),
    Cog(
        key="glad_hander",
        display="Glad Hander",
        department="sellbot",
        levels=(4, 5, 6, 7, 8),
        # Wiki: https://toontownrewritten.wiki/Glad_Hander
        attacks=(
            CogAttack(
                "rubber_stamp", "Rubber Stamp",
                damage=(4, 5, 6, 7, 8),
                accuracy=(90, 70, 50, 30, 10),
                frequency=(40, 30, 20, 10, 5),
            ),
            CogAttack(
                "fountain_pen", "Fountain Pen",
                damage=(3, 5, 6, 8, 9),
                accuracy=(70, 60, 50, 40, 30),
                frequency=(40, 30, 20, 10, 5),
            ),
            CogAttack(
                "filibuster", "Filibuster",
                damage=(4, 6, 9, 12, 15),
                accuracy=(30, 40, 50, 60, 70),
                frequency=(10, 20, 30, 40, 45),
            ),
            CogAttack(
                "schmooze", "Schmooze",
                damage=(5, 7, 11, 15, 20),
                accuracy=(55, 65, 75, 85, 95),
                frequency=(10, 20, 30, 40, 45),
            ),
        ),
    ),
    Cog(
        key="mover_and_shaker",
        display="Mover And Shaker",
        department="sellbot",
        levels=(5, 6, 7, 8, 9),
        # Wiki: https://toontownrewritten.wiki/Mover_%26_Shaker
        attacks=(
            CogAttack(
                "brain_storm", "Brain Storm",
                damage=(5, 6, 8, 10, 12),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "half_windsor", "Half Windsor",
                damage=(6, 9, 11, 13, 16),
                accuracy=(50, 65, 70, 75, 80),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "quake", "Quake",
                damage=(9, 12, 15, 18, 21),
                accuracy=(60, 65, 75, 80, 85),
                frequency=(20, 20, 20, 20, 20),
                group=True,
            ),
            CogAttack(
                "shake", "Shake",
                damage=(6, 8, 10, 12, 14),
                accuracy=(70, 75, 80, 85, 90),
                frequency=(25, 25, 25, 25, 25),
                group=True,
            ),
            CogAttack(
                "tremor", "Tremor",
                damage=(5, 6, 7, 8, 9),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(20, 20, 20, 20, 20),
                group=True,
            ),
        ),
    ),
    Cog(
        key="two_face",
        display="Two Face",
        department="sellbot",
        levels=(6, 7, 8, 9, 10),
        # Wiki: https://toontownrewritten.wiki/Two-Face
        attacks=(
            CogAttack(
                "evil_eye", "Evil Eye",
                damage=(10, 12, 14, 16, 18),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "hang_up", "Hang Up",
                damage=(7, 8, 10, 12, 13),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "razzle_dazzle", "Razzle Dazzle",
                damage=(8, 10, 12, 14, 16),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "red_tape", "Red Tape",
                damage=(6, 7, 8, 9, 10),
                accuracy=(60, 65, 75, 85, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
        ),
    ),
    Cog(
        key="the_mingler",
        display="The Mingler",
        department="sellbot",
        levels=(7, 8, 9, 10, 11),
        # Wiki: https://toontownrewritten.wiki/The_Mingler
        # [CONFLICT -- UNRESOLVED] power_trip. The wiki's Mingler roster has
        # only FOUR attacks (Buzz Word, Paradigm Shift, Schmooze, Tee
        # Off), and https://toontownrewritten.wiki/Power_Trip lists its
        # users as The Big Cheese, Big Wig, Robber Baron and Mr.
        # Hollywood -- not The Mingler. So TTR appears to have taken
        # Power Trip off this cog. It is kept in the table anyway,
        # because removing it means redistributing its 15% frequency
        # across the other four attacks and that redistribution is a
        # number no source gives. Leaving 15% of this cog's turns
        # unallocated would instead dump the shortfall onto whichever
        # attack happens to be first in the dict, which is worse.
        # Its damage and accuracy rows below are guide-era TTO values
        # with no wiki counterpart -- treat this attack as fiction.
        attacks=(
            CogAttack(
                "buzz_word", "Buzz Word",
                damage=(10, 11, 13, 15, 16),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "paradigm_shift", "Paradigm Shift",
                damage=(12, 15, 18, 21, 24),
                accuracy=(60, 70, 75, 80, 90),
                frequency=(25, 25, 25, 25, 25),
                group=True,
            ),
            CogAttack(
                "power_trip", "Power Trip",
                damage=(10, 13, 14, 15, 18),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(15, 15, 15, 15, 15),
                group=True,
            ),
            CogAttack(
                "schmooze", "Schmooze",
                damage=(7, 8, 12, 15, 16),
                accuracy=(55, 65, 75, 85, 95),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "tee_off", "Tee Off",
                damage=(8, 9, 10, 11, 12),
                accuracy=(70, 75, 80, 85, 95),
                frequency=(10, 10, 10, 10, 10),
            ),
        ),
    ),
    Cog(
        key="mr_hollywood",
        display="Mr Hollywood",
        department="sellbot",
        levels=(8, 9, 10, 11, 12),
        # Wiki: https://toontownrewritten.wiki/Mr._Hollywood
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        # A 50/50 split over two attacks cannot be right for a
        # four-attack cog.
        attacks=(
            CogAttack(
                "power_trip", "Power Trip",
                damage=(10, 12, 15, 18, 20),
                accuracy=(55, 65, 75, 85, 95),
                frequency=(50, 50, 50, 50, 50),
                group=True,
            ),
            CogAttack(
                "razzle_dazzle", "Razzle Dazzle",
                damage=(8, 11, 14, 17, 20),
                accuracy=(70, 75, 85, 90, 95),
                frequency=(50, 50, 50, 50, 50),
            ),
            CogAttack(
                "beguile", "Beguile",
                damage=(11, 14, 17, 20, 22),
                group=True, modeled=False,
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(7, 9, 12, 14, 17),
                group=False, modeled=False,
            ),
        ),
    ),
    ),
)

# Backwards-compatible alias; Department indexes by cog key like the old dict.
SELLBOT_COGS = SELLBOT
