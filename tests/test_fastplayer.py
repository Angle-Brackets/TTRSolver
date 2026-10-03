"""The fast rollout player: its move space, its inputs, its fallback."""
import json
import os
import random
import tempfile
import unittest

try:
    import numpy  # noqa: F401
    from solver.search import fastplayer, playout
    HAVE = fastplayer.available()
except Exception:                       # pragma: no cover
    HAVE = False


def _board(cogs=3, seed=1):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed)
    toon = vp_mod.maxed_toon(rng, tracks=[t for t in Track if t is not Track.TOON_UP],
                             laff=140)
    toon.sos_cards = {"Flippy": 1}
    maker = env_mod.BattleEnv(rng=random.Random(seed))
    return BattleState(toons=[toon], kind="vp",
                       cogs=[maker._sellbot_cog(rng, 6) for _ in range(cogs)])


@unittest.skipUnless(HAVE, "needs numpy and the shipped weights")
class MoveSpaceTest(unittest.TestCase):

    def test_every_output_maps_back_to_itself(self):
        for i in range(fastplayer.n_outputs()):
            self.assertEqual(i, fastplayer.index_of(fastplayer.action_of(i)), i)

    def test_sos_cards_have_their_own_outputs(self):
        from solver.state import Action
        i = fastplayer.index_of(Action(track=None, sos="Flippy"))
        self.assertGreaterEqual(i, 250)

    def test_inputs_and_mask_have_the_trained_widths(self):
        x, mask = fastplayer.features(_board())
        self.assertEqual(len(fastplayer.features_dim_probe()), len(x))
        self.assertEqual(fastplayer.n_outputs(), len(mask))

    def test_only_held_cards_are_legal(self):
        _x, mask = fastplayer.features(_board())
        names = fastplayer.sos_names()
        held = [n for n, ok in zip(names, mask[250:]) if ok]
        self.assertEqual(["Flippy"], held)


@unittest.skipUnless(HAVE, "needs numpy and the shipped weights")
class PlayTest(unittest.TestCase):

    def test_it_always_picks_a_legal_move(self):
        for seed in range(5):
            board = _board(seed=seed)
            _x, mask = fastplayer.features(board)
            move = fastplayer.act(board)[0]
            self.assertTrue(mask[fastplayer.index_of(move)])

    def test_bad_weights_are_refused_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w") as f:
                json.dump({"layers": [[[[0.0]], [0.0]]]}, f)
            self.assertFalse(fastplayer.use(path))
        self.assertTrue(fastplayer.use(fastplayer.DEFAULT_WEIGHTS))

    def test_without_weights_playouts_fall_back_to_climb(self):
        """A rollout must still run when the net is missing."""
        old = playout.ROLLOUT_PLAYER
        try:
            playout.ROLLOUT_PLAYER = "net"
            fastplayer.use("does-not-exist.json")
            got = playout.rollout(_board(cogs=2), [None], None, seed=1)
            self.assertTrue(0 <= got <= 2 + playout.LAFF_WEIGHT)
        finally:
            fastplayer.use(fastplayer.DEFAULT_WEIGHTS)
            playout.ROLLOUT_PLAYER = old


if __name__ == "__main__":
    unittest.main()
