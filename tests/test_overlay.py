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


class DisplayedReasonsMatchDisplayedMoveTest(unittest.TestCase):
    """The why-line must describe the gag that is on screen.

    `explain.describe` used to run in one place -- the SEARCH's
    callback -- while the panel renders whichever engine the player
    prefers. With the RL badge showing, a live board read

        Grand Piano on cog 1 (Number Cruncher, 110/110 hp)
        kills 2 - 95% acc

    and both numbers were false OF THE PIANO. They belonged to a group
    Wedding Cake the search had picked and the page never displayed: a
    single-target Drop against an awake level 9 is 70% and kills one.

    The failure is silent and looks like a mechanics bug rather than a
    plumbing one, which is why it is pinned here with the real values.
    """

    def _worker(self):
        import threading

        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._lock = threading.Lock()
        w.model = Model()
        w._post = lambda: None
        return w

    def _both_answers(self, model):
        model.rl_gag = "Grand Piano on cog 1"
        model.rl_track, model.rl_gag_level = "drop", 6
        model.rl_accuracy, model.rl_reason = 70, "kills it"
        model.search_gag = "Wedding Cake on every cog"
        model.search_track, model.search_gag_level = "throw", 7
        model.search_accuracy, model.search_reason = 95, "kills 2"
        model.search_ready = True

    def test_sync_follows_the_engine_being_shown(self):
        from solver.live.overlay import Worker

        model = Model()
        self._both_answers(model)

        model.engine = "rl"
        Worker._sync_explanation(model)
        self.assertEqual(70, model.accuracy)
        self.assertEqual("kills it", model.reason)

        model.engine = "search"
        Worker._sync_explanation(model)
        self.assertEqual(95, model.accuracy)
        self.assertEqual("kills 2", model.reason)

    def test_swapping_engines_swaps_the_reasons_with_the_gag(self):
        w = self._worker()
        self._both_answers(w.model)
        w.model.engine = "rl"
        w.model.preferred_engine = "rl"

        w.prefer_engine("search")
        self.assertEqual("Wedding Cake on every cog", w.model.gag)
        self.assertEqual(95, w.model.accuracy)
        self.assertEqual("kills 2", w.model.reason)

        w.prefer_engine("rl")
        self.assertEqual("Grand Piano on cog 1", w.model.gag)
        self.assertEqual(70, w.model.accuracy)
        self.assertEqual("kills it", w.model.reason)

    def test_a_refused_swap_leaves_the_pair_alone(self):
        """No search answer yet, so the badge does not move -- and the
        reasons must not move either."""
        w = self._worker()
        self._both_answers(w.model)
        w.model.search_ready = False
        w.model.engine = "rl"

        w.prefer_engine("search")
        self.assertEqual(70, w.model.accuracy)
        self.assertEqual("kills it", w.model.reason)

    def test_the_two_moves_really_do_read_differently(self):
        """The board from the report, so the numbers above stay honest.

        A level 9 Number Cruncher awake beside a lured level 6 Penny
        Pincher. Group Throw 7 collects the luredRatio bonus off the
        sleeper and pins at the 95 cap; a single Drop gets none of it.
        """
        from solver import data
        from solver.live import explain
        from solver.state import Action, BattleState, CogState, ToonState, Track

        def cog(key, level):
            hp = data.cog_max_hp(level)
            return CogState(cog_type=key, department="cashbot",
                            level=level, hp=hp, max_hp=hp)

        cruncher, pincher = cog("number_cruncher", 9), cog("penny_pincher", 6)
        pincher.status.lured = True
        toon = ToonState(95, 95, {t: 7 for t in Track},
                         {(t, l): 5 for t in Track for l in range(1, 8)},
                         frozenset())
        state = BattleState(toons=[toon], cogs=[cruncher, pincher])

        piano = explain.describe(
            state, Action(track=Track.DROP, level=6, target_index=0))
        self.assertEqual(70, piano["accuracy"])
        self.assertEqual(1, piano["kills"])
        self.assertEqual("kills it", explain.reason(piano))

        cake = explain.describe(
            state, Action(track=Track.THROW, level=7, target_index=None))
        self.assertEqual(95, cake["accuracy"])
        self.assertEqual(2, cake["kills"])
        self.assertEqual("kills 2", explain.reason(cake))


