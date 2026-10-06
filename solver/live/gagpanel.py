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

* greyed -- usually unlocked with none carried, but NOT always: a track
  the game will not let you use this round is greyed too, digits and
  all (Toon-Up in a solo fight). The digit decides, never the colour.
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

# How much of its own span a broken row must actually colour in. A band
# interrupted by cell badges keeps nearly all of it; a scatter of
# scenery blobs that happens to span the width does not.
MIN_SPAN_COVERAGE = 0.65

# The widest hole a badge punches in a row band. Beyond this the colour
# belongs to something else -- the Shticky Notes page is close enough to
# TRAP's yellow to match, ~290px away from the row.
MAX_BADGE_GAP = 60

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
# ...but only as a ceiling. The floor actually used is a fraction of the
# brightest near-grey in the cell's own corner, so a track the game has
# darkened still reads. WHITE_FLOOR_MIN keeps an empty dark cell from
# finding ink in its own noise.
WHITE_FLOOR_FRAC = 0.80
WHITE_FLOOR_MIN = 70

# Deliberately loose. The count is drawn about 10x14 pixels at 1080p, so
# even a correct match scores modestly -- a thin "1" reached only 0.37
# against its own template while every wrong digit sat below 0.26. What
# separates right from wrong here is the gap to the runner-up, not the
# absolute figure.
MIN_DIGIT_SCORE = 0.30

# How far the winning digit must beat the runner-up. A score says the
# blob is a digit; only the margin says which. Measured over all 41
# digits on a real panel: the median margin is 0.128, the worst *correct*
# read is 0.063, and the single wrong read -- a 6 misread as a 5 -- sits
# at 0.011, with the true digit not even second. So this separates the
# one bad read from every good one with a 5.7x gap on either side.
#
# It cannot fix the read. What it does is turn a confident wrong number
# into a known-doubtful one, which is what lets the pouch label repair it
# -- see `_repair_with_label`.
MIN_DIGIT_MARGIN = 0.04


@dataclass(frozen=True)
class PanelCell:
    track: Track
    level: int                   # 1-7
    count: Optional[int]         # None when the gag is not unlocked
    unlocked: bool
    # The digits were legible but close to another digit -- see
    # MIN_DIGIT_MARGIN. The count is this cell's best guess and should
    # not be trusted on its own.
    uncertain: bool = False

    @property
    def carried(self) -> int:
        return self.count or 0


@dataclass(frozen=True)
class GagPanel:
    """Everything the gag menu says about a toon's inventory."""

    cells: List[PanelCell]
    panel: Tuple[int, int, int, int]
    # (carried, capacity) off the menu's own "Total gags" line, when it
    # could be read. This is the checksum -- see `checksum_problem`.
    label: Optional[Tuple[int, int]] = None

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

    def checksum_problem(self) -> Optional[str]:
        """Why this read cannot be trusted, or None if it adds up.

        The menu prints its own total, and the cells have to sum to it.
        For a long time this was described as a free checksum and never
        actually taken: `pouch_total` existed, nothing read the label,
        and nothing compared them. The first real frame the suite ever
        saw was off by one -- a Trap cell holding 6 read as 5 -- which
        is exactly the failure the check is for and exactly the kind
        that is invisible without it. A misread count does not look
        wrong downstream; it looks like a toon with one fewer gag, and
        the solver plans confidently around it.

        Returns a message rather than raising, because the caller
        (`session.build_state`) collects reasons a state cannot be
        built and shows them all at once.
        """
        from ..data import gags as gags_mod

        # IMPOSSIBLE COUNTS, label or no label. More of a gag than any
        # toon can carry is a misread -- on a compressed frame a "5" read
        # as "62" and as "81" -- and needs no total to prove it.
        for cell in self.cells:
            if not cell.count:
                continue
            try:
                most = gags_mod.carry_limit(cell.track, cell.level, 7)
            except Exception:                  # noqa: BLE001
                continue
            if cell.count > most:
                return (f"gag count misread: {cell.track.value} level "
                        f"{cell.level} reads {cell.count}, more than can be "
                        f"carried ({most}) -- no advice from it")
        if self.label is None:
            # NO TOTAL TO CHECK AGAINST. This used to wave everything
            # through, including cells the digit reader itself flagged as
            # doubtful -- and those are exactly the misreads the total
            # exists to catch. With the label unread, a doubtful pouch
            # cell has nothing behind it, so the read is refused.
            doubtful = [c for c in self.cells if c.uncertain and c.count
                        and c.level < gags_mod.POUCH_EXEMPT_LEVEL]
            if doubtful:
                names = ", ".join(f"{c.track.value} {c.level}"
                                  for c in doubtful[:3])
                return (f"gag counts uncertain ({names}) and the menu's "
                        f"total could not be read to check them -- no "
                        f"advice from it")
            return None                  # unread, not disagreeing
        carried, capacity = self.label
        counted = self.pouch_total()
        if counted == carried:
            return None
        return (f"gag counts do not add up: the cells total {counted} but "
                f"the menu says {carried}/{capacity}. A digit was misread, "
                f"so the pouch is wrong -- no advice from it")


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
            if _qualifies(hit[y], need):
                rows.append(int(y))
        if rows:
            found[track] = rows
    return {track: min(rows) for track, rows in found.items()}


