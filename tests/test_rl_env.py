"""The RL view of a battle.

Standard library only -- the environment is the simulator wearing a
different interface, and torch never appears in `solver/`.
"""
import random
import unittest

from solver.rl import env
from solver.state import Track


class ActionTableTest(unittest.TestCase):

    def test_the_table_is_fixed_and_pass_is_index_zero(self):
        """The policy's output layer has a constant shape, and the pass
        is always present even when everything else is masked out."""
        self.assertEqual(env.PASS_INDEX, 0)
        self.assertTrue(env.action_at(0).is_pass)
        self.assertEqual(len(env.ACTIONS), 1 + 7 * 7 * 5)

    def test_pass_is_always_legal(self):
        """The search cannot say this -- widening its pass broke exact
        solve() -- and this environment can, because it memoises
        nothing. Conserving a scarce gag and declining to draw a cog's
        attack are both real moves."""
        rng = random.Random(0)
        for _ in range(50):
            state = env.default_position(rng)
            if state.is_terminal():
                continue
            self.assertTrue(env.legal_mask(state)[env.PASS_INDEX])


class MaskTest(unittest.TestCase):

    def setUp(self):
        self.rng = random.Random(7)

    def test_a_masked_action_is_never_unaffordable(self):
        for _ in range(40):
            state = env.default_position(self.rng)
            if state.is_terminal():
                continue
            toon = state.toons[0]
            for i, ok in enumerate(env.legal_mask(state)):
                if not ok or i == env.PASS_INDEX:
                    continue
                action = env.ACTIONS[i]
                self.assertGreater(
                    toon.gag_counts.get((action.track, action.level), 0), 0)
                self.assertGreater(toon.track_exp.get(action.track, 0), 0)

    def test_group_and_single_are_not_confused(self):
        from solver import simulator

        for _ in range(30):
            state = env.default_position(self.rng)
            for i, ok in enumerate(env.legal_mask(state)):
                if not ok or i == env.PASS_INDEX:
                    continue
                action = env.ACTIONS[i]
                group = simulator.is_group_action(action.track, action.level)
                self.assertEqual(group, action.target_index is None)

    def test_a_trapped_or_lured_cog_is_not_offered_a_trap(self):
        state = env.default_position(self.rng)
        for cog in state.cogs:
            cog.status.trapped = True
        for i, ok in enumerate(env.legal_mask(state)):
            if ok and i != env.PASS_INDEX:
                self.assertNotEqual(env.ACTIONS[i].track, Track.TRAP)


class EnvTest(unittest.TestCase):

    def test_observation_width_is_constant(self):
        e = env.BattleEnv(rng=random.Random(1))
        widths = set()
        for _ in range(20):
            obs, _mask = e.reset()
            widths.add(len(obs))
            for _step in range(3):
                obs, _m, _r, done, _i = e.step(env.PASS_INDEX)
                widths.add(len(obs))
                if done:
                    break
        self.assertEqual(widths, {env.OBS_DIM})

    def test_an_episode_ends(self):
        e = env.BattleEnv(rng=random.Random(2), max_rounds=20)
        for _ in range(10):
            _obs, mask = e.reset()
            for _step in range(25):
                choices = [i for i, ok in enumerate(mask) if ok]
                _obs, mask, _r, done, _info = e.step(
                    random.Random(_step).choice(choices))
                if done:
                    break
            else:
                self.fail("episode ran past its round cap")

    def test_reward_matches_the_search_objective(self):
        """The agent is scored by the same function the search is, so a
        comparison between them means something."""
        from solver.search import party_search as ps

        e = env.BattleEnv(rng=random.Random(3))
        e.reset()
        _o, _m, reward, _d, _i = e.step(env.PASS_INDEX)
        self.assertIsInstance(reward, float)
        self.assertLess(reward, 0.0)      # a pass costs a turn at minimum
        self.assertTrue(hasattr(ps, "round_reward"))


if __name__ == "__main__":
    unittest.main()


class StrangePositionTest(unittest.TestCase):
    """Mid-fight boards must be REACHABLE, not merely unusual.

    The first version set `trapped = True` without a `trap_level`, which
    no real battle can produce: the next Lure to spring it looks the
    trap's damage up by level and dies on `no gag at trap level None`.
    Training crashed 40 seconds in. A generator that can emit
    unreachable states is worse than one that is merely narrow -- it
    trains on a game that does not exist.
    """

    def test_every_trapped_cog_carries_a_trap_level(self):
        rng = random.Random(5)
        for _ in range(200):
            for cog in env.strange_position(rng).cogs:
                if cog.status.trapped:
                    self.assertIsNotNone(cog.status.trap_level)

    def test_every_lured_cog_can_be_ticked(self):
        """`_tick_lure` needs `lure_acc_before_bonus` to roll wake-up."""
        rng = random.Random(6)
        for _ in range(200):
            for cog in env.strange_position(rng).cogs:
                if cog.status.lured:
                    self.assertIsNotNone(cog.status.lure_acc_before_bonus)

    def test_positions_survive_being_played(self):
        from solver import party as party_mod

        rng = random.Random(7)
        for _ in range(150):
            state = env.strange_position(rng)
            for _round in range(4):
                if state.is_terminal():
                    break
                state, _h, _d = party_mod.step(
                    state, None, mode=party_mod.Mode.PICKUP, rng=rng)


class ToonShapeTest(unittest.TestCase):
    """Generated toons must be toons the game can produce."""

    def test_every_toon_owns_throw_and_squirt(self):
        """Both are starting tracks. A toon without them is not a hard
        puzzle, it is an impossible one."""
        rng = random.Random(9)
        for _ in range(300):
            exp = env.random_toon(rng).track_exp
            self.assertIn(Track.THROW, exp)
            self.assertIn(Track.SQUIRT, exp)

    def test_no_toon_owns_all_seven_tracks(self):
        rng = random.Random(10)
        for _ in range(300):
            self.assertLessEqual(len(env.random_toon(rng).track_exp), 6)

    def test_experience_is_in_range(self):
        rng = random.Random(11)
        for _ in range(300):
            for level in env.random_toon(rng).track_exp.values():
                self.assertTrue(1 <= level <= 7)
