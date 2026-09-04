"""Client for Toontown Rewritten's Local (Companion App) API.

TTR's own client can serve read-only JSON about your toon over HTTP on
localhost, once you switch it on in the game's options. It is official and
consent-gated: the game shows a prompt naming the `User-Agent` you send,
and you accept it in-game before anything is handed over.

WHAT THIS CAN AND CANNOT DO
---------------------------
It cannot see the battle. There is no endpoint for the cogs you are
fighting, their levels, their health, or whose turn it is -- every
plausible name (`/battle.json`, `/combat.json`, `/cogs.json`, ...) returns
404, and the seventeen that exist are about your toon and the world, not
the fight. That looks deliberate rather than accidental: the API is gated
behind a consent prompt precisely because TTR decided what third parties
may read, and live combat is on the other side of that line.

So this fills in the half of the solver's setup that is about *you*:

  laff            exact, current and max
  gag tracks      which are unlocked, to what level, and whether organic
  location        zone / neighborhood / district
  invasion        what is invading your district, if anything

The cogs you are facing still have to be entered by hand.

One further gap: `/gags.json` reports the highest level unlocked in each
track and its experience, but *not how many of each gag you are carrying*.
So this narrows the picker to gags you could legally hold and gets organic
right; the counts remain yours to set. `available_gags()` returns the
former and says nothing about the latter, deliberately -- inventing counts
here would be exactly the kind of plausible-looking stand-in the project
rules out.

PROTOCOL TRAPS
--------------
Two things will silently defeat you, both learned the hard way:

- The `Host` header must be `localhost:<port>`. Sending `127.0.0.1:1547`
  or `[::1]:1547` does not produce an error -- the server drops the
  connection with no response at all, which reads exactly like the game
  not running. This is anti-DNS-rebinding, and it is why every URL here
  is built with the literal hostname `localhost`.
- The API only listens once the setting is enabled in-game. Before that
  the port is closed, which again looks like "no game running".

`NotRunning` deliberately mentions both, because from the outside they are
indistinguishable.
"""
from __future__ import annotations

import json
import secrets
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..state import Track

# 1547 is the default; the client walks upwards when a port is taken so
# that several simultaneous toons each get their own server.
PORTS = tuple(range(1547, 1553))

DEFAULT_USER_AGENT = "TTRSolver (Toontown battle advisor)"

# Generous on purpose. The first request bearing a given Authorization
# token costs about three seconds against a live client -- measured at
# 2.9s, versus 1.8ms once the same token has been seen before -- and if
# the game decides to raise its consent prompt, the request waits on a
# human. A tight timeout here fails in the most misleading way possible,
# looking exactly like the game not running.
DEFAULT_TIMEOUT = 30.0

# Port scanning is a different question and wants a short fuse.
PROBE_TIMEOUT = 0.3

# The API names tracks the way the game does; the solver uses an enum.
TRACK_NAMES: Dict[str, Track] = {
    "Toon-Up": Track.TOON_UP,
    "Trap": Track.TRAP,
    "Lure": Track.LURE,
    "Sound": Track.SOUND,
    "Throw": Track.THROW,
    "Squirt": Track.SQUIRT,
    "Drop": Track.DROP,
}

# The client pads three cog names (Micromanager, Bloodsucker,
# Telemarketer) with U+0003 so it can line-break them in speech bubbles.
# Each is one word with a control character wedged into the middle, so it
# has to be stripped before the name will match anything.
SOFT_BREAK = chr(3)


class LocalAPIError(RuntimeError):
    """Any failure talking to the Local API."""


class NotRunning(LocalAPIError):
    """Nothing is serving the Local API on any candidate port."""


class ConsentRequired(LocalAPIError):
    """The game answered, but has not been granted permission yet."""


