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
- The teal slot. A desaturated blue-green, and the best anchor of the
  three. It is *not* unique to plates, though this said so for a long
  time: the claim was checked against battle screenshots, where it
  holds, and not against the rest of the game, where it does not.
  Standing in Donald's Dreamland, 2.1% of a 1440p frame matched the
  mask and two blobs cleared both the size and the aspect filter.

  So `find_plates` finds plate-*shaped* teal and nothing more. Deciding
  whether a frame is a battle needs a second signal and belongs to the
  caller -- `watch.BattleWatcher.in_battle` requires the gag menu too.

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

# And a ceiling, of frame WIDTH. The aspect and minimum-size filters both
# pass on large teal scenery: a grey-blue machine in the background of a
# Lullaby Lane street matched as a 629x391 "plate", aspect 1.61, in a
# frame whose real plates were 69x47 and 65x45.
#
# A plate is drawn at a fixed scale by a battle camera that barely moves,
# and measured at 3.4-3.6% of frame width across every capture so far.
# This is more than three times that, so a genuine plate has room to be
# much closer than any yet seen while a third of the screen is still
# refused.
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
    # The emblem is a circle, and the box has to be the circle rather
    # than a rectangle near it. An earlier guess sat 0.15 slot widths too
    # far left, catching plate metal on one side while clipping the disc
    # on the other; resized against a square template that mismatch
    # dropped correlation to noise and picked the wrong department.
    # Measured: 43x43px on a 66x45 slot, i.e. square, as a disc should be.
    "medallion": (0.20, 1.16, 0.85, 2.11),
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


def find_plates(frame: np.ndarray,
                reference_area: Optional[int] = None) -> List[Plate]:
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
            continue
        if box_w > width * MAX_SLOT_WIDTH_FRAC:
            continue
        if not ASPECT_RANGE[0] <= box_w / box_h <= ASPECT_RANGE[1]:
            continue
        # NOT FLUSH WITH THE FRAME EDGE. A cog plate floats above the
        # cog and always has game behind it on every side; a blob that
        # runs into the border is the window chrome, a letterboxing bar,
        # or something clipped by the capture. Measured live: a 58x48
        # box at (793, 0) passed every test above and read level score
        # 0.00 with 0% health, which is the documented scenery
        # signature, while the real second plate went unfound.
        #
        # A genuinely clipped plate is rejected too, and should be: the
        # level and health regions are offsets from this box, so a
        # truncated one reads garbage rather than nothing.
        if x0 <= 0 or y0 <= 0 or x1 >= width or y1 >= height:
            continue
        plates.append(Plate(slot=(x0, y0, x1, y1), filled=filled))
    return plates


def _denoise(mask: np.ndarray, keep_frac: float = 0.10) -> np.ndarray:
    """Drop blobs far smaller than the largest one.

    A single stray dark pixel -- a rivet edge, a compression artefact,
    the cog's body showing through the plate -- is enough to stretch the
    ink's bounding box well past the text. Since the box is what the
    normalisation scales by, one speck shrinks the glyphs relative to the
    templates and every comparison then fails. Observed: a speck below
    the text turned an 18px-tall "Level 6" into a 32px box and dropped
    the correct match to IoU 0.08.

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

    CENTRED, WHICH IT WAS NOT. Both masks used to be pinned to the top
    left of the padded box, so a glyph 13 pixels wide compared against a
    15-pixel template was offset by two -- and these glyphs are 13 to 18
    pixels tall, so two pixels is most of a stroke.

    It read as a template problem and was an alignment problem. A plate
    saying "Level 8" scored 6 at 0.701 over 8 at 0.689, twice, on
    different frames; every confusion in the sample was 6 against 8,
    which differ chiefly in the top left -- exactly where a horizontal
    misalignment does its damage. Centring the pad reads all six
    labelled samples correctly and takes the worst correct margin from
    0.012 to 0.073.

    A grayscale comparison also fixes them, and separates less well
    (0.026-0.065 against 0.073-0.407), so this stays binary.
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

    The level region reaches close enough to the edge of the plate to
    catch its border, which thresholds as a thin vertical bar spanning
    the full height. Being the rightmost blob, it was stealing the role
    of the digit: at 1440p a 4x40 sliver beat the real "8", which is why
    the reader returned a confident-looking level with a score of 0.07.

    Glyphs in one line of text share a height band; the border does not.
    """
    if len(boxes) < 3:
        return boxes
    heights = sorted(b[3] - b[1] for b in boxes)
    median = heights[len(heights) // 2]
    kept = [b for b in boxes if (b[3] - b[1]) <= limit * median]
    return kept if len(kept) >= 2 else boxes


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


# How far the best level template must beat the runner-up. Same idea and
# same value as MIN_DEPARTMENT_MARGIN, and it exists for the same reason:
# an absolute score says the region holds a legible digit, and says
# nothing about whether it is *this* digit.
#
# The evidence, from three reads of plates whose levels are legible in
# the image:
#
#     truth  read  score  runner-up  margin
#       6      6   0.793   8 @0.720   0.073
#       8      8   0.832   6 @0.726   0.106
#       8      6   0.709   8 @0.670   0.039   <- wrong
#
# The wrong one cleared MIN_LEVEL_SCORE comfortably; what it did not do
# is beat its runner-up by anything. Every confusion in the set is 6
# against 8, which are the two that survive `_normalise` looking most
# alike. Three samples is thin, so this is set to reject the observed
# failure with room and no more -- and it fails towards "unreadable",
# which blocks a state, rather than towards a confident wrong level,
# which produces a plan for a different cog with different HP.
MIN_LEVEL_MARGIN = 0.05


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
# 854x480 to 4K, and the right department wins at every one of them. On
# shape alone it was 0.07-0.22 and 720p picked the wrong department at a
# margin of 0.01, which is what this floor was originally sized to
# catch. It is left where it is: the floor costs nothing when the reads
# are clean, and it is the only thing standing between an unreadable
# emblem and a candidate list narrowed to the wrong five cogs.
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
