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
from typing import (Callable, Dict, List, NamedTuple, Optional,
                    Sequence, Tuple)

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

# The battle state whose entries count rounds. Observed live alongside
# 'WaitForInput'; one movie is one round.
MOVIE_STATE = "PlayMovie"


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
# Suit DNA
# ---------------------------------------------------------------------

# The department letter. [CONFIRMED BY OBSERVATION] -- all four turned
# up in one live capture and each agreed with the cog it was attached
# to: 'sf\0\0c' a Flunky, 'scc\0s' a Cold Caller, 'spp\0m' a Penny
# Pincher, 'sdt\0l' a Double Talker.
DNA_DEPARTMENTS = {"c": "bossbot", "s": "sellbot",
                   "m": "cashbot", "l": "lawbot"}

# Cog code to our own key. [OPEN TOONTOWN SOURCE] -- this is a NAMING
# map rather than game data, so it does not fall under the ban on
# Realms numbers reaching `solver/data/`; nothing here is a stat.
#
# Five entries are [CONFIRMED BY OBSERVATION] from live captures: sc,
# cc, f, pp, dt. Six more are confirmed from the game's OWN data pack,
# which prints them into its log beside the localiser key -- 'mh' next
# to #SuitMrHollywood, 'nd' to #SuitNameDropper, 'gh' to
# #SuitGladHander, 'ms' to #SuitMoverShaker, 'm' to #SuitTheMingler,
# 'cc' again to #SuitColdCaller. The rest follow the same scheme and an
# unknown code returns None rather than a guess.
DNA_COGS = {
    # Bossbot
    "f": "flunky", "p": "pencil_pusher", "ym": "yesman",
    "mm": "micromanager", "ds": "downsizer", "hh": "head_hunter",
    "cr": "corporate_raider", "tbc": "the_big_cheese",
    # Sellbot
    "cc": "cold_caller", "tm": "telemarketer", "nd": "name_dropper",
    "gh": "glad_hander", "ms": "mover_and_shaker", "tf": "two_face",
    "m": "the_mingler", "mh": "mr_hollywood",
    # Cashbot
    "sc": "short_change", "pp": "penny_pincher", "tw": "tightwad",
    "bc": "bean_counter", "nc": "number_cruncher", "mb": "money_bags",
    "ls": "loan_shark", "rb": "robber_baron",
    # Lawbot
    "bf": "bottom_feeder", "b": "bloodsucker", "dt": "double_talker",
    "ac": "ambulance_chaser", "bs": "backstabber", "sd": "spin_doctor",
    "le": "legal_eagle", "bw": "big_wig",
}


def parse_dna(raw) -> Optional[Tuple[str, str]]:
    """A suit's `setDNAString` as (department, cog key), or None.

    The blob is 's', then the cog's code padded with NULs to three
    bytes, then the department letter -- b'sdt\\x00l' is a Lawbot Double
    Talker, b'sf\\x00\\x00c' a Bossbot Flunky.

    Returns None for anything it does not recognise. An unknown cog is
    exactly the case the head catalogue refuses to guess at, and being
    handed a typed field instead of a picture is no reason to start.
    """
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 3:
        return None
    blob = bytes(raw)
    if blob[:1] != b"s":
        return None
    department = DNA_DEPARTMENTS.get(chr(blob[-1]))
    code = blob[1:-1].replace(b"\x00", b"").decode("latin-1", "replace")
    cog = DNA_COGS.get(code)
    if department is None or cog is None:
        return None
    return department, cog


def cog_level(level_dist) -> Optional[int]:
    """Absolute cog level from `setLevelDist`.

    IT IS THE LEVEL MINUS ONE, not an offset into the cog's own range,
    and the two are easy to confuse because they agree for every cog
    whose range starts at 1. Four live reads settled it, cross-checked
    against our own HP table rather than against Realms:

        Flunky        dist 0, hp 6   -> level 1   (both readings agree)
        Cold Caller   dist 0, hp 6   -> level 1   (both agree)
        Penny Pincher dist 1, hp 12  -> level 2   (range starts at 2,
                                                   so an offset would
                                                   have been 0)
        Double Talker dist 2, hp 20  -> level 3   (range starts at 3,
                                                   offset would be 0)

    The last two discriminate, and both say `level = dist + 1`.
    """
    if level_dist is None:
        return None
    try:
        return int(level_dist) + 1
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# The toon's pouch and training
# ---------------------------------------------------------------------

