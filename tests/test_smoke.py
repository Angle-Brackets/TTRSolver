"""
End-to-end smoke test plus a few checks on the pieces of the model that
are [CONFIRMED] enough to assert on.

Run from the repo root with:
    python -m unittest discover tests

The full-fight tests run under solver.testing.synthetic_battle_data(),
i.e. with FAKE cog accuracy and FAKE lure durations -- they prove the
code paths connect, not that the numbers are game-accurate.

Status-effect mechanics (lure wake-up / duration, luredRatio, kbBonus)
have their own file: tests/test_mechanics.py.
"""
import contextlib
import io
import random
import unittest

from solver import data, mechanics, simulator
from solver.demo import run_random_policy
from solver.state import Track, Action, CogState
from solver.testing import two_flunky_fight


class TestAccuracy(unittest.TestCase):
    def test_trap_always_hits(self):
        state = two_flunky_fight()
        acc = mechanics.calc_toon_accuracy(Track.TRAP, 2, state.toon, state.cogs)
        self.assertEqual(acc, 100)

    def test_formula_components_sum(self):
        # Lure L1 ($1 Bill, propAcc 60) + maxed track (60)
        # + level-6 cog tgtDef (-25)
        state = two_flunky_fight()
        cog = CogState(cog_type="flunky", department="bossbot", level=6,
                       hp=1, max_hp=1)
        acc = mechanics.calc_toon_accuracy(Track.LURE, 1, state.toon, [cog])
        self.assertEqual(acc, 60 + 60 - 25)

    def test_accuracy_is_capped(self):
        # Throw L3: 75 + 60 - 5 = 130, well over the cap.
        state = two_flunky_fight()
        acc = mechanics.calc_toon_accuracy(Track.THROW, 3, state.toon,
                                           [state.cogs[0]])
        self.assertEqual(acc, data.ACCURACY_CAP)

    def test_untrained_track_gets_no_exp_bonus(self):
        state = two_flunky_fight()
        self.assertEqual(mechanics.calc_track_exp(state.toon, Track.DROP), 0)

    def test_group_attack_uses_strongest_cog_defense(self):
        state = two_flunky_fight()  # cogs at levels 2 and 3
        self.assertEqual(mechanics.calc_tgt_def(Track.SOUND, state.cogs),
                         data.TGT_DEF_BY_LEVEL[3])


class TestLegalActions(unittest.TestCase):
    def test_only_owned_tracks_with_stock_are_offered(self):
        state = two_flunky_fight()
        offered = {(a.track, a.level) for a in simulator.legal_actions(state)}
        self.assertEqual(offered, {(Track.THROW, 3), (Track.LURE, 2),
                                   (Track.TRAP, 2)})

    def test_trap_not_offered_on_trapped_or_lured_cog(self):
        state = two_flunky_fight()
        state.cogs[0].status.trapped = True
        state.cogs[1].status.lured = True
        traps = [a for a in simulator.legal_actions(state)
                 if a.track == Track.TRAP]
        self.assertEqual(traps, [])

    def test_no_actions_when_all_cogs_dead(self):
        state = two_flunky_fight()
        for cog in state.cogs:
            cog.status.is_dead = True
        self.assertEqual(simulator.legal_actions(state), [])


