"""
End-to-end smoke test plus a few checks on the pieces of the model that
are [CONFIRMED] enough to assert on.

Run from the repo root with either:
    python -m unittest discover tests
    python -m pytest tests            (if pytest is installed)

The full-fight test runs under solver.testing.synthetic_bossbot_accuracy(),
i.e. with FAKE cog accuracy -- it proves the code paths connect, not that
the numbers are game-accurate.
"""
import contextlib
import io
import random
import unittest

from solver import data, mechanics, simulator
from solver.demo import run_random_policy
from solver.state import Track, Action, CogState
from solver.testing import synthetic_bossbot_accuracy, two_flunky_fight


class TestAccuracy(unittest.TestCase):
    def test_trap_always_hits(self):
        state = two_flunky_fight()
        acc = mechanics.calc_toon_accuracy(Track.TRAP, 2, state.toon, state.cogs)
        self.assertEqual(acc, 100)

    def test_formula_components_sum(self):
        # Lure L1 (propAcc 50) + maxed track (60) + level-6 cog tgtDef (-25)
        state = two_flunky_fight()
        cog = CogState(cog_type="flunky", department="bossbot", level=6,
                       hp=1, max_hp=1)
        acc = mechanics.calc_toon_accuracy(Track.LURE, 1, state.toon, [cog])
        self.assertEqual(acc, 50 + 60 - 25)

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
        cog = CogState(cog_type="flunky", department="bossbot", level=1,
                       hp=1, max_hp=1)
        with self.assertRaises(NotImplementedError):
            mechanics.cog_attack_damage_and_accuracy(cog, "pound_key")

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
        state = two_flunky_fight()
        state.cogs[1].status.is_dead = True  # keep it to a single target
        # Synthetic accuracy only so the cogs' counter-attack phase can run;
        # the assertion below is about trap damage, which is real TODO data.
        with synthetic_bossbot_accuracy():
            state, _r, _done = simulator.step(
                state, Action(track=Track.TRAP, level=2, target_index=0))
            self.assertTrue(state.cogs[0].status.trapped)
            with self.assertRaises(NotImplementedError):
                simulator.step(
                    state, Action(track=Track.LURE, level=2, target_index=0))

    def test_synthetic_accuracy_does_not_leak(self):
        with synthetic_bossbot_accuracy():
            self.assertIsNotNone(data.BOSSBOT_COGS["flunky"]["accuracy"])
        self.assertIsNone(data.BOSSBOT_COGS["flunky"]["accuracy"])


class TestFullFight(unittest.TestCase):
    def test_random_policy_fight_terminates(self):
        random.seed(0)
        state = two_flunky_fight()
        with synthetic_bossbot_accuracy():
            for _ in range(60):
                if state.is_terminal():
                    break
                actions = simulator.legal_actions(state)
                if not actions:
                    break
                state, _reward, done = simulator.step(state,
                                                      random.choice(actions))
                if done:
                    break
        self.assertTrue(state.is_terminal(),
                        "fight ran 60 rounds without reaching a terminal state")
        self.assertGreater(state.round_num, 0)

    def test_demo_runs(self):
        out = io.StringIO()
        with synthetic_bossbot_accuracy(), contextlib.redirect_stdout(out):
            run_random_policy(seed=0)
        self.assertIn("Battle finished", out.getvalue())


if __name__ == "__main__":
    unittest.main()
