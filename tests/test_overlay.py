"""The overlay's decisions, without a display.

Everything the window decides lives in `Model`, which knows nothing
about Tk, so all of it can be checked on a machine with no screen. The
Tk half is a rendering of this and holds no logic worth testing.

The one rule with teeth is when the confirm button may be pressed. An
override that is always available is a way to ask for advice about a
battle that is not happening, and the state would then be assembled
from whatever the readers last saw -- which is the same failure as
guessing, arrived at by a different route.
"""
import unittest

from solver.live.overlay import ADVICE_LINGER, Model


class ConfirmButtonTest(unittest.TestCase):

    def test_nothing_on_screen_means_nothing_to_confirm(self):
        model = Model(window_found=True)
        self.assertFalse(model.can_confirm)
        self.assertIn("nothing on screen", model.evidence)

    def test_plates_alone_are_enough_to_offer_it(self):
        """Plates without the menu is exactly the case automatic
        detection refuses, and exactly the case the player can settle."""
        model = Model(window_found=True, plates=2)
        self.assertTrue(model.can_confirm)
        self.assertIn("2 cog plates", model.evidence)

    def test_the_menu_alone_is_too(self):
        model = Model(window_found=True, menu_visible=True)
        self.assertTrue(model.can_confirm)
        self.assertIn("gag menu", model.evidence)

    def test_ending_a_fight_is_always_allowed(self):
        """Getting out has to work even once the screen has moved on --
        the plates are already gone by the time you want to say so."""
        model = Model(window_found=True, forced=True)
        self.assertTrue(model.can_confirm)

    def test_a_missing_game_window_is_said_out_loud(self):
        model = Model(window_found=False)
        self.assertFalse(model.can_confirm)
        self.assertIn("window", model.evidence)

    def test_one_plate_is_singular(self):
        self.assertIn("1 cog plate,",
                      Model(window_found=True, plates=1,
                            menu_visible=True).evidence + ",")


class ForcedStateTest(unittest.TestCase):

    def test_confirming_overrides_detection(self):
        self.assertTrue(Model(detected_battle=False, forced=True).in_battle)

    def test_so_does_denying(self):
        self.assertFalse(Model(detected_battle=True, forced=False).in_battle)

    def test_no_opinion_defers_to_detection(self):
        self.assertTrue(Model(detected_battle=True, forced=None).in_battle)
        self.assertFalse(Model(detected_battle=False, forced=None).in_battle)

    def test_the_status_says_which_it_is(self):
        self.assertIn("confirmed", Model(forced=True).status)
        self.assertIn("detected", Model(detected_battle=True).status)


class AdviceTextTest(unittest.TestCase):

    def test_the_gag_shows_while_the_fight_is_on(self):
        model = Model(detected_battle=True, gag="Wedding Cake on all cogs",
                      gag_at=1000.0)
        self.assertEqual(model.advice_text(now=1000.0),
                         "Wedding Cake on all cogs")

    def test_it_lingers_briefly_after_the_fight(self):
        """Long enough to read the last recommendation."""
        model = Model(detected_battle=False, gag="Trapdoor on Flunky",
                      gag_at=1000.0)
        self.assertEqual(model.advice_text(now=1000.0 + ADVICE_LINGER / 2),
                         "Trapdoor on Flunky")

    def test_then_stops_so_it_is_not_read_as_current(self):
        model = Model(detected_battle=False, gag="Trapdoor on Flunky",
                      gag_at=1000.0)
        self.assertEqual(model.advice_text(now=1000.0 + ADVICE_LINGER + 1),
                         "-")

    def test_thinking_is_shown_rather_than_a_stale_blank(self):
        model = Model(thinking=True)
        self.assertEqual(model.advice_text(now=0.0), "thinking...")

    def test_problems_are_shown_when_there_is_no_state(self):
        model = Model(problems=["cog 1: unidentified"])
        self.assertEqual(model.detail_lines(), ["cog 1: unidentified"])

    def test_cogs_are_shown_once_there_is_one(self):
        model = Model(detected_battle=True, cogs=["Flunky  lvl 4  100%"],
                      problems=["stale"])
        self.assertEqual(model.detail_lines(), ["Flunky  lvl 4  100%"])


class WorkerWiringTest(unittest.TestCase):
    """The worker is what the watcher asks for its override."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"needs numpy: {exc}")

    def test_forced_is_tri_state_and_thread_safe_to_set(self):
        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        import threading

        w._lock = threading.Lock()
        w._forced = None
        self.assertIsNone(w.forced())
        w.set_forced(True)
        self.assertTrue(w.forced())
        w.set_forced(False)
        self.assertIs(w.forced(), False)
        w.set_forced(None)
        self.assertIsNone(w.forced())

    def test_the_watcher_takes_the_override(self):
        """Confirming skips the gag-menu requirement for entering a
        fight, and denying ends one -- but neither invents cogs."""
        from solver.live.watch import BattleWatcher
        from solver.live.catalogue import HeadCatalogue

        empty = HeadCatalogue.__new__(HeadCatalogue)
        empty.entries = {}
        forced = {"v": None}
        w = BattleWatcher(catalogue=empty, capture=_NoCapture(),
                          collect=False, panel_present=lambda _f: False,
                          force_battle=lambda: forced["v"])
        # No menu, so detection refuses.
        self.assertFalse(w.in_battle(object(), True))
        forced["v"] = True
        self.assertTrue(w.in_battle(object(), True))
        # ...but a forced battle with nothing on screen is still no cogs.
        self.assertFalse(w.in_battle(object(), False))
        forced["v"] = False
        self.assertFalse(w.in_battle(object(), True))


class _NoCapture:
    def grab(self):                              # pragma: no cover
        raise AssertionError("should not be called")

    def close(self):
        pass


if __name__ == "__main__":
    unittest.main()
