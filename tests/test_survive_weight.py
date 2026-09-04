"""`QUICK_W["survive"]` and the property that makes it safe.

The term reads laff LEVEL, which no other term in `_quick_score` can
see -- that is why it exists, and why a heal was worth exactly zero
without it. The danger is the other half: if it also moved with the
PLAN it would reorder ordinary gag choices, and measured at weight 400
that cost solo buildings 26.0% -> 10.0% on one seed block and
27.0% -> 14.5% on another, p<0.001 both, because killing or luring a
cog lowers `expected_incoming` and the term then paid for damage
prevention a second time on top of `prevented`.

Pinning `incoming` to the pre-plan board fixes that, and these tests
pin the consequence: the term contributes the SAME constant to every
candidate in a menu, so it cannot reorder one.
"""
import random
import unittest

from solver import simulator, vp as vp_mod
from solver.rl import env as env_mod
from solver.search import party_search as ps
from solver.search import weights as ps_weights
from solver.state import ToonState, Track


def _party_board(seed=990000, laff=60, size=12):
    old = vp_mod.COG_ROUND, vp_mod.SKELECOG_ROUND
    vp_mod.COG_ROUND = vp_mod.SKELECOG_ROUND = size

    def sampler(rng):
        st = env_mod.facility_position(rng)
        party = []
        for _ in range(3):
            toon = ToonState(laff, 137, {t: 7 for t in Track}, {},
                             frozenset({Track.THROW}), pouch_capacity=80)
            env_mod.restock(toon, rng)
            toon.fires = 5
            party.append(toon)
        st.toons = party
        st.kind = "vp"
        st.street = None
        return st

    try:
        e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                              coordinated=True)
        e.reset()
        return e.state
    finally:
        vp_mod.COG_ROUND, vp_mod.SKELECOG_ROUND = old


class ConstantAcrossTheMenuTest(unittest.TestCase):

    def setUp(self):
        self._w = ps_weights.QUICK_W["survive"]

    def tearDown(self):
        ps_weights.QUICK_W["survive"] = self._w

    def _contribution(self, state, plan):
        ps_weights.QUICK_W["survive"] = 0.0
        lo = ps._quick_score(state, plan)
        ps_weights.QUICK_W["survive"] = 800.0
        hi = ps._quick_score(state, plan)
        return round(hi - lo, 6)

    def test_every_candidate_gets_the_same_contribution(self):
        state = _party_board()
        state.toons[0].laff = 20
        actions = [a for a in simulator.legal_actions(state)
                   if a.track is not None][:12]
        self.assertGreater(len(actions), 4)
        seen = {self._contribution(state, [a, None, None]) for a in actions}
        self.assertEqual(len(seen), 1, "survive reordered the menu: " + str(seen))

    def test_a_heal_and_an_attack_agree(self):
        """The case the solo gate cannot reach. A Toon-Up gag is the
        only ordinary action that raises laff, so if anything breaks the
        constancy it is this one."""
        state = _party_board()
        state.toons[0].laff = 20
        heal = [a for a in simulator.legal_actions(state)
                if a.track is Track.TOON_UP]
        hit = [a for a in simulator.legal_actions(state)
               if a.track is Track.THROW]
        self.assertTrue(heal and hit)
        self.assertEqual(self._contribution(state, [heal[0], None, None]),
                         self._contribution(state, [hit[0], None, None]))

    def test_it_equals_the_boards_own_survival(self):
        state = _party_board()
        state.toons[0].laff = 20
        hit = [a for a in simulator.legal_actions(state)
               if a.track is Track.THROW][0]
        self.assertAlmostEqual(
            self._contribution(state, [hit, None, None]) / 800.0,
            ps.survival_rounds(state), places=6)


