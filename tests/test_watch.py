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


# The scripted frames below draw cog plates but no gag menu, and the
# watcher now requires both to *enter* a battle. These tests are about
# what changed between frames, not about telling a battle from scenery,
# so they assert the panel is there; PanelGateTest covers the gate.
def ALWAYS(_frame):
    return True


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
                             collect=False, panel_present=ALWAYS)

    def setUp(self):
        # A catalogue with no entries and no disk access.
        self.empty = HeadCatalogue.__new__(HeadCatalogue)
        self.empty.entries = {}

    def watcher(self, frames, agree=2):
        w = BattleWatcher(catalogue=self.empty,
                          capture=ScriptedCapture(frames), agree=agree,
                          collect=False, panel_present=ALWAYS)
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

    def test_losing_every_plate_does_not_immediately_end_the_battle(self):
        """The plates go away for the whole of an attack animation.

        TTR cuts the camera to the cog being hit and takes the gag menu
        and every plate with it. Reading that as the end reported a
        battle starting and ending several times per fight, and each
        re-entry re-ran the search on what was the same battle.
        """
        one = frame_with([(300, 120)])
        blank = frame_with([])
        w = self.watcher([one, one, blank, blank, blank], agree=2)
        w.poll(); w.poll()
        self.assertTrue(w.view.active)
        self.assertEqual(w.poll(), [])
        self.assertEqual(w.poll(), [])
        self.assertTrue(w.view.active, "still the same fight")

    def test_plates_staying_away_long_enough_does_end_it(self):
        import solver.live.watch as watch_mod

        one = frame_with([(300, 120)])
        blank = frame_with([])
        w = self.watcher([one, one, blank, blank], agree=2)
        w.poll(); w.poll()
        # Older than any animation can be.
        w._plates_at -= watch_mod.BATTLE_GRACE + 1
        w.poll()
        events = w.poll()
        self.assertEqual([e.kind for e in events], ["battle_ended"])
        self.assertFalse(w.view.active)

    def test_something_that_knows_can_end_it_sooner(self):
        """The Local API's merit total ticks up the moment a fight pays
        out. That is proof the battle finished and it arrives at once,
        so it short-circuits the timer -- but it only fires for a
        department whose suit the toon owns, so it can confirm an end
        and never rule one out."""
        one = frame_with([(300, 120)])
        blank = frame_with([])
        paid_out = {"yes": False}
        w = BattleWatcher(catalogue=self.empty,
                          capture=ScriptedCapture([one, one, blank, blank]),
                          agree=2, collect=False, panel_present=ALWAYS,
                          battle_over=lambda: paid_out["yes"])
        w.poll(); w.poll()
        self.assertEqual(w.poll(), [])          # timer still running
        paid_out["yes"] = True
        events = w.poll()
        self.assertEqual([e.kind for e in events], ["battle_ended"])

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

    def test_the_roi_path_reports_the_same_box_as_a_full_scan(self):
        """The band path runs for the whole of every battle, so a box it
        shifts is a box every reading is taken from. The first version
        returned band-relative slots and let the readers sample the full
        frame with them, putting every region short by the band's top
        edge; nothing caught it because the counts still looked right.
        """
        one = frame_with([(300, 120)])
        w = self.watcher([one], agree=1)
        w.poll()
        self.assertEqual(w.full_scans, 1)
        from_full = [c.slot for c in w.view.cogs]

        w.poll()
        self.assertEqual(w.full_scans, 1)          # the band was used
        self.assertEqual([c.slot for c in w.view.cogs], from_full)

    def test_the_roi_box_matches_a_direct_full_frame_scan(self):
        """And the box must equal what find_plates says about the whole
        frame -- the band is an eighth of the frame, so thresholds
        expressed as fractions of it would drift the edges."""
        from solver.live.vision import find_plates

        one = frame_with([(300, 120)])
        w = self.watcher([one], agree=1)
        w.poll(); w.poll()
        self.assertEqual([c.slot for c in w.view.cogs],
                         [p.slot for p in find_plates(one)])