# Toontown's track order, which every one of these seven-long arrays is
# in: setInventory's rows, setTrackAccess, setTrackBonusLevel.
#
# WRITTEN OUT RATHER THAN TAKEN FROM `Track`'s DECLARATION ORDER, which
# happens to match today. Iterating the enum would couple the wire
# format to the order members are declared in an unrelated file, and
# reordering that enum -- an edit with no obvious connection to this
# module -- would silently shift every gag count by one track. The wire
# order is a property of the game, so it is stated here.
DC_TRACK_ORDER = ("toon_up", "trap", "lure", "sound",
                  "throw", "squirt", "drop")

INVENTORY_LEVELS = 7


def _track(name: str):
    from ..state import Track

    return Track(name)


def parse_inventory(blob) -> Optional[Dict]:
    """`setInventory` as {(Track, level): count}, or None.

    The blob is a uint16 length then seven rows of seven bytes, one row
    per track, one byte per level, holding the count carried. Verified
    against a real toon: the Toon-Up row was all zeros and that toon's
    `setTrackAccess[0]` was 0, which is an independent way of saying the
    same thing.

    Levels are 1-based here because the rest of this project counts them
    that way -- `gag_counts[(Track.TRAP, 6)]` is TNT.
    """
    if isinstance(blob, str):
        blob = blob.encode("latin-1", "replace")
    if not isinstance(blob, (bytes, bytearray)):
        return None
    raw = bytes(blob)
    if len(raw) >= 2:
        (declared,) = struct.unpack_from("<H", raw, 0)
        if declared == len(raw) - 2:
            raw = raw[2:]               # strip the blob's length prefix
    if len(raw) < len(DC_TRACK_ORDER) * INVENTORY_LEVELS:
        return None

    counts: Dict = {}
    for index, name in enumerate(DC_TRACK_ORDER):
        row = raw[index * INVENTORY_LEVELS:(index + 1) * INVENTORY_LEVELS]
        for level, number in enumerate(row, start=1):
            if number:
                counts[(_track(name), level)] = int(number)
    return counts


def parse_track_access(values) -> Optional[frozenset]:
    """`setTrackAccess` as the set of tracks the toon owns.

    Seven flags in `DC_TRACK_ORDER`. A toon with [0, 1, 1, 1, 1, 1, 1]
    has no Toon-Up, which is a real and awkward loadout rather than a
    misread -- `docs/` has a whole thread about what a Toon-Up-less toon
    can clear.
    """
    if not isinstance(values, (list, tuple)):
        return None
    if len(values) != len(DC_TRACK_ORDER):
        return None
    return frozenset(_track(name) for name, flag
                     in zip(DC_TRACK_ORDER, values) if flag)


def parse_organic(values) -> Optional[frozenset]:
    """`setTrackBonusLevel` as the set of ORGANIC tracks.

    Seven entries in `DC_TRACK_ORDER`, -1 for "not organic" and
    otherwise the level the bonus reaches. This project treats organic
    as a property of the whole track (see `ToonState.organic_tracks`),
    which is how TTR works: a track is earned organic by ToonTask and
    every gag in it is organic thereafter. So any non-negative entry
    makes the track organic and the level itself is dropped.

    THE LEVEL IS 0-BASED AND 6 MEANS THE WHOLE TRACK, per the owner, so
    a non-negative entry really does mean every gag in it -- the reading
    this function already took. A real toon read
    [-1, -1, -1, -1, 6, -1, -1]: Throw organic, all seven levels.

    Whether it means the same THING in both games is a separate
    question and the answer is no. Realms gives organic a flat +10% to
    damage; TTR's bonus varies by track and also raises Lure accuracy,
    which is why `Gag.organic_damage` is a per-gag column here rather
    than a multiplier. So this correctly reads WHICH tracks are organic
    and the solver will then price them by TTR's rules. That is the
    right split -- reading a position is not reading a rule -- but it
    does mean a damage number predicted here will not match what Realms
    rolls. See `docs/realms.md`.
    """
    if not isinstance(values, (list, tuple)):
        return None
    if len(values) != len(DC_TRACK_ORDER):
        return None
    return frozenset(_track(name) for name, level
                     in zip(DC_TRACK_ORDER, values)
                     if isinstance(level, int) and level >= 0)


# ---------------------------------------------------------------------
# setMembers
# ---------------------------------------------------------------------

