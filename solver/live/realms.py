"""Reading a live battle from Toontown Realms' local Astron cluster.

WHAT THIS IS. Realms -- what Toontown Offline became -- ships a full
Astron server that runs on the player's own machine. Every value the
screen readers infer from pixels is published there as a typed field:
the cog's identity, its exact HP, every toon's laff, the pouch. This
module subscribes to that stream and keeps an object store from it.

Subscribing to the Message Director is how every AI and UberDOG process
in an Astron cluster attaches. It is the designed extension point, it is
local, and this module is READ-ONLY: it sends two control messages, one
to name itself and one to subscribe, and never an object update or a
command of any kind.

WHAT IT IS NOT. It is not a source of game data. Realms is Toontown
Online lineage and its balance is frozen where TTR's moved on -- its
level 12 has 200 HP because that is what Toontown had before TTR 3.0.0
replaced the flat 10% boost with the `+14` term and made it 196.
Nothing read here may be written into `solver/data/`, used to fit a
weight, or used to score a policy. See `docs/realms.md`.

What it IS good for is proving the reader right. Whether `build_state`
turns a `setHP` into the correct `CogState.hp` does not depend on which
game's balance is in force, and this is far better ground truth for
that than a screenshot will ever be.

OPTIONAL DEPENDENCY. Needs panda3d, listed in requirements-realms.txt.
`solver/live/__init__` must not import this module and the tests skip
rather than fail when it is missing -- the same arrangement `vision.py`
has with numpy.
"""
from __future__ import annotations

import random
import socket
import struct
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

# Where Realms normally lands on Windows.
DEFAULT_LOCATIONS = (
    Path.home() / "AppData" / "Local" / "Toontown Realms",
    Path("C:/Program Files/Toontown Realms"),
    Path("C:/Program Files (x86)/Toontown Realms"),
)

MD_HOST = "127.0.0.1"
MD_PORT = 7199

# Astron control protocol. Control messages address channel 1 and OMIT
# the sender field that every other message carries. Getting that wrong
# shifts the message type by eight bytes and every datagram after it
# decodes as garbage, which looks like a wire format problem rather
# than an off-by-one.
CONTROL_CHANNEL = 1
CONTROL_ADD_CHANNEL = 9000
CONTROL_ADD_RANGE = 9002
CONTROL_SET_CON_NAME = 9004

# State server messages worth keeping.
OBJECT_DELETE_RAM = 2007
OBJECT_GET_ALL = 2014
OBJECT_GET_ALL_RESP = 2015
OBJECT_SET_FIELD = 2020
OBJECT_SET_FIELDS = 2021
OBJECT_CHANGING_LOCATION = 2060
OBJECT_ENTER_LOCATION_WITH_REQUIRED = 2066
OBJECT_ENTER_LOCATION_WITH_REQUIRED_OTHER = 2067
OBJECT_ENTER_AI_WITH_REQUIRED = 2064
OBJECT_ENTER_AI_WITH_REQUIRED_OTHER = 2065

ENTER_MESSAGES = (OBJECT_ENTER_LOCATION_WITH_REQUIRED,
                  OBJECT_ENTER_LOCATION_WITH_REQUIRED_OTHER,
                  OBJECT_ENTER_AI_WITH_REQUIRED,
                  OBJECT_ENTER_AI_WITH_REQUIRED_OTHER)

# The classes a battle is assembled from.
COG_CLASSES = ("DistributedSuitBase", "DistributedSuit",
               "DistributedFactorySuit", "DistributedMintSuit",
               "DistributedStageSuit", "DistributedTutorialSuit")
BATTLE_CLASSES = ("DistributedBattle", "DistributedBattleBldg",
                  "DistributedLevelBattle", "DistributedBattleFactory",
                  "DistributedMintBattle", "DistributedStageBattle",
                  "DistributedBattleFinal", "DistributedCogdoBattleBldg",
                  "DistributedCountryClubBattle", "DistributedBattleTutorial")
TOON_CLASSES = ("DistributedToon", "DistributedTemporaryToon")


class RealmsError(RuntimeError):
    """Realms is not installed, is not running, or is missing a file."""


def install_dir(override: Optional[str] = None) -> Path:
    candidates = [Path(override)] if override else list(DEFAULT_LOCATIONS)
    for path in candidates:
        if (path / "astron" / "dclass" / "ttoff.dc").is_file():
            return path
    raise RealmsError(
        "cannot find a Toontown Realms installation (looked for "
        + ", ".join(str(p) for p in candidates)
        + "). Set REALMS_DIR to the install directory.")


