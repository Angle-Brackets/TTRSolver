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
        cands = ps.candidates(party(), 0)
        tracks = {a.track for a in cands if not a.is_pass}
        self.assertEqual(tracks, {Track.THROW, Track.SOUND, Track.LURE,
                                  Track.TRAP})

    def test_a_party_can_already_decline_to_act(self):
        """Not via a pass candidate -- via an empty slot.

        `candidates` drops the pass, which looks like an omission and is
        not: a joint plan leaves a toon's slot None when it gives them
        nothing, measured at 19.2% of all plan slots. Adding an explicit
        pass candidate as well was inert, chosen 0 times in 543 slots.
        """
        seen = set()
        for plan in ps.plans(party(), Mode.COORDINATED):
            seen.update(a is None for a in plan)
        self.assertIn(True, seen)

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

    def test_stacked_lure_is_allowed(self):
        """Two Lures in a round is a real TTR play, not a wasted gag.

        This test asserts the OPPOSITE of what it used to. There was a
        rule here refusing a second Lure, by analogy with the Trap rule
        above. It was wrong. [CONFIRMED] TTR wiki (Lure): "Using
        multiple Lure gags simultaneously increases the accuracy", and
        the update notes: "Multiple Lure gags of the same type used
        simultaneously now grant a bonus (20/15/10)% accuracy depending
        on the gag level discrepancies of the additional Lure gags."

        The bonus itself is [TODO] -- see
        `mechanics.MULTI_LURE_ACCURACY_BONUS` -- so stacked Lure is
        searched at single-Lure accuracy and undervalued. Undervalued
        and reachable beats correctly valued and unreachable.
        """
        state = party(2)
        group = Action(track=Track.LURE, level=4, target_index=None)
        single = Action(track=Track.LURE, level=4, target_index=0)
        self.assertTrue(ps._playable(state, [group, group]))
        self.assertTrue(ps._playable(state, [group, single]))
        self.assertTrue(ps._playable(state, [single, group]))

    def test_drop_on_a_cog_this_round_lures_is_refused(self):
        """[CONFIRMED] TTR wiki: "Drop gags always miss on lured Cogs."

        Lure resolves before Drop, so a Drop aimed at anything the same
        round's Lure catches is a guaranteed miss. Verified on a real
        recommendation: the Drop and the toon doing nothing at all left
        an identical board.
        """
        state = BattleState(toons=[toon({(Track.LURE, 4): 2}),
                                   toon({(Track.DROP, 5): 2})],
                            cogs=[cog(), cog()])
        group_lure = Action(track=Track.LURE, level=4, target_index=None)
        drop = Action(track=Track.DROP, level=5, target_index=0)
        self.assertFalse(ps._playable(state, [group_lure, drop]))
        # ... but a Drop with no Lure in the round is fine.
        self.assertTrue(ps._playable(state, [None, drop]))

    def test_drop_on_an_already_lured_cog_is_refused(self):
        lured, other = cog(), cog()
        lured.status.lured = True
        state = BattleState(toons=[toon({(Track.DROP, 5): 2})],
                            cogs=[lured, other])
        self.assertFalse(ps._playable(
            state, [Action(track=Track.DROP, level=5, target_index=0)]))
        self.assertTrue(ps._playable(
            state, [Action(track=Track.DROP, level=5, target_index=1)]))

    def test_lure_in_the_same_round_as_sound_is_refused(self):
        """[CONFIRMED] TTR wiki: "Lured Cogs are awakened by Sound gags
        without a damage bonus." The Sound wakes what the Lure just
        caught and does not even collect the lured bonus for it, so the
        pair is dominated by joining the Sound or throwing an attack."""
        state = BattleState(toons=[toon({(Track.LURE, 4): 2}),
                                   toon({(Track.SOUND, 4): 2})],
                            cogs=[cog(), cog()])
        lure = Action(track=Track.LURE, level=4, target_index=None)
        sound = Action(track=Track.SOUND, level=4, target_index=None)
        self.assertFalse(ps._playable(state, [lure, sound]))
        self.assertTrue(ps._playable(state, [None, sound]))
        self.assertTrue(ps._playable(state, [lure, None]))

    def test_holding_is_offered_but_all_holding_is_not(self):
        """A toon with nothing useful to do must be able to hold.

        Without this the search made a toon on a winning board throw
        Toon-Up at a teammate on FULL LAFF, because a cheap wasted heal
        was the least bad thing it was allowed to say. No extra "wasted
        gag" penalty is needed -- `round_reward` already charges for
        what is spent, so a useless gag is strictly worse than holding.
        """
        state = party(2)
        self.assertTrue(any(None in plan
                            for plan in ps.plans(state, Mode.COORDINATED)))
        self.assertFalse(ps._playable(state, [None, None]))


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


