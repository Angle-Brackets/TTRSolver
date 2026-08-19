"""Carry limits scale with how far the track is trained.

The tables come from Open Toontown, which this project treats as a lead
rather than as truth. What promotes them past "plausible" is that they
reproduce numbers the wiki publishes independently: each table's DIAGONAL
is the `min_carry` of every gag (what you hold when that gag is the
newest thing you own) and its BOTTOM ROW is `max_carry` (fully trained).
That is 12 numbers per track which nobody chose to make agree.

These tests assert that agreement, so a future edit to either the tables
or the gag data cannot silently break it.
"""
import unittest

from solver import data
from solver.data import gags as gags_mod
from solver.state import Track

STANDARD = (Track.TOON_UP, Track.TRAP, Track.LURE, Track.THROW,
            Track.SQUIRT, Track.DROP)


class CarryLimitTest(unittest.TestCase):

    def test_diagonal_is_min_carry(self):
        """Holding a gag as your newest unlock is the `min_carry` case."""
        for track in STANDARD + (Track.SOUND,):
            for level in range(1, 7):
                got = gags_mod.carry_limit(track, level, level)
                want = data.gag(track, level).min_carry
                self.assertEqual(
                    got, want,
                    f"{track.value} lv{level}: table says {got}, the wiki "
                    f"infobox says min_carry={want}")

    def test_bottom_row_is_max_carry(self):
        """A fully trained track is the `max_carry` case."""
        for track in STANDARD + (Track.SOUND,):
            for level in range(1, 7):
                got = gags_mod.carry_limit(track, level, 6)
                want = data.gag(track, level).max_carry
                self.assertEqual(
                    got, want,
                    f"{track.value} lv{level}: table says {got}, the wiki "
                    f"infobox says max_carry={want}")

    def test_sound_took_traps_old_numbers(self):
        """The TTR nerf, and it is the whole row, not just levels 5-6."""
        self.assertEqual(
            [gags_mod.carry_limit(Track.SOUND, lv, 6) for lv in range(1, 7)],
            [20, 15, 15, 10, 5, 2])

    def test_trap_was_buffed_onto_the_standard_table(self):
        """[CONFIRMED] wiki: 'Trap now shares the same carry capacity
        with other gag tracks.' Seven Trapdoors and three TNT at the top."""
        self.assertEqual(
            [gags_mod.carry_limit(Track.TRAP, lv, 6) for lv in range(1, 7)],
            [30, 25, 20, 15, 7, 3])
        self.assertEqual(
            [gags_mod.carry_limit(Track.THROW, lv, 6) for lv in range(1, 7)],
            [30, 25, 20, 15, 7, 3])

    def test_untrained_and_unreached_gags_hold_nothing(self):
        self.assertEqual(gags_mod.carry_limit(Track.THROW, 3, 0), 0)
        self.assertEqual(gags_mod.carry_limit(Track.THROW, 5, 3), 0,
                         "you cannot carry a gag you have not unlocked")

    def test_level_seven_is_always_one(self):
        """Earned from the Sellbot Task Force, not by training the track."""
        for track in STANDARD + (Track.SOUND,):
            self.assertEqual(gags_mod.carry_limit(track, 7, 7), 1)
            self.assertEqual(gags_mod.carry_limit(track, 7, 6), 0)

    def test_limits_never_shrink_as_a_track_is_trained(self):
        for track in STANDARD + (Track.SOUND,):
            for level in range(1, 7):
                seen = [gags_mod.carry_limit(track, level, u)
                        for u in range(level, 8)]
                self.assertEqual(seen, sorted(seen),
                                 f"{track.value} lv{level} limit went down")


if __name__ == "__main__":
    unittest.main()
