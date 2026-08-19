"""Organic gags.

Organic is a property of a whole track, not of one gag: a toon earns an
organic track from a ToonTask and every gag in it is organic after that.
It raises damage for every track and accuracy for Lure specifically.

The data tables have carried organic values all along; nothing set the
flag, so every organic gag was resolved at its non-organic value.
"""
import unittest

from solver import data, mechanics
from solver.simulator import apply_toon_action, toon_action_accuracy
from solver.state import Action, BattleState, CogState, ToonState, Track


def fight(organic=frozenset(), gags=None, level=5):
    gags = gags or {(Track.THROW, 5): 2, (Track.TRAP, 6): 1,
                    (Track.LURE, 5): 1}
    full = data.cog_max_hp(level)
    return BattleState(
        toon=ToonState(95, 95, {t: 7 for t, _l in gags}, dict(gags),
                       organic_tracks=organic),
        cogs=[CogState("yesman", "bossbot", level, full, full)])


class OrganicStateTest(unittest.TestCase):

    def test_defaults_to_nothing_organic(self):
        self.assertEqual(fight().toon.organic_tracks, frozenset())
        self.assertFalse(fight().toon.is_organic(Track.THROW))

    def test_is_organic_reports_the_track(self):
        st = fight(organic=frozenset({Track.THROW}))
        self.assertTrue(st.toon.is_organic(Track.THROW))
        self.assertFalse(st.toon.is_organic(Track.DROP))

    def test_clone_carries_it(self):
        st = fight(organic=frozenset({Track.THROW}))
        self.assertEqual(st.clone().toon.organic_tracks, frozenset({Track.THROW}))


class OrganicDamageTest(unittest.TestCase):

    def damage(self, organic):
        st = fight(organic=frozenset({Track.THROW}) if organic else frozenset())
        _healed, dealt = apply_toon_action(
            st, Action(Track.THROW, 5, 0), hit=True)
        return dealt

    def test_organic_throw_hits_harder(self):
        plain, organic = self.damage(False), self.damage(True)
        self.assertGreater(organic, plain)

    def test_it_matches_the_data_table(self):
        gag = data.gag(Track.THROW, 5)
        self.assertEqual(self.damage(False), gag.damage_at(1.0))
        self.assertEqual(self.damage(True), gag.damage_at(1.0, organic=True))


class OrganicTrapTest(unittest.TestCase):
    """A trap's damage lands later, so the trap has to remember how it
    was laid."""

    def sprung(self, organic):
        """Damage as REPORTED, not as inferred from the hp delta.

        This used to measure `before - cog.hp`, which only equalled the
        damage while hp was allowed to go negative. `CogState.take_damage`
        clamps it at 0 -- the party path already did, the two solo paths
        did not -- so a 180-damage TNT into a 42 hp cog now leaves hp at 0
        and the delta reads 42. The gag's damage did not change; the way
        this measured it did.
        """
        st = fight(organic=frozenset({Track.TRAP}) if organic else frozenset())
        apply_toon_action(st, Action(Track.TRAP, 6, 0), hit=True)
        self.assertTrue(st.cogs[0].status.trapped)
        self.assertEqual(st.cogs[0].status.trap_organic, organic)
        _healed, dealt = apply_toon_action(st, Action(Track.LURE, 5, 0),
                                           hit=True)
        return dealt

    def test_an_organic_trap_hits_harder_when_sprung(self):
        self.assertGreater(self.sprung(True), self.sprung(False))

    def test_trap_uses_the_same_damage_convention_as_every_other_track(self):
        """It used damage_at(0.0), the MINIMUM of the range, where every
        other track uses 1.0. TNT deals 90-180, so a trap resolved at 90
        against a same-level Grand Piano's 170 -- and any Trap-versus-
        anything comparison was measuring that, not the game."""
        self.assertEqual(self.sprung(False), data.gag(Track.TRAP, 6).damage_at(1.0))

    def test_springing_clears_the_organic_flag(self):
        st = fight(organic=frozenset({Track.TRAP}))
        apply_toon_action(st, Action(Track.TRAP, 6, 0), hit=True)
        apply_toon_action(st, Action(Track.LURE, 5, 0), hit=True)
        self.assertFalse(st.cogs[0].status.trap_organic)


class OrganicLureTest(unittest.TestCase):
    """Lure is the one track where organic changes accuracy, not damage."""

    def test_organic_lure_is_more_accurate(self):
        """Against a level 12 cog, whose defence pulls the roll well below
        the 95 cap -- at the cap both read 95 and the difference is
        invisible, which is exactly where a real toon stops caring too."""
        plain = toon_action_accuracy(fight(level=12),
                                     Action(Track.LURE, 5, 0))
        organic = toon_action_accuracy(
            fight(organic=frozenset({Track.LURE}), level=12),
            Action(Track.LURE, 5, 0))
        self.assertGreater(organic, plain)

    def test_the_bonus_is_invisible_at_the_accuracy_cap(self):
        """Worth pinning: against a weak cog organic Lure buys nothing,
        because the roll is already capped."""
        plain = toon_action_accuracy(fight(level=3), Action(Track.LURE, 5, 0))
        organic = toon_action_accuracy(
            fight(organic=frozenset({Track.LURE}), level=3),
            Action(Track.LURE, 5, 0))
        self.assertEqual(plain, organic)


if __name__ == "__main__":
    unittest.main()