def _qualifies(row: np.ndarray, need: int) -> bool:
    """Does this row of the mask look like a panel band?

    An unbroken run of `need` is the clean case. A row whose cells carry
    ORGANIC SPROUTS is the other one: the colour is all still there, cut
    into pieces by the badge on each cell. Live, an organic TRAP row read
    a longest run of 247px against a 288px requirement while the other
    six ran 862px -- and `find_panel` returns None the moment one row is
    missing, so a battle went undetected with the menu wide open.

    Organic is not a corner case. It is a permanent property of a track,
    so a toon with an organic track would have had every battle in that
    zone go unnoticed, forever, for as long as they kept the track.

    So a broken row also qualifies, on a stricter test than mere pixel
    count: it must SPAN at least `need`, and fill most of what it spans.
    That is what a decorated line looks like and what a patch of scenery
    does not -- scenery matches these colours in blobs, which neither
    span far nor fill what they span.
    """
    if _longest_run(row) >= need:
        return True
    lit = np.flatnonzero(row)
    if lit.size == 0:
        return False

    # MERGED ACROSS SMALL GAPS ONLY. Measuring first-lit to last-lit made
    # the span the distance to anything else on screen wearing the same
    # colour: TRAP spanned 1152px because the Shticky Notes page is a
    # pale yellow close enough to match, so the band and the notepad were
    # treated as one thing with a hole between them, and the fill came
    # out at 62% against a 65% floor.
    #
    # A badge interrupts a band by tens of pixels. Anything further apart
    # is a different object, so the merge stops there and each group is
    # judged on its own.
    breaks = np.flatnonzero(np.diff(lit) > MAX_BADGE_GAP)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [lit.size - 1]))
    for first, last in zip(starts, ends):
        span = int(lit[last] - lit[first]) + 1
        filled = int(last - first) + 1
        if span >= need and filled >= span * MIN_SPAN_COVERAGE:
            return True
    return False


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
    spacing = sorted(b - a for a, b in zip(tops, tops[1:]))
    if not spacing:
        return None
    # MEDIAN, not mean. With a row missing one gap is a double, and a
    # mean folds that into every later calculation; the median ignores it.
    height = spacing[len(spacing) // 2]
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
    label = read_pouch_label(frame, located=located)
    cells = _repair_with_label(cells, label)
    return GagPanel(cells=cells,
                    panel=(left, min(bands.values()), left + width, bottom),
                    label=label)


def _repair_with_label(cells: List[PanelCell],
                       label: Optional[Tuple[int, int]]) -> List[PanelCell]:
    """Recover a single doubtful count from the menu's own total.

    The checksum was built to *detect* a misread. It can also fix one,
    in the case where the answer is forced rather than guessed: if
    exactly one pouch cell is uncertain, every other cell is confident,
    and the label says the pouch holds N, then that cell holds N minus
    the rest. There is nothing to choose.

    This is worth doing because the digit reader cannot be fixed by
    thresholds alone. On the frame this was built from, the misread 6
    scored 0.594 as a 5 with an 8 second at 0.583 -- the correct digit
    did not place at all, so no tightening of the match recovers it.
    The label does, exactly.

    Deliberately narrow. Two uncertain cells make the split ambiguous
    and it declines; a difference that is negative or larger than the
    gag's carry limit means something else is wrong and it declines. In
    every declining case the checksum still fails afterwards and the
    state is still refused, which is the behaviour this replaces rather
    than weakens.

    Level 7 gags are outside the pouch and absent from the label, so an
    uncertain level-7 cell can never be solved this way.
    """
    from .. import data
    from ..data.gags import POUCH_EXEMPT_LEVEL

    if label is None:
        return cells
    doubtful = [c for c in cells
                if c.uncertain and c.level < POUCH_EXEMPT_LEVEL]
    if len(doubtful) != 1:
        return cells
    target = doubtful[0]
    rest = sum(c.carried for c in cells
               if c.level < POUCH_EXEMPT_LEVEL and c is not target)
    missing = label[0] - rest
    if missing < 0:
        return cells
    try:
        limit = data.gag(target.track, target.level).max_carry
    except (KeyError, ValueError, NotImplementedError):
        limit = None
    if limit is not None and missing > limit:
        return cells
    return [PanelCell(c.track, c.level, missing, c.unlocked, uncertain=False)
            if c is target else c
            for c in cells]


# The "Total gags" note, as fractions of the panel's own width so the
# same numbers hold from 480p to 4K. It sits to the right of the grid on
# a bright yellow sticky note.
NOTE_SEARCH_FRAC = 0.60          # of panel width, rightwards from its edge
NOTE_YELLOW = (180, 170, 140, 70)  # min red, min green, max blue, min r-b
LABEL_INK_MAX = 130              # the text is near-black on the yellow
# Well above what letters score against digit templates by accident --
# measured 0.70-0.76 for the real digits against 0.31-0.61 for the
# letters of "Total gags" on the line above.
MIN_LABEL_DIGIT_SCORE = 0.55
MAX_LABEL_DIGITS = 3


def read_pouch_label(frame: np.ndarray,
                     located=None) -> Optional[Tuple[int, int]]:
    """(carried, capacity) from the menu's "Total gags N / M" line.

    Read separately from the cells and by a different route, which is
    the entire point: two readings of the same quantity that share no
    machinery disagree when one of them is wrong. The cells are white
    digits on blue and this is near-black on yellow, so they do not even
    share an ink threshold.

    The line is picked out by its shape rather than its position:
    exactly one glyph in it fails to match any digit -- the slash --
    with one to three confident digits either side. The label sits under
    "Total gags", whose letters do match digit templates, but loosely
    and in the wrong arrangement.
    """
    from .vision import _components, _normalise, _overlap

    located = located or find_panel(frame)
    if located is None:
        return None
    left, width, bands, row_height = located
    tops = sorted(bands.values())

    x0 = left + width
    x1 = min(frame.shape[1], x0 + int(width * NOTE_SEARCH_FRAC))
    y0 = max(0, tops[0] - row_height)
    y1 = min(frame.shape[0], tops[-1] + 2 * row_height)
    side = frame[y0:y1, x0:x1, :3].astype(int)
    if side.size == 0:
        return None

    red, green, blue = side[:, :, 0], side[:, :, 1], side[:, :, 2]
    min_r, min_g, max_b, min_rb = NOTE_YELLOW
    yellow = ((red > min_r) & (green > min_g) & (blue < max_b)
              & ((red - blue) > min_rb))
    patches = _components(yellow)
    if not patches:
        return None
    nx0, ny0, nx1, ny1 = max(patches,
                             key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    note = side[ny0:ny1, nx0:nx1]
    if note.size == 0:
        return None

    ink = ((note[:, :, 0] < LABEL_INK_MAX) & (note[:, :, 1] < LABEL_INK_MAX)
           & (note[:, :, 2] < LABEL_INK_MAX))
    blobs = [b for b in _components(ink)
             if (b[3] - b[1]) >= 3 and (b[2] - b[0]) >= 2]

    # Group glyphs into text lines by vertical overlap.
    lines: List[dict] = []
    for box in sorted(blobs, key=lambda b: b[1]):
        for line in lines:
            if box[1] < line["y1"] and line["y0"] < box[3]:
                line["y0"] = min(line["y0"], box[1])
                line["y1"] = max(line["y1"], box[3])
                line["boxes"].append(box)
                break
        else:
            lines.append({"y0": box[1], "y1": box[3], "boxes": [box]})

    templates = digit_templates()
    for line in sorted(lines, key=lambda ln: -ln["y0"]):
        groups: List[str] = [""]
        ok = True
        for bx0, by0, bx1, by1 in sorted(line["boxes"]):
            glyph = _normalise(ink[by0:by1, bx0:bx1])
            best, score = None, 0.0
            for value, template in templates.items():
                overlap = _overlap(glyph, template)
                if overlap > score:
                    best, score = value, overlap
            if score >= MIN_LABEL_DIGIT_SCORE:
                groups[-1] += str(best)
            elif len(groups) == 1 and groups[0]:
                groups.append("")            # the slash
            else:
                ok = False                   # a second non-digit: not it
                break
        if not ok or len(groups) != 2:
            continue
        carried, capacity = groups
        if not carried or not capacity:
            continue
        if len(carried) > MAX_LABEL_DIGITS or len(capacity) > MAX_LABEL_DIGITS:
            continue
        if int(carried) > int(capacity):
            continue
        return int(carried), int(capacity)
    return None


def _read_cell(patch: np.ndarray, track: Track, level: int) -> PanelCell:
    # DOMINANCE, not brightness. `B > 130` was the test, and the game
    # darkens a whole track when it cannot be used this round -- the blue
    # drops under the floor, the cell reads as empty, and its gags vanish
    # from the pouch even though the digit is right there. A dimmed blue
    # cell is still far more blue than red; a grey empty one is not, and
    # that difference survives the dimming where brightness does not.
    blue = ((patch[:, :, 2] > 60)
            & (patch[:, :, 2] - patch[:, :, 0] > 25)).mean()
    if blue <= MIN_BLUE_FRAC:
        # Greyed. Usually unlocked-but-empty -- BUT READ THE DIGIT ANYWAY,
        # because grey does not mean empty. The game greys a whole track
        # it will not let you use this round, and Toon-Up in a solo fight
        # is the standing case: it heals teammates, so with nobody to heal
        # a Megaphone and a Lipstick carried five apiece were drawn in the
        # same grey as an empty cell. Returning 0 on colour alone dropped
        # all ten, the cells summed to 20 against a menu label of 30, and
        # the checksum refused the state -- blaming a misread digit when
        # the digit had never been looked at.
        #
        # Every grey cell prints its count, zeros included, so reading it
        # costs nothing. A grey cell that reads 0, or reads nothing, is
        # the certain zero it always was, so a true empty cannot pick up
        # doubt it did not have before and crowd out `_repair_with_label`.
        count, margin = _read_count(patch)
        if not count:
            return PanelCell(track, level, 0, unlocked=True)
        return PanelCell(track, level, count, unlocked=True,
                         uncertain=margin < MIN_DIGIT_MARGIN)

    count, margin = _read_count(patch)
    if count is None:
        # Blue-ish but with no digit at all: the slot the panel draws
        # where a gag has not been unlocked. Not the same as zero.
        return PanelCell(track, level, None, unlocked=False)
    return PanelCell(track, level, count, unlocked=True,
                     uncertain=margin < MIN_DIGIT_MARGIN)


# Below this brightness a pixel is never a count digit, whatever Otsu
# says. Low on purpose: a dimmed track draws its digits near 110.
COUNT_INK_FLOOR = 70
# How far the brightest pixel must stand above the corner's median before
# anything in it can be a digit. A plain grey or blue corner has no ink.
COUNT_MIN_CONTRAST = 40

# A count glyph's height and width as fractions of the row's height. The
# digits are all drawn at one size (0.205-0.233 tall, at most 0.19 wide,
# over 168 labelled cells), so a glyph outside this band is something
# else merged in -- the mouse cursor, a highlight -- and is doubtful.
COUNT_HEIGHT = (0.17, 0.27)
COUNT_MAX_WIDTH = 0.30


def _count_glyphs(patch: np.ndarray, region=None):
    """The count's glyphs as (mask, greyscale) crops, left to right.

    BRIGHTNESS, NOT COLOURLESSNESS. Ink used to be "near-white AND barely
    coloured". Video compression bleeds the cell's blue into thin white
    strokes, which then fail the colour test: on a recorded frame most of
    a "5" vanished and the remains read as "62". White digits are far
    brighter than any cell behind them, so ink is luminance above an Otsu
    threshold for this corner (and above COUNT_INK_FLOOR).

    RIGHT-ALIGNED. A gag icon's highlights can pass a brightness test too
    -- a Fog Horn's streaks read as extra "1"s, turning 1 into 111. The
    count is right-aligned on one baseline, so only the run of glyphs
    ending at the rightmost one is kept: close together, similar height.
    """
    from .digits import otsu
    from .vision import _components

    height, width = patch.shape[:2]
    x0, y0, x1, y1 = DIGIT_REGION if region is None else region
    corner = patch[int(y0 * height):int(y1 * height),
                   int(x0 * width):int(x1 * width), :3].astype(float)
    if corner.size == 0:
        return []
    luma = (0.299 * corner[..., 0] + 0.587 * corner[..., 1]
            + 0.114 * corner[..., 2])
    # RELATIVE TO THE CELL, not an absolute floor. The game dims a whole
    # track it will not let you use this round, digits and all -- to
    # ~110 on a ~40 background -- and a fixed floor of 150 erased them
    # (a live VP once summed 45 against a label of 70 that way). So ink
    # must stand clear of THIS corner's own background: an Otsu split,
    # at least halfway from the median to the brightest pixel, and a
    # corner with too little contrast has no digit at all.
    peak, middle = float(luma.max()), float(np.median(luma))
    if peak - middle < COUNT_MIN_CONTRAST:
        return []
    ink = luma > max(otsu(luma), middle + 0.5 * (peak - middle),
                     COUNT_INK_FLOOR)
    if ink.sum() < 6:
        return []
    blobs = [b for b in _components(ink)
             if (b[3] - b[1]) >= 3 and (b[2] - b[0]) < 0.8 * ink.shape[1]]
    boxes = [b for b in _merge_columns(blobs)
             if (b[2] - b[0]) >= 2 and (b[3] - b[1]) >= 5]
    if not boxes:
        return []
    boxes.sort()
    anchor = boxes[-1]
    tall = anchor[3] - anchor[1]
    kept = [anchor]
    for box in reversed(boxes[:-1]):
        if (kept[0][0] - box[2] > 0.5 * tall
                or (box[3] - box[1]) < 0.6 * tall
                or abs(box[3] - anchor[3]) > 3):
            break
        kept.insert(0, box)
    return [(ink[b[1]:b[3], b[0]:b[2]], luma[b[1]:b[3], b[0]:b[2]])
            for b in kept]


def _read_count(patch: np.ndarray) -> Tuple[Optional[int], float]:
    """The white number in a cell's lower-right corner, and how clearly.

    The learned reader (`digits.count_classifier`) when its weights are
    present, the template matcher otherwise. Either way the margin comes
    back on the template scale, so `margin < MIN_DIGIT_MARGIN` means
    "doubtful" for both: the classifier's probability margin is mapped so
    that its own threshold, `digits.NET_DOUBT`, lands on MIN_DIGIT_MARGIN.
    """
    from .digits import NET_DOUBT, count_classifier

    net = count_classifier()
    if net is None:
        return _read_count_templates(patch)
    glyphs = _count_glyphs(patch)
    if not glyphs:
        return None, 0.0
    row = float(patch.shape[0])
    digits, margin = "", 1.0
    for mask, gray in glyphs:
        digit, gap = net.classify(gray)
        digits += str(digit)
        margin = min(margin, gap)
        # THE WRONG SIZE IS DOUBT, however confident the read. Every
        # count is drawn at one size: 0.205-0.233 of the row's height
        # across 168 labelled cells. The mouse cursor sitting on a "4"
        # merged into one blob 0.329 tall and 0.48 wide, which the
        # classifier read as "2" with a margin of 0.85.
        h, w = mask.shape[0] / row, mask.shape[1] / row
        if not COUNT_HEIGHT[0] <= h <= COUNT_HEIGHT[1] or w > COUNT_MAX_WIDTH:
            margin = 0.0
    return int(digits), margin * (MIN_DIGIT_MARGIN / NET_DOUBT)


def _read_count_templates(patch: np.ndarray) -> Tuple[Optional[int], float]:
    """The white number in a cell's lower-right corner, and how clearly.

    Returns (value, margin), where margin is the smallest gap between a
    digit and its runner-up across the glyphs read. A caller that looks
    only at the value will eventually act on a coin toss: on a real
    panel a 6 was read as a 5 at a margin of 0.011, with the true digit
    not even placing second.
    """
    height, width = patch.shape[:2]
    x0, y0, x1, y1 = DIGIT_REGION
    corner = patch[int(y0 * height):int(y1 * height),
                   int(x0 * width):int(x1 * width)]
    if corner.size == 0:
        return None, 0.0
    hi, lo = corner.max(axis=2), corner.min(axis=2)
    # RELATIVE TO THIS CELL, not an absolute white. The game dims whole
    # tracks -- a row you cannot use this round is drawn darkened -- and
    # the digit dims with it. A fixed floor of 150 then finds no ink at
    # all and the count reads as nothing: on a live VP panel the cells
    # summed to 45 against a menu label of 70, with the darkened TRAP,
    # LURE and SOUND rows contributing none of their gags.
    #
    # The digit is the brightest near-grey in its corner whatever the
    # cell's brightness, so the floor scales with what is actually there.
    # The absolute floor stays as a lower bound: without it, an empty
    # dark cell would find "ink" in its own noise.
    peak = int(lo.max()) if lo.size else 0
    floor = max(WHITE_FLOOR_MIN, min(WHITE_FLOOR, int(peak * WHITE_FLOOR_FRAC)))
    ink = (lo > floor) & ((hi - lo) < 45)
    if ink.sum() < 6:
        return None, 0.0

    from .vision import _components, _normalise, _overlap

    # Discard rules and specks before merging, not after. The cell's
    # lower border thresholds as a 36x1 line spanning the whole corner,
    # and since it overlaps every column the merge below folds the digit
    # into it and the count vanishes.
    blobs = [b for b in _components(ink)
             if (b[3] - b[1]) >= 3 and (b[2] - b[0]) < 0.8 * ink.shape[1]]

    digits = ""
    margin = 1.0
    for x0b, y0b, x1b, y1b in _merge_columns(blobs):
        if (x1b - x0b) < 2 or (y1b - y0b) < 5:
            continue
        glyph = _normalise(ink[y0b:y1b, x0b:x1b])
        ranked = sorted(((_overlap(glyph, template), value)
                         for value, template in digit_templates().items()),
                        reverse=True)
        if not ranked:
            continue
        score, best = ranked[0]
        if score > MIN_DIGIT_SCORE:
            digits += str(best)
            runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
            margin = min(margin, score - runner_up)
    if not digits:
        return None, 0.0
    return int(digits), margin


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
