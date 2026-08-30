"""Unites: laff and gags put back mid-fight.

They matter because laff is the binding constraint of every fight this
solver loses. A solo VP ends with about seventy gags in the pouch and
no laff, at every wave size, and clears 0.0% at 16 and 20 cogs a round
across every policy and weight tried -- while the owner beats that
fight. Unites are what the model was missing.

Sources: the wiki for values, caps and cooldown; the owner from play
for the two things the wiki does not state -- that a unite costs no
action, and that it applies immediately in the planning phase.
"""
import unittest

from solver import unites
from solver.data import gags as gags_mod
from solver.state import ToonState, Track


def _toon(laff=40, max_laff=137, counts=None):
    return ToonState(laff, max_laff,
                     {Track.THROW: 7, Track.SQUIRT: 7, Track.DROP: 7},
                     dict(counts or {}), frozenset())


class ToonUpTest(unittest.TestCase):

    def test_the_five_values_are_the_wiki_s(self):
        self.assertEqual(unites.TOON_UP_VALUES, (20, 35, 50, 65, 80))

    def test_a_value_the_game_does_not_issue_is_refused(self):
        """Not rounded to the nearest. The point of the table is that
        the game offers nothing else."""
        with self.assertRaises(ValueError):
            unites.toon_up_restored(40, 10, 137)

    def test_healing_is_capped_by_headroom_not_by_the_unite(self):
        self.assertEqual(unites.toon_up_restored(80, 130, 137), 7)
        self.assertEqual(unites.toon_up_restored(80, 40, 137), 80)

    def test_it_never_overheals(self):
        toon = _toon(laff=130)
        unites.apply_toon_up(toon, 80)
        self.assertEqual(toon.laff, toon.max_laff)

    def test_using_one_starts_the_cooldown(self):
        toon = _toon()
        self.assertTrue(unites.available(toon))
        unites.apply_toon_up(toon, 20)
        self.assertFalse(unites.available(toon))
        self.assertEqual(toon.unite_cooldown, unites.COOLDOWN_ROUNDS)


class GagUpTest(unittest.TestCase):

    def test_a_single_track_is_capped_at_seven(self):
        toon = _toon(counts={(Track.THROW, 1): 0})
        self.assertLessEqual(unites.apply_gag_up(toon, Track.THROW), 7)

    def test_all_tracks_is_capped_at_thirty(self):
        """Seven per track across seven tracks would be 49. The game
        allows 30, and using one cap for both is the obvious error."""
        toon = _toon()
        self.assertLessEqual(unites.apply_gag_up(toon, None), 30)

    def test_it_does_not_restock_the_exempt_tier(self):
        """Level 7 gags do not count against the pouch. Refilling them
        would hand the search an endless supply of the strongest gag in
        the game, so they are left out rather than guessed at."""
        toon = _toon()
        unites.apply_gag_up(toon, None)
        sevens = sum(n for (_t, level), n in toon.gag_counts.items()
                     if level >= gags_mod.POUCH_EXEMPT_LEVEL)
        self.assertEqual(sevens, 0)

    def test_it_respects_each_gag_s_carry_limit(self):
        toon = _toon()
        unites.apply_gag_up(toon, None)
        for (track, level), n in toon.gag_counts.items():
            self.assertLessEqual(n, gags_mod.gag(track, level).max_carry,
                                 f"{track} {level} over its carry limit")

    def test_it_only_restocks_tracks_the_toon_owns(self):
        toon = _toon()
        unites.apply_gag_up(toon, None)
        for (track, _lv) in toon.gag_counts:
            self.assertGreater(toon.track_exp.get(track, 0), 0,
                               f"restocked {track}, which the toon lacks")


class CooldownTest(unittest.TestCase):

    def test_three_rounds(self):
        toon = _toon()
        unites.apply_toon_up(toon, 20)
        for _ in range(unites.COOLDOWN_ROUNDS - 1):
            unites.tick_cooldown(toon)
            self.assertFalse(unites.available(toon))
        unites.tick_cooldown(toon)
        self.assertTrue(unites.available(toon))

    def test_it_never_goes_negative(self):
        toon = _toon()
        for _ in range(5):
            unites.tick_cooldown(toon)
        self.assertEqual(toon.unite_cooldown, 0)

    def test_the_cooldown_survives_a_clone(self):
        """`state_key` reads it, so a clone that dropped it would let
        the memo answer about one position with another's value -- the
        bug `fires` already had in `ToonState.clone`."""
        from solver.state import BattleState, CogState
        from solver import data
        hp = data.cog_max_hp(2)
        cog = CogState(department="sellbot", cog_type="cold_caller",
                       level=2, hp=hp, max_hp=hp)
        toon = _toon()
        unites.apply_toon_up(toon, 20)
        state = BattleState(toon=toon, cogs=[cog])
        self.assertEqual(state.clone().toons[0].unite_cooldown,
                         unites.COOLDOWN_ROUNDS)


class TheRulesThatAreNotInTheWikiTest(unittest.TestCase):

    def test_a_unite_costs_no_action(self):
        """[OWNER, from play]. It decides the whole model: a unite must
        never appear in the action table competing with a gag."""
        self.assertFalse(unites.costs_the_round())

    def test_a_unite_is_dearer_than_a_pink_slip(self):
        """[OWNER] "weigh them more than Fires". Costing no gag and no
        round makes a unite cheap WITHIN a battle and says nothing
        about its cost outside one -- they come only from beating the
        CFO."""
        from solver.search import party_search as ps
        self.assertGreater(unites.UNITE_PRICE, ps.FIRE_PRICE)
        self.assertGreater(unites.UNITE_PRICE, ps.FIRE_FLOOR)
