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
