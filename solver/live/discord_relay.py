"""What TTR tells Discord -- "Floor 2 of 4" -- read off Discord's own pipe.

    python -m solver.live.discord_relay

THE ONE PLACE A BUILDING'S FLOORS EXIST. The Local API says "Cog
Building" and the client's log says `SuitInterior`; neither has the
building's height or the floor. The game hands exactly that to Discord's
Rich Presence ("In a Three Story Sellbot Building", "Floor 3 of 3",
observed 2026-10-10) over a local pipe, and Discord lets no other
program read another app's status.

So this sits on that pipe. A Discord RPC client connects to the first of
`discord-ipc-0` .. `-9` that exists, and Discord takes the first free one
when it starts. Two cases:

* DISCORD NOT RUNNING: nothing owns `discord-ipc-0`, so the relay takes
  it and answers the game's handshake itself. No order to get right.
* DISCORD RUNNING: started BEFORE Discord, the relay owns `-0`, Discord
  settles on `-1`, and every byte is passed through to Discord unchanged
  both ways -- the player's status still shows. A Discord already
  holding `-0` cannot be displaced (`PipeTaken`).

Either way each `SET_ACTIVITY` frame is kept and written to
`PRESENCE_FILE` for the panel. It reads what the game PUBLISHES and
nothing else: no memory, no process.

Wire format, Discord's documented IPC: an 8-byte header, little-endian
(opcode, length), then that many bytes of JSON. Opcodes: 0 handshake,
1 frame, 2 close, 3 ping, 4 pong.

Standard library only, on every platform -- see the transports.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

BASE = "discord-ipc-"
OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4
HEADER = struct.Struct("<II")
BUFFER = 65536

PRESENCE_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
    "TTRSolver", "discord_presence.json")


class PipeTaken(RuntimeError):
    """Something -- normally a running Discord -- already owns the pipe."""


def frame(op: int, payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return HEADER.pack(op, len(body)) + body


class FrameReader:
    """Split a byte stream into (opcode, decoded JSON or None) frames."""

    def __init__(self):
        self._buf = b""

    def feed(self, data: bytes) -> List[Tuple[int, Optional[dict]]]:
        self._buf += data
        out = []
        while len(self._buf) >= HEADER.size:
            op, length = HEADER.unpack_from(self._buf)
            if len(self._buf) < HEADER.size + length:
                break
            body = self._buf[HEADER.size:HEADER.size + length]
            self._buf = self._buf[HEADER.size + length:]
            try:
                out.append((op, json.loads(body.decode("utf-8"))))
            except (ValueError, UnicodeDecodeError):
                out.append((op, None))
        return out


# -- transports ---------------------------------------------------------------
#
# The same stream on every platform, carried the way Discord's own
# `discord-rpc` library carries it (connection_win.cpp, connection_unix.cpp):
#   Windows       named pipe   \\.\pipe\discord-ipc-N
#   macOS, Linux  Unix socket  <dir>/discord-ipc-N, <dir> the first set of
#                 XDG_RUNTIME_DIR, TMPDIR, TMP, TEMP, else /tmp
# Seen working here on Windows. The Unix transport follows the reference
# implementation and has run against itself, not yet against a real Mac.

PIPE_PREFIX = "\\\\.\\pipe\\"


class WindowsPipes:
    """Overlapped named pipes through `_winapi`, as `multiprocessing` does.
    Overlapped because a game-to-Discord read and a Discord-to-game write
    on one synchronous handle would block each other."""

    def __init__(self):
        import _winapi
        self.w = _winapi

    def _instance(self, name: str, first: bool):
        w = self.w
        mode = w.PIPE_ACCESS_DUPLEX | w.FILE_FLAG_OVERLAPPED
        if first:
            mode |= w.FILE_FLAG_FIRST_PIPE_INSTANCE
        try:
            # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE are both 0; _winapi lacks them.
            return w.CreateNamedPipe(PIPE_PREFIX + name, mode, w.PIPE_WAIT,
                                     w.PIPE_UNLIMITED_INSTANCES, BUFFER, BUFFER,
                                     0, w.NULL)
        except PermissionError as exc:
            raise PipeTaken(name) from exc

    def serve(self, name: str):
        return [name, self._instance(name, first=True)]

    def accept(self, listener):
        name, handle = listener
        try:
            ov = self.w.ConnectNamedPipe(handle, overlapped=True)
            ov.GetOverlappedResult(True)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 535:    # already connected
                self.close(handle)
                listener[1] = self._instance(name, first=False)
                return None
        listener[1] = self._instance(name, first=False)
        return handle

    def close_listener(self, listener) -> None:
        self.close(listener[1])

    def connect(self, name: str):
        w = self.w
        try:
            return w.CreateFile(PIPE_PREFIX + name,
                                w.GENERIC_READ | w.GENERIC_WRITE, 0, w.NULL,
                                w.OPEN_EXISTING, w.FILE_FLAG_OVERLAPPED, w.NULL)
        except OSError:
            return None

    def read(self, handle) -> bytes:
        try:
            ov, _err = self.w.ReadFile(handle, BUFFER, overlapped=True)
            ov.GetOverlappedResult(True)
            return bytes(ov.getbuffer())
        except OSError:
            return b""

    def write(self, handle, data: bytes) -> bool:
        try:
            ov, _err = self.w.WriteFile(handle, data, overlapped=True)
            ov.GetOverlappedResult(True)
            return True
        except OSError:
            return False

    def close(self, handle) -> None:
        try:
            self.w.CloseHandle(handle)
        except OSError:
            pass


def unix_dir() -> str:
    """Where Discord puts its socket on macOS and Linux (discord-rpc)."""
    for var in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"):
        if os.environ.get(var):
            return os.environ[var]
    return "/tmp"


class UnixSockets:
    """Unix domain sockets in Discord's runtime directory."""

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or unix_dir()

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def serve(self, name: str):
        import socket
        path = self._path(name)
        if os.path.exists(path):
            probe = self.connect(name)
            if probe is not None:
                self.close(probe)
                raise PipeTaken(name)
            os.unlink(path)                       # a stale socket file
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(8)
        return [name, listener]

    def accept(self, listener):
        try:
            conn, _addr = listener[1].accept()
            return conn
        except OSError:
            return None

    def close_listener(self, listener) -> None:
        try:
            listener[1].close()
            os.unlink(self._path(listener[0]))
        except OSError:
            pass

    def connect(self, name: str):
        import socket
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.connect(self._path(name))
            return conn
        except OSError:
            conn.close()
            return None

    def read(self, conn) -> bytes:
        try:
            return conn.recv(BUFFER)
        except OSError:
            return b""

    def write(self, conn, data: bytes) -> bool:
        try:
            conn.sendall(data)
            return True
        except OSError:
            return False

    def close(self, conn) -> None:
        try:
            conn.close()
        except OSError:
            pass


