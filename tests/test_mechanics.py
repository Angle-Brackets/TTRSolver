"""
Status-effect mechanics: lure wake-up, lure duration, the luredRatio
accuracy bonus and the kbBonus damage bonus.

stdlib unittest only (pytest is not installed here). Run from the repo
root with:
    python -m unittest discover tests

Randomness is either seeded or monkeypatched, so every assertion below
is deterministic.
"""
import random
import unittest
from unittest import mock

from solver import data, mechanics, simulator
from solver.state import Action, BattleState, CogState, ToonState, Track
from solver.testing import two_flunky_fight


def _lured_cog(acc_before_bonus, rounds, level=2, hp=100, lure_level=2):
    """One Flunky, already lured with a known pre-bonus accuracy.
    `level` is the cog's level; `lure_level` is the Lure gag that landed."""
    cog = CogState(cog_type="flunky", department="bossbot", level=level,
                   hp=hp, max_hp=hp)
    cog.status.apply_lure(acc_before_bonus, rounds, lure_level)
    return cog


def early_expiry_enabled(lure_level=2):
    """Bring a Lure gag under the base-accuracy floor, which is the only way
    TTR 3.3.0 leaves the wake-up roll reachable. No real gag qualifies, so
    tests that exercise wake-up have to say so explicitly rather than
    relying on it happening by default.

    Raises the floor rather than lowering a gag's accuracy: Gag is frozen,
    and the threshold is the thing the rule actually turns on."""
    from solver.data import gags as _gags
    above = _gags.gag(Track.LURE, lure_level).accuracy + 1
    return mock.patch.object(mechanics.data, "EARLY_EXPIRY_ACCURACY_FLOOR",
                             above)


def _state_with(cogs):
    toon = ToonState(laff=100, max_laff=100,
                     track_exp={Track.THROW: 7, Track.LURE: 7, Track.TRAP: 7},
                     gag_counts={(Track.THROW, 3): 5, (Track.LURE, 2): 5,
                                 (Track.LURE, 5): 5, (Track.TRAP, 2): 5})
    return BattleState(toon=toon, cogs=list(cogs))


class TestLureAccuracyBeforeBonus(unittest.TestCase):
    def test_guide_worked_example(self):
        """Guide's own example: a Lureless toon's Lure (propAcc 70) on a
        level-12 cog -> 70 + 0 + (-55) = 15, wakeupChance 70."""
        toon = ToonState(laff=100, max_laff=100, track_exp={})   # Lureless
        cog = CogState(cog_type="flunky", department="bossbot", level=12,
                       hp=1, max_hp=1)
        acc = mechanics.lure_accuracy_before_bonus(Track.LURE, 5, toon, [cog])
        self.assertEqual(acc, 80 - 55)         # L5 propAcc 80, tgtDef -55
        self.assertEqual(mechanics.lure_wakeup_chance(acc), 50)

    def test_components_are_propacc_trackexp_tgtdef(self):
        state = two_flunky_fight()          # maxed Lure -> trackExp 60
        cog = CogState(cog_type="flunky", department="bossbot", level=6,
                       hp=1, max_hp=1)
        acc = mechanics.lure_accuracy_before_bonus(Track.LURE, 1,
                                                   state.toon, [cog])
        self.assertEqual(acc, 60 + 60 - 25)   # L1 propAcc 60 (TTR)

    def test_not_capped_at_95(self):
        """Documented reading: the 95 cap belongs to the post-bonus value
        the hit roll uses, not to the snapshot wakeupChance reads."""
        state = two_flunky_fight()
        cog = CogState(cog_type="flunky", department="bossbot", level=1,
                       hp=1, max_hp=1)
        acc = mechanics.lure_accuracy_before_bonus(Track.LURE, 5,
                                                   state.toon, [cog])
        self.assertEqual(acc, 80 + 60 - 2)     # L5 propAcc 80 (TTR)
        self.assertGreater(acc, data.ACCURACY_CAP)
        capped = mechanics.calc_toon_accuracy(Track.LURE, 5, state.toon, [cog])
        self.assertEqual(capped, data.ACCURACY_CAP)

    def test_organic_lure_uses_bonus_prop_accuracy(self):
        state = two_flunky_fight()
        cog = CogState(cog_type="flunky", department="bossbot", level=6,
                       hp=1, max_hp=1)
        acc = mechanics.lure_accuracy_before_bonus(
            Track.LURE, 1, state.toon, [cog], lure_tree_planted=True)
        self.assertEqual(acc, 70 + 60 - 25)   # organic L1 is 70