@dataclass(frozen=True)
class Snapshot:
    """One read of a toon's live state."""

    name: str
    toon_id: str
    laff: int
    max_laff: int
    zone: str
    neighborhood: str
    district: str
    # Undocumented, and null out on the street. Present in the payload, so
    # it is carried through rather than dropped -- see `instance_id` in the
    # module notes.
    instance_id: Optional[str] = None
    invasion: Optional[Tuple[str, int, bool]] = None
    # track -> (highest level unlocked, organic?)
    tracks: Dict[Track, Tuple[int, bool]] = field(default_factory=dict)
    # Progress on the *toon's own* cog disguises -- nothing to do with the
    # cogs being fought. Department key ("c"/"l"/"m"/"s") -> (merits
    # earned, merits needed) for each suit owned. See `merits_gained`.
    merits: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    @property
    def loading(self) -> bool:
        """True while the client is between zones.

        Observed live: `location.zone` goes to the empty string for about
        a second during a zone transition, then fills in with the new
        zone. Anything that reacts to location has to ignore that window
        rather than treat it as "nowhere".
        """
        return not self.zone

    def merits_gained(self, previous: "Snapshot") -> Dict[str, int]:
        """Merits added to the toon's own disguises between two snapshots.

        This is the closest the Local API gets to noticing a battle, and
        it is a weak signal worth being honest about. It fires only for
        departments whose suit you already own, only for that
        department's cogs, and the amount reflects cog levels rather than
        how many were in the fight -- so it can say "a Sellbot fight just
        paid out" but never which cogs, how many, or whether you won
        cleanly. Observed going 0 -> 3 the moment a Sellbot street battle
        ended.
        """
        gained = {}
        for dept, (current, _target) in self.merits.items():
            before = previous.merits.get(dept)
            if before is not None and current > before[0]:
                gained[dept] = current - before[0]
        return gained

    def available_gags(self) -> List[Tuple[Track, int]]:
        """Every gag this toon has unlocked, as (track, level) pairs.

        This is what the toon *may* carry, not what it *is* carrying --
        the API does not expose per-gag counts.
        """
        # Iterating the enum, not sorting it: Track subclasses str, so
        # sorted() would order these alphabetically (lure before trap)
        # rather than in the game's canonical track order.
        return [(track, level)
                for track in Track if track in self.tracks
                for level in range(1, self.tracks[track][0] + 1)]

    def track_exp(self) -> Dict[Track, int]:
        """Highest gag unlocked per track, as `ToonState.track_exp` wants.

        This is not a formatting convenience -- it feeds accuracy. The
        wiki's formula is `atkAcc = propAcc + trackExp + tgtDef + bonus`,
        and trackExp is `(highest unlocked level - 1) * 10`, halved for
        Toon-Up. A toon trained to level 7 in a track is therefore
        carrying a flat +60 accuracy that a solver ignoring this would
        miss entirely.

        Note it keys off the highest gag *unlocked*, not the raw
        experience points in `/gags.json`'s `experience` field, which do
        not enter the calculation at all.
        """
        return {track: top for track, (top, _organic) in self.tracks.items()}

    def organic_tracks(self) -> List[Track]:
        return [track for track in Track
                if self.tracks.get(track, (0, False))[1]]

    @property
    def invasion_text(self) -> str:
        """The invasion as a person would say it, or "" for none.

        HERE RATHER THAN AT EACH CALLER. `invasion` is a
        `(cog, count, mega)` tuple, and the panel was rendering it with
        `str()` -- which put a raw Python repr on screen,
        `('Spin Doctors', 3000, False)`, over a live battle.
        """
        if not self.invasion:
            return ""
        cog, count, mega = self.invasion
        return f"{cog} x{count}{' (MEGA)' if mega else ''}"

    def describe(self) -> str:
        lines = [f"{self.name} ({self.toon_id})",
                 f"  laff      {self.laff}/{self.max_laff}",
                 f"  location  {self.zone}, {self.neighborhood} "
                 f"[{self.district}]"]
        if self.instance_id:
            lines.append(f"  instance  {self.instance_id}")
        if self.invasion:
            lines.append(f"  invasion  {self.invasion_text}")
        lines.append("  gags")
        for track in Track:
            entry = self.tracks.get(track)
            if entry is None:
                lines.append(f"    {track.value:8s} locked")
            else:
                top, organic = entry
                lines.append(f"    {track.value:8s} to level {top}"
                             f"{'  (organic)' if organic else ''}")
        return "\n".join(lines)


class TTRLocal:
    """A session against one running game client.

    `Authorization` is required to be random and unique per application
    session, so one is generated per instance and reused; the game ties
    its consent decision to it.
    """

    def __init__(self, port: Optional[int] = None,
                 user_agent: str = DEFAULT_USER_AGENT,
                 timeout: float = DEFAULT_TIMEOUT):
        self.user_agent = user_agent
        self.timeout = timeout
        self.token = secrets.token_hex(16)
        self.port = port if port is not None else _first_open_port()

    def fetch(self, endpoint: str) -> dict:
        """GET one endpoint and decode it, e.g. `fetch("laff")`."""
        # Built with the literal hostname so urllib sends
        # `Host: localhost:<port>`; see the module docstring.
        url = f"http://localhost:{self.port}/{endpoint}.json"
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Authorization": self.token,
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ConsentRequired(
                    f"the game refused the request ({exc.code} "
                    f"{exc.reason}). Accept the prompt naming "
                    f"{self.user_agent!r} in-game, then retry.") from None
            raise LocalAPIError(
                f"GET {endpoint}.json -> {exc.code} {exc.reason}") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
            raise NotRunning(_not_running_message(self.port, exc)) from None

    def snapshot(self) -> Snapshot:
        """Read everything the solver cares about, in one request.

        Deliberately `/all.json` rather than the lighter `/info.json`:
        info omits `cogsuits`, so merits would silently parse as empty
        rather than fail. Over loopback the difference is 10KB against
        3KB, which is not worth a class of bug that shows up as a field
        that is always blank.
        """
        return parse_snapshot(self.fetch("all"))