def transport():
    return WindowsPipes() if sys.platform.startswith("win") else UnixSockets()


# -- the relay ------------------------------------------------------------------

class Relay:
    """Own `<base><own>`, pass every client through to Discord when it is
    there (answer for it when it is not), and keep the activities set."""

    def __init__(self, base: str = BASE, own: int = 0,
                 presence_file: Optional[str] = PRESENCE_FILE, carrier=None):
        self.base = base
        self.own = own
        self.presence_file = presence_file
        self.t = carrier or transport()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: Optional[Dict] = None
        self._listener = None
        self.sessions = 0

    def latest(self) -> Optional[Dict]:
        """The last activity any client set: details, state, when, who."""
        with self._lock:
            return dict(self._latest) if self._latest else None

    def _record(self, client_id, payload) -> None:
        if not isinstance(payload, dict) or payload.get("cmd") != "SET_ACTIVITY":
            return
        activity = (payload.get("args") or {}).get("activity")
        entry = {"at": time.time(), "client_id": client_id,
                 "details": (activity or {}).get("details"),
                 "state": (activity or {}).get("state"),
                 "cleared": activity is None}
        # The file first, so anything that saw `latest()` change can
        # already read it.
        if self.presence_file:
            try:
                os.makedirs(os.path.dirname(self.presence_file), exist_ok=True)
                tmp = self.presence_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(entry, fh)
                os.replace(tmp, self.presence_file)
            except OSError:
                pass
        with self._lock:
            self._latest = entry

    def start(self) -> "Relay":
        """Claim the pipe (or raise PipeTaken) and accept in the background."""
        self._listener = self.t.serve(self.base + str(self.own))
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        # Unblock a pending accept by connecting to it, then let go.
        conn = self.t.connect(self.base + str(self.own))
        if conn is not None:
            self.t.close(conn)
        if self._listener is not None:
            self.t.close_listener(self._listener)

    def _accept(self) -> None:
        while not self._stop.is_set():
            conn = self.t.accept(self._listener)
            if conn is None:
                continue
            if self._stop.is_set():
                self.t.close(conn)
                return
            self.sessions += 1
            threading.Thread(target=self._session, args=(conn,),
                             daemon=True).start()

    def _upstream(self):
        for index in range(10):
            if index != self.own:
                conn = self.t.connect(self.base + str(index))
                if conn is not None:
                    return conn
        return None

    def _session(self, game) -> None:
        t = self.t
        upstream = self._upstream()
        reader = FrameReader()
        client_id = None
        done = threading.Event()

        if upstream is not None:
            def back():
                while not done.is_set():
                    data = t.read(upstream)
                    if not data or not t.write(game, data):
                        break
                done.set()
            threading.Thread(target=back, daemon=True).start()

        while not done.is_set():
            data = t.read(game)
            if not data:
                break
            if upstream is not None and not t.write(upstream, data):
                break
            for op, payload in reader.feed(data):
                if op == OP_HANDSHAKE and isinstance(payload, dict):
                    client_id = payload.get("client_id")
                    if upstream is None:
                        # NO DISCORD: answer as it would, so the game keeps
                        # publishing what this relay is here to read.
                        t.write(game, frame(OP_FRAME, {
                            "cmd": "DISPATCH", "evt": "READY", "nonce": None,
                            "data": {"v": 1, "config": {},
                                     "user": {"id": "0", "username": "relay",
                                              "discriminator": "0"}}}))
                elif op == OP_FRAME:
                    self._record(client_id, payload)
                    if upstream is None and isinstance(payload, dict):
                        t.write(game, frame(OP_FRAME, {
                            "cmd": payload.get("cmd"), "evt": None,
                            "nonce": payload.get("nonce"), "data": {}}))
                elif op == OP_PING and upstream is None:
                    t.write(game, frame(OP_PONG, payload or {}))
        done.set()
        t.close(game)
        if upstream is not None:
            t.close(upstream)


