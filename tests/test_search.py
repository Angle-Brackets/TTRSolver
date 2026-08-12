"""
Tests for the expectimax search in solver/search/expectimax.py.

These check that the search is internally sound and that it makes the
obviously-right call in positions where the right call isn't debatable.
They assert the algorithm is sound, not that its game advice is expert:
the data underneath is transcribed, but nothing here checks the choices
against how strong players actually play.

Keep the fights small and the depths shallow: branching is roughly
(legal actions) x (outcomes per action) per ply, which is ~120 for a
two-cog fight, so depth 4+ on two cogs is slow without further pruning.

stdlib unittest only -- pytest is not installed.
"""
import unittest

from solver import data, simulator
from solver.search import expectimax
from solver.state import Track, CogState, ToonState, BattleState

from tests.test_outcomes import single_flunky_fight


class TestHandWrittenHeuristic(unittest.TestCase):
    """The fallback form, used whenever no weights are fitted.

    These pin its own scale -- "full laff, untouched cogs = 0" -- which
    is deliberately NOT the scale the fitted evaluator uses. That
    convention is the source of the -100 bias the fitted model exists to
    fix, so these assertions target `hand_written_value` directly rather
    than whatever `heuristic_value` currently dispatches to.
    """

    def test_untouched_fight_scores_zero(self):
        state = single_flunky_fight()
        self.assertAlmostEqual(expectimax.hand_written_value(state), 0.0,
                               delta=1e-9)

    def test_progress_scores_positive(self):
        state = single_flunky_fight()
        state.cogs[0].hp = 1  # nearly dead, toon untouched
        self.assertGreater(expectimax.hand_written_value(state), 0.0)

    def test_damage_taken_scores_negative(self):
        state = single_flunky_fight()
        state.toon.laff = 10
        self.assertLess(expectimax.hand_written_value(state), 0.0)

    def test_terminal_states_use_terminal_values(self):
        won = single_flunky_fight()
        won.cogs[0].status.is_dead = True
        self.assertEqual(expectimax.hand_written_value(won),
                         expectimax.WIN_VALUE)

        lost = single_flunky_fight()
        lost.toon.laff = 0
        self.assertEqual(expectimax.hand_written_value(lost),
                         expectimax.LOSS_VALUE)


class TestLeafDispatch(unittest.TestCase):
    """Whatever `heuristic_value` dispatches to must obey these."""

    def test_terminal_states_are_known_not_estimated(self):
        """The fitted form dropped this and scored a lost battle at +72:
        nothing in its feature set says "already over", and a linear
        model extrapolates happily from a pouch that still has gags."""
        won = single_flunky_fight()
        won.cogs[0].status.is_dead = True
        self.assertEqual(expectimax.heuristic_value(won),
                         expectimax.WIN_VALUE)

        lost = single_flunky_fight()
        lost.toon.laff = 0
        self.assertEqual(expectimax.heuristic_value(lost),
                         expectimax.LOSS_VALUE)

    def test_leaf_values_stay_inside_the_pruning_bounds(self):
        """star1 bounds a chance node by the range its unseen children
        can occupy, so a leaf outside that range makes the cut unsound.
        Unclamped, the fitted model put 32% of random positions outside
        it, reaching 175.7 against a ceiling of 100."""
        import random

        rng = random.Random(5)
        for _ in range(300):
            state = single_flunky_fight(level=rng.randint(1, 5))
            state.toon.laff = rng.randint(1, 50)
            state.cogs[0].hp = rng.randint(1, state.cogs[0].max_hp)
            if state.is_terminal():
                continue
            v = expectimax.heuristic_value(state)
            floor, ceiling = expectimax._value_bounds(state, 1, None)
            self.assertLessEqual(v, ceiling + 1e-9)
            self.assertGreaterEqual(v, floor - 1e-9)


