"""A board pickled before a field existed still loads.

Feedback logs pickle the whole board, and slotted classes restore their
slots by name and nothing more -- so every field added since a log was
written used to come back missing, and the first `clone()` raised.
"""
import pickle
import unittest

from solver.state import BattleState, CogState, ToonState, Track


def _board():
    toon = ToonState(70, 100, {Track.THROW: 7}, {(Track.THROW, 5): 3})
    return BattleState(toons=[toon], cogs=[CogState("flunky", "bossbot", 3, 20, 20)])


class OldPickleTest(unittest.TestCase):

    def test_a_field_added_since_takes_its_default(self):
        toon = _board().toons[0]
        _cls, _args, state = toon.__reduce_ex__(2)[:3]
        slots = dict(state[1])
        del slots["sos_calls"], slots["sos_cards"]
        old = ToonState.__new__(ToonState)
        old.__setstate__((None, slots))
        self.assertIsNone(old.sos_calls)
        self.assertEqual({}, old.sos_cards)
        self.assertEqual(70, old.laff)

    def test_an_old_board_clones(self):
        board = _board()
        _cls, _args, state = board.__reduce_ex__(2)[:3]
        slots = dict(state[1])
        del slots["sos_one_round"]
        old = BattleState.__new__(BattleState)
        old.__setstate__((None, slots))
        self.assertFalse(old.clone().sos_one_round)

    def test_a_round_trip_is_unchanged(self):
        board = _board()
        back = pickle.loads(pickle.dumps(board))
        self.assertEqual((70, 20, "street"), (back.toons[0].laff, back.cogs[0].hp, back.kind))


if __name__ == "__main__":
    unittest.main()