class RetryAfterAFailedReadTest(unittest.TestCase):
    """A read that produced no state must be tried again.

    Reported from live play: "the no battle thing pops up after a round
    passes and then it doesn't try to predict anymore". Searches are
    triggered by position CHANGES, and the frame captured at a round
    boundary is the one most likely to be unreadable -- so the failure
    landed and nothing asked again, because the next `damage` event
    cannot arrive while the player waits at the gag menu.
    """

    def _worker(self, **kw):
        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._last_try = 0.0
        # `_should_retry` also refuses to trust a `thinking` flag for
        # ever; a worker that never thought has no clock running.
        w._thinking_since = 0.0
        w.budget = 15.0
        w.model = Model()
        for key, value in kw.items():
            setattr(w.model, key, value)
        return w

    def test_it_asks_again_when_the_last_read_failed(self):
        w = self._worker(forced=True, problems=["cog 1: level unreadable"])
        self.assertTrue(w._should_retry(w.model, 100.0))

    def test_it_waits_out_the_interval_rather_than_hammering(self):
        from solver.live.overlay import RETRY_INTERVAL

        w = self._worker(forced=True, problems=["cog 1: level unreadable"])
        w._last_try = 100.0
        self.assertFalse(w._should_retry(w.model, 100.0 + RETRY_INTERVAL / 2))
        self.assertTrue(w._should_retry(w.model, 100.0 + RETRY_INTERVAL))

    def test_a_successful_read_stops_it(self):
        """`problems` is what success clears, so it is the gate."""
        w = self._worker(forced=True, problems=[])
        self.assertFalse(w._should_retry(w.model, 100.0))

    def test_stale_advice_does_not_look_like_success(self):
        """The previous round's gag is still on screen when this fires,
        so the absence of advice is the wrong thing to test."""
        w = self._worker(forced=True, problems=["cog 1: level unreadable"],
                         gag="Grand Piano on cog 1")
        self.assertTrue(w._should_retry(w.model, 100.0))

    def test_it_does_not_run_outside_a_battle(self):
        w = self._worker(forced=False, problems=["no cog plates"])
        self.assertFalse(w._should_retry(w.model, 100.0))

    def test_it_does_not_pile_onto_a_search_already_running(self):
        w = self._worker(forced=True, problems=["cog 1: level unreadable"],
                         thinking=True)
        self.assertFalse(w._should_retry(w.model, 100.0))


class FailedReadSaysWhyTest(unittest.TestCase):
    """`BuildResult` is falsy when it has no state, which ate its own
    reasons: `res.problems if res else [...]` can never take the first
    branch, so every unreadable frame reported the useless "no battle
    detected" while "cog 1: level unreadable" sat unused in `res`."""

    def test_the_result_carrying_reasons_is_falsy(self):
        from solver.live.session import BuildResult

        res = BuildResult(None, ["cog 1: level unreadable"])
        self.assertFalse(res)
        self.assertEqual(["cog 1: level unreadable"], res.problems)

    def test_the_reasons_reach_the_panel_anyway(self):
        from solver.live import advise as advise_mod
        from solver.live.session import BuildResult

        seen = []
        thinker = advise_mod.Thinker(
            lambda lines, state, action: seen.append(list(lines)))
        thinker._current = 0

        saved = (advise_mod._snapshot, advise_mod._panel,
                 advise_mod.build_state)
        advise_mod._snapshot = lambda: None
        advise_mod._panel = lambda frame: None
        advise_mod.build_state = lambda **kw: BuildResult(
            None, ["cog 1: level unreadable", "gag menu not visible"])
        try:
            thinker._run(0, object(), [], None, None, 1, 1.0)
        finally:
            (advise_mod._snapshot, advise_mod._panel,
             advise_mod.build_state) = saved

        self.assertEqual(
            [["cog 1: level unreadable", "gag menu not visible"]], seen)

    def test_nothing_at_all_still_says_something(self):
        from solver.live import advise as advise_mod

        seen = []
        thinker = advise_mod.Thinker(
            lambda lines, state, action: seen.append(list(lines)))
        thinker._current = 0

        saved = (advise_mod._snapshot, advise_mod._panel,
                 advise_mod.build_state)
        advise_mod._snapshot = lambda: None
        advise_mod._panel = lambda frame: None
        advise_mod.build_state = lambda **kw: None
        try:
            thinker._run(0, object(), [], None, None, 1, 1.0)
        finally:
            (advise_mod._snapshot, advise_mod._panel,
             advise_mod.build_state) = saved

        self.assertEqual([["no battle detected"]], seen)