def dc_path(override: Optional[str] = None) -> Path:
    return install_dir(override) / "astron" / "dclass" / "ttoff.dc"


# ---------------------------------------------------------------------
# The DC file
# ---------------------------------------------------------------------

class DCIndex:
    """Field id to name and value, using the game's own parser.

    The numbering in a .dc file is the contract between client and
    server, and it is NOT simply declaration order. A hand-rolled parser
    that assumed so put `DistributedSuit.setPathPosition` at 492 and
    decoded live cog traffic as `DistributedPlayer.setDISLname`, which
    is wrong in a way that looks plausible until you notice street cogs
    do not have account names. panda3d's `DCFile` is the parser the game
    itself uses, so it is right by construction rather than by
    agreement.
    """

    def __init__(self, path: Optional[Path] = None,
                 override: Optional[str] = None):
        try:
            from panda3d.core import Filename
            from panda3d.direct import DCFile
        except ImportError as exc:      # pragma: no cover - optional dep
            raise RealmsError(
                "reading Realms needs panda3d: "
                "pip install -r requirements-realms.txt") from exc

        self.path = Path(path) if path else dc_path(override)
        self._dc = DCFile()
        if not self._dc.read(Filename.fromOsSpecific(str(self.path))):
            raise RealmsError(f"could not parse {self.path}")

    def field(self, field_id: int):
        return self._dc.getFieldByIndex(field_id)

    def name(self, field_id: int) -> str:
        field = self.field(field_id)
        if field is None:
            return f"<unknown field {field_id}>"
        return f"{field.getClass().getName()}.{field.getName()}"

    def class_name(self, dclass_id: int) -> str:
        dclass = self._dc.getClass(dclass_id)
        return dclass.getName() if dclass is not None else f"<{dclass_id}>"

    def field_id(self, class_name: str, field_name: str) -> Optional[int]:
        dclass = self._dc.getClassByName(class_name)
        if dclass is None:
            return None
        field = dclass.getFieldByName(field_name)
        return None if field is None else field.getNumber()

    def required_fields(self, dclass_id: int) -> List:
        """A class's `required` fields, in wire order.

        An ENTER message packs them positionally with no field ids at
        all, so declaration order is the only thing that says which is
        which. Inherited required fields come first, which
        `getInheritedField` already accounts for. Molecular fields are
        skipped: they are aliases for several atomic fields and are
        never packed on the wire.
        """
        dclass = self._dc.getClass(dclass_id)
        if dclass is None:
            return []
        return [f for f in (dclass.getInheritedField(i)
                            for i in range(dclass.getNumInheritedFields()))
                if f.isRequired() and f.asMolecularField() is None]

    def unpack(self, field, blob: bytes):
        """(bytes consumed, value), or (None, None) if it will not decode.

        Returns rather than raises: one malformed field must not take
        down a listener reading a whole cluster's traffic. The byte
        count matters because SET_FIELDS and the ENTER messages pack
        values back to back with no lengths, so the only way to find the
        next field is to finish unpacking this one.
        """
        from panda3d.direct import DCPacker

        packer = DCPacker()
        packer.setUnpackData(bytes(blob))
        packer.beginUnpack(field)
        try:
            value = packer.unpackObject()
        except Exception:               # pragma: no cover - malformed
            return None, None
        consumed = packer.getNumUnpackedBytes()
        if not packer.endUnpack():
            return None, None
        # `unpackObject` returns a field's ARGUMENT LIST, so a
        # single-argument field like setHP comes back as `(6,)` rather
        # than `6`. Unwrap it: every caller wants the value, and a
        # one-tuple that has to be indexed at every use site is a
        # papercut that will eventually be forgotten somewhere.
        # Multi-argument fields (setMembers, setState) keep their tuple.
        if isinstance(value, (tuple, list)) and len(value) == 1:
            return consumed, value[0]
        return consumed, value


# ---------------------------------------------------------------------
# The object store
# ---------------------------------------------------------------------

class LiveObject:
    __slots__ = ("do_id", "dclass", "parent", "zone", "fields")

    def __init__(self, do_id: int, dclass: str = "",
                 parent: int = 0, zone: int = 0):
        self.do_id = do_id
        self.dclass = dclass
        self.parent = parent
        self.zone = zone
        self.fields: Dict[str, object] = {}

    def get(self, name: str, default=None):
        return self.fields.get(name, default)

    def __repr__(self) -> str:                       # pragma: no cover
        return (f"<{self.dclass or '?'} {self.do_id} zone={self.zone} "
                f"{len(self.fields)} fields>")


