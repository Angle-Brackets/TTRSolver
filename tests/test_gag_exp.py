"""Skill points required to unlock each gag.

[CONFIRMED] TTR wiki (Skill points, "Required skill points"). This is
`minE` in `mechanics.gag_damage_from_exp`; `maxE` is still missing, so
nothing consumes it in the damage path yet.
"""
import unittest

from solver import data
from solver.state import Track

TRACKS = (Track.TOON_UP, Track.TRAP, Track.LURE, Track.SOUND,
          Track.THROW, Track.SQUIRT, Track.DROP)


class ThresholdTest(unittest.TestCase):

    def test_every_track_has_seven_gags(self):
        for track in TRACKS:
            self.assertEqual(len(data.GAG_UNLOCK_EXP[track]), 7, track)

    def test_the_first_gag_is_free_and_the_last_costs_the_maximum(self):
        for track in TRACKS:
            self.assertEqual(data.gag_unlock_exp(track, 1), 0, track)
            self.assertEqual(data.gag_unlock_exp(track, 7),
                             data.TRACK_MAX_EXP, track)

    def test_thresholds_rise_with_level(self):
        for track in TRACKS:
            got = [data.gag_unlock_exp(track, l) for l in range(1, 8)]
            self.assertEqual(got, sorted(got), track)
            self.assertEqual(len(set(got)), 7, f"{track} has a repeat")

    def test_throw_and_squirt_start_cheaper_than_the_rest(self):
        """The two starting tracks, and the only ones whose level 2 and
        3 gags cost 10 and 50 rather than 20 and 100+."""
        for track in (Track.THROW, Track.SQUIRT):
            self.assertEqual(data.gag_unlock_exp(track, 2), 10)
            self.assertEqual(data.gag_unlock_exp(track, 3), 50)

    def test_the_damage_path_does_not_use_this_yet(self):
        """A guard. Wiring `gag_damage_from_exp` up needs `maxE`, which
        is not transcribed -- and guessing it would replace an honest
        stand-in with a confident wrong answer."""
        import solver.mechanics as mechanics

        self.assertEqual(mechanics.DAMAGE_TRAINED_FRACTION, 1.0)


if __name__ == "__main__":
    unittest.main()
