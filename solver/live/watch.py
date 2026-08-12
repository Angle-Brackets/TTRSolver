"""Following a battle as it happens, by watching the screen.

Reading one screenshot proves the vision works; it does not help anyone
mid-fight. This polls instead, so the solver sees the battle as the
player does.

WHY THIS NEEDS NO WINDOW HANDLE
-------------------------------
Plates are found by their teal portrait slot, which appears nowhere else
in Toontown's palette, so the search does not care where the game window
is. Borderless, windowed, moved to a second monitor, resized mid-session
-- all the same. There is no window enumeration here and no dependency on
the platform's window API, which also means nothing to break when TTR
changes how it presents its window.

COST
----
Scanning every pixel is the expensive part -- ~70ms at 1080p, ~280ms at
4K, against 33ms to grab the frame -- so it is avoided in both of the
states the watcher spends its time in.

During a battle, plates barely move, so the scan is confined to a padded
band of rows around where they were last seen: 1080p 75ms -> 19ms, 4K
281ms -> 75ms, with one full scan instead of eight.

Between battles there are no plates to narrow to, and that is the state
the watcher is in almost always. A subsampled presence test answers "is
there any teal at all" for a fraction of the cost and the exact scan
runs only once something shows up: 1440p 110ms -> 6.7ms, ~17x. See
`vision.locate_plates` for why the coarse pass is only ever a yes/no and
never an enumeration.

STABILITY
---------
Cogs animate: they lean, they get knocked back, plates fade in and slide.
A single frame is therefore not evidence. Readings are held until the
same answer arrives `agree` times in a row before the watcher will call
it a change, which is what stops a gag animation from being reported as
four cogs appearing and leaving.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .catalogue import HeadCatalogue, candidates
from .vision import (
    MIN_DEPARTMENT_MARGIN, Plate, find_plates, health_fraction,
    locate_plates, read_department, read_level,
)

MIN_LEVEL_SCORE = 0.55

# How much of the frame around the last known plates to re-scan. Plates
# drift as cogs are knocked about; a quarter of the band's own size in
# every direction covers that without approaching a full scan.
ROI_PAD = 0.35

# A health change smaller than this is measurement noise, not a hit.
# The bar reads within about a point when the frame is native, but
# scaling and animation blur widen that; 4% of a bar is well under the
# smallest real gag on the largest cog.
HEALTH_EPSILON = 0.04


@dataclass(frozen=True)
class CogReading:
    """What one plate says about one cog, at one moment."""

    index: int
    department: Optional[str]
    level: Optional[int]
    health: float
    cog: Optional[str] = None
    slot: Tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def identified(self) -> bool:
        return self.cog is not None

    def same_cog_as(self, other: "CogReading") -> bool:
        """Whether two readings plausibly describe the same cog.

        Health is deliberately excluded -- it is the thing expected to
        change -- and so is `cog`, so that a cog identified partway
        through a fight is not mistaken for a different one arriving.
        """
        return (self.department == other.department
                and self.level == other.level)


@dataclass
class BattleView:
    """The cogs currently on screen, once the reading has settled."""

    cogs: List[CogReading] = field(default_factory=list)
    since: float = 0.0

    @property
    def active(self) -> bool:
        return bool(self.cogs)


@dataclass
class Event:
    kind: str
    detail: str
    cogs: List[CogReading] = field(default_factory=list)


class Capture:
    """Screen frames as RGB arrays, from mss when present."""

    def __init__(self, monitor: int = 1):
        self.monitor = monitor
        self._sct = None
        try:
            import mss

            # mss.MSS on newer releases; mss.mss is the deprecated alias.
            factory = getattr(mss, "MSS", None) or mss.mss
            self._sct = factory()
            self._region = self._sct.monitors[monitor]
        except Exception:
            self._sct = None

    def grab(self) -> np.ndarray:
        if self._sct is not None:
            shot = self._sct.grab(self._region)
            # mss hands back BGRA; the readers expect RGB.
            return np.asarray(shot)[:, :, :3][:, :, ::-1]
        from PIL import ImageGrab

        return np.asarray(ImageGrab.grab().convert("RGB"))

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


def _shift(plate: Plate, offset: int) -> Plate:
    """Move a plate found in a band back into full-frame coordinates."""
    x0, y0, x1, y1 = plate.slot
    return Plate(slot=(x0, y0 + offset, x1, y1 + offset), filled=plate.filled)


def _roi(slots: Sequence[Tuple[int, int, int, int]], shape) -> Tuple[int, int]:
    """Vertical band to search, given where plates were last seen.

    Only the rows are narrowed. Cogs enter from the sides and the plates
    spread horizontally as more of them join, so clipping columns would
    lose a cog arriving mid-fight; the rows barely move.
    """
    top = min(s[1] for s in slots)
    bottom = max(s[3] for s in slots)
    pad = max(24, int((bottom - top) * (1.0 + ROI_PAD)))
    return max(0, top - pad), min(shape[0], bottom + pad)


class BattleWatcher:
    """Polls the screen and reports what changed."""

    def __init__(self, catalogue: Optional[HeadCatalogue] = None,
                 capture: Optional[Capture] = None, agree: int = 2,
                 collect: bool = True):
        self.catalogue = catalogue if catalogue is not None else HeadCatalogue()
        self.capture = capture or Capture()
        self.agree = agree
        self.collect = collect
        self.view = BattleView()
        # None means "nothing seen yet", which is not the same as an
        # empty list meaning "seen, and there are no cogs". Conflating
        # them makes the empty reading fail its own truthiness check, so
        # agreement never accumulates and the end of a battle is never
        # reported -- the one transition that is *defined* by emptiness.
        self._pending: Optional[List[CogReading]] = None
        self._pending_count = 0
        self._band: Optional[Tuple[int, int]] = None
        self.frames = 0
        self.full_scans = 0

    # -- reading ---------------------------------------------------------

    def read_frame(self, frame: np.ndarray) -> List[CogReading]:
        readings = []
        for i, plate in enumerate(self._locate(frame)):
            dept, margin = read_department(frame, plate)
            if margin < MIN_DEPARTMENT_MARGIN:
                dept = None
            level, score = read_level(frame, plate)
            if score < MIN_LEVEL_SCORE:
                level = None
            match = self.catalogue.match(frame, plate,
                                         among=candidates(dept, level))
            readings.append(CogReading(
                index=i, department=dept, level=level,
                health=health_fraction(frame, plate),
                cog=match.cog if match and match.confident else None,
                slot=plate.slot))
        return readings

    def _locate(self, frame: np.ndarray) -> List[Plate]:
        """Plates in the frame, preferring the band they were last in.

        Always returns full-frame coordinates. Handing back band-relative
        slots and expecting callers to add the offset is what the first
        version did, and every reader then sampled the full frame with a
        box short by the band's top edge -- silently, and on the path
        that runs for the whole of every battle.
        """
        self.frames += 1
        if self._band is not None:
            top, bottom = self._band
            # reference_area keeps the size thresholds those of the whole
            # frame; on a band roughly an eighth of the frame they would
            # otherwise collapse and drift the boxes by a few pixels.
            found = find_plates(frame[top:bottom],
                                reference_area=frame.shape[0] * frame.shape[1])
            if found:
                return [_shift(p, top) for p in found]
        self.full_scans += 1
        # locate_plates, not find_plates: between battles there is
        # nothing to narrow to, so this path runs on every poll and its
        # cost is the idle cost of the whole watcher.
        plates = locate_plates(frame)
        self._band = _roi([p.slot for p in plates], frame.shape) if plates \
            else None
        return plates

    # -- change detection ------------------------------------------------

    def poll(self) -> List[Event]:
        """Grab one frame and return whatever changed because of it."""
        frame = self.capture.grab()
        readings = self.read_frame(frame)

        if self._pending is not None and _matches(readings, self._pending):
            self._pending_count += 1
        else:
            self._pending, self._pending_count = readings, 1
        if self._pending_count < self.agree:
            return []

        events = self._diff(self.view.cogs, readings)
        if self.collect:
            self._collect(frame, readings)
        if events:
            self.view = BattleView(cogs=readings, since=time.time())
        else:
            self.view.cogs = readings        # health drift, same cogs
        return events

    def _diff(self, before: List[CogReading],
              after: List[CogReading]) -> List[Event]:
        events: List[Event] = []
        if not before and after:
            events.append(Event("battle_started",
                                f"{len(after)} cog(s)", list(after)))
            return events
        if before and not after:
            events.append(Event("battle_ended", "no cogs on screen"))
            return events
        if len(after) < len(before):
            events.append(Event("cog_defeated",
                                f"{len(before)} -> {len(after)} cogs",
                                list(after)))
        elif len(after) > len(before):
            events.append(Event("cog_joined",
                                f"{len(before)} -> {len(after)} cogs",
                                list(after)))
        else:
            for old, new in zip(before, after):
                drop = old.health - new.health
                if drop > HEALTH_EPSILON:
                    events.append(Event(
                        "damage",
                        f"cog {new.index + 1} {old.health:.0%} -> "
                        f"{new.health:.0%}", [new]))
        for old, new in zip(before, after):
            if new.identified and not old.identified:
                events.append(Event("identified",
                                    f"cog {new.index + 1} is {new.cog}",
                                    [new]))
        return events

    def _collect(self, frame: np.ndarray, readings: List[CogReading]) -> None:
        """Stash head crops for cogs the library cannot name yet.

        Only when the plate has narrowed the field to exactly one cog is
        it safe to record automatically -- anything wider needs a human
        to say which of the candidates it is.
        """
        for reading in readings:
            if reading.identified or reading.department is None \
                    or reading.level is None:
                continue
            pool = candidates(reading.department, reading.level)
            if len(pool) != 1 or pool[0] in self.catalogue.entries:
                continue
            plate = Plate(slot=reading.slot, filled=0)
            self.catalogue.add(pool[0], frame, plate)

    def close(self) -> None:
        self.capture.close()


def _matches(a: List[CogReading], b: List[CogReading]) -> bool:
    return len(a) == len(b) and all(x.same_cog_as(y) for x, y in zip(a, b))


def watch(on_event: Callable[[Event], None], interval: float = 0.4,
          duration: Optional[float] = None,
          watcher: Optional[BattleWatcher] = None) -> BattleWatcher:
    """Poll until `duration` elapses, calling `on_event` as things change."""
    watcher = watcher or BattleWatcher()
    started = time.time()
    try:
        while duration is None or time.time() - started < duration:
            cycle = time.time()
            for event in watcher.poll():
                on_event(event)
            time.sleep(max(0.0, interval - (time.time() - cycle)))
    except KeyboardInterrupt:
        pass
    return watcher


def _describe(reading: CogReading) -> str:
    from .read_battle import display

    who = display(reading.cog) if reading.cog else (
        f"{reading.department or '?'} lvl "
        f"{reading.level if reading.level is not None else '?'}")
    return f"{who} {reading.health:.0%}"


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Follow a Toontown battle live by watching the screen.")
    parser.add_argument("--interval", type=float, default=0.4,
                        help="seconds between polls (default 0.4)")
    parser.add_argument("--duration", type=float,
                        help="stop after this many seconds")
    parser.add_argument("--no-collect", action="store_true",
                        help="do not auto-record unambiguous cog heads")
    args = parser.parse_args(argv)

    watcher = BattleWatcher(collect=not args.no_collect)
    print(f"watching every {args.interval}s -- Ctrl-C to stop")
    start = time.time()

    def show(event: Event) -> None:
        stamp = time.time() - start
        line = f"[{stamp:7.1f}s] {event.kind:15s} {event.detail}"
        if event.cogs and event.kind in ("battle_started", "cog_defeated",
                                         "cog_joined"):
            line += "  | " + ", ".join(_describe(c) for c in event.cogs)
        print(line, flush=True)

    watch(show, interval=args.interval, duration=args.duration,
          watcher=watcher)
    watcher.close()
    scan_ratio = (watcher.full_scans / watcher.frames) if watcher.frames else 0
    print(f"\n{watcher.frames} frames, {watcher.full_scans} full scans "
          f"({scan_ratio:.0%}); library holds {len(watcher.catalogue)} cogs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
