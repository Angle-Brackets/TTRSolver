"""Reading gag counts off the in-battle gag menu.

The Local API reports which gags a toon has *unlocked* and whether a
track is organic, but never how many of each it is carrying -- the whole
of `/gags.json` is seven tracks by three fields, and none of them is a
count. The gag menu shows them, so they are read from the screen.

That leaves every solver input covered without typing: laff and track
training from the API, counts from here, cogs from `vision`.

FINDING THE PANEL
-----------------
Each track's row is backed by its own colour -- the same seven Toontown
has always used -- and each spans the panel's full width. Matching those
colours anywhere in the frame is far too loose, since a purple cog or a
green lawn will match too; what identifies a row is a *long contiguous
run* of the colour. Seven such runs, at a consistent left edge and even
spacing, is a gag panel and nothing else is.

The rows then give the panel's geometry directly: left edge, width, and
one y per track, with no separate search for the panel's frame.

CELL STATES
-----------
Three, and they must not be confused:

* greyed -- the gag is unlocked but none are carried, so the count is 0
* blue with a white digit -- carried, and the digit is the count
* blank -- the gag is not unlocked at that level at all, which is not
  the same as carrying none of it

The third looked like a bug when Drop, trained to 6, produced a seventh
cell with no digit in it. Reporting that as 0 would be wrong in a way
the solver would act on, since a level-7 Drop is not a gag this toon can
ever be holding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..state import Track

# The seven track row colours, in the order the panel lists them.
ROW_COLOURS: List[Tuple[Track, Tuple[int, int, int]]] = [
    (Track.TOON_UP, (218, 165, 255)),
    (Track.TRAP, (250, 255, 130)),
    (Track.LURE, (90, 206, 87)),
    (Track.SOUND, (93, 108, 239)),
    (Track.THROW, (255, 157, 87)),
    (Track.SQUIRT, (255, 84, 205)),
    (Track.DROP, (98, 245, 255)),
]

COLOUR_TOLERANCE = 26

# A row's colour band must run at least this fraction of the frame width
# to count. Scenery matches the colours in patches; only the panel
# matches them in a long unbroken line.
MIN_RUN_FRAC = 0.15

# Cell grid, as fractions of the panel's width. Measured from a 1080p
# frame: a 149px label area, then seven 91px cells on a 97.7px pitch.
CELL_LEFT = 0.2065
CELL_PITCH = 0.1133
CELL_WIDTH = 0.1056
CELLS_PER_ROW = 7

# Where the count sits inside a cell, and how blue a cell must be to
# count as holding anything.
DIGIT_REGION = (0.60, 0.45, 1.00, 0.95)
MIN_BLUE_FRAC = 0.20

# The count is white on blue. A high floor clips the glyph's antialiased
# edges and breaks it into pieces; this is low enough to keep a digit
# whole while still excluding the cell's own pale highlight.
WHITE_FLOOR = 150

# Deliberately loose. The count is drawn about 10x14 pixels at 1080p, so
# even a correct match scores modestly -- a thin "1" reached only 0.37
# against its own template while every wrong digit sat below 0.26. What
# separates right from wrong here is the gap to the runner-up, not the
# absolute figure.
MIN_DIGIT_SCORE = 0.30


@dataclass(frozen=True)
class PanelCell:
    track: Track
    level: int                   # 1-7
    count: Optional[int]         # None when the gag is not unlocked
    unlocked: bool

    @property
    def carried(self) -> int:
        return self.count or 0


@dataclass(frozen=True)
class GagPanel:
    """Everything the gag menu says about a toon's inventory."""

    cells: List[PanelCell]
    panel: Tuple[int, int, int, int]

    def counts(self) -> Dict[Tuple[Track, int], int]:
        """As `ToonState.gag_counts` wants it: only what is carried."""
        return {(c.track, c.level): c.count
                for c in self.cells if c.count}

    def track_exp(self) -> Dict[Track, int]:
        """Highest level unlocked per track, for the accuracy term.

        Derived from which cells exist rather than which hold gags: a
        track trained to 7 still contributes its full +60 accuracy with
        an empty pouch.
        """
        out: Dict[Track, int] = {}
        for cell in self.cells:
            if cell.unlocked:
                out[cell.track] = max(out.get(cell.track, 0), cell.level)
        return out

    def total(self) -> int:
        """Every gag carried, level 7s included."""
        return sum(c.carried for c in self.cells)

    def pouch_total(self) -> int:
        """What the menu's own "Total gags" label counts.

        Level 7 gags are carried outside the pouch, so the label omits
        them -- a frame holding 75 gags printed "Total gags 70 / 70",
        the difference being exactly its five level 7s. Comparing this
        against that label gives a free checksum on every capture: if
        they disagree, a digit was misread.
        """
        from ..data.gags import POUCH_EXEMPT_LEVEL

        return sum(c.carried for c in self.cells
                   if c.level < POUCH_EXEMPT_LEVEL)


