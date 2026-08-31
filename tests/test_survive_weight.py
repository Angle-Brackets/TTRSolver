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
        self._w = ps.QUICK_W["survive"]

    def tearDown(self):
        ps.QUICK_W["survive"] = self._w

    def _contribution(self, state, plan):
        ps.QUICK_W["survive"] = 0.0
        lo = ps._quick_score(state, plan, random.Random(0))
        ps.QUICK_W["survive"] = 800.0
        hi = ps._quick_score(state, plan, random.Random(0))
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

    def test_nothing_swinging_reads_the_cap(self):
        state = _party_board()
        self.assertEqual(ps.survival_rounds(state, incoming=0.0),
                         ps.SURVIVAL_CAP)

    def test_it_is_capped(self):
        state = _party_board()
        self.assertEqual(ps.survival_rounds(state, incoming=0.001),
                         ps.SURVIVAL_CAP)


class ShippedValueTest(unittest.TestCase):

    def test_the_swept_weight_is_what_shipped(self):
        self.assertEqual(ps.QUICK_W["survive"], 400.0)


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
