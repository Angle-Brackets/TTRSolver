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
        """Tolerant of one rounding unit on purpose.

        `gap` is rounded from full-precision EVs while the comparison
        here subtracts two already-rounded ones, so the two can differ by
        a cent -- 5.09 against 5.08 -- without anything being wrong.
        """
        children = bridge.expand_decision(self.state_dict, depth=1)
        self.assertAlmostEqual(children[0]["gap"],
                               children[0]["ev"] - children[1]["ev"],
                               delta=0.011)
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


class TestCogForecast(unittest.TestCase):
    """The forecast is what tells the user which attack is coming."""

    def setUp(self):
        self.state_dict = bridge.state_to_dict(bridge.build_state(CFG))

    def test_lists_every_living_cog_with_its_attacks(self):
        forecast = bridge.cog_forecast(self.state_dict)
        self.assertEqual(len(forecast), 2)
        for entry in forecast:
            self.assertTrue(entry["attacks"], f"{entry['cog']} has no attacks")
            for atk in entry["attacks"]:
                self.assertGreater(atk["prob"], 0)
                self.assertLessEqual(atk["hit_prob"], atk["prob"] + 1e-9)

    def test_attack_probabilities_sum_to_one_per_cog(self):
        """Marginal per cog: one of its attacks is always chosen."""
        for entry in bridge.cog_forecast(self.state_dict):
            self.assertAlmostEqual(sum(a["prob"] for a in entry["attacks"]),
                                   1.0, places=6)

    def test_dead_cogs_are_omitted(self):
        state = bridge.build_state(CFG)
        state.cogs[0].status.is_dead = True
        forecast = bridge.cog_forecast(bridge.state_to_dict(state))
        self.assertEqual(len(forecast), 1)

    def test_a_lured_cog_is_shown_as_unlikely_to_act(self):
        state = bridge.build_state(CFG)
        state.cogs[0].status.apply_lure(110, 2, 2)
        entry = bridge.cog_forecast(bridge.state_to_dict(state))[0]
        self.assertTrue(entry["lured"])
        self.assertEqual(entry["p_acts"], 0.0)
        self.assertEqual(entry["expected_damage"], 0.0)


class TestIcons(unittest.TestCase):
    """Icon filenames are derived from the same identity the data uses, so
    they can't drift from it. The files themselves are optional -- assets/
    is gitignored and only appears once tools/fetch_icons.py has run -- so
    nothing here asserts a file exists, only that the name is right."""

    def test_names_are_derived_from_identity(self):
        self.assertEqual(bridge.gag_icon(Track.LURE, 2), "gag-lure-2.png")
        self.assertEqual(bridge.cog_icon("bossbot", "the_big_cheese"),
                         "cog-bossbot-the_big_cheese.png")
        self.assertEqual(bridge.department_icon("lawbot"), "dept-lawbot.png")

    def test_every_gag_and_cog_in_the_catalogue_has_one(self):
        cat = json.loads(bridge.api_catalogue())
        for g in cat["gags"]:
            self.assertTrue(g["icon"].endswith(".png"))
        for dept, cogs in cat["departments"].items():
            self.assertIn(dept, cat["emblems"])
            for c in cogs:
                self.assertEqual(c["icon"], f"cog-{dept}-{c['type']}.png")

    def test_action_nodes_and_forecasts_carry_icons(self):
        state_dict = bridge.state_to_dict(bridge.build_state(CFG))
        for child in bridge.expand_decision(state_dict, depth=1):
            action = child["action"]
            self.assertEqual(child["icon"],
                             f"gag-{action['track']}-{action['level']}.png")
        for entry in bridge.cog_forecast(state_dict):
            self.assertTrue(entry["icon"].startswith("cog-"))
            self.assertTrue(entry["dept_icon"].startswith("dept-"))

    def test_state_nodes_carry_one_cog_icon_per_cog(self):
        root = json.loads(bridge.api_root(json.dumps(CFG)))
        self.assertEqual(len(root["cog_icons"]), len(root["cogs"]))


class TestBestLine(unittest.TestCase):
    def test_opens_with_the_action_the_solver_recommends(self):
        state_dict = bridge.state_to_dict(bridge.build_state(CFG))
        line = bridge.best_line(state_dict, depth=2)
        self.assertTrue(line)
        top = bridge.expand_decision(state_dict, depth=2)[0]
        self.assertEqual(line[0]["action"], top["action"])

    def test_plays_all_the_way_to_the_end(self):
        """The plan must finish the fight. It used to stop a move short --
        the step cap was a round number rather than anything to do with the
        position, so a five-move plan under a six-step cap looked complete
        while a longer one silently truncated."""
        cfg = dict(CFG, cogs=[{"type": "flunky", "level": 4},
                              {"type": "pencil_pusher", "level": 5}],
                   gags=[["throw", 3, 4], ["throw", 4, 2], ["sound", 4, 2]])
        state_dict = bridge.state_to_dict(bridge.build_state(cfg))
        line = bridge.best_line(state_dict, depth=1)
        self.assertTrue(line)
        self.assertIsNotNone(
            line[-1]["terminal"],
            "plan stopped before the battle ended: "
            + " -> ".join(s["label"] for s in line))

    def test_step_cap_defaults_to_the_pouch(self):
        """No line can outlast the gags, so that is the honest bound."""
        cfg = dict(CFG, gags=[["throw", 3, 2]])
        state_dict = bridge.state_to_dict(bridge.build_state(cfg))
        line = bridge.best_line(state_dict, depth=1)
        self.assertLessEqual(len(line), 3)

    def test_stops_at_a_terminal_state(self):
        cfg = dict(CFG, cogs=[{"type": "flunky", "level": 1}])
        state_dict = bridge.state_to_dict(bridge.build_state(cfg))
        line = bridge.best_line(state_dict, depth=2, steps=10)
        self.assertTrue(line)
        self.assertIsNotNone(line[-1]["terminal"],
                             "a one-cog fight should reach an end state")


class TestLoadoutValidation(unittest.TestCase):
    """The picker enforces the limits, but so must the bridge -- a config
    can arrive from anywhere, and the solver planning for a toon carrying
    all seven tracks would give advice nobody can follow."""

    def test_seven_tracks_is_refused(self):
        cfg = dict(CFG, gags=[[t.value, 1, 2] for t in Track])
        res = json.loads(bridge.api_root(json.dumps(cfg)))
        self.assertIn("error", res)
        self.assertIn("track", res["error"])

    def test_overfull_pouch_is_refused(self):
        cfg = dict(CFG, gags=[["throw", 1, 200]])
        res = json.loads(bridge.api_root(json.dumps(cfg)))
        self.assertIn("error", res)

    def test_a_legal_loadout_builds(self):
        res = json.loads(bridge.api_root(json.dumps(CFG)))
        self.assertNotIn("error", res)

    def test_catalogue_publishes_the_same_limits(self):
        """The grid greys cells out using these, so they have to be the
        numbers build_state will actually enforce."""
        limits = json.loads(bridge.api_catalogue())["limits"]
        self.assertEqual(limits["max_tracks"], data.MAX_GAG_TRACKS)
        self.assertEqual(limits["max_pouch"], data.MAX_POUCH)


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