def _row_bands(frame: np.ndarray) -> Dict[Track, int]:
    """The top y of each track's colour band, when all seven are present."""
    height, width = frame.shape[:2]
    need = int(width * MIN_RUN_FRAC)
    found: Dict[Track, List[int]] = {}

    for track, colour in ROW_COLOURS:
        hit = np.all(np.abs(frame[:, :, :3].astype(np.int16)
                            - np.array(colour)) < COLOUR_TOLERANCE, axis=2)
        rows = []
        for y in np.nonzero(hit.any(axis=1))[0]:
            if _longest_run(hit[y]) >= need:
                rows.append(int(y))
        if rows:
            found[track] = rows
    return {track: min(rows) for track, rows in found.items()}


def _longest_run(row: np.ndarray) -> int:
    """Longest unbroken stretch of True in a boolean row."""
    if not row.any():
        return 0
    idx = np.flatnonzero(np.diff(np.concatenate(
        ([0], row.view(np.int8), [0]))))
    return int((idx[1::2] - idx[::2]).max())


def _panel_bounds(frame: np.ndarray, band_rows: Dict[Track, int]):
    """Left edge and width of the panel, from the widest colour band."""
    height, width = frame.shape[:2]
    need = int(width * MIN_RUN_FRAC)
    best = None
    for track, colour in ROW_COLOURS:
        if track not in band_rows:
            continue
        y = band_rows[track]
        hit = np.all(np.abs(frame[y, :, :3].astype(np.int16)
                            - np.array(colour)) < COLOUR_TOLERANCE, axis=1)
        idx = np.flatnonzero(np.diff(np.concatenate(
            ([0], hit.view(np.int8), [0]))))
        if not len(idx):
            continue
        lengths = idx[1::2] - idx[::2]
        k = int(lengths.argmax())
        if lengths[k] >= need and (best is None or lengths[k] > best[1]):
            best = (int(idx[::2][k]), int(lengths[k]))
    return best


def find_panel(frame: np.ndarray) -> Optional[Tuple[int, int, Dict[Track, int], int]]:
    """(left, width, row tops, row height), or None if no panel is open."""
    bands = _row_bands(frame)
    if len(bands) < len(ROW_COLOURS):
        return None                      # a partly matched panel is not one
    bounds = _panel_bounds(frame, bands)
    if bounds is None:
        return None
    tops = sorted(bands.values())
    spacing = [b - a for a, b in zip(tops, tops[1:])]
    height = int(round(sum(spacing) / len(spacing))) if spacing else 0
    if height <= 0:
        return None
    return bounds[0], bounds[1], bands, height


def read_panel(frame: np.ndarray,
               track_exp: Optional[Dict[Track, int]] = None
               ) -> Optional[GagPanel]:
    """Read every cell of the gag menu, or None if it is not on screen.

    Pass `track_exp` -- `Snapshot.track_exp()` from the Local API -- when
    it is available. Whether a gag is unlocked is something the API
    states outright, and no amount of looking at pixels does it as well:
    an empty Toon-Up cell and a greyed Lure cell holding none of its gag
    differ by less than the variation between two greyed cells (std 42
    against 38 on a real frame). Reading counts is what the screen is
    good for; reading entitlements is not.

    Without it the reader still returns counts, and marks a cell
    unlocked when it can see a digit there.
    """
    located = find_panel(frame)
    if located is None:
        return None
    left, width, bands, row_height = located

    cells: List[PanelCell] = []
    for track, top in bands.items():
        trained = track_exp.get(track, 0) if track_exp is not None else None
        for col in range(CELLS_PER_ROW):
            level = col + 1
            if trained is not None and level > trained:
                cells.append(PanelCell(track, level, None, unlocked=False))
                continue
            x0 = left + round((CELL_LEFT + CELL_PITCH * col) * width)
            x1 = x0 + round(CELL_WIDTH * width)
            patch = frame[top:top + row_height, x0:x1, :3].astype(np.int16)
            if patch.size == 0:
                continue
            cells.append(_read_cell(patch, track, level))

    bottom = max(bands.values()) + row_height
    return GagPanel(cells=cells,
                    panel=(left, min(bands.values()), left + width, bottom))


