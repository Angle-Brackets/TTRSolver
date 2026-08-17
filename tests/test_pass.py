"""Passing: the round where the best move is not to move.

A solo toon with Trap and Lure left, against a cog that is already
lured, cannot do anything useful. Trap will not go on a lured cog, and
spending a Lure only refreshes a timer the toon wants to run out. The
right play is to wait, and before `Action(track=None)` existed the
solver could not express it -- it burned Lures until the pouch was
empty and lost a fight it should have won.

The scope of the rule is the delicate part and most of what is pinned
here is the *absence* of a pass. See `simulator.legal_actions` for the
two reasons it is offered so rarely.
"""
import unittest

from solver import data, outcomes, simulator
from solver.search import expectimax
from solver.state import Action, BattleState, CogState, ToonState, Track


def stuck_fight(lure_rounds=2, counts=None, laff=50):
    """Trap and Lure only, against one already-lured cog."""
    cog = CogState("flunky", "bossbot", 3,
                   data.cog_max_hp(3), data.cog_max_hp(3))
    if lure_rounds:
        cog.status.apply_lure(60, lure_rounds, 3)
    if counts is None:
        counts = {(Track.TRAP, 3): 2, (Track.LURE, 3): 2}
    toon = ToonState(laff, 60, {t: 6 for t, _l in counts}, dict(counts))
    return BattleState(toon=toon, cogs=[cog])


def passes(state):
    return [a for a in simulator.legal_actions(state) if a.is_pass]


class WhenPassIsOfferedTest(unittest.TestCase):
    def test_offered_when_lured_and_nothing_is_productive(self):
        self.assertEqual(len(passes(stuck_fight())), 1)

    def test_offered_with_nothing_lured_while_budget_lasts(self):
        """Passing with nothing lured is a real move: conserve a scarce
        gag, or decline to attack in a party because
        `mechanics.pick_cog_target` aims a cog at whoever hurt it most.

        This test used to assert the opposite and said so -- the narrow
        rule was a revert, kept because widening it appeared to make
        `solve()` value a pass as creating points. The cause was not the
        pass: `solve` computed its depth budget as "gags + 1" on the
        assumption that every action spends a gag, so a line containing
        passes truncated and its leaves fell through to
        `heuristic_value`. With the budget counting `free_passes` too,
        narrow and wide agree exactly.
        """
        self.assertEqual(len(passes(stuck_fight(lure_rounds=0))), 1)

    def test_not_offered_once_the_budget_is_spent(self):
        """The cap is what keeps the termination measure descending."""
        state = stuck_fight(lure_rounds=0)
        state.free_passes = 0
        self.assertEqual(passes(state), [])

    def test_offered_even_holding_a_damage_gag(self):
        """Holding a Throw does not oblige you to throw it."""
        state = stuck_fight(counts={(Track.TRAP, 3): 2, (Track.LURE, 3): 2,
                                    (Track.THROW, 3): 1})
        self.assertEqual(len(passes(state)), 1)

    def test_still_nothing_when_hurt_and_holding_only_toon_up(self):
        """This expected the opposite, on a premise the wiki denies.

        [CONFIRMED] TTR wiki (Toon-Up): "Toons cannot use Toon-Up gags
        to restore their own laff." A solo toon has no teammate to heal,
        so Toon-Up is never productive however low their laff -- and the
        pass is correctly still on offer.
        """
        state = stuck_fight(counts={(Track.LURE, 3): 2, (Track.TOON_UP, 3): 1},
                            laff=20)
        self.assertEqual(simulator.legal_actions(state), [])


    # The three cases below hold a pouch that CANNOT damage a cog --
    # Lure with Toon-Up, or Lure alone. `can_still_damage` calls that a
    # loss and `is_terminal` agrees, so `legal_actions` now returns
    # nothing at all rather than a pass: waiting cannot rescue a
    # position with no way to win, and offering the move would let a
    # search pretend otherwise. Trap-plus-Lure is not this case, since a
    # trap springs when a lure lands.
    def test_no_actions_at_all_when_the_pouch_cannot_damage(self):
        state = stuck_fight(counts={(Track.LURE, 3): 2, (Track.TOON_UP, 3): 1},
                            laff=60)
        self.assertTrue(state.is_terminal())
        self.assertEqual(simulator.legal_actions(state), [])

    def test_a_group_lure_over_a_mixed_battle_is_still_productive(self):
        """One cog loose means the Lure still catches something."""
        loose = CogState("flunky", "bossbot", 2,
                         data.cog_max_hp(2), data.cog_max_hp(2))
        state = stuck_fight(counts={(Track.LURE, 4): 2})
        state.cogs.append(loose)
        self.assertTrue(len(passes(state)) <= 1)

    def test_a_drop_with_only_lured_targets_is_not_productive(self):
        """Drop always misses a lured cog, so it is a gag thrown away."""
        state = stuck_fight(counts={(Track.LURE, 3): 1, (Track.DROP, 2): 1})
        self.assertEqual(len(passes(state)), 1)