class DamageTest(unittest.TestCase):

    def setUp(self):
        self.empty = HeadCatalogue.__new__(HeadCatalogue)
        self.empty.entries = {}

    def watcher(self):
        return BattleWatcher(catalogue=self.empty,
                             capture=ScriptedCapture([frame_with([])]),
                             agree=1, collect=False, panel_present=ALWAYS)

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


class TestNamingFromThePanel(unittest.TestCase):
    """Naming a plate applies it, and teaches the head library."""

    def _watcher(self):
        from solver.live.watch import BattleWatcher
        return BattleWatcher()

    def test_name_is_remembered_by_slot(self):
        w = self._watcher()
        w.name_plate(0, "mr_hollywood")
        self.assertEqual("mr_hollywood", w._named[0])

    def test_naming_queues_it_for_the_library(self):
        w = self._watcher()
        w.name_plate(0, "mr_hollywood")
        self.assertEqual("mr_hollywood", w._learn[0])

    def test_a_cog_already_known_is_not_relearned(self):
        """No point rewriting a signature the library already has."""
        w = self._watcher()
        if not w.catalogue.entries:
            self.skipTest("no catalogue entries shipped")
        known = sorted(w.catalogue.entries)[0]
        w.name_plate(0, known)
        self.assertNotIn(0, w._learn)
        self.assertEqual(known, w._named[0])

    def test_clearing_a_name_drops_the_pending_write(self):
        w = self._watcher()
        w.name_plate(0, "mr_hollywood")
        w.name_plate(0, None)
        self.assertNotIn(0, w._named)
        self.assertNotIn(0, w._learn)

    def test_learn_can_be_declined(self):
        w = self._watcher()
        w.name_plate(0, "mr_hollywood", learn=False)
        self.assertNotIn(0, w._learn)
        self.assertEqual("mr_hollywood", w._named[0])


    def test_a_name_survives_a_detection_flicker(self):
        """`find_plates` drops a plate for a frame when a cog is
        mid-animation. Acting on that threw the pick away, which looked
        exactly like the dropdown not working."""
        from solver.live.watch import FORGET_AFTER_FRAMES
        w = self._watcher()
        w.name_plate(1, "number_cruncher")
        for count in (2, 1, 2, 2, 1, 2):
            w._forget_names(count)
        self.assertEqual("number_cruncher", w._named[1])
        self.assertGreater(FORGET_AFTER_FRAMES, 1)

    def test_a_name_is_dropped_once_the_plate_really_goes(self):
        from solver.live.watch import FORGET_AFTER_FRAMES
        w = self._watcher()
        w.name_plate(1, "number_cruncher")
        for _ in range(FORGET_AFTER_FRAMES + 1):
            w._forget_names(1)
        self.assertEqual({}, w._named)

    def test_a_name_on_a_plate_that_still_exists_is_kept(self):
        """Only the out-of-range names are stale. Clearing all of them
        on any count change is what broke the feature."""
        w = self._watcher()
        w.name_plate(0, "mr_hollywood")
        for _ in range(10):
            w._forget_names(3)
        self.assertEqual("mr_hollywood", w._named[0])

    def test_an_explicit_reset_clears_everything(self):
        w = self._watcher()
        w.name_plate(0, "mr_hollywood")
        w._forget_names(-1)
        self.assertEqual({}, w._named)

    def test_lure_is_marked_and_cleared(self):
        w = self._watcher()
        w.mark_lured(1, True)
        self.assertIn(1, w._lured)
        w.mark_lured(1, False)
        self.assertNotIn(1, w._lured)

    def test_lure_marks_expire_with_the_plate(self):
        w = self._watcher()
        w.mark_lured(2, True)
        w._forget_names(-1)
        self.assertEqual(set(), w._lured)