class AGuaranteedMissSaysSoTest(unittest.TestCase):
    """Reported as "doesn't give the reasoning for the first attack".

    The reasoning was that the gag could not land: the policy offered a
    Grand Piano at a LURED cog, and Drop always misses one. No kill,
    nothing prevented, no damage -- so every branch fell through and the
    line came out blank, which reads as a broken explainer rather than
    as the warning it is.
    """

    def _board(self, lured):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track

        hp = data.cog_max_hp(9)
        cog = CogState(cog_type="number_cruncher", department="cashbot",
                       level=9, hp=hp, max_hp=hp)
        cog.status.lured = lured
        toon = ToonState(95, 95, {t: 7 for t in Track},
                         {(t, l): 5 for t in Track for l in range(1, 8)},
                         frozenset())
        return BattleState(toons=[toon], cogs=[cog])

    def test_drop_on_a_lured_cog_is_called_out(self):
        from solver.live import explain
        from solver.state import Action, Track

        piano = Action(track=Track.DROP, level=6, target_index=0)
        detail = explain.describe(self._board(True), piano)
        self.assertEqual(0, detail["accuracy"])
        self.assertEqual("always misses a lured cog", explain.reason(detail))

    def test_the_same_gag_on_an_awake_cog_reads_normally(self):
        from solver.live import explain
        from solver.state import Action, Track

        piano = Action(track=Track.DROP, level=6, target_index=0)
        detail = explain.describe(self._board(False), piano)
        self.assertEqual(70, detail["accuracy"])
        self.assertEqual("kills it", explain.reason(detail))

    def test_only_a_stated_zero_triggers_it(self):
        """`ACCURACY_FLOOR` is 5, so a merely unlikely gag is not this."""
        from solver import data
        from solver.live import explain

        self.assertEqual(5, data.ACCURACY_FLOOR)
        self.assertEqual("5 damage",
                         explain.reason({"accuracy": 5, "damage": 5}))


class OneFrameOneAnswerTest(unittest.TestCase):
    """`menu_visible` and the gag-menu READ must judge the same capture.

    `poll()` sets `menu_visible = find_panel(frame) is not None`, and the
    overlay used to grab a SECOND frame and hand that to `read_panel`,
    which starts with the identical `find_panel` call. Two captures
    milliseconds apart disagree while the menu is sliding, so the panel
    said "see: 2 cog plates, gag menu" and "no gag menu on screen" at
    once -- a contradiction with nothing the player could do about it.
    """

    def test_the_watcher_keeps_the_frame_it_graded(self):
        from solver.live.watch import BattleWatcher

        w = BattleWatcher.__new__(BattleWatcher)
        self.assertIsNone(getattr(w, "last_frame", None))

    def test_poll_publishes_that_frame(self):
        import inspect

        from solver.live.watch import BattleWatcher

        src = inspect.getsource(BattleWatcher.poll)
        grab = src.index("self.capture.grab()")
        keep = src.index("self.last_frame = frame")
        judge = src.index("find_panel(frame)")
        # Kept straight after the grab, and before anything judges it.
        self.assertLess(grab, keep)
        self.assertLess(keep, judge)

    def test_the_overlay_reads_it_rather_than_grabbing_again(self):
        import inspect

        from solver.live.overlay import Worker

        src = inspect.getsource(Worker.run)
        self.assertIn("frame = watcher.last_frame", src)
        # The only remaining grab is the "nothing polled yet" fallback.
        self.assertEqual(1, src.count("watcher.capture.grab()"))


