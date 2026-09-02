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


class TestGroupTrap(unittest.TestCase):
    """Railroad is a group gag: it arms every cog, not just the first.

    Arming only targets[0] made the best trap in the game behave like a
    single-target one, so the Railroad+Lure combo -- which should clear a
    field outright -- looked weaker than a plain pie and no strategy would
    take it."""

    def _field(self):
        toon = ToonState(laff=45, max_laff=45,
                         track_exp={Track.TRAP: 7, Track.LURE: 7},
                         gag_counts={(Track.TRAP, 7): 1, (Track.LURE, 2): 2})
        cogs = [CogState(cog_type="flunky", department="bossbot", level=lvl,
                         hp=data.cog_max_hp(lvl), max_hp=data.cog_max_hp(lvl))
                for lvl in (4, 5)]
        return BattleState(toon=toon, cogs=cogs)

    def test_railroad_arms_every_cog(self):
        state = self._field()
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=7, target_index=None))
        self.assertTrue(all(c.status.trapped for c in state.cogs))

    def test_a_single_target_trap_arms_only_its_target(self):
        state = self._field()
        state.toon.gag_counts[(Track.TRAP, 3)] = 1
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=3, target_index=0))
        self.assertTrue(state.cogs[0].status.trapped)
        self.assertFalse(state.cogs[1].status.trapped)

    def test_railroad_then_lure_clears_the_field(self):
        # Seeded because this asserts the Lure LANDS, which is an
        # accuracy roll off the module-level `random`. Unseeded it
        # passed on most streams and failed on some, so it was a flake
        # waiting for an unrelated test to consume a different number of
        # draws -- which is exactly how it surfaced.
        random.seed(0)
        state = self._field()
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=7, target_index=None))
        state, _r, done = simulator.step(
            state, Action(track=Track.LURE, level=2, target_index=None))
        self.assertTrue(all(c.status.is_dead for c in state.cogs))
        self.assertTrue(done)

    def test_railroad_wakes_the_field_to_lay_itself(self):
        """[CONFIRMED] by the owner: a group Trap needs one unlured cog
        to go down, and laying it un-lures every lured cog so the track
        runs under all of them.

        This test asserted the opposite -- that a lured cog is skipped,
        the rule single-target Traps follow. Skipping made the strongest
        combination in the game unplayable whenever anything happened to
        be asleep already."""
        state = self._field()
        state.cogs[0].status.apply_lure(110, 2, 2)
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=7, target_index=None))
        self.assertTrue(all(c.status.trapped for c in state.cogs))
        self.assertFalse(any(c.status.lured for c in state.cogs),
                         "laying the Railroad wakes them")

    def test_railroad_needs_one_unlured_cog(self):
        """With the whole field asleep there is nowhere to lay it."""
        state = self._field()
        for cog in state.cogs:
            cog.status.apply_lure(110, 2, 2)
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=7, target_index=None))
        self.assertFalse(any(c.status.trapped for c in state.cogs))
        self.assertTrue(all(c.status.lured for c in state.cogs),
                        "and it does not wake them either")

    def test_a_single_target_trap_still_refuses_a_lured_cog(self):
        """The waking rule belongs to the group Trap alone."""
        state = self._field()
        state.toon.gag_counts[(Track.TRAP, 3)] = 1
        state.cogs[0].status.apply_lure(110, 2, 2)
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=3, target_index=0))
        self.assertFalse(state.cogs[0].status.trapped)
        self.assertTrue(state.cogs[0].status.lured)

    def test_railroad_and_lure_in_ONE_round_clears_the_field(self):
        """Trap resolves before Lure, so the Railroad wakes and arms the
        field and the Lure then springs it -- in a single round. This is
        what the waking rule is for, and it was unreachable while lured
        cogs were skipped."""
        from solver.state import ToonState as _T

        toon = _T(laff=45, max_laff=45,
                  track_exp={Track.TRAP: 7, Track.LURE: 7},
                  gag_counts={(Track.TRAP, 7): 1, (Track.LURE, 2): 2},
                  organic_tracks=frozenset())
        mate = _T(laff=45, max_laff=45,
                  track_exp={Track.TRAP: 7, Track.LURE: 7},
                  gag_counts={(Track.TRAP, 7): 1, (Track.LURE, 2): 2},
                  organic_tracks=frozenset())
        cogs = [CogState(cog_type="flunky", department="bossbot", level=lvl,
                         hp=data.cog_max_hp(lvl), max_hp=data.cog_max_hp(lvl))
                for lvl in (4, 5)]
        state = BattleState(toons=[toon, mate], cogs=cogs)
        state.cogs[0].status.apply_lure(110, 2, 2)
        simulator.apply_party_round(
            state,
            [Action(track=Track.TRAP, level=7, target_index=None),
             Action(track=Track.LURE, level=2, target_index=None)],
            hits=[True, True])
        self.assertTrue(all(c.status.is_dead for c in state.cogs))


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
        """One gag on a target is not "two or more"."""
        self.assertEqual(mechanics.calc_hp_bonus(100), 0)
        self.assertEqual(mechanics.calc_hp_bonus(100, 1), 0)

    def test_hp_bonus_is_a_fifth_of_the_combined_damage(self):
        """[CONFIRMED] TTR wiki (Gags): "When two or more of the same gag
        type (excluding Lure, Trap, and Toon-Up) are used on a Cog
        simultaneously, a 20% damage bonus applies."

        This is the entire reason coordinating a party is worth
        anything, and it returned 0 unconditionally until now -- so a
        search over the old rules rated four toons stacking Throw on one
        cog exactly level with four toons hitting four different cogs.
        """
        self.assertEqual(mechanics.calc_hp_bonus(100, 2), 20)
        self.assertEqual(mechanics.calc_hp_bonus(100, 4), 20)

    def test_hp_bonus_is_of_the_total_not_per_gag(self):
        """Three gags do not earn 60%. They earn 20% of a larger total,
        which is where the extra comes from."""
        self.assertEqual(mechanics.calc_hp_bonus(150, 3), 30)

    def test_hp_bonus_rounds_up(self):
        """Rounding is NOT wiki-confirmed -- the wiki says "a 20% damage
        bonus" and not how it rounds. `ceil` comes from the QED1224
        source doc, which describes Toontown Online. Pinned so that a
        change to it is a decision rather than a drift."""
        self.assertEqual(mechanics.calc_hp_bonus(11, 2), 3)     # 2.2 -> 3