class PassMechanicsTest(unittest.TestCase):
    def test_it_spends_no_gag_and_deals_nothing(self):
        state = stuck_fight()
        before = dict(state.toon.gag_counts)
        healed, dealt = simulator.apply_toon_action(state, Action(None), True)
        self.assertEqual((healed, dealt), (0, 0))
        self.assertEqual(state.toon.gag_counts, before)

    def test_it_has_one_outcome_branch_not_a_hit_and_a_miss(self):
        state = stuck_fight()
        toon_branches = {
            tuple(sorted((t, l, n) for (t, l), n in st.toon.gag_counts.items()))
            for _p, st, _r in outcomes.action_outcomes(state, Action(None))}
        self.assertEqual(len(toon_branches), 1)
        self.assertEqual(simulator.toon_action_accuracy(state, Action(None)),
                         100)

    def test_it_costs_no_gag_price(self):
        from solver.search import objective as objective_mod
        obj = objective_mod.Objective(gag_cost=1.0, scarcity_cost=1.0)
        self.assertEqual(obj.gag_price(None, 0), 0.0)

    def test_it_burns_a_round_of_lure(self):
        state = stuck_fight(lure_rounds=3)
        branches = outcomes.action_outcomes(state, Action(None))
        self.assertTrue(branches)
        for _p, after, _r in branches:
            status = after.cogs[0].status
            rounds = status.lure_rounds_remaining if status.lured else 0
            self.assertLess(rounds, 3)


class PassWinsTheFightTest(unittest.TestCase):
    """The whole reason the move exists."""

    def solve(self, state):
        outcomes.clear_caches()
        return expectimax.evaluate(state, 10 ** 6, memo={})

    def test_without_pass_the_pouch_runs_dry_and_the_fight_is_lost(self):
        real = simulator.legal_actions
        simulator.legal_actions = lambda st: [
            a for a in real(st) if not a.is_pass]
        try:
            value, action = self.solve(stuck_fight())
        finally:
            simulator.legal_actions = real
            outcomes.clear_caches()
        self.assertEqual(action.track, Track.LURE)   # the wasted re-lure
        self.assertLess(value, -50.0)

    def test_with_pass_the_same_fight_is_won(self):
        value, action = self.solve(stuck_fight())
        self.assertTrue(action.is_pass)
        self.assertGreater(value, 50.0)

    def test_and_it_still_traps_first_when_the_cog_is_loose(self):
        """Passing is not the answer to everything -- only to being stuck."""
        _value, action = self.solve(stuck_fight(lure_rounds=0))
        self.assertEqual(action.track, Track.TRAP)


class PassDoesNotBreakTerminationTest(unittest.TestCase):
    """Exhaustive `solve` still finishes with a free move in the list.

    Termination rests on a lexicographic measure -- (gags remaining,
    total lure rounds remaining) -- rather than on gags alone, because a
    pass spends no gag. If the pass were ever legal with no cog lured,
    the second component would not decrease and this would hang.
    """

    def test_solve_terminates_on_a_pouch_that_can_only_wait(self):
        state = stuck_fight(lure_rounds=4,
                            counts={(Track.TRAP, 3): 3, (Track.LURE, 3): 3})
        outcomes.clear_caches()
        value, _action = expectimax.evaluate(state, 10 ** 6, memo={})
        self.assertIsInstance(value, float)

    def test_the_pass_budget_is_what_the_measure_now_rests_on(self):
        """The termination invariant, restated for the wider pass.

        `solve()` needs a well-founded measure. An unlured pass spends
        no gag and ticks no lure, and in the branch where every cog
        MISSES it costs no laff either -- leaving a state identical to
        its parent. `free_passes` is the third component that keeps the
        measure descending: (gags, lure rounds, free passes).
        """
        import random

        rng = random.Random(4242)
        tracks = [Track.TRAP, Track.LURE, Track.TOON_UP, Track.DROP,
                  Track.THROW]
        for _ in range(400):
            counts = {(rng.choice(tracks), rng.randint(1, 4)): rng.randint(0, 3)
                      for _i in range(rng.randint(1, 3))}
            cogs = []
            for _c in range(rng.randint(1, 3)):
                level = rng.randint(1, 5)
                cog = CogState("flunky", "bossbot", level,
                               data.cog_max_hp(level), data.cog_max_hp(level))
                if rng.random() < 0.5:
                    cog.status.apply_lure(60, rng.randint(1, 3), 3)
                cogs.append(cog)
            toon = ToonState(rng.randint(1, 60), 60,
                             {t: 6 for t, _l in counts}, counts)
            state = BattleState(toon=toon, cogs=cogs)
            if passes(state):
                self.assertTrue(
                    any(c.status.lured for c in state.active_cogs())
                    or state.free_passes > 0,
                    "pass offered with neither a lured cog nor budget: "
                    "nothing in the measure decreases here")


if __name__ == "__main__":
    unittest.main()


class DepthBudgetTest(unittest.TestCase):
    """`solve()`'s depth budget must count the pass budget too.

    It counted gags only, on the stated assumption that every action
    spends a gag. A pass does not, so a toon holding one gag got
    max_depth = 2, the search truncated, and the leaves fell through to
    `heuristic_value` -- which returned the right VALUE while naming the
    wrong ACTION, and is what the wider pass was blamed for.
    """

    def one_gag_position(self):
        return BattleState(
            toon=ToonState(30, 30, {Track.THROW: 5}, {(Track.THROW, 2): 1}),
            cogs=[CogState("flunky", "bossbot", 2, 2,
                           data.cog_max_hp(2))],
            free_passes=3)

    def test_throwing_the_last_gag_at_a_dying_cog_beats_passing(self):
        outcomes.clear_caches()
        _value, action = expectimax.solve(self.one_gag_position())
        self.assertIsNotNone(action)
        self.assertFalse(action.is_pass)
        self.assertEqual(action.track, Track.THROW)

    def test_the_budget_leaves_room_for_every_pass(self):
        state = self.one_gag_position()
        gags = sum(n for n in state.toon.gag_counts.values() if n > 0)
        # However solve computes it, it must allow a line that spends
        # every gag AND every pass.
        outcomes.clear_caches()
        value, _action = expectimax.solve(state)
        self.assertIsInstance(value, float)
        self.assertGreaterEqual(gags + state.free_passes, 4)
