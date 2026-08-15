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


class WindowTest(unittest.TestCase):
    """maxE is the next gag's threshold. [CONFIRMED] -- every gag
    infobox carries `prevexp` (its own) and `nextexp` (the next gag's),
    checked across Cupcake, Whole Cream Pie, Big Magnet, Foghorn and
    Grand Piano, four tracks between them."""

    def test_a_window_runs_to_the_next_gag(self):
        self.assertEqual(data.gag_exp_window(Track.THROW, 5), (2000, 6000))
        self.assertEqual(data.gag_exp_window(Track.SOUND, 2), (20, 200))

    def test_level_seven_has_no_window_and_needs_none(self):
        """Those gags have one fixed damage, so nothing interpolates.

        Checked only on the tracks that deal damage -- Lure and Toon-Up
        raise from `damage_at`, correctly, having none.
        """
        for track in TRACKS:
            low, high = data.gag_exp_window(track, 7)
            self.assertEqual(low, high)
            self.assertEqual(low, data.TRACK_MAX_EXP)
        for track in (Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP):
            gag = data.gag(track, 7)
            self.assertEqual(
                gag.damage_at(0.0, False), gag.damage_at(1.0, False),
                f"{track} level 7 has a damage RANGE, so a zero-width "
                f"window would divide by nearly nothing")

    def test_windows_tile_the_track_without_gaps(self):
        for track in TRACKS:
            for level in range(1, 7):
                self.assertEqual(data.gag_exp_window(track, level)[1],
                                 data.gag_exp_window(track, level + 1)[0],
                                 f"{track} level {level} leaves a gap")

    def test_the_formula_accepts_a_real_window(self):
        """A maxed toon at the top of a level 6 window deals max."""
        import solver.mechanics as mechanics

        low, high = data.gag_exp_window(Track.THROW, 6)
        gag = data.gag(Track.THROW, 6)
        lo_d, hi_d = gag.damage_at(0.0, False), gag.damage_at(1.0, False)
        self.assertEqual(
            mechanics.gag_damage_from_exp(high, high, low, lo_d, hi_d), hi_d)
        self.assertEqual(
            mechanics.gag_damage_from_exp(low, high, low, lo_d, hi_d), lo_d)
