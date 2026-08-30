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
from solver.search import party_search as ps
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


class SlipsAreFinite(unittest.TestCase):
    """A pink slip is charged for, and charged by what is still coming.

    Nothing restocks slips, so they are the same kind of resource as a
    gag, and `_cheap_score` used to say outright that it charged nothing
    for one. The party duly spent all ten on the CEO's waiter battle and
    reached the Big Cheese holding 0.3 of 10 -- with battle two needing
    them badly enough that having them is worth 42 points of clear rate.

    The SHAPE is the part to protect. A flat price also suppressed slips
    in the final battle, and a slip carried out of the fight unspent is
    worth nothing at all.
    """

    def position(self, cogs_remaining):
        toon = ToonState(laff=100, max_laff=100,
                         track_exp={t: 7 for t in Track},
                         gag_counts={(t, l): 5 for t in Track
                                     for l in range(1, 8)},
                         organic_tracks=frozenset(), fires=5)
        return BattleState(
            toons=[toon],
            cogs=[CogState("head_hunter", "bossbot", 10, 132, 132)],
            cogs_remaining=cogs_remaining)

    def test_a_slip_costs_more_when_more_cogs_are_coming(self):
        fire = Action(track=None, level=0, target_index=0, fire=True)
        near = ps._cheap_score(self.position(0), 0, fire)
        far = ps._cheap_score(self.position(20), 0, fire)
        self.assertGreater(near, far,
                           "a slip should be dearer with a fight still "
                           "ahead of it")

    def test_a_slip_is_free_in_the_last_battle(self):
        """cogs_remaining == 0 means nothing left to save for, so the
        price must fall away entirely rather than to some floor."""
        fire = Action(track=None, level=0, target_index=0, fire=True)
        state = self.position(0)
        original = ps.FIRE_PRICE
        try:
            ps.FIRE_PRICE = 0.0
            free = ps._cheap_score(state, 0, fire)
            ps.FIRE_PRICE = 1000.0
            priced = ps._cheap_score(state, 0, fire)
        finally:
            ps.FIRE_PRICE = original
        self.assertEqual(free, priced)


class FireInTheExactSearchTest(unittest.TestCase):
    """The exact path, which nothing above reaches.

    Every test in this file so far goes through `apply_toon_action` or
    `party_search`, both of which branch on `action.fire` early. The
    EXACT search does not: `outcomes.action_outcomes` asks for the hit
    probability before it looks at what the action is.

    That left `toon_action_accuracy` as the only guard, and it tested
    `is_pass`, which is False for a fire by definition even though a
    fire has `track=None` exactly as a pass does. So the call fell
    through to `calc_toon_accuracy(None, 0, ...)` and raised

        KeyError: no gag at no track (a pass) level 0

    and since `legal_actions` offers one fire per live cog before it
    offers any gag, EXACT SEARCH RAISED ON EVERY POSITION WHERE THE
    TOON HELD A SLIP -- on the first branch it expanded.
    """

    def _tiny(self, fires):
        """Small enough for `solve` to run to the end, with a slip."""
        from solver import data
        hp = data.cog_max_hp(2)
        toon = ToonState(laff=30, max_laff=100, fires=fires,
                         gag_counts={(Track.THROW, 1): 2},
                         track_exp={Track.THROW: 2})
        cog = CogState(cog_type="cold_caller", department="sellbot",
                       level=2, hp=hp, max_hp=hp)
        return BattleState(cogs=[cog], toons=[toon])

    def test_a_fire_has_an_accuracy_and_it_is_certain(self):
        fire = Action(track=None, level=0, target_index=0, fire=True)
        self.assertEqual(
            simulator.toon_action_accuracy(self._tiny(1), fire), 100)

    def test_the_pass_guard_does_not_cover_a_fire(self):
        """Why the guard needs its own arm rather than riding on the
        pass. If this ever becomes True the comment above is stale."""
        fire = Action(track=None, level=0, target_index=0, fire=True)
        self.assertFalse(fire.is_pass)
        self.assertIsNone(fire.track)

    def test_action_outcomes_accepts_a_fire(self):
        from solver import outcomes
        fire = Action(track=None, level=0, target_index=0, fire=True)
        branches = outcomes.action_outcomes(self._tiny(1), fire)
        self.assertTrue(branches)
        self.assertAlmostEqual(sum(p for p, _s, _r in branches), 1.0)
        # It cannot miss, so the cog is gone down every branch.
        for _p, nxt, _r in branches:
            self.assertTrue(nxt.cogs[0].status.is_dead)
            self.assertEqual(nxt.toons[0].fires, 0)

    def test_exact_solve_runs_with_slips_in_the_pouch(self):
        from solver.search import expectimax
        value, action = expectimax.solve(self._tiny(1))
        self.assertIsNotNone(action)
        self.assertIsInstance(value, float)

    def test_value_never_falls_as_slips_rise(self):
        """The invariant that would have caught this on its own.

        Nothing forces a toon to spend a slip, so every line playable
        with none is still playable with two: the exact value must be
        non-decreasing in the slip count. It cannot be checked at all
        while the call raises, which is how the crash stayed hidden.

        Held here to one position so the suite stays fast. Offline it
        was swept wider: 400 random small positions at depth 2, zero
        violations, smallest gain from 0 to 2 slips +0.000 -- that is,
        a spare slip is sometimes worth nothing and never worth less
        than nothing. Exact solve to the end is far too slow for that
        breadth; it ran on three positions and gained on all three
        (-117.2 / 90.2 / 96.3 on the first).
        """
        from solver.search import expectimax
        values = [expectimax.solve(self._tiny(f))[0] for f in (0, 1, 2)]
        for fewer, more in zip(values, values[1:]):
            self.assertGreaterEqual(
                more, fewer - 1e-6,
                f"a spare slip lowered the exact value: {values}")


