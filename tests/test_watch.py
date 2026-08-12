"""Following a battle across frames.

The watcher is driven by a scripted capture rather than a real screen, so
these test the part that actually holds the risk -- deciding what
changed, and refusing to react to a single noisy frame -- without needing
a game, a display, or mss.
"""
import unittest

try:
    import numpy as np

    from solver.live.catalogue import HeadCatalogue
    from solver.live.vision import TEAL
    from solver.live.watch import (
        BattleWatcher, CogReading, HEALTH_EPSILON, _roi,
    )
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"watch needs numpy: {exc}") from None


class ScriptedCapture:
    """Hands out a fixed list of frames, then repeats the last one."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def grab(self):
        frame = self.frames[min(self.calls, len(self.frames) - 1)]
        self.calls += 1
        return frame

    def close(self):
        pass


def frame_with(slots, size=(1280, 720)):
    """A frame holding a plate slot per (x, y) given."""
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :] = (70, 70, 80)
    for x, y in slots:
        img[y - 15:y + 90, x - 16:x + 198] = (170, 170, 165)
        img[y:y + 45, x:x + 66] = TEAL
    return img


class ReadingTest(unittest.TestCase):

    def test_same_cog_ignores_health(self):
        a = CogReading(0, "cashbot", 6, 1.0)
        b = CogReading(0, "cashbot", 6, 0.4)
        self.assertTrue(a.same_cog_as(b))

    def test_different_level_is_a_different_cog(self):
        a = CogReading(0, "cashbot", 6, 1.0)
        b = CogReading(0, "cashbot", 7, 1.0)
        self.assertFalse(a.same_cog_as(b))

    def test_identifying_a_cog_midfight_is_not_a_new_cog(self):
        """Otherwise naming a cog partway through reads as it being
        replaced, and the battle appears to restart."""
        a = CogReading(0, "cashbot", 6, 1.0, cog=None)
        b = CogReading(0, "cashbot", 6, 1.0, cog="tightwad")
        self.assertTrue(a.same_cog_as(b))


class RoiTest(unittest.TestCase):

    def test_band_covers_the_plates_with_room_to_move(self):
        top, bottom = _roi([(100, 200, 166, 245)], (720, 1280, 3))
        self.assertLess(top, 200)
        self.assertGreater(bottom, 245)

    def test_band_is_clamped_to_the_frame(self):
        top, bottom = _roi([(100, 2, 166, 47)], (720, 1280, 3))
        self.assertEqual(top, 0)
        self.assertLessEqual(bottom, 720)


class WatcherTest(unittest.TestCase):

    def build(self, frames, agree=2):
        return BattleWatcher(catalogue=HeadCatalogue.__new__(HeadCatalogue),
                             capture=ScriptedCapture(frames), agree=agree,
                             collect=False)

    def setUp(self):
        # A catalogue with no entries and no disk access.
        self.empty = HeadCatalogue.__new__(HeadCatalogue)
        self.empty.entries = {}

    def watcher(self, frames, agree=2):
        w = BattleWatcher(catalogue=self.empty,
                          capture=ScriptedCapture(frames), agree=agree,
                          collect=False)
        return w

    def test_a_single_frame_is_not_enough_to_report_a_battle(self):
        """Cogs animate; one frame is noise, not evidence."""
        w = self.watcher([frame_with([(300, 120)])], agree=2)
        self.assertEqual(w.poll(), [])          # first sighting: wait

    def test_two_agreeing_frames_start_a_battle(self):
        w = self.watcher([frame_with([(300, 120)])], agree=2)
        w.poll()
        events = w.poll()
        self.assertEqual([e.kind for e in events], ["battle_started"])
        self.assertTrue(w.view.active)

    def test_a_flickering_frame_does_not_start_a_battle(self):
        blank = frame_with([])
        one = frame_with([(300, 120)])
        w = self.watcher([one, blank, one, blank], agree=2)
        for _ in range(4):
            self.assertEqual(w.poll(), [])
        self.assertFalse(w.view.active)

    def test_losing_a_plate_reports_a_defeat(self):
        two = frame_with([(300, 120), (600, 120)])
        one = frame_with([(300, 120)])
        w = self.watcher([two, two, one, one], agree=2)
        w.poll(); w.poll()                      # battle starts
        w.poll()
        events = w.poll()
        self.assertEqual([e.kind for e in events], ["cog_defeated"])

    def test_losing_every_plate_ends_the_battle(self):
        one = frame_with([(300, 120)])
        blank = frame_with([])
        w = self.watcher([one, one, blank, blank], agree=2)
        w.poll(); w.poll()
        w.poll()
        events = w.poll()
        self.assertEqual([e.kind for e in events], ["battle_ended"])
        self.assertFalse(w.view.active)

    def test_a_new_plate_reports_a_join(self):
        one = frame_with([(300, 120)])
        two = frame_with([(300, 120), (600, 120)])
        w = self.watcher([one, one, two, two], agree=2)
        w.poll(); w.poll()
        w.poll()
        self.assertEqual([e.kind for e in w.poll()], ["cog_joined"])

    def test_the_roi_avoids_rescanning_the_whole_screen(self):
        """The optimisation that makes polling affordable."""
        one = frame_with([(300, 120)])
        w = self.watcher([one], agree=1)
        for _ in range(6):
            w.poll()
        self.assertEqual(w.frames, 6)
        self.assertLess(w.full_scans, 3)


class DamageTest(unittest.TestCase):

    def setUp(self):
        self.empty = HeadCatalogue.__new__(HeadCatalogue)
        self.empty.entries = {}

    def watcher(self):
        return BattleWatcher(catalogue=self.empty,
                             capture=ScriptedCapture([frame_with([])]),
                             agree=1, collect=False)

    def test_a_health_drop_is_reported_as_damage(self):
        w = self.watcher()
        before = [CogReading(0, "cashbot", 6, 1.0)]
        after = [CogReading(0, "cashbot", 6, 0.6)]
        self.assertEqual([e.kind for e in w._diff(before, after)], ["damage"])

    def test_noise_below_the_epsilon_is_not_damage(self):
        """A bar that wobbles a point between frames is not a hit."""
        w = self.watcher()
        before = [CogReading(0, "cashbot", 6, 1.0)]
        after = [CogReading(0, "cashbot", 6, 1.0 - HEALTH_EPSILON / 2)]
        self.assertEqual(w._diff(before, after), [])

    def test_health_going_up_is_not_damage(self):
        w = self.watcher()
        before = [CogReading(0, "cashbot", 6, 0.5)]
        after = [CogReading(0, "cashbot", 6, 0.9)]
        self.assertEqual(w._diff(before, after), [])


if __name__ == "__main__":
    unittest.main()
