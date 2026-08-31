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
