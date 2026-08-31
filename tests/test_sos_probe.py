"""The SOS probe: can `climb` propose a card at all?

An SOS is a legal action -- `simulator.legal_actions` emits one per card
held -- but `hybrid.climb` chose from indices into `env.ACTIONS`, which
holds no SOS and cannot hold one without changing `n_actions` and
invalidating every trained policy. So every card was unreachable by the
engine the overlay actually runs. These tests cover the probe that
supplies them directly.
"""
import random
import unittest

from solver import simulator, sos as sos_mod
from solver.rl import env as env_mod
from solver.search import hybrid, party_search as ps
from solver.state import Action, ToonState, Track

CARDS = {"Flippy": 1, "Lil Oldman": 1, "Clerk Clara": 1}


def _sampler(rng):
    st = env_mod.facility_position(rng)
    tracks = [t for t in Track if t is not Track.TOON_UP]
    toon = ToonState(12, 137, {t: 7 for t in tracks}, {},
                     frozenset({Track.THROW}), pouch_capacity=80)
    env_mod.restock(toon, rng)
    toon.sos_cards = dict(CARDS)
    st.toons = [toon]
    return st


def _board(seed):
    """A filled board. `facility_position` returns cogs=[]; `reset`
    builds them, and scoring an empty board measures nothing."""
    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=_sampler,
                          coordinated=True)
    e.reset()
    return e.state


class ProbeTest(unittest.TestCase):

    def test_no_sos_has_an_action_index(self):
        """The reason the probe exists."""
        self.assertEqual(
            [a for a in env_mod.ACTIONS
             if a is not None and getattr(a, "sos", None)], [])

    def test_it_offers_each_card_held_once(self):
        probes = hybrid._sos_probes(_board(3), 0)
        self.assertEqual(sorted(a.sos for a in probes), sorted(CARDS))

    def test_two_copies_are_still_one_offer(self):
        state = _board(3)
        state.toons[0].sos_cards = {"Flippy": 2}
        self.assertEqual([a.sos for a in hybrid._sos_probes(state, 0)],
                         ["Flippy"])

    def test_it_offers_nothing_when_none_are_held(self):
        state = _board(3)
        state.toons[0].sos_cards = {}
        self.assertEqual(hybrid._sos_probes(state, 0), [])

    def test_a_card_not_in_the_table_is_not_offered(self):
        """The three Operation specials are deliberately absent from
        `BY_NAME`; a save holding one must not crash the probe."""
        state = _board(3)
        state.toons[0].sos_cards = {"Rocky": 1, "Flippy": 1}
        self.assertEqual([a.sos for a in hybrid._sos_probes(state, 0)],
                         ["Flippy"])

    def test_legal_actions_agrees_with_the_probe(self):
        state = _board(3)
        legal = {a.sos for a in simulator.legal_actions(state) if a.sos}
        self.assertEqual(legal, {a.sos for a in hybrid._sos_probes(state, 0)})


class ReachesTheJudgeTest(unittest.TestCase):
    """End-to-end: the probe is wired into the trial loop, not merely
    returning a list nothing consumes."""

    def setUp(self):
        self._offer = hybrid.OFFER_SOS
        self._survive = ps.QUICK_W["survive"]

    def tearDown(self):
        hybrid.OFFER_SOS = self._offer
        ps.QUICK_W["survive"] = self._survive

    def test_climb_can_return_an_sos(self):
        # `survive` is weighted far above its shipped 0.0 on purpose:
        # this asserts the PATH is live, not that the card is a good
        # move at the shipped weights. See `test_a_heal_is_invisible`
        # for why the shipped weights can never pick one.
        ps.QUICK_W["survive"] = 1000.0
        hybrid.OFFER_SOS = True
        plan = hybrid.climb(_board(19), random.Random(19), budget=10)
        # Flippy, and it used to be Lil Oldman. Pinning `incoming` in
        # `survival_rounds` stopped the lure being paid twice -- once as
        # `prevented` and again through the incoming it removed -- and
        # on 12 laff the 180-point heal is the better card. The change
        # is the fix working, not a regression.
        self.assertEqual(getattr(plan[0], "sos", None), "Flippy")

    def test_the_flag_off_means_never(self):
        ps.QUICK_W["survive"] = 1000.0
        hybrid.OFFER_SOS = False
        plan = hybrid.climb(_board(19), random.Random(19), budget=10)
        self.assertIsNone(getattr(plan[0], "sos", None))