class PrevHitsFromTrapTest(unittest.TestCase):
    """Trap's contribution to accuracy, which is a solo rule.

    `calc_prev_hits_bonus` returned 0 unconditionally, on the reasoning
    that PrevHits is a same-round bonus between different toons and a
    solo toon acts once per round. That is right about the same-round
    half and wrong about Trap, which the wiki says explicitly persists:

      "The first Trap gag that is placed grants +10 to PrevHits, but
       only for Lure."
      "Further Trap gag placements grant an additional +5 to a group
       Lure gag."
      "The PrevHits for Lure remain across multiple rounds, as long as
       Trap is present."

    Trap in one round then Lure in the next is the commonest solo line
    there is, and it was being rolled ten points short.
    """

    def cogs(self, n, trapped=0):
        from solver import data
        from solver.state import CogState

        out = []
        for i in range(n):
            cog = CogState("flunky", "bossbot", 3,
                           data.cog_max_hp(3), data.cog_max_hp(3))
            if i < trapped:
                cog.status.trapped = True
                cog.status.trap_level = 3
                cog.status.trap_track = Track.TRAP
            out.append(cog)
        return out

    def test_no_trap_no_bonus(self):
        self.assertEqual(
            mechanics.calc_prev_hits_bonus(Track.LURE, 1, self.cogs(2)), 0)

    def test_the_first_trap_is_worth_ten_to_a_lure(self):
        self.assertEqual(
            mechanics.calc_prev_hits_bonus(Track.LURE, 1,
                                           self.cogs(2, trapped=1)), 10)

    def test_only_lure_collects_it(self):
        """"but only for Lure" -- a Throw at a trapped cog gets nothing."""
        for track in (Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP,
                      Track.TRAP, Track.TOON_UP):
            self.assertEqual(
                mechanics.calc_prev_hits_bonus(track, 1,
                                               self.cogs(2, trapped=1)), 0)

    def test_further_traps_add_five_to_a_group_lure(self):
        for traps, want in ((1, 10), (2, 15), (3, 20)):
            self.assertEqual(
                mechanics.calc_prev_hits_bonus(Track.LURE, 2,
                                               self.cogs(3, trapped=traps)),
                want, f"{traps} traps")

    def test_but_not_to_a_single_target_lure(self):
        """The wiki scopes the extra +5 to a group Lure gag."""
        self.assertEqual(
            mechanics.calc_prev_hits_bonus(Track.LURE, 1,
                                           self.cogs(3, trapped=3)), 10)

    def test_a_dead_cogs_trap_is_not_on_the_field(self):
        cogs = self.cogs(2, trapped=1)
        cogs[0].status.is_dead = True
        self.assertEqual(
            mechanics.calc_prev_hits_bonus(Track.LURE, 1, cogs), 0)

    def test_no_battle_state_means_no_opinion(self):
        """Callers that pass nothing keep the old behaviour."""
        self.assertEqual(mechanics.calc_prev_hits_bonus(Track.LURE), 0)
        self.assertEqual(mechanics.calc_prev_hits_bonus(Track.LURE, 1, []), 0)

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


