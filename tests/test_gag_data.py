"""Pins solver/data/gags.py against the TTR wiki audit.

These lock the literal transcriptions, the exact inventory of cells still
left None, and the invariants the wiki data actually bears out. If a future
edit fills a gap, adds one, or breaks a progression, one of these fails and
names the gag.

Nothing here recomputes a value from a formula -- every number that matters
was transcribed from the wiki and is asserted literally, so a typo in the
table cannot be masked by a matching typo in a test helper.
"""
import math
import unittest

from solver.data import gags
from solver.data.types import Gag
from solver.state import Track

LEVELS = (1, 2, 3, 4, 5, 6, 7)
DAMAGE_TRACKS = (Track.THROW, Track.SQUIRT, Track.SOUND,
                 Track.DROP, Track.TRAP)
ALL_TRACKS = DAMAGE_TRACKS + (Track.TOON_UP, Track.LURE)

# The complete inventory of values the audit could NOT confirm. Both are
# genuine three-way source conflicts, documented in data/gags.py.
# Trapdoor's organic damage used to be here. It was resolved to 83-94 by
# applying the organic rule rather than by choosing between the wiki's
# three disagreeing statements of it -- see solver/data/gags.py.
EXPECTED_MISSING = {
    ("heal", Track.TOON_UP, 3),          # Lipstick minimum heal
}


def g(track, level):
    return gags.gag(track, level)


def damages(track):
    return {lvl: g(track, lvl).damage for lvl in LEVELS}


class TestRegistryShape(unittest.TestCase):
    def test_every_track_and_level_has_exactly_one_gag(self):
        self.assertEqual(len(gags.GAGS), len(ALL_TRACKS) * 7)
        for track in ALL_TRACKS:
            for level in LEVELS:
                self.assertIsInstance(g(track, level), Gag)

    def test_lookup_rejects_levels_outside_one_to_seven(self):
        for bad in (0, 8, -1):
            with self.assertRaises(KeyError):
                g(Track.THROW, bad)

    def test_every_gag_has_a_display_name_and_an_accuracy(self):
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                self.assertTrue(gag.display.strip())
                self.assertIsInstance(gag.accuracy, int)
                self.assertGreaterEqual(gag.accuracy, 0)
                self.assertLessEqual(gag.accuracy, 100)

    def test_ranges_are_pairs_of_positive_ints_low_first(self):
        for gag in gags.GAGS:
            for name in ("damage", "organic_damage", "heal", "organic_heal"):
                span = getattr(gag, name)
                if span is None:
                    continue
                with self.subTest(gag=str(gag), field=name):
                    low, high = span
                    self.assertIsInstance(low, int)
                    self.assertIsInstance(high, int)
                    self.assertGreater(low, 0)
                    self.assertLessEqual(low, high)

    def test_only_lure_carries_a_duration_and_an_organic_accuracy(self):
        """Both fields exist on every Gag, but only Lure fills them --
        which is the whole reason Lure no longer needs its own module."""
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                if gag.track == Track.LURE:
                    self.assertIsNotNone(gag.lure_rounds)
                    self.assertIsNotNone(gag.organic_accuracy)
                else:
                    self.assertIsNone(gag.lure_rounds)
                    self.assertIsNone(gag.organic_accuracy)

    def test_damage_and_heal_do_not_coexist(self):
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                if gag.track == Track.TOON_UP:
                    self.assertIsNone(gag.damage)
                elif gag.track != Track.LURE:
                    self.assertIsNone(gag.heal)