class TestSearchChoices(unittest.TestCase):
    def test_takes_the_kill(self):
        """One cog at 12 HP, Cream Pie Slice does 17 and ends the fight for
        +100. Lure just delays. There is no case for luring here."""
        state = single_flunky_fight(level=2)
        action = expectimax.best_action(state, depth=2)
        self.assertIsNotNone(action)
        self.assertEqual(action.track, Track.THROW)

    def test_prioritizes_the_more_dangerous_cog(self):
        """Two cogs, one at 2 HP and one at full, both one-shottable by a
        Cream Pie Slice. Since the gag kills either way, the tie breaks on
        which cog would hurt more if left alive -- the level-5 one."""
        toon = ToonState(
            laff=50, max_laff=50,
            track_exp={Track.THROW: 7},
            gag_counts={(Track.THROW, 3): 5},
        )
        cogs = [
            CogState(cog_type="flunky", department="bossbot", level=5,
                     hp=data.cog_max_hp(5), max_hp=data.cog_max_hp(5)),
            CogState(cog_type="flunky", department="bossbot", level=2,
                     hp=2, max_hp=data.cog_max_hp(2)),
        ]
        state = BattleState(toon=toon, cogs=cogs)
        ranked = expectimax.rank_actions(state, depth=2)
        self.assertTrue(ranked)
        # The level-5 cog hits harder, so with both one-shottable the search
        # should not prefer leaving it alive.
        self.assertEqual(ranked[0][1].target_index, 0)

    def test_rank_actions_is_sorted_and_complete(self):
        state = single_flunky_fight()
        ranked = expectimax.rank_actions(state, depth=2)
        values = [v for v, _a in ranked]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreater(len(ranked), 1)


class TestPruningIsExact(unittest.TestCase):
    """Pruning may change the runtime and nothing else. If star1 ever
    returns a different value or move than an exhaustive search, it is
    wrong -- and silently wrong, which is the whole risk."""

    def _positions(self):
        yield single_flunky_fight(level=2)
        yield single_flunky_fight(level=5, laff=20)
        toon = ToonState(laff=40, max_laff=40,
                         track_exp={Track.THROW: 7, Track.SOUND: 7},
                         gag_counts={(Track.THROW, 3): 3, (Track.SOUND, 4): 2})
        cogs = [CogState(cog_type="flunky", department="bossbot", level=4,
                         hp=data.cog_max_hp(4), max_hp=data.cog_max_hp(4)),
                CogState(cog_type="flunky", department="bossbot", level=2,
                         hp=6, max_hp=data.cog_max_hp(2))]
        yield BattleState(toon=toon, cogs=cogs)

    def test_same_value_and_move_as_exhaustive(self):
        for i, state in enumerate(self._positions()):
            for depth in (1, 2):
                with self.subTest(position=i, depth=depth):
                    pruned = expectimax.evaluate(state, depth)
                    exact = expectimax.evaluate(state, depth, prune=False)
                    self.assertAlmostEqual(pruned[0], exact[0], places=6)
                    self.assertEqual(pruned[1], exact[1])

    def test_a_fresh_memo_gives_the_same_answer(self):
        """Transposition entries carry bounds, not just values; reusing one
        outside the window it was proved in would corrupt the result."""
        state = single_flunky_fight(level=4)
        shared = {}
        first = expectimax.evaluate(state, 2, memo=shared)
        again = expectimax.evaluate(state, 2, memo=shared)
        fresh = expectimax.evaluate(state, 2, memo={})
        self.assertEqual(first, again)
        self.assertAlmostEqual(first[0], fresh[0], places=6)


class TestSymmetryDedupe(unittest.TestCase):
    def test_identical_cogs_collapse(self):
        """Two cogs alike in type, level, HP and status are the same target,
        so searching both is wasted work."""
        toon = ToonState(laff=40, max_laff=40, track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 3): 3})
        same = [CogState(cog_type="flunky", department="bossbot", level=4,
                         hp=30, max_hp=30) for _ in range(3)]
        state = BattleState(toon=toon, cogs=same)
        self.assertEqual(len(simulator.legal_actions(state)), 3)
        self.assertEqual(len(expectimax.distinct_actions(state)), 1)

    def test_a_damaged_cog_is_a_different_target(self):
        toon = ToonState(laff=40, max_laff=40, track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 3): 3})
        cogs = [CogState(cog_type="flunky", department="bossbot", level=4,
                         hp=30, max_hp=30),
                CogState(cog_type="flunky", department="bossbot", level=4,
                         hp=12, max_hp=30)]
        state = BattleState(toon=toon, cogs=cogs)
        self.assertEqual(len(expectimax.distinct_actions(state)), 2)

    def test_dedupe_does_not_change_the_answer(self):
        toon = ToonState(laff=40, max_laff=40, track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 3): 3})
        cogs = [CogState(cog_type="flunky", department="bossbot", level=3,
                         hp=20, max_hp=20) for _ in range(2)]
        state = BattleState(toon=toon, cogs=cogs)
        value, _ = expectimax.evaluate(state, 2)
        exhaustive, _ = expectimax.evaluate(state, 2, prune=False)
        self.assertAlmostEqual(value, exhaustive, places=6)


