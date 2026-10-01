"""Judging by playing it out: the horizon, the drawn fight, the pick.

The rule these pin hardest is NO PEEKING: a playout may know how many
cogs are coming and from which level band, never which cogs.
"""
import random
import time
import unittest

from solver.live.boss import BossTracker

try:
    from solver.search import hybrid, playout
    HAVE = hybrid.available()
except Exception:                       # pragma: no cover
    HAVE = False


def _board(cogs=2, laff=140, seed=1):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed)
    have = [t for t in Track if t is not Track.TOON_UP]
    toon = vp_mod.maxed_toon(rng, tracks=have, laff=laff)
    env = env_mod.BattleEnv(rng=random.Random(seed))
    return BattleState(toons=[toon],
                       cogs=[env._sellbot_cog(rng, 4) for _ in range(cogs)],
                       kind="vp")


class HorizonTest(unittest.TestCase):

    def test_the_cog_round_knows_what_is_still_walking_in(self):
        hz = BossTracker(kind="vp").horizon(on_field=4)
        self.assertEqual(16, hz.holdout)
        self.assertEqual((1, 12), hz.band)
        self.assertEqual(((20, (8, 12)),), hz.later)
        self.assertEqual("sellbot", hz.department)

    def test_the_count_moves_with_defeats(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(10)
        self.assertEqual(6, tracker.horizon(on_field=4).holdout)

    def test_the_skelecog_round_has_nothing_after_it(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(25)
        hz = tracker.horizon(on_field=4)
        self.assertEqual(11, hz.holdout)
        self.assertEqual((8, 12), hz.band)
        self.assertEqual((), hz.later)

    def test_the_ceo_horizon_stops_at_the_unknown_battle(self):
        hz = BossTracker(kind="ceo").horizon(on_field=4)
        self.assertEqual("bossbot", hz.department)
        self.assertEqual((), hz.later)

    def test_unconfirmed_fights_have_no_horizon(self):
        self.assertIsNone(BossTracker(kind="cfo").horizon())
        self.assertIsNone(BossTracker(kind="cj").horizon())
        self.assertIsNone(BossTracker().horizon())
        self.assertIsNone(BossTracker(kind="vp", party_size=2).horizon())


@unittest.skipUnless(HAVE, "the policy needs numpy")
class BuildTest(unittest.TestCase):

    def test_without_a_horizon_the_battle_on_screen_is_all_there_is(self):
        env = playout.build_env(_board(), None, random.Random(0))
        self.assertEqual([], env.state.holdout)
        self.assertEqual(0, env.state.cogs_remaining)
        self.assertIsNone(env.plan)
        self.assertEqual("vp", env.state.kind)

    def test_unseen_cogs_are_drawn_in_the_right_numbers_and_band(self):
        hz = BossTracker(kind="vp").horizon(on_field=2)
        env = playout.build_env(_board(), hz, random.Random(0))
        self.assertEqual(18, len(env.state.holdout))
        self.assertEqual(20, env.state.cogs_remaining)
        for cog in env.state.holdout:
            self.assertTrue(1 <= cog.level <= 12)
            self.assertEqual("sellbot", cog.department)
        for cog in env.plan.floors[0]:
            self.assertTrue(8 <= cog.level <= 12)

    def test_a_real_holdout_on_the_board_is_never_used(self):
        """The simulator's own state carries the true cogs. A playout
        that read them would be advice no player could compute."""
        from solver.rl import env as env_mod

        board = _board()
        maker = env_mod.BattleEnv(rng=random.Random(9))
        board.holdout = [maker._sellbot_cog(random.Random(9), 12)
                         for _ in range(3)]
        env = playout.build_env(board, None, random.Random(0))
        self.assertEqual([], env.state.holdout)
        hz = BossTracker(kind="vp").horizon(on_field=2)
        drawn = [playout.build_env(board, hz, random.Random(s)).state.holdout
                 for s in (1, 2)]
        self.assertNotEqual([(c.cog_type, c.level) for c in drawn[0]],
                            [(c.cog_type, c.level) for c in drawn[1]])

    def test_the_live_board_is_not_touched(self):
        board = _board()
        before = [(c.hp, c.status.lured) for c in board.cogs]
        playout.rollout(board, [None], None, seed=3)
        self.assertEqual(before, [(c.hp, c.status.lured) for c in board.cogs])


@unittest.skipUnless(HAVE, "the policy needs numpy")
class PickTest(unittest.TestCase):

    def test_a_party_is_left_to_the_caller(self):
        board = _board()
        board.toons.append(board.toons[0].clone()
                           if hasattr(board.toons[0], "clone")
                           else board.clone().toons[0])
        self.assertIsNone(playout.pick(board, None, rollouts=2))

    def test_the_scorers_pick_is_tried_first(self):
        board = _board()
        res = playout.pick(board, None, seed=1, rollouts=2)
        self.assertEqual(playout._key(res.candidates[0]),
                         playout._key(playout.candidates(board)[0]))
        self.assertIn(playout._key(res.plan),
                      [playout._key(c) for c in res.candidates])

    def test_same_seed_same_answer(self):
        board = _board()
        a = playout.pick(board, None, seed=4, rollouts=2)
        b = playout.pick(board, None, seed=4, rollouts=2)
        self.assertEqual(playout._key(a.plan), playout._key(b.plan))
        self.assertEqual(a.means, b.means)

    def test_a_deadline_still_leaves_a_minimum(self):
        res = playout.pick(_board(), None, seed=1, rollouts=50,
                           deadline=time.monotonic())
        self.assertEqual(playout.MIN_ROLLOUTS, res.rollouts)

    def test_a_rollout_counts_only_what_could_be_defeated(self):
        board = _board(cogs=2)
        got = playout.rollout(board, [None], None, seed=2)
        self.assertTrue(0 <= got <= 2)


if __name__ == "__main__":
    unittest.main()