class WasteTest(unittest.TestCase):
    """Overkill is charged, scaled by how scarce the wasted gag is."""

    def position(self, hp):
        counts = {(Track.THROW, 1): 2, (Track.THROW, 7): 2}
        toon = ToonState(100, 100, {Track.THROW: 7}, dict(counts))
        return BattleState(toons=[toon],
                           cogs=[CogState("bean_counter", "cashbot", 4,
                                          hp, data.cog_max_hp(4))])

    def throw(self, level):
        return Action(track=Track.THROW, level=level, target_index=0)

    def test_a_level_7_into_a_nearly_dead_cog_is_mostly_waste(self):
        wasted, _scarcity = ps.plan_waste(self.position(8), [self.throw(7)])
        self.assertGreater(wasted, 100)

    def test_the_same_gag_wastes_nothing_when_it_is_needed(self):
        """The "unless it is the only option" case, falling out of the
        arithmetic rather than being special-cased."""
        wasted, _scarcity = ps.plan_waste(self.position(132), [self.throw(7)])
        self.assertEqual(wasted, 0.0)

    def test_a_cheap_gag_wasted_is_charged_far_less_than_a_dear_one(self):
        """Scarcity is the point: one Railroad per pouch, thirty Cupcakes."""
        from solver.search import objective as objective_mod

        obj = objective_mod.BALANCED
        dear = ps.waste_penalty(obj, self.position(8), [self.throw(7)])
        cheap = ps.waste_penalty(obj, self.position(3), [self.throw(1)])
        self.assertGreater(dear, cheap * 10)

    def test_no_charge_when_the_weight_is_off(self):
        import dataclasses
        from solver.search import objective as objective_mod

        off = dataclasses.replace(objective_mod.BALANCED, waste_weight=0.0)
        self.assertEqual(
            ps.waste_penalty(off, self.position(8), [self.throw(7)]), 0.0)


class GreedyRolloutTest(unittest.TestCase):

    def test_it_plays_better_than_the_people_model(self):
        """The rollout estimates a position's value, so it wants good
        play, not average play. `SensiblePrior` models what a STRANGER
        throws -- right for pickup teammates, wrong here, and it is the
        mechanism behind multi-round plans never scoring well.
        """
        from solver import party as party_mod
        from solver.search import objective as objective_mod

        obj = objective_mod.BALANCED
        state = party(3)

        def with_prior(seed):
            rng = random.Random(seed)
            cur, total = state.clone(), 0.0
            for _ in range(12):
                if cur.is_terminal():
                    break
                mine = party_mod.DEFAULT_MODEL.sample(cur, 0, rng)
                nxt, _h, _d = party_mod.step(cur, mine, rng=rng)
                lost = sum(max(0, b.laff - a.laff)
                           for b, a in zip(cur.toons, nxt.toons))
                total += ps.round_reward(
                    obj, lost, ps._spent(cur, nxt), nxt.is_win(),
                    nxt.is_terminal() and not nxt.is_win())
                cur = nxt
            return total

        greedy = sum(ps.rollout_value(state, obj, random.Random(s))
                     for s in range(8)) / 8
        prior = sum(with_prior(s) for s in range(8)) / 8
        self.assertGreater(greedy, prior)

    def test_it_gives_every_standing_toon_a_decision(self):
        plan = ps.greedy_plan(party(3), None.__class__ and
                              __import__("solver.search.objective",
                                         fromlist=["x"]).BALANCED)
        self.assertEqual(len(plan), 3)