class TestWakeupChance(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(mechanics.lure_wakeup_chance(15), 70)
        self.assertEqual(mechanics.lure_wakeup_chance(0), 100)
        self.assertEqual(mechanics.lure_wakeup_chance(50), 0)
        self.assertEqual(mechanics.lure_wakeup_chance(105), -110)

    def test_wakes_at_the_stated_rate(self):
        """wakeupChance 70 -> ~70% of rolls wake. Seeded, so this is a
        fixed number, not a flaky sample."""
        random.seed(1234)
        woke = sum(mechanics.lure_wakes_up(15) for _ in range(10000))
        self.assertAlmostEqual(woke / 10000, 0.70, delta=0.02)

    def test_accuracy_at_or_above_50_never_wakes(self):
        random.seed(7)
        for acc in (50, 95, 105):
            self.assertEqual(sum(mechanics.lure_wakes_up(acc)
                                 for _ in range(2000)), 0)

    def test_roll_boundaries(self):
        with mock.patch.object(mechanics.random, "randint", return_value=69):
            self.assertTrue(mechanics.lure_wakes_up(15))     # 69 < 70
        with mock.patch.object(mechanics.random, "randint", return_value=70):
            self.assertFalse(mechanics.lure_wakes_up(15))    # 70 < 70 is False


class TestLureDuration(unittest.TestCase):
    """Durations are now [CONFIRMED] from the TTR wiki, so they resolve
    instead of raising, and the synthetic stand-in is gone."""

    def test_durations_match_the_wiki(self):
        expected = {1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 8}
        for level, rounds in expected.items():
            self.assertEqual(mechanics.lure_duration_rounds(level), rounds)

    def test_lure_action_resolves(self):
        """A Lure used to raise for want of a duration. It shouldn't now."""
        state = two_flunky_fight()
        state, _reward, _done = simulator.step(
            state, Action(track=Track.LURE, level=2, target_index=None))
        lured = [c for c in state.cogs if c.status.lured]
        self.assertTrue(lured, "Small Magnet should have lured something")
        for cog in lured:
            # 2 rounds for Small Magnet, less the tick this round's own
            # cog phase already took.
            self.assertEqual(cog.status.lure_rounds_remaining, 1)
            self.assertEqual(cog.status.lure_level, 2)


class TestNoEarlyExpiry(unittest.TestCase):
    """TTR 3.3.0 left early expiry reachable only for Lure gags with base
    accuracy under 50%, and no such gag exists -- so lures now run their
    full duration."""

    def test_no_current_lure_gag_can_expire_early(self):
        for level in range(1, 8):
            self.assertFalse(mechanics.lure_can_expire_early(level))
            self.assertFalse(mechanics.lure_can_expire_early(
                level, lure_tree_planted=True))

    def test_rule_would_re_enable_below_the_floor(self):
        """Guard the threshold itself, so this stays a rule rather than a
        hardcoded False if a future rebalance moves a gag across it. $5 Bill
        is 70 and Big Magnet 65, so a floor of 68 catches exactly one."""
        with mock.patch.object(mechanics.data,
                               "EARLY_EXPIRY_ACCURACY_FLOOR", 68):
            self.assertFalse(mechanics.lure_can_expire_early(3))   # 70
            self.assertTrue(mechanics.lure_can_expire_early(4))    # 65

    def test_lured_cog_never_wakes_before_its_rounds_run_out(self):
        """Even with the wake-up roll rigged to always succeed."""
        state = two_flunky_fight()
        state, _r, _d = simulator.step(
            state, Action(track=Track.LURE, level=2, target_index=None))
        with mock.patch.object(mechanics, "lure_wakes_up", return_value=True):
            state, _r, _d = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        survivors = [c for c in state.cogs if not c.status.is_dead]
        for cog in survivors:
            self.assertTrue(cog.status.lured,
                            "lure ended early despite 3.3.0 removing that")


class TestCogPhaseWakeUp(unittest.TestCase):
    """The core fix: a lured cog is no longer out of the fight forever."""

    def _phase(self, state):
        # Force every cog attack that does happen to land, so "damage > 0"
        # is a clean proxy for "the cog attacked".
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            return simulator._resolve_cog_phase(state)

    def test_wakes_clears_state_and_attacks_the_same_round(self):
        # pre-bonus accuracy 0 -> wakeupChance 100 -> always wakes, but only
        # once the gag is under the 3.3.0 base-accuracy floor.
        cog = _lured_cog(0, rounds=3)
        with early_expiry_enabled():
            dmg = self._phase(_state_with([cog]))
        self.assertGreater(dmg, 0, "a woken cog must attack that same round")
        self.assertFalse(cog.status.lured)
        self.assertIsNone(cog.status.lure_acc_before_bonus)
        self.assertEqual(cog.status.lure_rounds_remaining, 0)

    def test_still_lured_cog_skips_and_burns_a_round(self):
        # pre-bonus accuracy 105 -> wakeupChance -110 -> never wakes.
        cog = _lured_cog(105, rounds=3)
        dmg = self._phase(_state_with([cog]))
        self.assertEqual(dmg, 0)
        self.assertTrue(cog.status.lured)
        self.assertEqual(cog.status.lure_rounds_remaining, 2)
        self.assertEqual(cog.status.lure_acc_before_bonus, 105)

    def test_lure_expires_when_its_rounds_run_out(self):
        """Even a lure that can never be woken from ends on schedule."""
        cog = _lured_cog(105, rounds=2)
        state = _state_with([cog])
        self.assertEqual(self._phase(state), 0)     # round 1: held
        self.assertEqual(self._phase(state), 0)     # round 2: held
        dmg = self._phase(state)                    # round 3: timed out
        self.assertGreater(dmg, 0)
        self.assertFalse(cog.status.lured)

    def test_unlured_cog_is_untouched_by_the_lure_path(self):
        cog = CogState(cog_type="flunky", department="bossbot", level=2,
                       hp=100, max_hp=100)
        self.assertGreater(self._phase(_state_with([cog])), 0)
        self.assertFalse(cog.status.lured)

    def test_lured_cog_without_stored_accuracy_raises(self):
        cog = CogState(cog_type="flunky", department="bossbot", level=2,
                       hp=100, max_hp=100)
        cog.status.lured = True                 # set by hand, no accuracy
        cog.status.lure_rounds_remaining = 2
        with self.assertRaises(ValueError):
            self._phase(_state_with([cog]))

    def test_only_the_woken_cog_attacks(self):
        # Both lured by a sub-floor gag so the wake-up roll is live at all;
        # the first has wakeupChance 100, the second -110.
        woken = _lured_cog(0, rounds=3)         # wakes
        asleep = _lured_cog(105, rounds=3)      # holds
        state = _state_with([woken, asleep])
        with early_expiry_enabled(), \
                mock.patch.object(mechanics, "roll_hit", return_value=True), \
                mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(7, 100)):
            dmg = simulator._resolve_cog_phase(state)
        self.assertEqual(dmg, 7)                # exactly one attacker
        self.assertFalse(woken.status.lured)
        self.assertTrue(asleep.status.lured)


