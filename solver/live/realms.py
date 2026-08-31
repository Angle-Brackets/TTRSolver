"""Reading a live battle from Toontown Realms' local Astron cluster.

Realms (what Toontown Offline became) ships a full Astron server on the
player's own machine, and every value the screen readers infer from
pixels is published there as a typed field: cog identity, exact HP,
laff, the pouch. This module subscribes to that stream via the Message
Director -- the designed extension point every AI/UberDOG process uses
-- and keeps an object store from it. READ-ONLY: it sends two control
messages (name itself, subscribe) plus `GET_ALL` queries, and never an
object update or a command.

NOT a source of game data: Realms is Toontown Online lineage and its
balance is frozen where TTR's moved on (its level 12 has 200 HP, TTR's
has 196 -- see `docs/realms.md`). Nothing read here may reach
`solver/data/`, fit a weight, or score a policy. It IS good for proving
the reader right -- whether `build_state` turns a `setHP` into the
correct `CogState.hp` doesn't depend on which game's balance is live,
and that's better ground truth than a screenshot.

Needs panda3d (`requirements-realms.txt`); `solver/live/__init__` must
not import this module, and tests skip rather than fail when it's
missing, matching `vision.py`'s arrangement with numpy.

Debugging history, wrong diagnoses and wire-format dead ends:
`docs/live-notes.md#solverliverealmspy`.
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

# State server message types, from Astron's own numbering. SIX OF THESE
# WERE WRONG in an earlier guessed numbering (2007, 2060, 2064-2067
# invented; 2060 was really SET_OWNER, so an ownership change was
# applied as a relocation). [CONFIRMED] below means it decoded to a real
# class/field on a live capture -- 2020 carried every one of 567
# datagrams in the first live capture as SET_FIELD, and 2014/2015 round
# tripped a GET_ALL query into a full object. `_unknown` counts anything
# else, so a still-wrong number shows up as a count rather than silence.
# See `docs/live-notes.md#state-server-message-numbering-six-of-the-constants-were-wrong`.
OBJECT_GET_ALL = 2014                   # [CONFIRMED] live
OBJECT_GET_ALL_RESP = 2015              # [CONFIRMED] live
OBJECT_SET_FIELD = 2020                 # [CONFIRMED] live
OBJECT_SET_FIELDS = 2021                # [CONFIRMED] live
OBJECT_DELETE_RAM = 2032
OBJECT_CHANGING_LOCATION = 2041
# [CONFIRMED] live: in one fight, 2042/2043/2052 delivered 34 objects
# between them (DistributedBattle, DistributedSuit, DistributedToon),
# every dclass id resolving to a real class. These three are what a
# battle and the player's own toon arrive on, and nothing else
# announces them.
OBJECT_ENTER_LOCATION_WITH_REQUIRED = 2042      # [CONFIRMED] live
OBJECT_ENTER_LOCATION_WITH_REQUIRED_OTHER = 2043    # [CONFIRMED] live
OBJECT_ENTER_AI_WITH_REQUIRED = 2052            # [CONFIRMED] live
OBJECT_ENTER_AI_WITH_REQUIRED_OTHER = 2053
OBJECT_ENTER_OWNER_WITH_REQUIRED = 2062
OBJECT_ENTER_OWNER_WITH_REQUIRED_OTHER = 2063

ENTER_MESSAGES = (OBJECT_ENTER_LOCATION_WITH_REQUIRED,
                  OBJECT_ENTER_LOCATION_WITH_REQUIRED_OTHER,
                  OBJECT_ENTER_AI_WITH_REQUIRED,
                  OBJECT_ENTER_AI_WITH_REQUIRED_OTHER,
                  OBJECT_ENTER_OWNER_WITH_REQUIRED,
                  OBJECT_ENTER_OWNER_WITH_REQUIRED_OTHER)

# 2040 and 2046 are NOT enter messages, despite arriving once per
# object like one: parsed as ENTER they delivered ZERO objects across a
# whole fight (vs. 34 for 2042/2043/2052), and `_enter` refused every
# one because the dclass id did not resolve. Left unparsed deliberately
# -- almost certainly SET_LOCATION (2040) and a GET_LOCATION reply
# (2044/2046 arrive together) -- and counted in `_unknown`. See
# `docs/live-notes.md#2040-and-2046-are-not-enter-messages`.
PROBE_ENTER = ()

# The ..._OTHER forms carry a trailing block of non-required fields.

ENTER_WITH_OTHER = (OBJECT_ENTER_LOCATION_WITH_REQUIRED_OTHER,
                    OBJECT_ENTER_AI_WITH_REQUIRED_OTHER,
                    OBJECT_ENTER_OWNER_WITH_REQUIRED_OTHER)

# The classes a battle is assembled from.
COG_CLASSES = ("DistributedSuitBase", "DistributedSuit",
               "DistributedFactorySuit", "DistributedMintSuit",
               "DistributedStageSuit", "DistributedTutorialSuit")
# `DistributedBattleBase` leads this list for the same reason
# `DistributedSuitBase` leads COG_CLASSES: a SET_FIELD names no class,
# so the object is tagged with the class its field was declared on
# (`setState`/`setMembers` are on the base), and omitting it meant a
# battle learned from the live stream (rather than via ENTER) matched
# nothing here. See `docs/live-notes.md#battle_classes-distributedbattlebase-has-to-lead-the-list`.
BATTLE_CLASSES = ("DistributedBattleBase",
                  "DistributedBattle", "DistributedBattleBldg",
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

    `.dc` field numbering is the wire contract and is NOT declaration
    order -- a hand-rolled parser that assumed so put
    `DistributedSuit.setPathPosition` at 492 and decoded live cog
    traffic as `DistributedPlayer.setDISLname`. panda3d's `DCFile` is
    the parser the game itself uses, so it's right by construction.
    See `docs/live-notes.md#dcindex-use-the-games-own-parser-and-guard-dclass`.
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

    def dclass(self, dclass_id: int):
        """A class by index, or None. GUARDED, because panda3d ASSERTS.

        `getFieldByIndex` returns None for a bad index; `getClass` fails
        a C++ assertion and takes the thread with it -- an out-of-range
        id off the wire once killed the reader this way. Bounds are
        checked here, once, rather than at each call site.
        """
        if not isinstance(dclass_id, int):
            return None
        if dclass_id < 0 or dclass_id >= self._dc.getNumClasses():
            return None
        return self._dc.getClass(dclass_id)

    def class_name(self, dclass_id: int) -> str:
        dclass = self.dclass(dclass_id)
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
        dclass = self.dclass(dclass_id)
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
        # single-argument field like setHP comes back as `(6,)`, not
        # `6`. Unwrap the common case; setMembers/setState keep their
        # tuple since they take several arguments.
        if isinstance(value, (tuple, list)) and len(value) == 1:
            return consumed, value[0]
        return consumed, value


# ---------------------------------------------------------------------
# The object store
# ---------------------------------------------------------------------

class LiveObject:
    __slots__ = ("do_id", "dclass", "parent", "zone", "fields", "streamed")

    def __init__(self, do_id: int, dclass: str = "",
                 parent: int = 0, zone: int = 0):
        self.do_id = do_id
        self.dclass = dclass
        self.parent = parent
        self.zone = zone
        self.fields: Dict[str, object] = {}
        # Fields the STREAM has delivered at least once. A query reply
        # may refresh anything not in here and must never touch what is.
        self.streamed: set = set()

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

    def enter(self, do_id, dclass, parent, zone, fields,
              fill_only: bool = False) -> LiveObject:
        """Record an object's arrival.

        `fill_only=True` (a QUERY reply) writes only fields not already
        held. A `GET_ALL` answer is stale by the time it lands, and
        applying it wholesale REVERTED values the live stream had since
        delivered -- with the roster re-queried every poll, a cog's HP
        was overwritten with a pre-hit snapshot twice a second, reading
        as health stuck a round behind. The stream is authority, the
        query is the bootstrap. See
        `docs/live-notes.md#objectstoreenter-and-the-fill_only-rule`.
        """
        with self._lock:
            obj = self._touch(do_id)
            obj.dclass, obj.parent, obj.zone = dclass, parent, zone
            if fill_only:
                # `setInventory` is `ownrecv`: the pouch goes to the
                # owning client, not a listener, so a query is the ONLY
                # way it's ever seen. Filling it once and never again
                # left the solver planning with session-start gags,
                # worse than the stale HP this rule prevents.
                for name, value in fields.items():
                    if name not in obj.streamed:
                        obj.fields[name] = value
            else:
                obj.fields.update(fields)
                obj.streamed.update(fields)
            return obj

    def set_field(self, do_id, name, value,
                  streamed: bool = True) -> LiveObject:
        with self._lock:
            obj = self._touch(do_id)
            obj.fields[name] = value
            if streamed:
                obj.streamed.add(name)
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

# Cog code to our own key. [OPEN TOONTOWN SOURCE] -- a NAMING map, not
# game data, so it is exempt from the ban on Realms numbers reaching
# `solver/data/`. sc/cc/f/pp/dt are [CONFIRMED BY OBSERVATION] from live
# captures; mh/nd/gh/ms/m/cc are confirmed from the game's own data
# pack, which prints them beside the localiser key (e.g. 'mh' next to
# #SuitMrHollywood). Unknown code returns None rather than a guess. See
# `docs/live-notes.md#suit-dna`.
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

    IT IS THE LEVEL MINUS ONE, not an offset into the cog's own range --
    the two agree for any cog whose range starts at 1, which is what
    makes them easy to confuse. Discriminated against our own HP table:

        Penny Pincher dist 1, hp 12 -> level 2 (range starts at 2,
                                                 an offset would be 0)
        Double Talker dist 2, hp 20 -> level 3 (range starts at 3,
                                                 offset would be 0)

    Both say `level = dist + 1`. Full 4-reading writeup:
    `docs/live-notes.md#cog_level-its-the-level-minus-one-not-a-range-offset`.
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
# WRITTEN OUT RATHER THAN TAKEN FROM `Track`'s DECLARATION ORDER: that
# would couple the wire format to an unrelated file's member order, and
# reordering the enum would silently shift every gag count by one
# track. The wire order is a property of the game, stated here. See
# `docs/live-notes.md#track-order-is-written-out-not-taken-from-the-enum`.
DC_TRACK_ORDER = ("toon_up", "trap", "lure", "sound",
                  "throw", "squirt", "drop")

INVENTORY_LEVELS = 7


def _track(name: str):
    from ..state import Track

    return Track(name)


def parse_inventory(blob) -> Optional[Dict]:
    """`setInventory` as {(Track, level): count}, or None.

    A uint16 length then seven rows of seven bytes (track x level),
    holding the count carried. Verified against a real toon: the
    Toon-Up row was all zeros and that toon's `setTrackAccess[0]` was 0,
    an independent way of saying the same thing. Levels are 1-based here
    to match the rest of the project -- `gag_counts[(Track.TRAP, 6)]` is
    TNT.
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