class TestFullSolve(unittest.TestCase):
    """Every action spends a gag, so the game is a DAG and can be solved to
    the end exactly -- no depth limit, no heuristic."""

    def test_solves_a_small_fight_to_the_end(self):
        toon = ToonState(laff=45, max_laff=45, track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 3): 4})
        cog = CogState(cog_type="flunky", department="bossbot", level=4,
                       hp=data.cog_max_hp(4), max_hp=data.cog_max_hp(4))
        value, action = expectimax.solve(BattleState(toon=toon, cogs=[cog]))
        self.assertIsNotNone(action)
        self.assertGreater(value, 0, "a winnable fight should score positive")

    def test_depth_bound_is_the_pouch(self):
        """The safety valve defaults to gags+1, which is the real bound: no
        line can outlast the pouch."""
        toon = ToonState(laff=45, max_laff=45, track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 1): 2})
        cog = CogState(cog_type="flunky", department="bossbot", level=1,
                       hp=6, max_hp=6)
        state = BattleState(toon=toon, cogs=[cog])
        deep, _ = expectimax.evaluate(state, 50)
        solved, _ = expectimax.solve(state)
        self.assertAlmostEqual(deep, solved, places=6)


class TestEpsilonTrimming(unittest.TestCase):
    def test_zero_epsilon_changes_nothing(self):
        state = single_flunky_fight(level=4)
        self.assertEqual(expectimax.evaluate(state, 2, epsilon=0.0),
                         expectimax.evaluate(state, 2))

    def test_trim_keeps_a_normalised_distribution(self):
        branches = [(0.5, None, 0.0), (0.3, None, 0.0), (0.15, None, 0.0),
                    (0.04, None, 0.0), (0.01, None, 0.0)]
        kept, dropped = expectimax.trim(branches, 0.05)
        self.assertAlmostEqual(sum(p for p, _s, _r in kept), 1.0, places=9)
        self.assertLess(len(kept), len(branches))
        self.assertGreater(dropped, 0)

    def test_trimming_keeps_the_same_move_here(self):
        """Not a guarantee in general -- it is an approximation -- but the
        EV gap between good and bad moves is usually tens of points and the
        error is a couple."""
        state = single_flunky_fight(level=4)
        self.assertEqual(expectimax.evaluate(state, 2, epsilon=0.05)[1],
                         expectimax.evaluate(state, 2)[1])


class TestSearchMechanics(unittest.TestCase):
    def test_terminal_states_have_no_remaining_value(self):
        """evaluate() returns value still to come, and a finished fight has
        none. The +/-100 is paid by the transition's reward -- returning it
        here as well would count every win twice."""
        state = single_flunky_fight()
        state.cogs[0].status.is_dead = True
        value, action = expectimax.evaluate(state, depth=3)
        self.assertEqual(value, 0.0)
        self.assertIsNone(action)

    def test_winning_line_is_not_double_counted(self):
        """A one-shot kill is worth about +100 (minus the gag cost), not
        +200."""
        state = single_flunky_fight(level=2)  # 12 HP, dies to a 17-damage pie
        value, _action = expectimax.evaluate(state, depth=2)
        self.assertLess(value, 100.0)

    def test_deeper_search_converges(self):
        """Deeper search should settle, not swing.

        This used to assert that deeper is never *worse*, and that held
        only because the old heuristic was pessimistic by about 100
        points -- every extra ply could do nothing but find things better
        than the leaf claimed. It was passing for the wrong reason. With
        a calibrated evaluator a shallow estimate can be slightly
        optimistic and deepening corrects it downward, so what is
        actually testable is convergence.
        """
        state = single_flunky_fight()
        one, _ = expectimax.evaluate(state, depth=1)
        two, _ = expectimax.evaluate(state, depth=2)
        three, _ = expectimax.evaluate(state, depth=3)
        self.assertLess(abs(three - two), abs(two - one) + 1e-9)
        self.assertLess(abs(three - one), 25.0)

    def test_memo_is_reused_across_calls(self):
        state = single_flunky_fight()
        memo = {}
        expectimax.evaluate(state, depth=2, memo=memo)
        entries_after_first = len(memo)
        expectimax.evaluate(state, depth=2, memo=memo)
        self.assertGreater(entries_after_first, 0)
        self.assertEqual(len(memo), entries_after_first)

    def test_unevaluable_actions_are_skipped_not_fatal(self):
        """Drop damage is TODO, so a Drop action can't be evaluated. The
        search should route around it rather than crash."""
        toon = ToonState(
            laff=50, max_laff=50,
            track_exp={Track.THROW: 7, Track.DROP: 7},
            gag_counts={(Track.THROW, 3): 2, (Track.DROP, 1): 2},
        )
        cog = CogState(cog_type="flunky", department="bossbot", level=2,
                       hp=data.cog_max_hp(2), max_hp=data.cog_max_hp(2))
        state = BattleState(toon=toon, cogs=[cog])
        action = expectimax.best_action(state, depth=2)
        self.assertIsNotNone(action)
        self.assertEqual(action.track, Track.THROW)