class ObjectStore:
    """Every object the listener has seen, keyed by doId.

    Deliberately keeps EVERY class rather than filtering to cogs and
    toons. A battle is identified by its own object and which toons and
    cogs are in it comes from `setMembers` on that object, so filtering
    earlier would leave cogs held with no way to know which fight they
    belong to.
    """

    def __init__(self):
        self.objects: Dict[int, LiveObject] = {}
        self._lock = threading.Lock()

    def _touch(self, do_id: int) -> LiveObject:
        obj = self.objects.get(do_id)
        if obj is None:
            obj = LiveObject(do_id)
            self.objects[do_id] = obj
        return obj

    def enter(self, do_id, dclass, parent, zone, fields) -> LiveObject:
        with self._lock:
            obj = self._touch(do_id)
            obj.dclass, obj.parent, obj.zone = dclass, parent, zone
            obj.fields.update(fields)
            return obj

    def set_field(self, do_id, name, value) -> LiveObject:
        with self._lock:
            obj = self._touch(do_id)
            obj.fields[name] = value
            return obj

    def relocate(self, do_id, parent, zone) -> None:
        with self._lock:
            obj = self.objects.get(do_id)
            if obj is not None:
                obj.parent, obj.zone = parent, zone

    def delete(self, do_id) -> None:
        with self._lock:
            self.objects.pop(do_id, None)

    def of_class(self, *names: str) -> List[LiveObject]:
        wanted = set(names)
        with self._lock:
            return [o for o in self.objects.values() if o.dclass in wanted]

    def get(self, do_id: int) -> Optional[LiveObject]:
        with self._lock:
            return self.objects.get(do_id)

    def snapshot(self) -> Dict[int, LiveObject]:
        with self._lock:
            return dict(self.objects)

    def __len__(self) -> int:
        with self._lock:
            return len(self.objects)


# ---------------------------------------------------------------------
# The listener
# ---------------------------------------------------------------------

def _datagram(payload: bytes) -> bytes:
    return struct.pack("<H", len(payload)) + payload


def _control(msgtype: int, body: bytes = b"") -> bytes:
    # No sender field on a control message.
    return _datagram(struct.pack("<BQH", 1, CONTROL_CHANNEL, msgtype) + body)


