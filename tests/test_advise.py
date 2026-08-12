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

    def _run(self, token, frame, readings, snapshot, objective, depth):
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


class DepthTest(unittest.TestCase):

    def test_the_default_depth_is_the_one_that_finishes(self):
        """Depth 3 ran for minutes on a real endgame loadout; depth 2
        took 9.3s. The default has to be the one usable in a round."""
        self.assertEqual(A.DEFAULT_DEPTH, 2)

    def test_only_position_changing_events_trigger_a_search(self):
        self.assertIn("damage", A.RECOMPUTE_ON)
        self.assertIn("cog_defeated", A.RECOMPUTE_ON)
        self.assertNotIn("identified", A.RECOMPUTE_ON)
        self.assertNotIn("battle_ended", A.RECOMPUTE_ON)


if __name__ == "__main__":
    unittest.main()
