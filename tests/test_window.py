"""Grabbing the game rather than the screen.

`solver/live/window.py` exists because the plate reader was built on the
premise that it never needed one -- the teal portrait slot being
distinctive enough to find anywhere in a frame. It is, inside the game.
Across a whole desktop it is not, and played windowed that is what the
capture handed it.

These cover the parts that do not need a running game. The reader side
is `test_live_read.py`.
"""
import sys
import unittest

try:
    import numpy as np

    from solver.live import window
    from solver.live.watch import Capture
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"window capture needs numpy: {exc}") from None


class GameRectTest(unittest.TestCase):

    def test_a_missing_window_is_none_not_an_error(self):
        """The game not running is ordinary, not exceptional: the
        watcher polls whether or not anyone is playing."""
        self.assertIsNone(window.game_rect(title="no such window ~!@#"))

    def test_describe_always_says_something(self):
        text = window.describe()
        self.assertIsInstance(text, str)
        self.assertTrue(text)

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows only")
    def test_a_real_rect_is_ordered_and_non_empty(self):
        rect = window.game_rect()
        if rect is None:
            self.skipTest("the game is not running")
        left, top, right, bottom = rect
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)

    @unittest.skipIf(sys.platform.startswith("win"), "non-Windows only")
    def test_other_platforms_fall_back_rather_than_fail(self):
        self.assertIsNone(window.game_rect())


class CaptureRegionTest(unittest.TestCase):
    """`Capture.region` decides what gets grabbed."""

    def test_following_can_be_turned_off(self):
        cap = Capture.__new__(Capture)
        cap.follow_window = False
        self.assertIsNone(cap.region())

    def test_the_rect_is_looked_up_per_grab(self):
        """Not cached. The window can be moved, resized or alt-tabbed
        between frames, and a stale rectangle reads the wrong part of
        the screen without saying so."""
        cap = Capture.__new__(Capture)
        cap.follow_window = True
        seen = []

        import solver.live.window as win_mod

        real = win_mod.game_rect
        win_mod.game_rect = lambda *a, **k: seen.append(1) or (0, 0, 8, 6)
        try:
            cap.region()
            cap.region()
        finally:
            win_mod.game_rect = real
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