if __name__ == "__main__":
    unittest.main()


class TimeBudgetTest(unittest.TestCase):
    """Anytime search: bounded latency, deepest pass that finished.

    Predicting the next ply's cost from the previous one does not work
    here -- depth 1 to 2 on a three-cog position jumps from 0.01s to 28s
    -- so the budget is enforced inside the search and an abandoned pass
    is thrown away whole.
    """

    def position(self):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track
        counts = {(Track.THROW, lvl): 5 for lvl in (3, 4, 5)}
        counts.update({(Track.SQUIRT, lvl): 5 for lvl in (3, 4, 5)})
        toon = ToonState(60, 60, {Track.THROW: 6, Track.SQUIRT: 6}, counts)
        cogs = [CogState("downsizer", "bossbot", 8, data.cog_max_hp(8),
                         data.cog_max_hp(8)) for _ in range(3)]
        return BattleState(toon=toon, cogs=cogs)

    def test_a_budget_is_respected(self):
        import time
        started = time.monotonic()
        expectimax.best_action_iterative(self.position(), depth=9,
                                         time_budget=1.0)
        self.assertLess(time.monotonic() - started, 3.0)

    def test_a_move_is_returned_even_on_a_tiny_budget(self):
        """Depth 1 always finishes, so there is always an answer."""
        _v, action = expectimax.best_action_iterative(
            self.position(), depth=9, time_budget=0.001)
        self.assertIsNotNone(action)

    def test_no_budget_still_searches_to_the_requested_depth(self):
        v1, _ = expectimax.best_action_iterative(self.position(), depth=1)
        v2, _ = expectimax.best_action_iterative(self.position(), depth=2)
        self.assertNotEqual(v1, v2)

    def test_a_generous_budget_matches_an_unbudgeted_search(self):
        state = self.position()
        want, want_move = expectimax.best_action_iterative(state, depth=2)
        got, got_move = expectimax.best_action_iterative(
            state, depth=2, time_budget=600.0)
        self.assertEqual(got_move, want_move)
        self.assertAlmostEqual(got, want, places=6)