class RealmsListener(threading.Thread):
    """A read-only Message Director participant.

    Subscribes to the whole channel range. A narrower subscription would
    need the district's doId and the battle's zone, which are exactly
    what this is trying to discover, so there is nothing to narrow to
    until a battle has already been seen once.
    """

    def __init__(self, index: Optional[DCIndex] = None,
                 host: str = MD_HOST, port: int = MD_PORT,
                 on_event: Optional[Callable[[str, "LiveObject"], None]] = None):
        super().__init__(daemon=True)
        self.index = index if index is not None else DCIndex()
        self.host, self.port = host, port
        self.store = ObjectStore()
        self.on_event = on_event
        self.connected = threading.Event()
        self.datagrams = 0
        self.undecoded = 0
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._reply_channel = 0
        self._context = 0

    # -- lifecycle ----------------------------------------------------
    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self.host, self.port),
                                                  timeout=5)
        except OSError as exc:
            raise RealmsError(
                f"no Astron message director on {self.host}:{self.port} -- "
                f"is Toontown Realms running?") from exc
        self._sock.sendall(_control(CONTROL_SET_CON_NAME,
                                    b"ttrsolver-reader\x00"))
        self._sock.sendall(_control(CONTROL_ADD_RANGE,
                                    struct.pack("<QQ", 0, (1 << 64) - 1)))
        # A private channel for query replies. Randomised rather than
        # fixed so two readers on one cluster do not eat each other's
        # answers, and kept well above the doId space.
        self._reply_channel = 0x5454_0000_0000_0000 | random.getrandbits(32)
        self._sock.sendall(_control(CONTROL_ADD_CHANNEL,
                                    struct.pack("<Q", self._reply_channel)))
        self.connected.set()

    def refresh(self, do_id: int) -> None:
        """Ask the state server for everything it holds about `do_id`.

        WHY THIS EXISTS. The stream carries CHANGES. An object generated
        before the listener attached has therefore never been described
        to it: the first live run saw 944 datagrams, decoded every one,
        and still reported `hp=None` for a cog standing in front of the
        player, because the cog's `setHP` was packed into a generate
        message that had already been and gone.

        Requiring the tool to be attached before the fight starts is not
        a workable rule for something a player turns on when they want
        advice, so this asks.

        IT IS STILL A READ. `OBJECT_GET_ALL` is a query: it mutates no
        object, sends nothing to the client, and is answered on this
        listener's own private channel. The read-only promise in this
        module's docstring is about not changing the game, and a query
        does not.
        """
        if self._sock is None:
            raise RealmsError("not connected")
        self._context += 1
        payload = (struct.pack("<BQ", 1, do_id)          # to the object
                   + struct.pack("<Q", self._reply_channel)
                   + struct.pack("<H", OBJECT_GET_ALL)
                   + struct.pack("<II", self._context, do_id))
        self._sock.sendall(_datagram(payload))

    def refresh_all(self, classes: Optional[Sequence[str]] = None) -> int:
        """Re-ask for every object seen so far, or just some classes."""
        wanted = set(classes) if classes else None
        asked = 0
        for obj in self.store.snapshot().values():
            if wanted is not None and obj.dclass not in wanted:
                continue
            self.refresh(obj.do_id)
            asked += 1
        return asked

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:             # pragma: no cover
                pass

    def run(self) -> None:              # pragma: no cover - needs a server
        if self._sock is None:
            self.connect()
        self._sock.settimeout(1.0)
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf = self.feed(buf + chunk)

    # -- decoding -----------------------------------------------------
    def feed(self, buf: bytes) -> bytes:
        """Consume whole datagrams from `buf`, return the remainder.

        Split out from `run` so it can be tested without a socket. The
        framing -- a uint16 length prefix that a TCP read will happily
        split down the middle -- is the part most likely to be got
        wrong, and it needs no live cluster to exercise.
        """
        while len(buf) >= 2:
            (length,) = struct.unpack_from("<H", buf, 0)
            if len(buf) < 2 + length:
                break
            payload, buf = buf[2:2 + length], buf[2 + length:]
            self.datagrams += 1
            try:
                self.handle(payload)
            except (struct.error, IndexError, ValueError):
                self.undecoded += 1
        return buf

    def handle(self, payload: bytes) -> None:
        count = payload[0]
        offset = 1 + 8 * count
        _sender, msgtype = struct.unpack_from("<QH", payload, offset)
        body = payload[offset + 10:]

        if msgtype == OBJECT_SET_FIELD:
            self._set_field(body)
        elif msgtype == OBJECT_SET_FIELDS:
            self._set_fields(body)
        elif msgtype in ENTER_MESSAGES:
            self._enter(body)
        elif msgtype == OBJECT_GET_ALL_RESP:
            # context, then exactly an ENTER payload, then the non-required
            # fields as (count, [id, value]...).
            self._enter(body[4:], with_other=True)
        elif msgtype == OBJECT_DELETE_RAM:
            (do_id,) = struct.unpack_from("<I", body, 0)
            self.store.delete(do_id)
        elif msgtype == OBJECT_CHANGING_LOCATION:
            do_id, parent, zone = struct.unpack_from("<III", body, 0)
            self.store.relocate(do_id, parent, zone)

    def _record(self, do_id: int, field, value) -> None:
        obj = self.store.set_field(do_id, field.getName(), value)
        if not obj.dclass:
            # SET_FIELD does not name the class. The field knows the one
            # it was DECLARED on, which for an inherited field is the
            # base -- good enough to tell a cog from a toon, and the
            # ENTER message corrects it with the real class.
            obj.dclass = field.getClass().getName()
        self._notify(field.getName(), obj)

    def _set_field(self, body: bytes) -> None:
        do_id, field_id = struct.unpack_from("<IH", body, 0)
        field = self.index.field(field_id)
        if field is None:
            self.undecoded += 1
            return
        _consumed, value = self.index.unpack(field, body[6:])
        self._record(do_id, field, value)

    def _set_fields(self, body: bytes) -> None:
        do_id, count = struct.unpack_from("<IH", body, 0)
        offset = 6
        for _ in range(count):
            (field_id,) = struct.unpack_from("<H", body, offset)
            offset += 2
            field = self.index.field(field_id)
            if field is None:
                self.undecoded += 1
                return                  # no way to find the next boundary
            consumed, value = self.index.unpack(field, body[offset:])
            if consumed is None:
                self.undecoded += 1
                return
            offset += consumed
            self._record(do_id, field, value)

    def _enter(self, body: bytes, with_other: bool = False) -> None:
        # doId, parentId, zoneId, dclassId, then the required fields
        # packed positionally with no ids at all.
        do_id, parent, zone, dclass_id = struct.unpack_from("<IIIH", body, 0)
        offset = 14
        fields: Dict[str, object] = {}
        for field in self.index.required_fields(dclass_id):
            consumed, value = self.index.unpack(field, body[offset:])
            if consumed is None:
                self.undecoded += 1
                break
            fields[field.getName()] = value
            offset += consumed
        else:
            # Only read the `other` block if every required field landed.
            # A short read above leaves `offset` pointing into the middle
            # of a value, and a count taken from there is nonsense.
            if with_other and offset + 2 <= len(body):
                (count,) = struct.unpack_from("<H", body, offset)
                offset += 2
                for _ in range(count):
                    if offset + 2 > len(body):
                        break
                    (field_id,) = struct.unpack_from("<H", body, offset)
                    offset += 2
                    field = self.index.field(field_id)
                    if field is None:
                        break
                    consumed, value = self.index.unpack(field, body[offset:])
                    if consumed is None:
                        break
                    fields[field.getName()] = value
                    offset += consumed
        obj = self.store.enter(do_id, self.index.class_name(dclass_id),
                               parent, zone, fields)
        self._notify("<enter>", obj)

    def _notify(self, what: str, obj: LiveObject) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(what, obj)
        except Exception:               # pragma: no cover - bad callback
            pass                        # must never kill the reader

    # -- what is on the field ------------------------------------------
    def cogs(self) -> List[LiveObject]:
        return self.store.of_class(*COG_CLASSES)

    def battles(self) -> List[LiveObject]:
        return self.store.of_class(*BATTLE_CLASSES)

    def toons(self) -> List[LiveObject]:
        return self.store.of_class(*TOON_CLASSES)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def _describe(listener: "RealmsListener") -> str:
    lines = []
    battles = listener.battles()
    lines.append(f"battles : {len(battles)}")
    for battle in battles:
        lines.append(f"  #{battle.do_id} zone {battle.zone} "
                     f"state={battle.get('setState')!r}")
        members = battle.get("setMembers")
        if members:
            lines.append(f"    members {members!r}"[:300])

    cogs = listener.cogs()
    lines.append(f"cogs    : {len(cogs)}")
    for cog in sorted(cogs, key=lambda o: o.do_id):
        dna = cog.get("setDNAString")
        if isinstance(dna, (bytes, bytearray)):
            dna = bytes(dna).decode("latin-1", "replace")
        lines.append(f"  #{cog.do_id} zone {cog.zone} dna={dna!r} "
                     f"lvl+{cog.get('setLevelDist')} "
                     f"hp {cog.get('setHP')}/{cog.get('setMaxHP')} "
                     f"skele={cog.get('setSkelecog')}")

    toons = listener.toons()
    lines.append(f"toons   : {len(toons)}")
    for toon in sorted(toons, key=lambda o: o.do_id):
        lines.append(f"  #{toon.do_id} laff {toon.get('setHp')}/"
                     f"{toon.get('setMaxHp')} "
                     f"tracks={toon.get('setTrackAccess')} "
                     f"organic={toon.get('setTrackBonusLevel')}")
    return "\n".join(lines)


