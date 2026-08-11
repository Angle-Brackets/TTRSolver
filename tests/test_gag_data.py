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
EXPECTED_MISSING = {
    ("organic_damage", Track.TRAP, 5),   # Trapdoor organic
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

    def test_every_gag_is_named_and_has_an_accuracy(self):
        for gag in gags.GAGS:
            with self.subTest(gag=str(gag)):
                self.assertTrue(gag.name.strip())
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
    def test_missing_values_are_exactly_the_two_known_conflicts(self):
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
        with self.assertRaises(NotImplementedError):
            g(Track.TRAP, 5).damage_at(organic=True)


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
        self.assertEqual(g(Track.SOUND, 1).name, "Bike Horn")
        self.assertEqual(g(Track.SOUND, 1).damage, (3, 4))
        self.assertEqual(g(Track.SOUND, 6).name, "Foghorn")
        self.assertEqual(g(Track.SOUND, 6).damage, (25, 50))

    def test_ttr_renamed_and_rebalanced_level_7_trap_and_drop(self):
        self.assertEqual(g(Track.TRAP, 7).name, "Railroad")
        self.assertEqual(g(Track.TRAP, 7).damage, (200, 200))
        self.assertEqual(g(Track.DROP, 7).name, "Toontanic")
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


class TestToonUpMiss(unittest.TestCase):
    def test_toon_up_miss_still_heals(self):
        self.assertEqual(gags.TOON_UP_MISS_FRACTION, 0.20)
        full = g(Track.TOON_UP, 1).heal_at()
        self.assertEqual(math.ceil(full * gags.TOON_UP_MISS_FRACTION), 2)


if __name__ == "__main__":
    unittest.main()