class ValueBoundsTest(unittest.TestCase):
    """The floor must never exceed a real value.

    A bound that is too generous only prunes less; a bound that is too
    tight prunes a real answer and does it silently. This is the direct
    check -- the pruning-exactness test catches the same class of bug,
    but only after it has already corrupted a result.

    It has caught one: making the loss term conditional removed a flat
    -100 that had been standing in for the heuristic's own floor at the
    depth cutoff, and for the objective knobs (laff_weight, scarcity,
    turn cost) that were never in the bound at all.
    """

    def _positions(self):
        from solver.state import BattleState, CogState, ToonState, Track
        from solver import data

        yield single_flunky_fight(level=2)
        yield single_flunky_fight(level=5, laff=20)
        yield single_flunky_fight(level=5, laff=12)
        toon = ToonState(laff=40, max_laff=40,
                         track_exp={Track.THROW: 7, Track.SOUND: 7},
                         gag_counts={(Track.THROW, 3): 3, (Track.SOUND, 4): 2})
        cogs = [CogState(cog_type="flunky", department="bossbot", level=4,
                         hp=data.cog_max_hp(4), max_hp=data.cog_max_hp(4)),
                CogState(cog_type="flunky", department="bossbot", level=2,
                         hp=6, max_hp=data.cog_max_hp(2))]
        yield BattleState(toon=toon, cogs=cogs)

    def test_the_floor_never_exceeds_the_true_value(self):
        from solver.search import objective as objectives

        for i, state in enumerate(self._positions()):
            for name, obj in objectives.PRESETS.items():
                for depth in (1, 2):
                    with self.subTest(position=i, objective=name, depth=depth):
                        value, _ = expectimax.evaluate(
                            state, depth, obj, memo={}, prune=False)
                        floor, ceiling = expectimax._value_bounds(
                            state, depth, obj)
                        self.assertLessEqual(floor, value + 1e-9,
                                             f"floor {floor} above value {value}")
                        self.assertGreaterEqual(ceiling, value - 1e-9)

    def test_the_floor_is_tighter_than_assuming_total_loss(self):
        """The point of the depth-aware floor. If it were not tighter it
        would buy nothing, and pruning would go back to never firing."""
        state = single_flunky_fight(level=2)
        floor, _ = expectimax._value_bounds(state, 1, None)
        naive = -(float(state.toon.laff) + 100.0 + 0.1 * 7.0)
        self.assertGreater(floor, naive)

    def test_max_round_damage_is_an_over_estimate(self):
        """It has to be: it bounds how bad a round can get."""
        from solver import outcomes

        state = single_flunky_fight(level=5)
        bound = expectimax.max_round_damage(state)
        worst = max(d for d, _p in
                    outcomes.cog_damage_distribution(state.cogs[0]).items())
        self.assertGreaterEqual(bound, worst)

    def test_dead_cogs_contribute_no_damage(self):
        state = single_flunky_fight(level=5)
        before = expectimax.max_round_damage(state)
        state.cogs[0].status.is_dead = True
        self.assertEqual(expectimax.max_round_damage(state), 0)
        self.assertGreater(before, 0)


class CollapseGateTest(unittest.TestCase):
    """When the cog phase may be averaged into its mean.

    Collapsing makes the search risk-neutral about damage. Measured at
    equal depth over nine positions, `balanced` picked the same move 9/9
    and `survive` only 7/9 -- and one of the two disagreements was a toon
    at full laff, so what matters is the objective's attitude to risk,
    not how dangerous the position is.
    """

    def test_risk_neutral_objectives_may_collapse(self):
        from solver.search import objective as objectives
        for name in ("balanced", "speedrun", "conserve", "glass cannon"):
            with self.subTest(objective=name):
                self.assertTrue(
                    expectimax.may_collapse(objectives.get(name)))

    def test_survive_may_not_collapse(self):
        from solver.search import objective as objectives
        self.assertFalse(expectimax.may_collapse(objectives.get("survive")))

    def test_no_objective_defaults_to_allowing_it(self):
        self.assertTrue(expectimax.may_collapse(None))

    def test_collapsing_is_off_unless_asked_for(self):
        """`exact_plies=None` must approximate nothing."""
        from solver.state import BattleState, CogState, ToonState, Track
        toon = ToonState(60, 60, {Track.THROW: 6},
                         {(Track.THROW, 4): 4, (Track.THROW, 5): 2})
        cogs = [CogState("flunky", "bossbot", 4, data.cog_max_hp(4),
                         data.cog_max_hp(4))]
        state = BattleState(toon=toon, cogs=cogs)
        plain = expectimax.evaluate(state, 2, memo={})
        explicit = expectimax.evaluate(state, 2, memo={}, exact_plies=None)
        self.assertEqual(plain, explicit)

    def test_collapsing_reaches_the_same_move_on_a_safe_position(self):
        from solver.state import BattleState, CogState, ToonState, Track
        toon = ToonState(60, 60, {Track.THROW: 6, Track.SQUIRT: 6},
                         {(Track.THROW, 4): 4, (Track.THROW, 5): 2,
                          (Track.SQUIRT, 4): 4})
        cogs = [CogState("flunky", "bossbot", 4, data.cog_max_hp(4),
                         data.cog_max_hp(4)),
                CogState("flunky", "bossbot", 3, data.cog_max_hp(3),
                         data.cog_max_hp(3))]
        state = BattleState(toon=toon, cogs=cogs)
        _v0, exact = expectimax.evaluate(state, 2, memo={})
        _v1, collapsed = expectimax.evaluate(state, 2, memo={}, exact_plies=0)
        self.assertEqual(exact, collapsed)
