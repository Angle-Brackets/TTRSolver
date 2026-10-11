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


@unittest.skipUnless(HAVE, "needs numpy and the shipped weights")
class UniteHeadTest(unittest.TestCase):
    """The network sees every unite; the loadout decides what it may use."""

    def tearDown(self):
        fastplayer._MODEL = fastplayer._UNITE = fastplayer._PATH = None

    def test_every_unite_option_has_a_slot_and_back(self):
        from solver import unites as unites_mod

        toon = _board().toons[0]
        toon.laff, toon.unites_held = 20, 3
        for choice in unites_mod.candidates(toon):
            slot = fastplayer._slot_of(toon, choice)
            self.assertGreater(slot, 0, choice)
            self.assertEqual(choice, fastplayer._choice_of(toon, slot))

    def test_none_held_or_cooling_down_masks_every_unite(self):
        board = _board()
        board.toons[0].laff = 20
        self.assertEqual([True] + [False] * (len(fastplayer.unite_slots()) - 1),
                         fastplayer.unite_mask(board))
        board.toons[0].unites_held, board.toons[0].unite_cooldown = 3, 2
        self.assertFalse(any(fastplayer.unite_mask(board)[1:]))
        board.toons[0].unite_cooldown = 0
        self.assertTrue(any(fastplayer.unite_mask(board)[1:]))

    def test_it_sees_unites_held_and_the_cooldown(self):
        board = _board()
        before, _ = fastplayer.features(board)
        board.toons[0].unites_held, board.toons[0].unite_cooldown = 5, 3
        after, _ = fastplayer.features(board)
        self.assertEqual([1.0, 1.0], after[-2:])
        self.assertEqual([0.0, 0.0], before[-2:])

    def _weights(self, unite_slot=None):
        n_in, n_out = len(fastplayer.features_dim_probe()), fastplayer.n_outputs()
        payload = {"layers": [[[[0.0] * 4] * n_in, [0.0] * 4],
                              [[[0.0] * n_out] * 4, [0.0] * n_out]]}
        if unite_slot is not None:
            bias = [0.0] * len(fastplayer.unite_slots())
            bias[unite_slot] = 5.0
            payload["unite"] = [[[0.0] * len(bias)] * 4, bias]
        path = os.path.join(tempfile.mkdtemp(), "w.json")
        with open(path, "w") as fh:
            json.dump(payload, fh)
        return path

    def test_a_chosen_unite_rides_on_the_plan_and_spares_the_board(self):
        board = _board()
        toon = board.toons[0]
        toon.laff, toon.unites_held = 20, 2
        slot = fastplayer._slot_of(toon, ("toon_up", 80))
        self.assertTrue(fastplayer.use(self._weights(slot)))
        plan = fastplayer.act(board)
        self.assertEqual(("toon_up", 80), playout.unite_of(plan))
        self.assertEqual(20, toon.laff)
        self.assertEqual(2, toon.unites_held)

    def test_it_never_picks_a_unite_it_does_not_hold(self):
        board = _board()
        board.toons[0].laff = 20
        slot = fastplayer._slot_of(board.toons[0], ("toon_up", 80))
        self.assertTrue(fastplayer.use(self._weights(slot)))
        self.assertIsNone(playout.unite_of(fastplayer.act(board)))

    def test_weights_from_before_unites_still_load_and_never_unite(self):
        n_in = len(fastplayer.features_dim_probe()) - 2
        n_out = fastplayer.n_outputs()
        payload = {"layers": [[[[0.0] * 4] * n_in, [0.0] * 4],
                              [[[0.0] * n_out] * 4, [0.0] * n_out]]}
        path = os.path.join(tempfile.mkdtemp(), "old.json")
        with open(path, "w") as fh:
            json.dump(payload, fh)
        self.assertTrue(fastplayer.use(path))
        board = _board()
        board.toons[0].laff, board.toons[0].unites_held = 20, 2
        self.assertIsNone(playout.unite_of(fastplayer.act(board)))


@unittest.skipUnless(HAVE, "needs numpy and the shipped weights")
class HorizonInputsTest(unittest.TestCase):
    """Expert iteration's student sees what is still to come -- cogs
    waiting, later waves, SOS calls left -- which the board does not show.
    Weights decide: three more inputs than the board means they take it."""

    def tearDown(self):
        fastplayer.use(fastplayer.DEFAULT_WEIGHTS)

    def _weights(self, extra):
        n_in = len(fastplayer.features_dim_probe()) + extra
        n_out = fastplayer.n_outputs()
        payload = {"layers": [[[[0.0] * 4] * n_in, [0.0] * 4],
                              [[[0.0] * n_out] * 4, [0.0] * n_out]]}
        path = os.path.join(tempfile.mkdtemp(), f"w{extra}.json")
        with open(path, "w") as fh:
            json.dump(payload, fh)
        return path

    def test_the_horizon_values(self):
        board = _board()
        board.cogs_remaining = 20
        board.toons[0].sos_calls = 3
        self.assertEqual([0.6, 0.5, 0.6], [round(v, 2) for v in fastplayer.horizon(board, holdout=12)])

    def test_weights_that_take_it_get_it(self):
        self.assertTrue(fastplayer.use(self._weights(fastplayer.HORIZON_DIM)))
        self.assertTrue(fastplayer._HORIZON)
        seen = []
        real = fastplayer.features

        def spy(state, holdout=None, with_horizon=False):
            seen.append((holdout, with_horizon))
            return real(state, holdout, with_horizon)
        fastplayer.features = spy
        try:
            fastplayer.act(_board(), holdout=9)
        finally:
            fastplayer.features = real
        self.assertIn((9, True), seen, "the real waiting count reached the inputs")

    def test_old_weights_do_not(self):
        self.assertTrue(fastplayer.use(self._weights(0)))
        self.assertFalse(fastplayer._HORIZON)
        self.assertEqual(len(fastplayer.features_dim_probe()),
                         len(fastplayer.features(_board())[0]),
                         "the value net reads this width too")
