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

FIXTURE = Path(__file__).with_name("fixtures") / "battle_1280x720.png"


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
            level, score = vision.read_level(self.frame, plate)
            self.assertGreaterEqual(score, MIN_LEVEL_SCORE)
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

    @unittest.expectedFailure
    def test_the_pouch_checksum_matches_the_menus_own_label(self):
        """KNOWN FAILURE: one cell misreads, and this is how we know.

        The menu prints "Total gags 67 / 70" and level 7s are carried
        outside the pouch, so `pouch_total()` must equal 67. It returns
        66: the Trap level-5 cell holds 6 and reads as 5.

        Marked expected-failure rather than deleted or loosened, because
        the number it is comparing against is not yet read off the
        screen either -- wiring that up is what turns this from a
        hand-checked observation into the checksum CLAUDE.md describes.
        A digit reader that confuses 5 and 6 will quietly hand the
        solver a pouch it does not have.
        """
        panel = gagpanel.read_panel(self.frame)
        self.assertEqual(panel.pouch_total(), 67)


if __name__ == "__main__":
    unittest.main()
