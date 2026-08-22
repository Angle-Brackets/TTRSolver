"""Accuracies the rules STATE rather than compute.

Trap always hits, Throw and Squirt are guaranteed against fully lured
cogs, Drop always misses them. Solo play had all three right. The party
round kept its own copy of the decision, added the same-round stun bonus
to the forced number and capped the sum, and so got all three wrong --
but only when something else landed earlier in the round, which is why
878 tests passed over it.

These pin the rule at both levels: what `mechanics` says, and what a
party round actually resolves the die against.
"""
import unittest

from solver import mechanics, simulator
from solver.state import (Action, BattleState, CogState, CogStatus,
                          ToonState, Track)


def toon():
    return ToonState(laff=110, max_laff=110,
                     track_exp={t: 7 for t in Track},
                     gag_counts={(t, l): 5 for t in Track
                                 for l in range(1, 8)},
                     organic_tracks=frozenset())


def board(lured=False):
    return BattleState(
        toons=[toon(), toon()],
        cogs=[CogState("the_big_cheese", "bossbot", 13, 224, 224,
                       status=CogStatus(
                           lured=lured,
                           lure_rounds_remaining=3 if lured else 0))
              for _ in range(4)])


def resolved(state, plan, hits):
    """The accuracy each roll group was actually resolved against."""
    record = []
    simulator.apply_party_round(state, list(plan), hits=hits, record=record)
    return {track: accuracy for track, _key, accuracy in record}


class ForcedAccuracyRule(unittest.TestCase):
    def test_mechanics_states_the_three_forced_cases(self):
        lured = board(lured=True).cogs
        plain = board().cogs
        self.assertEqual(mechanics.forced_accuracy(Track.TRAP, plain), 100)
        self.assertEqual(mechanics.forced_accuracy(Track.THROW, lured), 100)
        self.assertEqual(mechanics.forced_accuracy(Track.SQUIRT, lured), 100)
        self.assertEqual(mechanics.forced_accuracy(Track.DROP, lured), 0)

    def test_an_ordinary_attack_is_not_forced(self):
        self.assertIsNone(mechanics.forced_accuracy(Track.THROW, board().cogs))
        self.assertIsNone(mechanics.forced_accuracy(Track.DROP, board().cogs))


class ForcedAccuracySurvivesAPartyRound(unittest.TestCase):
    """The stun bonus must not touch a forced number, in either direction."""

    def test_trap_still_always_hits_after_a_heal_lands(self):
        acc = resolved(board(),
                       [Action(track=Track.TOON_UP, level=5, target_index=1),
                        Action(track=Track.TRAP, level=5, target_index=0)],
                       [True, True])
        self.assertEqual(acc[Track.TRAP], 100,
                         "a landed Toon-Up pushed always-hit Trap to the "
                         "95 cap, giving it a 5% miss")

    def test_a_guaranteed_throw_is_not_dragged_down_to_the_cap(self):
        acc = resolved(board(lured=True),
                       [Action(track=Track.TOON_UP, level=5, target_index=1),
                        Action(track=Track.THROW, level=7, target_index=None)],
                       [True, True])
        self.assertEqual(acc[Track.THROW], 100,
                         "guaranteed against lured cogs means guaranteed, "
                         "not 95%")

    def test_drop_always_misses_a_lured_cog(self):
        """Nothing lands before the Drop here, so the cogs are still
        asleep when it resolves.

        This test used to pair the Drop with a Throw, which was a
        stronger scenario until the lure rule was corrected: a landed
        Throw now WAKES the cogs, so by the time Drop resolves they are
        no longer lured and it rolls normally. That is right, and it
        stopped testing what it was written for."""
        acc = resolved(board(lured=True),
                       [Action(track=Track.DROP, level=7, target_index=None),
                        None],
                       [True, True])
        self.assertEqual(acc[Track.DROP], 0)

    def test_a_landed_throw_wakes_them_and_the_drop_can_then_hit(self):
        """The corrected rule, stated as its own case so the interaction
        is pinned rather than implied."""
        acc = resolved(board(lured=True),
                       [Action(track=Track.THROW, level=7, target_index=None),
                        Action(track=Track.DROP, level=7, target_index=None)],
                       [True, True])
        self.assertGreater(acc[Track.DROP], 0,
                           "the Throw woke them, so Drop is no longer "
                           "facing a lured cog")

    def test_the_stun_bonus_still_applies_where_it_should(self):
        """The fix must not switch stun off -- only stop it reaching a
        forced number. Drop on UNLURED cogs is the case that keeps it."""
        miss = resolved(board(),
                        [Action(track=Track.THROW, level=7, target_index=None),
                         Action(track=Track.DROP, level=7, target_index=None)],
                        [False, True])
        hit = resolved(board(),
                       [Action(track=Track.THROW, level=7, target_index=None),
                        Action(track=Track.DROP, level=7, target_index=None)],
                       [True, True])
        self.assertGreater(hit[Track.DROP], miss[Track.DROP],
                           "a landed Throw should still stun for the Drop")


if __name__ == "__main__":
    unittest.main()
