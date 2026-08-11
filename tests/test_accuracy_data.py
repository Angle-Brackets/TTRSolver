"""
Regression pins for solver/data/accuracy.py, the accuracy-formula tables.

Every value asserted here was read off the Toontown Rewritten wiki during
the accuracy audit:

  * https://toontownrewritten.wiki/Accuracy      -- the formula, the propAcc
    tables for all seven tracks, trackExp, tgtDef, PrevHits, luredRatio,
    the 95% cap and the 5% floor.
  * the per-track pages (Toon-Up, Trap, Sound, Throw, Squirt, Drop) -- each
    gag table's "Base accuracy" column, an independent restatement of the
    same propAcc numbers.
  * https://toontownrewritten.wiki/Organic_gags  -- which tracks gain
    accuracy (rather than damage or healing) from being organic.

The point of this file is that a future edit which quietly reintroduces a
strategy-guide value has to fail a test. Where the wiki gives no number
(cog levels 13-19, the post-4.3.3 soft-cap ceiling) the tests pin the
*absence* instead.
"""
import unittest

from solver.data import accuracy as acc
from solver.state import Track


ALL_TRACKS = (Track.TOON_UP, Track.TRAP, Track.LURE, Track.SOUND,
              Track.THROW, Track.SQUIRT, Track.DROP)


class TestPropAccShape(unittest.TestCase):
    def test_every_track_has_seven_levels(self):
        self.assertEqual(set(acc.AV_PROP_ACCURACY), set(ALL_TRACKS))
        for track in ALL_TRACKS:
            with self.subTest(track=track):
                self.assertEqual(len(acc.AV_PROP_ACCURACY[track]), 7)

    def test_no_missing_cells(self):
        for track, row in acc.AV_PROP_ACCURACY.items():
            with self.subTest(track=track):
                self.assertNotIn(None, row)

    def test_values_are_percentages(self):
        for track, row in acc.AV_PROP_ACCURACY.items():
            for level, value in enumerate(row, start=1):
                with self.subTest(track=track, level=level):
                    self.assertIsInstance(value, int)
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 100)


class TestPropAccValues(unittest.TestCase):
    """Exact rows, per the wiki's Accuracy#propAcc tables."""

    def test_toon_up(self):
        # Feather/Megaphone/Lipstick/Bamboo Cane/Pixie Dust/Juggling Cubes
        # at 70%, High Dive at 95%.
        self.assertEqual(acc.AV_PROP_ACCURACY[Track.TOON_UP],
                         [70, 70, 70, 70, 70, 70, 95])

    def test_toon_up_level_7_is_95_not_100(self):
        """The one propAcc cell this audit corrected. The strategy guide
        said 100; the wiki says 95, twice (the propAcc table, and the
        Toon-Up page: "High Dive has a 95% base accuracy ... the only
        Toon-Up gag to have high accuracy")."""
        self.assertEqual(acc.AV_PROP_ACCURACY[Track.TOON_UP][6], 95)

    def test_trap_row_is_zero(self):
        """Every Trap gag is listed at 0% base accuracy. Trap hitting is a
        separate special rule ("atkAcc is automatically set to 100%"), not
        a propAcc value -- so this row must stay zeroed, or a caller that
        misses the short-circuit would silently get free 100s."""
        self.assertEqual(acc.AV_PROP_ACCURACY[Track.TRAP], [0] * 7)

    def test_flat_rows(self):
        for track, value in ((Track.SOUND, 95), (Track.THROW, 75),
                             (Track.SQUIRT, 95), (Track.DROP, 50)):
            with self.subTest(track=track):
                self.assertEqual(acc.AV_PROP_ACCURACY[track], [value] * 7)

    def test_only_toon_up_and_lure_vary_by_level(self):
        """Accuracy#propAcc: "For all gag tracks besides Toon-Up and Lure,
        every gag in the same track have the same propAcc value."."""
        varying = {t for t in ALL_TRACKS
                   if len(set(acc.AV_PROP_ACCURACY[t])) > 1}
        self.assertEqual(varying, {Track.TOON_UP, Track.LURE})

    def test_lure_row_matches_the_gag_objects(self):
        """The propAcc rows are derived from the Gag objects, not restated
        here -- a second copy keyed by track/level is how Lure drifted out
        of sync in the first place."""
        from solver.data.gags import gag
        LURE_BASE_ACCURACY = {lvl: gag(Track.LURE, lvl).accuracy
                              for lvl in range(1, 8)}
        self.assertEqual(acc.AV_PROP_ACCURACY[Track.LURE],
                         [LURE_BASE_ACCURACY[lvl] for lvl in range(1, 8)])
        self.assertEqual(acc.AV_PROP_ACCURACY[Track.LURE],
                         [60, 55, 70, 65, 80, 75, 90])