class TestMissingCellInventory(unittest.TestCase):
    def test_missing_values_are_exactly_the_known_conflicts(self):
        found = set()
        for gag in gags.GAGS:
            if gag.track == Track.LURE:
                continue                      # Lure deals no damage
            for name in ("damage", "organic_damage", "heal", "organic_heal"):
                if gag.track == Track.TOON_UP and name.endswith("damage"):
                    continue
                if gag.track != Track.TOON_UP and name.endswith("heal"):
                    continue
                if getattr(gag, name) is None:
                    found.add((name, gag.track, gag.level))
        self.assertEqual(found, EXPECTED_MISSING)

    def test_accessors_raise_rather_than_default(self):
        with self.assertRaises(NotImplementedError):
            g(Track.TOON_UP, 3).heal_at()

    def test_trapdoor_organic_was_resolved_by_the_organic_rule(self):
        """It used to be blank: the wiki says 83-94, 84-94 and 83-93 in
        three different places. Organic damage follows
        ceil(base * (100 + bonus)/100), which reproduces 67 of the 68
        transcribed organic values, and Trap's bonus is 10% on an agreed
        base of 75-85 -- so 83-94, which is the Trap page's table."""
        gag = g(Track.TRAP, 5)
        self.assertEqual(gag.organic_damage, (83, 94))
        self.assertEqual(gags.organic_value(Track.TRAP, 75), 83)
        self.assertEqual(gags.organic_value(Track.TRAP, 85), 94)

    def test_the_organic_rule_reproduces_the_transcribed_values(self):
        """One exception, deliberately left as transcribed: Seltzer Bottle
        is recorded at 22 where the 15% rule gives 21."""
        mismatches = []
        for gag in gags.GAGS:
            if not (gag.damage and gag.organic_damage):
                continue
            for base, organic in zip(gag.damage, gag.organic_damage):
                if gags.organic_value(gag.track, base) != organic:
                    mismatches.append((gag.display, base, organic))
        self.assertEqual([m[0] for m in mismatches], ["Seltzer Bottle"])


class TestWikiValues(unittest.TestCase):
    """Literal transcriptions. These are the audit's actual product."""

    def test_throw_damage(self):
        self.assertEqual(damages(Track.THROW), {
            1: (4, 6), 2: (8, 10), 3: (14, 17), 4: (24, 27),
            5: (36, 40), 6: (48, 100), 7: (120, 120)})

    def test_squirt_damage(self):
        self.assertEqual(damages(Track.SQUIRT), {
            1: (3, 4), 2: (6, 8), 3: (10, 12), 4: (18, 21),
            5: (27, 30), 6: (36, 80), 7: (105, 105)})

    def test_sound_damage(self):
        self.assertEqual(damages(Track.SOUND), {
            1: (3, 4), 2: (5, 7), 3: (9, 11), 4: (14, 16),
            5: (19, 21), 6: (25, 50), 7: (90, 90)})

    def test_drop_damage(self):
        self.assertEqual(damages(Track.DROP), {
            1: (10, 10), 2: (18, 18), 3: (30, 30), 4: (45, 45),
            5: (60, 70), 6: (85, 170), 7: (180, 180)})

    def test_trap_damage(self):
        self.assertEqual(damages(Track.TRAP), {
            1: (10, 12), 2: (18, 20), 3: (30, 35), 4: (45, 50),
            5: (75, 85), 6: (90, 180), 7: (200, 200)})

    def test_toon_up_heals(self):
        self.assertEqual({lvl: g(Track.TOON_UP, lvl).heal for lvl in LEVELS}, {
            1: (8, 10), 2: (15, 18), 3: None, 4: (40, 45),
            5: (50, 60), 6: (75, 105), 7: (210, 210)})

    def test_lure_durations_and_accuracy(self):
        self.assertEqual({lvl: g(Track.LURE, lvl).lure_rounds for lvl in LEVELS},
                         {1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 8})
        self.assertEqual({lvl: g(Track.LURE, lvl).accuracy for lvl in LEVELS},
                         {1: 60, 2: 55, 3: 70, 4: 65, 5: 80, 6: 75, 7: 90})
        self.assertEqual(
            {lvl: g(Track.LURE, lvl).organic_accuracy for lvl in LEVELS},
            {1: 70, 2: 65, 3: 80, 4: 75, 5: 90, 6: 85, 7: 100})

    def test_sound_is_not_shifted_by_a_level(self):
        """The guide's table began at Whistle and had no Bike Horn, so every
        Sound level sat one row too low. Bike Horn is level 1."""
        self.assertEqual(g(Track.SOUND, 1).display, "Bike Horn")
        self.assertEqual(g(Track.SOUND, 1).damage, (3, 4))
        self.assertEqual(g(Track.SOUND, 6).display, "Foghorn")
        self.assertEqual(g(Track.SOUND, 6).damage, (25, 50))

    def test_ttr_renamed_and_rebalanced_level_7_trap_and_drop(self):
        self.assertEqual(g(Track.TRAP, 7).display, "Railroad")
        self.assertEqual(g(Track.TRAP, 7).damage, (200, 200))
        self.assertEqual(g(Track.DROP, 7).display, "Toontanic")
        self.assertEqual(g(Track.DROP, 7).damage, (180, 180))

    def test_level_6_gags_all_have_wide_ranges(self):
        """Throw L6 (48-100) and Sound "25-50" were both once rejected as
        implausible. Every level 6 gag in the game is like this."""
        for track in DAMAGE_TRACKS:
            low, high = g(track, 6).damage
            with self.subTest(track=track):
                self.assertGreaterEqual(high, low * 1.5)
        low, high = g(Track.TOON_UP, 6).heal
        self.assertGreater(high, low)


