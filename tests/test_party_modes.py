"""The two ways to treat a toon you are not.

Whether a teammate is something you choose or something you predict is
not a search detail, it is a different problem, and these pin the
boundary between them.

`SensiblePrior` is a stated guess at what an average player throws and
nothing in the wiki or the source can confirm it -- there is no fact of
the matter about what a stranger does. So what is tested here is that it
is *coherent* (a distribution, over legal-looking moves, that prefers a
kill) and never that it is right.
"""
import unittest

from solver import data, party
from solver.party import Mode, SensiblePrior
from solver.state import Action, BattleState, CogState, ToonState, Track


def cog(level=6, hp=None):
    mx = data.cog_max_hp(level)
    return CogState("yesman", "bossbot", level,
                    hp if hp is not None else mx, mx)


def toon(counts=None, laff=80):
    counts = {(Track.THROW, 3): 3} if counts is None else counts
    return ToonState(laff, 95, {t: 7 for t, _l in counts}, dict(counts))


class Fixed:
    """A `random` stand-in with a scripted stream."""

    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)

    def randint(self, _lo, hi):
        return int(self.values.pop(0) * hi)

    def choice(self, seq):
        return seq[0]


class PriorShapeTest(unittest.TestCase):
    """It has to be a distribution before it can be a good one."""

    def state(self, counts=None, cogs=None):
        return BattleState(toons=[toon(), toon(counts)],
                           cogs=cogs or [cog()])

    def test_probabilities_sum_to_one(self):
        dist = SensiblePrior().distribution(self.state(), 1)
        self.assertAlmostEqual(sum(p for p, _a in dist), 1.0)

    def test_the_favourite_gets_the_focus_mass(self):
        dist = SensiblePrior(focus=0.7).distribution(
            self.state(counts={(Track.THROW, 3): 1, (Track.THROW, 5): 1}), 1)
        self.assertAlmostEqual(dist[0][0], 0.7)

    def test_a_single_option_takes_all_of_it(self):
        dist = SensiblePrior().distribution(
            self.state(counts={(Track.SOUND, 4): 1}), 1)
        self.assertEqual(len(dist), 1)
        self.assertAlmostEqual(dist[0][0], 1.0)

    def test_an_empty_pouch_predicts_sitting_out(self):
        """Not an invented attack. Predicting a gag they do not have is
        worse than predicting nothing."""
        dist = SensiblePrior().distribution(self.state(counts={}), 1)
        self.assertEqual(dist, [(1.0, None)])

    def test_a_sad_toon_does_nothing(self):
        state = BattleState(toons=[toon(), toon(laff=0)], cogs=[cog()])
        self.assertEqual(SensiblePrior().distribution(state, 1),
                         [(1.0, None)])

    def test_focus_must_be_a_probability(self):
        for bad in (0.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                SensiblePrior(focus=bad)


class PriorChoiceTest(unittest.TestCase):
    """What it favours, which is a guess and is labelled as one."""

    def test_it_prefers_a_gag_that_finishes_a_cog(self):
        """A player reaches for the kill, so the prior does too."""
        state = BattleState(
            toons=[toon(), toon({(Track.THROW, 3): 1, (Track.THROW, 5): 1})],
            cogs=[cog(hp=200), cog(hp=15)])
        best = SensiblePrior().distribution(state, 1)[0][1]
        self.assertEqual(best.target_index, 1)      # the one it can kill

    def test_otherwise_the_biggest_gag(self):
        state = BattleState(
            toons=[toon(), toon({(Track.THROW, 3): 1, (Track.THROW, 5): 1})],
            cogs=[cog(hp=300)])
        best = SensiblePrior().distribution(state, 1)[0][1]
        self.assertEqual(best.level, 5)

    def test_it_does_not_drop_on_a_lured_cog(self):
        """Drop always misses one; nobody aims there."""
        lured = cog(hp=200)
        lured.status.apply_lure(60, 3, 3)
        state = BattleState(toons=[toon(), toon({(Track.DROP, 5): 2})],
                            cogs=[lured])
        self.assertEqual(SensiblePrior().distribution(state, 1),
                         [(1.0, None)])

    def test_sampling_follows_the_distribution(self):
        state = BattleState(
            toons=[toon(), toon({(Track.THROW, 3): 1, (Track.THROW, 5): 1})],
            cogs=[cog(hp=300)])
        prior = SensiblePrior(focus=0.6)
        self.assertEqual(prior.sample(state, 1, Fixed([0.1])).level, 5)
        self.assertEqual(prior.sample(state, 1, Fixed([0.9])).level, 3)


class ModeTest(unittest.TestCase):
    """Chosen or predicted -- the toggle."""

    def state(self):
        return BattleState(toons=[toon(), toon()], cogs=[cog(hp=300)])

    def test_coordinated_takes_the_actions_it_is_given(self):
        given = [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 0)]
        got = party.teammate_actions(self.state(), given[0],
                                     Mode.COORDINATED, joint=given)
        self.assertEqual(got, given)

    def test_coordinated_refuses_a_wrong_sized_plan(self):
        """Two toons and one action is a bug, not a toon sitting out --
        sitting out is an explicit None."""
        with self.assertRaises(ValueError):
            party.teammate_actions(self.state(), None, Mode.COORDINATED,
                                   joint=[Action(Track.THROW, 3, 0)])

    def test_coordinated_needs_a_plan_at_all(self):
        with self.assertRaises(ValueError):
            party.teammate_actions(self.state(), None, Mode.COORDINATED)

    def test_pickup_keeps_your_action_and_predicts_the_rest(self):
        mine = Action(Track.THROW, 3, 0)
        got = party.teammate_actions(self.state(), mine, Mode.PICKUP,
                                     rng=Fixed([0.1]))
        self.assertEqual(len(got), 2)
        self.assertIs(got[0], mine)
        self.assertIsNotNone(got[1])

    def test_pickup_never_chooses_for_you(self):
        """Your own action is whatever you passed, including nothing."""
        got = party.teammate_actions(self.state(), None, Mode.PICKUP,
                                     rng=Fixed([0.1]))
        self.assertIsNone(got[0])


