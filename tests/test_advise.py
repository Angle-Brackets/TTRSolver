"""The advisory loop's threading, without running a search.

What matters here is that a nine-second think never blocks the poll that
notices a cog dying, and that an answer computed for a position the
battle has already left is discarded rather than printed.
"""
import threading
import time
import unittest

try:
    from solver.live import advise as A
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"advise needs numpy: {exc}") from None


class SlowThinker(A.Thinker):
    """A Thinker whose 'search' is a controllable sleep."""

    def __init__(self, on_result, delay):
        super().__init__(on_result)
        self.delay = delay
        self.started = threading.Event()

    def _run(self, token, frame, readings, snapshot, objective, depth,
             budget=None, ignore_checksum=False, allies=0,
             fires=0, reject=None, boss=None, unites=0):
        # The signature MIRRORS `Thinker._run` and has to keep doing so.
        # `submit` starts a thread with these as positional args, so an
        # arity that has drifted raises at call time -- outside `_run`'s
        # own try, which is the thing that would have reported it. The
        # thread dies silently and it looks exactly like a search that
        # never finished.
        self.started.set()
        time.sleep(self.delay)
        with self._lock:
            superseded = token != self._current
        if not superseded:
            self.on_result([f"answer for {frame}"], object())


class ThinkerTest(unittest.TestCase):

    def test_a_result_is_delivered(self):
        seen = []
        t = SlowThinker(lambda lines, state: seen.append(lines), 0.02)
        t.submit("frame-1", [], None, None, 1)
        time.sleep(0.25)
        self.assertEqual(len(seen), 1)

    def test_a_superseded_search_is_discarded(self):
        """If the battle moved on, the answer is for a fight that is no
        longer being played."""
        seen = []
        t = SlowThinker(lambda lines, state: seen.append(lines), 0.15)
        t.submit("stale", [], None, None, 1)
        t.started.wait(1.0)
        t.submit("fresh", [], None, None, 1)
        time.sleep(0.6)
        self.assertEqual(len(seen), 1)
        self.assertIn("fresh", seen[0][0])

    def test_submitting_does_not_block_the_caller(self):
        """The poll loop must keep its cadence while a search runs."""
        t = SlowThinker(lambda lines, state: None, 0.4)
        start = time.time()
        t.submit("frame", [], None, None, 1)
        self.assertLess(time.time() - start, 0.1)


class UnitesTest(unittest.TestCase):
    """The player's Unite count reaches the board the solver sees."""

    def test_the_count_lands_on_the_toon(self):
        from types import SimpleNamespace
        from solver.state import BattleState, ToonState

        res = SimpleNamespace(state=BattleState(toons=[ToonState(50, 50, {}, {})], cogs=[]))
        A._with_unites(res, 3)
        self.assertEqual(3, res.state.toons[0].unites_held)
        A._with_unites(res, -2)
        self.assertEqual(0, res.state.toons[0].unites_held)

    def test_no_board_is_left_alone(self):
        A._with_unites(None, 3)