# `setResistanceMessages` ids are `category * 100 + index`, and the
# categories are the SpeedChat "Unites" menu in its own order.
#
# [OWNER] from the in-game menu, which reads Toon-Up, Gag-Up,
# Jellybeans, Toon-Down. This was left undecoded until that screenshot,
# because nothing in the install names them -- the only "resistance"
# files in the archives are three particle effects -- and the entry
# counts alone were not evidence.
#
# They do corroborate it, though, which is why this is a reading rather
# than a guess: category 0 holds exactly 5 ids and `TOON_UP_VALUES` has
# exactly 5 values, and category 1 holds exactly 8, which is the seven
# gag tracks plus all-tracks.
RESISTANCE_CATEGORIES = {0: "toon_up", 1: "gag_up",
                         2: "jellybeans", 3: "toon_down"}

# The Gag-Up submenu, in its own order. [OWNER] from the in-game menu:
# Toon-Up, Trap, Lure, Sound, Throw, Squirt, Drop, All -- which is
# Toontown's canonical track order followed by all-tracks, and is what
# makes index 107 "All" rather than an eighth track.
GAG_UP_TRACKS = {0: "toon_up", 1: "trap", 2: "lure", 3: "sound",
                 4: "throw", 5: "squirt", 6: "drop", 7: None}

