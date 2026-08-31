"""SOS Toons: the card table and the rules that decide their value.

The damages and durations come from the wiki and are easy. The rules
that matter are the ones it does not state -- what wakes a lure, what
costs a turn, what shares an accuracy roll -- and those are pinned
here because getting them wrong would be invisible in a win rate.
"""
import unittest

from solver import sos
from solver.state import Track


class TableTest(unittest.TestCase):

    def test_every_card_has_a_known_shape(self):
        shapes = {sos.HEAL, sos.TRAP, sos.LURE, sos.DAMAGE_ALL,
                  sos.DAMAGE_UNLURED, sos.RESTOCK, sos.TOONS_HIT,
                  sos.COGS_MISS}
        for card in sos.CARDS:
            self.assertIn(card.kind, shapes, card.name)

    def test_the_operation_cards_are_absent(self):
        """[OWNER] Rocky, Loopy Loopenloop and Lord Lowden Clear are
        limited-time rewards and not renewable. Planning around a card
        the player cannot farm is planning around one that runs out."""
        for name in sos.NOT_MODELLED:
            self.assertNotIn(name, sos.BY_NAME)

    def test_the_wiki_damage_figures(self):
        for name, amount in (("Clerk Clara", 180), ("Moe Zart", 75),
                             ("Barnacle Bessie", 170),
                             ("Barbara Seville", 35), ("Clumsy Ned", 60)):
            self.assertEqual(sos.BY_NAME[name].amount, amount, name)

    def test_the_wiki_durations(self):
        for name, rounds in (("Lil Oldman", 6), ("Stinky Ned", 4),
                             ("Sticky Lou", 5), ("Flim Flam", 3)):
            self.assertEqual(sos.BY_NAME[name].amount, rounds, name)

    def test_restock_sizes(self):
        """Twelve for one track, forty-five for all. Professor Pete is
        not seven times twelve, so the two are separate figures."""
        self.assertEqual(sos.BY_NAME["Baker Bridget"].amount, 12)
        self.assertEqual(sos.BY_NAME["Baker Bridget"].track, Track.THROW)
        self.assertEqual(sos.BY_NAME["Professor Pete"].amount, 45)
        self.assertIsNone(sos.BY_NAME["Professor Pete"].track)


class HealSplitTest(unittest.TestCase):
    """Plain division. Only the divisor differs from a gag's."""

    def test_it_reproduces_the_published_table(self):
        expected = {
            "Madam Chuckle": (60, 30, 20, 15),
            "Daffy Don": (120, 60, 40, 30),
            "Flippy": (180, 90, 60, 45),
        }
        for name, row in expected.items():
            card = sos.BY_NAME[name]
            got = tuple(sos.heal_share(card, n) for n in (1, 2, 3, 4))
            self.assertEqual(got, row, name)

    def test_a_solo_toon_gets_the_whole_thing(self):
        """One recipient means no division. This is why Flippy is worth
        so much solo, where a Toon-Up GAG is worth nothing at all --
        the gag has zero recipients, the SOS has one."""
        self.assertEqual(sos.heal_share(sos.BY_NAME["Flippy"], 1), 180)

    def test_no_recipients_heals_nothing(self):
        self.assertEqual(sos.heal_share(sos.BY_NAME["Flippy"], 0), 0)

    def test_asking_a_non_heal_card_raises(self):
        with self.assertRaises(ValueError):
            sos.heal_share(sos.BY_NAME["Moe Zart"], 1)


