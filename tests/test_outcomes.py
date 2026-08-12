"""
Tests for the exact outcome distributions in solver/outcomes.py.

The important one here is test_matches_sampled_step: outcomes.py and
simulator.py currently implement the round rules twice (see outcomes.py's
module docstring), so this compares the enumerated distribution against
what step() actually samples. If the two implementations drift apart, that
test is what catches it.

stdlib unittest only -- pytest is not installed.
"""
import random
import unittest
from collections import Counter

from solver import outcomes, simulator
from solver.state import Track, Action, CogState, ToonState, BattleState
from solver.testing import two_flunky_fight

TOLERANCE = 1e-9


def single_flunky_fight(level=2, laff=50):
    """One toon, one cog -- small enough to enumerate by hand."""
    from solver import data
    toon = ToonState(
        laff=laff, max_laff=50,
        track_exp={Track.THROW: 7, Track.LURE: 7},
        gag_counts={(Track.THROW, 3): 5, (Track.LURE, 2): 3},
    )
    cog = CogState(cog_type="flunky", department="bossbot", level=level,
                   hp=data.cog_max_hp(level), max_hp=data.cog_max_hp(level))
    return BattleState(toon=toon, cogs=[cog])


class TestDistributionsAreProper(unittest.TestCase):
    def test_cog_damage_distribution_sums_to_one(self):
        state = single_flunky_fight()
        dist = outcomes.cog_damage_distribution(state.cogs[0])
        self.assertAlmostEqual(sum(dist.values()), 1.0, delta=TOLERANCE)

    def test_cog_phase_outcomes_sum_to_one(self):
        state = two_flunky_fight()
        branches = outcomes.cog_phase_outcomes(state)
        self.assertAlmostEqual(sum(p for p, _d, _e, _h in branches), 1.0,
                               delta=TOLERANCE)

    def test_action_outcomes_sum_to_one(self):
        state = two_flunky_fight()
        action = Action(track=Track.THROW, level=3, target_index=0)
        branches = outcomes.action_outcomes(state, action)
        self.assertAlmostEqual(sum(p for p, _s, _r in branches), 1.0,
                               delta=TOLERANCE)

    def test_no_zero_probability_branches(self):
        state = two_flunky_fight()
        action = Action(track=Track.THROW, level=3, target_index=0)
        branches = outcomes.action_outcomes(state, action)
        self.assertTrue(all(p > 0 for p, _s, _r in branches))

    def test_missing_cell_raises_as_a_data_gap(self):
        """A single TODO cell inside an otherwise-populated table must
        surface as a data gap, not a TypeError from the arithmetic and not
        a silently-dropped branch.

        bossbot/the_big_cheese/glower_power accuracy is the live example:
        no cog accuracy is published anywhere, and the guide's row for this
        attack was three superimposed unused attacks rather than one."""
        from solver import data
        cog = CogState(cog_type="the_big_cheese", department="bossbot",
                       level=11, hp=10, max_hp=10)
        self.assertIsNone(
            data.cog("bossbot", "the_big_cheese").attack("glower_power").accuracy[0],
            "test premise changed: glower_power accuracy is no longer TODO")
        with self.assertRaises(NotImplementedError):
            outcomes.cog_damage_distribution(cog)


class TestMatchesSampledStep(unittest.TestCase):
    """outcomes.action_outcomes must describe exactly what simulator.step
    samples."""

    def _empirical(self, state, action, trials, seed=1234):
        random.seed(seed)
        counts = Counter()
        rewards = {}
        for _ in range(trials):
            next_state, reward, _done = simulator.step(state, action)
            key = outcomes.state_key(next_state)
            counts[key] += 1
            rewards[key] = reward
        return counts, rewards

    def test_matches_sampled_step(self):
        state = single_flunky_fight()
        action = Action(track=Track.THROW, level=3, target_index=0)
        trials = 8000

        exact = {outcomes.state_key(s): (p, r)
                 for p, s, r in outcomes.action_outcomes(state, action)}
        counts, sampled_rewards = self._empirical(state, action, trials)

        self.assertEqual(set(counts) - set(exact), set(),
                         "step() reached a state the enumeration missed")

        for key, (prob, reward) in exact.items():
            empirical = counts[key] / trials
            self.assertAlmostEqual(
                empirical, prob, delta=0.03,
                msg=f"probability mismatch for {key}: "
                    f"enumerated {prob:.3f}, sampled {empirical:.3f}")
            if key in sampled_rewards:
                self.assertAlmostEqual(reward, sampled_rewards[key], delta=1e-9,
                                       msg=f"reward mismatch for {key}")


