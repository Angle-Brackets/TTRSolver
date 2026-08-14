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
from solver.state import Action, BattleState, CogState, ToonState, Track


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

    def test_two_toons_do_not_lure_the_same_cog(self):
        """Same rule, and it cost more to find.

        The search answered a maxed four-toon position with two group
        Lures in one round. Dropping either scored 8.6 higher over 300
        playouts -- the second lure was simply a thrown-away gag.
        """
        for plan in ps.plans(party(4), Mode.COORDINATED):
            lures = [a.target_index for a in plan
                     if a is not None and a.track == Track.LURE]
            self.assertEqual(len(lures), len(set(lures)))

    def test_a_group_lure_excludes_every_other_lure(self):
        """It covers everyone, so it collides in either order."""
        state = party(2)
        group = Action(track=Track.LURE, level=4, target_index=None)
        single = Action(track=Track.LURE, level=4, target_index=0)
        self.assertFalse(ps._playable(state, [group, single]))
        self.assertFalse(ps._playable(state, [single, group]))
        self.assertFalse(ps._playable(state, [group, group]))


class StratifiedShortlistTest(unittest.TestCase):
    """One track family must not monopolise the shortlist.

    `_quick_score` plays one round with everything HITTING, so it scores
    a Trap+Lure plan as though the lure never misses and charges nothing
    for the risk. With a global top-N cut that optimism deleted an
    entire family: on the maxed position it ranked Trap+Lure plans at
    1081-1089 and the known-best Sound line at 988, so all 60 surviving
    plans were Lure+Trap and the best line was never sampled.

    Stratifying does not make `_quick_score` honest. It stops the
    dishonesty being fatal, by guaranteeing each family a slot so the
    real sampled evaluation can choose between them.
    """

    def maxed_position(self):
        counts = {}
        for track, levels in [(Track.THROW, (4, 5, 6, 7)),
                              (Track.SQUIRT, (4, 5, 6, 7)),
                              (Track.SOUND, (4, 5, 6, 7)),
                              (Track.LURE, (4, 5, 6)),
                              (Track.TRAP, (4, 5, 6))]:
            for level in levels:
                counts[(track, level)] = 2
        toons = [ToonState(137, 137, {t: 7 for t, _l in counts}, dict(counts))
                 for _ in range(4)]
        cogs = [CogState("loan_shark", "cashbot", level,
                         data.cog_max_hp(level), data.cog_max_hp(level))
                for level in (10, 10, 10, 11)]
        return BattleState(toons=toons, cogs=cogs)

    def test_an_all_sound_plan_survives_truncation(self):
        shortlist = ps.plans(self.maxed_position(), Mode.COORDINATED)
        self.assertTrue(
            any(all(a is not None and a.track == Track.SOUND for a in plan)
                for plan in shortlist),
            "no all-Sound plan on the shortlist -- the stratification "
            "that keeps one track family from monopolising it has gone")

    def test_no_family_takes_more_than_its_share(self):
        shortlist = ps.plans(self.maxed_position(), Mode.COORDINATED)
        counts = {}
        for plan in shortlist:
            sig = tuple(sorted({a.track.name for a in plan if a is not None}))
            counts[sig] = counts.get(sig, 0) + 1
        self.assertLess(max(counts.values()), len(shortlist) // 2,
                        f"one family dominates the shortlist: {counts}")


class SearchTest(unittest.TestCase):

    def test_a_terminal_position_is_worth_nothing_more(self):
        dead = cog()
        dead.status.is_dead = True
        value, plan = ps.evaluate(party(cogs=[dead]), depth=1)
        self.assertEqual(value, 0.0)
        self.assertIsNone(plan)

    def test_depth_zero_with_the_fitted_leaf_asks_the_evaluator(self):
        from solver.search import expectimax

        state = party()
        value, plan = ps.evaluate(state, depth=0, leaf="fitted")
        self.assertAlmostEqual(value, expectimax.heuristic_value(state))
        self.assertIsNone(plan)

    def test_depth_zero_plays_the_position_out_by_default(self):
        """The default leaf is a rollout, not the fitted evaluator.

        The evaluator cannot rank party positions -- pooled over four
        maxed pouches its features pin at their caps, and three plans
        whose outcomes differed by eleven points of "did you win" scored
        96.73, 98.03 and 98.96. A rollout cannot saturate because it
        does not estimate: it plays to the end and adds up what happened.
        """
        state = party()
        value, plan = ps.evaluate(state, depth=0, rng=random.Random(0))
        self.assertIsNone(plan)
        self.assertNotAlmostEqual(
            value, ps.evaluate(state, depth=0, leaf="fitted")[0])

    def test_a_rollout_prefers_the_position_that_is_winning(self):
        """Sanity that the rollout carries signal at all.

        Averaged, and that is the point rather than an implementation
        detail. A single playout of these two positions ranked the
        nearly-dead party ABOVE the healthy one, which is just variance
        -- one rollout is a sample of size one. Over 200 the gap is
        91.2 against 78.7, with the hurt party losing 6.5% of the time
        and the healthy one never. Anything reading `rollout_value` for
        a decision has to average it too.
        """
        from solver.search import objective as objective_mod

        obj = objective_mod.BALANCED
        healthy = party(2)
        hurt = party(2)
        for t in hurt.toons:
            t.laff = 5

        def mean(state, seed, n=40):
            rng = random.Random(seed)
            return sum(ps.rollout_value(state, obj, rng)
                       for _ in range(n)) / n

        self.assertGreater(mean(healthy, 1), mean(hurt, 1))

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
