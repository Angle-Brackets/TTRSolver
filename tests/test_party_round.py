"""Resolving a round for more than one toon.

Four solo toons are not a party, and three effects are the difference.
Each exists only when several gags land in the same round, which is why
calling `apply_toon_action` four times cannot produce it:

* Order. Gags resolve by track, not by who chose first, so a Lure
  landing before a Throw is what makes the Throw a knockback.
* Combos. Same-track gags on the same cog have their damage summed and
  then bonused on the total, rather than bonused individually.
* Stun. A landed attack makes later attacks of a different track more
  accurate.

Hits are supplied rather than rolled throughout, so these test the
resolution and not the dice.
"""
import unittest

from solver import data, mechanics, simulator
from solver.state import Action, BattleState, CogState, ToonState, Track


def cog(level=6, hp=None):
    mx = data.cog_max_hp(level)
    return CogState("yesman", "bossbot", level,
                    hp if hp is not None else mx, mx)


def toon(counts, laff=80, organic=()):
    return ToonState(laff, 95, {t: 7 for t, _l in counts}, dict(counts),
                     organic_tracks=frozenset(organic))


class ComboTest(unittest.TestCase):
    """Same track, same cog, same round."""

    def test_two_throws_beat_two_separate_throws(self):
        counts = {(Track.THROW, 3): 1}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=200)])
        pie = data.gag(Track.THROW, 3).damage_at(1.0)
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 0)],
            hits=[True, True])
        dealt = 200 - state.cogs[0].hp
        self.assertEqual(dealt, 2 * pie + mechanics.calc_hp_bonus(2 * pie, 2))
        self.assertGreater(dealt, 2 * pie)

    def test_the_bonus_is_on_the_total_not_per_gag(self):
        counts = {(Track.THROW, 3): 1}
        state = BattleState(toons=[toon(counts) for _ in range(3)],
                            cogs=[cog(hp=300)])
        pie = data.gag(Track.THROW, 3).damage_at(1.0)
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0)] * 3, hits=[True] * 3)
        self.assertEqual(300 - state.cogs[0].hp,
                         3 * pie + mechanics.calc_hp_bonus(3 * pie, 3))

    def test_different_tracks_do_not_combo(self):
        state = BattleState(
            toons=[toon({(Track.THROW, 3): 1}), toon({(Track.SQUIRT, 3): 1})],
            cogs=[cog(hp=200)])
        throw = data.gag(Track.THROW, 3).damage_at(1.0)
        squirt = data.gag(Track.SQUIRT, 3).damage_at(1.0)
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.SQUIRT, 3, 0)],
            hits=[True, True])
        self.assertEqual(200 - state.cogs[0].hp, throw + squirt)

    def test_different_cogs_do_not_combo(self):
        counts = {(Track.THROW, 3): 1}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=200), cog(hp=200)])
        pie = data.gag(Track.THROW, 3).damage_at(1.0)
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 1)],
            hits=[True, True])
        self.assertEqual(200 - state.cogs[0].hp, pie)
        self.assertEqual(200 - state.cogs[1].hp, pie)

    def test_a_miss_is_not_part_of_the_combo(self):
        counts = {(Track.THROW, 3): 1}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=200)])
        pie = data.gag(Track.THROW, 3).damage_at(1.0)
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 0)],
            hits=[True, False])
        self.assertEqual(200 - state.cogs[0].hp, pie)


class OrderTest(unittest.TestCase):

    def test_lure_resolves_before_throw(self):
        """So the Throw is a knockback, whoever chose first."""
        state = BattleState(
            toons=[toon({(Track.THROW, 3): 1}), toon({(Track.LURE, 3): 1})],
            cogs=[cog(hp=200)])
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.LURE, 3, 0)],
            hits=[True, True])
        plain = data.gag(Track.THROW, 3).damage_at(1.0)
        self.assertGreater(200 - state.cogs[0].hp, plain)

    def test_every_gag_is_spent_whether_or_not_it_lands(self):
        counts = {(Track.THROW, 3): 2}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=200)])
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 0)],
            hits=[True, False])
        for t in state.toons:
            self.assertEqual(t.gag_counts[(Track.THROW, 3)], 1)

    def test_sitting_the_round_out_spends_nothing(self):
        counts = {(Track.THROW, 3): 2}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=200)])
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), None], hits=[True, True])
        self.assertEqual(state.toons[1].gag_counts[(Track.THROW, 3)], 2)


class StunTest(unittest.TestCase):
    """A landed attack helps the next one of a different track."""

    def test_prior_hits_are_worth_twenty_five_each(self):
        self.assertEqual(mechanics.calc_same_round_prev_hits(0), 0)
        self.assertEqual(mechanics.calc_same_round_prev_hits(1), 25)
        self.assertEqual(mechanics.calc_same_round_prev_hits(2), 50)

    def test_and_cap_at_seventy_five(self):
        """The wiki: a bonus of +75 is possible with three prior hits."""
        self.assertEqual(mechanics.calc_same_round_prev_hits(3), 75)
        self.assertEqual(mechanics.calc_same_round_prev_hits(9), 75)

    def test_a_group_attack_shares_the_bonus_either_way(self):
        self.assertTrue(simulator._prev_hits_apply(True, [0], False, [1]))
        self.assertTrue(simulator._prev_hits_apply(False, [0], True, [1]))

    def test_otherwise_they_must_share_a_target(self):
        self.assertTrue(simulator._prev_hits_apply(False, [0], False, [0]))
        self.assertFalse(simulator._prev_hits_apply(False, [0], False, [1]))