class TestOrganicAccuracy(unittest.TestCase):
    """Organic gags: only Lure trades organic-ness for accuracy."""

    def test_every_track_has_an_entry(self):
        self.assertEqual(set(acc.AV_ORGANIC_PROP_ACCURACY), set(ALL_TRACKS))

    def test_only_lure_has_an_organic_accuracy_row(self):
        """Organic gags: "Damage-dealing gags (Trap, Sound, Throw, Squirt,
        and Drop) gain an increase in damage when organic, while Toon-Up
        gags gain additional healing power. Lure gags gain an increase in
        base accuracy when organic."

        The None rows are a finding, not a gap -- if someone later fills
        one in with an invented number this test fails."""
        with_rows = {t for t, row in acc.AV_ORGANIC_PROP_ACCURACY.items()
                     if any(v is not None for v in row)}
        self.assertEqual(with_rows, {Track.LURE})
        self.assertEqual(acc.ORGANIC_ACCURACY_TRACKS, frozenset({Track.LURE}))
        self.assertEqual(with_rows, set(acc.ORGANIC_ACCURACY_TRACKS))

    def test_organic_lure_row(self):
        self.assertEqual(acc.AV_ORGANIC_PROP_ACCURACY[Track.LURE],
                         [70, 65, 80, 75, 90, 85, 100])

    def test_legacy_alias_still_points_at_the_lure_row(self):
        """mechanics.calc_prop_acc reads AV_LURE_BONUS_ACCURACY."""
        self.assertEqual(acc.AV_LURE_BONUS_ACCURACY,
                         acc.AV_ORGANIC_PROP_ACCURACY[Track.LURE])
        self.assertEqual(len(acc.AV_LURE_BONUS_ACCURACY), 7)

    def test_organic_lure_beats_plain_lure_at_every_level(self):
        for level in range(7):
            with self.subTest(level=level + 1):
                self.assertGreater(acc.AV_LURE_BONUS_ACCURACY[level],
                                   acc.AV_PROP_ACCURACY[Track.LURE][level])


class TestTrackExp(unittest.TestCase):
    def test_table(self):
        self.assertEqual(acc.TRACK_EXP_BY_LEVEL,
                         {1: 0, 2: 10, 3: 20, 4: 30, 5: 40, 6: 50, 7: 60})

    def test_agrees_with_the_arithmetic_mechanics_uses(self):
        for level, value in acc.TRACK_EXP_BY_LEVEL.items():
            with self.subTest(level=level):
                self.assertEqual(value, (level - 1) * 10)


class TestTgtDef(unittest.TestCase):
    def test_confirmed_levels_present(self):
        self.assertEqual(set(acc.TGT_DEF_RANK_1),
                         set(range(1, 13)) | {20})

    def test_levels_13_to_19_are_absent(self):
        """The wiki prints "Unknown" for these. Absence makes a lookup
        raise, which is the intended behaviour -- do not interpolate
        between level 12 (-55) and level 20 (-65)."""
        for level in range(13, 20):
            with self.subTest(level=level):
                self.assertNotIn(level, acc.TGT_DEF_RANK_1)
                self.assertNotIn(level, acc.TGT_DEF_RANK_2_PLUS)
                with self.assertRaises(KeyError):
                    acc.tgt_def(level)

    def test_rank_1_values(self):
        self.assertEqual(
            acc.TGT_DEF_RANK_1,
            {1: -2, 2: -5, 3: -10, 4: -12, 5: -15, 6: -25, 7: -30,
             8: -35, 9: -40, 10: -45, 11: -50, 12: -55, 20: -65})

    def test_rank_2_plus_differs_only_at_levels_4_and_5(self):
        """Accuracy#tgtDef prints "-12*/-15" and "-15*/-20" with the
        footnote "Rank 1 Cogs used the tgtDef value with the asterisk"."""
        differing = {lvl for lvl in acc.TGT_DEF_RANK_1
                     if acc.TGT_DEF_RANK_1[lvl] != acc.TGT_DEF_RANK_2_PLUS[lvl]}
        self.assertEqual(differing, {4, 5})
        self.assertEqual(acc.TGT_DEF_RANK_2_PLUS[4], -15)
        self.assertEqual(acc.TGT_DEF_RANK_2_PLUS[5], -20)

    def test_all_values_are_non_positive(self):
        """"tgtDef is a negative integer determined by the targeted Cog
        level"."""
        for table in (acc.TGT_DEF_RANK_1, acc.TGT_DEF_RANK_2_PLUS):
            for level, value in table.items():
                with self.subTest(level=level, value=value):
                    self.assertIsInstance(value, int)
                    self.assertLess(value, 0)

    def test_monotonically_harder_with_level(self):
        for table in (acc.TGT_DEF_RANK_1, acc.TGT_DEF_RANK_2_PLUS):
            levels = sorted(table)
            for lo, hi in zip(levels, levels[1:]):
                with self.subTest(lo=lo, hi=hi):
                    self.assertLessEqual(table[hi], table[lo])

    def test_default_table_is_the_rank_1_branch(self):
        """mechanics.calc_tgt_def indexes TGT_DEF_BY_LEVEL without knowing
        a cog's rank; it must keep resolving to the rank-1 branch, which is
        what it did before the audit."""
        self.assertIs(acc.TGT_DEF_BY_LEVEL, acc.TGT_DEF_RANK_1)
        self.assertEqual(acc.TGT_DEF_BY_LEVEL[4], -12)
        self.assertEqual(acc.TGT_DEF_BY_LEVEL[5], -15)

    def test_tgt_def_helper_dispatches_on_rank(self):
        self.assertEqual(acc.tgt_def(4, cog_rank=1), -12)
        self.assertEqual(acc.tgt_def(5, cog_rank=1), -15)
        for rank in range(2, 9):
            with self.subTest(rank=rank):
                self.assertEqual(acc.tgt_def(4, cog_rank=rank), -15)
                self.assertEqual(acc.tgt_def(5, cog_rank=rank), -20)

    def test_tgt_def_helper_ignores_rank_off_the_asterisked_levels(self):
        for level in (1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 20):
            with self.subTest(level=level):
                self.assertEqual(acc.tgt_def(level, 1), acc.tgt_def(level, 5))

    def test_helper_defaults_to_rank_1(self):
        for level in acc.TGT_DEF_RANK_1:
            with self.subTest(level=level):
                self.assertEqual(acc.tgt_def(level), acc.TGT_DEF_RANK_1[level])