class TestLureLanding(unittest.TestCase):
    def test_successful_lure_records_pre_bonus_accuracy(self):
        state = two_flunky_fight()
        state.cogs[1].status.is_dead = True      # single target, level-2 cog
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=0))
        cog = state.cogs[0]
        self.assertTrue(cog.status.lured)
        # propAcc 55 (Small Magnet) + trackExp 60 + tgtDef(level 2) -5.
        self.assertEqual(cog.status.lure_acc_before_bonus, 110)
        self.assertEqual(cog.status.lure_level, 2)
        # 2 rounds, one already ticked by this round's own cog phase.
        self.assertEqual(cog.status.lure_rounds_remaining, 1)

    def test_missed_lure_records_nothing(self):
        state = two_flunky_fight()
        state.cogs[1].status.is_dead = True
        with mock.patch.object(mechanics, "roll_hit", return_value=False):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=0))
        self.assertFalse(state.cogs[0].status.lured)
        self.assertIsNone(state.cogs[0].status.lure_acc_before_bonus)

    def test_one_lure_does_not_remove_a_cog_forever(self):
        """Regression guard for the bug this file exists for: before the
        fix, a single landed Lure took a cog out of the fight permanently.
        Now the lure runs out (or is woken from) and the cog attacks
        again."""
        cog = CogState(cog_type="flunky", department="bossbot", level=2,
                       hp=500, max_hp=500)
        state = _state_with([cog])
        random.seed(0)
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=0))
            self.assertTrue(state.cogs[0].status.lured)
            laff_after_lure = state.toon.laff
            for _ in range(5):      # 3 synthetic lure rounds, then some
                state, _r, _done = simulator.step(
                    state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertFalse(state.cogs[0].status.lured)
        self.assertLess(state.toon.laff, laff_after_lure,
                        "the lure never ended -- cog got no attacks in")

    def test_relanding_a_lure_does_not_refresh_it(self):
        """A Lure on an already-lured cog is wasted: the existing counter
        keeps running down on its original schedule. It neither stacks
        (3.0.0 removed that) nor refreshes."""
        cog = _lured_cog(105, rounds=2, hp=500)
        state = _state_with([cog])
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=5, target_index=0))
        after = state.cogs[0].status
        # Not 4 (a level-5 refresh), not 6 (stacked) -- just the original 2
        # less the tick this round's own cog phase took.
        self.assertEqual(after.lure_rounds_remaining, 1)
        self.assertEqual(after.lure_acc_before_bonus, 105,
                         "the original lure's accuracy must survive")
        self.assertEqual(after.lure_level, 2,
                         "the original lure's gag level must survive")

    def test_group_lure_still_catches_the_unlured(self):
        """The no-refresh rule is a per-cog no-op, not a rejected action:
        a group Lure over a partly-lured battle must still catch the cogs
        that aren't lured yet."""
        already = _lured_cog(105, rounds=2, hp=500)
        fresh = CogState(cog_type="flunky", department="bossbot", level=2,
                         hp=500, max_hp=500)
        state = _state_with([already, fresh])
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=None))
        self.assertTrue(state.cogs[1].status.lured, "un-lured cog missed out")
        self.assertEqual(state.cogs[0].status.lure_rounds_remaining, 1)
        self.assertEqual(state.cogs[1].status.lure_rounds_remaining, 1)


