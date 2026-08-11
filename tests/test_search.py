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

from solver import data
from solver.search import expectimax
from solver.state import Track, CogState, ToonState, BattleState

from tests.test_outcomes import single_flunky_fight


class TestHeuristic(unittest.TestCase):
    def test_untouched_fight_scores_zero(self):
        state = single_flunky_fight()
        self.assertAlmostEqual(expectimax.heuristic_value(state), 0.0, delta=1e-9)

    def test_progress_scores_positive(self):
        state = single_flunky_fight()
        state.cogs[0].hp = 1  # nearly dead, toon untouched
        self.assertGreater(expectimax.heuristic_value(state), 0.0)

    def test_damage_taken_scores_negative(self):
        state = single_flunky_fight()
        state.toon.laff = 10
        self.assertLess(expectimax.heuristic_value(state), 0.0)

    def test_terminal_states_use_terminal_values(self):
        won = single_flunky_fight()
        won.cogs[0].status.is_dead = True
        self.assertEqual(expectimax.heuristic_value(won), expectimax.WIN_VALUE)

        lost = single_flunky_fight()
        lost.toon.laff = 0
        self.assertEqual(expectimax.heuristic_value(lost), expectimax.LOSS_VALUE)


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

    def test_deeper_search_is_not_worse(self):
        """Sanity check on the search itself: with a heuristic this simple,
        seeing further shouldn't make the toon think a winnable fight is
        worse than a shallow look suggested."""
        state = single_flunky_fight()
        shallow, _ = expectimax.evaluate(state, depth=1)
        deep, _ = expectimax.evaluate(state, depth=3)
        self.assertGreaterEqual(deep, shallow - 1e-9)

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
