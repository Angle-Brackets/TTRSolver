"""The Discord relay passes the game's stream through and keeps its status.

Run on test-only pipe names, never Discord's, with a fake Discord and a
fake game on either side. Each platform's transport is exercised where
that platform can run it.
"""
import json
import os
import socket
import tempfile
import threading
import time
import unittest

from solver.live import discord_relay as R

ACTIVITY = {"cmd": "SET_ACTIVITY", "nonce": "n1",
            "args": {"pid": 1, "activity": {
                "details": "In a Four Story Sellbot Building",
                "state": "Floor 2 of 4"}}}


def _base():
    return f"ttrsolver-test-ipc-{os.getpid()}-{time.time_ns() % 10**9}-"


def _recv_frames(t, conn, count, timeout=5.0):
    reader, got, deadline = R.FrameReader(), [], time.time() + timeout
    while len(got) < count and time.time() < deadline:
        data = t.read(conn)
        if not data:
            break
        got += reader.feed(data)
    return got


class FrameReaderTest(unittest.TestCase):

    def test_frames_split_across_reads(self):
        data = R.frame(R.OP_HANDSHAKE, {"v": 1}) + R.frame(R.OP_FRAME, ACTIVITY)
        reader = R.FrameReader()
        self.assertEqual([], reader.feed(data[:5]))
        out = reader.feed(data[5:])
        self.assertEqual([R.OP_HANDSHAKE, R.OP_FRAME], [op for op, _ in out])
        self.assertEqual("Floor 2 of 4", out[1][1]["args"]["activity"]["state"])