class TestDamageEndsLure(unittest.TestCase):
    """A landed attack wakes a lured cog. [CONFIRMED] by the owner from
    play: ANY attack gag does this, not only Sound.

    This class used to be `TestDamageDoesNotEndLure` and guarded the
    opposite -- `LURE_ENDS_ON_DAMAGE` was `None`, an unfilled gap, and
    only Sound cleared the lure on the reading that the wiki names Sound
    explicitly. Naming one track is not excluding the others, and the
    gap was expensive: `prevented` multiplies by `lure_rounds_remaining`,
    so every lure was paid for rounds it could never deliver once
    anything hit the cog.
    """

    def test_the_questions_are_answered(self):
        self.assertTrue(mechanics.LURE_ENDS_ON_DAMAGE)
        self.assertTrue(mechanics.DROP_MISSES_LURED_COGS)

    def test_a_surviving_cog_wakes_up(self):
        lured = _lured_cog(105, rounds=3, hp=200)
        state = _state_with([lured])
        with mock.patch.object(mechanics, "roll_hit", return_value=True),                 mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(0, 100)):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertFalse(state.cogs[0].status.lured,
                         "a landed Throw has to wake it")

    def test_the_knockback_is_collected_before_it_wakes(self):
        """Order matters and the owner was explicit about it: the +50%
        lands against the SLEEPING cog, and only then does the lure end.
        Waking it first would quietly delete the bonus."""
        lured = _lured_cog(105, rounds=3, hp=400)
        plain = _lured_cog(105, rounds=0, hp=400)
        plain.status.lured = False
        hurt = []
        for cog in (lured, plain):
            state = _state_with([cog])
            before = state.cogs[0].hp
            with mock.patch.object(mechanics, "roll_hit", return_value=True),                     mock.patch.object(mechanics,
                                      "cog_attack_damage_and_accuracy",
                                      return_value=(0, 100)):
                state, _r, _done = simulator.step(
                    state, Action(track=Track.THROW, level=3, target_index=0))
            hurt.append(before - state.cogs[0].hp)
        self.assertGreater(hurt[0], hurt[1],
                           "the lured cog should still take knockback")

    def test_killed_lured_cog_has_its_lure_cleared(self):
        lured = _lured_cog(105, rounds=3, hp=5)
        state = _state_with([lured])
        with mock.patch.object(mechanics, "roll_hit", return_value=True):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertTrue(state.cogs[0].status.is_dead)
        self.assertFalse(state.cogs[0].status.lured)
        self.assertIsNone(state.cogs[0].status.lure_acc_before_bonus)

    def test_a_lure_does_not_wake_anybody(self):
        """Only DAMAGE wakes. Trap and Lure place effects, so a second
        Lure landing on a sleeping field must leave it asleep."""
        cogs = [_lured_cog(105, rounds=3, hp=200) for _ in range(2)]
        state = _state_with(cogs)
        with mock.patch.object(mechanics, "roll_hit", return_value=True),                 mock.patch.object(mechanics, "cog_attack_damage_and_accuracy",
                                  return_value=(0, 100)):
            state, _r, _done = simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=None))
        self.assertTrue(any(c.status.lured for c in state.cogs))