class GroupGagWasteTest(unittest.TestCase):
    """A group gag's overkill on a weak cog is not a choice anyone made.

    Its damage is uniform by construction, so charging per cog bills a
    plan for spread it cannot avoid. What a player chooses is how big a
    group gag to bring, and the binding constraint is the toughest cog
    it has to kill -- so the waste is counted ONCE against that.

    Charged per cog, 2 Foghorn + 2 Aoogah (the known-best line on the
    maxed position, sized within 3 damage of the toughest cog) was
    billed 84 wasted damage and priced out of its own win.
    """

    def maxed(self):
        counts = {(Track.SOUND, level): 2 for level in (4, 5, 6, 7)}
        toons = [ToonState(137, 137, {Track.SOUND: 7}, dict(counts))
                 for _ in range(4)]
        cogs = [CogState("loan_shark", "cashbot", level,
                         data.cog_max_hp(level), data.cog_max_hp(level))
                for level in (10, 10, 10, 11)]
        return BattleState(toons=toons, cogs=cogs)

    def sound(self, level):
        return Action(track=Track.SOUND, level=level, target_index=None)

    def waste(self, levels):
        return ps.plan_waste(self.maxed(),
                             [self.sound(lv) for lv in levels])[0]

    def test_a_well_sized_group_gag_wastes_almost_nothing(self):
        # 2 Foghorn + 2 Aoogah deals 159 against a toughest cog of 156.
        self.assertLess(self.waste([6, 6, 4, 4]), 10)

    def test_an_oversized_one_is_still_charged(self):
        # 4 Foghorn deals 240; 4 Opera Singer deals 432.
        self.assertGreater(self.waste([6, 6, 6, 6]), 50)
        self.assertGreater(self.waste([7, 7, 7, 7]), 200)

    def test_the_ordering_matches_the_exhaustive_sweep(self):
        self.assertLess(self.waste([6, 6, 4, 4]), self.waste([6, 6, 6, 6]))
        self.assertLess(self.waste([6, 6, 6, 6]), self.waste([7, 7, 7, 7]))

    def test_single_target_waste_is_still_per_cog(self):
        """The group rule must not leak into single-target gags, where
        over-investing in one cog IS the choice being made."""
        counts = {(Track.THROW, 7): 2}
        state = BattleState(
            toons=[ToonState(100, 100, {Track.THROW: 7}, dict(counts))],
            cogs=[CogState("bean_counter", "cashbot", 4, 8,
                           data.cog_max_hp(4)),
                  CogState("loan_shark", "cashbot", 9,
                           data.cog_max_hp(9), data.cog_max_hp(9))])
        wasted, _s = ps.plan_waste(
            state, [Action(track=Track.THROW, level=7, target_index=0)])
        self.assertGreater(wasted, 100)


