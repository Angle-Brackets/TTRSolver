"""
Bossbot cog attack tables.

Each cog entry:
  "levels":            list of absolute levels this cog can appear at; index
                       into the per-attack lists is (cog.level - levels[0])
  "freq":              {attack_name: [freq% at each relative level]}
  "damage":            {attack_name: [(min,max) or fixed int, at each level]}
  "accuracy":          {attack_name: [accuracy% at each relative level]}
  "group_attacks":     set of attack names that hit all toons
  "unmodeled_attacks": {name: {"damage": [...], "group": bool}} -- attacks
                       the wiki confirms this cog really has but which the
                       simulator cannot fire. See "The 4.0.0 hole" below.

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
   have no frequency, so they cannot be sampled. They live in
   "unmodeled_attacks" instead of in "freq"/"damage"/"accuracy". Putting them
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

BOSSBOT_COGS = {
    "flunky": {
        # Wiki: https://toontownrewritten.wiki/Flunky
        "levels": [1, 2, 3, 4, 5],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "pound_key":   [30, 35, 40, 45, 50],
            "shred":       [10, 15, 20, 25, 30],
            "clip_on_tie": [60, 50, 40, 30, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "pound_key":   [2, 2, 3, 4, 6],
            "shred":       [3, 4, 5, 6, 7],
            "clip_on_tie": [1, 1, 2, 2, 3],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "pound_key":   [75, 75, 80, 80, 90],
            "shred":       [50, 55, 60, 65, 70],
            "clip_on_tie": [75, 80, 85, 90, 95],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all three "One Toon"
        "unmodeled_attacks": {},
    },
    "pencil_pusher": {
        # Wiki: https://toontownrewritten.wiki/Pencil_Pusher
        # [RESOLVED] The guide's appendices disagreed on this cog's first
        #     attack: A and C called it "Fountain Pencil", B "Fountain Pen".
        #     The wiki settles it -- the attack is Fountain Pen, and the key
        #     already used here was the right one.
        "levels": [2, 3, 4, 5, 6],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "fountain_pen":   [20, 20, 20, 20, 20],
            "rub_out":        [20, 20, 20, 20, 20],
            "finger_wag":     [35, 30, 25, 20, 15],
            "write_off":      [ 5, 10, 15, 20, 25],
            "fill_with_lead": [20, 20, 20, 20, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "fountain_pen":   [ 2,  3,  4,  6,  9],
            "rub_out":        [ 4,  5,  6,  8, 12],
            "finger_wag":     [ 1,  2,  2,  3,  4],
            "write_off":      [ 4,  6,  8, 10, 12],
            "fill_with_lead": [ 3,  4,  5,  6,  7],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "fountain_pen":   [75, 75, 75, 75, 75],
            "rub_out":        [75, 75, 75, 75, 75],
            "finger_wag":     [75, 75, 75, 75, 75],
            "write_off":      [75, 75, 75, 75, 75],
            "fill_with_lead": [75, 75, 75, 75, 75],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all five "One Toon"
        "unmodeled_attacks": {},
    },
    "yesman": {
        # Wiki: https://toontownrewritten.wiki/Yesman
        "levels": [3, 4, 5, 6, 7],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "rubber_stamp":  [35, 35, 35, 35, 35],
            "razzle_dazzle": [25, 20, 15, 10,  5],
            "synergy":       [ 5, 10, 15, 20, 25],
            "tee_off":       [35, 35, 35, 35, 35],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "rubber_stamp":  [2, 2, 3, 3, 4],
            "razzle_dazzle": [1, 1, 1, 1, 1],
            "synergy":       [4, 5, 6, 7, 8],
            "tee_off":       [3, 3, 4, 4, 5],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "rubber_stamp":  [75, 75, 75, 75, 75],
            "razzle_dazzle": [50, 50, 50, 50, 50],
            "synergy":       [50, 60, 70, 80, 90],
            "tee_off":       [50, 60, 70, 80, 90],
        },
        "group_attacks": {"synergy"},  # [CONFIRMED] wiki: Synergy is "Group"
        "unmodeled_attacks": {},
    },
    "micromanager": {
        # Wiki: https://toontownrewritten.wiki/Micromanager
        # [FREQ STALE] The wiki's roster has SIX attacks; the guide had five.
        #     Close the Loop is one of 4.0.0's new attacks, so per the 4.0.0
        #     note "frequency values across all Cogs that have their attack
        #     pool updated" were tweaked -- the frequencies below are the
        #     pre-4.0.0 five-attack split and no longer describe this cog.
        # [TODO] brain_storm accuracy: the guide lists a flat 5 at every level
        #     while all four other Micromanager attacks run 50/60/70/80/90, and
        #     no other attack anywhere in Appendix C is below 10. The wiki
        #     publishes no cog accuracy at all, so it cannot arbitrate. Still
        #     None rather than "corrected" to 50.
        "levels": [4, 5, 6, 7, 8],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "demotion":     [30, 30, 30, 30, 30],
            "finger_wag":   [10, 10, 10, 10, 10],
            "fountain_pen": [15, 15, 15, 15, 15],
            "brain_storm":  [25, 25, 25, 25, 25],
            "buzz_word":    [20, 20, 20, 20, 20],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "demotion":     [ 6,  8, 12, 15, 18],
            "finger_wag":   [ 4,  6,  9, 12, 15],
            "fountain_pen": [ 3,  4,  6,  8, 10],
            "brain_storm":  [ 4,  6,  9, 12, 15],
            "buzz_word":    [ 4,  6,  9, 12, 15],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "demotion":     [  50,   60,   70,   80,   90],
            "finger_wag":   [  50,   60,   70,   80,   90],
            "fountain_pen": [  50,   60,   70,   80,   90],
            "brain_storm":  [None, None, None, None, None],
            "buzz_word":    [  50,   60,   70,   80,   90],
        },
        # [CONFIRMED] wiki: the five modeled attacks are all "One Toon".
        "group_attacks": set(),
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: https://toontownrewritten.wiki/Close_the_Loop
            # Micromanager's signature attack, added in TTR 4.0.0. No
            # frequency is published, so it cannot be sampled.
            "close_the_loop": {"damage": [3, 5, 7, 10, 12], "group": True},
        },
    },
    "downsizer": {
        # Wiki: https://toontownrewritten.wiki/Downsizer
        # [RESOLVED] Guide appendices split on "Pinkslip" (A, C) vs "Pink
        #     Slip" (B); the wiki's attack is Pink Slip.
        "levels": [5, 6, 7, 8, 9],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "canned":    [25, 25, 25, 25, 25],
            "downsize":  [35, 35, 35, 35, 35],
            "pink_slip": [25, 25, 25, 25, 25],
            "sacked":    [15, 15, 15, 15, 15],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "canned":    [ 5,  6,  8, 10, 12],
            "downsize":  [ 8,  9, 11, 13, 15],
            "pink_slip": [ 4,  5,  6,  7,  8],
            "sacked":    [ 5,  6,  7,  8,  9],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "canned":    [60, 75, 80, 85, 90],
            "downsize":  [50, 65, 70, 75, 80],
            "pink_slip": [60, 65, 75, 80, 85],
            "sacked":    [50, 50, 50, 50, 50],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all four "One Toon"
        "unmodeled_attacks": {},
    },
    "head_hunter": {
        # Wiki: https://toontownrewritten.wiki/Head_Hunter
        # Head Hunter really does have Rolodex (wiki Rolodex page lists this
        # cog); Corporate Raider does not -- see that entry.
        "levels": [6, 7, 8, 9, 10],
        "freq": {  # [UNVERIFIED] guide Appendix A
            "fountain_pen": [15, 15, 15, 15, 15],
            "glower_power": [20, 20, 20, 20, 20],
            "half_windsor": [20, 20, 20, 20, 20],
            "head_shrink":  [35, 35, 35, 35, 35],
            "rolodex":      [10, 10, 10, 10, 10],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "fountain_pen": [ 5,  6,  8, 10, 12],
            "glower_power": [ 7,  8, 10, 12, 13],
            "half_windsor": [ 8, 10, 12, 14, 16],
            "head_shrink":  [10, 12, 15, 18, 21],
            "rolodex":      [ 6,  7,  8,  9, 10],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "fountain_pen": [60, 75, 80, 85, 90],
            "glower_power": [50, 60, 70, 80, 90],
            "half_windsor": [60, 65, 70, 75, 80],
            "head_shrink":  [65, 75, 80, 85, 95],
            "rolodex":      [60, 65, 70, 75, 80],
        },
        "group_attacks": set(),  # [CONFIRMED] wiki: all five "One Toon"
        "unmodeled_attacks": {},
    },
    "corporate_raider": {
        # Wiki: https://toontownrewritten.wiki/Corporate_Raider
        # [RESOLVED] The guide's appendices disagreed on the 4th attack:
        #     A and C said "Rolodex", B said "Power Tie". The wiki settles it
        #     in B's favour -- Corporate Raider's attack is Power Tie
        #     (https://toontownrewritten.wiki/Power_Tie lists this cog; the
        #     Rolodex page does not). The key was renamed rolodex ->
        #     power_tie; the numbers are unchanged, and the wiki's damage row
        #     [10, 12, 14, 16, 18] matches the one the guide had under both
        #     names, so no frequency or accuracy was reassigned.
        # [FREQ STALE] The wiki's roster has FIVE attacks; the guide had four.
        #     Hostile Takeover is new in 4.0.0, so the split below predates
        #     the pool change.
        "levels": [7, 8, 9, 10, 11],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "canned":        [20, 20, 20, 20, 20],
            "evil_eye":      [35, 35, 35, 35, 35],
            "play_hardball": [30, 30, 30, 30, 30],
            "power_tie":     [15, 15, 15, 15, 15],
        },
        "damage": {  # [CONFIRMED] wiki -- agrees with the guide throughout
            "canned":        [ 6,  7,  8,  9, 10],
            "evil_eye":      [12, 15, 18, 21, 24],
            "play_hardball": [ 7,  8, 12, 15, 16],
            "power_tie":     [10, 12, 14, 16, 18],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "canned":        [60, 75, 80, 85, 90],
            "evil_eye":      [60, 70, 75, 80, 90],
            "play_hardball": [60, 65, 70, 75, 80],
            "power_tie":     [65, 75, 80, 85, 95],
        },
        # [CONFIRMED] wiki: the four modeled attacks are all "One Toon".
        "group_attacks": set(),
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Hostile_Takeover -- Corporate Raider's
            # signature group attack, added in TTR 4.0.0. No frequency.
            "hostile_takeover": {"damage": [10, 13, 14, 15, 18], "group": True},
        },
    },
    "the_big_cheese": {
        # Wiki: https://toontownrewritten.wiki/The_Big_Cheese
        # [RESOLVED] glower_power damage. The guide gave three values per
        #     level ("10, 14, 14") because, per its Appendix C footnote, The
        #     Big Cheese had three unused attacks (CigarSmoke, FloodTheMarket,
        #     SongAndDance) that all rendered as Glower Power while keeping
        #     their own stats. TTR 4.0.0 un-hid them: Flood the Market and
        #     Power Trip are now real, separately-named attacks on this cog,
        #     and Glower Power has a single damage row of its own --
        #     [10, 12, 15, 18, 20], confirmed on both the cog page and
        #     https://toontownrewritten.wiki/Glower_Power. The first of the
        #     guide's three values (10) turns out to have been the Glower
        #     Power one, but that is hindsight, not how the value was chosen.
        # [TODO] glower_power accuracy stays None: the guide gave three
        #     values for the same reason, and the wiki publishes no accuracy.
        # [FREQ STALE] The wiki's roster has FOUR attacks; the guide had two.
        #     A 50/50 split over two attacks cannot be right for a four-attack
        #     cog.
        "levels": [8, 9, 10, 11, 12],
        "freq": {  # [UNVERIFIED, STALE] guide Appendix A, wrong attack pool
            "tee_off":      [50, 50, 50, 50, 50],
            "glower_power": [50, 50, 50, 50, 50],
        },
        "damage": {  # [CONFIRMED] wiki
            "tee_off":      [ 8, 11, 14, 17, 20],
            "glower_power": [10, 12, 15, 18, 20],
        },
        "accuracy": {  # [UNVERIFIED] guide Appendix C
            "tee_off":      [  55,   65,   70,   75,   80],
            "glower_power": [None, None, None, None, None],
        },
        # [CONFIRMED] wiki: both modeled attacks are "One Toon".
        "group_attacks": set(),
        "unmodeled_attacks": {
            # [CONFIRMED] wiki: /Power_Trip and /Flood_the_Market. Both are
            # group attacks this cog gained in TTR 4.0.0. No frequency, so
            # neither can be sampled -- this cog is badly under-modeled.
            "power_trip":       {"damage": [11, 13, 14, 16, 19], "group": True},
            "flood_the_market": {"damage": [13, 15, 16, 18, 21], "group": True},
        },
    },
}
