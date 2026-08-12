"""Cloning, and the sharing that makes it affordable.

`BattleState.clone` runs 586,000 times for one three-cog depth-2 search,
so it shares `track_exp` and `gag_counts` rather than copying them. That
is safe only while the invariants below hold, and they are easy to break
by accident -- a second place that writes to `gag_counts` in place would
silently edit every sibling state at once, and no existing test would
notice until a search returned a wrong answer.
"""
import unittest

from solver import data
from solver.simulator import apply_toon_action
from solver.state import Action, BattleState, CogState, ToonState, Track


def fight():
    toon = ToonState(laff=50, max_laff=50,
                     track_exp={Track.THROW: 5, Track.SQUIRT: 4},
                     gag_counts={(Track.THROW, 3): 2, (Track.SQUIRT, 2): 4})
    cog = CogState(cog_type="flunky", department="bossbot", level=3,
                   hp=data.cog_max_hp(3), max_hp=data.cog_max_hp(3))
    return BattleState(toon=toon, cogs=[cog])


class CloneSharingTest(unittest.TestCase):

    def test_track_exp_is_shared_not_copied(self):
        """Fixed for the whole battle, so copying it per clone is waste."""
        state = fight()
        self.assertIs(state.clone().toon.track_exp, state.toon.track_exp)

    def test_gag_counts_are_shared_not_copied(self):
        state = fight()
        self.assertIs(state.clone().toon.gag_counts, state.toon.gag_counts)

    def test_cogs_are_not_shared(self):
        """Cog HP and status change constantly and must not be."""
        state = fight()
        clone = state.clone()
        self.assertIsNot(clone.cogs[0], state.cogs[0])
        self.assertIsNot(clone.cogs[0].status, state.cogs[0].status)


class CopyOnWriteTest(unittest.TestCase):
    """Sharing is only safe because the one writer copies first."""

    def test_spending_a_gag_does_not_touch_a_clone(self):
        state = fight()
        clone = state.clone()
        apply_toon_action(state, Action(Track.THROW, 3, 0), hit=True)
        self.assertEqual(state.toon.gag_counts[(Track.THROW, 3)], 1)
        self.assertEqual(clone.toon.gag_counts[(Track.THROW, 3)], 2)

    def test_spending_a_gag_does_not_touch_the_original(self):
        state = fight()
        clone = state.clone()
        apply_toon_action(clone, Action(Track.THROW, 3, 0), hit=True)
        self.assertEqual(clone.toon.gag_counts[(Track.THROW, 3)], 1)
        self.assertEqual(state.toon.gag_counts[(Track.THROW, 3)], 2)

    def test_two_clones_diverge_independently(self):
        """The case the search actually relies on: one state, many
        successors, each spending something different."""
        state = fight()
        a, b = state.clone(), state.clone()
        apply_toon_action(a, Action(Track.THROW, 3, 0), hit=True)
        apply_toon_action(b, Action(Track.SQUIRT, 2, 0), hit=True)
        self.assertEqual(a.toon.gag_counts[(Track.THROW, 3)], 1)
        self.assertEqual(a.toon.gag_counts[(Track.SQUIRT, 2)], 4)
        self.assertEqual(b.toon.gag_counts[(Track.THROW, 3)], 2)
        self.assertEqual(b.toon.gag_counts[(Track.SQUIRT, 2)], 3)
        self.assertEqual(state.toon.gag_counts[(Track.THROW, 3)], 2)

    def test_damage_to_a_cog_does_not_touch_a_clone(self):
        state = fight()
        clone = state.clone()
        before = clone.cogs[0].hp
        apply_toon_action(state, Action(Track.THROW, 3, 0), hit=True)
        self.assertLess(state.cogs[0].hp, before)
        self.assertEqual(clone.cogs[0].hp, before)


if __name__ == "__main__":
    unittest.main()