def _read_cell(patch: np.ndarray, track: Track, level: int) -> PanelCell:
    blue = ((patch[:, :, 2] > 130)
            & (patch[:, :, 2] - patch[:, :, 0] > 45)).mean()
    if blue <= MIN_BLUE_FRAC:
        # Greyed: unlocked but empty. A cell that is neither blue nor
        # grey does not reach here -- see the digit check below.
        return PanelCell(track, level, 0, unlocked=True)

    count = _read_count(patch)
    if count is None:
        # Blue-ish but with no digit at all: the slot the panel draws
        # where a gag has not been unlocked. Not the same as zero.
        return PanelCell(track, level, None, unlocked=False)
    return PanelCell(track, level, count, unlocked=True)


def _read_count(patch: np.ndarray) -> Optional[int]:
    """The white number in a cell's lower-right corner."""
    height, width = patch.shape[:2]
    x0, y0, x1, y1 = DIGIT_REGION
    corner = patch[int(y0 * height):int(y1 * height),
                   int(x0 * width):int(x1 * width)]
    if corner.size == 0:
        return None
    hi, lo = corner.max(axis=2), corner.min(axis=2)
    ink = (lo > WHITE_FLOOR) & ((hi - lo) < 45)
    if ink.sum() < 6:
        return None

    from .vision import _components, _normalise, _overlap

    # Discard rules and specks before merging, not after. The cell's
    # lower border thresholds as a 36x1 line spanning the whole corner,
    # and since it overlaps every column the merge below folds the digit
    # into it and the count vanishes.
    blobs = [b for b in _components(ink)
             if (b[3] - b[1]) >= 3 and (b[2] - b[0]) < 0.8 * ink.shape[1]]

    digits = ""
    for x0b, y0b, x1b, y1b in _merge_columns(blobs):
        if (x1b - x0b) < 2 or (y1b - y0b) < 5:
            continue
        glyph = _normalise(ink[y0b:y1b, x0b:x1b])
        best, score = None, 0.0
        for value, template in digit_templates().items():
            overlap = _overlap(glyph, template)
            if overlap > score:
                best, score = value, overlap
        if best is not None and score > MIN_DIGIT_SCORE:
            digits += str(best)
    return int(digits) if digits else None


def _merge_columns(boxes):
    """Join blobs that occupy the same columns -- they are one glyph.

    The count is drawn small, and thresholding it splits a digit into
    stacked pieces: a "5" arrived as two boxes sharing an x-range,
    scoring 0.42 and 0.21 against templates that expect a whole glyph.
    Digits sitting side by side never share columns, so horizontal
    overlap is a safe rule for "same character" -- and it keeps
    two-digit counts apart, which matters when a pouch holds thirty
    Cupcakes.
    """
    merged: List[List[int]] = []
    for x0, y0, x1, y1 in sorted(boxes):
        for box in merged:
            if x0 < box[2] and box[0] < x1:          # columns overlap
                box[0], box[1] = min(x0, box[0]), min(y0, box[1])
                box[2], box[3] = max(x1, box[2]), max(y1, box[3])
                break
        else:
            merged.append([x0, y0, x1, y1])
    return [tuple(b) for b in merged]


_DIGITS: Dict[int, np.ndarray] = {}


def digit_templates() -> Dict[int, np.ndarray]:
    """0-9 rendered in the game's own interface font.

    Counts run past nine -- a pouch holds thirty Cupcakes -- so this
    matches single glyphs and joins them, rather than matching whole
    numbers the way the cog plate's level does.
    """
    if _DIGITS:
        return _DIGITS
    from PIL import Image, ImageDraw, ImageFont

    from . import ttr_assets
    from .vision import _ink, _normalise

    font = ImageFont.truetype(str(ttr_assets.interface_font()), 64)
    for value in range(10):
        canvas = Image.new("L", (200, 140), 255)
        ImageDraw.Draw(canvas).text((20, 20), str(value), font=font, fill=0)
        _DIGITS[value] = _normalise(_ink(np.asarray(canvas)))
    return _DIGITS
