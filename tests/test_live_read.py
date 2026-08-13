"""Reading a real battle frame, end to end.

The repo had no battle frame in it, and that absence is why a whole
class of bug survived: every reader was tested against synthetic frames
with plates painted onto flat backgrounds, which is a picture of a
battle with none of the things that make a real one hard.

What it cost. Played windowed, `Capture` grabbed the entire desktop, and
the teal mask cannot tell a cog's portrait slot from a blue-green
wallpaper. On a 2560x1440 desktop the wallpaper produced a 319x190 blob
that outscored both real plates -- 65x45 and 68x47 -- so the watcher
reported one cog, at a fixed position, in the overworld as readily as in
a fight, and every read came back `level unreadable / unidentified`.
Nothing in the suite could have caught it.

This fixture is the same frame cropped to the game window, at 720p. The
capture side is covered in `test_window.py`; this is the reader side,
and its job is to fail if a change to the vision code stops it reading a
picture of an actual battle.

The ground truth is legible in the image: a level 6 Bossbot at full
health and a level 8 Lawbot just below it, and a gag menu whose own
label reads "Total gags 67 / 70".
"""
import unittest
from pathlib import Path

try:
    import numpy as np
    from PIL import Image

    from solver.live import gagpanel, vision
except ImportError as exc:                   # numpy/pillow are extras
    raise unittest.SkipTest(f"live reading needs numpy+pillow: {exc}") from None

FIXTURE = Path(__file__).with_name("fixtures") / "battle_1921x1081.png"


@unittest.skipUnless(FIXTURE.is_file(), f"missing {FIXTURE.name}")
class RealBattleFrameTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.frame = np.asarray(Image.open(FIXTURE).convert("RGB"))

    def test_both_plates_are_found(self):
        plates = vision.find_plates(self.frame)
        self.assertEqual(len(plates), 2)

    def test_the_plates_are_plate_shaped(self):
        """The wallpaper blob that displaced them was 319x190, aspect
        1.68. Real slots are near the documented 66x45."""
        for plate in vision.find_plates(self.frame):
            x0, y0, x1, y1 = plate.slot
            self.assertTrue(1.15 <= (x1 - x0) / (y1 - y0) <= 1.85)

    def test_the_levels_read(self):
        from solver.live.watch import MIN_LEVEL_SCORE

        levels = []
        for plate in vision.find_plates(self.frame):
            level, score, margin = vision.read_level(self.frame, plate)
            self.assertGreaterEqual(score, MIN_LEVEL_SCORE)
            self.assertGreaterEqual(margin, vision.MIN_LEVEL_MARGIN)
            levels.append(level)
        self.assertEqual(levels, [6, 8])

    def test_the_departments_read(self):
        depts = []
        for plate in vision.find_plates(self.frame):
            dept, margin = vision.read_department(self.frame, plate)
            self.assertGreaterEqual(margin, vision.MIN_DEPARTMENT_MARGIN)
            depts.append(dept)
        self.assertEqual(depts, ["bossbot", "lawbot"])

    def test_both_cogs_read_as_nearly_untouched(self):
        for plate in vision.find_plates(self.frame):
            self.assertGreater(vision.health_fraction(self.frame, plate), 0.9)

    def test_the_gag_menu_is_found(self):
        self.assertIsNotNone(gagpanel.find_panel(self.frame))

    def test_every_unlocked_track_reads_some_gags(self):
        from solver.state import Track

        panel = gagpanel.read_panel(self.frame)
        self.assertIsNotNone(panel)
        carried = {track for (track, _level), n in panel.counts().items() if n}
        # Toon-Up is locked on this toon; the other six are trained.
        self.assertEqual(
            carried,
            {Track.TRAP, Track.LURE, Track.SOUND, Track.THROW,
             Track.SQUIRT, Track.DROP})

    def test_the_menus_own_total_reads(self):
        """Read by a different route from the cells, on purpose: white
        digits on blue against near-black on yellow. Two readings that
        share no machinery disagree when one is wrong."""
        self.assertEqual(gagpanel.read_pouch_label(self.frame), (67, 70))

    def test_an_implausible_label_is_declined_not_returned(self):
        """A checksum that can be wrong is worse than no checksum.

        Resampled to 1600x900 the leading digit of "67" reads as an 8,
        confidently enough (0.61) to clear the digit threshold. The
        structure still parses, so what rejects it is the arithmetic:
        a pouch cannot hold 87 of a maximum 70. The reader returns None
        and the checksum simply does not run, rather than reporting a
        mismatch against a total that was itself misread.
        """
        from PIL import Image as PILImage

        small = np.asarray(PILImage.fromarray(self.frame)
                           .resize((1600, 900), PILImage.LANCZOS))
        self.assertIsNone(gagpanel.read_pouch_label(small))

    def test_an_unread_label_does_not_raise_a_false_alarm(self):
        panel = gagpanel.GagPanel(cells=[], panel=(0, 0, 1, 1), label=None)
        self.assertIsNone(panel.checksum_problem())

    def test_the_label_repairs_the_misread_cell(self):
        """The inversion this test was written expecting.

        It used to assert the mismatch: the cells totalled 66 against a
        label of 67, because the Trap level-5 cell holds 6 and read as
        5. The digit reader still cannot read it -- 5 scored 0.594 and 8
        second at 0.583, with the true digit not placing at all -- so no
        threshold recovers it.

        What recovers it is the label. Exactly one cell is uncertain, so
        its value is forced: 67 minus the confident rest. Detection
        became correction without anything having to be guessed.
        """
        panel = gagpanel.read_panel(self.frame)
        self.assertEqual(panel.label, (67, 70))
        self.assertEqual(panel.pouch_total(), 67)
        self.assertIsNone(panel.checksum_problem())
        trap5 = next(c for c in panel.cells
                     if c.track.value == "trap" and c.level == 5)
        self.assertEqual(trap5.count, 6)
        self.assertFalse(trap5.uncertain)

    def test_only_one_cell_was_ever_in_doubt(self):
        """The repair is only sound because the ambiguity is isolated.
        Across all 41 digits on this panel the median margin is 0.128
        and the worst correct read is 0.063; one sits at 0.011."""
        panel = gagpanel.read_panel(self.frame)
        self.assertEqual([c for c in panel.cells if c.uncertain], [])


