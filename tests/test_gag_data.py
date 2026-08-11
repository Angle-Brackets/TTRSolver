"""Pins solver/data/gags.py against the TTR wiki audit.

These tests lock the *shape* of the gag tables, the exact inventory of
cells still left None, and the invariants the wiki data actually bears
out. If a future edit fills a gap, adds one, or breaks a progression,
one of these fails and names the cell.

Nothing here recomputes a value from a formula -- every number that
matters was transcribed from the wiki and is asserted literally, so a
typo in the table cannot be masked by a matching typo in a test helper.
"""
import unittest

from solver.data import gags
from solver.state import Track


LEVELS = (1, 2, 3, 4, 5, 6, 7)

DAMAGE_TRACKS = (Track.THROW, Track.SQUIRT, Track.SOUND,
                 Track.DROP, Track.TRAP)
ALL_GAG_TRACKS = DAMAGE_TRACKS + (Track.TOON_UP,)

# The complete inventory of cells the audit could NOT confirm. Both are
# genuine source conflicts, documented in data/gags.py. Nothing else in
# the module is allowed to be None.
EXPECTED_MISSING = {
    ("GAG_ORGANIC_DAMAGE_MINMAX", Track.TRAP, 5),   # Trapdoor organic
    ("GAG_HEAL_MINMAX", Track.TOON_UP, 3),          # Lipstick min heal
}


def _pairs(table):
    """(level, entry) for a level->tuple-or-None mapping."""
    return [(lvl, table.get(lvl)) for lvl in LEVELS]


class TestTableShape(unittest.TestCase):
    """Every table covers exactly levels 1-7 and holds (min, max) ints."""

    def test_damage_tracks_cover_all_seven_levels(self):
        for track in DAMAGE_TRACKS:
            with self.subTest(track=track):
                self.assertEqual(set(gags.GAG_DAMAGE_MINMAX[track]),
                                 set(LEVELS))
                self.assertEqual(set(gags.GAG_ORGANIC_DAMAGE_MINMAX[track]),
                                 set(LEVELS))

    def test_toon_up_is_absent_from_the_damage_tables(self):
        """Toon-Up heals; it must not masquerade as a damage row."""
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.TOON_UP], {})
        self.assertEqual(gags.GAG_ORGANIC_DAMAGE_MINMAX[Track.TOON_UP], {})

    def test_heal_tables_cover_all_seven_levels(self):
        self.assertEqual(set(gags.GAG_HEAL_MINMAX), set(LEVELS))
        self.assertEqual(set(gags.GAG_ORGANIC_HEAL_MINMAX), set(LEVELS))

    def test_names_cover_every_track_and_level(self):
        self.assertEqual(set(gags.GAG_NAMES), set(ALL_GAG_TRACKS))
        for track, names in gags.GAG_NAMES.items():
            with self.subTest(track=track):
                self.assertEqual(set(names), set(LEVELS))
                for lvl, name in names.items():
                    self.assertTrue(name and isinstance(name, str),
                                    f"{track} L{lvl} has no name")

    def test_group_levels_cover_every_track(self):
        self.assertEqual(set(gags.GAG_GROUP_LEVELS), set(ALL_GAG_TRACKS))
        for track, levels in gags.GAG_GROUP_LEVELS.items():
            with self.subTest(track=track):
                self.assertIsInstance(levels, frozenset)
                self.assertTrue(levels <= set(LEVELS))

    def test_every_present_entry_is_a_pair_of_positive_ints(self):
        tables = [
            ("damage", gags.GAG_DAMAGE_MINMAX),
            ("organic damage", gags.GAG_ORGANIC_DAMAGE_MINMAX),
            ("heal", {Track.TOON_UP: gags.GAG_HEAL_MINMAX}),
            ("organic heal", {Track.TOON_UP: gags.GAG_ORGANIC_HEAL_MINMAX}),
        ]
        for label, byTrack in tables:
            for track, table in byTrack.items():
                for lvl, entry in table.items():
                    if entry is None:
                        continue
                    with self.subTest(table=label, track=track, level=lvl):
                        self.assertIsInstance(entry, tuple)
                        self.assertEqual(len(entry), 2)
                        lo, hi = entry
                        self.assertIsInstance(lo, int)
                        self.assertIsInstance(hi, int)
                        self.assertGreater(lo, 0)
                        self.assertLessEqual(lo, hi, "min exceeds max")

    def test_no_half_populated_tuples(self):
        """A cell is either fully known or fully None. calc_toon_damage
        interpolates between min and max, so a (None, 40) would produce a
        TypeError deep in mechanics instead of the intended
        NotImplementedError at the table lookup."""
        for byTrack in (gags.GAG_DAMAGE_MINMAX,
                        gags.GAG_ORGANIC_DAMAGE_MINMAX):
            for track, table in byTrack.items():
                for lvl, entry in table.items():
                    if entry is not None:
                        with self.subTest(track=track, level=lvl):
                            self.assertNotIn(None, entry)
        for table in (gags.GAG_HEAL_MINMAX, gags.GAG_ORGANIC_HEAL_MINMAX):
            for lvl, entry in table.items():
                if entry is not None:
                    with self.subTest(level=lvl):
                        self.assertNotIn(None, entry)


