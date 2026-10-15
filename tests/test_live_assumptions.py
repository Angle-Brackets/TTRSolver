"""The live panels advise on a Big Cheese instead of failing.

Glower Power has no published accuracy, so the tables keep it [TODO] and
the data layer raises. The simulated CEO fight already borrows one; the
live panels now do too (`cogs.live_play_assumptions`). Everything here
runs in fresh processes, so this test process keeps the [TODO] the data
tests rely on.
"""
import concurrent.futures
import pathlib
import subprocess
import sys
import unittest

from solver import outcomes
from solver.data import cogs as cogs_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LivePlayAssumptionsTest(unittest.TestCase):

    def test_a_worker_pool_can_compute_a_big_cheese(self):
        """The panels' engines run in spawned pools; the initializer is
        what gives those processes the borrow."""
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=1, initializer=cogs_mod.live_play_assumptions) as pool:
            result = pool.submit(outcomes._attack_outcomes,
                                 "bossbot", "the_big_cheese", 12).result(timeout=120)
        self.assertTrue(result)
        self.assertAlmostEqual(1.0, sum(p for p, *_ in result), places=6)

    def test_without_it_a_fresh_process_still_raises(self):
        code = ("from solver import outcomes\n"
                "try:\n"
                "    outcomes._attack_outcomes('bossbot', 'the_big_cheese', 12)\n"
                "    print('computed')\n"
                "except Exception as e:\n"
                "    print(e)\n")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        self.assertIn("glower_power", out.stdout, out.stderr)
        self.assertIn("TODO", out.stdout, out.stderr)

    def test_every_live_pool_is_built_with_it(self):
        """A pool built without the initializer would raise on a Big
        Cheese however the panel's own process was set up."""
        for path in ("solver/live/advise.py", "solver/live/realms_panel.py",
                     "solver/live/worker.py"):
            source = (ROOT / path).read_text(encoding="utf-8")
            pools = source.count("ProcessPoolExecutor(")
            self.assertEqual(pools, source.count("initializer=live_play_assumptions"),
                             path)


if __name__ == "__main__":
    unittest.main()