class IncomingOverrideTest(unittest.TestCase):

    def test_the_override_is_what_holds_it_still(self):
        """Without it the term moves with the plan -- the behaviour the
        pin removes. Guards against someone dropping the argument."""
        state = _party_board()
        board = ps.expected_incoming(state)
        self.assertAlmostEqual(ps.survival_rounds(state, incoming=board),
                               ps.survival_rounds(state), places=9)

    def test_a_quieter_board_survives_longer(self):
        state = _party_board()
        near = ps.survival_rounds(state, incoming=100.0)
        far = ps.survival_rounds(state, incoming=10.0)
        self.assertLess(near, far)

    def test_nothing_swinging_falls_back_to_what_wakes_up(self):
        """Zero incoming used to read the cap. It no longer does when
        the board still has live cogs on it.

        A LURE IS A REPRIEVE, NOT SAFETY. With the field asleep incoming
        is 0, and dividing laff by it saturated this term, so 120 laff
        and 4 laff both scored the cap -- the one term that can see a
        toon about to die was blind exactly in the window where healing
        is safe. It now measures against `latent_incoming`, the same
        board with the sleepers counted.
        """
        state = _party_board()
        got = ps.survival_rounds(state, incoming=0.0)
        self.assertLess(got, ps_weights.SURVIVAL_CAP)
        self.assertAlmostEqual(
            got, min(ps_weights.SURVIVAL_CAP,
                     min(t.laff for t in state.toons if t.laff > 0)
                     / ps.latent_incoming(state)), places=9)

    def test_an_empty_board_still_reads_the_cap(self):
        """Nothing alive is genuinely safe, and the fallback must not
        pretend otherwise -- there is no threat to measure against."""
        state = _party_board()
        # Emptied rather than zeroed: `hp = 0` does not retire a cog,
        # because a Version 2.0 has a second layer behind the suit and
        # `active_cogs` still counts it.
        state.cogs = []
        self.assertEqual(ps.survival_rounds(state, incoming=0.0),
                         ps_weights.SURVIVAL_CAP)

    def test_the_fallback_can_be_turned_off(self):
        saved = ps_weights.LURE_IS_A_REPRIEVE
        ps_weights.LURE_IS_A_REPRIEVE = False
        try:
            self.assertEqual(ps.survival_rounds(_party_board(), incoming=0.0),
                             ps_weights.SURVIVAL_CAP)
        finally:
            ps_weights.LURE_IS_A_REPRIEVE = saved

    def test_it_is_capped(self):
        state = _party_board()
        self.assertEqual(ps.survival_rounds(state, incoming=0.001),
                         ps_weights.SURVIVAL_CAP)


class ShippedValueTest(unittest.TestCase):

    def test_the_swept_weight_is_what_shipped(self):
        self.assertEqual(ps_weights.QUICK_W["survive"], 400.0)


if __name__ == "__main__":
    unittest.main()


class NothingIsOfferedWithoutEvidenceTest(unittest.TestCase):
    """`OFFER_UNITES` and `OFFER_SOS` are on, and that must stay safe
    for live advice.

    Neither consumable is visible to the readers: the Local API reports
    no unite pouch and nothing reads SOS cards off the screen, so
    `session.build_state` sets neither field. Both therefore have to
    default to "hold none" rather than "hold anything", or the overlay
    would advise spending a resource it has no evidence of -- the
    invented-state failure CLAUDE.md warns about.
    """

    def test_a_freshly_built_toon_holds_neither(self):
        # Exactly the constructor call `session.build_state` makes: no
        # unites, no cards, no fires named.
        toon = ToonState(laff=85, max_laff=137,
                         track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 4): 3},
                         organic_tracks=frozenset())
        self.assertEqual(toon.unites_held, 0)
        self.assertEqual(dict(toon.sos_cards), {})

    def test_and_so_is_offered_neither(self):
        from solver import unites
        from solver.search import hybrid
        toon = ToonState(laff=85, max_laff=137,
                         track_exp={Track.THROW: 7},
                         gag_counts={(Track.THROW, 4): 3},
                         organic_tracks=frozenset())
        state = _party_board()
        state.toons = [toon]
        self.assertFalse(unites.available(toon))
        self.assertEqual(list(unites.candidates(toon)), [])
        self.assertEqual(hybrid._sos_probes(state, 0), [])

    def test_the_flags_really_are_on(self):
        from solver.search import hybrid
        self.assertTrue(hybrid.OFFER_UNITES)
        self.assertTrue(hybrid.OFFER_SOS)


