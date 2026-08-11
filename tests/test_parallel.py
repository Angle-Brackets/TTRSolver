"""Parallel execution must change the runtime and nothing else.

The failure mode worth guarding against isn't a crash -- it's a parallel
run that quietly produces different numbers from the serial one, because
then every benchmark in the docs depends on how many cores happened to be
free. Seeds are the fight index, so results are worker-count independent
by construction; these tests hold that.

stdlib unittest only -- pytest is not installed.
"""
import unittest

from solver.search import parallel


class TestDeterminism(unittest.TestCase):
    def test_same_seed_gives_the_same_fight(self):
        a = parallel._play_one(("expectimax", 1, 7, "default"))
        b = parallel._play_one(("expectimax", 1, 7, "default"))
        self.assertEqual(a, b)

    def test_different_seeds_give_different_fights(self):
        results = {parallel._play_one(("random", 1, s, "default"))
                   for s in range(8)}
        self.assertGreater(len(results), 1, "every seed produced one outcome")

    def test_serial_and_parallel_agree(self):
        """The point of the whole exercise: more workers, same answer."""
        serial = parallel.play_many("expectimax", 4, 1, "default", workers=1)
        threaded = parallel.play_many("expectimax", 4, 1, "default", workers=2)
        self.assertEqual(serial, threaded)

    def test_results_are_ordered_by_seed(self):
        """pool.map preserves input order; a switch to imap_unordered would
        silently scramble which fight is which."""
        results = parallel.play_many("random", 6, 1, "default", workers=2)
        expected = [parallel._play_one(("random", 1, s, "default"))
                    for s in range(6)]
        self.assertEqual(results, expected)


class TestWorkerCount(unittest.TestCase):
    def test_default_is_at_least_one(self):
        self.assertGreaterEqual(parallel.default_workers(), 1)

    def test_tiny_batches_stay_in_process(self):
        """Spawning a pool costs about a second on Windows; two fights are
        not worth it."""
        self.assertEqual(len(parallel.play_many("random", 2, 1, "default")), 2)


if __name__ == "__main__":
    unittest.main()
