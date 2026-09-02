"""`solver/live/explain.py` -- the numbers behind a recommendation.

The panel sent WHAT to throw and nothing about why, while the solver
computed the reasons on every score and discarded them. These pin both
that the numbers arrive and that a failure to compute them never costs
the advice they were explaining.
"""
import random
import unittest

from solver import data, simulator
from solver.live import explain
from solver.rl import env as env_mod, harness
from solver.state import Action, Track


def _board(seed=9):
    def sampler(rng):
        state = env_mod.facility_position(rng)
        state.toons = [harness.solo_loadout(rng, fires=2)]
        return state

    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                          coordinated=True)
    e.reset()
    return e.state


class DescribeTest(unittest.TestCase):

    def test_the_board_terms_do_not_need_an_action(self):
        detail = explain.describe(_board(), None)
        self.assertIn("incoming", detail)
        self.assertIn("survive", detail)

    def test_an_attack_reports_damage_and_kills(self):
        state = _board()
        attack = next(a for a in simulator.legal_actions(state)
                      if a.track is Track.THROW)
        detail = explain.describe(state, attack)
        self.assertGreater(detail["damage"], 0)
        self.assertIn("accuracy", detail)

    def test_a_lure_reports_prevention_rather_than_damage(self):
        state = _board()
        lure = next(a for a in simulator.legal_actions(state)
                    if a.track is Track.LURE)
        detail = explain.describe(state, lure)
        self.assertEqual(detail.get("damage", 0), 0)
        self.assertGreater(detail.get("prevented", 0), 0)

    def test_survive_is_capped_like_the_scorer(self):
        from solver.search import weights
        detail = explain.describe(_board(), None)
        self.assertLessEqual(detail["survive"], weights.SURVIVAL_CAP)

    def test_a_trap_always_hits(self):
        """Read through the simulator, so a FORCED accuracy comes back
        stated rather than rolled up and capped at 95."""
        state = _board()
        trap = next((a for a in simulator.legal_actions(state)
                     if a.track is Track.TRAP), None)
        if trap is None:
            self.skipTest("no trap in this pouch")
        self.assertEqual(explain.accuracy_of(state, trap), 100)

    def test_a_pass_has_no_accuracy(self):
        self.assertIsNone(explain.accuracy_of(_board(), Action(track=None)))


class NeverCostsTheAdviceTest(unittest.TestCase):
    """Every entry point returns something usable on nonsense input."""

    def test_no_state_is_an_empty_dict(self):
        self.assertEqual(explain.describe(None, None), {})

    def test_a_broken_state_does_not_raise(self):
        class Broken:
            cogs = None
            toons = None
        self.assertIsInstance(explain.describe(Broken(), None), dict)

    def test_accuracy_of_nonsense_is_none(self):
        self.assertIsNone(explain.accuracy_of(_board(), object()))

    def test_reason_of_nothing_is_empty(self):
        self.assertEqual(explain.reason({}), "")
        self.assertEqual(explain.reason({"damage": 0, "kills": 0}), "")


class ReasonTest(unittest.TestCase):

    def test_a_kill_outranks_everything(self):
        self.assertEqual(
            explain.reason({"kills": 1, "prevented": 90, "damage": 40}),
            "kills it")

    def test_several_kills_are_counted(self):
        self.assertEqual(explain.reason({"kills": 3}), "kills 3")

    def test_prevention_beats_raw_damage(self):
        self.assertEqual(explain.reason({"prevented": 88, "damage": 10}),
                         "prevents ~88 incoming")

    def test_a_trap_says_so(self):
        self.assertEqual(explain.reason({"arms": 60.0}), "arms the trap")

    def test_damage_is_the_fallback(self):
        self.assertEqual(explain.reason({"damage": 42}), "42 damage")


class SerialisedTest(unittest.TestCase):

    def test_the_page_receives_them(self):
        import json
        from solver.live.overlay import CogRow, Model
        from solver.live.panel import model_json
        model = Model()
        model.incoming, model.survive = 41.9, 2.4
        model.accuracy, model.reason = 95, "kills it"
        model.rows = [CogRow(name="x", level=5, health=0.5, hp=21,
                             max_hp=42)]
        payload = json.loads(model_json(model))
        self.assertEqual(payload["incoming"], 41.9)
        self.assertEqual(payload["survive"], 2.4)
        self.assertEqual(payload["accuracy"], 95)
        self.assertEqual(payload["reason"], "kills it")
        self.assertEqual(payload["rows"][0]["hp"], 21)
        self.assertEqual(payload["rows"][0]["max_hp"], 42)

    def test_an_empty_model_serialises_cleanly(self):
        import json
        from solver.live.overlay import Model
        from solver.live.panel import model_json
        payload = json.loads(model_json(Model()))
        for key in ("incoming", "survive", "accuracy"):
            self.assertIsNone(payload[key])
        self.assertEqual(payload["reason"], "")


if __name__ == "__main__":
    unittest.main()