class Members(NamedTuple):
    """`DistributedBattleBase.setMembers`, unpacked.

    The DC declares twelve untyped-looking slots --

        setMembers(uint32[], string, string, string, string, string,
                   uint32[], string, string, string, string, int16)

    -- which is Toontown's long-standing shape: the suits and their
    four state strings, then the toons and theirs, then a timestamp.
    Observed live as

        ([401005039], '', '', '0', '', '9', [100000001], '', '', '0',
         '', -23220)

    one cog and one toon, which is a solo street battle and reads
    correctly as such.

    `suits` and `toons` are the ones this project needs. `toons` in
    particular answers directly what the panel currently asks the player
    for: the party size, and so `BattleState.allies_standing`.

    THE STATE STRINGS ARE TWO DIFFERENT ENCODINGS, which is the trap
    here and was settled by observation rather than assumed. A second
    capture, two cogs with the first one lured:

        active='01'   lured='0'   traps='99'

    `traps` has one character per suit. `active` and `lured` do NOT:
    they are the INDICES of the suits in that state. One lured cog out
    of two gives '0', where a per-suit encoding would have given '10'
    or similar. The earlier single-cog capture (`lured=''`, `traps='9'`)
    agrees with both readings and so decides nothing; it is the two-cog
    frame that discriminates.

    Reading `lured` as one-char-per-suit would therefore mark the wrong
    cog asleep, in a solver where lure is the pivot of every Trap line.

    WHAT A TRAP LOOKS LIKE IS STILL UNOBSERVED. Every capture so far has
    '9' in every trap slot, and `setMembers` is only re-broadcast when
    membership changes -- a trap set mid-round does not resend it -- so
    a trapped cog has not been seen. `trapped_indices` therefore reports
    only "this slot is not 9", which is enough to know a trap is there
    and not enough to know which gag it is.
    """
    suits: Tuple[int, ...]
    suits_joining: str
    suits_pending: str
    suits_active: str
    suits_lured: str
    suit_traps: str
    toons: Tuple[int, ...]
    toons_joining: str
    toons_pending: str
    toons_active: str
    toons_running: str
    timestamp: int

    @property
    def toon_count(self) -> int:
        return len(self.toons)

    @property
    def allies_standing(self) -> int:
        """Teammates besides you, for `BattleState.allies_standing`.

        Clamped at 3: four toons is the most a battle holds, and a
        larger number would divide the danger by something impossible.
        """
        return max(0, min(3, len(self.toons) - 1))

    def _indices(self, text: str) -> Tuple[int, ...]:
        """Suit indices named in a state string, dropping any that do
        not address a suit actually in the roster."""
        out = []
        for char in text:
            if char.isdigit():
                index = int(char)
                if 0 <= index < len(self.suits):
                    out.append(index)
        return tuple(out)

    def lured_suits(self) -> Tuple[int, ...]:
        """doIds of the cogs currently lured."""
        return tuple(self.suits[i] for i in self._indices(self.suits_lured))

    def active_suits(self) -> Tuple[int, ...]:
        return tuple(self.suits[i] for i in self._indices(self.suits_active))

    def trapped_suits(self) -> Tuple[int, ...]:
        """doIds of cogs with SOMETHING on their trap slot.

        One character per suit, and '9' in every capture so far, which
        is this field's "no trap". A non-'9' character names the trap
        gag, but no trapped cog has been observed, so what the character
        maps to is not decoded -- only that it is not nothing. That is
        the honest half: enough to know a cog is trapped, not enough to
        say which gag is under it.
        """
        return tuple(do_id for do_id, char
                     in zip(self.suits, self.suit_traps) if char != "9")