class TestLuredRatioBonus(unittest.TestCase):
    """bonus term: luredRatio = (lured cogs / total cogs) * 100."""

    def _cogs(self, lured_flags):
        out = []
        for i, lured in enumerate(lured_flags):
            cog = CogState(cog_type="flunky", department="bossbot", level=2,
                           hp=10, max_hp=10)
            if lured:
                cog.status.apply_lure(105, 3, 2)
            out.append(cog)
        return out

    def test_ratio(self):
        # Sound gets it at every level; Throw/Squirt only at level 7.
        self.assertEqual(
            mechanics.calc_lured_ratio_bonus(Track.SOUND, 3,
                                             self._cogs([True, False])), 50)
        self.assertEqual(
            mechanics.calc_lured_ratio_bonus(Track.SQUIRT, 7,
                                             self._cogs([True, True])), 100)
        self.assertEqual(
            mechanics.calc_lured_ratio_bonus(Track.SOUND, 1,
                                             self._cogs([False, False])), 0)

    def test_only_sound_and_level_7_throw_squirt_qualify(self):
        """[CONFIRMED] TTR wiki: the bonus goes to "all Sound gags, and
        level 7 Throw or Squirt gags". The strategy guide's rule was
        "everything except Lure/Toon-Up/Drop", which wrongly gave it to
        ordinary single-target Throw/Squirt and to Trap."""
        self.assertTrue(mechanics.gets_lured_ratio(Track.SOUND, 1))
        self.assertTrue(mechanics.gets_lured_ratio(Track.SOUND, 7))
        self.assertTrue(mechanics.gets_lured_ratio(Track.THROW, 7))
        self.assertTrue(mechanics.gets_lured_ratio(Track.SQUIRT, 7))

        for level in range(1, 7):
            self.assertFalse(mechanics.gets_lured_ratio(Track.THROW, level))
            self.assertFalse(mechanics.gets_lured_ratio(Track.SQUIRT, level))
        for track in (Track.LURE, Track.TOON_UP, Track.DROP, Track.TRAP):
            for level in range(1, 8):
                self.assertFalse(mechanics.gets_lured_ratio(track, level))

    def test_excluded_tracks(self):
        cogs = self._cogs([True, True])
        for track in (Track.LURE, Track.TOON_UP, Track.DROP, Track.TRAP):
            self.assertEqual(
                mechanics.calc_lured_ratio_bonus(track, 3, cogs), 0)

    def test_dead_cogs_are_out_of_the_denominator(self):
        cogs = self._cogs([True, False])
        cogs[1].status.is_dead = True
        self.assertEqual(
            mechanics.calc_lured_ratio_bonus(Track.SOUND, 3, cogs), 100)

    def test_feeds_into_toon_accuracy(self):
        state = two_flunky_fight()
        cogs = self._cogs([True, False])
        # Level-3 Throw does NOT get luredRatio: 75 propAcc + 60 trackExp - 5.
        plain = mechanics.calc_toon_accuracy(Track.THROW, 3, state.toon,
                                             [cogs[1]], all_cogs=cogs)
        self.assertEqual(plain, min(75 + 60 - 5, data.ACCURACY_CAP))
        # Sound does: 95 + 60 - 5 + 50, capped.
        boosted = mechanics.calc_toon_accuracy(Track.SOUND, 1, state.toon,
                                               cogs, all_cogs=cogs)
        self.assertEqual(boosted, data.ACCURACY_CAP)