class LureInteractionTest(unittest.TestCase):
    """[OWNER] Everything but Lure wakes a sleeper, for two reasons."""

    def test_trap_wakes_because_it_cannot_be_laid_under_a_sleeper(self):
        self.assertTrue(sos.BY_NAME["Clerk Clara"].wakes_lured)

    def test_sound_wakes_because_it_is_an_attack(self):
        """Which is what LURE_ENDS_ON_DAMAGE already says of gags, so
        no new rule -- Moe Zart's 75 to all wakes the whole field, and
        that is usually a bad trade rather than free damage."""
        self.assertTrue(sos.BY_NAME["Moe Zart"].wakes_lured)

    def test_drop_does_not_wake_because_it_never_lands_on_a_sleeper(self):
        self.assertFalse(sos.BY_NAME["Barnacle Bessie"].wakes_lured)

    def test_lure_and_heal_leave_a_lure_alone(self):
        self.assertFalse(sos.BY_NAME["Lil Oldman"].wakes_lured)
        self.assertFalse(sos.BY_NAME["Flippy"].wakes_lured)

    def test_trap_is_the_only_setup(self):
        """Everything else resolves the round it is played, so only
        Trap needs a second round to be worth anything."""
        setups = [c.name for c in sos.CARDS if c.is_setup]
        self.assertEqual(sorted(setups),
                         ["Clerk Clara", "Clerk Penny", "Clerk Will"])


class AccuracyTest(unittest.TestCase):

    def test_no_card_rolls_for_accuracy(self):
        for card in sos.CARDS:
            self.assertFalse(sos.rolls_accuracy(card), card.name)

    def test_an_sos_must_not_join_a_shared_roll_group(self):
        """`party_search._roll_groups` keys a SHARED die on
        (track, target) so two toons throwing the same track at the
        same cog land or miss together. An SOS dragged into that group
        would miss whenever the party's gag did -- Moe Zart failing
        because someone else's Elephant Trunk failed. Fires and passes
        are already skipped there for the same reason: they never roll.
        """
        from solver.search import party_search as ps
        import inspect
        source = inspect.getsource(ps._roll_groups)
        self.assertIn("fire", source,
                      "the exemption pattern this must follow is gone")
        self.assertTrue(all(not sos.rolls_accuracy(c) for c in sos.CARDS))


