"""`party.NetTeammate`: a teammate who plays for their own pouch and the board."""
import random
import unittest

try:
    import numpy  # noqa: F401
    from solver.search import fastplayer
    HAVE = fastplayer.available()
except Exception:                       # pragma: no cover
    HAVE = False


def _party(mate_gags):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState, ToonState

    rng = random.Random(3)
    me = vp_mod.maxed_toon(rng, tracks=[t for t in Track if t is not Track.TOON_UP],
                           laff=120)
    mate = ToonState(100, 100, {t: 7 for t, _l in mate_gags}, dict(mate_gags))
    maker = env_mod.BattleEnv(rng=random.Random(3))
    return BattleState(toons=[me, mate], kind="street",
                       cogs=[maker._sellbot_cog(rng, 6) for _ in range(3)])


@unittest.skipUnless(HAVE, "needs numpy and the fast network's weights")
class NetTeammateTest(unittest.TestCase):

    def test_a_distribution_that_sums_to_one(self):
        from solver import party
        from solver.data.types import Track

        dist = party.NetTeammate().distribution(
            _party({(Track.THROW, 5): 3, (Track.SQUIRT, 4): 5}), 1)
        self.assertAlmostEqual(1.0, sum(p for p, _a in dist))

    def test_it_throws_from_the_teammates_own_pouch(self):
        from solver import party
        from solver.data.types import Track

        dist = party.NetTeammate().distribution(_party({(Track.DROP, 5): 4}), 1)
        tracks = {a.track for _p, a in dist if a is not None and a.track is not None}
        self.assertEqual({Track.DROP}, tracks)

    def test_a_sad_teammate_sits_out(self):
        from solver import party
        from solver.data.types import Track

        board = _party({(Track.DROP, 5): 4})
        board.toons[1].laff = 0
        self.assertEqual([(1.0, None)], party.NetTeammate().distribution(board, 1))

    def test_temperature_flattens_the_spread(self):
        from solver import party
        from solver.data.types import Track

        board = _party({(Track.THROW, 5): 3, (Track.SQUIRT, 4): 5, (Track.DROP, 3): 4})
        sharp = max(p for p, _a in party.NetTeammate(temperature=1.0).distribution(board, 1))
        flat = max(p for p, _a in party.NetTeammate(temperature=4.0).distribution(board, 1))
        self.assertLessEqual(flat, sharp)


if __name__ == "__main__":
    unittest.main()
