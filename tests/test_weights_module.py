"""`solver/search/weights.py` and the one way it can silently break.

The tunables moved out of `party_search.py` so the tuning surface is
visible whole. The hazard in doing that is exact: `from .weights import
FIRE_FLOOR` binds a COPY, so `weights.FIRE_FLOOR = x` would stop
reaching the reader -- silently, and only in the tests and sweeps that
patch it. Every read must be an attribute lookup.
"""
import pathlib
import random
import unittest

from solver.rl import env as env_mod, harness
from solver import simulator
from solver.search import party_search as ps, weights


class NoCopiedBindingsTest(unittest.TestCase):

    def test_party_search_never_imports_the_names(self):
        source = pathlib.Path("solver/search/party_search.py").read_text(
            encoding="utf-8")
        self.assertNotIn("from .weights import", source)
        self.assertNotIn("from solver.search.weights import", source)

    def test_the_module_is_imported_as_a_module(self):
        source = pathlib.Path("solver/search/party_search.py").read_text(
            encoding="utf-8")
        self.assertIn("from . import weights", source)


class PatchingReachesTheReaderTest(unittest.TestCase):
    """The contract `tests/test_fires.py` and `tools/fit_scorer.py` rely
    on. If these fail, patching has become a no-op and every sweep that
    uses it is silently measuring the shipped value."""

    def _board(self):
        def sampler(rng):
            state = env_mod.facility_position(rng)
            state.toons = [harness.solo_loadout(rng)]
            return state

        e = env_mod.BattleEnv(rng=random.Random(3), sampler=sampler,
                              coordinated=True)
        e.reset()
        return e.state

    def test_a_scalar_patch_reaches_it(self):
        original = weights.FIRE_FLOOR
        try:
            weights.FIRE_FLOOR = 999.0
            self.assertEqual(ps._fire_price(0, floor=True), 999.0)
        finally:
            weights.FIRE_FLOOR = original

    def test_REBINDING_the_weight_table_reaches_it(self):
        """`tools/fit_scorer.py` replaces the whole dict, not a key."""
        state = self._board()
        action = next(a for a in simulator.legal_actions(state)
                      if not a.is_pass)
        original = weights.QUICK_W
        normal = ps._quick_score(state, [action])
        try:
            weights.QUICK_W = {k: 0.0 for k in original}
            zeroed = ps._quick_score(state, [action])
        finally:
            weights.QUICK_W = original
        self.assertNotEqual(normal, zeroed)

    def test_mutating_a_single_weight_reaches_it(self):
        state = self._board()
        action = next(a for a in simulator.legal_actions(state)
                      if not a.is_pass)
        original = weights.QUICK_W["price"]
        try:
            weights.QUICK_W["price"] = 0.0
            cheap = ps._quick_score(state, [action])
            weights.QUICK_W["price"] = 1000.0
            dear = ps._quick_score(state, [action])
        finally:
            weights.QUICK_W["price"] = original
        self.assertGreater(cheap, dear)


class EverythingMovedTest(unittest.TestCase):

    def test_the_tunables_are_gone_from_party_search(self):
        """Anything left behind is a second home for a tuned number."""
        import re
        source = pathlib.Path("solver/search/party_search.py").read_text(
            encoding="utf-8")
        defined = set(re.findall(r"^([A-Z][A-Z0-9_]{2,}) *=", source,
                                 re.MULTILINE))
        self.assertEqual(defined, set(), "tunables still in party_search")

    def test_they_are_all_in_weights(self):
        for name in ("QUICK_W", "GREEDY_W", "FIRE_PRICE", "FIRE_FLOOR",
                     "SURVIVAL_CAP", "SCARCITY_UNITS", "MAX_PLANS",
                     "SAMPLES", "PER_TRACK", "ROLLOUT_ROUNDS"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(weights, name))


if __name__ == "__main__":
    unittest.main()