if __name__ == "__main__":
    unittest.main()


class TestTwoTrapsCancel(unittest.TestCase):
    """Two Traps at one cog in one round nil each other, and the gags are
    still spent. [CONFIRMED] by the owner from play.

    The Railroad is the exception: it nils the other and places anyway.

    This could not live in `apply_toon_action`, which is where Trap used
    to be resolved one toon at a time -- each call sees only its own
    trap, so the second silently overwrote the first and a cog that
    should have ended the round bare ended it armed.
    """

    def _party(self, n=4):
        toons = [ToonState(laff=80, max_laff=80,
                           track_exp={t: 7 for t in Track},
                           gag_counts={(t, l): 3 for t in Track
                                       for l in range(1, 8)},
                           organic_tracks=frozenset())
                 for _ in range(n)]
        hp = data.cog_max_hp(12)
        cogs = [CogState(cog_type="mr_hollywood", department="sellbot",
                         level=12, hp=hp, max_hp=hp) for _ in range(2)]
        return BattleState(toons=toons, cogs=cogs)

    def test_two_traps_on_one_cog_leave_it_bare(self):
        state = self._party()
        simulator.apply_party_round(
            state,
            [Action(Track.TRAP, 1, 0), Action(Track.TRAP, 3, 0), None, None],
            hits=[True] * 4)
        self.assertFalse(state.cogs[0].status.trapped)
        self.assertIsNone(state.cogs[0].status.trap_level)

    def test_both_gags_are_spent_anyway(self):
        state = self._party()
        simulator.apply_party_round(
            state,
            [Action(Track.TRAP, 1, 0), Action(Track.TRAP, 3, 0), None, None],
            hits=[True] * 4)
        self.assertEqual(state.toons[0].gag_counts[(Track.TRAP, 1)], 2)
        self.assertEqual(state.toons[1].gag_counts[(Track.TRAP, 3)], 2)

    def test_the_railroad_survives_being_nilled(self):
        state = self._party()
        simulator.apply_party_round(
            state,
            [Action(Track.TRAP, 1, 0), Action(Track.TRAP, 7, None),
             None, None],
            hits=[True] * 4)
        self.assertTrue(state.cogs[0].status.trapped)
        self.assertEqual(state.cogs[0].status.trap_level, 7,
                         "the Railroad places, the Banana Peel does not")

    def test_traps_on_different_cogs_both_place(self):
        state = self._party()
        simulator.apply_party_round(
            state,
            [Action(Track.TRAP, 1, 0), Action(Track.TRAP, 3, 1), None, None],
            hits=[True] * 4)
        self.assertEqual([c.status.trap_level for c in state.cogs], [1, 3])

    def test_one_trap_alone_still_places(self):
        state = self._party()
        simulator.apply_party_round(
            state, [Action(Track.TRAP, 6, 0), None, None, None],
            hits=[True] * 4)
        self.assertTrue(state.cogs[0].status.trapped)

    def test_a_second_trap_answers_a_badly_placed_one(self):
        """The reason this rule matters strategically: a teammate who
        traps a full-health cog about to be lured has thrown the lure
        away, and the only answer is to trap the same cog again."""
        state = self._party()
        simulator.apply_party_round(
            state,
            [Action(Track.TRAP, 1, 0), Action(Track.TRAP, 1, 0),
             Action(Track.LURE, 6, None), None],
            hits=[True] * 4)
        self.assertTrue(state.cogs[0].status.lured,
                        "nilling the trap leaves the Lure intact")
        self.assertEqual(state.cogs[0].hp, state.cogs[0].max_hp,
                         "and nothing sprang")


