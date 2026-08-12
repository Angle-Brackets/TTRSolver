"""Reading a Toontown battle off the screen.

The Local API knows the toon and nothing about the fight (see
`ttr_local`), so the cogs have to be read from the rendered frame. This
module finds the cog plates -- the metal signs TTR draws above each cog
when `show-cog-levels` is on -- and returns their geometry. Interpreting
what is inside them is the caller's job.

FINDING THE PLATES
------------------
The anchor is the flat teal square behind each cog's head render. Three
things were tried and two rejected:

- Fixed coordinates. The plate is drawn in 3D above the cog, so it moves
  with the camera, the cog's position, and how many cogs are present.
- The metal plate itself. Brushed grey has poor contrast against
  cobblestone, pavement and Cog HQ interiors, which is most of the game.
- The teal slot. A desaturated blue-green that appears nowhere else in
  Toontown's high-key palette. This one works.

NOTHING HERE IS IN ABSOLUTE PIXELS
----------------------------------
Every threshold is a fraction of the frame and every sub-region of a
plate is a multiple of its own slot. The same battle may be rendered
anywhere from 480p to 4K, and the plate is drawn larger when the camera
is closer, so a constant tuned at 1080p is a constant that breaks
everywhere else. Verified to find both plates in a two-cog battle at
854x480, 720p, 900p, 1080p, 1440p and 2160p.
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
MIN_SLOT_FRAC = 0.00058          # of frame area

# The slot is a fixed-aspect rectangle. Measured 1.44-1.52 across six
# resolutions; the window is wider than that to tolerate a cog head that
# eats into one edge of the backdrop.
ASPECT_RANGE = (1.15, 1.85)

# Sub-regions of a plate, as multiples of its slot's width and height:
# (left, top, right, bottom). Derived from a 1080p frame and confirmed to
# land correctly on both plates of a two-cog battle.
PARTS: Dict[str, Tuple[float, float, float, float]] = {
    "level": (1.15, 0.05, 2.55, 0.95),
    "medallion": (0.05, 1.20, 0.80, 2.10),
    # Calibrated to the meter's *track*, not a box drawn around it. Both
    # cogs in the reference frame were at full health, so the extent of
    # saturated pixels is exactly the full-bar extent; the two plates
    # agreed to within 0.03 slot widths. A hand-drawn box read a full
    # bar as 83% full, which would have made every use of this wrong.
    "health": (1.03, 1.42, 2.18, 1.83),
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
    """Boolean mask of pixels close to the portrait backdrop colour."""
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


def find_plates(frame: np.ndarray) -> List[Plate]:
    """Every cog plate in a battle frame, left to right.

    `frame` is an (H, W, 3) or (H, W, 4) array of uint8 RGB.
    """
    height, width = frame.shape[:2]
    area = width * height

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
            continue
        if not ASPECT_RANGE[0] <= box_w / box_h <= ASPECT_RANGE[1]:
            continue
        plates.append(Plate(slot=(x0, y0, x1, y1), filled=filled))
    return plates


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