class EffectTest(unittest.TestCase):
    """Playing a card actually does what the card says."""

    def _board(self, laff=40, lured=False):
        from solver import data
        from solver.state import BattleState, CogState, ToonState
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(laff, 137, {t: 7 for t in tracks},
                         {(Track.THROW, 5): 1}, frozenset(),
                         pouch_capacity=80)
        cogs = []
        for level in (12, 11, 10, 9):
            hp = data.cog_max_hp(level)
            cog = CogState(department="sellbot", cog_type="mr_hollywood",
                           level=level, hp=hp, max_hp=hp)
            if lured:
                cog.status.apply_lure(90, 4, level=5)
            cogs.append(cog)
        return BattleState(toon=toon, cogs=cogs)

    def test_flippy_gives_a_solo_toon_the_lot(self):
        state = self._board(laff=40)
        sos.apply(sos.BY_NAME["Flippy"], state)
        self.assertEqual(state.toons[0].laff, 137)   # 40 + 180, capped

    def test_a_heal_never_overheals(self):
        state = self._board(laff=130)
        report = sos.apply(sos.BY_NAME["Flippy"], state)
        self.assertEqual(report["healed"], 7)
        self.assertEqual(state.toons[0].laff, 137)

    def test_sound_hits_everything_and_wakes_it(self):
        state = self._board(lured=True)
        report = sos.apply(sos.BY_NAME["Moe Zart"], state)
        self.assertEqual(report["hit"], 4)
        self.assertEqual(sum(1 for c in state.cogs if c.status.lured), 0)

    def test_drop_hits_nothing_on_a_lured_field(self):
        state = self._board(lured=True)
        report = sos.apply(sos.BY_NAME["Barnacle Bessie"], state)
        self.assertEqual(report["hit"], 0)
        self.assertEqual(sum(1 for c in state.cogs if c.status.lured), 4,
                         "Drop must leave the sleepers asleep")

    def test_a_trap_card_places_and_un_lures(self):
        state = self._board(lured=True)
        report = sos.apply(sos.BY_NAME["Clerk Clara"], state)
        self.assertEqual(report["trapped"], 4)
        self.assertEqual(sum(1 for c in state.cogs if c.status.lured), 0)
        self.assertTrue(all(c.status.trapped for c in state.cogs))

    def test_an_sos_trap_springs_for_its_own_damage(self):
        """Not the gag's. Clerk Clara is 180 and TNT the gag happens to
        match, but Clerk Will is 60 where Quicksand is 50."""
        from solver import simulator
        for name, expected in (("Clerk Will", 60), ("Clerk Penny", 120),
                               ("Clerk Clara", 180)):
            state = self._board()
            sos.apply(sos.BY_NAME[name], state)
            self.assertEqual(simulator._apply_trap_trigger(state.cogs[0]),
                             expected, name)

    def test_springing_clears_the_sos_damage(self):
        from solver import simulator
        state = self._board()
        sos.apply(sos.BY_NAME["Clerk Clara"], state)
        simulator._apply_trap_trigger(state.cogs[0])
        self.assertIsNone(state.cogs[0].status.trap_damage)
        self.assertFalse(state.cogs[0].status.trapped)

    def test_a_normal_gag_trap_is_unaffected(self):
        """The override must not capture the ordinary path."""
        from solver import data, simulator
        from solver.state import CogState
        hp = data.cog_max_hp(12)
        cog = CogState(department="sellbot", cog_type="mr_hollywood",
                       level=12, hp=hp, max_hp=hp)
        cog.status.trapped = True
        cog.status.trap_level = 6
        self.assertEqual(simulator._apply_trap_trigger(cog), 180)

    def test_lure_cards_lure_the_field_for_their_duration(self):
        state = self._board()
        sos.apply(sos.BY_NAME["Lil Oldman"], state)
        self.assertTrue(all(c.status.lured for c in state.cogs))
        self.assertEqual(state.cogs[0].status.lure_rounds_remaining, 6)

    def test_professor_pete_restocks_forty_five(self):
        state = self._board()
        report = sos.apply(sos.BY_NAME["Professor Pete"], state)
        self.assertEqual(report["restocked"], 45)

    def test_a_single_track_card_restocks_twelve_of_that_track(self):
        state = self._board()
        report = sos.apply(sos.BY_NAME["Baker Bridget"], state)
        self.assertEqual(report["restocked"], 12)
        elsewhere = sum(n for (track, _lv), n
                        in state.toons[0].gag_counts.items()
                        if track is not Track.THROW)
        self.assertEqual(elsewhere, 0, "leaked into another track")

    def test_the_accuracy_cards_set_a_timed_effect(self):
        state = self._board()
        sos.apply(sos.BY_NAME["Sticky Lou"], state)
        self.assertEqual(state.toons_hit_rounds, 5)
        sos.apply(sos.BY_NAME["Julius Wheezer"], state)
        self.assertEqual(state.cogs_miss_rounds, 5)