def parse_snapshot(payload: dict) -> Snapshot:
    """Turn an `/info.json` or `/all.json` body into a `Snapshot`.

    Split out from the client so it can be tested against a recorded
    payload without a running game.
    """
    toon = payload.get("toon") or {}
    laff = payload.get("laff") or {}
    location = payload.get("location") or {}

    tracks: Dict[Track, Tuple[int, bool]] = {}
    for name, entry in (payload.get("gags") or {}).items():
        track = TRACK_NAMES.get(name)
        if track is None:
            # A new track would be a game change, not a glitch; say so
            # rather than silently dropping it.
            raise LocalAPIError(
                f"unknown gag track {name!r} from the Local API; "
                f"solver.state.Track has no match for it.")
        if entry is None:
            continue                      # track not unlocked
        top = (entry.get("gag") or {}).get("level")
        if top is None:
            continue
        tracks[track] = (int(top), entry.get("organic") is not None)

    # Only departments with a suit carry a promotion block.
    merits: Dict[str, Tuple[int, int]] = {}
    for dept, entry in (payload.get("cogsuits") or {}).items():
        promotion = (entry or {}).get("promotion")
        if promotion:
            merits[dept] = (int(promotion.get("current", 0)),
                            int(promotion.get("target", 0)))

    invasion = payload.get("invasion")
    parsed_invasion = None
    if invasion:
        parsed_invasion = (
            str(invasion.get("cog", "")).replace(SOFT_BREAK, ""),
            int(invasion.get("quantity") or 0),
            bool(invasion.get("megaInvasion")),
        )

    return Snapshot(
        name=toon.get("name", "?"),
        toon_id=toon.get("id", "?"),
        laff=int(laff.get("current", 0)),
        max_laff=int(laff.get("max", 0)),
        zone=location.get("zone", "?"),
        neighborhood=location.get("neighborhood", "?"),
        district=location.get("district", "?"),
        instance_id=location.get("instanceId"),
        invasion=parsed_invasion,
        tracks=tracks,
        merits=merits,
    )


def discover(user_agent: str = DEFAULT_USER_AGENT,
             timeout: float = DEFAULT_TIMEOUT,
             probe_timeout: float = PROBE_TIMEOUT) -> List[TTRLocal]:
    """One session per running toon, in port order.

    Multitoon players get a server each, from 1547 upwards.

    The two timeouts are separate deliberately: `probe_timeout` is how
    long to wait on a TCP connect while scanning six ports, and wants to
    be short; `timeout` is how long a real request may take, and wants to
    be long. Collapsing them into one made every first request fail.
    """
    return [TTRLocal(port=p, user_agent=user_agent, timeout=timeout)
            for p in PORTS if _port_open(p, probe_timeout)]


def _port_open(port: int, timeout: float = PROBE_TIMEOUT) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _first_open_port() -> int:
    for port in PORTS:
        if _port_open(port):
            return port
    raise NotRunning(_not_running_message(None, None))


def _not_running_message(port: Optional[int], exc: object) -> str:
    where = f"port {port}" if port else f"ports {PORTS[0]}-{PORTS[-1]}"
    detail = f" ({exc})" if exc else ""
    return (
        f"no Toontown Rewritten Local API on {where}{detail}.\n"
        f"  - Is the game running, and is the Local API enabled in its "
        f"options? The port stays closed until you turn it on.\n"
        f"  - A dropped connection also means a wrong Host header; it "
        f"must be exactly localhost:<port>.")


def main(argv: Optional[List[str]] = None) -> int:
    sessions = discover()
    if not sessions:
        print(_not_running_message(None, None))
        return 1
    for session in sessions:
        print(f"--- port {session.port} ---")
        try:
            print(session.snapshot().describe())
        except LocalAPIError as exc:
            print(f"  {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
