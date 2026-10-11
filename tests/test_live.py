"""Parsing the Toontown Rewritten Local API.

These run against a recorded payload rather than a live game, so they work
with no client running. The fixture is synthetic but its shape is copied
from a real `/all.json`, including the two things the published docs do
not mention: `toon.id` and `location.instanceId`.
"""
import unittest

from solver.live.ttr_local import (
    LocalAPIError, Snapshot, parse_snapshot, TRACK_NAMES,
)
from solver.state import Track


def payload(**overrides):
    """A realistic `/info.json` body, shaped like the observed one."""
    body = {
        "toon": {"id": "TTID-XXXX-XXXX", "name": "Test Toon",
                 "species": "dog", "headColor": "#a35a44", "style": "..."},
        "laff": {"current": 78, "max": 95},
        "location": {"zone": "Loopy Lane", "neighborhood": "Toontown Central",
                     "district": "Splat Summit", "instanceId": None},
        "gags": {
            "Toon-Up": None,
            "Trap": {"gag": {"level": 7, "name": "Railroad"},
                     "organic": None,
                     "experience": {"current": 200, "next": 500}},
            "Lure": {"gag": {"level": 5, "name": "Hypno-Goggles"},
                     "organic": {"level": 5, "name": "Hypno-Goggles"},
                     "experience": {"current": 178, "next": 500}},
            "Sound": None, "Throw": None, "Squirt": None, "Drop": None,
        },
        "invasion": None,
    }
    body.update(overrides)
    return body


class ParseSnapshotTest(unittest.TestCase):

    def test_reads_toon_laff_and_location(self):
        snap = parse_snapshot(payload())
        self.assertEqual(snap.name, "Test Toon")
        self.assertEqual(snap.toon_id, "TTID-XXXX-XXXX")
        self.assertEqual((snap.laff, snap.max_laff), (78, 95))
        self.assertEqual(snap.zone, "Loopy Lane")
        self.assertEqual(snap.district, "Splat Summit")

    def test_locked_tracks_are_absent_not_zero(self):
        """A locked track must not read as "unlocked to level 0"."""
        snap = parse_snapshot(payload())
        self.assertNotIn(Track.TOON_UP, snap.tracks)
        self.assertIn(Track.TRAP, snap.tracks)

    def test_organic_is_detected_per_track(self):
        snap = parse_snapshot(payload())
        self.assertEqual(snap.organic_tracks(), [Track.LURE])
        self.assertFalse(snap.tracks[Track.TRAP][1])

    def test_organic_stops_at_the_top_organic_gag(self):
        """[CONFIRMED] wiki: trees are planted in order of level, so the
        API's organic gag is the highest one; nothing above it is."""
        body = payload()
        body["gags"]["Throw"] = {"gag": {"level": 7, "name": "Wedding Cake"},
                                 "organic": {"level": 4, "name": "Whole Fruit Pie"},
                                 "experience": {}}
        snap = parse_snapshot(body)
        self.assertEqual({Track.LURE: 5, Track.THROW: 4}, snap.organic_levels())
        from solver.live import session
        toon = session.ToonState(100, 100, {Track.THROW: 7}, {},
                                 frozenset(snap.organic_tracks()),
                                 organic_levels=snap.organic_levels())
        self.assertTrue(toon.is_organic(Track.THROW, 4))
        self.assertFalse(toon.is_organic(Track.THROW, 5))
        self.assertFalse(toon.is_organic(Track.THROW, 7))
        self.assertTrue(toon.is_organic(Track.THROW))

    def test_available_gags_expands_every_level_below_the_top(self):
        snap = parse_snapshot(payload())
        self.assertEqual(snap.available_gags(),
                         [(Track.TRAP, n) for n in range(1, 8)]
                         + [(Track.LURE, n) for n in range(1, 6)])

    def test_unknown_track_raises_rather_than_being_dropped(self):
        """A renamed or new track is a game change worth failing loudly on."""
        body = payload()
        body["gags"]["Zap"] = {"gag": {"level": 1, "name": "?"},
                               "organic": None, "experience": {}}
        with self.assertRaises(LocalAPIError) as caught:
            parse_snapshot(body)
        self.assertIn("Zap", str(caught.exception))

    def test_every_api_track_name_maps_to_a_track(self):
        self.assertEqual(set(TRACK_NAMES.values()), set(Track))

    def test_instance_id_is_carried_through(self):
        """Undocumented, so easy to drop by accident; the solver wants it."""
        body = payload()
        body["location"]["instanceId"] = "abc-123"
        self.assertEqual(parse_snapshot(body).instance_id, "abc-123")

    def test_invasion_strips_the_clients_soft_break(self):
        """Three cog names carry a U+0003 the client uses to line-break."""
        body = payload(invasion={"cog": "Micro" + chr(3) + "manager",
                                 "quantity": 1000, "megaInvasion": True})
        snap = parse_snapshot(body)
        self.assertEqual(snap.invasion, ("Micromanager", 1000, True))

    def test_no_invasion_is_none(self):
        self.assertIsNone(parse_snapshot(payload()).invasion)

    def test_describe_mentions_locked_and_unlocked_tracks(self):
        text = parse_snapshot(payload()).describe()
        self.assertIn("locked", text)
        self.assertIn("to level 7", text)
        self.assertIn("(organic to 5)", text)


