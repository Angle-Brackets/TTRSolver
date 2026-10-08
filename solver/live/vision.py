"""Reading a Toontown battle off the screen.

The Local API knows the toon and nothing about the fight (see
`ttr_local`), so the cogs are read from the rendered frame. This module
finds the cog plates -- the metal signs TTR draws above each cog when
`show-cog-levels` is on -- and returns their geometry; interpreting
what's inside is the caller's job.

FINDING THE PLATES. The anchor is the flat teal square behind each cog's
head render -- not fixed coordinates (the plate floats in 3D and moves
with the camera) and not the metal plate itself (poor contrast against
cobblestone and Cog HQ interiors). The teal slot isn't unique to plates,
though: standing in Donald's Dreamland, 2.1% of a 1440p frame matched
the mask and two blobs cleared the size and aspect filters too. So
`find_plates` finds plate-*shaped* teal and nothing more; deciding
whether a frame is a battle needs a second signal and belongs to the
caller -- `watch.BattleWatcher.in_battle` requires the gag menu too.

NOTHING HERE IS IN ABSOLUTE PIXELS. Every threshold is a fraction of the
frame, and every sub-region of a plate a multiple of its own slot, since
a constant tuned at 1080p breaks everywhere else. Verified to find both
plates in a two-cog battle at 854x480 through 2160p.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

# Sampled from the slot interior of a real battle frame.
TEAL = (90, 141, 158)
TOLERANCE = 34


# Fractions of the frame rather than pixel counts. At 1080p these come
# out near the values found by hand (120px, 40px, 1200px).
MIN_FRAGMENT_FRAC = 0.000058     # of frame area
MERGE_GAP_FRAC = 0.021           # of frame width
# Measured against a live rejection: a 65x45 slot held 1110 teal pixels
# on a 1921x1081 frame but was refused for wanting 1204 -- the colour
# was right (rgb(87,139,155) vs TEAL (90,141,158)), just less backdrop
# showing, since that cog's head covers more of its slot. 0.00046 puts
# the floor under that reading with room, well above the largest
# rejected non-plate seen in the same frames (359).
MIN_SLOT_FRAC = 0.00046          # of frame area

# And a ceiling, of frame WIDTH. The aspect and minimum-size filters
# both pass large teal scenery too: a grey-blue machine in a Lullaby
# Lane street matched as a 629x391 "plate" (aspect 1.61) in a frame
# whose real plates were 69x47 and 65x45. A plate is drawn at a fixed
# scale and measured at 3.4-3.6% of frame width across every capture so
# far; this is more than three times that.
MAX_SLOT_WIDTH_FRAC = 0.12

# The slot is a fixed-aspect rectangle. Measured 1.44-1.52 across six
# resolutions; the window is wider than that to tolerate a cog head that
# eats into one edge of the backdrop.
ASPECT_RANGE = (1.15, 1.85)

# Sub-regions of a plate, as multiples of its slot's width and height:
# (left, top, right, bottom). Derived from a 1080p frame and confirmed to
# land correctly on both plates of a two-cog battle.
PARTS: Dict[str, Tuple[float, float, float, float]] = {
    "level": (1.15, 0.05, 2.55, 0.95),
    # The emblem is a circle; the box must BE the circle, not a
    # rectangle near it. An earlier guess sat 0.15 slot widths too far
    # left, clipping the disc on one side and catching plate metal on
    # the other, which dropped correlation to noise and picked the
    # wrong department. Measured: 43x43px on a 66x45 slot -- square, as
    # a disc should be.
    "medallion": (0.20, 1.16, 0.85, 2.11),
    # Calibrated to the meter's *track*, not a box drawn around it. Both
    # cogs in the reference frame were at full health, so the extent of
    # saturated pixels is exactly the full-bar extent; the two plates
    # agreed to within 0.03 slot widths. A hand-drawn box read a full
    # bar as 83% full, which would have made every use of this wrong.
    "health": (1.03, 1.42, 2.18, 1.83),
    # The lure indicator: a red-bordered tile the game floats ABOVE the
    # plate, centred on the whole sign rather than on the portrait slot,
    # carrying the rounds the cog has left asleep.
    #
    # Negative y because it sits above the slot's own top edge. The
    # bounds are generous on purpose -- this is a presence test for
    # saturated red, not a template match, so a few slot-widths of slack
    # costs nothing and covers the tile drifting with plate size.
    "lure": (0.55, -1.30, 1.75, -0.15),
}


@dataclass(frozen=True)
class Plate:
    """One cog's sign, located but not yet read."""

    slot: Tuple[int, int, int, int]      # the teal portrait backdrop
    filled: int                          # teal pixels, for diagnostics

    def region(self, part: str) -> Tuple[int, int, int, int]:
        """Pixel box of a named sub-region, scaled off this plate's slot."""
        try:
            left, top, right, bottom = PARTS[part]
        except KeyError:
            raise KeyError(f"no such plate region {part!r}; "
                           f"have {sorted(PARTS)}") from None
        x0, y0, x1, y1 = self.slot
        w, h = x1 - x0, y1 - y0
        # round, not int: truncating both edges biases every region
        # systematically smaller, and the regions are only ~20px tall at
        # 1080p, so a consistent one-pixel shave is a real loss.
        return (round(x0 + left * w), round(y0 + top * h),
                round(x0 + right * w), round(y0 + bottom * h))

    @property
    def width(self) -> int:
        return self.slot[2] - self.slot[0]

    @property
    def height(self) -> int:
        return self.slot[3] - self.slot[1]


