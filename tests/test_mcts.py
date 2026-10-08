"""`search.mcts`: open-loop tree search over your own decisions."""
import random
import unittest

try:
    import numpy  # noqa: F401
    from solver.search import fastplayer, hybrid, mcts, playout
    HAVE = fastplayer.available() and hybrid.available()
except Exception:                       # pragma: no cover
    HAVE = False


def _board(toons=1, seed=1):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed)
    have = [t for t in Track if t is not Track.TOON_UP]
    party = [vp_mod.maxed_toon(rng, tracks=have, laff=120) for _ in range(toons)]
    maker = env_mod.BattleEnv(rng=random.Random(seed))
    return BattleState(toons=party, kind="vp",
                       cogs=[maker._sellbot_cog(rng, 8) for _ in range(4)])


@unittest.skipUnless(HAVE, "needs numpy and the shipped weights")
class PickTest(unittest.TestCase):

    def test_it_answers_with_a_move_from_the_menu(self):
        board = _board()
        result = mcts.pick(board, seed=2, iterations=24)
        keys = [playout._key(c) for c in result.candidates]
        self.assertIn(playout._key(result.plan), keys)
        self.assertEqual(24, result.rollouts)

    def test_the_same_seed_gives_the_same_answer(self):
        a = mcts.pick(_board(), seed=5, iterations=24)
        b = mcts.pick(_board(), seed=5, iterations=24)
        self.assertEqual(playout._key(a.plan), playout._key(b.plan))

    def test_it_searches_past_the_first_decision(self):
        mcts.pick(_board(), seed=3, iterations=48)
        self.assertGreater(mcts.depth_reached(mcts.LAST_ROOT), 1)

    def test_every_visit_is_counted_once_at_the_root(self):
        mcts.pick(_board(), seed=4, iterations=30)
        self.assertEqual(30, sum(mcts.LAST_ROOT.n))

    def test_a_party_goes_to_the_flat_playouts(self):
        result = mcts.pick(_board(toons=2), seed=1, iterations=8)
        self.assertIsNotNone(result)


class ChooseTest(unittest.TestCase):

    def test_an_untried_move_is_chosen_by_its_prior(self):
        node = mcts._Node(["a", "b", "c"], [0.1, 0.7, 0.2])
        self.assertEqual(1, node.choose(0.0, 1.0))

    def test_a_well_tried_good_move_beats_an_untried_weak_prior(self):
        node = mcts._Node(["a", "b"], [0.9, 0.1])
        node.n, node.w, node.visits = [20, 20], [2.0, 18.0], 40
        self.assertEqual(1, node.choose(0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
