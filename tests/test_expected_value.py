"""The plan scorers take the expectation over the accuracy dice.

Both used to play one ALL-HIT round. That is nearly true in a cog
building -- accuracy runs 70-95% and hardly varies by track -- and badly
wrong against level 13-14 cogs, where it spans 51% to 95%, because it
ranks by the number printed on the gag rather than by the number the gag
is likely to deliver.
"""
import unittest

from solver import simulator
from solver.search import objective as objective_mod
from solver.search import party_search as ps
from solver.state import (Action, BattleState, CogState, CogStatus,
                          ToonState, Track)


def toon():
    return ToonState(laff=110, max_laff=110,
                     track_exp={t: 7 for t in Track},
                     gag_counts={(t, l): 5 for t in Track
                                 for l in range(1, 8)},
                     organic_tracks=frozenset())


# `head_hunter` at level 12 rather than a CEO's level-14 Big Cheese:
# `prevented` needs the cog's attack table, and the Big Cheese has a
# [TODO] accuracy that only `ceo.enable_big_cheese` fills in -- with a
# borrow that cannot be switched off again, so a test must not turn it on
# and leave it on for whatever runs next. Level 12 keeps the point
# intact: a level 7 Drop is 55% there against a Squirt's 95%.
def board(level=12, lured=False, n=4):
    return BattleState(
        toons=[toon(), toon()],
        cogs=[CogState("head_hunter", "bossbot", level, 200, 200,
                       status=CogStatus(
                           lured=lured,
                           lure_rounds_remaining=3 if lured else 0))
              for _ in range(n)])


class TheScoreIsAnExpectation(unittest.TestCase):
    def test_quick_score_is_the_probability_weighted_average(self):
        """The exact invariant: one gag, two branches, weighted by the
        accuracy the simulator itself resolved the roll against."""
        state = board()
        plan = [Action(Track.DROP, 7, None), None]

        record = []
        hit = ps._score_leaf(state, plan, [True, True], record)
        miss = ps._score_leaf(state, plan, [False, True])
        chance = record[0][2] / 100.0
        self.assertAlmostEqual(ps._quick_score(state, plan),
                               chance * hit + (1 - chance) * miss, places=6)

    def test_a_missed_round_scores_below_a_landed_one(self):
        state = board()
        plan = [Action(Track.DROP, 7, None), None]
        self.assertLess(ps._quick_score(state, plan),
                        ps._score_leaf(state, plan, [True, True]),
                        "scoring the all-hit branch alone is the old bug")

    def test_accuracy_can_outrank_raw_damage(self):
        """A level 7 Drop hits a level 12 cog 55% of the time and a level
        7 Squirt 95%. The all-hit scorer could only see the damage."""
        state = board()
        drop = [Action(Track.DROP, 7, None), None]
        squirt = [Action(Track.SQUIRT, 7, None), None]
        self.assertGreater(ps._score_leaf(state, drop, [True, True]),
                           ps._score_leaf(state, squirt, [True, True]),
                           "the Drop should win on damage if it lands")
        self.assertGreater(ps._quick_score(state, squirt),
                           ps._quick_score(state, drop),
                           "and lose once the dice are counted")

    def test_a_drop_on_lured_cogs_is_worth_nothing(self):
        """Forced accuracy, so there is one branch and it is a miss."""
        state = board(lured=True)
        plan = [Action(Track.DROP, 7, None), None]
        self.assertAlmostEqual(
            ps._quick_score(state, plan),
            ps._score_leaf(state, plan, [False, True]), places=6)


class BothScorersAgreeOnTheDice(unittest.TestCase):
    def test_greedy_score_is_also_an_expectation(self):
        """`rollout_value` IS `greedy_plan` played forward, so an all-hit
        rollout values every position as though the party never misses."""
        state = board()
        objective = objective_mod.Objective()
        trial = [Action(Track.DROP, 7, None), None]

        scored = ps._greedy_score(state, trial, objective)

        # Rebuild the two branches by hand and weight them by the
        # accuracy the simulator itself resolved the roll against.
        record = []
        simulator.apply_party_round(state.clone(), list(trial),
                                    hits=[True, True], record=record)
        chance = record[0][2] / 100.0
        self.assertLess(chance, 1.0, "this gag has to be able to miss")

        captured = {}
        original = ps._expected_over_rolls
        try:
            ps._expected_over_rolls = lambda st, pl, leaf: captured.setdefault(
                "leaf", leaf) and 0.0
            ps._greedy_score(state, trial, objective)
        finally:
            ps._expected_over_rolls = original
        leaf = captured["leaf"]
        expected = chance * leaf([True, True], []) +             (1 - chance) * leaf([False, True], [])
        self.assertAlmostEqual(scored, expected, places=6)

    def test_correlated_dice_are_not_hedged(self):
        """Two toons throwing one track at one cog share a die, so the
        round lands twice or not at all. Treating the rolls as
        independent would make stacking look safer than it is."""
        state = board()
        stacked = [Action(Track.DROP, 7, None), Action(Track.DROP, 7, None)]
        groups = ps._roll_groups(stacked)
        self.assertEqual(len(set(groups.values())), 1,
                         "same track, same target -- one die")


if __name__ == "__main__":
    unittest.main()
