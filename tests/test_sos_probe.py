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
from solver.search import weights as ps_weights

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
        self._survive = ps_weights.QUICK_W["survive"]

    def tearDown(self):
        hybrid.OFFER_SOS = self._offer
        ps_weights.QUICK_W["survive"] = self._survive

    def test_climb_can_return_an_sos(self):
        # `survive` is weighted far above its shipped 0.0 on purpose:
        # this asserts the PATH is live, not that the card is a good
        # move at the shipped weights. See `test_a_heal_is_invisible`
        # for why the shipped weights can never pick one.
        ps_weights.QUICK_W["survive"] = 1000.0
        hybrid.OFFER_SOS = True
        plan = hybrid.climb(_board(19), random.Random(19), budget=10)
        # Flippy, and it used to be Lil Oldman. Pinning `incoming` in
        # `survival_rounds` stopped the lure being paid twice -- once as
        # `prevented` and again through the incoming it removed -- and
        # on 12 laff the 180-point heal is the better card. The change
        # is the fix working, not a regression.
        self.assertEqual(getattr(plan[0], "sos", None), "Flippy")

    def test_the_flag_off_means_never(self):
        ps_weights.QUICK_W["survive"] = 1000.0
        hybrid.OFFER_SOS = False
        plan = hybrid.climb(_board(19), random.Random(19), budget=10)
        self.assertIsNone(getattr(plan[0], "sos", None))


class HealIsVisibleTest(unittest.TestCase):
    """A heal card now pays for the laff it puts back.

    THIS CLASS USED TO ASSERT THE OPPOSITE, and was right to: with
    `survive` at 0.0 a Flippy scored EXACTLY `-SOS_PRICE`, so the 180
    laff it restored contributed nothing at all and the price was
    getting blamed for a defect somewhere else.

    The defect was in the report, not the weights. `apply_toon_action`
    returned `0, 0` for an SOS -- correct for the damage, which an SOS
    does not deal as the toon, and wrong for the FIRST element, which is
    laff healed. `apply_party_round` recorded no healing, so
    `QUICK_W["heal"]` never saw a card heal at all.

    What it cost: `_restored` caps a heal at the toon's headroom, which
    is precisely the "worth more when you are low" weighting a heal
    should have -- 17 laff into a full toon, 125 into a dying one. With
    the report stuck at zero that weighting could not apply, and Flippy
    scored 558.4 at 120 laff and 558.4 at 12.
    """

    def setUp(self):
        self._survive = ps_weights.QUICK_W["survive"]

    def tearDown(self):
        ps_weights.QUICK_W["survive"] = self._survive

    def test_a_heal_is_worth_more_than_its_price_alone(self):
        ps_weights.QUICK_W["survive"] = 0.0
        state = _board(3)
        score = ps._quick_score(state, [Action(track=None, sos="Flippy")],
                                random.Random(0))
        # The old assertion was `== -SOS_PRICE` exactly. Anything above
        # it is the heal being counted; below would mean it is being
        # charged for healing.
        self.assertGreater(score, -sos_mod.SOS_PRICE)

    def test_it_is_worth_more_to_a_toon_with_more_room(self):
        """The laff-relative half, which `_restored` supplies by capping
        at headroom -- the same card is worth less to a healthy toon."""
        ps_weights.QUICK_W["survive"] = 0.0
        card = [Action(track=None, sos="Flippy")]
        hurt = _board(3)
        full = _board(3)
        for toon in full.toons:
            toon.laff = toon.max_laff
        self.assertGreater(
            ps._quick_score(hurt, card, random.Random(0)),
            ps._quick_score(full, card, random.Random(0)))

    def test_the_survive_term_is_what_reveals_it(self):
        state = _board(3)
        card = [Action(track=None, sos="Flippy")]
        ps_weights.QUICK_W["survive"] = 0.0
        flat = ps._quick_score(state, card)
        ps_weights.QUICK_W["survive"] = 200.0
        lifted = ps._quick_score(state, card)
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