class GroupDamageIsPerCogTest(unittest.TestCase):
    """A group gag's TOTAL is the scorer's number, not the player's.

    Foghorn against two cogs reported "100 damage" beside a 110/110
    Number Cruncher, which reads as very nearly a kill. It is 50 each
    and both cogs live. Spreading damage is the whole point of Sound, so
    summing the spread away hides exactly what the track is for.
    """

    def _cog(self, key, level, lured=False):
        from solver import data
        from solver.state import CogState

        hp = data.cog_max_hp(level)
        cog = CogState(cog_type=key, department="cashbot", level=level,
                       hp=hp, max_hp=hp)
        cog.status.lured = lured
        return cog

    def _state(self, cogs):
        from solver.state import BattleState, ToonState, Track

        toon = ToonState(95, 95, {t: 7 for t in Track},
                         {(t, l): 3 for t in Track for l in range(1, 8)},
                         frozenset())
        return BattleState(toons=[toon], cogs=cogs)

    def test_an_even_spread_is_reported_per_cog(self):
        from solver.live import explain
        from solver.state import Action, Track

        state = self._state([self._cog("bean_counter", 7),
                             self._cog("number_cruncher", 9)])
        detail = explain.describe(
            state, Action(track=Track.SOUND, level=6, target_index=None))
        self.assertEqual(100, detail["damage"])     # still the total
        self.assertEqual(2, detail["targets"])
        self.assertEqual(50, detail["each"])
        self.assertEqual("50 to each of 2 cogs", explain.reason(detail))

    def test_an_uneven_spread_falls_back_to_the_total(self):
        """A lured cog takes the knockback bonus, so there is no
        single "each" to quote."""
        from solver.live import explain
        from solver.state import Action, Track

        state = self._state([self._cog("robber_baron", 12),
                             self._cog("robber_baron", 12, lured=True)])
        detail = explain.describe(
            state, Action(track=Track.THROW, level=7, target_index=None))
        self.assertEqual(2, detail["targets"])
        self.assertNotIn("each", detail)
        self.assertEqual("300 damage across 2 cogs", explain.reason(detail))

    def test_a_single_target_is_unchanged(self):
        from solver.live import explain
        from solver.state import Action, Track

        state = self._state([self._cog("bean_counter", 7),
                             self._cog("number_cruncher", 9)])
        detail = explain.describe(
            state, Action(track=Track.DROP, level=5, target_index=0))
        self.assertEqual(1, detail["targets"])
        self.assertEqual("70 damage", explain.reason(detail))

    def test_a_kill_still_wins_over_the_damage_line(self):
        from solver.live import explain

        self.assertEqual("kills 2", explain.reason(
            {"kills": 2, "damage": 300, "targets": 2, "each": 150}))


class MarksDieWithTheirFightTest(unittest.TestCase):
    """A hand-set mark must not survive into the next battle.

    Reported from play: a cog named "Name Dropper" in one fight -- picked
    from the dropdown because it was not in the head library -- came back
    in the NEXT fight, where the cog was really a Bean Counter. The
    solver planned against 56 hp while 72 hp stood on screen.

    The marks are keyed on PLATE ORDER, and `read_frame` puts the
    player's name ahead of the readers, so a stale pick beats a correct
    read rather than losing to it. `_forget_names(-1)` is the reset and
    was reachable only from the "Fight is over" button, so a fight that
    ended the ordinary way cleared nothing.
    """

    def _watcher(self):
        from solver.live.watch import BattleWatcher

        w = BattleWatcher.__new__(BattleWatcher)
        w._named, w._learn, w._levels = {}, {}, {}
        w._lured = set()
        w._low_frames = 0
        return w

    def _marked(self):
        w = self._watcher()
        w._named[0] = "name_dropper"
        w._lured.add(0)
        w._levels[0] = 6
        return w

    def test_the_explicit_reset_clears_every_kind_of_mark(self):
        w = self._marked()
        w._forget_names(-1)
        self.assertEqual({}, w._named)
        self.assertEqual(set(), w._lured)
        self.assertEqual({}, w._levels)

    def test_a_confirmed_end_resets(self):
        import inspect

        from solver.live.watch import BattleWatcher

        src = inspect.getsource(BattleWatcher.poll)
        end = src.index('battle_ended')
        reset = src.index('self._forget_names(-1)', end)
        started = src.index('battle_started', end)
        # Reset on the confirmed end, before the battle_started backstop.
        self.assertLess(end, reset)
        self.assertLess(reset, started)

    def test_a_start_resets_too_in_case_the_end_was_missed(self):
        import inspect

        from solver.live.watch import BattleWatcher

        src = inspect.getsource(BattleWatcher.poll)
        self.assertEqual(2, src.count('self._forget_names(-1)'))

    def test_an_unconfirmed_end_still_resets_nothing(self):
        """The grace period exists because plates vanish mid-animation;
        a suppressed end must not throw the player's marks away."""
        import inspect

        from solver.live.watch import BattleWatcher

        src = inspect.getsource(BattleWatcher.poll)
        guard = src.index('if not self._battle_is_over():')
        bail = src.index('return []', guard)
        reset = src.index('self._forget_names(-1)', guard)
        self.assertLess(bail, reset)

    def test_pruning_by_count_is_not_the_reset(self):
        """`_forget_names(count)` keeps in-range marks on purpose --
        plates flicker -- so it can never stand in for the reset."""
        w = self._marked()
        w._forget_names(2)
        self.assertEqual("name_dropper", w._named.get(0))