def teal_mask(frame: np.ndarray) -> np.ndarray:
    """Boolean mask of pixels close to the portrait backdrop colour.

    A REFUTED WIDENING IS RECORDED HERE: Lawbot HQ's sepia courtroom
    light seemed to need a looser mask (matching teal by channel ORDER
    rather than a fixed +/-34 box, since a tint leaves order intact),
    but the test frame actually had no cogs in it -- on a real Lawbot HQ
    battle, the box alone and the widened version found the same single
    plate. A wider mask isn't free either: at the loosest thresholds
    tried it invented a third plate on a two-plate frame and dropped a
    department margin to 0.28. `tools/teal_ab.py` is the check, if a
    zone ever does defeat the box.
    """
    delta = np.abs(frame[:, :, :3].astype(np.int16) - np.array(TEAL))
    return np.all(delta < TOLERANCE, axis=2)


def _runs(mask: np.ndarray) -> List[Tuple[int, int, int]]:
    """Horizontal runs of True, as (row, start, end).

    Working in runs rather than pixels keeps the labelling loop over a
    few thousand items instead of a few million, which is the difference
    between 1.2s and a few milliseconds on a 4K frame.
    """
    out = []
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=bool)
    padded[:, 1:-1] = mask
    diff = np.diff(padded.astype(np.int8), axis=1)
    starts = np.argwhere(diff == 1)
    ends = np.argwhere(diff == -1)
    for (ry, sx), (_ry2, ex) in zip(starts, ends):
        out.append((int(ry), int(sx), int(ex)))
    return out