class TestMissingCellInventory(unittest.TestCase):
    """The exact set of unconfirmed cells, so a new gap can't appear --
    or be quietly filled with a guess -- without this failing."""

    def _actual_missing(self):
        found = set()
        for track, table in gags.GAG_ORGANIC_DAMAGE_MINMAX.items():
            for lvl, entry in table.items():
                if entry is None:
                    found.add(("GAG_ORGANIC_DAMAGE_MINMAX", track, lvl))
        for track, table in gags.GAG_DAMAGE_MINMAX.items():
            for lvl, entry in table.items():
                if entry is None:
                    found.add(("GAG_DAMAGE_MINMAX", track, lvl))
        for lvl, entry in gags.GAG_HEAL_MINMAX.items():
            if entry is None:
                found.add(("GAG_HEAL_MINMAX", Track.TOON_UP, lvl))
        for lvl, entry in gags.GAG_ORGANIC_HEAL_MINMAX.items():
            if entry is None:
                found.add(("GAG_ORGANIC_HEAL_MINMAX", Track.TOON_UP, lvl))
        return found

    def test_missing_cells_are_exactly_the_two_known_conflicts(self):
        self.assertEqual(self._actual_missing(), EXPECTED_MISSING)

    def test_all_damage_is_now_populated(self):
        """The audit closed every damage gap, Trap included. This is the
        headline result -- if it regresses, the trap+lure combo breaks."""
        for track in DAMAGE_TRACKS:
            for lvl in LEVELS:
                with self.subTest(track=track, level=lvl):
                    self.assertIsNotNone(gags.GAG_DAMAGE_MINMAX[track][lvl])


class TestWikiValues(unittest.TestCase):
    """Literal transcriptions. These are the audit's actual product."""

    def test_throw_damage(self):
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.THROW], {
            1: (4, 6), 2: (8, 10), 3: (14, 17), 4: (24, 27),
            5: (36, 40), 6: (48, 100), 7: (120, 120)})

    def test_squirt_damage(self):
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.SQUIRT], {
            1: (3, 4), 2: (6, 8), 3: (10, 12), 4: (18, 21),
            5: (27, 30), 6: (36, 80), 7: (105, 105)})

    def test_sound_damage(self):
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.SOUND], {
            1: (3, 4), 2: (5, 7), 3: (9, 11), 4: (14, 16),
            5: (19, 21), 6: (25, 50), 7: (90, 90)})

    def test_drop_damage(self):
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.DROP], {
            1: (10, 10), 2: (18, 18), 3: (30, 30), 4: (45, 45),
            5: (60, 70), 6: (85, 170), 7: (180, 180)})

    def test_trap_damage(self):
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.TRAP], {
            1: (10, 12), 2: (18, 20), 3: (30, 35), 4: (45, 50),
            5: (75, 85), 6: (90, 180), 7: (200, 200)})

    def test_toon_up_heals(self):
        self.assertEqual(gags.GAG_HEAL_MINMAX, {
            1: (8, 10), 2: (15, 18), 3: None, 4: (40, 45),
            5: (50, 60), 6: (75, 105), 7: (210, 210)})

    def test_sound_is_not_shifted_by_a_level(self):
        """The guide's table began at Whistle and had no Bike Horn, so
        every Sound level sat one row too low. Bike Horn is level 1."""
        self.assertEqual(gags.GAG_NAMES[Track.SOUND][1], "Bike Horn")
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.SOUND][1], (3, 4))
        self.assertEqual(gags.GAG_NAMES[Track.SOUND][6], "Foghorn")
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.SOUND][6], (25, 50))

    def test_ttr_renamed_and_rebalanced_level_7_trap_and_drop(self):
        self.assertEqual(gags.GAG_NAMES[Track.TRAP][7], "Railroad")
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.TRAP][7], (200, 200))
        self.assertEqual(gags.GAG_NAMES[Track.DROP][7], "Toontanic")
        self.assertEqual(gags.GAG_DAMAGE_MINMAX[Track.DROP][7], (180, 180))

    def test_level_6_gags_all_have_wide_ranges(self):
        """Throw L6 (48-100) and Sound "25-50" were both once rejected as
        implausible. Every level 6 gag in the game is like this."""
        for track in DAMAGE_TRACKS:
            lo, hi = gags.GAG_DAMAGE_MINMAX[track][6]
            with self.subTest(track=track):
                self.assertGreaterEqual(hi, lo * 1.5)
        lo, hi = gags.GAG_HEAL_MINMAX[6]
        self.assertGreater(hi, lo)