class FirstAnswerAliasingTest(unittest.TestCase):
    """THE EXTRA BIRTHDAY CAKES. `climb` applies its unite to the board it
    is handed; handed the live board, a unite PPO merely considered healed
    the laff and restocked the pouch that the Search row then planned on."""

    def test_the_board_comes_back_untouched(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("the policy needs numpy")
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track

        toon = ToonState(12, 100, {Track.THROW: 7, Track.SQUIRT: 7, Track.LURE: 7},
                         {(Track.THROW, 5): 3, (Track.SQUIRT, 5): 3, (Track.LURE, 4): 2})
        toon.unites_held = 3
        hp = data.cog_max_hp(10)
        board = BattleState(toons=[toon], cogs=[
            CogState("mr_hollywood", "sellbot", 10, hp, hp) for _ in range(3)])
        before = (toon.laff, toon.unites_held, dict(toon.gag_counts), toon.unite_cooldown)
        _act, unite = A.first_answer(board)
        if not unite:
            self.skipTest("the policy chose no unite here; nothing to alias")
        t = board.toons[0]
        self.assertEqual(before, (t.laff, t.unites_held, dict(t.gag_counts), t.unite_cooldown))


class BudgetTest(unittest.TestCase):

    def test_latency_is_bounded_by_time_not_depth(self):
        """Cost depends on the position, not the depth number: at depth
        2 a two-cog fight takes 2.3s and a three-cog fight 28s. A fixed
        depth therefore either stalls on a crowded battle or wastes an
        easy one, so the depth is only a cap and a budget does the
        limiting."""
        self.assertGreater(A.DEFAULT_DEPTH, 2)
        self.assertGreater(A.DEFAULT_BUDGET, 0)

    def test_epsilon_is_the_value_checked_against_an_exact_search(self):
        """0.03 kept the same move on every position tried; 0.08 changed
        the three-cog answer."""
        self.assertEqual(A.DEFAULT_EPSILON, 0.03)

    def test_only_position_changing_events_trigger_a_search(self):
        self.assertIn("damage", A.RECOMPUTE_ON)
        self.assertIn("cog_defeated", A.RECOMPUTE_ON)
        self.assertNotIn("identified", A.RECOMPUTE_ON)
        self.assertNotIn("battle_ended", A.RECOMPUTE_ON)


if __name__ == "__main__":
    unittest.main()


class StartupApiTest(unittest.TestCase):
    """The panel connects to the Local API as it opens, and an unanswered
    consent prompt is never answered with a second one."""

    def setUp(self):
        self.saved = dict(A._SESSION)

    def tearDown(self):
        A._SESSION.clear()
        A._SESSION.update(self.saved)

    def test_a_pending_prompt_keeps_the_same_client(self):
        from solver.live.ttr_local import ConsentRequired

        class Pending:
            def snapshot(self):
                raise ConsentRequired("prompt still up")
        client = Pending()
        A._SESSION.update(client=client, snapshot=None, taken=0.0, tried=0.0)
        found = []
        import solver.live.ttr_local as T
        saved_discover = T.discover
        T.discover = lambda *a, **k: found.append(1) or []
        try:
            self.assertIsNone(A._snapshot())
            self.assertIsNone(A._snapshot(force=True))
        finally:
            T.discover = saved_discover
        self.assertIs(client, A._SESSION["client"], "kept, so no new prompt")
        self.assertEqual([], found, "no rediscovery while the prompt is up")

    def test_the_panel_connects_as_it_opens(self):
        import threading
        import time as _time
        from solver.live.overlay import Worker

        w = Worker.__new__(Worker)
        w._stop = threading.Event()
        calls = []
        saved = A._snapshot
        A._snapshot = lambda *a, **k: calls.append(1)
        try:
            w._keep_api_fresh()
            deadline = _time.time() + 2
            while not calls and _time.time() < deadline:
                _time.sleep(0.02)
        finally:
            w._stop.set()
            A._snapshot = saved
        self.assertTrue(calls, "asked straight away, not at the first battle")


class SteadySearchTest(unittest.TestCase):
    """Seen live: the gag menu dropped out of the reader's view every few
    seconds, each dropout restarted the 12-15 s search, and the Search row
    never finished. The same board must keep its search; an unreadable
    frame is not news; only a new board supersedes."""

    def setUp(self):
        import concurrent.futures
        import threading
        from types import SimpleNamespace
        from solver.state import BattleState, CogState, ToonState, Track

        self.saved = {k: getattr(A, k) for k in
                      ("_snapshot", "_panel", "_panel_with_training", "build_state",
                       "_pool", "_kill_pool")}
        self.searches, self.kills, self.posts = [], [], []
        self.board = {"hp": 20, "readable": True}

        def build_state(**_k):
            if not self.board["readable"]:
                return SimpleNamespace(state=None, problems=["gag menu not visible"])
            toon = ToonState(50, 50, {Track.THROW: 7}, {(Track.THROW, 4): 3})
            cog = CogState("flunky", "bossbot", 3, self.board["hp"], 20)
            return SimpleNamespace(state=BattleState(toons=[toon], cogs=[cog]), problems=[])

        test = self

        class Pool:
            def submit(self, fn, state, *args):
                future = concurrent.futures.Future()
                test.searches.append(future)
                return future

        A._snapshot = lambda *a, **k: object()
        A._panel = lambda frame: object()
        A._panel_with_training = lambda frame, snap: object()
        A.build_state = build_state
        A._pool = lambda: Pool()
        A._kill_pool = lambda: self.kills.append(1)
        self.thinker = A.Thinker(lambda lines, state, action, unite:
                                 self.posts.append((lines, action)))
        self.threading = threading

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(A, k, v)

    def _submit(self, changed=False):
        self.thinker.submit(None, [], None, None, 2, budget=1.0, changed=changed)
        self._settle()

    def _settle(self):
        import time
        time.sleep(0.15)

    def _finish(self, i=-1, action="pie"):
        self.searches[i].set_result((["Whole Fruit Pie"], None, action, None))
        self._settle()

    def test_the_same_board_keeps_its_search(self):
        self._submit()
        self._submit()
        self._submit(changed=True)
        self.assertEqual(1, len(self.searches), "no restart for the same board")
        self._finish()
        self.assertEqual([(["Whole Fruit Pie"], "pie")], self.posts)

    def test_an_unreadable_frame_does_not_cancel_it(self):
        self._submit()
        self.board["readable"] = False
        self._submit()
        self._submit()
        self.assertEqual([], self.posts, "the menu flickering out is not news")
        self._finish()
        self.assertEqual("pie", self.posts[-1][1])

    def test_a_new_board_supersedes_and_stops_the_old_search(self):
        self._submit()
        self.board["hp"] = 9
        self._submit(changed=True)
        self.assertEqual(2, len(self.searches))
        self.assertEqual([1], self.kills, "the abandoned search is stopped")
        self._finish(0, "stale")
        self._finish(1, "fresh")
        self.assertEqual(["fresh"], [a for _l, a in self.posts])

    def test_an_answer_stands_until_a_battle_event_questions_it(self):
        self._submit()
        self._finish()
        self.board["readable"] = False
        self._submit()
        self.assertEqual(1, len(self.posts), "kept: nothing happened in the fight")
        self._submit(changed=True)
        self.assertEqual(["gag menu not visible"], self.posts[-1][0],
                         "after an event, an unreadable board is said")
