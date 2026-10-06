"""Voting on the gag menu across the frames of one opening."""
import unittest

from solver.state import Track


def _panel(cells, label=None):
    from solver.live.gagpanel import GagPanel, PanelCell

    return GagPanel(cells=[PanelCell(Track[t], lvl, n, unlocked=True, uncertain=u)
                           for t, lvl, n, u in cells],
                    panel=(0, 0, 0, 0), label=label)


def _count(panel, track, level):
    return next(c for c in panel.cells
                if c.track is Track[track] and c.level == level)


class PanelMemoryTest(unittest.TestCase):

    def setUp(self):
        from solver.live.panel_memory import PanelMemory

        self.mem = PanelMemory()

    def test_a_doubtful_cell_takes_the_clean_sighting(self):
        """The cursor on a digit: doubtful now, read cleanly a poll ago."""
        self.mem.observe(_panel([("DROP", 5, 7, False)]))
        cell = _count(self.mem.resolve(_panel([("DROP", 5, 1, True)])), "DROP", 5)
        self.assertEqual((7, False), (cell.count, cell.uncertain))

    def test_a_confident_misread_is_outvoted_by_two(self):
        for _ in range(2):
            self.mem.observe(_panel([("THROW", 4, 5, False)]))
        cell = _count(self.mem.resolve(_panel([("THROW", 4, 1, False)])), "THROW", 4)
        self.assertEqual(5, cell.count)

    def test_one_sighting_cannot_overrule_a_confident_read(self):
        self.mem.observe(_panel([("THROW", 4, 5, False)]))
        cell = _count(self.mem.resolve(_panel([("THROW", 4, 4, False)])), "THROW", 4)
        self.assertEqual(4, cell.count)

    def test_a_split_vote_settles_nothing(self):
        self.mem.observe(_panel([("SQUIRT", 4, 4, False)]))
        self.mem.observe(_panel([("SQUIRT", 4, 2, False)]))
        cell = _count(self.mem.resolve(_panel([("SQUIRT", 4, 2, True)])), "SQUIRT", 4)
        self.assertTrue(cell.uncertain)

    def test_doubtful_reads_are_never_votes(self):
        self.mem.observe(_panel([("DROP", 5, 1, True)]))
        cell = _count(self.mem.resolve(_panel([("DROP", 5, 9, True)])), "DROP", 5)
        self.assertEqual((9, True), (cell.count, cell.uncertain))

    def test_closing_the_menu_forgets(self):
        """Gags are spent while the menu is shut."""
        self.mem.observe(_panel([("DROP", 5, 7, False)]))
        self.mem.reset()
        cell = _count(self.mem.resolve(_panel([("DROP", 5, 6, True)])), "DROP", 5)
        self.assertEqual((6, True), (cell.count, cell.uncertain))

    def test_the_label_check_still_runs_on_the_result(self):
        self.mem.observe(_panel([("DROP", 5, 7, False)]))
        out = self.mem.resolve(_panel([("DROP", 5, 1, True)], label=(9, 40)))
        self.assertIn("do not add up", out.checksum_problem())
