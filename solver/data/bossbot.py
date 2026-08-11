"""
Bossbot cog attack tables.

One `Cog` per entry, each holding a tuple of `CogAttack` (see data/types.py).
An attack's damage/accuracy/frequency are per *relative* level -- use
`cog.damage_at(attack, level)` and friends, which do the index arithmetic and
raise naming the exact cell if it is a documented gap. `modeled=False` marks
an attack the wiki confirms this cog has but which the simulator cannot fire. See "The 4.0.0 hole" below.

TWO SOURCES, TWO CONFIDENCE LEVELS -- READ THIS BEFORE EDITING
--------------------------------------------------------------
[CONFIRMED] from the TTR wiki (<https://toontownrewritten.wiki>), fetched
through its MediaWiki API and cross-checked between each cog's own page and
each attack's own page:

  * "levels"          -- the cog's normal range (infobox llevel/hlevel)
  * "damage"          -- the CogAttackTable / AttackTable damage rows
  * "group_attacks"   -- the "Target" row (One Toon vs Group), corroborated
                         by Category:Single Cog attacks / Group Cog attacks
  * the attack roster -- which attacks the cog actually has

[UNVERIFIED -- GUIDE-DERIVED] still from the QED1224/Toontown-Resources
strategy-guide README (**master branch**), Appendix A and Appendix C:

  * "freq"
  * "accuracy"

The wiki publishes neither number anywhere. Its "Cog attack" page defines
both concepts and gives no values; no cog page, attack page, or template
carries them; a search for them turns up nothing. So these two columns could
not be checked against the wiki and are left exactly as the guide had them.
They are deliberately NOT tagged [CONFIRMED]. The guide describes *Toontown
Online*, and per the changelog below TTR has since changed both columns.

THE 4.0.0 HOLE
--------------
TTR 4.0.0 ("Under New Management", 2024) rebalanced cog attacks wholesale.
From the wiki's Release notes (2024), section "Cog Attacks":

  "All Cog Attacks across all Cog departments have been rebalanced to make
   them all on an equal footing of overall strength"
  "Tweaked numerous accuracy values of the over-leveled Sellbots that were
   mildly over-tuned, and established values for the over-leveled Cogs in
   the other Cog departments."
  "Tweaked numerous frequency values across all Cogs that have their attack
   pool updated."
  "Introducing 12 new Cog Attacks that help provide variety and accommodate
   for some missing damage that some Cog departments have been lacking."

Earlier, TTR 3.0.0 (2021) rebalanced cog *health* -- see data.cog_max_hp.

Two consequences for the tables below:

1. For any cog whose roster changed, the guide's frequencies are not merely
   unverified, they are known stale: they distribute 100% over the wrong set
   of attacks. Those cogs are tagged [FREQ STALE] inline.

2. The new attacks are wiki-confirmed (name, damage, target, level span) but
   have no frequency, so they cannot be sampled. They are carried as CogAttack(modeled=False). Putting them
   in the main tables with a None frequency would make
   mechanics.pick_cog_attack and outcomes.cog_damage_distribution blow up
   inside a *sum* over frequencies, which reads as a simulator bug rather
   than a documented data gap -- and would break callers that legitimately
   expect a NotImplementedError. **The simulator therefore UNDER-estimates
   every cog carrying an "unmodeled_attacks" entry.**

OVER-LEVELED COGS
-----------------
The wiki confirms every cog can appear three levels above its normal range
("Flunky can have three additional levels, up to level 8"), an 8-level span,
and publishes damage for all 8. Only the normal 5 are modeled: levels 6-8 of
the span have no frequency or accuracy from either source, so a cog there
could not be simulated anyway. The "levels" lists were checked against the
wiki's llevel-hlevel for all 32 cogs and every one already matched.

A `None` in an otherwise-filled list is a per-cell [TODO]: a value neither
source gives unambiguously, left blank rather than guessed at, and called out
in a comment where it appears. mechanics.cog_attack_damage_and_accuracy and
outcomes.cog_damage_distribution both null-check per cell and raise
NotImplementedError naming the cell.
"""
from .types import Cog, CogAttack, Department

