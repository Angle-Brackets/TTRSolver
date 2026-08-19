"""The scrappy regime must be harder without being incoherent.

Two ways a synthetic difficulty knob goes wrong, and both have already
happened once here:

  * it builds toons who could not have reached the street they are on
    (the incoherence `facility_position` exists to prevent), or
  * it strips the very tracks the regime is meant to lean on -- the
    first version squeezed `grind`, which decides how many tracks a toon
    ever trained, and Lure fell from 34% to 23%.
"""
import random
import statistics
import unittest

from solver import facility
from solver.rl import env as env_mod
from solver.state import Track


def _profile(sampler, n=200):
    laff, top, pooled = [], [], 0
    for seed in range(n):
        state = sampler(random.Random(seed))
        for toon in state.toons:
            laff.append(toon.max_laff)
            levels = [lv for (_t, lv), c in toon.gag_counts.items() if c > 0]
            top.append(max(levels) if levels else 0)
        tracks = {t for toon in state.toons
                  for (t, _lv), c in toon.gag_counts.items()
                  if c > 0 and toon.track_exp.get(t, 0) > 0}
        if {Track.LURE, Track.TOON_UP} <= tracks:
            pooled += 1
    return statistics.mean(laff), statistics.mean(top), pooled / n


class ScrappyRegimeTest(unittest.TestCase):

    def test_it_is_harder_on_both_axes(self):
        base_laff, base_top, _ = _profile(env_mod.facility_position)
        hard_laff, hard_top, _ = _profile(env_mod.scrappy_position)
        self.assertLess(hard_laff, base_laff, "scrappy toons need less laff")
        self.assertLess(hard_top, base_top,
                        "scrappy toons need lower gag levels -- that is the "
                        "half that stops them one-shotting a cog")

    def test_it_keeps_the_support_tracks_it_demands(self):
        _l, _t, base = _profile(env_mod.facility_position)
        _l2, _t2, hard = _profile(env_mod.scrappy_position)
        self.assertGreater(hard, base,
                           "the regime exists to force Lure and Toon-Up, so "
                           "the party must hold them more often, not less")
        self.assertGreater(hard, 0.6)

    def test_no_toon_falls_below_its_playground_floor(self):
        """Hardship squeezes toward the floor and never through it."""
        for seed in range(300):
            state = env_mod.scrappy_position(random.Random(seed))
            street = next(s for s in facility.STREETS if s[0] == state.street)
            low, _high = facility.PROGRESSION[street[1]]["laff"]
            for toon in state.toons:
                self.assertGreaterEqual(
                    toon.max_laff, low,
                    f"seed {seed}: {toon.max_laff} laff is below the "
                    f"{low} its playground awards, so this toon could not "
                    f"have reached {state.street}")

    def test_parties_are_still_party_sized(self):
        for seed in range(100):
            state = env_mod.scrappy_position(random.Random(seed))
            self.assertGreaterEqual(len(state.toons), 2)
            self.assertLessEqual(len(state.toons), 4)


if __name__ == "__main__":
    unittest.main()
