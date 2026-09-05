"""The visualizer's adapter must carry everything the solver has.

`serve.py` mounts the real `solver` package into the browser, so the
RULES cannot drift -- that is the whole design. What can drift is this
adapter, and it did: every consumable was dropped in serialisation, so a
position built with slips and cards came back carrying none. A dropped
field is invisible rather than broken, which is the same failure the
`organic` note in `toon_to_dict` records.
"""
import unittest

from solver.state import BattleState, CogState, ToonState, Track
from visualizer import bridge


def _toon():
    toon = ToonState(90, 137, {t: 7 for t in Track},
                     {(Track.THROW, 5): 3}, frozenset({Track.THROW}))
    toon.fires = 4
    toon.unites_held = 6
    toon.sos_cards = {"Flippy": 2, "Lil Oldman": 1}
    return toon


class ToonRoundTripTest(unittest.TestCase):

    def _round_trip(self, toon):
        return bridge.toon_from_dict(bridge.toon_to_dict(toon))

    def test_the_consumables_survive(self):
        back = self._round_trip(_toon())
        self.assertEqual(4, back.fires)
        self.assertEqual(6, back.unites_held)
        self.assertEqual({"Flippy": 2, "Lil Oldman": 1}, back.sos_cards)

    def test_a_toon_carrying_none_stays_that_way(self):
        """Absent keys must read as zero, not raise -- old saved states
        have no consumable fields at all."""
        payload = bridge.toon_to_dict(_toon())
        for key in ("fires", "unites_held", "sos_cards"):
            payload.pop(key)
        back = bridge.toon_from_dict(payload)
        self.assertEqual(0, back.fires)
        self.assertEqual(0, back.unites_held)
        self.assertEqual({}, back.sos_cards)

    def test_the_older_fields_still_survive(self):
        toon = _toon()
        back = self._round_trip(toon)
        self.assertEqual(toon.laff, back.laff)
        self.assertEqual(toon.max_laff, back.max_laff)
        self.assertEqual(toon.track_exp, back.track_exp)
        self.assertEqual(toon.gag_counts, back.gag_counts)
        self.assertEqual(toon.organic_tracks, back.organic_tracks)

    def test_it_is_json_safe(self):
        """The page ships this over postMessage; tuple keys would not
        survive, which is why gags are a list of triples."""
        import json

        json.dumps(bridge.toon_to_dict(_toon()))


class StateRoundTripTest(unittest.TestCase):

    def _state(self):
        from solver import data

        hp = data.cog_max_hp(8)
        cog = CogState(cog_type="loan_shark", department="cashbot",
                       level=8, hp=hp, max_hp=hp)
        cog.status.lured = True
        cog.status.trapped = True
        cog.status.trap_level = 4
        return BattleState(toons=[_toon(), _toon()], cogs=[cog])

    def test_a_party_keeps_every_toon_and_its_pouch(self):
        back = bridge.state_from_dict(bridge.state_to_dict(self._state()))
        self.assertEqual(2, len(back.toons))
        for toon in back.toons:
            self.assertEqual(4, toon.fires)
            self.assertEqual({"Flippy": 2, "Lil Oldman": 1}, toon.sos_cards)

    def test_cog_status_survives(self):
        back = bridge.state_from_dict(bridge.state_to_dict(self._state()))
        status = back.cogs[0].status
        self.assertTrue(status.lured)
        self.assertTrue(status.trapped)
        self.assertEqual(4, status.trap_level)


if __name__ == "__main__":
    unittest.main()


class PolicyEndpointTest(unittest.TestCase):
    """`api_climb` is why the solver moved out of the browser.

    Every other number the tool returns comes from `expectimax`. The
    overlay panel plays with `hybrid.climb`, and under Pyodide that was
    doubly blocked -- numpy was never `loadPackage`d and the source
    manifest globbed `*.py`, so the 7.7 MB policy export never reached
    the browser filesystem. Server side both are simply present.
    """

    def _state(self):
        from solver import data

        hp = data.cog_max_hp(8)
        cog = CogState(cog_type="loan_shark", department="cashbot",
                       level=8, hp=hp, max_hp=hp)
        toon = ToonState(90, 137, {t: 7 for t in Track},
                         {(Track.THROW, 5): 3, (Track.THROW, 6): 2,
                          (Track.SQUIRT, 5): 3},
                         frozenset())
        return bridge.state_to_dict(BattleState(toons=[toon], cogs=[cog]))

    def test_it_answers_with_a_plan(self):
        import json

        out = json.loads(bridge.api_climb(json.dumps({"state": self._state()})))
        if not out.get("available"):
            self.skipTest("policy unavailable: %s" % out.get("reason"))
        self.assertEqual(1, len(out["plan"]))
        self.assertTrue(out["labels"][0])

    def test_it_is_deterministic(self):
        """The page re-asks the same position as the user clicks about;
        an answer that changed each time would read as a solver bug."""
        import json

        payload = json.dumps({"state": self._state()})
        a = json.loads(bridge.api_climb(payload))
        b = json.loads(bridge.api_climb(payload))
        if not a.get("available"):
            self.skipTest("policy unavailable")
        self.assertEqual(a["labels"], b["labels"])

    def test_a_missing_policy_is_reported_not_raised(self):
        import json

        from solver.search import hybrid

        saved = hybrid.available
        hybrid.available = lambda: False
        try:
            out = json.loads(
                bridge.api_climb(json.dumps({"state": self._state()})))
        finally:
            hybrid.available = saved
        self.assertFalse(out["available"])
        self.assertIn("reason", out)


class CallEndpointTest(unittest.TestCase):
    """`POST /api/call` is the whole page-to-solver contract."""

    @classmethod
    def setUpClass(cls):
        import socketserver
        import threading

        from visualizer.serve import Handler

        cls.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _post(self, body):
        import json
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/call" % self.port,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    def test_the_catalogue_comes_back(self):
        out = self._post({"fn": "api_catalogue"})
        for key in ("departments", "gags", "objectives", "limits"):
            self.assertIn(key, out)

    def test_a_scenario_builds(self):
        out = self._post({"fn": "api_root", "payload": {
            "laff": 90, "gags": [["throw", 5, 3]],
            "cogs": [{"type": "loan_shark", "department": "cashbot",
                      "level": 8}]}})
        self.assertEqual("decision", out["kind"])
        self.assertEqual(["Loan Shark L8 90/90"], out["cogs"])

    def test_only_api_functions_are_callable(self):
        """`bridge` is full of helpers that take Python objects, and the
        module namespace is not a safe thing to expose wholesale."""
        out = self._post({"fn": "os"})
        self.assertIn("error", out)
        out = self._post({"fn": "state_from_dict", "payload": {}})
        self.assertIn("error", out)

    def test_a_bad_loadout_is_an_error_not_a_crash(self):
        out = self._post({"fn": "api_root", "payload": {
            "laff": 90, "gags": [["throw", 5, 999]], "cogs": []}})
        self.assertIn("error", out)
        self.assertIn("pouch", out["error"])