class BothEnginesOfferUnitesTest(unittest.TestCase):
    """TTR could not use a unite at all.

    Unites were a wrapper that existed only around `hybrid.climb`, and
    the TTR overlay runs `advise` -> `expectimax.best_action_iterative`.
    So the whole feature was invisible on that client, not by decision
    but because the two engines had no way to share the comparison.
    """

    def test_the_wrapper_is_engine_agnostic(self):
        from solver import unites
        self.assertTrue(callable(unites.best_with_unite))

    def test_it_picks_nothing_when_none_are_held(self):
        from solver import unites
        state = _party_board()
        for toon in state.toons:
            toon.unites_held = 0
        calls = []

        def value_of(st):
            calls.append(st)
            return "answer", 10.0

        choice, answer = unites.best_with_unite(state, value_of)
        self.assertIsNone(choice)
        self.assertEqual(answer, "answer")
        # Exactly one evaluation: the no-unite baseline. This is what
        # keeps the exact search's latency unchanged for a player whose
        # holdings are unknown.
        self.assertEqual(len(calls), 1)

    def test_a_unite_must_beat_the_price_not_merely_the_baseline(self):
        from solver import unites
        state = _party_board(laff=40)
        state.toons[0].unites_held = 5
        seen = {"n": 0}

        def value_of(st):
            seen["n"] += 1
            # Every unite looks better, but by less than it costs.
            return "u" if seen["n"] > 1 else "base", (
                10.0 + unites.UNITE_PRICE - 1.0 if seen["n"] > 1 else 10.0)

        choice, answer = unites.best_with_unite(state, value_of)
        self.assertGreater(seen["n"], 1, "no candidate was evaluated")
        self.assertIsNone(choice)
        self.assertEqual(answer, "base")

    def test_a_unite_that_clears_the_price_wins(self):
        from solver import unites
        state = _party_board(laff=40)
        state.toons[0].unites_held = 5
        seen = {"n": 0}

        def value_of(st):
            seen["n"] += 1
            return "u" if seen["n"] > 1 else "base", (
                10.0 + unites.UNITE_PRICE + 1.0 if seen["n"] > 1 else 10.0)

        choice, answer = unites.best_with_unite(state, value_of)
        self.assertIsNotNone(choice)
        self.assertEqual(answer, "u")

    def test_the_search_path_reports_one(self):
        from solver.live import advise
        self.assertTrue(hasattr(advise, "LAST_UNITE"))


class TrappedLureTest(unittest.TestCase):
    """Reported from live play: a lone trapped level 5 Ambulance Chaser
    with a Trapdoor in front, advised a GROUP Small Magnet.

    `_track_key` is (track, group), so the menu carries the policy's
    favourite single lure and its favourite group lure -- and the LEVEL
    inside each is the policy's alone. Nothing compared one level
    against another, so the cheap single lure the scorer prefers was
    never offered.
    """

    def _board(self, trapped=True):
        from solver import data
        from solver.state import BattleState, CogState
        hp = data.cog_max_hp(5)
        cog = CogState(department="lawbot", cog_type="ambulance_chaser",
                       level=5, hp=hp, max_hp=hp)
        if trapped:
            cog.status.trapped = True
            cog.status.trap_level = 5
        counts = {(Track.LURE, lv): 5 for lv in range(1, 8)}
        for track in (Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP):
            for level in range(1, 8):
                counts[(track, level)] = 5
        toon = ToonState(80, 137, {t: 7 for t in Track}, counts,
                         frozenset({Track.THROW}), pouch_capacity=80)
        return BattleState(toon=toon, cogs=[cog])

    def test_every_lure_lands_at_the_same_rate_on_a_trapped_cog(self):
        """Why the CHEAPEST is right rather than the most accurate: the
        trapped bonus takes all of them to the 95 cap, so the printed
        accuracy stops being a difference at all."""
        from solver import simulator
        from solver.state import Action
        seen = set()
        for level in range(1, 8):
            record = []
            probe = self._board().clone()
            simulator.apply_party_round(
                probe, [Action(track=Track.LURE, level=level, target_index=0)],
                hits=[True], record=record)
            seen.add(record[0][2])
        self.assertEqual(seen, {95})

    def test_the_scorer_prefers_the_cheap_one(self):
        from solver.state import Action
        cheap = ps._quick_score(
            self._board(), [Action(track=Track.LURE, level=1, target_index=0)],
            random.Random(0))
        dear = ps._quick_score(
            self._board(), [Action(track=Track.LURE, level=5, target_index=0)],
            random.Random(0))
        self.assertGreater(cheap, dear)

    def test_it_no_longer_advises_a_group_lure_on_one_cog(self):
        """A budget must cover the menu. `spent >= budget` breaks the
        scoring loop, so a wide menu with a small budget never reaches
        the probes appended after the policy's own entries -- at width
        16 and budget 8 this board picks Foghorn, wasting an armed trap,
        and at budget 24 (what the panel runs) it picks the $1 Bill.
        """
        from solver.search import hybrid
        plan = hybrid.climb(self._board(), random.Random(0), budget=24)
        self.assertIsNotNone(plan[0])
        self.assertEqual(plan[0].track, Track.LURE)
        self.assertIsNotNone(plan[0].target_index,
                             "a group lure on a single cog")

    def test_the_probe_fires_only_on_a_trapped_board(self):
        """Narrow on purpose. Offering cheap gags everywhere starves the
        track sweep at the panel's budget of 8: measured, difficulty 9
        fell 60% to 42% and the VP 94% to 81%."""
        from solver.search import hybrid
        self.assertFalse(hybrid.TARGETED_PROBES_FIRST)
        self.assertEqual(hybrid._cheapest_lures(self._board(False), 0, None),
                         hybrid._cheapest_lures(self._board(False), 0, None))
        untrapped = hybrid.climb(self._board(False), random.Random(0),
                                 budget=8)
        self.assertIsNotNone(untrapped[0])


