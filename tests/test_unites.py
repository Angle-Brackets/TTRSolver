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


def _toon(laff=40, max_laff=137, counts=None, held=10):
    # `held` is explicit because `unites_held` defaults to 0 and a toon
    # holding none is offered none. The live readers cannot see a unite
    # pouch, so "unknown" has to mean "offer nothing".
    return ToonState(laff, max_laff,
                     {Track.THROW: 7, Track.SQUIRT: 7, Track.DROP: 7},
                     dict(counts or {}), frozenset(), unites_held=held)


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


class PouchCapacityTest(unittest.TestCase):
    """A Gag-Up cannot fill past what the toon can carry.

    The wiki's two caps -- 7 for one track, 30 for all -- are per USE.
    The pouch is a third cap and leaving it out let a restock add 30
    every time with no ceiling: a toon restocked five times carried 266
    gags against a capacity of 80, and a VP trace showed 567.
    """

    def _full(self):
        import random
        from solver.rl import env as env_mod
        toon = ToonState(100, 137,
                         {t: 7 for t in Track if t is not Track.TOON_UP},
                         {}, frozenset(), pouch_capacity=80)
        env_mod.restock(toon, random.Random(3))
        return toon

    def _pouch(self, toon):
        return sum(n for (_t, level), n in toon.gag_counts.items()
                   if level < gags_mod.POUCH_EXEMPT_LEVEL)

    def test_a_full_pouch_gains_nothing(self):
        toon = self._full()
        self.assertEqual(self._pouch(toon), toon.pouch_capacity)
        toon.unite_cooldown = 0
        self.assertEqual(unites.apply_gag_up(toon, None), 0)

    def test_repeated_restocks_stop_at_capacity(self):
        toon = self._full()
        toon.gag_counts = {k: max(0, v - 6) for k, v in toon.gag_counts.items()}
        for _ in range(5):
            toon.unite_cooldown = 0
            unites.apply_gag_up(toon, None)
            self.assertLessEqual(self._pouch(toon), toon.pouch_capacity,
                                 "restocked past the pouch")

    def test_it_still_fills_a_pouch_with_room(self):
        """The cap must not be so eager it refuses a legitimate restock."""
        toon = self._full()
        toon.gag_counts = {k: 0 for k in toon.gag_counts}
        toon.unite_cooldown = 0
        self.assertGreater(unites.apply_gag_up(toon, None), 0)


class FillOrderTest(unittest.TestCase):
    """A restock fills from the TOP DOWN, evenly across tracks. [OWNER]

    Filling level 1 upward, one track at a time, spends the whole
    thirty on Squirting Flowers and Cupcakes and leaves the gags worth
    having untouched -- which made a Gag-Up look nearly worthless and
    was the first version of this.
    """

    def _empty(self):
        return ToonState(100, 137,
                         {t: 7 for t in Track if t is not Track.TOON_UP},
                         {}, frozenset(), pouch_capacity=80)

    def test_all_tracks_fills_the_top_first(self):
        toon = self._empty()
        unites.apply_gag_up(toon, None)
        low = sum(n for (_t, level), n in toon.gag_counts.items()
                  if level <= 4)
        high = sum(n for (_t, level), n in toon.gag_counts.items()
                   if level >= 5)
        self.assertEqual(low, 0, "spent budget on the bottom of the pouch")
        self.assertGreater(high, 0)

    def test_all_tracks_spreads_rather_than_draining_one(self):
        toon = self._empty()
        unites.apply_gag_up(toon, None)
        touched = {track for (track, _lv), n in toon.gag_counts.items()
                   if n > 0}
        self.assertGreaterEqual(len(touched), 5,
                                f"only filled {len(touched)} tracks")

    def test_a_single_track_unite_focuses_on_that_track(self):
        """[OWNER] "unless it's a single gag track which obviously then
        it will focus in on that one from the top down"."""
        toon = self._empty()
        added = unites.apply_gag_up(toon, Track.THROW)
        self.assertEqual(added, unites.GAG_UP_SINGLE_TRACK_MAX)
        elsewhere = sum(n for (track, _lv), n in toon.gag_counts.items()
                        if track is not Track.THROW)
        self.assertEqual(elsewhere, 0, "leaked into other tracks")
        self.assertEqual(toon.gag_counts.get((Track.THROW, 6), 0),
                         gags_mod.gag(Track.THROW, 6).max_carry,
                         "did not fill the top of the track first")

    def test_it_never_exceeds_a_gag_s_own_limit(self):
        """The cap that was always right, kept honest through the
        rewrite of the fill order."""
        toon = self._empty()
        for _ in range(6):
            toon.unite_cooldown = 0
            unites.apply_gag_up(toon, None)
        for (track, level), n in toon.gag_counts.items():
            self.assertLessEqual(n, gags_mod.gag(track, level).max_carry)