class TestInvariants(unittest.TestCase):

    def test_damage_is_non_decreasing_with_level(self):
        """True of both endpoints on all five damage tracks."""
        for track in DAMAGE_TRACKS:
            table = gags.GAG_DAMAGE_MINMAX[track]
            for lvl in LEVELS[:-1]:
                lo, hi = table[lvl]
                nlo, nhi = table[lvl + 1]
                with self.subTest(track=track, level=lvl):
                    self.assertLessEqual(lo, nlo, "min damage went down")
                    self.assertLessEqual(hi, nhi, "max damage went down")

    def test_heal_is_non_decreasing_with_level(self):
        known = [(lvl, e) for lvl, e in _pairs(gags.GAG_HEAL_MINMAX)
                 if e is not None]
        for (lvl, (lo, hi)), (_nl, (nlo, nhi)) in zip(known, known[1:]):
            with self.subTest(level=lvl):
                self.assertLessEqual(lo, nlo)
                self.assertLessEqual(hi, nhi)

    def test_organic_beats_base_everywhere(self):
        for track in DAMAGE_TRACKS:
            for lvl in LEVELS:
                organic = gags.GAG_ORGANIC_DAMAGE_MINMAX[track][lvl]
                if organic is None:
                    continue
                base = gags.GAG_DAMAGE_MINMAX[track][lvl]
                with self.subTest(track=track, level=lvl):
                    self.assertGreater(organic[0], base[0])
                    self.assertGreater(organic[1], base[1])
        for lvl in LEVELS:
            base = gags.GAG_HEAL_MINMAX[lvl]
            if base is None:
                continue
            organic = gags.GAG_ORGANIC_HEAL_MINMAX[lvl]
            with self.subTest(level=lvl):
                self.assertGreater(organic[0], base[0])
                self.assertGreater(organic[1], base[1])

    def test_level_7_gags_deal_a_single_fixed_value(self):
        for track in DAMAGE_TRACKS:
            lo, hi = gags.GAG_DAMAGE_MINMAX[track][7]
            with self.subTest(track=track):
                self.assertEqual(lo, hi)
        self.assertEqual(*gags.GAG_HEAL_MINMAX[7])

    def test_every_level_7_gag_is_a_group_gag(self):
        for track, levels in gags.GAG_GROUP_LEVELS.items():
            with self.subTest(track=track):
                self.assertIn(7, levels)

    def test_group_levels_match_the_wiki_affects_column(self):
        self.assertEqual(gags.GAG_GROUP_LEVELS[Track.SOUND],
                         frozenset(LEVELS))
        self.assertEqual(gags.GAG_GROUP_LEVELS[Track.TOON_UP],
                         frozenset({2, 4, 6, 7}))
        for track in (Track.THROW, Track.SQUIRT, Track.DROP, Track.TRAP):
            with self.subTest(track=track):
                self.assertEqual(gags.GAG_GROUP_LEVELS[track],
                                 frozenset({7}))


class TestOrganicMultiplier(unittest.TestCase):
    """The Organic gags page states a per-track ceil(kx) rule. It is
    recorded for reference, and it reproduces the transcribed tables --
    with the documented exceptions. Pinning the exceptions keeps anyone
    from "fixing" a transcribed value to match the formula."""

    EXCEPTIONS = {
        # (track, level, endpoint index) -> why
        (Track.SQUIRT, 4, 0): "wiki says 22, ceil(1.15*18) = 21",
    }

    def test_bonus_covers_every_damage_track_plus_toon_up(self):
        self.assertEqual(set(gags.ORGANIC_BONUS_PCT), set(ALL_GAG_TRACKS))

    def test_organic_value_uses_exact_integer_ceiling(self):
        """1.1 * 100 == 110.00000000000001, so a float multiplier plus
        math.ceil() turns organic Birthday Cake into 111. Guard the
        exact cases that trip on it."""
        self.assertEqual(gags.organic_value(Track.THROW, 100), 110)
        self.assertEqual(gags.organic_value(Track.SOUND, 90), 99)
        self.assertEqual(gags.organic_value(Track.TRAP, 200), 220)
        # and a genuine round-up
        self.assertEqual(gags.organic_value(Track.THROW, 75), 83)

    def test_formula_reproduces_the_damage_tables(self):
        mismatches = set()
        for track in DAMAGE_TRACKS:
            for lvl in LEVELS:
                organic = gags.GAG_ORGANIC_DAMAGE_MINMAX[track][lvl]
                if organic is None:
                    continue
                base = gags.GAG_DAMAGE_MINMAX[track][lvl]
                for i in (0, 1):
                    if gags.organic_value(track, base[i]) != organic[i]:
                        mismatches.add((track, lvl, i))
        self.assertEqual(mismatches, set(self.EXCEPTIONS))

    def test_formula_reproduces_the_heal_table(self):
        for lvl in LEVELS:
            base = gags.GAG_HEAL_MINMAX[lvl]
            if base is None:
                continue
            organic = gags.GAG_ORGANIC_HEAL_MINMAX[lvl]
            for i in (0, 1):
                with self.subTest(level=lvl, endpoint=i):
                    self.assertEqual(
                        gags.organic_value(Track.TOON_UP, base[i]),
                        organic[i])

    def test_toon_up_miss_still_heals(self):
        self.assertEqual(gags.TOON_UP_MISS_FRACTION, 0.20)


if __name__ == "__main__":
    unittest.main()
