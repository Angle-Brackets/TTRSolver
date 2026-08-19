"""Pink slips: instant, unmissable, one action, finite.

[CONFIRMED] wiki: a fire removes a targeted cog from the battle with a
cannon and eliminates both the suit and Skelecog form of a Version 2.0.
The owner confirms from play that it costs the toon's action for the
round and cannot miss.

They are deliberately absent from every default position. A fire is
strictly better than any gag against any cog, so a party holding them
does not play the game -- which is precisely why they need pinning down
rather than leaving loose.
"""
import unittest

from solver import simulator
from solver.state import Action, BattleState, CogState, Track, ToonState


def _state(fires=0, gags=None, cogs=None):
    toon = ToonState(laff=100, max_laff=100, fires=fires,
                     gag_counts=dict(gags or {(Track.THROW, 4): 2}),
                     track_exp={Track.THROW: 7, Track.LURE: 7})
    if cogs is None:
        cogs = [CogState(cog_type="Flunky", department="bossbot",
                         level=12, hp=196, max_hp=196)]
    return BattleState(cogs=cogs, toons=[toon])


class FireTest(unittest.TestCase):

    def test_not_offered_without_one(self):
        st = _state(fires=0)
        self.assertFalse(any(a.fire for a in simulator.legal_actions(st)))

    def test_offered_once_per_live_cog(self):
        cogs = [CogState(cog_type="Flunky", department="bossbot",
                         level=8, hp=90, max_hp=90) for _ in range(3)]
        cogs[1].status.is_dead = True
        st = _state(fires=2, cogs=cogs)
        fires = [a for a in simulator.legal_actions(st) if a.fire]
        self.assertEqual(sorted(a.target_index for a in fires), [0, 2])

    def test_a_fire_is_not_a_pass(self):
        """`is_pass` keys on track being None, which a fire also has."""
        self.assertFalse(Action(track=None, target_index=0, fire=True).is_pass)
        self.assertTrue(Action(track=None).is_pass)

    def test_it_kills_outright_and_cannot_miss(self):
        st = _state(fires=1)
        # hit=False: a fire does not consult the roll at all.
        simulator.apply_toon_action(
            st, Action(track=None, target_index=0, fire=True), hit=False)
        self.assertTrue(st.cogs[0].status.is_dead)
        self.assertEqual(st.cogs[0].hp, 0)

    def test_it_spends_exactly_one(self):
        st = _state(fires=2)
        simulator.apply_toon_action(
            st, Action(track=None, target_index=0, fire=True), hit=True)
        self.assertEqual(st.toons[0].fires, 1)

    def test_it_reports_no_damage(self):
        """Scorers read the second return value as damage dealt. A cog
        fired out of the fight was not damaged, and crediting 196 would
        make a fire the biggest hit in the game to every evaluator."""
        st = _state(fires=1)
        healed, damage = simulator.apply_toon_action(
            st, Action(track=None, target_index=0, fire=True), hit=True)
        self.assertEqual((healed, damage), (0, 0))

    def test_spending_one_you_do_not_have_raises(self):
        st = _state(fires=0)
        with self.assertRaises(ValueError):
            simulator.apply_toon_action(
                st, Action(track=None, target_index=0, fire=True), hit=True)

    def test_a_fire_counts_as_a_way_to_damage(self):
        """Otherwise `can_still_damage` calls a winnable fight lost and
        `legal_actions` returns nothing at all."""
        st = _state(fires=1, gags={(Track.LURE, 3): 5})
        self.assertTrue(st.can_still_damage())
        self.assertTrue(any(a.fire for a in simulator.legal_actions(st)))

    def test_lure_only_and_no_fires_is_still_lost(self):
        st = _state(fires=0, gags={(Track.LURE, 3): 5})
        self.assertFalse(st.can_still_damage())

    def test_fires_are_finite_so_the_measure_still_descends(self):
        """The termination argument: every fire action strictly reduces a
        counter nothing restores."""
        st = _state(fires=2, cogs=[
            CogState(cog_type="Flunky", department="bossbot",
                     level=8, hp=90, max_hp=90) for _ in range(3)])
        seen = []
        for target in (0, 1):
            simulator.apply_toon_action(
                st, Action(track=None, target_index=target, fire=True),
                hit=True)
            seen.append(st.toons[0].fires)
        self.assertEqual(seen, [1, 0])
        self.assertFalse(any(a.fire for a in simulator.legal_actions(st)))


if __name__ == "__main__":
    unittest.main()