class TestKnockbackBonus(unittest.TestCase):
    """kbBonus = totalDmgs * 0.50, Throw/Squirt on a lured target."""

    def test_multiplier_and_eligibility(self):
        self.assertEqual(mechanics.calc_kb_bonus(Track.THROW, True, 20), 10.0)
        self.assertEqual(mechanics.calc_kb_bonus(Track.SQUIRT, True, 21), 10.5)
        self.assertEqual(mechanics.calc_kb_bonus(Track.THROW, False, 20), 0.0)
        for track in (Track.SOUND, Track.DROP, Track.LURE, Track.TRAP):
            self.assertEqual(mechanics.calc_kb_bonus(track, True, 20), 0.0)

    def test_hp_bonus_is_zero_for_a_solo_toon(self):
        self.assertEqual(mechanics.calc_hp_bonus(100), 0.0)

    def test_throw_at_a_lured_cog_deals_the_bonus(self):
        base = mechanics.calc_toon_damage(Track.THROW, 3)     # 17
        lured = _lured_cog(105, rounds=3, hp=200)
        state = _state_with([lured])
        with mock.patch.object(mechanics, "roll_hit", return_value=True), \
                mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(0, 100)):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        # 17 + floor(8.5) worth of HP: total 25.5 floored to 25.
        self.assertEqual(state.cogs[0].hp, 200 - int(base * 1.5))
        self.assertGreater(base * 1.5, base)

    def test_throw_at_an_unlured_cog_deals_base_damage(self):
        base = mechanics.calc_toon_damage(Track.THROW, 3)
        cog = CogState(cog_type="flunky", department="bossbot", level=2,
                       hp=200, max_hp=200)
        state = _state_with([cog])
        with mock.patch.object(mechanics, "roll_hit", return_value=True), \
                mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(0, 100)):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertEqual(state.cogs[0].hp, 200 - base)


class TestDamageDoesNotEndLure(unittest.TestCase):
    """Not a claim that this is right -- a guard that the unconfirmed
    mechanic stays unimplemented and visible. See
    mechanics.LURE_ENDS_ON_DAMAGE; flip both if the source is nailed down."""

    def test_open_questions_are_still_open(self):
        self.assertIsNone(mechanics.LURE_ENDS_ON_DAMAGE)
        self.assertIsNone(mechanics.DROP_MISSES_LURED_COGS)

    def test_surviving_damaged_cog_keeps_its_lure(self):
        lured = _lured_cog(105, rounds=3, hp=200)
        state = _state_with([lured])
        with mock.patch.object(mechanics, "roll_hit", return_value=True), \
                mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(0, 100)):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertTrue(state.cogs[0].status.lured)

    def test_killed_lured_cog_has_its_lure_cleared(self):
        lured = _lured_cog(105, rounds=3, hp=5)
        state = _state_with([lured])
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertTrue(state.cogs[0].status.is_dead)
        self.assertFalse(state.cogs[0].status.lured)
        self.assertIsNone(state.cogs[0].status.lure_acc_before_bonus)


if __name__ == "__main__":
    unittest.main()
