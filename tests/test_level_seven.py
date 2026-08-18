"""The level-7 ban, and the invariant that makes it safe.

`state.ALLOW_LEVEL_7` has to be honoured in TWO places or it is worse
than not having it. `simulator.legal_actions` decides what may be
thrown; `BattleState.can_still_damage` decides whether the battle is
already lost. The second keys on TRACKS and ignores levels, so a toon
holding nothing but Throw-7 reads as perfectly able to fight while the
first offers it nothing to throw -- a position every search treats as
playable and cannot play.
"""
import unittest

from solver import simulator
from solver import state as state_mod
from solver.state import BattleState, CogState, Track, ToonState


class LevelSevenBanTest(unittest.TestCase):

    def setUp(self):
        self._was = state_mod.ALLOW_LEVEL_7
        self.addCleanup(self._restore)

    def _restore(self):
        state_mod.ALLOW_LEVEL_7 = self._was

    def _state(self, counts):
        toon = ToonState(laff=80, max_laff=80, gag_counts=dict(counts),
                         track_exp={track: 7 for track, _l in counts})
        cog = CogState(cog_type="Flunky", department="bossbot",
                       level=8, hp=90, max_hp=90)
        return BattleState(cogs=[cog], toons=[toon])

    def test_constant_matches_the_data_table(self):
        from solver.data.gags import POUCH_EXEMPT_LEVEL
        self.assertEqual(state_mod.LEVEL_SEVEN, POUCH_EXEMPT_LEVEL)

    def test_sevens_offered_by_default(self):
        st = self._state({(Track.THROW, 7): 1, (Track.THROW, 5): 2})
        levels = {a.level for a in simulator.legal_actions(st)
                  if a.track == Track.THROW}
        self.assertIn(7, levels)
        self.assertIn(5, levels)

    def test_sevens_withheld_when_banned(self):
        state_mod.ALLOW_LEVEL_7 = False
        st = self._state({(Track.THROW, 7): 1, (Track.THROW, 5): 2})
        levels = {a.level for a in simulator.legal_actions(st)
                  if a.track == Track.THROW}
        self.assertNotIn(7, levels)
        self.assertIn(5, levels)

    def test_the_toggle_is_read_at_call_time(self):
        st = self._state({(Track.THROW, 7): 1})
        self.assertTrue(any(a.level == 7 for a in simulator.legal_actions(st)))
        state_mod.ALLOW_LEVEL_7 = False
        self.assertFalse(any(a.level == 7 for a in simulator.legal_actions(st)))
        state_mod.ALLOW_LEVEL_7 = True
        self.assertTrue(any(a.level == 7 for a in simulator.legal_actions(st)))

    def test_a_pouch_of_only_sevens_is_lost_when_banned(self):
        """The invariant. Both rules must agree, or the search hangs."""
        st = self._state({(Track.THROW, 7): 1})
        self.assertTrue(st.can_still_damage())

        state_mod.ALLOW_LEVEL_7 = False
        self.assertFalse(st.can_still_damage(),
                         "a banned gag cannot count as a way to damage a cog")
        # And the two agree: nothing legal, and the state knows it is lost.
        self.assertEqual(simulator.legal_actions(st), [])

    def test_lower_levels_keep_the_battle_alive(self):
        state_mod.ALLOW_LEVEL_7 = False
        st = self._state({(Track.THROW, 7): 1, (Track.THROW, 4): 3})
        self.assertTrue(st.can_still_damage())
        self.assertTrue(simulator.legal_actions(st))


if __name__ == "__main__":
    unittest.main()