class PriceTest(unittest.TestCase):
    """The gap to a unite is scarcity ONLY; the turn is charged by the
    mechanics.

    An SOS occupies the action slot, so the plan holds no gag for that
    toon and the damage terms drop without anything being priced.
    Measured with both prices zeroed, the best gag alone beats the card
    alone by about 203 points. A price gap of the same size would charge
    the turn twice.
    """

    def test_it_sits_slightly_above_a_unite(self):
        from solver import unites
        gap = sos_mod.SOS_PRICE - unites.UNITE_PRICE
        self.assertGreater(gap, 0, "an SOS must still cost more")
        self.assertLess(gap, 203,
                        "a gap at or above the measured turn cost charges "
                        "the turn twice")

    def test_spending_the_turn_costs_something_without_any_price(self):
        """The mechanical half, with prices out of the way.

        On a FULL toon, where the heal is entirely wasted, so what
        separates the two is only the gag the card did not throw. At 12
        laff the card rightly wins instead -- 180 restored beats any one
        gag -- which is why this pins the healthy case.
        """
        state = _board(3)
        state.toons[0].laff = state.toons[0].max_laff
        actions = [a for a in simulator.legal_actions(state)
                   if a.track is not None]
        old_w = ps_weights.QUICK_W["price"]
        try:
            ps_weights.QUICK_W["price"] = 0.0
            gag = max(actions,
                      key=lambda a: ps._quick_score(state, [a]))
            best = ps._quick_score(state, [gag])
            card = ps._quick_score(state, [Action(track=None, sos="Flippy")],
                                   random.Random(0))
            self.assertGreater(best, card)
        finally:
            ps_weights.QUICK_W["price"] = old_w


class RenderTest(unittest.TestCase):
    """The advice line. Every card must produce one, and none may raise.

    An SOS has `track=None` and `is_pass=False`, so `advise._render`
    fell through to `data.gag(None, None)` and raised `no gag at no
    track (a pass) level 0` -- and the panel's own fallback then raised
    AttributeError on `None.value` while handling it. Exactly the shape
    of the fire bug that renderer already carries a comment about.
    """

    def _state(self):
        e = env_mod.BattleEnv(rng=random.Random(7), sampler=_sampler,
                              coordinated=True)
        e.reset()
        return e.state

    def test_every_card_renders(self):
        from solver.live import advise
        state = self._state()
        for card in sos_mod.CARDS:
            with self.subTest(card=card.name):
                line = advise._render(Action(track=None, sos=card.name), state)
                self.assertIn(card.name, line)
                self.assertTrue(line.startswith("call "))

    def test_the_panel_renders_it_too(self):
        from solver.live import realms_panel as rp
        state = self._state()
        line = rp._render(Action(track=None, sos="Flippy"), state)
        self.assertIn("Flippy", line)

    def test_the_panel_fallback_survives_a_track_less_action(self):
        """The fallback exists to survive a failure in the shared
        renderer; it must not raise while doing so."""
        from solver.live import realms_panel as rp
        for act in (Action(track=None, sos="Flippy"),
                    Action(track=None, fire=True, target_index=0)):
            with self.subTest(action=act):
                self.assertIsInstance(rp._render(act, None), str)

    def test_a_heal_splits_across_the_toons_standing(self):
        """[CONFIRMED] wiki: Flippy is 180 to a lone toon, halving as
        more share it -- 180/90/60/45."""
        card = sos_mod.BY_NAME["Flippy"]
        self.assertIn("180", sos_mod.describe(card, 1))
        self.assertIn("90", sos_mod.describe(card, 2))
        self.assertIn("60", sos_mod.describe(card, 3))
        self.assertIn("45", sos_mod.describe(card, 4))

    def test_a_track_is_named_the_way_a_player_writes_it(self):
        line = sos_mod.describe(sos_mod.BY_NAME["Professor Guffaw"], 1)
        self.assertIn("Toon-Up", line)
        self.assertNotIn("toon_up", line)

    def test_the_slug_and_level_the_page_gets(self):
        from solver.live import realms_panel as rp
        card = Action(track=None, sos="Flippy")
        self.assertEqual(rp._track_of(card), "sos")
        self.assertIsNone(rp._level_of(card))


class TrackSlugTest(unittest.TestCase):
    """`advise.track_of` is the TTR overlay's path and had the same
    hole: it guarded `is_pass` and `fire` but not SOS, so it reached
    `action.track.value` and raised. It also returned None for a fire,
    which showed the styling a PASS gets -- and both panels render
    through the same page, so TTR lost the pink slip icon that Realms
    shows for the identical recommendation.
    """

    def test_an_sos_has_a_slug(self):
        from solver.live import advise
        self.assertEqual(advise.track_of(Action(track=None, sos="Flippy")),
                         "sos")

    def test_a_fire_has_one_too(self):
        from solver.live import advise
        self.assertEqual(
            advise.track_of(Action(track=None, fire=True, target_index=0)),
            "fire")

    def test_a_pass_has_none(self):
        from solver.live import advise
        self.assertIsNone(advise.track_of(Action(track=None)))
        self.assertIsNone(advise.track_of(None))

    def test_a_gag_is_its_own_track(self):
        from solver.live import advise
        self.assertEqual(
            advise.track_of(Action(track=Track.THROW, level=4)), "throw")

    def test_both_panels_agree(self):
        """Two panels colouring the same recommendation differently
        would be worse than the coupling, so one defers to the other."""
        from solver.live import advise
        from solver.live import realms_panel as rp
        for act in (Action(track=None, sos="Flippy"),
                    Action(track=None, fire=True, target_index=0),
                    Action(track=None),
                    Action(track=Track.DROP, level=5)):
            with self.subTest(action=act):
                self.assertEqual(rp._track_of(act), advise.track_of(act))