class TestInvariants(unittest.TestCase):
    def test_damage_is_non_decreasing_with_level(self):
        for track in DAMAGE_TRACKS:
            rows = [g(track, lvl).damage for lvl in LEVELS]
            for lvl, (prev, cur) in enumerate(zip(rows, rows[1:]), start=1):
                with self.subTest(track=track, level=lvl):
                    self.assertLessEqual(prev[0], cur[0])
                    self.assertLessEqual(prev[1], cur[1])

    def test_heal_is_non_decreasing_with_level(self):
        known = [(lvl, g(Track.TOON_UP, lvl).heal) for lvl in LEVELS
                 if g(Track.TOON_UP, lvl).heal is not None]
        for (_, prev), (lvl, cur) in zip(known, known[1:]):
            with self.subTest(level=lvl):
                self.assertLessEqual(prev[0], cur[0])
                self.assertLessEqual(prev[1], cur[1])

    def test_organic_beats_base_everywhere(self):
        for gag in gags.GAGS:
            for base_name, org_name in (("damage", "organic_damage"),
                                        ("heal", "organic_heal")):
                base, org = getattr(gag, base_name), getattr(gag, org_name)
                if base is None or org is None:
                    continue
                with self.subTest(gag=str(gag), field=org_name):
                    self.assertGreaterEqual(org[0], base[0])
                    self.assertGreaterEqual(org[1], base[1])

    def test_level_7_gags_deal_a_single_fixed_value(self):
        for track in DAMAGE_TRACKS:
            low, high = g(track, 7).damage
            with self.subTest(track=track):
                self.assertEqual(low, high)

    def test_every_level_7_gag_is_a_group_gag(self):
        for track in ALL_TRACKS:
            with self.subTest(track=track):
                self.assertTrue(g(track, 7).group)

    def test_group_levels_match_the_wiki_affects_column(self):
        expected = {
            Track.TOON_UP: {2, 4, 6, 7},
            Track.LURE:    {2, 4, 6, 7},
            Track.SOUND:   {1, 2, 3, 4, 5, 6, 7},
            Track.TRAP:    {7},
            Track.THROW:   {7},
            Track.SQUIRT:  {7},
            Track.DROP:    {7},
        }
        for track, levels in expected.items():
            actual = {x.level for x in gags.gags_in(track) if x.group}
            with self.subTest(track=track):
                self.assertEqual(actual, levels)


class TestOrganicRule(unittest.TestCase):
    def test_bonus_covers_every_damage_track_plus_toon_up(self):
        self.assertEqual(set(gags.ORGANIC_BONUS_PCT),
                         set(DAMAGE_TRACKS) | {Track.TOON_UP})

    def test_organic_value_uses_exact_integer_ceiling(self):
        """1.1 * 100 is 110.00000000000001 in float, so ceil() of it gives
        111 and overstates an organic Birthday Cake. Integer arithmetic
        doesn't have that edge -- this is a regression test for it."""
        self.assertEqual(gags.organic_value(Track.THROW, 100), 110)
        self.assertEqual(math.ceil(1.1 * 100), 111)     # the trap avoided

    def test_formula_reproduces_the_tables_except_the_known_exception(self):
        mismatches = []
        for gag in gags.GAGS:
            if gag.damage is None or gag.organic_damage is None:
                continue
            predicted = tuple(gags.organic_value(gag.track, v) for v in gag.damage)
            if predicted != gag.organic_damage:
                mismatches.append(str(gag))
        # Squirt 4 (Seltzer Bottle): every wiki source says organic 22-25,
        # the formula gives 21. Tables win; pinned so nobody "fixes" it.
        self.assertEqual(mismatches, ["Seltzer Bottle (squirt 4)"])