class TestSimultaneousLures(unittest.TestCase):
    """Two Lures in one round are ONE effect per cog, not two in order.

    [CONFIRMED] by the owner from play: "those lures fire simultaneously
    and the toons go sad."

    `apply_party_round` used to hand Lure to `apply_toon_action` once per
    toon. On a trapped cog that read as a sequence -- the first Lure
    sprang the trap and correctly left the cog awake, and the second then
    saw a bare cog and lured it. The party ended the round safe from a
    cog that in the real game is awake and swinging.

    The cost of the bug was strategic, not cosmetic. It made a group Lure
    look like an answer to a teammate's badly-placed Trap, so a policy
    trained against it learned to reach for one; the actual answers are
    nilling the Trap or overwriting it with a Railroad.

    What a second Lure legitimately buys is accuracy, via
    `mechanics.multi_lure_bonus`, and that is applied to the shared roll
    before any of this.
    """

    def _party(self, n=4, trapped_level=None):
        toons = [ToonState(laff=80, max_laff=80,
                           track_exp={t: 7 for t in Track},
                           gag_counts={(t, l): 3 for t in Track
                                       for l in range(1, 8)},
                           organic_tracks=frozenset())
                 for _ in range(n)]
        hp = data.cog_max_hp(12)
        cogs = [CogState(cog_type="mr_hollywood", department="sellbot",
                         level=12, hp=hp, max_hp=hp) for _ in range(2)]
        if trapped_level is not None:
            cogs[0].status.trapped = True
            cogs[0].status.trap_track = Track.TRAP
            cogs[0].status.trap_level = trapped_level
        return BattleState(toons=toons, cogs=cogs)

    def _round(self, state, actions):
        simulator.apply_party_round(state, actions, hits=[True] * 4)

    def test_the_second_lure_does_not_recatch_a_sprung_cog(self):
        """The bug, stated directly."""
        state = self._party(trapped_level=1)
        self._round(state, [Action(Track.LURE, 6, None),
                            Action(Track.LURE, 4, None), None, None])
        self.assertFalse(state.cogs[0].status.lured,
                         "the trap sprang; no simultaneous Lure re-catches it")

    def test_the_trap_still_springs(self):
        state = self._party(trapped_level=1)
        before = state.cogs[0].hp
        self._round(state, [Action(Track.LURE, 6, None),
                            Action(Track.LURE, 4, None), None, None])
        self.assertLess(state.cogs[0].hp, before)

    def test_the_trap_springs_exactly_once(self):
        """Two Lures are not two triggers -- there is one trap.

        Measured against the one-Lure case rather than against a damage
        number recomputed here, so organic and level rules stay in one
        place.
        """
        one = self._party(trapped_level=1)
        self._round(one, [Action(Track.LURE, 6, None), None, None, None])
        two = self._party(trapped_level=1)
        self._round(two, [Action(Track.LURE, 6, None),
                          Action(Track.LURE, 4, None), None, None])
        self.assertEqual(two.cogs[0].hp, one.cogs[0].hp)

    def test_untrapped_cogs_are_still_lured(self):
        """Only the sprung cog stays awake; the rest of a group Lure works."""
        state = self._party(trapped_level=1)
        self._round(state, [Action(Track.LURE, 6, None),
                            Action(Track.LURE, 4, None), None, None])
        self.assertTrue(state.cogs[1].status.lured)

    def test_both_lures_are_spent(self):
        state = self._party(trapped_level=1)
        self._round(state, [Action(Track.LURE, 6, None),
                            Action(Track.LURE, 4, None), None, None])
        self.assertEqual(state.toons[0].gag_counts[(Track.LURE, 6)], 2)
        self.assertEqual(state.toons[1].gag_counts[(Track.LURE, 4)], 2)

    def test_a_missed_lure_is_spent_and_does_nothing(self):
        state = self._party()
        simulator.apply_party_round(
            state, [Action(Track.LURE, 6, None), None, None, None],
            hits=[False] * 4)
        self.assertFalse(state.cogs[0].status.lured)
        self.assertEqual(state.toons[0].gag_counts[(Track.LURE, 6)], 2)

    def test_the_strongest_lure_sets_the_duration(self):
        """Same rule by which the best gag sharing a roll sets accuracy."""
        state = self._party()
        self._round(state, [Action(Track.LURE, 1, 0),
                            Action(Track.LURE, 6, 0), None, None])
        self.assertEqual(state.cogs[0].status.lure_rounds_remaining,
                         mechanics.lure_duration_rounds(6))

    def test_one_lure_on_a_trapped_cog_is_unchanged(self):
        """The single-Lure path was already right; keep it that way."""
        state = self._party(trapped_level=1)
        self._round(state, [Action(Track.LURE, 6, None), None, None, None])
        self.assertFalse(state.cogs[0].status.lured)
        self.assertFalse(state.cogs[0].status.trapped)

    def test_lures_alone_still_lure(self):
        state = self._party()
        self._round(state, [Action(Track.LURE, 6, None),
                            Action(Track.LURE, 4, None), None, None])
        self.assertTrue(all(c.status.lured for c in state.cogs))