def _label(runs: Sequence[Tuple[int, int, int]]) -> Dict[int, List[int]]:
    """Union-find over runs; adjacent rows whose runs overlap are joined."""
    parent = list(range(len(runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_row: Dict[int, List[int]] = {}
    for idx, (row, _s, _e) in enumerate(runs):
        by_row.setdefault(row, []).append(idx)
    for row, here in by_row.items():
        for above in by_row.get(row - 1, ()):
            _r, as_, ae = runs[above]
            for idx in here:
                _r2, s, e = runs[idx]
                if s < ae and as_ < e:       # horizontal overlap
                    union(idx, above)

    groups: Dict[int, List[int]] = {}
    for idx in range(len(runs)):
        groups.setdefault(find(idx), []).append(idx)
    return groups


def _boxes(runs, groups, min_area):
    out = []
    for members in groups.values():
        area = sum(runs[i][2] - runs[i][1] for i in members)
        if area < min_area:
            continue
        rows = [runs[i][0] for i in members]
        out.append([min(runs[i][1] for i in members), min(rows),
                    max(runs[i][2] for i in members), max(rows) + 1, area])
    return out


def _merge(boxes, gap):
    """Rejoin fragments of one slot split by the cog's head.

    The head is drawn over its own backdrop and usually spans the slot's
    full height, so the teal arrives as two pieces either side of it.
    Requiring one connected blob finds the plates whose cog is slim and
    silently misses the rest -- which looks like success on a single
    screenshot.
    """
    merged: List[List[int]] = []
    for x0, y0, x1, y1, area in sorted(boxes):
        for box in merged:
            if (x0 < box[2] + gap and box[0] < x1 + gap
                    and y0 < box[3] + gap and box[1] < y1 + gap):
                box[0], box[1] = min(x0, box[0]), min(y0, box[1])
                box[2], box[3] = max(x1, box[2]), max(y1, box[3])
                box[4] += area
                break
        else:
            merged.append([x0, y0, x1, y1, area])
    return merged


def _reject(log, x0, y0, x1, y1, filled, why: str) -> None:
    """Record a candidate that did not survive the filters.

    Opt-in: pass a list as `rejects` to `find_plates`. A missing plate is
    invisible otherwise -- the caller sees a shorter list and no reason --
    and every filter here is a threshold that a real plate can fall the
    wrong side of.
    """
    if log is not None:
        log.append({"box": (x0, y0, x1, y1), "w": x1 - x0, "h": y1 - y0,
                    "filled": filled, "why": why})


# A SECOND WAY TO FIND A PLATE, for zones where colour cannot.
#
# `teal_mask` is a box around one sampled triple, which works because the
# portrait backdrop is an unusual colour -- except in Bossbot HQ's icy
# cobblestone, where the mortar reads rgb(87,137,160) against a TEAL of
# (90,141,158): the mask matched 19.7% of the whole frame as one
# connected web, swallowing both plates into a blob the width filter
# then rejected. Neither capping run length nor an opening at radius 4
# helped (coverage only moved 19.75% -> 18.86%).
#
# So this anchors on the HEALTH BAR instead: saturated green, which the
# scenery lacks. `PARTS["health"]` gives the bar's box in slot-relative
# units, so inverting it gives the slot -- on the failing frame a 75x18
# bar at (948,185) predicts a slot at (881,123) 65x44, which really is
# 53% teal. The teal test still runs, just to CONFIRM one small box
# instead of searching the whole frame -- both cues must agree.
HEALTH_GREEN_MIN = 150           # the bar is bright, the scenery is not
HEALTH_GREEN_MARGIN = 60         # green over BOTH red and blue
# Bar aspect follows from `PARTS`: 1.15 slot widths by 0.41 slot
# heights on a slot near 1.48:1, so about 4.15 -- measured on the
# building frame as 75x18, aspect 4.17.
#
# KNOWN LIMIT: `PARTS["health"]` was calibrated on two FULL-health cogs,
# so inverting through the bar's width only holds while the bar is
# fairly full; a badly hurt cog draws too short a bar to pass the
# aspect band. Deriving the slot from the bar's HEIGHT instead would be
# fill-independent but admits far more candidates and needs a stronger
# verifier than teal -- useless in exactly the zone this exists for. A
# real change needing real frames to settle, not a constant to nudge.
HEALTH_ASPECT = (2.6, 6.0)
HEALTH_WIDTH_FRAC = (0.015, 0.14)
# How much of the predicted slot must actually be teal. The plate's own
# portrait is split by the cog's head, so this is never near 100%.
HEALTH_SLOT_TEAL_MIN = 0.20


def _health_bars(frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Boxes of saturated green that could be a cog's health meter."""
    rgb = frame[:, :, :3].astype(np.int16)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mask = ((green > HEALTH_GREEN_MIN)
            & (green - red > HEALTH_GREEN_MARGIN)
            & (green - blue > HEALTH_GREEN_MARGIN))
    height, width = mask.shape
    runs = _runs(mask)
    if not runs:
        return []
    out = []
    lo, hi = HEALTH_WIDTH_FRAC
    for x0, y0, x1, y1, _filled in _boxes(runs, _label(runs), 24):
        box_w, box_h = x1 - x0, y1 - y0
        if not box_h or not (width * lo <= box_w <= width * hi):
            continue
        if not HEALTH_ASPECT[0] <= box_w / box_h <= HEALTH_ASPECT[1]:
            continue
        out.append((x0, y0, x1, y1))
    return out


def find_plates_by_health(frame: np.ndarray,
                          rejects: Optional[List[dict]] = None
                          ) -> List["Plate"]:
    """Plates located from the health bar rather than the portrait.

    A FALLBACK, not a replacement: `find_plates` calls this only when
    the colour search found nothing, so no zone that works today can be
    changed by it.
    """
    left, top, right, bottom = PARTS["health"]
    plates = []
    for x0, y0, x1, y1 in _health_bars(frame):
        slot_w = (x1 - x0) / (right - left)
        slot_h = (y1 - y0) / (bottom - top)
        sx0 = int(round(x0 - left * slot_w))
        sy0 = int(round(y0 - top * slot_h))
        sx1, sy1 = int(round(sx0 + slot_w)), int(round(sy0 + slot_h))
        if sx0 < 0 or sy0 < 0 or sy1 > frame.shape[0] or sx1 > frame.shape[1]:
            _reject(rejects, sx0, sy0, sx1, sy1, 0,
                    "predicted slot falls outside the frame")
            continue
        teal = teal_mask(frame[sy0:sy1, sx0:sx1])
        share = float(teal.mean())
        if share < HEALTH_SLOT_TEAL_MIN:
            _reject(rejects, sx0, sy0, sx1, sy1, int(teal.sum()),
                    f"slot behind the bar is only {share:.0%} teal")
            continue
        plates.append(Plate(slot=(sx0, sy0, sx1, sy1),
                            filled=int(teal.sum())))
    return sorted(plates, key=lambda p: p.slot[0])


def find_plates(frame: np.ndarray,
                reference_area: Optional[int] = None,
                rejects: Optional[List[dict]] = None) -> List[Plate]:
    """Every cog plate in a battle frame, left to right.

    `frame` is an (H, W, 3) or (H, W, 4) array of uint8 RGB.

    `reference_area` overrides the frame area the size thresholds are
    computed from. It matters when searching a small crop of a larger
    frame: the thresholds are deliberately fractions of the frame, so on
    a 90x70 cut-out they collapse to almost nothing and antialiased
    pixels at the slot's edge start counting, moving the box by a few
    pixels. Since every plate region is a multiple of that box, a few
    pixels is enough to shift the health track and clip a digit.
    """
    height, width = frame.shape[:2]
    area = reference_area if reference_area else width * height

    runs = _runs(teal_mask(frame))
    if not runs:
        return []
    groups = _label(runs)
    boxes = _boxes(runs, groups, max(8, int(area * MIN_FRAGMENT_FRAC)))
    slots = _merge(boxes, max(4, int(width * MERGE_GAP_FRAC)))

    plates = []
    for x0, y0, x1, y1, filled in sorted(slots):
        box_w, box_h = x1 - x0, y1 - y0
        if not box_h or filled < area * MIN_SLOT_FRAC:
            _reject(rejects, x0, y0, x1, y1, filled,
                    f"too little teal: {filled} < "
                    f"{int(area * MIN_SLOT_FRAC)}")
            continue
        if box_w > width * MAX_SLOT_WIDTH_FRAC:
            _reject(rejects, x0, y0, x1, y1, filled,
                    f"too wide: {box_w} > {int(width * MAX_SLOT_WIDTH_FRAC)}"
                    f" -- teal in the scene merged into the slot?")
            continue
        if not ASPECT_RANGE[0] <= box_w / box_h <= ASPECT_RANGE[1]:
            _reject(rejects, x0, y0, x1, y1, filled,
                    f"aspect {box_w / box_h:.2f} outside "
                    f"{ASPECT_RANGE[0]}-{ASPECT_RANGE[1]}")
            continue
        # NOT FLUSH WITH THE FRAME EDGE: a cog plate always has game
        # behind it on every side, so a blob touching the border is
        # window chrome, letterboxing, or a capture clip. Measured
        # live: a 58x48 box at (793, 0) passed every filter above and
        # read level score 0.00 with 0% health -- the documented
        # scenery signature -- while the real second plate went
        # unfound. A genuinely clipped plate is rejected too, correctly:
        # its level and health regions are offsets from this box, so a
        # truncated one reads garbage, not nothing.
        if x0 <= 0 or y0 <= 0 or x1 >= width or y1 >= height:
            _reject(rejects, x0, y0, x1, y1, filled, "touches the frame edge")
            continue
        plates.append(Plate(slot=(x0, y0, x1, y1), filled=filled))
    if not plates:
        # THE COLOUR FOUND NOTHING, so try the health bar. Only on the
        # empty result, so a zone that reads today cannot be changed by
        # this -- and "nothing" is exactly the answer the icy cobblestone
        # of Bossbot HQ produces, where the mortar IS the portrait
        # colour and every plate is swallowed into one frame-wide blob.
        return find_plates_by_health(frame, rejects=rejects)
    return plates


def _denoise(mask: np.ndarray, keep_frac: float = 0.10) -> np.ndarray:
    """Drop blobs far smaller than the largest one.

    A single stray dark pixel (a rivet edge, compression artefact, the
    cog's body showing through) is enough to stretch the ink's bounding
    box well past the text, which shrinks every glyph relative to the
    templates it's normalised against and fails the comparison.
    Observed: a speck below the text turned an 18px-tall "Level 6" into
    a 32px box and dropped the correct match to IoU 0.08.

    Letters of "Level N" are all within an order of magnitude of each
    other, so a tenth of the largest blob separates text from grit.
    """
    runs = _runs(mask)
    if not runs:
        return mask
    groups = _label(runs)
    areas = {key: sum(runs[i][2] - runs[i][1] for i in members)
             for key, members in groups.items()}
    floor = max(areas.values()) * keep_frac
    cleaned = np.zeros_like(mask)
    for key, members in groups.items():
        if areas[key] >= floor:
            for i in members:
                row, start, end = runs[i]
                cleaned[row, start:end] = True
    return cleaned


def _ink(gray: np.ndarray, threshold: int = 110):
    """Tight crop of dark pixels, or None if the patch is blank.

    Plate text is near-black on brushed metal, so a fixed threshold is
    enough; the tight crop is what makes the comparison independent of
    where in the region the text happens to sit.
    """
    mask = _denoise(gray < threshold)
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _normalise(mask: np.ndarray, height: int = 24) -> np.ndarray:
    """Scale a binary mask to a fixed height, keeping its aspect."""
    from PIL import Image

    img = Image.fromarray((mask * 255).astype(np.uint8))
    width = max(1, round(img.width * height / img.height))
    return np.asarray(img.resize((width, height), Image.LANCZOS)) > 127


def _overlap(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection over union of two binary masks, centred and padded.

    CENTRED, not pinned to the top-left as both masks once were: a
    13px-wide glyph compared against a 15px template was offset by two,
    which is most of a stroke at these sizes (13-18px tall). It read as
    a template problem and was an alignment one -- "Level 8" scored 6 at
    0.701 over 8 at 0.689, twice, on different frames, every confusion
    being 6 vs 8 (which differ chiefly top-left, where misalignment hits
    hardest). Centring reads all six labelled samples correctly and
    takes the worst correct margin from 0.012 to 0.073.

    Grayscale also fixes it but separates less well (0.026-0.065 vs
    0.073-0.407), so this stays binary.
    """
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])

    def padded(mask: np.ndarray) -> np.ndarray:
        out = np.zeros((h, w), bool)
        top = (h - mask.shape[0]) // 2
        left = (w - mask.shape[1]) // 2
        out[top:top + mask.shape[0], left:left + mask.shape[1]] = mask
        return out

    pa, pb = padded(a), padded(b)
    union = (pa | pb).sum()
    return float((pa & pb).sum()) / float(union) if union else 0.0


def _components(mask: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Bounding boxes of each blob, left to right."""
    runs = _runs(mask)
    if not runs:
        return []
    boxes = []
    for members in _label(runs).values():
        rows = [runs[i][0] for i in members]
        boxes.append((min(runs[i][1] for i in members), min(rows),
                      max(runs[i][2] for i in members), max(rows) + 1))
    return sorted(boxes)


def _drop_tall_outliers(boxes, limit: float = 1.6):
    """Discard blobs far taller than the text they sit among.

    The level region reaches close enough to the plate's edge to catch
    its border, which thresholds as a thin vertical bar spanning the
    full height -- at 1440p a 4x40 sliver beat the real "8" as rightmost
    blob, returning a confident-looking level with score 0.07. Glyphs in
    one line of text share a height band; the border does not.
    """
    if len(boxes) < 3:
        return boxes
    heights = sorted(b[3] - b[1] for b in boxes)
    median = heights[len(heights) // 2]
    # AND BELOW THE LINE: "Level N" has no descenders, so glyphs share a
    # baseline and the border does not. Height alone let one through --
    # on a plate with a pixel-narrow slot, the border read 27px against
    # a 17px median (just inside the 1.6x limit) and, being rightmost,
    # was read as the level ("1", score 0.30) while the real "5" was
    # ignored.
    baselines = sorted(b[3] for b in boxes)
    baseline = baselines[len(baselines) // 2]
    kept = [b for b in boxes if (b[3] - b[1]) <= limit * median
            and b[3] - baseline <= 0.3 * median]
    return kept if len(kept) >= 2 else boxes


def level_glyphs(patch: np.ndarray):
    """The level number's glyphs as (mask, darkness) crops, left to right.

    The same split as `_digits_only` -- "Level" and the number, parted at
    the widest gap, the plate's border dropped -- but returning each digit
    of the number separately, with its greyscale (inverted, so ink is
    bright) for `digits.level_classifier`. `patch` is the plate's level
    region, RGB.
    """
    gray = np.asarray(patch, dtype=float)[..., :3].mean(axis=2)
    full = _denoise(gray < 110)
    if not full.any():
        return []
    ys, xs = np.nonzero(full)
    oy, ox = ys.min(), xs.min()
    mask = full[oy:ys.max() + 1, ox:xs.max() + 1]
    gray = gray[oy:ys.max() + 1, ox:xs.max() + 1]
    boxes = _drop_tall_outliers(_components(mask))
    if len(boxes) < 2:
        return []
    gaps = [(boxes[i + 1][0] - boxes[i][2], i) for i in range(len(boxes) - 1)]
    widest, at = max(gaps)
    typical = sorted(g for g, _ in gaps)[len(gaps) // 2]
    if widest <= typical:
        return []
    number = boxes[at + 1:]
    # One glyph per digit: blobs overlapping in x are one glyph.
    merged = []
    for b in number:
        if merged and b[0] < merged[-1][2]:
            m = merged[-1]
            merged[-1] = (m[0], min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3]))
        else:
            merged.append(b)
    return [(mask[y0:y1, x0:x1], 255.0 - gray[y0:y1, x0:x1])
            for x0, y0, x1, y1 in merged]


def _digits_only(mask: np.ndarray):
    """Split "Level 6" and keep the "6".

    Matching the whole string does not work: "Level " is six of the seven
    characters and identical in every template, so the overlap is
    dominated by the part that carries no information. Measured on a real
    plate, the correct level scored 0.47 while a wrong one scored 0.69.

    The word and the number are separated by a space wider than any gap
    between letters, so the widest gap is the split point.
    """
    boxes = _drop_tall_outliers(_components(mask))
    if len(boxes) < 2:
        return None
    gaps = [(boxes[i + 1][0] - boxes[i][2], i) for i in range(len(boxes) - 1)]
    widest, at = max(gaps)
    letter_gaps = [g for g, _ in gaps]
    typical = sorted(letter_gaps)[len(letter_gaps) // 2]
    if widest <= typical:
        return None                      # no clear word break
    x0 = boxes[at + 1][0]
    x1 = max(b[2] for b in boxes[at + 1:])
    y0 = min(b[1] for b in boxes[at + 1:])
    y1 = max(b[3] for b in boxes[at + 1:])
    return mask[y0:y1, x0:x1]


_LEVEL_TEMPLATES: Dict[int, np.ndarray] = {}


def level_templates(levels=range(1, 13)) -> Dict[int, np.ndarray]:
    """The rendered *number* of each level, from the game's own font.

    Numbers rather than the whole "Level N" string, and matched as a
    group rather than per glyph so that "12" needs no splitting into two
    characters. Width carries real information here -- a two-digit number
    is far wider relative to its height than a single digit.
    """
    if _LEVEL_TEMPLATES:
        return _LEVEL_TEMPLATES
    from PIL import Image, ImageDraw, ImageFont

    from . import ttr_assets

    font = ImageFont.truetype(str(ttr_assets.interface_font()), 64)
    for level in levels:
        canvas = Image.new("L", (400, 160), 255)
        ImageDraw.Draw(canvas).text((20, 20), str(level), font=font, fill=0)
        _LEVEL_TEMPLATES[level] = _normalise(_ink(np.asarray(canvas)))
    return _LEVEL_TEMPLATES


# How far the best level template must beat the runner-up -- same idea
# as MIN_DEPARTMENT_MARGIN: a high score says the region holds a
# legible digit, not that it's THIS digit.
#
# Evidence, from three reads of legible plate levels:
#
#     truth  read  score  runner-up  margin
#       6      6   0.793   8 @0.720   0.073
#       8      8   0.832   6 @0.726   0.106
#       8      6   0.709   8 @0.670   0.039   <- wrong
#
# The wrong read cleared MIN_LEVEL_SCORE but barely beat its runner-up.
# Every confusion here is 6 vs 8, the two `_normalise` makes look most
# alike. Three samples is thin, so this rejects the observed failure
# with little margin to spare -- failing towards "unreadable" (blocks a
# state) rather than a confident wrong level (plans for the wrong cog).
MIN_LEVEL_MARGIN = 0.05


def _holes(mask: np.ndarray, diagonal: bool, min_size: int = 2) -> int:
    """Closed loops in a binary glyph: background regions that cannot
    reach the border. `diagonal` lets background leak through pixels
    that touch only at a corner; specks under `min_size` are ignored."""
    padded = np.pad(np.asarray(mask, dtype=bool), 1)
    h, w = padded.shape
    seen = padded.copy()                 # ink is never background
    steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    loops = 0
    for sy in range(h):
        for sx in range(w):
            if seen[sy, sx]:
                continue
            stack, size, edge = [(sy, sx)], 0, False
            seen[sy, sx] = True
            while stack:
                y, x = stack.pop()
                size += 1
                edge = edge or y in (0, h - 1) or x in (0, w - 1)
                for dy, dx in steps:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if not edge and size >= min_size:
                loops += 1
    return loops


def loops(mask: np.ndarray) -> Optional[int]:
    """The glyph's loop count, or None when it depends on whether pixels
    touching at a corner are joined -- the count is then not evidence."""
    if mask is None or mask.size == 0:
        return None
    strict, loose = _holes(mask, False), _holes(mask, True)
    return strict if strict == loose else None


_TEMPLATE_LOOPS: Dict[int, Optional[int]] = {}


def template_loops() -> Dict[int, Optional[int]]:
    if not _TEMPLATE_LOOPS:
        for level, template in level_templates().items():
            _TEMPLATE_LOOPS[level] = loops(template)
    return _TEMPLATE_LOOPS


def read_level(frame: np.ndarray,
               plate: Plate) -> Tuple[Optional[int], float, float]:
    """The cog's level, how well it matched, and by how much it won.

    Returns (level, score, margin). `margin` is the gap to the
    second-best template, and a caller that ignores it will eventually
    act on a level that was a coin toss -- see MIN_LEVEL_MARGIN.

    (None, 0.0, 0.0) when the region holds no legible text, which
    happens while the plate is fading in.
    """
    x0, y0, x1, y1 = plate.region("level")
    patch = frame[max(0, y0):y1, max(0, x0):x1, :3]
    if patch.size == 0:
        return None, 0.0, 0.0
    from .digits import NET_DOUBT, level_classifier

    net = level_classifier()
    if net is not None:
        # THE LEARNED READER, when its weights are present. Same return
        # scales as the template path below, so the callers' gates hold:
        # score is the least confident digit's probability, and the
        # probability margin is mapped so that NET_DOUBT lands on
        # MIN_LEVEL_MARGIN. A number outside 1-12 is not a cog level.
        glyphs = level_glyphs(patch)
        if not glyphs:
            return None, 0.0, 0.0
        text, score, margin = "", 1.0, 1.0
        for _mask, darkness in glyphs:
            probs = net.probabilities(darkness)
            order = np.argsort(probs)[::-1]
            text += str(int(order[0]))
            score = min(score, float(probs[order[0]]))
            margin = min(margin, float(probs[order[0]] - probs[order[1]]))
        level = int(text)
        if not 1 <= level <= 12:
            return None, 0.0, 0.0
        return level, score, margin * (MIN_LEVEL_MARGIN / NET_DOUBT)
    mask = _ink(patch.mean(axis=2))
    if mask is None or mask.shape[0] < 4:
        return None, 0.0, 0.0
    digits = _digits_only(mask)
    if digits is None or digits.shape[0] < 4:
        return None, 0.0, 0.0

    observed = _normalise(digits)
    scored = sorted(((_overlap(observed, template), level)
                     for level, template in level_templates().items()),
                    reverse=True)
    if not scored:
        return None, 0.0, 0.0
    score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    # LOOPS AS A SECOND WITNESS: shape overlap confuses 5/6/8, and a cog
    # showing through the plate thins the strokes -- a clear "Level 5"
    # once read 5 at 0.754 over 6 at 0.707. But 5 has no closed loop, 6
    # has one, 8 has two. When the glyph's loop count is UNAMBIGUOUS
    # (same whether corner-touching pixels join or not) and AGREES with
    # the best template, rivals with a different count are ruled out and
    # the margin taken against whichever remains. It never overrules the
    # best match -- an ambiguous or disagreeing count (e.g. a 6 whose
    # hook touches its body at one corner pixel) just leaves the plain
    # margin for the caller's threshold to judge.
    seen = loops(digits)
    if seen is not None and template_loops().get(best) == seen:
        rivals = [s for s, lvl in scored[1:]
                  if template_loops().get(lvl) == seen]
        runner_up = rivals[0] if rivals else 0.0
    return best, score, score - runner_up


# How much the emblem's colour counts against its shape. The four
# emblems are tinted -- Bossbot warm, Sellbot red, Cashbot green, Lawbot
# blue -- and discarding that was the reason a Bossbot medallion could
# read as Sellbot at all: in greyscale a necktie and a bar chart are two
# similar arrangements of pale metal, while their tints differ in the
# green and blue channels by several units and never overlap. Shape is
# kept because tint alone is a three-number signature and a lit scene
# can shift it.
TINT_WEIGHT = 0.06

_EMBLEMS: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}


def _tint(rgb: np.ndarray) -> np.ndarray:
    """How a patch's channels depart from its own brightness.

    Subtracting the patch's mean brightness is what makes this survive
    the scene being lit differently from the flat texture atlas: it
    measures colour balance, not exposure.
    """
    mean = rgb.reshape(-1, 3).astype(float).mean(axis=0)
    return mean - mean.mean()


def emblem_templates() -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """Department emblems as (normalised greyscale, tint)."""
    if _EMBLEMS:
        return _EMBLEMS
    from PIL import Image

    from . import ttr_assets

    for dept, path in ttr_assets.department_emblems().items():
        with Image.open(path) as img:
            colour = img.convert("RGB").resize((48, 48), Image.LANCZOS)
        rgb = np.asarray(colour, dtype=float)
        grey = np.asarray(colour.convert("L"), dtype=float)
        _EMBLEMS[dept] = ((grey - grey.mean()) / (grey.std() or 1.0),
                          _tint(rgb))
    return _EMBLEMS


# How far the best emblem must beat the runner-up to be believed.
#
# With colour in the score the winning margin runs 0.21-0.61 across
# 854x480 to 4K, correct every time. On shape alone it was 0.07-0.22,
# and 720p picked the wrong department at a margin of 0.01 -- what this
# floor was sized to catch. It costs nothing when reads are clean, and
# is the only thing between an unreadable emblem and a candidate list
# narrowed to the wrong five cogs.
MIN_DEPARTMENT_MARGIN = 0.05


def read_department(frame: np.ndarray,
                    plate: Plate) -> Tuple[Optional[str], float]:
    """Which department's emblem is on the plate, and by what margin.

    The emblem is embossed metal on more metal, so absolute brightness
    says little and shape says everything -- hence zero-mean,
    unit-variance correlation rather than a difference of pixels.

    The returned score is the winning *margin* over the runner-up, not
    the correlation: a high correlation that every department shares
    means nothing, and the margin is what separates a real read from a
    coin toss. Compare it against `MIN_DEPARTMENT_MARGIN`.
    """
    from PIL import Image

    x0, y0, x1, y1 = plate.region("medallion")
    patch = frame[max(0, y0):y1, max(0, x0):x1, :3]
    if patch.size == 0:
        return None, 0.0

    colour = Image.fromarray(patch.astype(np.uint8)).resize(
        (48, 48), Image.LANCZOS)
    rgb = np.asarray(colour, dtype=float)
    grey = np.asarray(colour.convert("L"), dtype=float)
    grey = (grey - grey.mean()) / (grey.std() or 1.0)
    tint = _tint(rgb)

    scored = sorted(
        ((float((grey * shape).mean())
          - TINT_WEIGHT * float(np.linalg.norm(tint - hue)), dept)
         for dept, (shape, hue) in emblem_templates().items()),
        reverse=True)
    if len(scored) < 2:
        return (scored[0][1], 0.0) if scored else (None, 0.0)
    return scored[0][1], scored[0][0] - scored[1][0]


# How much to shrink the frame when hunting for plates from scratch. The
# teal slot is 66x45 at 1080p, so a quarter-size frame still leaves a
# 16x11 block -- comfortably above what the detector needs, since it
# finds 30x20 slots at 854x480. Every threshold in this module is a
# fraction of the frame rather than a pixel count, so they survive the
# change of scale without adjustment.
COARSE_DIVISOR = 4


# Teal in a quarter-size frame below this fraction of its pixels is
# treated as none at all. A single slot survives subsampling as tens of
# pixels, well clear of stray scenery.
COARSE_PRESENCE_FRAC = 0.00012


def any_plates(frame: np.ndarray,
               divisor: int = COARSE_DIVISOR) -> bool:
    """Whether the frame plausibly contains a cog plate.

    A cheap yes/no on a subsampled copy. It is deliberately *not* used to
    enumerate plates: subsampling drops the thin strips of backdrop
    beside a wide cog head, so a quarter-size scan finds one plate and
    misses its neighbour -- observed at 720p and 1440p on a two-cog
    frame. As a presence test that does not matter, because any one
    surviving plate is enough to trigger the exact scan.
    """
    if divisor <= 1:
        return bool(find_plates(frame))
    small = frame[::divisor, ::divisor]
    return bool(teal_mask(small).sum()
                >= max(12, small.shape[0] * small.shape[1]
                       * COARSE_PRESENCE_FRAC))


def locate_plates(frame: np.ndarray,
                  divisor: int = COARSE_DIVISOR) -> List[Plate]:
    """Find plates anywhere in the frame, skipping obviously empty ones.

    While no battle is running there is nothing to narrow the search to,
    so every poll would otherwise pay for a whole-frame scan: ~70ms at
    1080p, ~124ms at 1440p, forever, just to keep answering "no cogs".
    A subsampled presence test answers that in a few milliseconds, and
    the exact scan runs only once something teal shows up -- which is
    the first frame of a battle, after which the row band takes over.

    Plates it does return are found at full resolution, so their boxes
    are pixel-accurate; every plate region is a multiple of that box.
    """
    if not any_plates(frame, divisor):
        return []
    return find_plates(frame)


# The tile is a saturated red that nothing else near a plate wears. Set
# from the live frame the owner supplied rather than from the art files,
# which are not extractable for this element.
LURE_RED_MIN = 140          # red channel floor
LURE_RED_DOMINANCE = 55     # how far red must lead both other channels
LURE_MIN_PIXELS = 40        # below this it is a stray highlight


def lure_indicator(frame: np.ndarray, plate: Plate) -> bool:
    """Is this cog asleep on a Lure?

    The game draws a red tile above the plate showing the rounds left.
    Nothing read it, so the live advisor treated every cog as awake --
    and against a lured cog Throw and Squirt are forced to 100% with
    knockback, Drop always misses, and the cog does not attack. Four
    rules wrong at once, which is why the advice looked odd rather than
    merely suboptimal.

    A PRESENCE TEST, not a digit read. The tile also carries the rounds
    remaining, and reading it would be better -- but the digit reader
    already declines a plate's own level at these sizes, so promising a
    duration would be promising precision this cannot deliver. Asleep or
    awake is the part the forced accuracies turn on.
    """
    x0, y0, x1, y1 = plate.region("lure")
    height, width = frame.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return False
    return lure_pixels(frame, plate) >= LURE_MIN_PIXELS


def lure_pixels(frame: np.ndarray, plate: Plate) -> int:
    """How many pixels above the plate look like the lure tile.

    Split out so a report can show the margin rather than a yes/no. A
    false LURED is expensive -- it tells the solver that Throw and Squirt
    hit for certain and that the cog will not swing -- so the count
    matters when the verdict is in doubt.
    """
    x0, y0, x1, y1 = plate.region("lure")
    height, width = frame.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    patch = frame[y0:y1, x0:x1, :3].astype(np.int16)
    red = patch[:, :, 0]
    lead = red - np.maximum(patch[:, :, 1], patch[:, :, 2])
    return int(((red > LURE_RED_MIN) & (lead > LURE_RED_DOMINANCE)).sum())


def health_fraction(frame: np.ndarray, plate: Plate) -> float:
    """How full a cog's health meter is, in 0..1.

    Use this for *changes*, not as a source of truth for HP. The solver
    already knows each cog's HP exactly -- starting value from its level,
    and every point of damage it has dealt since -- so reading the number
    off the screen only introduces a second, worse answer. What it cannot
    derive is whether a gag hit, and a bar that moved between rounds says
    so cheaply, without having to parse gag animations or the floating
    damage numbers.

    The meter is a saturated bar on a dark track, shifting green ->
    yellow -> red as the cog is damaged, so the test is for saturation
    rather than for any one hue.
    """
    x0, y0, x1, y1 = plate.region("health")
    x0, y0 = max(0, x0), max(0, y0)
    strip = frame[y0:y1, x0:x1, :3].astype(np.int16)
    if strip.size == 0:
        return 0.0
    highest = strip.max(axis=2)
    lowest = strip.min(axis=2)
    lit = (highest > 150) & ((highest - lowest) > 120)
    columns = lit.any(axis=0)
    return float(columns.sum()) / float(len(columns)) if len(columns) else 0.0
