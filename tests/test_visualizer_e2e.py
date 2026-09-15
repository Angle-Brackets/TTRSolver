import json
import pathlib
import unittest
from visualizer import bridge, serve

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

class TestVisualizerE2E(unittest.TestCase):
    def test_dist_build_artifacts_exist(self):
        dist = REPO_ROOT / "visualizer" / "dist"
        self.assertTrue(dist.exists(), "visualizer/dist must exist")
        self.assertTrue((dist / "index.html").exists(), "visualizer/dist/index.html must exist")
        assets = dist / "assets"
        self.assertTrue(assets.exists(), "visualizer/dist/assets must exist")
        # Check gag and cog art are copied
        self.assertTrue((assets / "gag-throw-5.png").exists(), "gag-throw-5.png must exist in dist/assets")
        self.assertTrue((assets / "pink-slip.png").exists(), "pink-slip.png must exist in dist/assets")

    def test_handler_path_translation(self):
        handler = serve.Handler
        class DummyHandler:
            pass
        d = DummyHandler()
        # translate_path uses REPO_ROOT
        res_root = serve.Handler.translate_path(d, "/visualizer/index.html")
        self.assertTrue(res_root.endswith("index.html"))
        res_asset = serve.Handler.translate_path(d, "/visualizer/assets/gag-throw-5.png")
        self.assertTrue(res_asset.endswith("gag-throw-5.png"))

    def test_end_to_end_flow(self):
        # 1. Catalogue
        cat = json.loads(bridge.api_catalogue())
        self.assertIn("scenarios", cat)
        self.assertIn("sos_cards", cat)
        self.assertIn("unites", cat)

        # 2. Scenario generator for all kinds
        for kind in ("building", "scrappy", "strange", "hard", "combo"):
            scen = json.loads(bridge.api_generate_scenario(json.dumps({"kind": kind})))
            st = scen.get("state", scen)
            self.assertTrue("toons" in st or "toon" in st)
            self.assertTrue("cogs" in st or "cogs" in scen)

        # 3. Random toon generator
        raw_toon = json.loads(bridge.api_random_toon(json.dumps({})))
        toon = raw_toon.get("toon", raw_toon)
        self.assertIn("laff", toon)
        self.assertIn("gags", toon)

        # 4. Root with multi-toon party and statuses
        cfg = {
            "toons": [
                {
                    "laff": 110,
                    "max_laff": 110,
                    "organic": "throw",
                    "fires": 2,
                    "unites_held": ["laff_80"],
                    "sos_cards": ["flippy"],
                    "gags": {"throw": {"5": 5, "6": 2}, "squirt": {"5": 5}, "sound": {"5": 5}},
                },
                {
                    "laff": 85,
                    "max_laff": 90,
                    "organic": None,
                    "fires": 0,
                    "gags": {"sound": {"5": 5, "4": 5}},
                },
            ],
            "cogs": [
                {
                    "dept": "sellbot",
                    "name": "Mr. Hollywood",
                    "level": 12,
                    "hp": 182,
                    "max_hp": 182,
                    "lured": True,
                    "lure_rounds": 2,
                    "trapped": False,
                    "suited": False,
                },
                {
                    "dept": "lawbot",
                    "name": "Legal Eagle",
                    "level": 11,
                    "hp": 156,
                    "max_hp": 156,
                    "lured": False,
                    "trapped": True,
                    "trap_level": 6,
                    "suited": True,
                },
            ],
        }
        root = json.loads(bridge.api_root(json.dumps(cfg)))
        self.assertEqual(root["kind"], "decision")
        self.assertEqual(len(root["cogs"]), 2)

        # 5. Expand decision (depth 1)
        dec = json.loads(bridge.api_expand_decision(json.dumps({"state": root["state"], "depth": 1})))
        self.assertTrue(len(dec["children"]) > 0)
        first_act = dec["children"][0]

        # 6. Expand action
        act = json.loads(bridge.api_expand_action(json.dumps({"state": root["state"], "action": first_act["action"]})))
        self.assertTrue(len(act["children"]) > 0)

        # 7. Cog threat forecast
        fc = json.loads(bridge.api_cog_forecast(json.dumps({"state": root["state"]})))
        self.assertEqual(len(fc["cogs"]), 2)

        # 8. Best line
        line = json.loads(bridge.api_best_line(json.dumps({"state": root["state"], "depth": 1})))
        self.assertIn("line", line)

        # 9. Climb (PPO)
        climb = json.loads(bridge.api_climb(json.dumps({"state": root["state"], "budget": 4, "width": 4})))
        self.assertIn("available", climb)

if __name__ == "__main__":
    unittest.main()