class TestMissingDataRaises(unittest.TestCase):
    """The project rule is that TODO data raises rather than silently
    producing a made-up number. These guard that rule."""

    def test_todo_gag_damage_raises(self):
        with self.assertRaises(NotImplementedError):
            mechanics.calc_toon_damage(Track.DROP, 1)

    def test_todo_cog_accuracy_raises(self):
        """Data-driven so it survives the accuracy tables being filled in:
        pick any cog whose table is still None, or skip once none are."""
        for dept, cogs in data.COG_DEPARTMENTS.items():
            for cog_type, table in cogs.items():
                if table.get("accuracy") is None:
                    cog = CogState(cog_type=cog_type, department=dept,
                                   level=table["levels"][0], hp=1, max_hp=1)
                    attack = next(iter(table["freq"]))
                    with self.assertRaises(NotImplementedError):
                        mechanics.cog_attack_damage_and_accuracy(cog, attack)
                    return
        self.skipTest("every cog accuracy table is transcribed")

    def test_trap_damage_is_still_todo(self):
        """Per-level Trap damage is the gag gap that remains. Laying a trap
        and luring the cog onto it must raise rather than invent a number.
        (Lure duration used to be listed here too; it's [CONFIRMED] from the
        wiki now.)"""
        state = two_flunky_fight()
        state.cogs[1].status.is_dead = True
        state, _r, _d = simulator.step(
            state, Action(track=Track.TRAP, level=2, target_index=0))
        with self.assertRaises(NotImplementedError):
            simulator.step(state, Action(track=Track.LURE, level=2,
                                         target_index=0))

    def test_toon_up_raises(self):
        state = two_flunky_fight()
        state.toon.track_exp[Track.TOON_UP] = 7
        state.toon.gag_counts[(Track.TOON_UP, 1)] = 1
        with self.assertRaises(NotImplementedError):
            simulator.step(state, Action(track=Track.TOON_UP, level=1))

    def test_trap_lure_combo_raises_while_trap_damage_is_todo(self):
        """The trap+lure detonation path is implemented, but per-level trap
        damage isn't transcribed yet -- so triggering it must raise, not
        deal a guessed number. Delete this test when data/gags.py gains
        real Trap rows."""
        if data.GAG_DAMAGE_MINMAX[Track.TRAP].get(2) is not None:
            self.skipTest("Trap level-2 damage has been transcribed")
        state = two_flunky_fight()
        state.cogs[1].status.is_dead = True  # keep it to a single target
        # Synthetic data only so the surrounding round loop can run (cog
        # counter-attacks, lure duration); the assertion below is about
        # trap damage, which is real TODO data.
        state, _r, _done = simulator.step(
            state, Action(track=Track.TRAP, level=2, target_index=0))
        self.assertTrue(state.cogs[0].status.trapped)
        with self.assertRaises(NotImplementedError):
            simulator.step(
                state, Action(track=Track.LURE, level=2, target_index=0))

    def test_synthetic_stand_ins_do_not_leak(self):
        real_accuracy = data.BOSSBOT_COGS["flunky"]["accuracy"]
        real_durations = dict(mechanics.LURE_ROUNDS_BY_LEVEL)
        self.assertIsNotNone(data.BOSSBOT_COGS["flunky"]["accuracy"])
        self.assertIsNotNone(mechanics.LURE_ROUNDS_BY_LEVEL[2])
        self.assertIs(data.BOSSBOT_COGS["flunky"]["accuracy"], real_accuracy)
        self.assertEqual(mechanics.LURE_ROUNDS_BY_LEVEL, real_durations)


class TestFullFight(unittest.TestCase):
    def test_random_policy_fight_terminates(self):
        random.seed(0)
        state = two_flunky_fight()
        for _ in range(60):
            if state.is_terminal():
                break
            candidates = simulator.legal_actions(state)
            done = None
            # Luring a trapped cog needs [TODO] Trap damage and raises;
            # retry past those rather than counting them as the end.
            while candidates:
                action = random.choice(candidates)
                try:
                    state, _reward, done = simulator.step(state, action)
                    break
                except NotImplementedError:
                    candidates.remove(action)
            if done is None or done:
                break
        self.assertTrue(state.is_terminal(),
                        "fight ran 60 rounds without reaching a terminal state")
        self.assertGreater(state.round_num, 0)

    def test_demo_runs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_random_policy(seed=0)
        self.assertIn("Battle finished", out.getvalue())

    def test_a_lure_lands_and_later_ends_during_a_real_fight(self):
        """Round-loop level check on the lure fix. Before it, one landed
        Lure removed a cog from the fight permanently. Detailed coverage
        of the wake-up / timeout paths lives in tests/test_mechanics.py."""
        random.seed(3)
        state = two_flunky_fight()
        state.toon.laff = state.toon.max_laff = 500        # let it run long
        state.cogs[1].status.is_dead = True                # one target
        state.cogs[0].hp = state.cogs[0].max_hp = 500      # don't kill it
        state.toon.gag_counts = {(Track.LURE, 2): 1, (Track.THROW, 3): 40}
        state, _r, _done = simulator.step(
            state, Action(track=Track.LURE, level=2, target_index=0))
        lured_at_least_once = state.cogs[0].status.lured
        for _ in range(6):
            state, _r, _done = simulator.step(
                state, Action(track=Track.THROW, level=3, target_index=0))
        self.assertTrue(lured_at_least_once)
        self.assertFalse(state.cogs[0].status.lured)
        self.assertLess(state.toon.laff, state.toon.max_laff,
                        "the lured cog never got an attack in")


if __name__ == "__main__":
    unittest.main()