# [OWNER] from the in-game menu: 100, 200, 350, 600. Recorded because it
# confirms category 2 is money and nothing else; the solver has no use
# for it, and a battle cannot spend one.
JELLYBEAN_VALUES = (100, 200, 350, 600)

# The two the solver models.
#
# Jellybeans buy nothing in a battle. **Toon-Down is CUSTOM TO REALMS**
# -- [OWNER] "Toon-Down is custom, don't implement it" -- so it is not
# merely unmodelled, it does not exist in the game this solver is for.
#
# That makes the whole category table REALMS-SPECIFIC, and it must not
# be carried across to TTR. A build that invents a category is exactly
# the lineage hazard docs/realms.md is about: this decodes a reader's
# wire format, and says nothing about what TTR offers.
BATTLE_UNITES = ("toon_up", "gag_up")


def parse_resistance(value) -> Optional[Dict[str, int]]:
    """`setResistanceMessages` as {category name: count}, or None.

    Unknown categories are kept under their number, so a build that
    adds one shows up as a surprise rather than vanishing quietly.
    """
    if value is None:
        return None
    out: Dict[str, int] = {}
    try:
        for row in value:
            if len(row) < 2:
                return None
            ident, count = int(row[0]), max(0, int(row[1]))
            name = RESISTANCE_CATEGORIES.get(ident // 100, str(ident // 100))
            out[name] = out.get(name, 0) + count
    except (TypeError, ValueError):
        return None
    return out


def battle_unites(value) -> Optional[int]:
    """How many unites the toon holds that a BATTLE can spend, or None.

    Toon-Up and Gag-Up only. This used to be the grand total, which
    counted Jellybeans and Toon-Down as if they were unites the search
    could play -- on the captured toon that read 3994 where the
    spendable figure is 3993 across two categories, and on a normal toon
    it would be wrong by whatever jellybean unites they happen to carry.
    """
    parsed = parse_resistance(value)
    if parsed is None:
        return None
    return sum(parsed.get(kind, 0) for kind in BATTLE_UNITES)


def gag_up_tracks(value) -> Optional[Dict[Optional[str], int]]:
    """Which Gag-Up unites are held, as {track name or None: count}.

    None is the all-tracks unite. Returns None if the field is absent.

    Not consumed by anything yet, and that is deliberate:
    `ToonState.unites_held` is a single number, so the search cannot ask
    "do I hold a Lure restock". This decodes what the wire says so the
    gap is a modelling choice rather than a missing reading.
    """
    if value is None:
        return None
    out: Dict[Optional[str], int] = {}
    try:
        for row in value:
            ident, count = int(row[0]), max(0, int(row[1]))
            if ident // 100 != 1 or count <= 0:
                continue
            index = ident % 100
            if index not in GAG_UP_TRACKS:
                continue
            key = GAG_UP_TRACKS[index]
            out[key] = out.get(key, 0) + count
    except (TypeError, ValueError, IndexError):
        return None
    return out


def npc_names(override: Optional[str] = None) -> Dict[int, str]:
    """NPC id -> name, from the install's own `npctoons.json`.

    SOS cards are NPC friends: `setNPCFriendsDict` is a list of
    (npc_id, count). The table lives in `phase_3/data/npctoons.json`
    inside `ttrm_dat_01.pak`.

    READ FROM THE INSTALL, never vendored. It is Realms data and so
    Toontown Online lineage, which must not reach `solver/data/` -- see
    docs/realms.md. Here it is the reader decoding an id, the same job
    `parse_inventory` does for a pouch.
    """
    import json

    from panda3d.core import Filename, Multifile

    root = install_dir(override) / "resources" / "default"
    out: Dict[int, str] = {}
    for pak in sorted(root.glob("ttrm_dat_*.pak")):
        mf = Multifile()
        if not mf.openRead(Filename.fromOsSpecific(str(pak))):
            continue
        index = mf.findSubfile("phase_3/data/npctoons.json")
        if index < 0:
            continue
        try:
            table = json.loads(bytes(mf.readSubfile(index)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        for key, row in table.items():
            name = row.get("name") if isinstance(row, dict) else None
            if name:
                try:
                    out[int(key)] = name
                except (TypeError, ValueError):
                    continue
    return out


def parse_npc_friends(value, names: Optional[Dict[int, str]] = None
                      ) -> Optional[Dict[str, int]]:
    """`setNPCFriendsDict` as {card name: count}, or None.

    Ids the table does not name are DROPPED rather than guessed at. An
    unnamed card cannot be matched to `sos.BY_NAME` anyway, and a card
    the solver cannot identify must not become one it can.
    """
    if value is None:
        return None
    if names is None:
        try:
            names = npc_names()
        except Exception:               # noqa: BLE001 - reader, not truth
            names = {}
    out: Dict[str, int] = {}
    try:
        for row in value:
            npc_id, count = int(row[0]), int(row[1])
            name = names.get(npc_id)
            if name and count > 0:
                out[name] = out.get(name, 0) + count
    except (TypeError, ValueError, IndexError):
        return None
    return out


def parse_track_access(values) -> Optional[frozenset]:
    """`setTrackAccess` as the set of tracks the toon owns.

    Seven flags in `DC_TRACK_ORDER`. A toon with [0, 1, 1, 1, 1, 1, 1]
    has no Toon-Up -- a real and awkward loadout, not a misread.
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
    otherwise the level the bonus reaches. THE LEVEL IS 0-BASED AND 6
    MEANS THE WHOLE TRACK, per the owner -- confirmed by a real toon
    reading [-1, -1, -1, -1, 6, -1, -1] (Throw organic, all seven
    levels). This project treats organic as a property of the whole
    track (`ToonState.organic_tracks`, matching how TTR works), so any
    non-negative entry makes the track organic and the level is dropped.

    Realms' organic is NOT the same bonus as TTR's -- flat +10% damage
    there vs. a per-track bonus that also raises Lure accuracy here
    (`Gag.organic_damage`) -- so this reads WHICH tracks are organic and
    the solver prices them by TTR's rules; a damage number predicted
    here will not match what Realms rolls. See `docs/realms.md` and
    `docs/live-notes.md#parse_inventory-parse_track_access-parse_organic`.
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

    Twelve untyped-looking slots --

        setMembers(uint32[], string, string, string, string, string,
                   uint32[], string, string, string, string, int16)

    -- Toontown's long-standing shape: suits and their four state
    strings, then toons and theirs, then a timestamp. Observed live as
    `([401005039], '', '', '0', '', '9', [100000001], '', '', '0', '',
    -23220)`, one cog and one toon, a solo street battle. `suits` and
    `toons` are what this project needs; `toons` gives the party size
    (`BattleState.allies_standing`).

    THE STATE STRINGS ARE TWO DIFFERENT ENCODINGS. `traps` is one
    character per suit; `active` and `lured` are INDICES of suits in
    that state, not per-suit flags -- a two-cog capture with the first
    lured read `active='01' lured='0' traps='99'`, and one lured cog out
    of two giving `'0'` only makes sense as an index (a per-suit
    encoding would give `'10'`). Reading `lured` as one-char-per-suit
    would mark the wrong cog asleep, in a solver where Lure is the pivot
    of every Trap line. Full writeup, including why a single-cog capture
    didn't discriminate: `docs/live-notes.md#members--setmembers`.
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
        """doIds of cogs with a trap under them."""
        return tuple(do_id for do_id, _level in self.traps().items())

    def traps(self) -> Dict[int, int]:
        """{cog doId: trap gag level}, from the roster's own slots.

        ONE CHARACTER PER SUIT, the trap gag's 0-BASED LEVEL rather than
        a flag -- '9' is the no-trap sentinel (only seven trap levels,
        so 0-6 are real and 9 cannot collide). [CONFIRMED] live: a
        trapped Money Bags read '4' (decodes to level 5, Trapdoor; owner
        confirmed that's what was thrown).

        THE ROSTER DOES REFRESH -- this module used to claim `setMembers`
        only re-broadcasts on membership change, so a mid-round trap
        would never appear. Wrong: the slot updates with the cog still
        in the fight. `chosen_traps` (from `setChosenToonAttacks`) stays
        as a fallback for when a stale roster and a fresh observation
        disagree, but the roster is authoritative. See
        `docs/live-notes.md#members--setmembers`.
        """
        out: Dict[int, int] = {}
        for do_id, char in zip(self.suits, self.suit_traps):
            if not char.isdigit():
                continue
            index = int(char)
            if 0 <= index <= 6:         # seven trap levels; 9 means none
                out[do_id] = index + 1
        return out


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
        # msgtype -> count, for everything `handle` does not recognise.
        # A wrong constant then shows up as a number rather than as
        # silence, which is how six of them survived unnoticed.
        self._unknown: Dict[int, int] = {}
        # msgtype -> how many objects it successfully delivered, and
        # which classes. This is how an unrecognised number gets
        # identified without dumping payloads: an ENTER parse that
        # resolves to a real class is evidence, one that does not is
        # counted as undecoded.
        self._entered: Dict[int, int] = {}
        self._entered_classes: Dict[int, set] = {}
        # How many `setChosenToonAttacks` arrived, and how many named a
        # Lure. Without these, "the Lure level is unknown" cannot be
        # told apart from "the field never arrived" -- and they need
        # opposite fixes.
        self.attacks_seen = 0
        self.lures_seen = 0
        self.traps_seen = 0
        # cog doId -> (trap level, round it was set). Recorded from the
        # chosen attacks, because `setMembers` will not say. See
        # `_note_chosen_attacks`.
        self.chosen_traps: Dict[int, Tuple[int, int]] = {}
        # battle doId -> the last movie applied, so the doubled
        # datagrams cannot deal their damage twice.
        self._last_movie: Dict[int, str] = {}
        # battle doId -> (level, round) of the last Lure thrown in it,
        # whatever it was aimed at. See `_note_chosen_attacks`.
        self.last_lure: Dict[int, Tuple[int, int]] = {}

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

        The stream carries only CHANGES: the first live run saw 944
        datagrams, decoded every one, and still reported `hp=None` for a
        cog standing in front of the player, because its `setHP` was in
        a generate message sent before the listener attached. Requiring
        attachment before the fight starts isn't workable, so this asks
        instead.

        Still a read: `OBJECT_GET_ALL` mutates no object, sends nothing
        to the client, and is answered on this listener's own private
        channel. See `docs/live-notes.md#realmslistenerrefresh-and-refresh_battle_members`.
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

        THE MISSING LINK: a live capture showed a battle with one suit
        in its roster and `cogs: 0` in the store, because cogs walk the
        street before the fight and `refresh_all` only re-asks about
        objects already known. The battle's own roster says which cogs
        matter, so this asks about those doIds directly.
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
            except Exception:           # noqa: BLE001
                # DELIBERATELY BROAD: one bad datagram must cost one
                # datagram, not the reader thread. A narrower tuple
                # (struct.error, IndexError, ValueError) missed panda3d's
                # AssertionError (a C++ out-of-range index), which
                # escaped and killed the thread, leaving the panel
                # frozen on a fight that had stopped updating.
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
            self._enter(body, with_other=msgtype in ENTER_WITH_OTHER,
                        msgtype=msgtype)
        elif msgtype == OBJECT_GET_ALL_RESP:
            # context, then exactly an ENTER payload, then the non-required
            # fields as (count, [id, value]...).
            # A QUERY REPLY, so it may only fill gaps. See
            # `ObjectStore.enter`.
            self._enter(body[4:], with_other=True, msgtype=msgtype,
                        fill_only=True)
        elif msgtype == OBJECT_DELETE_RAM:
            (do_id,) = struct.unpack_from("<I", body, 0)
            self.store.delete(do_id)
        elif msgtype == OBJECT_CHANGING_LOCATION:
            do_id, parent, zone = struct.unpack_from("<III", body, 0)
            self.store.relocate(do_id, parent, zone)
        elif msgtype in PROBE_ENTER:
            # UNDER INVESTIGATION, and self-validating: parsing an
            # unrecognised once-per-object message as ENTER either
            # resolves to a real dclass (in which case that's what it
            # is) or `_enter` declines and counts it -- a wrong guess
            # cannot enter the store.
            self._unknown[msgtype] = self._unknown.get(msgtype, 0) + 1
            self._enter(body, with_other=True, msgtype=msgtype)
        else:
            self._unknown[msgtype] = self._unknown.get(msgtype, 0) + 1

    def _note_chosen_attacks(self, battle_do_id: int, value) -> None:
        """Remember which Lure/Trap gag was thrown at which cog.

        `setMembers` says a cog IS lured and never which gag did it, and
        `lure_can_expire_early` keys off the gag's level -- a cog marked
        lured with no level raises the moment the search touches it.
        `setChosenToonAttacks(toonIds, tracks, levels, targets, ...)` is
        the only field that says. Targets are indices into the battle's
        suit roster, read at the same time since cogs die and indices
        shift.

        Only Lure and Trap are kept: everything else the solver reads
        from state, and intent (what a toon MEANT to do, which may miss)
        is the weaker source. See
        `docs/live-notes.md#_note_chosen_attacks-tracking-lure-and-trap-intent`.
        """
        if not isinstance(value, (tuple, list)) or len(value) < 4:
            return
        battle = self.store.get(battle_do_id)
        members = parse_members(battle.get("setMembers")) if battle else None
        if members is None:
            return
        _toons, tracks, levels, targets = value[0], value[1], value[2], value[3]
        lure_index = DC_TRACK_ORDER.index("lure")
        trap_index = DC_TRACK_ORDER.index("trap")
        now = self.battle_rounds.get(battle_do_id, 0)
        for track, level, target in zip(tracks, levels, targets):
            if int(track) == trap_index:
                # A trap always targets exactly ONE cog (no group Trap),
                # so unlike Lure the target index is always a real slot
                # and no battle-wide fallback is needed. See doc pointer
                # above for why `setMembers` alone isn't enough here.
                self.traps_seen += 1
                index = int(target)
                if 0 <= index < len(members.suits):
                    self.chosen_traps[members.suits[index]] = (
                        int(level) + 1, now)
                continue
            if int(track) != lure_index:
                continue
            self.lures_seen += 1
            # Levels are 0-based on the wire and 1-based everywhere in
            # this project.
            found = (int(level) + 1, now)

            # BATTLE-WIDE FALLBACK: a GROUP Lure's `target` is a sentinel
            # rather than a slot, so keying only on the slot missed group
            # Lures entirely -- see doc pointer above.
            self.last_lure[battle_do_id] = found

            index = int(target)
            single = 0 <= index < len(members.suits)
            if single:
                self.chosen_lures[members.suits[index]] = found

            # A LURE SPENDS A TRAP: clear any trap held for the cogs it
            # reaches (all of them for a group Lure), on the LURE rather
            # than on the cog appearing lured -- a cog dragged onto its
            # own trap wakes and never appears in `suits_lured` at all.
            # DELIBERATELY CONSERVATIVE: a Lure that misses still clears
            # the trap here, which under-claims rather than over-claims
            # a combo. See doc pointer above.
            reached = ([members.suits[index]] if single
                       else list(members.suits))
            for do_id in reached:
                self.chosen_traps.pop(do_id, None)

    def apply_movie(self, battle_do_id: int, value) -> int:
        """Subtract a round's damage from the cogs, from `setMovie`.

        The server writes `setHP` at COMMIT time to the HP going INTO
        that round -- a round's damage only reaches the state server at
        the NEXT commit (confirmed live: HP 90 at one commit, 61 at the
        next, every gag in between having hit). That leaves the panel a
        round stale exactly during `WaitForInput`, while the player
        chooses, and no amount of re-querying fixes it.

        `setMovie` (`required broadcast ram`) carries the round's
        resolution and arrives WITH the commit, before the animation
        plays, so applying it moves the reader from a round behind to
        slightly ahead. Safe because `setHP` is ABSOLUTE: the real value
        at the next commit overwrites this rather than compounding with
        it -- a forward correction the server later confirms. See
        `docs/live-notes.md#apply_movie-correcting-for-stale-hp-and-the-doubled-datagram`.
        """
        if not isinstance(value, (list, tuple)) or len(value) < 5:
            return 0
        made, _toons, suits, toon_attacks, _suit_attacks = value[:5]
        if not made:
            return 0

        # EVERY DATAGRAM ARRIVES TWICE -- a full-range subscription
        # matches both an object's own channel and its location channel
        # -- so without this the damage would be applied twice and every
        # cog would die at half health.
        fingerprint = repr(value)
        if self._last_movie.get(battle_do_id) == fingerprint:
            return 0
        self._last_movie[battle_do_id] = fingerprint

        active = [int(x) for x in (suits or ())]
        applied = 0
        for attack in toon_attacks or ():
            if len(attack) < 5:
                continue
            _i, track, _level, target, hp = attack[:5]
            if int(track) < 0:
                continue
            damage = [int(x) for x in (hp or ())]
            if not any(damage):
                continue

            if len(damage) == 1 and int(target) in active:
                hits = [(int(target), damage[0])]
            elif len(damage) == len(active):
                # A group gag: one entry per active suit, in order.
                hits = list(zip(active, damage))
            else:
                # Some other shape. Rather than guess at it, leave the
                # HP to the server's own next write.
                continue

            for do_id, amount in hits:
                if amount <= 0:
                    continue
                obj = self.store.get(do_id)
                if obj is None:
                    continue
                current = obj.get("setHP")
                if current is None:
                    continue
                self.store.set_field(do_id, "setHP",
                                     max(0, int(current) - amount))
                applied += 1
        return applied

    def _note_state(self, battle_do_id: int, value) -> None:
        """Count rounds by watching the battle's state machine.

        A round is one movie (toons choose, movie plays, next round
        begins); `setState` walks that cycle, so counting entries into
        the movie state counts rounds. This is the only way to know how
        much of a Lure is left -- the whole 165KB `.dc` file mentions
        "lure" nowhere outside `setMembers`'s untyped slots, since lure
        duration is AI-side state and is never distributed.
        """
        name = value[0] if isinstance(value, (tuple, list)) and value else value
        if isinstance(name, (bytes, bytearray)):
            name = bytes(name).decode("latin-1", "replace")
        if name == MOVIE_STATE:
            self.battle_rounds[battle_do_id] = (
                self.battle_rounds.get(battle_do_id, 0) + 1)

    def trap_on(self, cog_do_id: int) -> Optional[int]:
        """The level of the Trap under a cog, or None.

        Prefers `setMembers`, which is authoritative when it is fresh: a
        slot that is not '9' means the server says there is a trap
        there, and if that ever disagrees with what we watched being
        thrown then the server wins.

        Otherwise the observed choice. Cleared when the cog is lured,
        because that is what springs a trap -- keeping it would have the
        solver plan a combo whose damage has already been collected.
        """
        battles = self.battles()
        if len(battles) != 1:
            return None
        members = parse_members(battles[0].get("setMembers"))
        if members is None:
            return None

        if cog_do_id in members.lured_suits():
            # Lured and still standing means the Lure found no trap
            # here; a trapped cog springs it and wakes. Either way there
            # is nothing under this one now.
            self.chosen_traps.pop(cog_do_id, None)
            return None
        # THE ROSTER WINS: it's the server's own answer and names the
        # gag, where watched-attacks only knows what was aimed.
        from_roster = members.traps().get(cog_do_id)
        if from_roster is not None:
            return from_roster
        # UNVERIFIED, HAS NEVER FIRED: a live capture had `traps_seen ==
        # 2` and stored neither, so `setChosenToonAttacks`'s target is
        # evidently not a Trap roster slot the way it is for Lure. Left
        # in place since it's free and the roster wins anyway -- see
        # `docs/live-notes.md#trap_on--lure_age`.
        entry = self.chosen_traps.get(cog_do_id)
        return None if entry is None else entry[0]

    def lure_age(self, cog_do_id: int) -> Optional[Tuple[int, int]]:
        """(Lure level, rounds since it was thrown), or None.

        None means this reader did not see the Lure land, which is the
        case whenever it attached mid-fight.
        """
        battles = self.battles()
        if len(battles) != 1:
            return None
        entry = self.chosen_lures.get(cog_do_id)
        if entry is None:
            # Fall back to the last Lure thrown in this battle: right
            # for a group Lure and a solo fight; wrong only for two
            # different Lure levels in one round in a party, which can't
            # be searched yet anyway.
            entry = self.last_lure.get(battles[0].do_id)
        if entry is None:
            return None
        level, thrown_in = entry
        now = self.battle_rounds.get(battles[0].do_id, thrown_in)
        return level, max(0, now - thrown_in)

    def _record(self, do_id: int, field, value) -> None:
        name = field.getName()
        if name == "setChosenToonAttacks":
            self.attacks_seen += 1
            self._note_chosen_attacks(do_id, value)
        elif name == "setState":
            self._note_state(do_id, value)
        elif name == "setMovie":
            self.apply_movie(do_id, value)
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

    def _enter(self, body: bytes, with_other: bool = False,
               msgtype: int = 0, fill_only: bool = False) -> None:
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
        if self.index.dclass(dclass_id) is None:
            # Not an ENTER after all, or one we mis-sliced. Committing
            # it would put an object named "<60000>" in the store and
            # make a wrong guess look like a discovery.
            self.undecoded += 1
            return
        obj = self.store.enter(do_id, self.index.class_name(dclass_id),
                               parent, zone, fields, fill_only=fill_only)
        self._notify("<enter>", obj)
        self._entered[msgtype] = self._entered.get(msgtype, 0) + 1
        self._entered_classes.setdefault(msgtype, set()).add(obj.dclass)

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
