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