class DamageAttributionTest(unittest.TestCase):
    """Who hurt the cog, for `pick_cog_target`."""

    def test_each_toons_damage_is_recorded_against_the_cog(self):
        state = BattleState(
            toons=[toon({(Track.THROW, 3): 1}), toon({(Track.THROW, 5): 1})],
            cogs=[cog(hp=300)])
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 5, 0)],
            hits=[True, True])
        recorded = state.cogs[0].status.damage_by_toon
        self.assertEqual(set(recorded), {0, 1})
        self.assertGreater(recorded[1], recorded[0])   # level 5 hits harder

    def test_a_miss_records_nothing(self):
        counts = {(Track.THROW, 3): 1}
        state = BattleState(toons=[toon(counts), toon(counts)],
                            cogs=[cog(hp=300)])
        simulator.apply_party_round(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 0)],
            hits=[True, False])
        self.assertEqual(set(state.cogs[0].status.damage_by_toon), {0})


class ToonUpTest(unittest.TestCase):

    def test_healing_goes_to_the_toon_who_threw_it(self):
        state = BattleState(
            toons=[toon({(Track.TOON_UP, 1): 1}, laff=40), toon({}, laff=40)],
            cogs=[cog()])
        healed = simulator.apply_party_round(
            state, [Action(Track.TOON_UP, 1, None), None], hits=[True, True])
        self.assertGreater(healed[0], 0)
        self.assertEqual(healed[1], 0)


class SoloEquivalenceTest(unittest.TestCase):
    """One toon through the party path matches the solo path.

    Not a formality: if the two disagree, the party code is a second
    implementation of the rules rather than a generalisation of them,
    and they will drift.
    """

    def test_one_throw_deals_the_same_either_way(self):
        counts = {(Track.THROW, 4): 2}
        party = BattleState(toons=[toon(counts)], cogs=[cog(hp=200)])
        solo = BattleState(toon=toon(counts), cogs=[cog(hp=200)])
        simulator.apply_party_round(party, [Action(Track.THROW, 4, 0)],
                                    hits=[True])
        simulator.apply_toon_action(solo, Action(Track.THROW, 4, 0), True)
        self.assertEqual(party.cogs[0].hp, solo.cogs[0].hp)
        self.assertEqual(party.toon.gag_counts, solo.toon.gag_counts)

    def test_a_lone_gag_gets_no_combo_bonus(self):
        counts = {(Track.THROW, 4): 1}
        state = BattleState(toons=[toon(counts)], cogs=[cog(hp=200)])
        simulator.apply_party_round(state, [Action(Track.THROW, 4, 0)],
                                    hits=[True])
        self.assertEqual(200 - state.cogs[0].hp,
                         data.gag(Track.THROW, 4).damage_at(1.0))


if __name__ == "__main__":
    unittest.main()


class SharedAccuracyRollTest(unittest.TestCase):
    """One roll per track per target, not one per gag.

    Gags of the same track aimed at the same cog resolve on a single
    accuracy roll, so they all land or all miss together; a group gag
    rolls once for the whole battle. Rolling each gag separately let a
    party hedge -- four Throws at one cog would almost certainly land
    *something* -- which is not the game, and badly overvalues stacking
    a track on one target.
    """

    class Rolls:
        """Counts how many accuracy dice were asked for."""

        def __init__(self, value):
            self.value = value
            self.calls = 0

        def __call__(self, rng=None):
            # `rng` because accuracy_roll takes one now, so a seeded
            # search can be reproduced. The stub ignores it.
            self.calls += 1
            return self.value

    def party(self, n, counts):
        return BattleState(toons=[toon(counts) for _ in range(n)],
                           cogs=[cog(hp=400), cog(hp=400)])

    def rolls_taken(self, state, actions, value=0):
        dice = self.Rolls(value)
        real = mechanics.accuracy_roll
        mechanics.accuracy_roll = dice
        try:
            simulator.apply_party_round(state, actions)
        finally:
            mechanics.accuracy_roll = real
        return dice.calls

    def test_same_track_same_cog_shares_one_roll(self):
        state = self.party(3, {(Track.THROW, 3): 1})
        taken = self.rolls_taken(state, [Action(Track.THROW, 3, 0)] * 3)
        self.assertEqual(taken, 1)

    def test_same_track_different_cogs_roll_separately(self):
        state = self.party(2, {(Track.THROW, 3): 1})
        taken = self.rolls_taken(
            state, [Action(Track.THROW, 3, 0), Action(Track.THROW, 3, 1)])
        self.assertEqual(taken, 2)

    def test_a_group_gag_rolls_once_for_the_battle(self):
        state = self.party(2, {(Track.SOUND, 4): 1})
        taken = self.rolls_taken(state, [Action(Track.SOUND, 4, None)] * 2)
        self.assertEqual(taken, 1)

    def test_they_all_miss_together(self):
        """The point of the shared roll: no hedging."""
        state = self.party(3, {(Track.THROW, 3): 1})
        self.rolls_taken(state, [Action(Track.THROW, 3, 0)] * 3, value=99)
        self.assertEqual(state.cogs[0].hp, 400)

    def test_and_all_land_together(self):
        state = self.party(3, {(Track.THROW, 3): 1})
        self.rolls_taken(state, [Action(Track.THROW, 3, 0)] * 3, value=0)
        pie = data.gag(Track.THROW, 3).damage_at(1.0)
        self.assertEqual(400 - state.cogs[0].hp,
                         3 * pie + mechanics.calc_hp_bonus(3 * pie, 3))


