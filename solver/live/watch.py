"""Following a battle as it happens, by watching the screen.

Reading one screenshot proves the vision works; polling lets the solver
see the battle as the player does.

WHAT COUNTS AS A BATTLE. Teal plates alone are not sufficient: the slot
colour isn't unique outside a battle screenshot, and a blue-green
desktop wallpaper produced plates all day -- so entering a battle also
requires the gag menu (`in_battle`), on a frame cropped to the game
window first (`window.game_rect`, `Capture`).

Teal plates are not necessary either: when a round resolves, TTR cuts
the camera to show the attack and takes the menu and every plate with it
for the length of the animation. Absence means nothing until it outlasts
one -- see `BATTLE_GRACE` and `_battle_is_over` -- otherwise a single
fight reports itself starting and ending once per round.

COST. Scanning every pixel is the expensive part (~70ms at 1080p, ~280ms
at 4K, against 33ms to grab the frame), so it is avoided in both states
the watcher spends its time in: during a battle the scan is confined to
a padded band around the last-seen plates (1080p 75ms -> 19ms, 4K 281ms
-> 75ms), and between battles -- almost all the time -- a subsampled
presence test answers "any teal at all" far cheaper, with the exact scan
running only once something shows up (1440p 110ms -> 6.7ms). See
`vision.locate_plates` for why the coarse pass stays yes/no only.

STABILITY. Cogs animate -- lean, get knocked back, plates fade and slide
-- so a single frame is not evidence. Readings are held until the same
answer arrives `agree` times running before the watcher calls it a
change, which stops a gag animation reading as four cogs appearing and
leaving.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .catalogue import HeadCatalogue, candidates

# Frames a plate must stay missing before a name given for it is
# dropped. Detection flickers; a pick must not.
FORGET_AFTER_FRAMES = 5

# Identify cogs only on frames where the gag menu is open, or where the
# number of plates has changed. See `read_frame` for why.
REREAD_ONLY_WITH_MENU = True
from .vision import (
    lure_indicator,
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
    # Asleep on a Lure. Read from the plate via `vision.lure_indicator`,
    # with the player's mark in `_lured` as an override for a false
    # negative.
    #
    # It changes the advice completely: Throw and Squirt are forced to
    # 100% against a lured cog and collect the knockback bonus, Drop
    # always misses one, and a lured cog does not attack. Treating a
    # sleeping cog as awake means planning every one of those wrong.
    lured: bool = False
    # A trap laid in front of this cog. TTR floats a banana peel over a
    # trapped cog (`ttr_t_gui_bat_statusEffect_icon_trapped`), readable
    # in principle unlike `lured` -- see `ttr_assets.status_icon`.
    #
    # WHICH trap is a separate question: the marker is the same peel for
    # Quicksand and TNT, and `CogStatus` needs a level (or explicit
    # damage) before a Lure can spring it for the right number. So this
    # only says "something is under it"; the level comes from the player
    # or from what the solver itself advised.
    trapped: bool = False
    trap_level: Optional[int] = None

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


def _outside_the_menu(frame, plates):
    """Drop plate candidates that sit inside the gag menu.

    A cog plate floats above its cog; the menu is drawn over the lower
    middle of the screen and never contains one. The menu also holds
    plenty of teal (cell backgrounds, the empty Drop slot), and after
    the slot floor came down to admit a real plate at 1110 pixels, an
    80x49 patch inside the TRAP row started passing as a second cog. A
    false plate is worse than a missed one: the search then plans
    against a cog nobody is fighting.

    Costs nothing: `find_panel` has already run this poll for the read
    gate, and its bounds are exactly what's needed.
    """
    if not plates:
        return plates
    from .gagpanel import find_panel

    located = find_panel(frame)
    if located is None:
        return plates
    left, width, bands, row_height = located
    if not bands:
        return plates
    top = min(bands.values())
    bottom = max(bands.values()) + row_height
    kept = []
    for plate in plates:
        x0, y0, x1, y1 = plate.slot
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        inside = (left <= cx <= left + width) and (top <= cy <= bottom)
        if not inside:
            kept.append(plate)
    return kept


class BattleWatcher:
    """Polls the screen and reports what changed."""

    def __init__(self, catalogue: Optional[HeadCatalogue] = None,
                 capture: Optional[Capture] = None, agree: int = 2,
                 collect: bool = True, panel_present=None,
                 battle_over=None, force_battle=None):
        self.catalogue = catalogue if catalogue is not None else HeadCatalogue()
        # Cogs the player named by hand, keyed by PLATE ORDER -- the
        # catalogue only knows a few heads, so `match`/`eliminate` often
        # can't, and the player can see the cog perfectly well. NOT
        # keyed on `plate.slot`: that's a detected box that drifts a few
        # pixels between frames from antialiasing, so a name keyed on it
        # never matched again. Order is stable frame to frame and
        # unstable across a death, so `_forget_names` clears names when
        # the plate count changes rather than letting one slide onto a
        # different cog.
        self._named: dict = {}
        self._low_frames = 0
        # Plates the player has marked as lured, by plate order. Same
        # keying and same expiry as `_named`.
        self._lured: set = set()
        # Traps the player has marked, plate order -> gag level.
        self._trapped: dict = {}
        # Levels the player typed in, by plate order. `read_level`
        # refuses when a digit could equally be another -- a live
        # "Level 8" once scored 0.73 with a 0.02 margin against a 0.05
        # floor, correctly, since a Level 8 was once read as a 6. But
        # the plate says "Level 8" in plain text, so let the player say
        # so.
        self._levels: dict = {}
        # Last full read, reused while the board is mid-animation.
        self._cached_readings = None
        self.reused_reads = 0
        # Set once per poll and shared, rather than recomputed by every
        # caller that wants it.
        self.menu_visible = False
        # THE FRAME `menu_visible` AND THE READINGS WERE TAKEN FROM, so
        # the solver reads the same capture the watcher graded -- a
        # second, separately grabbed frame can disagree mid-animation
        # (e.g. "2 cog plates, gag menu" and "no gag menu" at once),
        # which is not a contradiction the player can do anything about.
        self.last_frame = None
        # Slots the player named that are not in the library yet. The
        # panel names a slot without a frame in hand, so the head is
        # recorded on the next frame that reads the slot -- which is
        # also the check that the plate is still there.
        self._learn: dict = {}
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
        # () -> True (in a fight), False (not), or None (no opinion).
        # The overlay's confirm button. Automatic detection is evidence
        # about the screen; this is the player, who can simply see.
        self.force_battle = force_battle
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
        forced = self.force_battle() if self.force_battle else None
        if forced is not None:
            return not forced
        if self.battle_over is not None and self.battle_over():
            return True
        return (time.time() - self._plates_at) > BATTLE_GRACE

    # -- reading ---------------------------------------------------------

    def read_frame(self, frame: np.ndarray,
                   menu_visible: Optional[bool] = None) -> List[CogReading]:
        readings = []
        plates = self._locate(frame)
        plates = _outside_the_menu(frame, plates)
        self._forget_names(len(plates))

        # RE-READ WHEN THE MENU IS UP, or when the lineup changes.
        # Identifying a cog (department, level, signature match) is the
        # expensive part of a poll, and redoing it every frame --
        # including ones where TTR swings the camera through an attack,
        # where plates are moving and half-occluded -- produced flicker
        # that wiped cogs the player had named by hand.
        #
        # The gag menu is up exactly when a decision is due and the
        # board is still, so it's a good clock for "look properly now".
        # A boss fight can walk new cogs in mid-round with the menu
        # down, so a plate-count change also forces a look; otherwise
        # last round's answer still holds, since cogs don't change
        # identity.
        if REREAD_ONLY_WITH_MENU and self._cached_readings is not None:
            # PASSED IN, never computed here: calling `find_panel` just
            # to decide whether to skip a read cost 33x the read itself
            # (495ms a poll vs 15). The caller already needs this answer
            # for its own "is the menu up" display, so it's computed
            # once and handed over -- a gate must be cheaper than what
            # it gates.
            if menu_visible is None:
                menu_visible = self.menu_visible
            same_lineup = len(self._cached_readings) == len(plates)
            if same_lineup and not menu_visible:
                self.reused_reads += 1
                return self._cached_readings
        for i, plate in enumerate(plates):
            dept, margin = read_department(frame, plate)
            if margin < MIN_DEPARTMENT_MARGIN:
                dept = None
            level, score, level_margin = read_level(frame, plate)
            told = self._levels.get(i)
            # Both gates. A low score means the region holds nothing
            # legible; a low margin means it holds something legible
            # that could equally be another digit. The second is the
            # dangerous one -- a live plate reading "Level 8" was read
            # as 6 at score 0.709, over a runner-up of 0.670.
            if score < MIN_LEVEL_SCORE or level_margin < MIN_LEVEL_MARGIN:
                level = None
            if told is not None:
                level = told
            pool = candidates(dept, level)
            # THE PLAYER FIRST. They are looking at the cog; the
            # library holds six heads of thirty-two and will happily
            # match a Number Cruncher against the Bean Counter it has.
            # Consulting the name only when nothing else identified the
            # plate meant a confident wrong answer could not be
            # corrected -- the exact case reported.
            cog = self._named.get(i)
            if cog is not None:
                if self._learn.pop(i, None) == cog:
                    # Owner-authorised: overwrite whatever signature
                    # produced the bad match. `add` keeps the crop, so a
                    # mis-click is visible and correctable.
                    try:
                        self.catalogue.add(cog, frame, plate)
                    except Exception:
                        pass
            else:
                match = self.catalogue.match(frame, plate, among=pool)
                cog = match.cog if match and match.confident else None
                if cog is None:
                    # Nothing resembles it, but it may be deducible: if
                    # every known candidate is ruled out and one is
                    # left, that is the cog. See HeadCatalogue.eliminate.
                    cog = self.catalogue.eliminate(frame, plate, among=pool)
            readings.append(CogReading(
                index=i, department=dept, level=level,
                health=health_fraction(frame, plate),
                cog=cog, slot=plate.slot,
                # Read from the plate, with the player's mark as an
                # override -- the detector is new and a false negative
                # must not leave them unable to say otherwise.
                lured=(i in self._lured) or lure_indicator(frame, plate)))
        self._cached_readings = readings
        return readings

    def set_level(self, index, level) -> None:
        """The player reading the level off the plate for us."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if level in (None, "", 0):
            self._levels.pop(index, None)
            return
        try:
            value = int(level)
        except (TypeError, ValueError):
            return
        if 1 <= value <= 20:
            self._levels[index] = value

    def _traps(self) -> dict:
        """The player's trap marks, created on demand.

        `getattr` rather than a class attribute: a dict on the class
        would be SHARED by every watcher, so one battle's traps would
        appear in the next one's. Instances built with `__new__` -- which
        the tests do -- have no `__init__` to set it up.
        """
        traps = getattr(self, "_trapped", None)
        if traps is None:
            traps = {}
            self._trapped = traps
        return traps

    def mark_trapped(self, index, level) -> None:
        """The player says a trap of `level` sits in front of this cog.

        A LEVEL, not a flag. The floating marker is the same banana peel
        whatever the trap is, and `CogStatus` cannot spring a trap it
        cannot price -- `data.gag(TRAP, None)` raises. `None` clears.
        """
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if level in (None, "", 0):
            self._traps().pop(index, None)
            return
        try:
            value = int(level)
        except (TypeError, ValueError):
            return
        if 1 <= value <= 7:
            self._traps()[index] = value

    def mark_lured(self, index, lured: bool) -> None:
        """The player says this cog is asleep, or is not."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if lured:
            self._lured.add(index)
        else:
            self._lured.discard(index)

    def _forget_names(self, count: int) -> None:
        """Drop hand-named cogs that no longer have a plate.

        ONLY THE OUT-OF-RANGE ONES: clearing every name whenever the
        plate count changed destroyed the feature, since `find_plates`
        drops a plate for a frame whenever a cog is mid-animation or
        obscured, discarding the player's pick on that flicker alone. A
        name for a gone plate is stale and goes; a name for a plate that
        still exists is kept even if the count moved.

        Indices shift when a cog dies, so a surviving name can end up on
        the wrong cog -- visible in the dropdown and correctable, unlike
        a silently discarded pick. `end_fight` clears the lot.
        """
        if count < 0:                    # explicit reset
            self._named.clear()
            self._learn.clear()
            self._lured.clear()
            self._traps().clear()
            self._levels.clear()
            self._low_frames = 0
            # THE LAST FIGHT'S READINGS GO TOO. `read_frame` reuses them
            # while the lineup holds and the menu is down, which is right
            # mid-fight and wrong across fights: seen live, a level 6
            # Mover & Shaker walked in before the menu came up and was
            # handed the previous fight's level 5 (42/42) until it did.
            self._cached_readings = None
            return
        # NO PLATES AT ALL IS "CANNOT SEE", NOT "COGS GONE" -- it must
        # never forget anything. The attack animation between rounds
        # hides every plate for several seconds, longer than the
        # debounce below (5 frames at 0.5s = 2.5s), so acting on a zero
        # count dropped every hand-named cog on the first round
        # transition after naming it. A zero count is the reader saying
        # it has no evidence, not that the cogs are gone.
        if count == 0:
            self._low_frames = 0
            return
        # DEBOUNCED. A plate that vanishes for one frame has not gone --
        # it is mid-animation, or something walked in front of it. Acting
        # on the first frame meant one dropout threw the pick away, which
        # is indistinguishable from the dropdown not working.
        highest = max(self._named, default=-1)
        if highest < count:
            self._low_frames = 0
            return
        self._low_frames = getattr(self, "_low_frames", 0) + 1
        if self._low_frames < FORGET_AFTER_FRAMES:
            return
        self._low_frames = 0
        for index in [i for i in self._named if i >= count]:
            self._named.pop(index, None)
            self._learn.pop(index, None)
        self._lured = {i for i in self._lured if i < count}
        self._trapped = {i: v for i, v in self._traps().items()
                         if i < count}
        for index in [i for i in self._levels if i >= count]:
            self._levels.pop(index, None)

    def name_plate(self, index, cog: Optional[str], learn: bool = True) -> None:
        """Record what the player says is in this plate slot.

        WRITTEN TO THE HEAD LIBRARY, on the owner's instruction: a wrong
        entry poisons every later match, but `add` overwrites rather
        than accumulates and keeps the source crop, so a mis-click can
        be seen and corrected -- and the player naming a cog they're
        looking at beats a signature match against a handful of known
        heads.

        The write is deferred: this is called from the UI thread with no
        frame in hand, so the head is recorded on the next frame that
        reads the slot.
        """
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if cog:
            self._named[index] = cog
            if learn and cog not in self.catalogue.entries:
                self._learn[index] = cog
        else:
            self._named.pop(index, None)
            self._learn.pop(index, None)

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

        Teal plates alone are not enough evidence: standing in Donald's
        Dreamland, 2.1% of the frame matched the teal mask and two blobs
        cleared the size and aspect filters, so the watcher called a
        battle and then cogs defeated as the player walked around --
        every reading `level unreadable / unidentified`, the signature
        of plate-shaped scenery with no level to read.

        The gag menu is the honest signal, and it's free: nothing can be
        advised without it anyway, since gag counts come only from the
        screen, and `find_panel` returns None on the same frame that
        fools the plate detector.

        Entry is strict, continuation lenient, because the menu slides
        away during attack animations -- requiring it every frame would
        flap the battle on and off mid-fight.
        """
        forced = self.force_battle() if self.force_battle else None
        if forced is False:
            return False
        if forced:
            # The player says they are fighting. That overrides the gag
            # menu, which is the *evidence* for a battle and not the
            # battle itself, but it cannot conjure cogs: plates are
            # still what the readers read, so a forced battle with
            # nothing on screen is still no cogs.
            return plates_seen

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
        self.last_frame = frame
        # Once per poll, for the read gate and for anyone displaying it.
        from .gagpanel import find_panel

        self.menu_visible = find_panel(frame) is not None
        readings = self.read_frame(frame, menu_visible=self.menu_visible)
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
        # AGREEMENT IS FOR DETECTION, NOT FOR AN ASSERTION. Two matching
        # polls before believing the screen is right -- readings flicker
        # through animations. But when the player has pressed "I'm in a
        # fight" they have already told us; making them wait another poll
        # for the readers to agree with each other is the delay they were
        # trying to skip.
        forced = self.force_battle() if self.force_battle else None
        need = 1 if forced else self.agree
        if self._pending_count < need:
            return []

        events = self._diff(self.view.cogs, readings)

        # PLATES GOING AWAY IS NOT THE BATTLE ENDING: TTR cuts the
        # camera and takes the menu and every plate with it for the
        # length of each attack animation, so treating that as the end
        # reported a battle starting and ending several times per fight.
        # Absence is only evidence once it outlasts an animation. The
        # agreement count above keeps accumulating meanwhile, so the end
        # fires on the first poll after the grace expires rather than
        # needing another `agree` frames on top.
        if any(e.kind == "battle_ended" for e in events):
            if not self._battle_is_over():
                return []
            # THE PLAYER'S MARKS DIE WITH THE FIGHT THEY WERE MADE IN.
            # Marks are keyed on PLATE ORDER, so without this a name set
            # at index 0 in one battle stamps onto whatever stands at
            # index 0 in the next -- and since `read_frame` puts the
            # player's name FIRST, the stale pick beats a correct read.
            # Reported from play: a Name Dropper named in one fight
            # reappeared in the next as a Bean Counter -- 56hp planned
            # against 72hp actual.
            #
            # `_lured` and `_levels` carry over the same way and are
            # worse, since nothing on screen contradicts them: a fresh
            # cog inherits "asleep" and the solver quietly plans around
            # a lure that doesn't exist.
            self._forget_names(-1)
        # BACKSTOP, for an end detection missed: a fight STARTING is the
        # other moment nothing may carry over, and the player hasn't had
        # a chance to mark anything yet, so there's nothing of theirs to
        # lose. This runs a poll late -- this frame's readings are
        # already stamped with the old names above -- but one wrong
        # frame that then corrects itself beats a wrong name that never
        # does.
        if any(e.kind == "battle_started" for e in events):
            self._forget_names(-1)
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
            elif (len(before) == len(after) and not old.same_cog_as(new)
                  and new.level is not None):
                # A READING CORRECTED ITSELF -- a level or department read
                # anew at the same plate count. It changes the cog's health
                # and attacks, so it is news; without an event the advice
                # stayed on the board it had been wrong about.
                events.append(Event("corrected",
                                    f"cog {new.index + 1}: level {old.level} "
                                    f"-> {new.level}", [new]))
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