class TestCapAndFloor(unittest.TestCase):
    def test_cap_value(self):
        self.assertEqual(acc.ACCURACY_CAP, 95)

    def test_cap_is_flagged_soft(self):
        """4.3.3 made the 95% hard cap a soft cap. The value is still 95;
        what changed is that bonuses may exceed it. The wiki never says by
        how much, so nothing beyond this flag is recorded."""
        self.assertTrue(acc.ACCURACY_CAP_IS_SOFT)

    def test_floor(self):
        self.assertEqual(acc.ACCURACY_FLOOR, 5)
        self.assertEqual(acc.ACCURACY_FLOOR_EXEMPT_TRACKS,
                         frozenset({Track.DROP}))

    def test_floor_is_below_every_prop_acc_except_trap(self):
        """Sanity: the 5% floor can only ever bite via tgtDef, never
        because a gag's own base accuracy is under it."""
        for track in ALL_TRACKS:
            if track is Track.TRAP:
                continue
            with self.subTest(track=track):
                self.assertGreater(min(acc.AV_PROP_ACCURACY[track]),
                                   acc.ACCURACY_FLOOR)


class TestPrevHits(unittest.TestCase):
    def test_per_hit_and_max(self):
        """Accuracy#PrevHits: "incremented by the number of previous hits
        x 25 (excluding Trap) ... with a bonus of +75 being possible with
        three prior hits" (4.0.0 patch notes). The guide's 20/60 are the
        pre-rebalance Toontown Online numbers."""
        self.assertEqual(acc.PREV_HITS_BONUS_PER_HIT, 25)
        self.assertEqual(acc.PREV_HITS_MAX_BONUS, 75)
        self.assertEqual(acc.PREV_HITS_MAX_PRIOR_HITS, 3)

    def test_max_is_consistent_with_per_hit(self):
        self.assertEqual(
            acc.PREV_HITS_BONUS_PER_HIT * acc.PREV_HITS_MAX_PRIOR_HITS,
            acc.PREV_HITS_MAX_BONUS)

    def test_not_the_strategy_guide_numbers(self):
        self.assertNotEqual(acc.PREV_HITS_BONUS_PER_HIT, 20)
        self.assertNotEqual(acc.PREV_HITS_MAX_BONUS, 60)

    def test_trap_specific_prev_hits(self):
        """Trap's PrevHits rules, per Accuracy#PrevHits and the Trap page:
        +10 to Lure for the first Trap, +5 per extra Trap for a group Lure,
        +50 when Lure activates a Trap (4.0.5 raised this from 30)."""
        self.assertEqual(acc.TRAP_LURE_ACCURACY_BONUS, 10)
        self.assertEqual(acc.TRAP_EXTRA_LURE_ACCURACY_BONUS, 5)
        self.assertEqual(acc.TRAP_ACTIVATION_PREV_HITS, 50)


class TestFormulaWiring(unittest.TestCase):
    """The tables are only useful if mechanics.py reads the audited ones."""

    def test_mechanics_reads_the_corrected_toon_up_row(self):
        from solver import mechanics
        self.assertEqual(mechanics.calc_prop_acc(Track.TOON_UP, 7), 95)
        self.assertEqual(mechanics.calc_prop_acc(Track.TOON_UP, 1), 70)

    def test_mechanics_organic_lure_still_resolves(self):
        from solver import mechanics
        self.assertEqual(
            mechanics.calc_prop_acc(Track.LURE, 7, lure_tree_planted=True),
            100)
        self.assertEqual(
            mechanics.calc_prop_acc(Track.LURE, 7, lure_tree_planted=False),
            90)

    def test_data_package_reexports_are_the_same_objects(self):
        from solver import data
        self.assertIs(data.AV_PROP_ACCURACY, acc.AV_PROP_ACCURACY)
        self.assertIs(data.TGT_DEF_BY_LEVEL, acc.TGT_DEF_BY_LEVEL)
        self.assertEqual(data.PREV_HITS_BONUS_PER_HIT,
                         acc.PREV_HITS_BONUS_PER_HIT)


if __name__ == "__main__":
    unittest.main()