BOSSBOT = Department(
    key="bossbot",
    display="Bossbots",
    cogs=(
        Cog(
            key="flunky",
            display="Flunky",
            department="bossbot",
            levels=(1, 2, 3, 4, 5),
            # Wiki: https://toontownrewritten.wiki/Flunky
            attacks=(
                CogAttack(
                    "pound_key", "Pound Key",
                    damage=(2, 2, 3, 4, 6),
                    accuracy=(75, 75, 80, 80, 90),
                    frequency=(30, 35, 40, 45, 50),
                ),
                CogAttack(
                    "shred", "Shred",
                    damage=(3, 4, 5, 6, 7),
                    accuracy=(50, 55, 60, 65, 70),
                    frequency=(10, 15, 20, 25, 30),
                ),
                CogAttack(
                    "clip_on_tie", "Clip On Tie",
                    damage=(1, 1, 2, 2, 3),
                    accuracy=(75, 80, 85, 90, 95),
                    frequency=(60, 50, 40, 30, 20),
                ),
            ),
    ),
    Cog(
        key="pencil_pusher",
        display="Pencil Pusher",
        department="bossbot",
        levels=(2, 3, 4, 5, 6),
        # Wiki: https://toontownrewritten.wiki/Pencil_Pusher
        # [RESOLVED] The guide's appendices disagreed on this cog's first
        # attack: A and C called it "Fountain Pencil", B "Fountain Pen".
        # The wiki settles it -- the attack is Fountain Pen, and the key
        # already used here was the right one.
        attacks=(
            CogAttack(
                "fountain_pen", "Fountain Pen",
                damage=(2, 3, 4, 6, 9),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "rub_out", "Rub Out",
                damage=(4, 5, 6, 8, 12),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(1, 2, 2, 3, 4),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(35, 30, 25, 20, 15),
            ),
            CogAttack(
                "write_off", "Write Off",
                damage=(4, 6, 8, 10, 12),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(5, 10, 15, 20, 25),
            ),
            CogAttack(
                "fill_with_lead", "Fill With Lead",
                damage=(3, 4, 5, 6, 7),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(20, 20, 20, 20, 20),
            ),
        ),
    ),
    Cog(
        key="yesman",
        display="Yesman",
        department="bossbot",
        levels=(3, 4, 5, 6, 7),
        # Wiki: https://toontownrewritten.wiki/Yesman
        attacks=(
            CogAttack(
                "rubber_stamp", "Rubber Stamp",
                damage=(2, 2, 3, 3, 4),
                accuracy=(75, 75, 75, 75, 75),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "razzle_dazzle", "Razzle Dazzle",
                damage=(1, 1, 1, 1, 1),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(25, 20, 15, 10, 5),
            ),
            CogAttack(
                "synergy", "Synergy",
                damage=(4, 5, 6, 7, 8),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(5, 10, 15, 20, 25),
                group=True,
            ),
            CogAttack(
                "tee_off", "Tee Off",
                damage=(3, 3, 4, 4, 5),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(35, 35, 35, 35, 35),
            ),
        ),
    ),
    Cog(
        key="micromanager",
        display="Micromanager",
        department="bossbot",
        levels=(4, 5, 6, 7, 8),
        # Wiki: https://toontownrewritten.wiki/Micromanager
        # [FREQ STALE] The wiki's roster has SIX attacks; the guide had five.
        # Close the Loop is one of 4.0.0's new attacks, so per the 4.0.0
        # note "frequency values across all Cogs that have their attack
        # pool updated" were tweaked -- the frequencies below are the
        # pre-4.0.0 five-attack split and no longer describe this cog.
        # brain_storm accuracy: RESOLVED, and the suspicion was wrong. A flat
        # 5 looked like a dropped zero -- the other four attacks run
        # 50/60/70/80/90 and nothing else in Appendix C is under 10 -- so
        # it was left None. Open Toontown's SuitBattleGlobals.py carries
        # ('BrainStorm', (4, 6, 9, 12, 15), (5, 5, 5, 5, 5), ...), i.e.
        # the guide transcribed it faithfully and the value really is
        # that low. Filled in, and [UNVERIFIED] for TTR exactly like every
        # other accuracy row rather than held to a stricter standard.
        attacks=(
            CogAttack(
                "demotion", "Demotion",
                damage=(6, 8, 12, 15, 18),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "finger_wag", "Finger Wag",
                damage=(4, 6, 9, 12, 15),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(10, 10, 10, 10, 10),
            ),
            CogAttack(
                "fountain_pen", "Fountain Pen",
                damage=(3, 4, 6, 8, 10),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "brain_storm", "Brain Storm",
                damage=(4, 6, 9, 12, 15),
                accuracy=(5, 5, 5, 5, 5),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "buzz_word", "Buzz Word",
                damage=(4, 6, 9, 12, 15),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "close_the_loop", "Close The Loop",
                damage=(3, 5, 7, 10, 12),
                group=True, modeled=False,
            ),
        ),
    ),
    Cog(
        key="downsizer",
        display="Downsizer",
        department="bossbot",
        levels=(5, 6, 7, 8, 9),
        # Wiki: https://toontownrewritten.wiki/Downsizer
        # [RESOLVED] Guide appendices split on "Pinkslip" (A, C) vs "Pink
        # Slip" (B); the wiki's attack is Pink Slip.
        attacks=(
            CogAttack(
                "canned", "Canned",
                damage=(5, 6, 8, 10, 12),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "downsize", "Downsize",
                damage=(8, 9, 11, 13, 15),
                accuracy=(50, 65, 70, 75, 80),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "pink_slip", "Pink Slip",
                damage=(4, 5, 6, 7, 8),
                accuracy=(60, 65, 75, 80, 85),
                frequency=(25, 25, 25, 25, 25),
            ),
            CogAttack(
                "sacked", "Sacked",
                damage=(5, 6, 7, 8, 9),
                accuracy=(50, 50, 50, 50, 50),
                frequency=(15, 15, 15, 15, 15),
            ),
        ),
    ),
    Cog(
        key="head_hunter",
        display="Head Hunter",
        department="bossbot",
        levels=(6, 7, 8, 9, 10),
        # Wiki: https://toontownrewritten.wiki/Head_Hunter
        # Head Hunter really does have Rolodex (wiki Rolodex page lists this
        # cog); Corporate Raider does not -- see that entry.
        attacks=(
            CogAttack(
                "fountain_pen", "Fountain Pen",
                damage=(5, 6, 8, 10, 12),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "glower_power", "Glower Power",
                damage=(7, 8, 10, 12, 13),
                accuracy=(50, 60, 70, 80, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "half_windsor", "Half Windsor",
                damage=(8, 10, 12, 14, 16),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "head_shrink", "Head Shrink",
                damage=(10, 12, 15, 18, 21),
                accuracy=(65, 75, 80, 85, 95),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "rolodex", "Rolodex",
                damage=(6, 7, 8, 9, 10),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(10, 10, 10, 10, 10),
            ),
        ),
    ),
    Cog(
        key="corporate_raider",
        display="Corporate Raider",
        department="bossbot",
        levels=(7, 8, 9, 10, 11),
        # Wiki: https://toontownrewritten.wiki/Corporate_Raider
        # [RESOLVED] The guide's appendices disagreed on the 4th attack:
        # A and C said "Rolodex", B said "Power Tie". The wiki settles it
        # in B's favour -- Corporate Raider's attack is Power Tie
        # (https://toontownrewritten.wiki/Power_Tie lists this cog; the
        # Rolodex page does not). The key was renamed rolodex ->
        # power_tie; the numbers are unchanged, and the wiki's damage row
        # [10, 12, 14, 16, 18] matches the one the guide had under both
        # names, so no frequency or accuracy was reassigned.
        # [FREQ STALE] The wiki's roster has FIVE attacks; the guide had four.
        # Hostile Takeover is new in 4.0.0, so the split below predates
        # the pool change.
        attacks=(
            CogAttack(
                "canned", "Canned",
                damage=(6, 7, 8, 9, 10),
                accuracy=(60, 75, 80, 85, 90),
                frequency=(20, 20, 20, 20, 20),
            ),
            CogAttack(
                "evil_eye", "Evil Eye",
                damage=(12, 15, 18, 21, 24),
                accuracy=(60, 70, 75, 80, 90),
                frequency=(35, 35, 35, 35, 35),
            ),
            CogAttack(
                "play_hardball", "Play Hardball",
                damage=(7, 8, 12, 15, 16),
                accuracy=(60, 65, 70, 75, 80),
                frequency=(30, 30, 30, 30, 30),
            ),
            CogAttack(
                "power_tie", "Power Tie",
                damage=(10, 12, 14, 16, 18),
                accuracy=(65, 75, 80, 85, 95),
                frequency=(15, 15, 15, 15, 15),
            ),
            CogAttack(
                "hostile_takeover", "Hostile Takeover",
                damage=(10, 13, 14, 15, 18),
                group=True, modeled=False,
            ),
        ),
    ),
    Cog(
        key="the_big_cheese",
        display="The Big Cheese",
        department="bossbot",
        levels=(8, 9, 10, 11, 12),
        # Wiki: https://toontownrewritten.wiki/The_Big_Cheese
        # [RESOLVED] glower_power damage. The guide gave three values per
        # level ("10, 14, 14") because, per its Appendix C footnote, The
        # Big Cheese had three unused attacks (CigarSmoke, FloodTheMarket,
        # SongAndDance) that all rendered as Glower Power while keeping
        # their own stats. TTR 4.0.0 un-hid them: Flood the Market and
        # Power Trip are now real, separately-named attacks on this cog,
        # and Glower Power has a single damage row of its own --
        # [10, 12, 15, 18, 20], confirmed on both the cog page and
        # https://toontownrewritten.wiki/Glower_Power. The first of the
        # guide's three values (10) turns out to have been the Glower
        # Power one, but that is hindsight, not how the value was chosen.
        # [TODO] glower_power accuracy stays None: the guide gave three
        # values for the same reason, and the wiki publishes no accuracy.
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        # A 50/50 split over two attacks cannot be right for a four-attack
        # cog.
        attacks=(
            CogAttack(
                "tee_off", "Tee Off",
                damage=(8, 11, 14, 17, 20),
                accuracy=(55, 65, 70, 75, 80),
                frequency=(50, 50, 50, 50, 50),
            ),
            CogAttack(
                "glower_power", "Glower Power",
                damage=(10, 12, 15, 18, 20),
                accuracy=(None, None, None, None, None),
                frequency=(50, 50, 50, 50, 50),
            ),
            CogAttack(
                "power_trip", "Power Trip",
                damage=(11, 13, 14, 16, 19),
                group=True, modeled=False,
            ),
            CogAttack(
                "flood_the_market", "Flood The Market",
                damage=(13, 15, 16, 18, 21),
                group=True, modeled=False,
            ),
        ),
    ),
    ),
)

# Backwards-compatible alias; Department indexes by cog key like the old dict.
BOSSBOT_COGS = BOSSBOT
