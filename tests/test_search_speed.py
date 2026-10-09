"""Speedups to the exact search: what they may and may not change."""
import random
import unittest

from solver.search import expectimax, features, objective


def _board(cogs=2, seed=1):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed)
    toon = vp_mod.maxed_toon(rng, tracks=[t for t in Track if t is not Track.TOON_UP],
                             laff=120)
    vp_mod.owner_vp_pouch(toon)
    maker = env_mod.BattleEnv(rng=random.Random(seed))
    board = [maker._sellbot_cog(rng, 7) for _ in range(cogs)]
    for cog in board:
        cog.hp = max(1, cog.hp // 2)
    return BattleState(toons=[toon], cogs=board, kind="street")


class BeamTest(unittest.TestCase):

    def tearDown(self):
        expectimax.BEAM = None

    def test_off_by_default(self):
        self.assertIsNone(expectimax.BEAM)

    def test_a_direct_evaluate_is_never_trimmed(self):
        exact = expectimax.evaluate(_board(1), 2, objective.BALANCED)
        expectimax.BEAM = 1
        self.assertEqual(exact, expectimax.evaluate(_board(1), 2, objective.BALANCED))

    def test_the_root_keeps_every_move(self):
        """Trimming happens below the root, so the move chosen at depth 2
        (where every child is a leaf) cannot change."""
        exact = expectimax.best_action_iterative(_board(2), depth=2,
                                                 objective=objective.BALANCED)
        expectimax.BEAM = 1
        trimmed = expectimax.best_action_iterative(_board(2), depth=2,
                                                   objective=objective.BALANCED)
        self.assertEqual(exact, trimmed)

    def test_trimmed_and_exact_results_never_share_a_memo_entry(self):
        memo = {}
        expectimax.best_action_iterative(_board(1), depth=3,
                                         objective=objective.BALANCED, memo=memo)
        before = {k for k in memo if isinstance(k[0], tuple)}
        expectimax.BEAM = 2
        expectimax.best_action_iterative(_board(1), depth=3,
                                         objective=objective.BALANCED, memo=memo)
        trimmed = {k for k in memo if isinstance(k[0], tuple)} - before
        self.assertTrue(trimmed)
        self.assertTrue(all(k[-1] == 2 for k in trimmed))


class KeptMemoTest(unittest.TestCase):

    def test_a_kept_memo_gives_the_same_answer(self):
        memo = {}
        first = expectimax.best_action_iterative(_board(2), depth=2,
                                                 objective=objective.BALANCED, memo=memo)
        again = expectimax.best_action_iterative(_board(2), depth=2,
                                                 objective=objective.BALANCED, memo=memo)
        self.assertEqual(first, again)

    def test_a_new_objective_wipes_it(self):
        memo = {}
        expectimax.best_action_iterative(_board(1), depth=2,
                                         objective=objective.BALANCED, memo=memo)
        size = len(memo)
        expectimax.best_action_iterative(_board(1), depth=1,
                                         objective=objective.SURVIVE, memo=memo)
        self.assertLess(len(memo), size)
        self.assertIn(("__objective__", repr(objective.SURVIVE)), memo)


class PouchCacheTest(unittest.TestCase):

    def test_cached_and_fresh_features_agree(self):
        board = _board(3, seed=4)
        features._POUCH_CACHE.clear()
        fresh = features.extract(board)
        cached = features.extract(board)
        self.assertEqual(fresh, cached)

    def test_a_spent_gag_is_a_different_entry(self):
        board = _board(2, seed=4)
        features._POUCH_CACHE.clear()
        before = features._damage_budget(board)
        key = next(iter(board.toon.gag_counts))
        board.toon.gag_counts = dict(board.toon.gag_counts)
        board.toon.gag_counts[key] = 0
        self.assertLessEqual(features._damage_budget(board), before)


if __name__ == "__main__":
    unittest.main()