class ToonUpCostTest(unittest.TestCase):

    def test_healing_spends_the_gag(self):
        """It did not, which made healing free -- and a free action is
        one a search takes for no reason. A joint search filled three of
        four slots with Feathers thrown at toons already on full laff."""
        state = BattleState(
            toons=[toon({(Track.TOON_UP, 1): 3}, laff=40)], cogs=[cog()])
        simulator.apply_party_round(state, [Action(Track.TOON_UP, 1, None)],
                                    hits=[True])
        self.assertEqual(state.toons[0].gag_counts[(Track.TOON_UP, 1)], 2)


class SharedAccuracyIsTheBestGagTest(unittest.TestCase):
    """When gags share a roll, the strongest one sets the odds.

    Moot for every track but Lure and Toon-Up: propAcc is uniform within
    a track, so a Cupcake and a Birthday Cake are both 75 and it makes
    no difference which is read. Lure is where it matters -- 60/55/70/
    65/80/75/90 by level -- and a stronger Lure carries a weaker one
    thrown at the same cog.

    [UNVERIFIED] for Lure: play knowledge, not the wiki, which gives the
    per-gag accuracies and says nothing about two Lures on one cog.
    """

    def test_throw_accuracies_are_uniform_so_the_question_is_moot(self):
        accuracies = {data.gag(Track.THROW, lvl).prop_accuracy()
                      for lvl in range(1, 8)}
        self.assertEqual(len(accuracies), 1)

    def test_but_lure_accuracies_are_not(self):
        accuracies = {data.gag(Track.LURE, lvl).prop_accuracy()
                      for lvl in range(1, 8)}
        self.assertGreater(len(accuracies), 1)

    def roll_with(self, state, actions, value):
        real = mechanics.accuracy_roll
        mechanics.accuracy_roll = lambda rng=None: value
        try:
            simulator.apply_party_round(state, actions)
        finally:
            mechanics.accuracy_roll = real

    def untrained(self, counts):
        """Barely trained in Lure, so the gap between gags survives.

        A maxed toon adds +60 trackExp and both Lures pin at the 95 cap,
        which hides the very difference this is about -- the first
        version of these tests did exactly that and passed for the wrong
        reason.
        """
        return ToonState(80, 95, {Track.LURE: 1}, dict(counts))

    def lure_accuracy(self, state, level):
        return simulator.toon_action_accuracy(state, Action(Track.LURE,
                                                            level, 0))

    def test_the_two_lures_really_do_differ_here(self):
        """Premise check, because the cap can silently erase it."""
        state = BattleState(
            toons=[self.untrained({(Track.LURE, 1): 1, (Track.LURE, 5): 1})],
            cogs=[cog(level=1, hp=400)])
        self.assertLess(self.lure_accuracy(state, 1),
                        self.lure_accuracy(state, 5))

    def test_a_strong_lure_carries_a_weak_one_on_the_same_cog(self):
        counts = {(Track.LURE, 1): 1, (Track.LURE, 5): 1}
        state = BattleState(
            toons=[self.untrained(counts), self.untrained(counts)],
            cogs=[cog(level=1, hp=400)])
        between = (self.lure_accuracy(state, 1)
                   + self.lure_accuracy(state, 5)) // 2
        self.roll_with(state,
                       [Action(Track.LURE, 1, 0), Action(Track.LURE, 5, 0)],
                       value=between)
        self.assertTrue(state.cogs[0].status.lured)

    def test_a_weak_lure_alone_misses_that_roll(self):
        """The other half: without the strong Lure beside it, the same
        roll beats the weak gag."""
        counts = {(Track.LURE, 1): 1, (Track.LURE, 5): 1}
        state = BattleState(toons=[self.untrained(counts)],
                            cogs=[cog(level=1, hp=400)])
        between = (self.lure_accuracy(state, 1)
                   + self.lure_accuracy(state, 5)) // 2
        self.roll_with(state, [Action(Track.LURE, 1, 0)], value=between)
        self.assertFalse(state.cogs[0].status.lured)
