"""`search.valuenet`: a learned leaf for the exact search."""
import json
import os
import random
import tempfile
import unittest

try:
    import numpy  # noqa: F401
    from solver.search import fastplayer
    HAVE = fastplayer.available()
except Exception:                       # pragma: no cover
    HAVE = False


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
    board = [maker._sellbot_cog(rng, 6) for _ in range(cogs)]
    return BattleState(toons=[toon], cogs=board, kind="street")


def _weights(bias):
    """A tiny network whose output is `bias` (scaled) whatever the input."""
    n_in = len(fastplayer.features_dim_probe())
    payload = {"layers": [[[[0.0] * 4] * n_in, [0.0] * 4],
                          [[[0.0]] * 4, [bias]]], "scale": 100.0}
    path = os.path.join(tempfile.mkdtemp(), "v.json")
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return path


@unittest.skipUnless(HAVE, "needs numpy and the fast network's weights")
class ValueNetTest(unittest.TestCase):

    def tearDown(self):
        from solver.search import valuenet

        valuenet.USE = False
        valuenet._MODEL = valuenet._PATH = None
        valuenet._CACHE.clear()

    def test_off_by_default(self):
        from solver.search import expectimax, fitted, valuenet

        self.assertFalse(valuenet.USE)
        board = _board()
        if fitted.is_fitted():
            self.assertEqual(fitted.value(board), expectimax.heuristic_value(board))

    def test_on_it_is_the_leaf_and_stays_inside_the_clamp(self):
        from solver.search import expectimax, valuenet

        self.assertTrue(valuenet.use(_weights(5.0)))          # 500 before the clamp
        valuenet.USE = True
        board = _board()
        self.assertEqual(100.0, expectimax.heuristic_value(board))
        valuenet._PATH = None
        valuenet.use(_weights(-50.0))                       # -5000 before the clamp
        self.assertEqual(valuenet.value_floor(board), expectimax.heuristic_value(board))
        self.assertEqual(valuenet.value_floor(board), expectimax.heuristic_floor(board))

    def test_terminal_boards_are_known_not_estimated(self):
        from solver.search import valuenet

        valuenet.use(_weights(0.5))
        valuenet.USE = True
        board = _board(1)
        board.cogs[0].hp = 0
        board.cogs[0].status.is_dead = True
        self.assertEqual(100.0, valuenet.value(board))

    def test_pruned_search_matches_exhaustive_with_the_net_at_the_leaves(self):
        from solver.search import expectimax, objective, valuenet

        valuenet.use(_weights(0.7))
        valuenet.USE = True
        for seed in range(3):
            board = _board(2, seed)
            exact = expectimax.evaluate(board.clone(), 2, objective.BALANCED, prune=False)
            pruned = expectimax.evaluate(board.clone(), 2, objective.BALANCED)
            self.assertAlmostEqual(exact[0], pruned[0], places=9)
            self.assertEqual(exact[1], pruned[1])


if __name__ == "__main__":
    unittest.main()