class RevengeMemoryTest(unittest.TestCase):
    """A cog remembers who has been hitting it for the WHOLE FIGHT.

    Open Toontown wipes its damage record every round
    (`CLEAR_SUIT_ATTACKERS = 1`, cleared in `__initRound`), so a toon who
    stops attacking leaves the revenge pool there. [OWNER] that is a bug
    in TTO rather than a rule, so `damage_by_toon` accumulates here and
    is never reset.

    Pinned because the divergence is real and looks like a missing
    reset to anyone diffing against the source. It is deliberate --
    the third accident in that one function this project declines to
    reproduce.
    """

    def _board(self):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track
        hp = data.cog_max_hp(6)
        cogs = [CogState(department="sellbot", cog_type="cold_caller",
                         level=6, hp=hp, max_hp=hp)]
        toons = [ToonState(80, 137, {t: 7 for t in Track},
                           {(Track.THROW, 3): 9, (Track.SQUIRT, 3): 9},
                           frozenset()) for _ in range(2)]
        return BattleState(toons=toons, cogs=cogs)

    def test_damage_accumulates_across_rounds(self):
        from solver import simulator
        from solver.state import Action, Track
        state = self._board()
        simulator.apply_party_round(
            state, [Action(track=Track.THROW, level=3, target_index=0), None],
            hits=[True, True])
        first = dict(state.cogs[0].status.damage_by_toon)
        simulator.apply_party_round(
            state, [None, Action(track=Track.SQUIRT, level=3, target_index=0)],
            hits=[True, True])
        second = dict(state.cogs[0].status.damage_by_toon)
        self.assertEqual(set(first), {0})
        self.assertEqual(set(second), {0, 1},
                         "round one's attacker was forgotten -- that is "
                         "Open Toontown's behaviour, and it is a bug")
        self.assertEqual(second[0], first[0])

    def test_a_toon_that_stops_attacking_stays_a_target(self):
        """The consequence: passing does not shed aggro here."""
        import random
        from solver import mechanics, simulator
        from solver.state import Action, Track
        state = self._board()
        simulator.apply_party_round(
            state, [Action(track=Track.THROW, level=3, target_index=0), None],
            hits=[True, True])
        for _ in range(4):        # toon 0 passes from here on
            simulator.apply_party_round(state, [None, None], hits=[True, True])
        self.assertIn(0, state.cogs[0].status.damage_by_toon)
        picks = [mechanics.pick_cog_target(state.cogs[0], state.toons,
                                           random.Random(s))
                 for s in range(200)]
        self.assertGreater(picks.count(0), 0,
                           "the earlier attacker left the revenge pool")
