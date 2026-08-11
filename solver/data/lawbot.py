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
from .types import Cog, CogAttack, Department

LAWBOT = Department(
    key="lawbot",
    display="Lawbots",
    cogs=(
        Cog(
            key="bottom_feeder",
            display="Bottom Feeder",
            department="lawbot",
            levels=(1, 2, 3, 4, 5),
            # Wiki: https://toontownrewritten.wiki/Bottom_Feeder
            # [!] The wiki contradicts itself on pick_pocket, but only outside the
            # modeled range: the Bottom Feeder page ends the row ...5, 6, 8 at
            # levels 6-8 while /Pick_Pocket ends it ...5, 6, 7. Levels 1-5
            # agree on both pages, so the row below is unaffected.
            attacks=(
                CogAttack(
                    "rubber_stamp", "Rubber Stamp",
                    damage=(2, 3, 4, 5, 6),
                    accuracy=(75, 80, 85, 90, 95),
                    frequency=(20, 20, 20, 20, 20),
                ),
                CogAttack(
                    "shred", "Shred",
                    damage=(2, 4, 6, 8, 10),
                    accuracy=(50, 55, 60, 65, 70),
                    frequency=(20, 20, 20, 20, 20),
                ),
                CogAttack(
                    "watercooler", "Watercooler",
                    damage=(3, 4, 5, 6, 7),
                    accuracy=(95, 95, 95, 95, 95),
                    frequency=(10, 10, 10, 10, 10),
                ),
                CogAttack(
                    "pick_pocket", "Pick Pocket",
                    damage=(1, 1, 2, 2, 3),
                    accuracy=(25, 30, 35, 40, 45),
                    frequency=(50, 50, 50, 50, 50),
                ),
            ),
    ),
    Cog(
        key="bloodsucker",
        display="Bloodsucker",
        department="lawbot",
        levels=(2, 3, 4, 5, 6),
        # Wiki: https://toontownrewritten.wiki/Bloodsucker
        # [RESOLVED] Appendix A spelled this attack "Withdrawl", B and C
        # "Withdrawal". The wiki uses Withdrawal, which is the key here.
        attacks=(
            CogAttack(
                "eviction_notice", "Eviction Notice",
                damage=(1, 2, 3, 3, 4),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "red_tape", "Red Tape",
                damage=(2, 3, 4, 6, 9),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "withdrawal", "Withdrawal",
                damage=(6, 8, 10, 12, 14),
                accuracy=(95, 95, 95, 95, 95),
                frequency=(10, 10, 10, 10, 10),
            ),
            CogAttack(
                "liquidate", "Liquidate",
                damage=(2, 3, 4, 6, 9),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(50, 50, 50, 50, 50),
            ),
        ),
    ),
    Cog(
        key="double_talker",
        display="Double Talker",
        department="lawbot",
        levels=(3, 4, 5, 6, 7),
        # Wiki: https://toontownrewritten.wiki/Double_Talker
        # [RESOLVED] Appendix A spelled this "Buzzword", B and C "Buzz Word";
        # the wiki uses Buzz Word. Key is buzz_word package-wide.
        # [CORRECTED] group_attacks was {"buzz_word"} on the strength of
        # Appendix B's Type column. The wiki says Buzz Word is a single-
        # target attack: the Double Talker page gives Target = One Toon,
        # https://toontownrewritten.wiki/Buzz_Word gives Target = One Toon
        # and files it under Category:Single Cog attacks, and the same
        # attack is single-target on Micromanager and The Mingler too.
        # Double Talker now has no group attacks at all.
        attacks=(
            CogAttack(
                "rubber_stamp", "Rubber Stamp",
                damage=(1, 1, 1, 1, 1),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(5, 5, 5, 5, 5),
            ),
            CogAttack(
                "bounce_check", "Bounce Check",
                damage=(1, 1, 1, 1, 1),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(5, 5, 5, 5, 5),
            ),
            CogAttack(
                "buzz_word", "Buzz Word",
                damage=(1, 2, 3, 5, 6),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "double_talk", "Double Talk",
                damage=(6, 6, 9, 13, 18),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "jargon", "Jargon",
                damage=(3, 4, 6, 9, 12),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "mumbo_jumbo", "Mumbo Jumbo",
                damage=(3, 4, 6, 9, 12),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
        ),
    ),
    Cog(
        key="ambulance_chaser",
        display="Ambulance Chaser",
        department="lawbot",
        levels=(4, 5, 6, 7, 8),
        # Wiki: https://toontownrewritten.wiki/Ambulance_Chaser
        attacks=(
            CogAttack(
                "shake", "Shake",
                damage=(4, 6, 9, 12, 15),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(15, 15, 15, 15, 15),
                group=True,
            ),
            CogAttack(
                "red_tape", "Red Tape",
                damage=(6, 8, 12, 15, 19),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "rolodex", "Rolodex",
                damage=(3, 4, 5, 6, 7),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "hang_up", "Hang Up",
                damage=(2, 3, 4, 5, 6),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(35, 35, 35, 35, 35),
            ),
        ),
    ),
    Cog(
        key="backstabber",
        display="Backstabber",
        department="lawbot",
        levels=(5, 6, 7, 8, 9),
        # Wiki: https://toontownrewritten.wiki/Back_Stabber (the wiki spells
        # the cog's name as two words; the key stays backstabber).
        attacks=(
            CogAttack(
                "guilt_trip", "Guilt Trip",
                damage=(8, 11, 13, 15, 18),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(40, 40, 40, 40, 40),
                group=True,
            ),
            CogAttack(
                "restraining_order", "Restraining Order",
                damage=(6, 7, 9, 11, 13),
                accuracy=(50, 65, 70, 75, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(5, 6, 7, 8, 9),
                accuracy=(50, 55, 65, 75, 80),
                frequency=(35, 35, 35, 35, 35),
            ),
        ),
    ),
    Cog(
        key="spin_doctor",
        display="Spin Doctor",
        department="lawbot",
        levels=(6, 7, 8, 9, 10),
        # Wiki: https://toontownrewritten.wiki/Spin_Doctor
        # [RESOLVED] Appendix C listed a 5th Spin Doctor attack, "Rolodex"
        # (60/65/70/75/80), that Appendices A and B did not. It was
        # omitted here as unselectable. The wiki confirms the omission
        # was right: Spin Doctor's roster is these four attacks, and
        # https://toontownrewritten.wiki/Rolodex lists its users as Head
        # Hunter, Ambulance Chaser, Name Dropper and Telemarketer -- not
        # Spin Doctor.
        attacks=(
            CogAttack(
                "paradigm_shift", "Paradigm Shift",
                damage=(9, 10, 13, 16, 17),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(30, 30, 30, 30, 30),
                group=True,
            ),
            CogAttack(
                "quake", "Quake",
                damage=(8, 10, 12, 14, 16),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(20, 20, 20, 20, 20),
                group=True,
            ),
            CogAttack(
                "spin", "Spin",
                damage=(10, 12, 15, 18, 20),
                accuracy=(70, 75, 80, 85, 90),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "write_off", "Write Off",
                damage=(6, 7, 8, 9, 10),
                accuracy=(60, 65, 75, 85, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
        ),
    ),
    Cog(
        key="legal_eagle",
        display="Legal Eagle",
        department="lawbot",
        levels=(7, 8, 9, 10, 11),
        # Wiki: https://toontownrewritten.wiki/Legal_Eagle
        attacks=(
            CogAttack(
                "evil_eye", "Evil Eye",
                damage=(10, 11, 13, 15, 16),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "jargon", "Jargon",
                damage=(7, 9, 11, 13, 15),
                accuracy=(60, 70, 75, 80, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "legalese", "Legalese",
                damage=(11, 13, 16, 19, 21),
                accuracy=(55, 65, 75, 85, 95),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "pecking_order", "Pecking Order",
                damage=(15, 15, 17, 19, 22),
                accuracy=(70, 75, 80, 85, 95),
                frequency=(30, 30, 30, 30, 30),
            ),
        ),
    ),
    Cog(
        key="big_wig",
        display="Big Wig",
        department="lawbot",
        levels=(8, 9, 10, 11, 12),
        # Wiki: https://toontownrewritten.wiki/Big_Wig
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        # A 50/50 split over two attacks cannot be right for a
        # four-attack cog.
        # finger_wag damage: RESOLVED by triangulation. The wiki appeared to
        # contradict itself -- the Big Wig page gives 9, 11, 13, 16, 18
        # while https://toontownrewritten.wiki/Finger_Wag gives
        # 13, 15, 17, 19, 21 for the same five levels.
        #
        # The Finger_Wag page is misattributing Throw Book's row. Three
        # independent places agree Big Wig's THROW BOOK damage is exactly
        # 13, 15, 17, 19, 21: the wiki's own Throw Book entry for this
        # cog (see unmodeled_attacks below), Open Toontown's
        # SuitBattleGlobals.py, and the pre-rebalance guide -- which also
        # listed this row under "finger_wag" even though Toontown Online's
        # Big Wig has no Finger Wag at all, only Power Trip and Throw
        # Book. So the row was mislabeled at the source and the wiki's
        # per-attack page inherited the error.
        #
        # That leaves the Big Wig page's 9, 11, 13, 16, 18 as the only
        # unexplained-away figure for Finger Wag, and it is monotonic
        # across the over-level seam where the other row is not. Filled
        # in from it. [CONFIRMED] wiki, Big Wig page.
        attacks=(
            CogAttack(
                "power_trip", "Power Trip",
                damage=(10, 11, 13, 15, 16),
                accuracy=(75, 80, 85, 90, 95),
                frequency=(50, 50, 50, 50, 50),
                group=True,
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(9, 11, 13, 16, 18),
                accuracy=(80, 85, 85, 85, 90),
                frequency=(50, 50, 50, 50, 50),
            ),
            CogAttack(
                "quash", "Quash",
                damage=(12, 13, 15, 17, 19),
                group=True, modeled=False,
            ),
            CogAttack(
                "throw_book", "Throw Book",
                damage=(13, 15, 17, 19, 21),
                group=False, modeled=False,
            ),
        ),
    ),
    ),
)

# Backwards-compatible alias; Department indexes by cog key like the old dict.
LAWBOT_COGS = LAWBOT