class StepTest(unittest.TestCase):
    """A whole party round, end to end."""

    def test_the_caller_s_state_is_untouched(self):
        state = BattleState(toons=[toon(), toon()], cogs=[cog(hp=300)])
        before = state.cogs[0].hp
        party.step(state, Action(Track.THROW, 3, 0), rng=Fixed([0.1] * 20))
        self.assertEqual(state.cogs[0].hp, before)

    def test_both_toons_gags_are_spent(self):
        state = BattleState(toons=[toon(), toon()], cogs=[cog(hp=300)])
        nxt, _healed, _done = party.step(
            state, Action(Track.THROW, 3, 0), rng=Fixed([0.1] * 20))
        self.assertEqual(nxt.toons[0].gag_counts[(Track.THROW, 3)], 2)
        self.assertEqual(nxt.toons[1].gag_counts[(Track.THROW, 3)], 2)

    def test_a_coordinated_round_does_what_it_was_told(self):
        state = BattleState(toons=[toon(), toon()], cogs=[cog(hp=300)])
        nxt, _h, _d = party.step(
            state, None, mode=Mode.COORDINATED,
            joint=[Action(Track.THROW, 3, 0), None], rng=Fixed([0.1] * 20))
        self.assertEqual(nxt.toons[0].gag_counts[(Track.THROW, 3)], 2)
        self.assertEqual(nxt.toons[1].gag_counts[(Track.THROW, 3)], 3)

    def test_the_round_counter_advances(self):
        state = BattleState(toons=[toon(), toon()], cogs=[cog(hp=300)])
        nxt, _h, _d = party.step(state, Action(Track.THROW, 3, 0),
                                 rng=Fixed([0.1] * 20))
        self.assertEqual(nxt.round_num, state.round_num + 1)

    def test_a_battle_can_be_played_out(self):
        """The point of all of it: a party fight that reaches an end."""
        import random

        rng = random.Random(0)
        state = BattleState(
            toons=[toon({(Track.THROW, 5): 8}), toon({(Track.SQUIRT, 5): 8})],
            cogs=[cog(level=4), cog(level=4)])
        for _round in range(40):
            state, _healed, done = party.step(
                state, Action(Track.THROW, 5, 0), rng=rng)
            if done:
                break
        self.assertTrue(state.is_terminal())


if __name__ == "__main__":
    unittest.main()
