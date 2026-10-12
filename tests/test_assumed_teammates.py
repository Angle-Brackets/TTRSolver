"""Stand-in teammates for the TTR Playout row.

TTR shows the client one toon, so the pill's count of teammates is all
the panel knows about them. `party.assumed_teammates` turns that count
into toons the playouts can plan around; the overlay does it for the
Playout row alone.
"""
import random
import threading
import unittest

from solver import party
from solver.data.types import Track
from solver.state import BattleState, ToonState


def _you():
    exp = {Track.THROW: 7, Track.SQUIRT: 6, Track.DROP: 5, Track.SOUND: 7}
    return ToonState(90, 120, exp, {(Track.THROW, 5): 3}, pouch_capacity=60)


class AssumedTeammatesTest(unittest.TestCase):

    def test_built_like_you_at_full_laff(self):
        you = _you()
        mates = party.assumed_teammates(you, 2)
        self.assertEqual(2, len(mates))
        for mate in mates:
            self.assertEqual(you.max_laff, mate.laff)
            self.assertEqual(you.max_laff, mate.max_laff)
            self.assertEqual(you.track_exp, mate.track_exp)
            self.assertEqual(you.pouch_capacity, mate.pouch_capacity)
            self.assertGreater(sum(mate.gag_counts.values()), 0)
            # Only tracks you have: the stand-in is built like you.
            for track, _level in mate.gag_counts:
                self.assertIn(track, you.track_exp)

    def test_they_do_not_share_your_pouch(self):
        you = _you()
        mate = party.assumed_teammates(you, 1)[0]
        mate.gag_counts.clear()
        mate.track_exp.clear()
        self.assertEqual({(Track.THROW, 5): 3}, you.gag_counts)
        self.assertIn(Track.THROW, you.track_exp)

    def test_deterministic_so_every_process_sees_the_same_team(self):
        a = party.assumed_teammates(_you(), 3)
        b = party.assumed_teammates(_you(), 3)
        self.assertEqual([m.gag_counts for m in a], [m.gag_counts for m in b])

    def test_none_for_none(self):
        self.assertEqual([], party.assumed_teammates(_you(), 0))


class OverlayStandsThemInTest(unittest.TestCase):

    def _worker(self):
        from solver.live.overlay import Model, Worker

        w = Worker.__new__(Worker)
        w._lock = threading.Lock()
        w.model = Model()
        w._settings_changed = lambda: None
        return w

    def _board(self, allies):
        from solver.rl import env as env_mod

        rng = random.Random(5)
        cogs = [env_mod.BattleEnv(rng=rng)._sellbot_cog(rng, 6) for _ in range(2)]
        board = BattleState(toons=[_you()], cogs=cogs, kind="street")
        board.allies_standing = allies
        return board

    def test_the_count_becomes_toons_for_the_playouts(self):
        w = self._worker()
        board = self._board(2)
        seen = w._with_teammates(board)
        self.assertEqual(3, len(seen.toons))
        self.assertEqual(0, seen.allies_standing)
        self.assertEqual("pickup", w.group_mode)
        # The board the other rows see is untouched.
        self.assertEqual(1, len(board.toons))
        self.assertEqual(2, board.allies_standing)

    def test_solo_is_left_alone(self):
        w = self._worker()
        w.group_mode = "pickup"
        board = self._board(0)
        self.assertIs(board, w._with_teammates(board))
        self.assertIsNone(w.group_mode)

    def test_the_toggle_reaches_the_playouts(self):
        w = self._worker()
        w.set_party_mode("coordinated")
        self.assertEqual("coordinated", w.model.party_mode)
        w._with_teammates(self._board(1))
        self.assertEqual("coordinated", w.group_mode)
        w.set_party_mode("nonsense")
        self.assertEqual("coordinated", w.party_mode)


if __name__ == "__main__":
    unittest.main()