class NoOpHealTest(unittest.TestCase):
    """A heal with nobody to heal must be refused, not merely priced.

    This symptom -- a party at full laff opening with Toon-Up -- survived
    three separate fixes aimed at it, and the position's value did not
    move by 0.01 across any of them:

      * holding was added, which made a no-op heal EQUAL to holding
        rather than worse;
      * the heal/damage clamp was corrected, which does not bite when
        nobody is hurt;
      * the heal was redirected from the thrower to teammates, which on
        a full-laff party is one no-op replacing another.

    Each was a real bug and none was this one.
    """

    def test_refused_when_every_teammate_is_at_full_laff(self):
        state = BattleState(
            toons=[toon({(Track.TOON_UP, 5): 2}), toon({(Track.THROW, 4): 2})],
            cogs=[cog()])
        for t in state.toons:
            t.laff = t.max_laff
        heal = Action(track=Track.TOON_UP, level=5, target_index=1)
        self.assertFalse(ps._playable(state, [heal, None]))

    def test_allowed_when_a_teammate_is_hurt(self):
        state = BattleState(
            toons=[toon({(Track.TOON_UP, 5): 2}), toon({(Track.THROW, 4): 2})],
            cogs=[cog()])
        state.toons[0].laff = state.toons[0].max_laff
        state.toons[1].laff = 5
        heal = Action(track=Track.TOON_UP, level=5, target_index=1)
        self.assertTrue(ps._playable(state, [heal, None]))

    def test_refused_solo_at_any_laff(self):
        """Nobody else in the battle, so there is nobody to heal."""
        state = BattleState(toons=[toon({(Track.TOON_UP, 5): 2})],
                            cogs=[cog()])
        state.toons[0].laff = 1
        self.assertFalse(ps._playable(
            state, [Action(track=Track.TOON_UP, level=5, target_index=0)]))


class DropAfterSoundTest(unittest.TestCase):
    """Drop on a lured cog is fine if something wakes it first.

    [CONFIRMED] TTR wiki (Lure): "Lured Cogs are awakened by Sound
    gags", and ATTACK_ORDER puts SOUND before DROP -- so a Sound this
    round un-lures the cog in time for the Drop to land. Every Sound gag
    is a group gag, so one anywhere in the plan covers every cog.

    The rule banning Drop-on-lured was refusing this outright.
    `_playable` exists to refuse what CANNOT work, not what might not: a
    Sound that misses leaves the cog lured and the Drop misses too, but
    that is a gamble, not a guarantee.
    """

    def position(self):
        lured, other = cog(), cog()
        lured.status.lured = True
        return BattleState(
            toons=[toon({(Track.SOUND, 4): 2}), toon({(Track.DROP, 5): 2})],
            cogs=[lured, other])

    def test_drop_on_a_lured_cog_is_allowed_when_a_sound_wakes_it(self):
        sound = Action(track=Track.SOUND, level=4, target_index=None)
        drop = Action(track=Track.DROP, level=5, target_index=0)
        self.assertTrue(ps._playable(self.position(), [sound, drop]))

    def test_and_still_refused_without_the_sound(self):
        drop = Action(track=Track.DROP, level=5, target_index=0)
        self.assertFalse(ps._playable(self.position(), [None, drop]))


class LearnedLeafTest(unittest.TestCase):
    """`leaf="learned"` uses the trained value head, and degrades to a
    rollout rather than failing when it cannot."""

    def test_it_falls_back_when_the_model_is_unavailable(self):
        from solver.search import policy

        real = policy.value
        policy.value = lambda state, feats: None
        try:
            value, plan = ps.evaluate(party(2), depth=0, leaf="learned",
                                      rng=random.Random(0))
        finally:
            policy.value = real
        self.assertIsNone(plan)
        self.assertIsInstance(value, float)

    def test_it_uses_the_model_when_available(self):
        from solver.search import policy

        real = policy.value
        policy.value = lambda state, feats: 42.5
        try:
            value, _plan = ps.evaluate(party(2), depth=0, leaf="learned",
                                       rng=random.Random(0))
        finally:
            policy.value = real
        self.assertAlmostEqual(value, 42.5)

    def test_an_unknown_leaf_name_still_uses_the_evaluator(self):
        from solver.search import expectimax

        state = party(2)
        value, _plan = ps.evaluate(state, depth=0, leaf="fitted")
        self.assertAlmostEqual(value, expectimax.heuristic_value(state))