class TestLoadoutLimits(unittest.TestCase):
    """What a toon may actually carry. [CONFIRMED] from the wiki: six tracks
    of seven, and a full pouch is 80 gags."""

    def test_limits_match_the_wiki(self):
        self.assertEqual(gags.MAX_GAG_TRACKS, 6)
        self.assertEqual(gags.MAX_POUCH, 80)
        self.assertEqual(gags.POUCH_CAPACITIES["Starting Pouch"], 20)
        self.assertEqual(gags.POUCH_CAPACITIES["Large Backpack"], 80)

    def test_a_normal_loadout_is_legal(self):
        self.assertEqual(gags.validate_loadout(
            {(Track.THROW, 3): 10, (Track.LURE, 2): 5}), [])

    def test_seven_tracks_is_rejected(self):
        """No toon has all seven; every real loadout gives one up."""
        problems = gags.validate_loadout({(t, 1): 1 for t in Track})
        self.assertEqual(len(problems), 1)
        self.assertIn("track", problems[0])
        self.assertIn(str(gags.MAX_GAG_TRACKS), problems[0])

    def test_six_tracks_is_fine(self):
        six = list(Track)[:6]
        self.assertEqual(gags.validate_loadout({(t, 1): 1 for t in six}), [])

    # Filling a pouch takes several gags: no single gag's own cap reaches
    # 80, so a one-gag loadout hits the per-gag limit long before the pouch
    # limit. 30 + 25 + 20 + 5 across two tracks is exactly full and legal.
    FULL_POUCH = {(Track.THROW, 1): 30, (Track.THROW, 2): 25,
                  (Track.THROW, 3): 20, (Track.LURE, 1): 5}

    def test_exactly_a_full_pouch_is_fine(self):
        self.assertEqual(sum(self.FULL_POUCH.values()), gags.MAX_POUCH)
        self.assertEqual(gags.validate_loadout(self.FULL_POUCH), [])

    def test_an_overfull_pouch_is_rejected(self):
        over = dict(self.FULL_POUCH)
        over[(Track.LURE, 1)] += 1
        problems = gags.validate_loadout(over)
        self.assertEqual(len(problems), 1)
        self.assertIn(str(gags.MAX_POUCH), problems[0])

    def test_no_single_gag_can_fill_a_pouch(self):
        """Which is why the pouch limit is never the first thing you hit."""
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                self.assertLess(gag.max_carry, gags.MAX_POUCH)

    def test_per_gag_caps_are_enforced(self):
        problems = gags.validate_loadout({(Track.THROW, 6): 20})
        self.assertEqual(len(problems), 1)
        self.assertIn("Birthday Cake", problems[0])
        self.assertIn("3", problems[0])
        self.assertEqual(gags.validate_loadout({(Track.THROW, 6): 3}), [])

    def test_every_gag_has_a_carry_limit(self):
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                self.assertIsNotNone(gag.max_carry)
                self.assertGreaterEqual(gag.max_carry, 1)
                self.assertLessEqual(gag.min_carry, gag.max_carry)

    def test_limits_shrink_as_gags_get_stronger(self):
        """Level 7s are one-per-pouch; caps fall monotonically with level."""
        for track in ALL_TRACKS:
            caps = [g(track, lvl).max_carry for lvl in LEVELS]
            with self.subTest(track=track):
                self.assertEqual(caps, sorted(caps, reverse=True))
                self.assertEqual(caps[-1], 1)

    def test_zero_counts_dont_consume_a_track_slot(self):
        """Clearing a track's last gag has to free the slot, or the picker
        would lock you out of a track you no longer carry."""
        counts = {(t, 1): 0 for t in Track}
        counts[(Track.THROW, 1)] = 5
        self.assertEqual(gags.validate_loadout(counts), [])

    def test_both_rules_report_together(self):
        problems = gags.validate_loadout({(t, 1): 20 for t in Track})
        self.assertEqual(len(problems), 2)


class TestToonUpMiss(unittest.TestCase):
    def test_toon_up_miss_still_heals(self):
        self.assertEqual(gags.TOON_UP_MISS_FRACTION, 0.20)
        full = g(Track.TOON_UP, 1).heal_at()
        self.assertEqual(math.ceil(full * gags.TOON_UP_MISS_FRACTION), 2)


if __name__ == "__main__":
    unittest.main()