class IntegrationTest(unittest.TestCase):
    """An SOS as an ordinary action: legal, playable, and never rolling."""

    def _state(self, cards=None, cogs=2):
        from solver import data
        from solver.state import BattleState, CogState, ToonState
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(40, 137, {t: 7 for t in tracks},
                         {(Track.THROW, 5): 2}, frozenset())
        toon.sos_cards = dict(cards or {})
        built = []
        for level in (12, 11, 10, 9)[:cogs]:
            hp = data.cog_max_hp(level)
            built.append(CogState(department="sellbot",
                                  cog_type="mr_hollywood", level=level,
                                  hp=hp, max_hp=hp))
        return BattleState(toon=toon, cogs=built)

    def test_a_toon_holding_none_is_offered_none(self):
        """The property that keeps every existing position unchanged."""
        from solver import simulator
        state = self._state()
        self.assertEqual(
            [a for a in simulator.legal_actions(state) if a.sos], [])

    def test_a_held_card_becomes_a_legal_action(self):
        from solver import simulator
        state = self._state({"Flippy": 1})
        names = [a.sos for a in simulator.legal_actions(state) if a.sos]
        self.assertEqual(names, ["Flippy"])

    def test_playing_one_spends_the_card(self):
        from solver import simulator
        from solver.state import Action
        state = self._state({"Flippy": 2})
        simulator.apply_toon_action(state, Action(track=None, sos="Flippy"),
                                    hit=True)
        self.assertEqual(state.toons[0].sos_cards["Flippy"], 1)
        self.assertEqual(state.toons[0].laff, 137)

    def test_calling_one_you_do_not_hold_raises(self):
        from solver import simulator
        from solver.state import Action
        with self.assertRaises(KeyError):
            simulator.apply_toon_action(
                self._state(), Action(track=None, sos="Flippy"), hit=True)

    def test_an_sos_action_is_not_a_pass(self):
        """`is_pass` keys on a null track, which an SOS also has. Fires
        already caused this exact bug once."""
        from solver.state import Action
        action = Action(track=None, sos="Flippy")
        self.assertFalse(action.is_pass)
        self.assertIsNone(action.track)

    def test_an_sos_never_misses(self):
        from solver import simulator
        from solver.state import Action
        state = self._state({"Moe Zart": 1})
        self.assertEqual(
            simulator.toon_action_accuracy(
                state, Action(track=None, sos="Moe Zart")), 100)

    def test_an_sos_does_not_share_the_party_s_accuracy_roll(self):
        """Moe Zart must not miss because someone's Elephant Trunk did.
        Both are Sound; a shared die would bind them together."""
        from solver.search import party_search as ps
        from solver.state import Action
        plan = [Action(track=Track.SOUND, level=4, target_index=None),
                Action(track=None, sos="Moe Zart")]
        groups = ps._roll_groups(plan)
        self.assertIn(0, groups, "the real gag should roll")
        self.assertNotIn(1, groups, "the SOS must not be in a roll group")

    def test_the_clone_carries_the_cards(self):
        state = self._state({"Flippy": 3})
        self.assertEqual(state.clone().toons[0].sos_cards, {"Flippy": 3})


class TimedEffectTest(unittest.TestCase):

    def _state(self):
        from solver import data
        from solver.state import BattleState, CogState, ToonState
        toon = ToonState(80, 137, {Track.DROP: 1}, {(Track.DROP, 7): 1},
                         frozenset())
        hp = data.cog_max_hp(9)
        cog = CogState(department="sellbot", cog_type="mr_hollywood",
                       level=9, hp=hp, max_hp=hp)
        return BattleState(toon=toon, cogs=[cog])

    def test_toons_hit_raises_gag_accuracy(self):
        """Drop is the least accurate track and the one it rescues."""
        from solver import mechanics
        state = self._state()
        plain = mechanics.calc_toon_accuracy(
            Track.DROP, 5, state.toons[0], [], toons_hit=False)
        boosted = mechanics.calc_toon_accuracy(
            Track.DROP, 5, state.toons[0], [], toons_hit=True)
        self.assertGreater(boosted, plain)

    def test_it_still_respects_the_hard_cap(self):
        """4.3.3 made the 95 cap soft and the wiki never says by how
        much, so the project keeps it hard. This must not be the one
        exception that quietly ignores that."""
        from solver import data, mechanics
        state = self._state()
        boosted = mechanics.calc_toon_accuracy(
            Track.THROW, 1, state.toons[0], [], toons_hit=True)
        self.assertLessEqual(boosted, data.ACCURACY_CAP)

    def test_the_effects_are_in_the_state_key(self):
        """A Cogs Miss changes the cog phase, so two positions
        identical but for one are not the same node -- the
        `free_passes` lesson."""
        from solver import outcomes
        a = self._state()
        b = self._state()
        b.cogs_miss_rounds = 3
        self.assertNotEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_they_count_down_each_round(self):
        from solver import simulator
        state = self._state()
        state.toons_hit_rounds = 2
        state.cogs_miss_rounds = 1
        simulator._resolve_cog_phase(state)
        self.assertEqual(state.toons_hit_rounds, 1)
        self.assertEqual(state.cogs_miss_rounds, 0)
        simulator._resolve_cog_phase(state)
        self.assertEqual(state.toons_hit_rounds, 0)
        self.assertEqual(state.cogs_miss_rounds, 0, "went negative")
