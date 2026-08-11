"""
Tests for the visualizer's JSON bridge.

The bridge is the only translation layer between the browser UI and the
solver, so the thing worth guarding is that it *translates* and doesn't
*decide*: state must survive a round trip intact, and the numbers it hands
the page must be the same ones the solver produces directly.

stdlib unittest only -- pytest is not installed.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "visualizer"))

import bridge  # noqa: E402

from solver import data, outcomes, simulator  # noqa: E402
from solver.search import expectimax  # noqa: E402
from solver.state import Action, Track  # noqa: E402

CFG = {
    "laff": 45,
    "cogs": [{"type": "flunky", "level": 4},
             {"type": "pencil_pusher", "level": 5}],
    "gags": [["throw", 3, 4], ["sound", 4, 2], ["lure", 2, 3]],
}


class TestRoundTrip(unittest.TestCase):
    def test_state_survives_serialization(self):
        state = bridge.build_state(CFG)
        # Dirty every field the UI could otherwise silently drop.
        state.cogs[0].status.apply_lure(110, 2, 2)
        state.cogs[1].status.trapped = True
        state.cogs[1].status.trap_level = 3
        state.cogs[1].hp -= 7
        state.round_num = 4

        back = bridge.state_from_dict(bridge.state_to_dict(state))

        self.assertEqual(outcomes.state_key(back), outcomes.state_key(state))
        self.assertEqual(back.round_num, state.round_num)
        self.assertEqual(back.toon.track_exp, state.toon.track_exp)
        self.assertEqual(back.toon.gag_counts, state.toon.gag_counts)
        self.assertEqual(back.cogs[0].status.lure_rounds_remaining, 2)
        self.assertEqual(back.cogs[0].status.lure_level, 2)
        self.assertEqual(back.cogs[1].status.trap_level, 3)

    def test_action_round_trip(self):
        for action in (Action(track=Track.THROW, level=3, target_index=1),
                       Action(track=Track.SOUND, level=4, target_index=None)):
            back = bridge.action_from_dict(bridge.action_to_dict(action))
            self.assertEqual(back, action)


class TestExpansionMatchesTheSolver(unittest.TestCase):
    """The page must not be able to show a different answer than the solver."""

    def setUp(self):
        self.state = bridge.build_state(CFG)
        self.state_dict = bridge.state_to_dict(self.state)

    def test_decision_children_match_rank_actions(self):
        children = bridge.expand_decision(self.state_dict, depth=2)
        ranked = expectimax.rank_actions(self.state, depth=2)

        self.assertEqual(len(children), len(ranked))
        for child, (value, action) in zip(children, ranked):
            self.assertAlmostEqual(child["ev"], round(value, 2), places=6)
            self.assertEqual(bridge.action_from_dict(child["action"]), action)

    def test_decision_children_are_sorted_best_first(self):
        children = bridge.expand_decision(self.state_dict, depth=1)
        evs = [c["ev"] for c in children]
        self.assertEqual(evs, sorted(evs, reverse=True))
        self.assertTrue(children[0]["best"])
        self.assertFalse(any(c["best"] for c in children[1:]))

    def test_gap_is_the_lead_over_the_runner_up(self):
        children = bridge.expand_decision(self.state_dict, depth=1)
        self.assertAlmostEqual(children[0]["gap"],
                               round(children[0]["ev"] - children[1]["ev"], 2),
                               places=2)
        self.assertIsNone(children[-1]["gap"])

    def test_action_outcomes_are_a_complete_distribution(self):
        action = Action(track=Track.THROW, level=3, target_index=0)
        children = bridge.expand_action(self.state_dict,
                                        bridge.action_to_dict(action))
        total = sum(c["prob"] for c in children)
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_bucketing_preserves_total_probability(self):
        """Rare outcomes collapse into one row rather than spawning dozens
        of children -- but the probability mass has to survive."""
        action = Action(track=Track.SOUND, level=4, target_index=None)
        uncapped = bridge.expand_action(self.state_dict,
                                        bridge.action_to_dict(action), cap=999)
        capped = bridge.expand_action(self.state_dict,
                                      bridge.action_to_dict(action), cap=3)
        self.assertGreater(len(uncapped), len(capped))
        self.assertAlmostEqual(sum(c["prob"] for c in capped),
                               sum(c["prob"] for c in uncapped), places=3)
        self.assertEqual(capped[-1]["kind"], "bucket")

    def test_data_gaps_surface_as_an_error_not_a_crash(self):
        cfg = dict(CFG, cogs=[{"type": "the_big_cheese",
                               "department": "bossbot", "level": 11}])
        state_dict = bridge.state_to_dict(bridge.build_state(cfg))
        action = {"track": "throw", "level": 3, "target": 0}
        res = json.loads(bridge.api_expand_action(
            json.dumps({"state": state_dict, "action": action})))
        self.assertIn("error", res)
        self.assertIn("glower_power", res["error"])


class TestCatalogue(unittest.TestCase):
    def test_lists_every_department_and_cog(self):
        cat = json.loads(bridge.api_catalogue())
        self.assertEqual(set(cat["departments"]), set(data.COG_DEPARTMENTS))
        for dept, cogs in cat["departments"].items():
            self.assertEqual(len(cogs), len(data.COG_DEPARTMENTS[dept]))

    def test_gag_group_flags_come_from_the_simulator(self):
        """The old JS port hardcoded 'level 7 only' and was wrong for Lure
        and Toon-Up. These flags must be read from simulator, not restated."""
        cat = json.loads(bridge.api_catalogue())
        by_key = {(g["track"], g["level"]): g["group"] for g in cat["gags"]}
        for (track, level), is_group in by_key.items():
            self.assertEqual(
                is_group, simulator.is_group_action(Track(track), level),
                f"{track} {level} disagrees with simulator.is_group_action")
        self.assertTrue(by_key[("lure", 2)], "Small Magnet is a group gag")
        self.assertFalse(by_key[("lure", 1)], "$1 Bill is single-target")

    def test_gag_names_come_from_the_data_tables(self):
        self.assertEqual(bridge.gag_name(Track.LURE, 2), "Small Magnet")
        self.assertEqual(bridge.gag_name(Track.LURE, 7), "Presentation")


class TestApiSurface(unittest.TestCase):
    def test_root_is_json_and_renders_cog_labels(self):
        root = json.loads(bridge.api_root(json.dumps(CFG)))
        self.assertEqual(root["kind"], "decision")
        self.assertEqual(len(root["cogs"]), 2)
        self.assertIn("Flunky L4", root["cogs"][0])

    def test_every_api_entry_point_returns_valid_json(self):
        root = json.loads(bridge.api_root(json.dumps(CFG)))
        dec = json.loads(bridge.api_expand_decision(
            json.dumps({"state": root["state"], "depth": 1})))
        self.assertIn("children", dec)
        act = json.loads(bridge.api_expand_action(json.dumps(
            {"state": root["state"], "action": dec["children"][0]["action"]})))
        self.assertIn("children", act)


if __name__ == "__main__":
    unittest.main()