class HealIsInvisibleTest(unittest.TestCase):
    """Why no card can win at the shipped weights, recorded so the
    price is not blamed for it.

    `_score_leaf` simulates the toon phase only, so laff never moves
    within it and a term reading laff LEVEL is the only thing that can
    see a heal. That term is `survival_rounds` and its weight is 0.0 --
    the same wall that made a unite score exactly zero.
    """

    def setUp(self):
        self._survive = ps.QUICK_W["survive"]

    def tearDown(self):
        ps.QUICK_W["survive"] = self._survive

    def test_a_heal_is_worth_exactly_its_price_and_nothing_else(self):
        ps.QUICK_W["survive"] = 0.0
        state = _board(3)
        score = ps._quick_score(state, [Action(track=None, sos="Flippy")],
                                random.Random(0))
        # Not "about" -0400: EXACTLY. Flippy restores 180 laff to a toon
        # on 12 and the score is the price alone, so the heal
        # contributed zero. Dropping SOS_PRICE would not help -- at
        # price 0 this reads 0.00 and still loses to any gag.
        self.assertAlmostEqual(score, -sos_mod.SOS_PRICE, places=6)

    def test_the_survive_term_is_what_reveals_it(self):
        state = _board(3)
        card = [Action(track=None, sos="Flippy")]
        ps.QUICK_W["survive"] = 0.0
        flat = ps._quick_score(state, card, random.Random(0))
        ps.QUICK_W["survive"] = 200.0
        lifted = ps._quick_score(state, card, random.Random(0))
        self.assertGreater(lifted, flat)


if __name__ == "__main__":
    unittest.main()


class EnvCanPlayOneTest(unittest.TestCase):
    """`BattleEnv.step` takes an index, and no SOS has one.

    Without the override an SOS chosen by `climb` maps to `PASS_INDEX`
    and the toon does nothing, so a measurement would count the card as
    used while nothing happened.
    """

    def test_stepping_an_index_is_unchanged(self):
        a = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        b = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        a.reset()
        b.reset()
        ra = a.step(env_mod.PASS_INDEX)
        rb = b.step(env_mod.PASS_INDEX, action=None)
        self.assertEqual(ra[2], rb[2])
        self.assertEqual(ra[3], rb[3])

    def test_a_card_is_actually_spent(self):
        e = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        e.reset()
        held = e.state.toons[0].sos_cards["Lil Oldman"]
        e.step(env_mod.PASS_INDEX,
               action=Action(track=None, sos="Lil Oldman"))
        self.assertEqual(e.state.toons[0].sos_cards.get("Lil Oldman", 0),
                         held - 1)

    def test_the_card_takes_effect(self):
        """Lil Oldman lures every cog; a pass lures none. This is what
        separates a card that was played from one silently dropped."""
        e = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        e.reset()
        self.assertFalse(any(c.status.lured for c in e.state.cogs))
        e.step(env_mod.PASS_INDEX,
               action=Action(track=None, sos="Lil Oldman"))
        live = [c for c in e.state.cogs if not c.status.is_dead]
        self.assertTrue(live and all(c.status.lured for c in live))


class SosLureSurvivesACogPhaseTest(unittest.TestCase):
    """An SOS lure has no gag level, and the expiry rule looked one up.

    `sos.apply` passes `level=None` deliberately -- a card is not a gag.
    `_tick_lure` then asked `lure_can_expire_early(None)`, which reached
    `data.gag(LURE, None)` and raised. Every Lure card therefore crashed
    the first cog phase after it was played, which no test caught
    because scoring simulates the toon phase only.
    """

    def test_a_lure_card_survives_the_round_it_is_played(self):
        e = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        e.reset()
        e.step(env_mod.PASS_INDEX,
               action=Action(track=None, sos="Lil Oldman"))
        live = [c for c in e.state.cogs if not c.status.is_dead]
        self.assertTrue(live and all(c.status.lured for c in live))

    def test_every_lure_card_does(self):
        for name in ("Stinky Ned", "Nancy Gas", "Lil Oldman"):
            with self.subTest(card=name):
                e = env_mod.BattleEnv(rng=random.Random(7),
                                      sampler=_sampler, coordinated=True)
                e.reset()
                e.state.toons[0].sos_cards = {name: 1}
                e.step(env_mod.PASS_INDEX, action=Action(track=None, sos=name))

    def test_an_sos_lure_never_expires_early(self):
        from solver import mechanics
        self.assertFalse(mechanics.lure_can_expire_early(None))

    def test_a_real_gag_level_is_unaffected(self):
        from solver import mechanics
        for level in range(1, 8):
            self.assertFalse(mechanics.lure_can_expire_early(level))


class EveryCardSurvivesARoundTest(unittest.TestCase):
    """Play all 29 through two full rounds.

    The lure crash was invisible because every existing SOS test scored
    a card rather than playing one, and scoring simulates the toon phase
    only. This is the cheap comprehensive version of the check that
    caught it: two rounds, so a delayed effect resolves as well.
    """

    def _sampler(self, rng):
        st = env_mod.facility_position(rng)
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(60, 137, {t: 7 for t in tracks}, {},
                         frozenset({Track.THROW}), pouch_capacity=80)
        env_mod.restock(toon, rng)
        st.toons = [toon]
        return st

    def test_all_of_them(self):
        for card in sos_mod.CARDS:
            for seed in (7, 11):
                with self.subTest(card=card.name, seed=seed):
                    e = env_mod.BattleEnv(rng=random.Random(seed),
                                          sampler=self._sampler,
                                          coordinated=True)
                    e.reset()
                    e.state.toons[0].sos_cards = {card.name: 1}
                    e.step(env_mod.PASS_INDEX,
                           action=Action(track=None, sos=card.name))
                    e.step(env_mod.PASS_INDEX)