# OBSERVED 2026-10-10 in Discord: details "In a Three Story Sellbot
# Building", state "Floor 3 of 3". Only that shape is read; anything else
# (a street, a facility, a wording change) is None, never a guess.
_STORIES = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
_BUILDING = re.compile(r"\b(One|Two|Three|Four|Five) Story "
                       r"(Sellbot|Cashbot|Lawbot|Bossbot) Building\b")
_FLOOR = re.compile(r"\bFloor (\d+) of (\d+)\b")
_DEPARTMENT = {"Sellbot": "sellbot", "Cashbot": "cashbot",
               "Lawbot": "lawbot", "Bossbot": "bossbot"}


def building(entry: Optional[Dict]) -> Optional[Dict]:
    """{floor, floors, department} from a presence record, or None.

    The floor and its total come from "Floor X of Y"; the story count in
    the details must agree with Y, or the record is not trusted at all.
    """
    if not entry or entry.get("cleared"):
        return None
    text = " ".join(str(entry.get(k) or "") for k in ("details", "state"))
    floor = _FLOOR.search(text)
    if floor is None:
        return None
    current, total = int(floor.group(1)), int(floor.group(2))
    kind = _BUILDING.search(text)
    if kind is not None and _STORIES[kind.group(1)] != total:
        return None
    if not 1 <= current <= total <= 5:
        return None
    return {"floor": current, "floors": total,
            "department": _DEPARTMENT[kind.group(2)] if kind else None}


def read_presence(path: str = PRESENCE_FILE,
                  max_age: float = 6 * 3600) -> Optional[Dict]:
    """The relay's last record, if one exists and is not stale."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            entry = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or time.time() - entry.get("at", 0) > max_age:
        return None
    return entry


def main(argv=None) -> int:
    try:
        relay = Relay().start()
    except PipeTaken:
        print("Discord already owns discord-ipc-0. Quit Discord completely "
              "(tray icon -> Quit), run this again, then start Discord and "
              "then Toontown -- or leave Discord closed.")
        return 1
    print("relay on discord-ipc-0. Start Toontown now (and Discord, if wanted).")
    print(f"writing what the game publishes to {PRESENCE_FILE}")
    shown = None
    try:
        while True:
            entry = relay.latest()
            text = entry and (entry.get("details"), entry.get("state"))
            if text and text != shown:
                print(f"{time.strftime('%H:%M:%S')}  {text[0]} | {text[1]}")
                shown = text
            time.sleep(1.0)
    except KeyboardInterrupt:
        relay.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