class ReconsiderActuallyRejectsTest(unittest.TestCase):
    """"No, not that" has to reject the MOVE, not its wording.

    `climb` masks its logits on `hybrid.reject_key(entry)`, a
    `(track, group)` tuple. `reconsider` added `model.gag` -- the
    rendered English, "Grand Piano on cog 1 (Number Cruncher, 110/110
    hp)" -- to the set those tuples are looked up in. A string never
    equals a tuple, so nothing was masked and the button did nothing.

    The text could not have worked even in principle: it carries the
    cog's current hp, so it changes every time the cog is hit.
    """

    def _worker(self, engine="rl"):
        import threading

        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._lock = threading.Lock()
        w.model = Model()
        w.model.engine = engine
        w._post = lambda: None
        w._rejected = set()
        w._rl_action = None
        w._search_action = None
        w._asked = threading.Event()
        return w

    def _piano(self):
        from solver.state import Action, Track

        return Action(track=Track.DROP, level=6, target_index=0)

    def test_it_stores_the_key_the_mask_looks_up(self):
        from solver.search import hybrid
        from solver.state import Track

        w = self._worker()
        w._rl_action = self._piano()
        w.reconsider()
        self.assertEqual({hybrid.reject_key(self._piano())}, w._rejected)
        self.assertIn((Track.DROP, False), w._rejected)

    def test_the_key_masks_real_actions(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid

        w = self._worker()
        w._rl_action = self._piano()
        w.reconsider()
        masked = [e for e in env_mod.ACTIONS
                  if hybrid.reject_key(e) in w._rejected]
        self.assertTrue(masked, "reconsider masked nothing at all")
        # One click turns down a KIND of move, not one gag.
        self.assertGreater(len(masked), 1)

    def test_the_old_display_text_masked_nothing(self):
        """Pins the bug, so it cannot come back as a 'simplification'."""
        from solver.rl import env as env_mod
        from solver.search import hybrid

        text = {"Grand Piano on cog 1 (Number Cruncher, 110/110 hp)"}
        self.assertEqual(
            0, sum(1 for e in env_mod.ACTIONS
                   if hybrid.reject_key(e) in text))

    def test_it_rejects_whichever_engine_is_on_screen(self):
        from solver.state import Action, Track

        w = self._worker(engine="search")
        w._rl_action = self._piano()
        w._search_action = Action(track=Track.THROW, level=7,
                                  target_index=None)
        w.reconsider()
        self.assertIn((Track.THROW, True), w._rejected)
        self.assertNotIn((Track.DROP, False), w._rejected)

    def test_a_pass_gets_the_constant_actions_uses_for_it(self):
        """`ACTIONS` stores the pass as a literal None, so `reject_key`
        answers "pass"; a real `Action` with track=None would key as
        (None, True) and match nothing."""
        from solver.search import hybrid
        from solver.state import Action

        w = self._worker()
        w._rl_action = Action(track=None)
        w.reconsider()
        self.assertEqual({"pass"}, w._rejected)
        self.assertEqual("pass", hybrid.reject_key(None))

    def test_nothing_on_screen_rejects_nothing(self):
        w = self._worker()
        w.reconsider()
        self.assertEqual(set(), w._rejected)

    def test_a_rejection_does_not_outlive_the_position(self):
        import inspect

        from solver.live.overlay import Worker

        src = inspect.getsource(Worker.run)
        self.assertIn("self._rejected.clear()", src)
        # Cleared when the BOARD moved, not when the player asked again.
        clear = src.index("self._rejected.clear()")
        changed = src.index("changed = any(")
        self.assertLess(changed, clear)


class RejectWidthsTest(unittest.TestCase):
    """"Not this gag" and "not this track" are different rejections.

    `reject_key` alone is (track, group) -- a KIND of move. That is the
    right default and the wrong only option: turning down a Grand Piano
    because it is overkill on a 56 hp cog is not the same as turning
    down Drop because the cog is lured. The panel's popup asks which,
    so the mask has to understand all three widths at once.
    """

    def _reject(self, action, scope):
        import threading

        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._lock = threading.Lock()
        w.model = Model()
        w.model.engine = "rl"
        w._post = lambda: None
        w._rejected = set()
        w._rl_action = action
        w._search_action = None
        w._asked = threading.Event()
        w.reconsider(scope)
        return w._rejected

    def _piano(self):
        from solver.state import Action, Track

        return Action(track=Track.DROP, level=6, target_index=0)

    def _masked(self, keys):
        from solver.rl import env as env_mod
        from solver.search import hybrid

        return [e for e in env_mod.ACTIONS
                if not keys.isdisjoint(hybrid.reject_keys(e))]

    def test_the_three_widths_nest(self):
        gag = self._masked(self._reject(self._piano(), "gag"))
        kind = self._masked(self._reject(self._piano(), "kind"))
        track = self._masked(self._reject(self._piano(), "track"))
        self.assertLess(len(gag), len(kind))
        self.assertLess(len(kind), len(track))

    def test_rejecting_one_gag_leaves_the_others(self):
        from solver.state import Track

        masked = self._masked(self._reject(self._piano(), "gag"))
        self.assertTrue(masked)
        self.assertEqual({6}, {e.level for e in masked})
        self.assertEqual({Track.DROP}, {e.track for e in masked})

    def test_rejecting_a_track_takes_every_level_of_it(self):
        from solver.state import Track

        masked = self._masked(self._reject(self._piano(), "track"))
        self.assertEqual({Track.DROP}, {e.track for e in masked})
        # Including the level 7 group gag, which the "kind" width leaves.
        self.assertIn(7, {e.level for e in masked})

    def test_the_kind_width_spares_the_group_gag(self):
        masked = self._masked(self._reject(self._piano(), "kind"))
        self.assertNotIn(7, {e.level for e in masked})

    def test_an_unknown_scope_falls_back_to_the_old_behaviour(self):
        from solver.search import hybrid

        self.assertEqual({hybrid.reject_key(self._piano())},
                         self._reject(self._piano(), "wat"))

    def test_a_caller_storing_only_old_keys_still_works(self):
        """`realms_panel` stores bare `reject_key` values; widening the
        mask must not have broken it."""
        from solver.rl import env as env_mod
        from solver.search import hybrid

        first = next(e for e in env_mod.ACTIONS if e is not None)
        self.assertTrue(self._masked({hybrid.reject_key(first)}))

    def test_a_pass_is_its_own_key_at_every_width(self):
        from solver.state import Action

        for scope in ("gag", "kind", "track"):
            self.assertEqual({"pass"},
                             self._reject(Action(track=None), scope))


class BothPanelsShareTheirDecisionsTest(unittest.TestCase):
    """One implementation of "what to do with an answer", not two.

    The two panels differ in exactly one thing -- where a `BattleState`
    comes from -- and everything after that was written twice. It
    drifted in BOTH directions before `AdviceWorker` existed: one
    panel's Reconsider compared a rendered English sentence against
    tuples and so did nothing at all, while the other's worked; one grew
    a why-line and the other never did.

    This is the guard against that happening again. A subclass may
    override a shared decision, but doing so is the drift, so it has to
    be a deliberate edit here as well.
    """

    def _classes(self):
        from solver.live.overlay import Worker
        from solver.live.worker import AdviceWorker

        try:
            from solver.live.realms_panel import RealmsWorker
        except Exception as exc:                   # pragma: no cover
            self.skipTest("second panel unavailable: %s" % exc)
        return AdviceWorker, Worker, RealmsWorker

    def test_both_workers_inherit_the_shared_half(self):
        base, screen, other = self._classes()
        self.assertTrue(issubclass(screen, base))
        self.assertTrue(issubclass(other, base))

    def test_neither_reimplements_a_shared_decision(self):
        """`_post` differs by design -- what a panel refreshes before
        shipping the model is its own business. `_settings_changed` is
        the declared hook. Anything else re-implemented is drift."""
        base, screen, other = self._classes()
        allowed = {"_post", "_settings_changed"}
        shared = {m for m in vars(base) if not m.startswith("__")}
        for cls in (screen, other):
            clashes = (shared & set(vars(cls))) - allowed
            self.assertEqual(set(), clashes,
                             "%s re-implements %s" % (cls.__name__, clashes))

    def test_the_controls_really_are_shared(self):
        """Names the ones that matter, so deleting one from the base and
        quietly restoring it in a subclass fails here."""
        base, _screen, _other = self._classes()
        for name in ("reconsider", "prefer_engine", "set_objective",
                     "set_budget", "set_level_7", "set_toon_count",
                     "set_max_fires", "set_max_unites", "set_max_sos",
                     "ask_now", "_describe_into", "_sync_explanation",
                     "_reject_key", "displayed_action"):
            self.assertIn(name, vars(base), name)

    def test_both_reconsider_controls_take_the_same_widths(self):
        import inspect

        from solver.live.panel import Api

        try:
            from solver.live.realms_panel import RealmsApi
        except Exception as exc:                   # pragma: no cover
            self.skipTest("second panel unavailable: %s" % exc)
        for api in (Api, RealmsApi):
            params = inspect.signature(api.reconsider).parameters
            self.assertIn("scope", params,
                          "%s.reconsider takes no scope" % api.__name__)


class SpentBudgetRunsDownTest(unittest.TestCase):
    """A pink slip advised and played is a pink slip gone.

    Reported from a live VP: the panel kept offering resources the run
    had already used, and there was no way to see how many were left --
    the boxes only ever showed what the player had typed in.
    """

    def _worker(self, **holdings):
        import threading

        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._lock = threading.Lock()
        w.model = Model()
        w._post = lambda: None
        w._rl_action = w._search_action = None
        w.max_fires = holdings.get("fires", 0)
        w.max_unites = holdings.get("unites", 0)
        w.max_sos = holdings.get("sos", 0)
        w.spent_fires = w.spent_unites = w.spent_sos = 0
        return w

    def test_a_fire_comes_off_the_count(self):
        from solver.state import Action

        w = self._worker(fires=5)
        self.assertEqual(5, w.remaining("fires"))
        w.note_spent(Action(track=None, target_index=0, fire=True))
        self.assertEqual(4, w.remaining("fires"))

    def test_an_sos_comes_off_its_own_count(self):
        from solver.state import Action

        w = self._worker(fires=5, sos=2)
        w.note_spent(Action(track=None, sos="Flippy"))
        self.assertEqual(1, w.remaining("sos"))
        self.assertEqual(5, w.remaining("fires"), "a card is not a slip")

    def test_a_unite_is_charged_alongside_the_gag(self):
        """A unite costs no action, so it is advised BESIDE a gag and
        has to be charged separately from it."""
        from solver.state import Action, Track

        w = self._worker(unites=8)
        w.note_spent(Action(track=Track.THROW, level=5, target_index=0),
                     unite="80 Toon-Up unite")
        self.assertEqual(7, w.remaining("unites"))

    def test_an_ordinary_gag_costs_none_of_them(self):
        from solver.state import Action, Track

        w = self._worker(fires=5, unites=8, sos=2)
        w.note_spent(Action(track=Track.DROP, level=6, target_index=0))
        self.assertEqual((5, 8, 2), (w.remaining("fires"),
                                     w.remaining("unites"),
                                     w.remaining("sos")))

    def test_it_never_goes_below_zero(self):
        from solver.state import Action

        w = self._worker(fires=1)
        for _ in range(4):
            w.note_spent(Action(track=None, target_index=0, fire=True))
        self.assertEqual(0, w.remaining("fires"))

    def test_correcting_the_box_forgets_what_we_thought_was_spent(self):
        """The player can see the pouch and the panel cannot, so their
        number wins outright."""
        from solver.state import Action

        w = self._worker(fires=5)
        w.ask_now = lambda: None
        w._settings_changed = lambda: None
        w.note_spent(Action(track=None, target_index=0, fire=True))
        w.set_max_fires(3)
        self.assertEqual(3, w.remaining("fires"))

    def test_a_new_fight_restores_everything(self):
        from solver.state import Action

        w = self._worker(fires=5, sos=2)
        w.note_spent(Action(track=None, sos="Flippy"))
        w.note_spent(Action(track=None, target_index=0, fire=True))
        w.reset_spending()
        self.assertEqual((5, 2), (w.remaining("fires"), w.remaining("sos")))

    def test_the_solver_is_given_what_is_left(self):
        """Not `max_fires`. The whole point: a spent slip must not be
        offered again."""
        import inspect

        from solver.live.overlay import Worker

        self.assertIn('fires=self.remaining("fires")',
                      inspect.getsource(Worker.run))


class InvasionReadsAsWordsTest(unittest.TestCase):
    """`Snapshot.invasion` is a `(cog, count, mega)` tuple.

    The panel rendered it with `str()`, which put a raw Python repr on
    screen over a live battle: `('Spin Doctors', 3000, False)`. The
    phrasing lives next to the field now, so the panel and
    `Snapshot.describe` cannot drift.
    """

    def _snapshot(self, invasion):
        import dataclasses

        from solver.live.ttr_local import Snapshot

        blank = {f.name: (None if f.default is dataclasses.MISSING
                          else f.default)
                 for f in dataclasses.fields(Snapshot)}
        return dataclasses.replace(Snapshot(**blank), invasion=invasion)

    def test_an_invasion_reads_as_a_sentence(self):
        self.assertEqual("Spin Doctors x3000",
                         self._snapshot(("Spin Doctors", 3000, False))
                         .invasion_text)

    def test_a_mega_says_so(self):
        self.assertEqual("Spin Doctors x3000 (MEGA)",
                         self._snapshot(("Spin Doctors", 3000, True))
                         .invasion_text)

    def test_no_invasion_is_empty_not_none(self):
        """The model's field is a string the page prints directly."""
        self.assertEqual("", self._snapshot(None).invasion_text)

    def test_the_panel_does_not_str_the_tuple(self):
        import inspect

        from solver.live.overlay import Worker

        src = inspect.getsource(Worker.run)
        self.assertIn("invasion_text", src)
        self.assertNotIn("str(invasion)", src)


class AStuckThinkingFlagUnblocksTest(unittest.TestCase):
    """`thinking` is cleared only by a search reporting back.

    A superseded search never reports -- `Thinker` drops the older
    result on purpose -- so a flag left raised would block every retry
    for the rest of the fight. The panel then sits on a stale problem
    while the readers are, by then, seeing the board perfectly well.
    """

    def _worker(self, thinking, since, now=1000.0):
        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w.model = Model()
        w.model.forced = True
        w.model.problems = ["no cog plates on screen"]
        w.model.thinking = thinking
        w.budget = 15.0
        w._last_try = 0.0
        w._thinking_since = since
        return w, now

    def test_a_search_still_inside_its_budget_blocks_the_retry(self):
        w, now = self._worker(True, since=995.0)      # 5s in
        self.assertFalse(w._should_retry(w.model, now))

    def test_one_far_past_its_budget_does_not(self):
        from solver.live.overlay import STUCK_SLACK

        w, now = self._worker(True, since=1000.0 - (15.0 + STUCK_SLACK + 1))
        self.assertTrue(w._should_retry(w.model, now))

    def test_the_slack_sits_outside_the_child_deadline(self):
        """`Thinker._run` gives the child `budget + 15`, so anything
        later is not a slow answer -- it is one that never arrives."""
        from solver.live.overlay import STUCK_SLACK

        self.assertGreater(STUCK_SLACK, 15.0)

    def test_a_worker_that_never_thought_is_not_called_stuck(self):
        w, now = self._worker(False, since=0.0)
        self.assertTrue(w._should_retry(w.model, now))
        w.model.problems = []
        self.assertFalse(w._should_retry(w.model, now))

    def test_the_clock_starts_only_on_the_rising_edge(self):
        """Re-submitting while already thinking must not push the
        deadline out for ever."""
        import inspect

        from solver.live.overlay import Worker

        src = inspect.getsource(Worker.run)
        self.assertIn("if not model.thinking:", src)
        self.assertLess(src.index("if not model.thinking:"),
                        src.index("model.thinking = True"))