class TestStateKey(unittest.TestCase):
    def test_ignores_round_number(self):
        a = two_flunky_fight()
        b = two_flunky_fight()
        b.round_num = 7
        self.assertEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_distinguishes_hp(self):
        a = two_flunky_fight()
        b = two_flunky_fight()
        b.cogs[0].hp -= 1
        self.assertNotEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_ignores_exhausted_gags(self):
        a = two_flunky_fight()
        b = two_flunky_fight()
        b.toon.gag_counts[(Track.DROP, 1)] = 0
        self.assertEqual(outcomes.state_key(a), outcomes.state_key(b))


if __name__ == "__main__":
    unittest.main()


from solver import data  # noqa: E402  (used by the tests below)


class CollapseDamageTest(unittest.TestCase):
    """Merging outcomes that differ only in the damage number.

    The cog phase carries no decision -- cogs cannot kill each other or
    change what gags remain -- so branches sharing a cog configuration
    can be averaged. What must NOT be averaged is anything the next
    choice depends on.
    """

    def position(self):
        from solver.state import BattleState, CogState, ToonState, Track
        toon = ToonState(50, 50, {Track.THROW: 5},
                         {(Track.THROW, 3): 3, (Track.THROW, 4): 2})
        cogs = [CogState("flunky", "bossbot", 3, data.cog_max_hp(3),
                         data.cog_max_hp(3)),
                CogState("flunky", "bossbot", 4, data.cog_max_hp(4),
                         data.cog_max_hp(4))]
        return BattleState(toon=toon, cogs=cogs)

    def branches(self):
        from solver.state import Action, Track
        state = self.position()
        return state, outcomes.action_outcomes(state, Action(Track.THROW, 3, 0))

    def test_collapsing_reduces_the_branch_count(self):
        _state, branches = self.branches()
        collapsed = outcomes.collapse_damage(branches)
        self.assertLess(len(collapsed), len(branches))

    def test_probability_is_conserved(self):
        _state, branches = self.branches()
        collapsed = outcomes.collapse_damage(branches)
        self.assertAlmostEqual(sum(p for p, _s, _r in collapsed), 1.0,
                               places=9)

    def test_expected_laff_is_conserved(self):
        """The mean is the whole point; it must survive the merge."""
        _state, branches = self.branches()
        before = sum(p * s.toon.laff for p, s, _r in branches)
        after = sum(p * s.toon.laff
                    for p, s, _r in outcomes.collapse_damage(branches))
        self.assertAlmostEqual(before, after, delta=0.5)

    def test_expected_reward_is_conserved(self):
        _state, branches = self.branches()
        before = sum(p * r for p, _s, r in branches)
        after = sum(p * r for p, _s, r in outcomes.collapse_damage(branches))
        self.assertAlmostEqual(before, after, places=6)

    def test_hit_and_miss_are_not_merged(self):
        """They differ in cog HP, which decides the next move."""
        _state, branches = self.branches()
        collapsed = outcomes.collapse_damage(branches)
        configs = {tuple(c.hp for c in s.cogs) for _p, s, _r in collapsed}
        self.assertGreater(len(configs), 1)

    def test_death_is_never_averaged_into_survival(self):
        """Averaging a loss into a survival is the distortion that would
        let the search walk into a defeat it cannot see."""
        from solver.state import Action, BattleState, CogState, ToonState, Track

        toon = ToonState(3, 50, {Track.THROW: 5}, {(Track.THROW, 3): 2})
        cogs = [CogState("flunky", "bossbot", 5, data.cog_max_hp(5),
                         data.cog_max_hp(5))]
        state = BattleState(toon=toon, cogs=cogs)
        branches = outcomes.action_outcomes(state, Action(Track.THROW, 3, 0))
        collapsed = outcomes.collapse_damage(branches)
        terminal = [s.is_terminal() for _p, s, _r in collapsed]
        self.assertIn(True, terminal, "a lethal branch must survive")
        self.assertIn(False, terminal, "a survivable branch must survive")

    def test_a_single_branch_is_returned_unchanged(self):
        self.assertEqual(outcomes.collapse_damage([]), [])
        one = [(1.0, self.position(), 0.0)]
        self.assertIs(outcomes.collapse_damage(one), one)