class SosTrapSurvivesACloneTest(unittest.TestCase):
    """`CogStatus.copy` dropped `trap_damage`.

    An SOS trap sets `trap_damage` and leaves `trap_level` None, because
    a card's 60/120/180 is not a gag level. The copy carried `trapped`
    but not the damage, so a cloned cog was still marked trapped with
    BOTH fields None and `_apply_trap_trigger` raised `no gag at trap
    level None` the first time a lure sprang it.

    Every search clones, so this fired in play and not in any test --
    the third instance of this omission after `fires` and `suited`.
    """

    def _trapped(self):
        from solver import data
        from solver.state import BattleState, CogState
        hp = data.cog_max_hp(5)
        cog = CogState(department="lawbot", cog_type="ambulance_chaser",
                       level=5, hp=hp, max_hp=hp)
        toon = ToonState(80, 137, {t: 7 for t in Track},
                         {(Track.LURE, 1): 5}, frozenset(),
                         pouch_capacity=80)
        toon.sos_cards = {"Clerk Clara": 1}
        state = BattleState(toon=toon, cogs=[cog])
        simulator.apply_party_round(
            state, [Action(track=None, sos="Clerk Clara")], hits=[True])
        return state

    def test_the_card_sets_damage_and_no_level(self):
        status = self._trapped().cogs[0].status
        self.assertTrue(status.trapped)
        self.assertEqual(status.trap_damage, 180)
        self.assertIsNone(status.trap_level)

    def test_a_clone_keeps_the_damage(self):
        clone = self._trapped().clone()
        self.assertEqual(clone.cogs[0].status.trap_damage, 180)

    def test_a_lure_springs_it_on_a_clone(self):
        clone = self._trapped().clone()
        before = clone.cogs[0].hp
        simulator.apply_party_round(
            clone, [Action(track=Track.LURE, level=1, target_index=0)],
            hits=[True])
        self.assertLess(clone.cogs[0].hp, before)

    def test_every_trap_card_survives_a_clone(self):
        for name in ("Clerk Will", "Clerk Penny", "Clerk Clara"):
            with self.subTest(card=name):
                state = self._trapped()
                state.toons[0].sos_cards = {name: 1}
                for cog in state.cogs:
                    cog.status.trapped = False
                    cog.status.trap_damage = None
                simulator.apply_party_round(
                    state, [Action(track=None, sos=name)], hits=[True])
                clone = state.clone()
                self.assertEqual(clone.cogs[0].status.trap_damage,
                                 sos_mod.BY_NAME[name].amount)


class VpFloorCapTest(unittest.TestCase):
    """A VP floor gets longer than the default 20 rounds.

    Twenty cogs with four on the field runs into the forties, so every
    long VP was ending in `truncated: True` -- the harness calling time,
    not a defeat. Measured once the unite cooldown was also fixed: at a
    cap of 20 the solo clear rate was 0.0% in every condition; at 60 it
    was 8.3% with unites and 33.3% with cards.
    """

    def _env(self, kind, **kw):
        e = env_mod.BattleEnv(rng=random.Random(1), sampler=_sampler,
                              coordinated=True, **kw)
        e.reset()
        e.state.kind = kind
        return e

    def test_a_vp_floor_gets_the_longer_cap(self):
        self.assertEqual(env_mod.VP_FLOOR_ROUNDS,
                         self._env("vp")._floor_cap())

    def test_everything_else_keeps_the_default(self):
        env = self._env("facility")
        self.assertEqual(env.max_rounds, env._floor_cap())
        self.assertEqual(20, env.max_rounds)

    def test_an_explicit_longer_cap_still_wins(self):
        """A caller who asked for a long fight gets one."""
        env = self._env("vp", max_rounds=env_mod.VP_FLOOR_ROUNDS + 40)
        self.assertEqual(env_mod.VP_FLOOR_ROUNDS + 40, env._floor_cap())

    def test_it_is_long_enough_for_an_observed_clear(self):
        """A solo clear was seen at about 48 rounds; the cap has to
        leave room above that rather than sit on it."""
        self.assertGreater(env_mod.VP_FLOOR_ROUNDS, 48)
