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
from solver.party import Mode, SensiblePrior, SolverPolicy
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
    """What it favours.

    All a guess, and labelled as one -- what is asserted is that it
    behaves the way people visibly do, not that it is right. The theme
    is the one that matters in long fights: spend as little as
    possible, take as little as possible.
    """

    def cashbot(self, level, hp=None):
        mx = data.cog_max_hp(level)
        return CogState("money_bags", "cashbot", level,
                        hp if hp is not None else mx, mx)

    def best(self, state):
        return SensiblePrior().distribution(state, 1)[0][1]

    def test_it_does_not_overkill(self):
        """A Wedding Cake into a five-hit-point cog kills it and throws
        the rest away. The first version of this scored raw damage and
        so preferred exactly that, which is the opposite of how anybody
        plays."""
        pouch = {(Track.THROW, 1): 10, (Track.THROW, 3): 5,
                 (Track.THROW, 5): 3, (Track.THROW, 7): 1}
        state = BattleState(toons=[toon(), toon(pouch)],
                            cogs=[self.cashbot(6, hp=5)])
        self.assertEqual(self.best(state).level, 1)

    def test_it_still_reaches_for_enough_gag_to_finish(self):
        """Frugal is not timid: a cog it can kill this round, it kills."""
        pouch = {(Track.THROW, 1): 10, (Track.THROW, 5): 3}
        state = BattleState(toons=[toon(), toon(pouch)],
                            cogs=[self.cashbot(6, hp=38)])
        self.assertEqual(self.best(state).level, 5)

    def test_a_rare_gag_has_to_earn_its_place(self):
        """Two gags both one-shot the cog; the plentiful one wins.
        Nobody opens with their Railroad."""
        pouch = {(Track.THROW, 3): 10, (Track.THROW, 7): 1}
        state = BattleState(toons=[toon(), toon(pouch)],
                            cogs=[self.cashbot(4, hp=12)])
        self.assertEqual(self.best(state).level, 3)

    def test_it_lures_when_nothing_can_kill_and_the_cogs_hit_hard(self):
        """The play a damage-only model can never predict, and the
        reason teams lure at all: a lured cog deals no damage."""
        pouch = {(Track.THROW, 3): 5, (Track.LURE, 4): 4}
        state = BattleState(
            toons=[toon(), toon(pouch)],
            cogs=[self.cashbot(9) for _ in range(4)])
        self.assertEqual(self.best(state).track, Track.LURE)

    def test_but_not_when_they_are_already_lured(self):
        """Nothing left to catch."""
        pouch = {(Track.THROW, 3): 5, (Track.LURE, 4): 4}
        cogs = [self.cashbot(9) for _ in range(4)]
        for c in cogs:
            c.status.apply_lure(60, 3, 4)
        state = BattleState(toons=[toon(), toon(pouch)], cogs=cogs)
        self.assertNotEqual(self.best(state).track, Track.LURE)

    def test_a_kill_beats_chipping_something_else(self):
        pouch = {(Track.THROW, 3): 5}
        state = BattleState(
            toons=[toon(), toon(pouch)],
            cogs=[self.cashbot(9), self.cashbot(4, hp=10)])
        self.assertEqual(self.best(state).target_index, 1)

    def test_it_does_not_drop_on_a_lured_cog(self):
        """Drop always misses one; nobody aims there."""
        lured = self.cashbot(6, hp=200)
        lured.status.apply_lure(60, 3, 3)
        state = BattleState(toons=[toon(), toon({(Track.DROP, 5): 2})],
                            cogs=[lured])
        self.assertEqual(SensiblePrior().distribution(state, 1),
                         [(1.0, None)])

    def test_sampling_follows_the_distribution(self):
        pouch = {(Track.THROW, 3): 5, (Track.THROW, 5): 3}
        state = BattleState(toons=[toon(), toon(pouch)],
                            cogs=[self.cashbot(6, hp=300)])
        prior = SensiblePrior(focus=0.6)
        first = prior.distribution(state, 1)[0][1]
        self.assertEqual(prior.sample(state, 1, Fixed([0.1])), first)
        self.assertNotEqual(prior.sample(state, 1, Fixed([0.9])), first)


class SolverPolicyTest(unittest.TestCase):
    """Predicting a teammate by the objective you are recommending.

    The principled form of the same idea: rather than hand-scoring an
    imitation of good play, ask the solver what good play is and predict
    that -- a party as everyone subscribing to one objective, instead of
    one real player surrounded by approximations. It costs a search per
    teammate, so it is for offline work rather than the live budget.
    """

    def cashbot(self, level):
        mx = data.cog_max_hp(level)
        return CogState("money_bags", "cashbot", level, mx, mx)

    def test_it_agrees_with_the_prior_where_the_play_is_clear(self):
        """Not a proof that either is right, but the cheap model being
        a stand-in for the expensive one is the thing worth checking
        before trusting it."""
        pouch = {(Track.THROW, 3): 5, (Track.THROW, 5): 3,
                 (Track.LURE, 4): 3, (Track.SOUND, 4): 3}
        state = BattleState(toons=[toon(pouch), toon(pouch)],
                            cogs=[self.cashbot(9) for _ in range(4)])
        prior = SensiblePrior().distribution(state, 1)[0][1]
        solved = SolverPolicy(depth=1).distribution(state, 1)[0][1]
        self.assertEqual(prior.track, solved.track)

    def test_it_is_still_a_distribution(self):
        pouch = {(Track.THROW, 3): 5, (Track.THROW, 5): 3}
        state = BattleState(toons=[toon(pouch), toon(pouch)],
                            cogs=[self.cashbot(6)])
        dist = SolverPolicy(depth=1).distribution(state, 1)
        self.assertAlmostEqual(sum(p for p, _a in dist), 1.0)

    def test_a_sad_teammate_does_nothing(self):
        state = BattleState(toons=[toon(), toon(laff=0)],
                            cogs=[self.cashbot(6)])
        self.assertEqual(SolverPolicy(depth=1).distribution(state, 1),
                         [(1.0, None)])

    def test_the_rotation_puts_the_teammate_in_the_chair(self):
        """The search chooses for toons[0], so predicting toon 1 means
        handing it a state where toon 1 is toon 0."""
        a, b = toon({(Track.THROW, 3): 1}), toon({(Track.SOUND, 4): 1})
        state = BattleState(toons=[a, b], cogs=[self.cashbot(6)])
        rotated = party._as_actor(state, 1)
        self.assertEqual(rotated.toon.gag_counts, b.gag_counts)
        self.assertEqual(len(rotated.toons), 2)

    def test_rotating_to_yourself_changes_nothing(self):
        state = BattleState(toons=[toon(), toon()], cogs=[self.cashbot(6)])
        self.assertIs(party._as_actor(state, 0), state)


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