def main(argv=None) -> int:                          # pragma: no cover
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Read a live Toontown Realms battle off its Astron "
                    "cluster. Read-only: it subscribes and queries, and "
                    "never sends an object update.")
    parser.add_argument("--seconds", type=float, default=20.0,
                        help="how long to watch")
    parser.add_argument("--discover", type=float, default=5.0,
                        help="listen this long before asking the state "
                             "server about what turned up")
    parser.add_argument("--dir", help="Realms install directory")
    args = parser.parse_args(argv)

    try:
        index = DCIndex(override=args.dir)
    except RealmsError as exc:
        print(f"  {exc}")
        return 1
    print(f"  dc      : {index.path}")

    listener = RealmsListener(index=index)
    try:
        listener.connect()
    except RealmsError as exc:
        print(f"  {exc}")
        return 1
    listener.start()
    print(f"  attached: {MD_HOST}:{MD_PORT}")

    time.sleep(args.discover)
    asked = listener.refresh_all()
    time.sleep(2.0)
    print(f"  asked    : {asked} objects\n")

    end = time.time() + args.seconds
    seen = set()
    while time.time() < end:
        current = {b.do_id for b in listener.battles()}
        if current - seen:
            seen |= current
            listener.refresh_all()
            time.sleep(1.0)
            print(_describe(listener))
            print()
        time.sleep(0.5)

    if not seen:
        print(_describe(listener))
    print(f"\n  {listener.datagrams} datagrams, "
          f"{listener.undecoded} undecoded, {len(listener.store)} objects")
    listener.close()
    return 0


if __name__ == "__main__":                           # pragma: no cover
    raise SystemExit(main())