class DeathLineTest(unittest.TestCase):
    """"Heal or kill" -- the rule, and why it is not a laff threshold.

    [OWNER] "if the expected incoming from the cogs, assuming they are
    all unlured, is greater than the current HP, shouldn't we heal" and
    "we should heal or kill". `toons_at_risk` cannot answer it: that one
    SKIPS a lured cog on purpose, so that luring visibly lowers it. Both
    questions are worth asking and they disagree on a sleeping field.
    """

    def _lured_board(self, laff):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track

        cogs = []
        for level in (11, 12, 11, 12):
            hp = data.cog_max_hp(level)
            cog = CogState(cog_type="mr_hollywood", department="sellbot",
                           level=level, hp=hp, max_hp=hp)
            cog.status.apply_lure(80, 3, None)
            cogs.append(cog)
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(laff, 137, {t: 7 for t in tracks},
                         {(t, l): 3 for t in tracks for l in range(1, 8)},
                         frozenset())
        return BattleState(toons=[toon], cogs=cogs)

    def test_a_sleeping_field_still_counts_against_you(self):
        """The difference from `toons_at_risk`, stated as a test."""
        state = self._lured_board(25)
        self.assertEqual(0.0, ps.toons_at_risk(state))
        self.assertEqual(1.0, ps.past_the_death_line(state))

    def test_a_healthy_toon_is_not_past_it(self):
        self.assertEqual(0.0, ps.past_the_death_line(self._lured_board(120)))

    def test_killing_enough_clears_it_without_healing(self):
        """Why the threshold is not a laff number. A Wedding Cake kills
        two of the four, dropping the woken round from 84 to 44 -- under
        a toon on 60, who therefore does not have to heal."""
        from solver import simulator
        from solver.state import Action, Track

        state = self._lured_board(60)
        self.assertEqual(1.0, ps.past_the_death_line(
            self._lured_board(40)), "40 laff should be past the line")
        probe = state.clone()
        simulator.apply_party_round(
            probe, [Action(track=Track.THROW, level=7, target_index=None)],
            hits=[True])
        self.assertLess(len(list(probe.active_cogs())), 4)
        self.assertEqual(0.0, ps.past_the_death_line(probe))

    def test_the_same_kill_does_not_save_a_lower_toon(self):
        from solver import simulator
        from solver.state import Action, Track

        probe = self._lured_board(25).clone()
        simulator.apply_party_round(
            probe, [Action(track=Track.THROW, level=7, target_index=None)],
            hits=[True])
        self.assertEqual(1.0, ps.past_the_death_line(probe))

    def test_it_ships_off_and_that_is_recorded(self):
        """Measured at 0 against 300 on the solo VP and moved nothing.
        The term stays wired; the weight stays honest."""
        self.assertEqual(0.0, ps_weights.QUICK_W["deadline"])