class DegenerateMenuTest(unittest.TestCase):
    """A menu of one kind of move is what let slips run away with the VP.

    A fire keys as (None, False), so ten of them collapse to a single
    `_track_key` and fill the top-k, leaving the judge nothing to
    compare against. `hybrid.PROBE_WHEN_DEGENERATE` notices that and
    widens the menu for that seat.

    Held out over 500 solo VPs at 8 cogs a round: with ten slips 68.6%
    against 54.0% (+138/-65, p<0.0001), and with none 47.4% against
    47.2% -- all of the gain, none of the cost. See `hybrid`.
    """

    def _values(self, n, finite):
        vals = [float("-inf")] * n
        for i in finite:
            vals[i] = 1.0
        return vals

    def _fire_indices(self):
        from solver.rl import env as env_mod
        return list(env_mod._FIRE_INDEX.values())

    def test_all_fires_is_degenerate(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid
        order = self._fire_indices()[:3]
        vals = self._values(len(env_mod.ACTIONS), order)
        self.assertTrue(hybrid._menu_is_degenerate(order, vals))

    def test_a_mixed_menu_is_not(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid
        fire = self._fire_indices()[0]
        gag = next(i for i, a in enumerate(env_mod.ACTIONS)
                   if a is not None and not a.fire)
        order = [fire, gag]
        vals = self._values(len(env_mod.ACTIONS), order)
        self.assertFalse(hybrid._menu_is_degenerate(order, vals))

    def test_two_gags_of_one_track_and_reach_are_degenerate(self):
        """Not a rule about fires. Any single `_track_key` counts --
        this is the shape the Drop-argmax collapse had too."""
        from solver.rl import env as env_mod
        from solver.search import hybrid
        by_key = {}
        for i, a in enumerate(env_mod.ACTIONS):
            if a is None or a.fire:
                continue
            by_key.setdefault(hybrid._track_key(a), []).append(i)
        order = next(v for v in by_key.values() if len(v) >= 2)[:2]
        vals = self._values(len(env_mod.ACTIONS), order)
        self.assertTrue(hybrid._menu_is_degenerate(order, vals))

    def test_masked_entries_are_ignored(self):
        """An -inf entry is not on the menu, so it must not count as a
        second kind of move and suppress the probe."""
        from solver.rl import env as env_mod
        from solver.search import hybrid
        fires = self._fire_indices()[:2]
        gag = next(i for i, a in enumerate(env_mod.ACTIONS)
                   if a is not None and not a.fire)
        vals = self._values(len(env_mod.ACTIONS), fires)   # gag is -inf
        self.assertTrue(hybrid._menu_is_degenerate(fires + [gag], vals))

    def test_the_flag_turns_it_off(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid
        order = self._fire_indices()[:3]
        vals = self._values(len(env_mod.ACTIONS), order)
        original = hybrid.PROBE_WHEN_DEGENERATE
        try:
            hybrid.PROBE_WHEN_DEGENERATE = False
            self.assertFalse(hybrid._menu_is_degenerate(order, vals))
        finally:
            hybrid.PROBE_WHEN_DEGENERATE = original


class FireFloorTest(unittest.TestCase):
    """A slip costs something on every board, not only mid-facility.

    `_quick_score` charged `FIRE_PRICE * cogs_remaining`, and nothing
    sets `cogs_remaining` on a board the live panel builds -- it cannot
    know what a VP or a building still holds. So a slip was free in
    every live fight, and one got spent on a level 1 Cold Caller with
    6 hp while the pouch held gags that would have killed it.
    """

    def _board(self, hp, fires=5):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track
        cog = CogState(cog_type="cold_caller", department="sellbot",
                       level=1, hp=hp, max_hp=data.cog_max_hp(1))
        toon = ToonState(laff=80, max_laff=100, fires=fires,
                         gag_counts={(Track.THROW, 4): 3,
                                     (Track.SQUIRT, 5): 3},
                         track_exp={Track.THROW: 7, Track.SQUIRT: 7})
        return BattleState(cogs=[cog], toons=[toon])

    def test_a_slip_is_not_free_when_nothing_is_known_to_remain(self):
        from solver.search import party_search as ps
        from solver.state import Action
        fire = Action(track=None, level=0, target_index=0, fire=True)
        state = self._board(6)
        self.assertEqual(state.cogs_remaining, 0,
                         "the premise: a panel board knows of no more cogs")
        original = ps.FIRE_FLOOR
        try:
            ps.FIRE_FLOOR = 0.0
            free = ps._quick_score(state, [fire])
            ps.FIRE_FLOOR = 50.0
            priced = ps._quick_score(state, [fire])
        finally:
            ps.FIRE_FLOOR = original
        self.assertLess(priced, free,
                        "the floor must cost something at horizon 0")

    def test_the_floor_is_on(self):
        """Measured free on held-out seeds -- 86.4% against 85.6% on a
        solo VP, and eight tenths of a slip cheaper. If this is ever
        turned off, the panel starts firing 6hp cogs again."""
        from solver.search import party_search as ps
        self.assertGreater(ps.FIRE_FLOOR, 0.0)
