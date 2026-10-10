"""Legal-move rules found wrong in live play."""
import unittest

from solver import data
from solver.simulator import apply_toon_action, legal_actions
from solver.state import Action, BattleState, CogState, ToonState, Track


def _board(lured):
    toon = ToonState(70, 100, {Track.TRAP: 7, Track.THROW: 7},
                     {(Track.TRAP, 7): 1, (Track.THROW, 5): 4})
    hp = data.cog_max_hp(12)
    cogs = [CogState("mrhollywood", "sellbot", 12, hp, hp) for _ in lured]
    for cog, is_lured in zip(cogs, lured):
        if is_lured:
            cog.status.apply_lure(80, 3, level=5)
    return BattleState(toons=[toon], cogs=cogs)


class RailroadTest(unittest.TestCase):
    """[CONFIRMED] by the owner: a Railroad needs ONE unlured cog; it then
    wakes the lured ones and arms every cog. With all lured it cannot be
    placed."""

    railroad = Action(Track.TRAP, 7, None)

    def test_not_offered_when_every_cog_is_lured(self):
        self.assertNotIn(self.railroad, legal_actions(_board([True])))
        self.assertNotIn(self.railroad, legal_actions(_board([True, True])))

    def test_one_unlured_cog_lets_it_wake_and_arm_the_row(self):
        board = _board([True, False])
        self.assertIn(self.railroad, legal_actions(board))
        apply_toon_action(board, self.railroad, hit=True)
        self.assertTrue(all(c.status.trapped and not c.status.lured for c in board.cogs))

    def test_a_single_trap_is_still_refused_on_a_lured_cog(self):
        board = _board([True])
        board.toons[0].gag_counts = {(Track.TRAP, 5): 2}
        self.assertNotIn(Action(Track.TRAP, 5, 0), legal_actions(board))


if __name__ == "__main__":
    unittest.main()