class CloneIsolationTest(unittest.TestCase):
    """A restock on a clone must not reach the state it was cloned from.

    `ToonState.clone` SHARES `gag_counts` -- copy-on-write, with
    `_spend_gag` copying before it mutates. `apply_gag_up` did not
    copy, so every unite candidate `climb` evaluated AND DISCARDED
    still refilled the real pouch. Traps grew from 25 to 51 across a VP
    in which no Gag-Up was ever chosen, which is how it surfaced.
    """

    def _state(self):
        from solver import data
        from solver.state import BattleState, CogState
        hp = data.cog_max_hp(4)
        toon = ToonState(60, 137,
                         {t: 7 for t in Track if t is not Track.TOON_UP},
                         {(Track.THROW, 5): 1}, frozenset(),
                         pouch_capacity=80)
        cog = CogState(department="sellbot", cog_type="glad_hander",
                       level=4, hp=hp, max_hp=hp)
        return BattleState(toon=toon, cogs=[cog])

    def test_restocking_a_clone_leaves_the_original_alone(self):
        state = self._state()
        before = dict(state.toons[0].gag_counts)
        unites.apply_gag_up(state.clone().toons[0], None)
        self.assertEqual(state.toons[0].gag_counts, before)

    def test_healing_a_clone_leaves_the_original_alone(self):
        state = self._state()
        laff = state.toons[0].laff
        unites.apply_toon_up(state.clone().toons[0], 50)
        self.assertEqual(state.toons[0].laff, laff)

    def test_the_clone_itself_really_is_restocked(self):
        """The isolation must not be achieved by doing nothing."""
        state = self._state()
        clone = state.clone()
        self.assertGreater(unites.apply_gag_up(clone.toons[0], None), 0)
        self.assertNotEqual(clone.toons[0].gag_counts,
                            state.toons[0].gag_counts)


class TieBreakTest(unittest.TestCase):
    """An all-tracks restock is offered before any single track.

    They usually TIE on a one-round score -- both put the same best gag
    in hand this round -- and `climb` breaks ties by evaluation order.
    Measured: Gag-Up lure and Gag-Up all both scored 3985.0 on the same
    board, and the single track won, taking 7 gags instead of 30 for
    the same cooldown. The extra 23 pay off in later rounds, which a
    one-round scorer cannot see, so the tie is broken here.
    """

    def test_all_tracks_comes_first(self):
        toon = ToonState(70, 137,
                         {t: 7 for t in Track if t is not Track.TOON_UP},
                         {(Track.TRAP, 4): 10}, frozenset(),
                         pouch_capacity=80, unites_held=10)
        gag_ups = [c for c in unites.candidates(toon) if c[0] == "gag_up"]
        self.assertTrue(gag_ups)
        self.assertIsNone(gag_ups[0][1],
                          "a single track is offered before all tracks")

    def test_all_tracks_really_does_restore_more(self):
        """The premise. If a single track ever gave more, the ordering
        would be wrong rather than merely arbitrary."""
        def fresh():
            return ToonState(70, 137,
                             {t: 7 for t in Track if t is not Track.TOON_UP},
                             {}, frozenset(), pouch_capacity=80)
        every = unites.apply_gag_up(fresh(), None)
        one = unites.apply_gag_up(fresh(), Track.THROW)
        self.assertGreater(every, one)


class StockTest(unittest.TestCase):
    """A unite has to be HELD. The cooldown alone left the supply
    unlimited, which took solo buildings from 26% to 100% on one seed
    block and 27% to 99% on another -- the solver spending about four
    unites a building it had no evidence of holding."""

    def test_none_held_means_none_available(self):
        self.assertFalse(unites.available(_toon(held=0)))

    def test_none_held_means_nothing_offered(self):
        self.assertEqual(list(unites.candidates(_toon(laff=40, held=0))), [])

    def test_the_default_is_none(self):
        """The live readers cannot see a unite pouch, so an unbuilt
        field must offer nothing rather than everything."""
        bare = ToonState(40, 137, {Track.THROW: 7}, {}, frozenset())
        self.assertEqual(bare.unites_held, 0)
        self.assertFalse(unites.available(bare))

    def test_using_one_spends_one(self):
        toon = _toon(held=3)
        unites.apply_toon_up(toon, 20)
        self.assertEqual(toon.unites_held, 2)

    def test_a_gag_up_spends_one_too(self):
        toon = _toon(held=3, counts={(Track.THROW, 1): 1})
        unites.apply_gag_up(toon, Track.THROW)
        self.assertEqual(toon.unites_held, 2)

    def test_the_last_one_runs_out(self):
        toon = _toon(held=1)
        unites.apply_toon_up(toon, 20)
        for _ in range(unites.COOLDOWN_ROUNDS):
            unites.tick_cooldown(toon)
        self.assertEqual(toon.unite_cooldown, 0)
        self.assertFalse(unites.available(toon),
                         "cooldown expired but the pouch is empty")

    def test_it_never_goes_negative(self):
        toon = _toon(held=0)
        unites.apply_toon_up(toon, 20)
        self.assertEqual(toon.unites_held, 0)

    def test_a_clone_carries_the_stock(self):
        """Anything spent must survive `clone`, or it evaporates and a
        sweep reports usage that never happened -- the bug `fires` has
        a standing comment about."""
        from solver.state import BattleState, CogState
        from solver import data
        hp = data.cog_max_hp(3)
        state = BattleState(toon=_toon(held=7),
                            cogs=[CogState(department="sellbot",
                                           cog_type="cold_caller", level=3,
                                           hp=hp, max_hp=hp)])
        self.assertEqual(state.clone().toons[0].unites_held, 7)