class TransitionTest(unittest.TestCase):
    """Behaviour observed against a live client, not invented."""

    def test_empty_zone_reads_as_loading(self):
        """`location.zone` empties for about a second between zones; that
        is a transition, not an absence of location."""
        body = payload()
        body["location"]["zone"] = ""
        self.assertTrue(parse_snapshot(body).loading)
        self.assertFalse(parse_snapshot(payload()).loading)


class MeritsTest(unittest.TestCase):
    """The toon's own disguise progress -- not the cogs it is fighting."""

    def suited(self, sellbot_merits):
        return payload(cogsuits={
            "c": {"department": "Bossbot", "hasDisguise": False},
            "l": {"department": "Lawbot", "hasDisguise": False},
            "s": {"department": "Sellbot", "hasDisguise": True,
                  "suit": {"id": "cc", "name": "Cold Caller"},
                  "version": 1, "level": 5,
                  "promotion": {"current": sellbot_merits, "target": 150}},
        })

    def test_only_departments_with_a_suit_are_tracked(self):
        snap = parse_snapshot(self.suited(3))
        self.assertEqual(snap.merits, {"s": (3, 150)})

    def test_winning_a_fight_shows_up_as_a_merit_gain(self):
        before = parse_snapshot(self.suited(0))
        after = parse_snapshot(self.suited(3))
        self.assertEqual(after.merits_gained(before), {"s": 3})

    def test_no_gain_between_identical_snapshots(self):
        snap = parse_snapshot(self.suited(3))
        self.assertEqual(snap.merits_gained(snap), {})

    def test_a_department_absent_before_is_not_a_gain(self):
        """Gaining a suit mid-session must not read as winning a fight."""
        before = parse_snapshot(payload())
        after = parse_snapshot(self.suited(3))
        self.assertEqual(after.merits_gained(before), {})


class SnapshotContractTest(unittest.TestCase):
    """What a snapshot must not claim to know."""

    def test_snapshot_carries_no_gag_counts(self):
        """The API does not expose how many of each gag you hold, and
        inventing them is exactly what the project rules out."""
        self.assertFalse(
            [f for f in Snapshot.__dataclass_fields__ if "count" in f])


if __name__ == "__main__":
    unittest.main()


class PinkSlipsTest(unittest.TestCase):
    """[CONFIRMED] live 2026-10-10: `/pinkslips.json` is a bare integer."""

    def test_a_bare_count(self):
        from solver.live.ttr_local import parse_pink_slips
        self.assertEqual(0, parse_pink_slips(0))
        self.assertEqual(7, parse_pink_slips(7))

    def test_anything_else_is_unknown_not_zero(self):
        from solver.live.ttr_local import parse_pink_slips
        for body in ({}, "3", -1, None, True):
            self.assertIsNone(parse_pink_slips(body))
