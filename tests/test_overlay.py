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

from solver.live.overlay import ADVICE_LINGER, Model, TurnCounter


class ConfirmButtonTest(unittest.TestCase):

    def test_it_is_offered_even_with_nothing_read_yet(self):
        """Was the opposite, and the owner was right to object.

        Detection needs two agreeing polls, so for a second or so after a
        fight starts there is nothing on screen as far as the readers are
        concerned -- and that is exactly when a player wants to say "I am
        in a fight". Gating the override on detection made the button
        unavailable in the only window where it was useful.

        Asserting a fight that is not happening costs nothing:
        `build_state` still refuses without readings, so the panel
        reports what it cannot see instead of inventing advice.
        """
        model = Model(window_found=True)
        self.assertTrue(model.can_confirm)
        self.assertIn("nothing on screen", model.evidence)

    def test_it_is_withheld_without_the_game_window(self):
        """No window is a different thing from nothing read: there is
        nothing to assert a fight in."""
        model = Model(window_found=False)
        self.assertFalse(model.can_confirm)

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


class TurnCounterTest(unittest.TestCase):
    """Rounds are inferred from the gag menu; nothing reports them."""

    def test_no_battle_means_no_turn(self):
        c = TurnCounter()
        self.assertEqual(c.observe(False, True, now=0.0), 0)

    def test_the_menu_opening_is_the_first_turn(self):
        c = TurnCounter()
        self.assertEqual(c.observe(True, False, now=0.0), 0)
        self.assertEqual(c.observe(True, True, now=1.0), 1)

    def test_the_menu_staying_open_is_still_one_turn(self):
        """It is on screen for the whole time you are choosing."""
        c = TurnCounter()
        c.observe(True, True, now=0.0)
        for t in range(1, 20):
            c.observe(True, True, now=float(t))
        self.assertEqual(c.turn, 1)

    def test_it_counts_again_when_the_menu_comes_back(self):
        c = TurnCounter()
        c.observe(True, True, now=0.0)          # turn 1
        c.observe(True, False, now=5.0)         # animation
        self.assertEqual(c.observe(True, True, now=10.0), 2)

    def test_a_flicker_is_not_a_round(self):
        """A momentary misread of the menu would otherwise count one.
        Nothing in Toontown resolves a round that fast."""
        c = TurnCounter()
        c.observe(True, True, now=0.0)
        c.observe(True, False, now=0.4)         # one bad frame
        self.assertEqual(c.observe(True, True, now=0.8), 1)

    def test_it_restarts_with_each_battle(self):
        c = TurnCounter()
        c.observe(True, True, now=0.0)
        c.observe(True, False, now=6.0)
        c.observe(True, True, now=12.0)
        self.assertEqual(c.turn, 2)
        self.assertEqual(c.observe(False, False, now=20.0), 0)
        self.assertEqual(c.observe(True, True, now=30.0), 1)

    def test_the_status_line_marks_it_as_an_estimate(self):
        self.assertIn("~3", Model(detected_battle=True, turn=3).status)

    def test_and_omits_it_before_the_first_menu(self):
        self.assertNotIn("turn", Model(detected_battle=True, turn=0).status)


class AdviseOnDemandTest(unittest.TestCase):
    """Asking for a prediction, rather than waiting for one.

    The search otherwise runs only when the battle *changes*. Both of
    the common failures -- the gag menu opening after the fight started,
    a cog labelled mid-battle -- leave a stale problem that nothing
    would recompute until something died.
    """

    def test_offered_during_a_battle(self):
        self.assertTrue(Model(detected_battle=True).can_advise)

    def test_not_offered_when_there_is_no_battle(self):
        self.assertFalse(Model(detected_battle=False).can_advise)

    def test_not_offered_while_a_search_is_already_running(self):
        self.assertFalse(Model(detected_battle=True, thinking=True).can_advise)

    def test_offered_on_a_confirmed_battle_too(self):
        self.assertTrue(Model(detected_battle=False, forced=True).can_advise)

    def test_the_request_is_a_flag_the_worker_picks_up(self):
        """Pressed on Tk's thread, acted on by the worker's."""
        import threading

        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._asked = threading.Event()
        self.assertFalse(w._asked.is_set())
        w.ask_now()
        self.assertTrue(w._asked.is_set())


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


class TestEndingAFight(unittest.TestCase):
    """"Fight is over" must actually end it, and wipe what it left."""

    def _worker(self):
        import queue
        from solver.live.overlay import Worker
        from solver.search import objective as objectives
        return Worker(queue.Queue(maxsize=4), objectives.PRESETS["balanced"],
                      2, 15.0)

    def _mid_fight(self, w):
        from solver.live.overlay import Model
        w.model = Model(detected_battle=True, plates=2, menu_visible=True,
                        gag="Wedding Cake on all cogs", track="throw",
                        gag_level=7, turn=4, problems=["cog 1: unidentified"])
        return w.model

    def test_it_leaves_the_battle(self):
        w = self._worker()
        self._mid_fight(w)
        w.end_fight()
        self.assertFalse(w.model.in_battle)

    def test_it_suppresses_rather_than_deferring(self):
        """None means 'decide for yourself', and the readers still see
        plates -- so the battle came straight back."""
        w = self._worker()
        self._mid_fight(w)
        w.end_fight()
        self.assertIs(False, w.forced())

    def test_it_clears_the_advice_and_the_reasons(self):
        w = self._worker()
        self._mid_fight(w)
        w.end_fight()
        self.assertIsNone(w.model.gag)
        self.assertIsNone(w.model.track)
        self.assertEqual([], w.model.problems)
        self.assertEqual(0, w.model.turn)

    def test_the_player_can_start_another(self):
        w = self._worker()
        self._mid_fight(w)
        w.end_fight()
        w.set_forced(True)
        self.assertIs(True, w.forced())