class RepairDeclinesTest(unittest.TestCase):
    """When the answer is not forced, it must not be invented.

    The repair is only legitimate because the value is determined:
    exactly one cell in doubt, everything else confident, and a label
    that pins the total. Every case where that fails has to fall
    through to the checksum refusing the state -- which is the
    behaviour the repair replaces, not weakens.
    """

    def cell(self, level, count, uncertain=False):
        from solver.state import Track

        return gagpanel.PanelCell(Track.THROW, level, count,
                                  unlocked=True, uncertain=uncertain)

    def test_one_doubtful_cell_is_solved(self):
        cells = [self.cell(1, 5), self.cell(2, 9, uncertain=True)]
        fixed = gagpanel._repair_with_label(cells, (11, 70))
        self.assertEqual([c.count for c in fixed], [5, 6])
        self.assertFalse(any(c.uncertain for c in fixed))

    def test_two_doubtful_cells_are_left_alone(self):
        """The label constrains their sum and not the split."""
        cells = [self.cell(1, 5, uncertain=True),
                 self.cell(2, 9, uncertain=True)]
        self.assertEqual(gagpanel._repair_with_label(cells, (11, 70)), cells)

    def test_no_doubtful_cell_is_left_alone(self):
        """A disagreement with everything confident is a different
        failure, and guessing which cell to move would be a guess."""
        cells = [self.cell(1, 5), self.cell(2, 9)]
        self.assertEqual(gagpanel._repair_with_label(cells, (11, 70)), cells)

    def test_a_negative_remainder_is_refused(self):
        cells = [self.cell(1, 40), self.cell(2, 9, uncertain=True)]
        self.assertEqual(gagpanel._repair_with_label(cells, (11, 70)), cells)

    def test_a_remainder_past_the_carry_limit_is_refused(self):
        """No pouch holds ninety Cupcakes; something else is wrong."""
        cells = [self.cell(1, 0), self.cell(2, 1, uncertain=True)]
        self.assertEqual(gagpanel._repair_with_label(cells, (90, 90)), cells)

    def test_an_unread_label_repairs_nothing(self):
        cells = [self.cell(1, 5), self.cell(2, 9, uncertain=True)]
        self.assertEqual(gagpanel._repair_with_label(cells, None), cells)

    def test_a_level_seven_cell_cannot_be_solved_this_way(self):
        """Level 7s are outside the pouch and absent from the label."""
        cells = [self.cell(1, 5), self.cell(7, 9, uncertain=True)]
        self.assertEqual(gagpanel._repair_with_label(cells, (5, 70)), cells)


if __name__ == "__main__":
    unittest.main()
