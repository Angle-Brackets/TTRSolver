"""Following a battle as it happens, by watching the screen.

Reading one screenshot proves the vision works; it does not help anyone
mid-fight. This polls instead, so the solver sees the battle as the
player does.

WHAT COUNTS AS A BATTLE
-----------------------
Two mistakes were made here, in opposite directions, and both looked
like the vision failing.

Teal plates are not sufficient. The slot colour is not unique outside a
battle screenshot, and a blue-green desktop wallpaper produced plates
all day -- so entering a battle also requires the gag menu
(`in_battle`), and the frame is cropped to the game window before any
of this runs (`window.game_rect`, `Capture`).

Teal plates are not necessary either, which is the subtler one. When a
round resolves, TTR cuts the camera to show the attack and takes the
menu and every plate with it for the length of the animation. Absence
therefore means nothing until it outlasts one -- see `BATTLE_GRACE` and
`_battle_is_over`. Before that, a single fight reported itself starting
and ending once per round.

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
    locate_plates, read_department, read_level, MIN_LEVEL_MARGIN,
)

MIN_LEVEL_SCORE = 0.55

# How long the plates may be absent before the battle counts as over.
# They vanish for the whole of an attack animation -- TTR cuts the camera
# to the cog being hit and takes the gag menu and every plate with it --
# so anything shorter reports the fight ending and restarting once per
# round. A crowded battle animates several attacks back to back, which is
# where the upper end of this comes from. Erring long costs only a
# delayed "battle_ended"; erring short costs the identity of the fight.
BATTLE_GRACE = 20.0

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
    """Frames of the game as RGB arrays, from mss when present.

    Of *the game*, not of the screen, whenever the game's window can be
    found -- see `window.game_rect`. Played windowed, a full-screen grab
    hands the plate reader the whole desktop, and the teal mask has no
    way to tell a portrait slot from a blue-green wallpaper. On a real
    desktop that cost every read: one wallpaper blob outscored both
    actual plates. Falls back to the whole screen when the window is not
    found, which is the old behaviour.
    """

    def __init__(self, monitor: int = 1, follow_window: bool = True):
        self.monitor = monitor
        self.follow_window = follow_window
        self._sct = None
        try:
            import mss

            # mss.MSS on newer releases; mss.mss is the deprecated alias.
            factory = getattr(mss, "MSS", None) or mss.mss
            self._sct = factory()
            self._region = self._sct.monitors[monitor]
        except Exception:
            self._sct = None

    def region(self) -> Optional[Tuple[int, int, int, int]]:
        """(left, top, right, bottom) to grab, or None for everything.

        Looked up per grab rather than cached: the window can be moved,
        resized or alt-tabbed between frames, and a stale rectangle
        would silently read the wrong part of the screen. The lookup is
        a single FindWindow and costs far less than the grab.
        """
        if not self.follow_window:
            return None
        from .window import game_rect

        return game_rect()

    def grab(self) -> np.ndarray:
        box = self.region()
        if self._sct is not None:
            if box is not None:
                left, top, right, bottom = box
                shot = self._sct.grab({"left": left, "top": top,
                                       "width": right - left,
                                       "height": bottom - top})
            else:
                shot = self._sct.grab(self._region)
            # mss hands back BGRA; the readers expect RGB.
            return np.asarray(shot)[:, :, :3][:, :, ::-1]
        from PIL import ImageGrab

        return np.asarray(ImageGrab.grab(bbox=box).convert("RGB"))

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
                 collect: bool = True, panel_present=None,
                 battle_over=None):
        self.catalogue = catalogue if catalogue is not None else HeadCatalogue()
        self.capture = capture or Capture()
        self.agree = agree
        self.collect = collect
        # How to tell a battle from teal scenery -- see `in_battle`.
        # Injectable so tests of the change detection can drive it with
        # scripted plate frames without also having to draw a gag menu.
        self.panel_present = panel_present
        self.view = BattleView()
        # None means "nothing seen yet", which is not the same as an
        # empty list meaning "seen, and there are no cogs". Conflating
        # them makes the empty reading fail its own truthiness check, so
        # agreement never accumulates and the end of a battle is never
        # reported -- the one transition that is *defined* by emptiness.
        self._pending: Optional[List[CogReading]] = None
        self._pending_count = 0
        self._band: Optional[Tuple[int, int]] = None
        self._plates_at = 0.0
        self.battle_over = battle_over
        self.frames = 0
        self.full_scans = 0

    def _battle_is_over(self) -> bool:
        """Has the fight actually finished, rather than paused?

        Two ways to know, and the cheap one is only a timer. Plates are
        absent for the whole of an attack animation, so their absence
        means nothing until it has outlasted one; `BATTLE_GRACE` is that
        bound.

        `battle_over` is the shortcut, for a caller that knows something
        the screen does not. The Local API's merit totals tick up the
        moment a fight pays out, which is proof the battle finished and
        arrives immediately -- but only for a department whose suit the
        toon already owns, so it confirms an end and can never rule one
        out. Hence: either signal ends the battle, neither is required.
        """
        if self.battle_over is not None and self.battle_over():
            return True
        return (time.time() - self._plates_at) > BATTLE_GRACE

    # -- reading ---------------------------------------------------------

    def read_frame(self, frame: np.ndarray) -> List[CogReading]:
        readings = []
        for i, plate in enumerate(self._locate(frame)):
            dept, margin = read_department(frame, plate)
            if margin < MIN_DEPARTMENT_MARGIN:
                dept = None
            level, score, level_margin = read_level(frame, plate)
            # Both gates. A low score means the region holds nothing
            # legible; a low margin means it holds something legible
            # that could equally be another digit. The second is the
            # dangerous one -- a live plate reading "Level 8" was read
            # as 6 at score 0.709, over a runner-up of 0.670.
            if score < MIN_LEVEL_SCORE or level_margin < MIN_LEVEL_MARGIN:
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

    def in_battle(self, frame: np.ndarray, plates_seen: bool) -> bool:
        """Is this frame a battle, as opposed to teal-coloured scenery?

        Teal plates alone are not enough evidence and never were. The
        claim in `vision`'s docstring that the slot colour "appears
        nowhere else in Toontown's high-key palette" was validated on
        battle screenshots only, and it is false in the wider game:
        standing in Donald's Dreamland, 2.1% of the frame matched the
        teal mask and two blobs cleared both the size and the aspect
        filter, so the watcher called a battle, then called cogs
        defeated as the player walked around and the blobs came and
        went. Every reading it produced was `level unreadable /
        unidentified`, which is what a false positive looks like from
        the inside -- plate-shaped scenery has no level to read.

        The gag menu is the honest signal, and it is free: nothing can
        be advised without it anyway, because gag counts come only from
        the screen. `find_panel` returns None on the same overworld
        frame that fools the plate detector.

        Entry is strict and continuation is lenient, because the menu
        slides away while attack animations play. Requiring it every
        frame would flap the battle on and off mid-fight.
        """
        if not plates_seen:
            return False
        if self.view.active:
            return True                 # already in one: plates suffice

        check = self.panel_present
        if check is None:
            from .gagpanel import find_panel

            def check(f):
                return find_panel(f) is not None
        return bool(check(frame))

    def poll(self) -> List[Event]:
        """Grab one frame and return whatever changed because of it."""
        frame = self.capture.grab()
        readings = self.read_frame(frame)
        if not self.in_battle(frame, bool(readings)):
            readings = []
            # Drop the search band too. It was set from whatever the
            # plate detector matched, and if that was scenery the band
            # is wrong -- `_locate` prefers it and would keep finding
            # the same non-cogs instead of falling back to a full scan.
            self._band = None

        if readings:
            self._plates_at = time.time()

        if self._pending is not None and _matches(readings, self._pending):
            self._pending_count += 1
        else:
            self._pending, self._pending_count = readings, 1
        if self._pending_count < self.agree:
            return []

        events = self._diff(self.view.cogs, readings)

        # PLATES GOING AWAY IS NOT THE BATTLE ENDING.
        #
        # When a round resolves, TTR cuts the camera to show the attack,
        # and the gag menu and every plate go with it for the length of
        # the animation. Treating that as the end reported a battle
        # starting and ending several times per fight, and each
        # re-entry re-ran the search on what was the same battle.
        #
        # Absence is only evidence once it has outlasted an animation.
        # The agreement count above is deliberately left to accumulate
        # meanwhile, so the end fires on the first poll after the grace
        # expires rather than needing another `agree` frames of a thing
        # that has already been stable for twenty seconds.
        if (any(e.kind == "battle_ended" for e in events)
                and not self._battle_is_over()):
            return []
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