def parse_members(value) -> Optional[Members]:
    """A `setMembers` value as a `Members`, or None if it is not one."""
    if not isinstance(value, (tuple, list)) or len(value) != 12:
        return None
    try:
        suits = tuple(int(x) for x in value[0])
        toons = tuple(int(x) for x in value[6])
    except (TypeError, ValueError):
        return None

    def text(raw) -> str:
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw).decode("latin-1", "replace")
        return "" if raw is None else str(raw)

    return Members(suits, text(value[1]), text(value[2]), text(value[3]),
                   text(value[4]), text(value[5]), toons,
                   text(value[7]), text(value[8]), text(value[9]),
                   text(value[10]), int(value[11]))


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
        # cog doId -> (Lure level, the round it was thrown in). See
        # `_note_chosen_attacks` and `lure_age`.
        self.chosen_lures: Dict[int, Tuple[int, int]] = {}
        # battle doId -> how many movies it has played. A round is one
        # movie, so this counts rounds. See `_note_state`.
        self.battle_rounds: Dict[int, int] = {}

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

    def refresh_battle_members(self) -> int:
        """Ask about every doId a battle names in `setMembers`.

        THE MISSING LINK, and the reason a live capture showed a battle
        with one suit in its roster and `cogs: 0` in the store. Cogs are
        generated long before the fight -- they walk the street first --
        so the listener has usually never seen a field update for them,
        and `refresh_all` only asks about objects it already knows.

        The battle itself is the thing that says which cogs matter, so
        reading its roster and asking about those doIds directly is what
        closes the loop.
        """
        asked = 0
        for battle in self.battles():
            members = parse_members(battle.get("setMembers"))
            if members is None:
                continue
            for do_id in tuple(members.suits) + tuple(members.toons):
                self.refresh(do_id)
                asked += 1
        return asked

    def members(self) -> Optional[Members]:
        """The roster of the battle in progress, if there is exactly one.

        More than one battle is on the cluster whenever another toon is
        fighting elsewhere in the district, so this deliberately refuses
        to choose between them -- picking the wrong one would advise on
        somebody else's fight.
        """
        battles = self.battles()
        if len(battles) != 1:
            return None
        return parse_members(battles[0].get("setMembers"))

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

    def _note_chosen_attacks(self, battle_do_id: int, value) -> None:
        """Remember which Lure gag was thrown at which cog.

        `setMembers` says a cog IS lured and never which gag did it, and
        the solver cannot use a lure without that: `lure_can_expire_early`
        keys off the gag's level, so a cog marked lured with no level
        raises the moment the search touches it.

        `setChosenToonAttacks(toonIds, tracks, levels, targets, ...)` is
        the only thing that says. Targets are indices into the battle's
        suit roster, so the roster has to be read at the same time --
        cogs die and the indices shift.

        Only Lure is kept. Everything else the solver reads from state
        rather than from intent, and intent is the weaker source: a
        chosen attack is what a toon MEANT to do, and it may miss.
        """
        if not isinstance(value, (tuple, list)) or len(value) < 4:
            return
        battle = self.store.get(battle_do_id)
        members = parse_members(battle.get("setMembers")) if battle else None
        if members is None:
            return
        _toons, tracks, levels, targets = value[0], value[1], value[2], value[3]
        lure_index = DC_TRACK_ORDER.index("lure")
        for track, level, target in zip(tracks, levels, targets):
            if int(track) != lure_index:
                continue
            index = int(target)
            if 0 <= index < len(members.suits):
                # Levels are 0-based on the wire and 1-based everywhere
                # in this project.
                self.chosen_lures[members.suits[index]] = (
                    int(level) + 1, self.battle_rounds.get(battle_do_id, 0))

    def _note_state(self, battle_do_id: int, value) -> None:
        """Count rounds by watching the battle's state machine.

        A round is one movie: the toons choose, the movie plays, the
        next round begins. `setState` walks that cycle, so counting
        entries into the movie state counts rounds -- which is the only
        way to know how much of a Lure is left, since NOTHING in the DC
        carries lure duration. The whole 165KB file mentions "lure"
        nowhere outside `setMembers`' untyped slots: it is AI-side state
        and is never distributed.
        """
        name = value[0] if isinstance(value, (tuple, list)) and value else value
        if isinstance(name, (bytes, bytearray)):
            name = bytes(name).decode("latin-1", "replace")
        if name == MOVIE_STATE:
            self.battle_rounds[battle_do_id] = (
                self.battle_rounds.get(battle_do_id, 0) + 1)

    def lure_age(self, cog_do_id: int) -> Optional[Tuple[int, int]]:
        """(Lure level, rounds since it was thrown), or None.

        None means this reader did not see the Lure land, which is the
        case whenever it attached mid-fight.
        """
        entry = self.chosen_lures.get(cog_do_id)
        if entry is None:
            return None
        level, thrown_in = entry
        battles = self.battles()
        if len(battles) != 1:
            return None
        now = self.battle_rounds.get(battles[0].do_id, thrown_in)
        return level, max(0, now - thrown_in)

    def _record(self, do_id: int, field, value) -> None:
        name = field.getName()
        if name == "setChosenToonAttacks":
            self._note_chosen_attacks(do_id, value)
        elif name == "setState":
            self._note_state(do_id, value)
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
        members = parse_members(battle.get("setMembers"))
        if members is not None:
            lines.append(f"    toons {members.toon_count} "
                         f"(allies {members.allies_standing}) "
                         f"{list(members.toons)}")
            lines.append(f"    suits {list(members.suits)} "
                         f"active={members.suits_active!r} "
                         f"lured={members.suits_lured!r} "
                         f"traps={members.suit_traps!r}")

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
            listener.refresh_battle_members()
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