class _RelayCases:
    """The same cases over whichever transport `carrier()` gives."""

    def carrier(self):
        raise NotImplementedError

    def setUp(self):
        self.t = self.carrier()
        self.base = _base()
        self.tmp = tempfile.TemporaryDirectory()
        self.presence = os.path.join(self.tmp.name, "presence.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _relay(self):
        relay = R.Relay(base=self.base, own=0, presence_file=self.presence,
                        carrier=self.t).start()
        self.addCleanup(relay.stop)
        return relay

    def test_it_passes_through_to_discord_and_keeps_the_status(self):
        discord = self.t.serve(self.base + "1")        # Discord, on -1
        self.addCleanup(self.t.close_listener, discord)
        relay = self._relay()
        seen = {}

        def fake_discord():
            conn = self.t.accept(discord)
            hello = _recv_frames(self.t, conn, 1)
            self.t.write(conn, R.frame(R.OP_FRAME, {"cmd": "DISPATCH", "evt": "READY"}))
            seen["frames"] = hello + _recv_frames(self.t, conn, 1)
            self.t.close(conn)
        server = threading.Thread(target=fake_discord, daemon=True)
        server.start()

        game = self.t.connect(self.base + "0")
        self.assertIsNotNone(game)
        self.t.write(game, R.frame(R.OP_HANDSHAKE, {"v": 1, "client_id": "ttr"}))
        ready = _recv_frames(self.t, game, 1)
        self.t.write(game, R.frame(R.OP_FRAME, ACTIVITY))
        server.join(5)
        self.t.close(game)

        self.assertEqual("READY", ready[0][1]["evt"], "Discord's reply reached the game")
        self.assertEqual([R.OP_HANDSHAKE, R.OP_FRAME], [op for op, _ in seen["frames"]])
        self.assertEqual(ACTIVITY, seen["frames"][1][1], "passed through unchanged")
        self._assert_kept(relay)

    def test_without_discord_it_answers_for_it(self):
        relay = self._relay()
        game = self.t.connect(self.base + "0")
        self.t.write(game, R.frame(R.OP_HANDSHAKE, {"v": 1, "client_id": "ttr"}))
        ready = _recv_frames(self.t, game, 1)
        self.t.write(game, R.frame(R.OP_FRAME, ACTIVITY))
        ack = _recv_frames(self.t, game, 1)
        self.t.close(game)
        self.assertEqual("READY", ready[0][1]["evt"])
        self.assertEqual("n1", ack[0][1]["nonce"])
        self._assert_kept(relay)

    def test_a_discord_that_comes_back_takes_the_game_over(self):
        """OBSERVED live: the game reconnects to the relay within seconds of
        Discord quitting. When Discord returns (on `-1`), the game must be
        handed to it, or the player's status never shows again."""
        relay = self._relay()
        relay.RETRY_UPSTREAM = 0.0
        game = self.t.connect(self.base + "0")
        self.t.write(game, R.frame(R.OP_HANDSHAKE, {"v": 1, "client_id": "ttr"}))
        _recv_frames(self.t, game, 1)                      # the relay's READY
        self.t.write(game, R.frame(R.OP_FRAME, ACTIVITY))
        _recv_frames(self.t, game, 1)                      # the relay's ack

        discord = self.t.serve(self.base + "1")            # Discord is back
        self.addCleanup(self.t.close_listener, discord)
        seen = {}

        def fake_discord():
            conn = self.t.accept(discord)
            seen["hello"] = _recv_frames(self.t, conn, 1)
            self.t.write(conn, R.frame(R.OP_FRAME, {"cmd": "DISPATCH", "evt": "READY"}))
            seen["next"] = _recv_frames(self.t, conn, 1)
            self.t.write(conn, R.frame(R.OP_FRAME, {"cmd": "SET_ACTIVITY", "nonce": "n2",
                                                     "evt": None, "data": {}}))
            time.sleep(0.2)
            self.t.close(conn)
        server = threading.Thread(target=fake_discord, daemon=True)
        server.start()

        later = dict(ACTIVITY, nonce="n2")
        later["args"] = {"pid": 1, "activity": {"details": "In a Four Story Sellbot Building",
                                                "state": "Floor 3 of 4"}}
        self.t.write(game, R.frame(R.OP_FRAME, later))
        reply = _recv_frames(self.t, game, 1)
        server.join(5)
        self.t.close(game)

        self.assertEqual("ttr", seen["hello"][0][1]["client_id"], "the hello was replayed")
        self.assertEqual("Floor 3 of 4", seen["next"][0][1]["args"]["activity"]["state"])
        self.assertEqual("n2", reply[0][1]["nonce"], "Discord's own reply reached the game")
        self.assertEqual("Floor 3 of 4", relay.latest()["state"])

    def test_a_taken_pipe_is_refused(self):
        self._relay()
        with self.assertRaises(R.PipeTaken):
            R.Relay(base=self.base, own=0, presence_file=None,
                    carrier=self.carrier()).start()

    def _assert_kept(self, relay):
        deadline = time.time() + 5
        while relay.latest() is None and time.time() < deadline:
            time.sleep(0.02)
        entry = relay.latest()
        self.assertEqual(("In a Four Story Sellbot Building", "Floor 2 of 4"),
                         (entry["details"], entry["state"]))
        self.assertEqual("ttr", entry["client_id"])
        with open(self.presence, encoding="utf-8") as fh:
            self.assertEqual("Floor 2 of 4", json.load(fh)["state"])
        self.assertEqual("Floor 2 of 4", R.read_presence(self.presence)["state"])


@unittest.skipUnless(os.name == "nt", "Windows named pipes")
class WindowsPipesTest(_RelayCases, unittest.TestCase):
    def carrier(self):
        return R.WindowsPipes()


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix sockets")
class UnixSocketsTest(_RelayCases, unittest.TestCase):
    def carrier(self):
        self._dir = getattr(self, "_dir", None) or tempfile.mkdtemp()
        return R.UnixSockets(self._dir)


class BuildingTest(unittest.TestCase):
    """OBSERVED in Discord: "In a Three Story Sellbot Building" /
    "Floor 3 of 3". Only that shape is read."""

    def test_the_observed_shape(self):
        self.assertEqual({"floor": 3, "floors": 3, "department": "sellbot"},
                         R.building({"details": "In a Three Story Sellbot Building",
                                     "state": "Floor 3 of 3"}))
        self.assertEqual({"floor": 2, "floors": 4, "department": "sellbot"},
                         R.building({"details": "In a Four Story Sellbot Building",
                                     "state": "Floor 2 of 4"}))

    def test_a_story_count_that_disagrees_is_not_trusted(self):
        self.assertIsNone(R.building({"details": "In a Four Story Sellbot Building",
                                      "state": "Floor 2 of 3"}))

    def test_anything_else_is_none(self):
        for entry in (None, {"details": "On Sleet Street", "state": "The Brrrgh"},
                      {"cleared": True, "state": "Floor 1 of 2"},
                      {"state": "Floor 7 of 9"}):
            self.assertIsNone(R.building(entry))


class PanelFloorTest(unittest.TestCase):
    """The TTR panel shows the floor only while the API says we are in a
    Cog building -- a stale record from the last one must not leak out."""

    def _worker(self, entry):
        from types import SimpleNamespace
        from solver.live.overlay import Worker
        w = Worker.__new__(Worker)
        w._relay = SimpleNamespace(latest=lambda: entry)
        return w

    def test_in_a_building(self):
        w = self._worker({"details": "In a Four Story Sellbot Building",
                          "state": "Floor 2 of 4"})
        self.assertEqual(2, w._building("Cog Building")["floor"])

    def test_the_panel_keeps_trying_for_the_pipe(self):
        """A running Discord holds it until the player quits Discord; the
        panel must take it in that gap, not give up at startup."""
        from solver.live.overlay import Worker
        w = Worker.__new__(Worker)
        w._relay, w._relay_tried = None, 0.0
        calls = []
        real = R.Relay

        class Taken:
            def __init__(self, *a, **k):
                calls.append(1)

            def start(self):
                raise R.PipeTaken("discord-ipc-0")
        R.Relay = Taken
        try:
            w._start_relay()
            w._start_relay()                 # too soon: not retried
            w._relay_tried -= w.RELAY_RETRY + 1
            w._start_relay()                 # later: retried
        finally:
            R.Relay = real
        self.assertEqual(2, len(calls))
        self.assertIsNone(w._relay)

    def test_outside_one(self):
        w = self._worker({"details": "In a Four Story Sellbot Building",
                          "state": "Floor 4 of 4"})
        self.assertIsNone(w._building("Sleet Street"))


class DiscoveryTest(unittest.TestCase):

    def test_unix_dir_follows_discord_rpc(self):
        saved = {k: os.environ.pop(k, None) for k in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")}
        try:
            self.assertEqual("/tmp", R.unix_dir())
            os.environ["TMP"] = "/x/tmp"
            self.assertEqual("/x/tmp", R.unix_dir())
            os.environ["XDG_RUNTIME_DIR"] = "/run/user/1000"
            self.assertEqual("/run/user/1000", R.unix_dir())
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_stale_presence_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"at": time.time() - 10 * 3600, "state": "Floor 1 of 2"}, fh)
            self.assertIsNone(R.read_presence(path))


if __name__ == "__main__":
    unittest.main()
