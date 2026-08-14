"""Searching a party position.

The search is sampled rather than exact -- a party round's outcome space
is the accuracy rolls times each cog's attack times its choice of target
times, in pickup mode, the teammates' actions -- so almost nothing here
can assert a value. What it can assert is structure, and one inequality
that turns out to be the most useful test in the file.
"""
import random
import unittest

from solver import data
from solver.party import Mode
from solver.search import party_search as ps
from solver.state import BattleState, CogState, ToonState, Track


def cog(level=6, hp=None):
    mx = data.cog_max_hp(level)
    return CogState("yesman", "bossbot", level,
                    hp if hp is not None else mx, mx)


def toon(counts=None, laff=80):
    counts = counts or {(Track.THROW, 4): 3, (Track.THROW, 5): 3,
                        (Track.SOUND, 4): 3, (Track.SOUND, 5): 3,
                        (Track.LURE, 4): 3, (Track.TRAP, 5): 3}
    return ToonState(laff, 95, {t: 7 for t, _l in counts}, dict(counts))


def party(n=2, cogs=None):
    return BattleState(toons=[toon() for _ in range(n)],
                       cogs=cogs or [cog(), cog()])


class PlanGenerationTest(unittest.TestCase):

    def test_pickup_plans_choose_only_for_you(self):
        """Everyone else is sampled, not chosen -- that is the mode."""
        for plan in ps.plans(party(), Mode.PICKUP):
            self.assertIsNotNone(plan[0])
            self.assertTrue(all(a is None for a in plan[1:]))

    def test_coordinated_plans_choose_for_everyone(self):
        for plan in ps.plans(party(), Mode.COORDINATED):
            self.assertEqual(len(plan), 2)
            self.assertTrue(any(a is not None for a in plan))

    def test_every_track_reaches_the_shortlist(self):
        """Candidates are capped per track, not overall, so a generally
        stronger track cannot squeeze another out entirely. At two per
        track this cap once hid the best Sound plan available -- see
        docs/party-strategy.md."""
        tracks = {a.track for a in ps.candidates(party(), 0)}
        self.assertEqual(tracks, {Track.THROW, Track.SOUND, Track.LURE,
                                  Track.TRAP})

    def test_a_plan_nobody_can_throw_is_not_offered(self):
        state = BattleState(
            toons=[toon({(Track.THROW, 4): 1}), toon({(Track.SOUND, 4): 1})],
            cogs=[cog()])
        for plan in ps.plans(state, Mode.COORDINATED):
            for t, action in zip(state.toons, plan):
                if action is not None:
                    self.assertGreater(
                        t.gag_counts.get((action.track, action.level), 0), 0)

    def test_two_toons_do_not_trap_the_same_cog(self):
        """A cog takes one trap; the second is a wasted gag and should
        not be occupying a plan slot."""
        for plan in ps.plans(party(), Mode.COORDINATED):
            traps = [a.target_index for a in plan
                     if a is not None and a.track == Track.TRAP]
            self.assertEqual(len(traps), len(set(traps)))


class SearchTest(unittest.TestCase):

    def test_a_terminal_position_is_worth_nothing_more(self):
        dead = cog()
        dead.status.is_dead = True
        value, plan = ps.evaluate(party(cogs=[dead]), depth=1)
        self.assertEqual(value, 0.0)
        self.assertIsNone(plan)

    def test_depth_zero_falls_back_to_the_evaluator(self):
        from solver.search import expectimax

        state = party()
        value, plan = ps.evaluate(state, depth=0)
        self.assertAlmostEqual(value, expectimax.heuristic_value(state))
        self.assertIsNone(plan)

    def test_it_returns_a_plan_for_every_toon(self):
        _v, plan = ps.evaluate(party(3), depth=1, mode=Mode.COORDINATED,
                               samples=2, rng=random.Random(0))
        self.assertEqual(len(plan), 3)

    def test_coordinated_is_never_worse_than_pickup(self):
        """The invariant, and the one that earns its keep.

        Coordinated may choose everything pickup may and more, so its
        value cannot be lower. It WAS lower, because `max_plans` took a
        lexicographic prefix of the joint enumeration -- the first sixty
        plans were arrangements of one Trap and the search never saw a
        Sound plan. Nothing else in this file would have noticed.
        """
        state = party(2)
        seed = 11
        pickup, _p = ps.evaluate(state, depth=1, mode=Mode.PICKUP,
                                 samples=24, rng=random.Random(seed))
        team, _t = ps.evaluate(state, depth=1, mode=Mode.COORDINATED,
                               samples=24, rng=random.Random(seed))
        self.assertGreaterEqual(team, pickup - 1e-6)

    def test_sampling_more_does_not_change_the_shape_of_the_answer(self):
        """Not a determinism check -- the search is sampled and will
        wobble. Only that it stays in the same league."""
        state = party(2)
        few, _a = ps.evaluate(state, depth=1, samples=4,
                              rng=random.Random(3))
        many, _b = ps.evaluate(state, depth=1, samples=32,
                               rng=random.Random(3))
        self.assertLess(abs(few - many), 60.0)


class RewardTest(unittest.TestCase):
    """A round is priced in the same units as the solo search."""

    def objective(self):
        from solver.search import objective as objective_mod

        return objective_mod.BALANCED

    def test_laff_lost_costs(self):
        obj = self.objective()
        self.assertLess(
            ps.round_reward(obj, 10, [], won=False, lost=False),
            ps.round_reward(obj, 0, [], won=False, lost=False))

    def test_gags_are_priced_by_scarcity(self):
        """A level 7 costs more than a level 1 because fewer fit in a
        pouch, which is the whole reason the team prefers cheap Sound."""
        obj = self.objective()
        dear = ps.round_reward(obj, 0, [(Track.SOUND, 7, 1)], False, False)
        cheap = ps.round_reward(obj, 0, [(Track.SOUND, 4, 1)], False, False)
        self.assertLess(dear, cheap)

    def test_winning_pays_and_losing_does_not(self):
        obj = self.objective()
        self.assertGreater(ps.round_reward(obj, 0, [], True, False),
                           ps.round_reward(obj, 0, [], False, True))


if __name__ == "__main__":
    unittest.main()
