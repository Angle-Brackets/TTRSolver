"""Telling one cog from another by the head render on its plate.

Department and level alone don't identify a cog: only 8 of 48 pairs name
a single cog, the worst allow five. The remaining evidence is the
plate's 3D head render.

No per-cog icon ships in the game files to match against -- `cogIcons`
is just the four department emblems, and the per-cog images in the phase
files are texture skins, not flat icons. So the reference has to be a
captured render, which works because the render's camera, light and
teal backdrop are fixed: the same cog gives nearly the same pixels every
time.

Labelling costs little: the plate narrows candidates to at most five, so
each cog needs answering once, ever, while playing normally.

Stored per cog: the slot resized to a small fixed grid with the teal
backdrop masked out, so comparison is about the cog, not how much
background it covers. Signatures live in a JSON index beside the PNG
crops they came from, so a bad label can be inspected and deleted by
hand.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .. import data
from .vision import TEAL, TOLERANCE, Plate

# The signature grid. Small enough that lighting jitter and a pixel of
# camera drift do not matter, large enough to tell a Flunky from a
# Micromanager.
GRID = (24, 16)          # (height, width)

DEFAULT_DIR = Path(__file__).resolve().parent / "_cog_heads"

# Below this, treat the match as unknown rather than guessing. Distances
# are mean absolute difference over masked, normalised pixels.
MAX_DISTANCE = 0.22

# The bar for a match that beat nothing, because its pool held one known
# cog. See `Match.confident`. Correct matches measured at 0.000, 0.020
# and 0.028 against wrong cogs at 0.132-0.157, so this sits in a gap
# nearly five times wide -- but it is three readings of two cogs, and it
# should be revisited once the library is fuller.
MAX_UNVERIFIED_DISTANCE = 0.08


@dataclass(frozen=True)
class Match:
    cog: str
    distance: float
    runner_up: Optional[str] = None
    runner_up_distance: float = float("inf")

    @property
    def margin(self) -> float:
        return self.runner_up_distance - self.distance

    @property
    def confident(self) -> bool:
        """Whether this match is worth acting on.

        With a runner-up, `margin` does the work and the absolute
        distance just has to be sane.

        WITHOUT ONE, MARGIN IS INFINITY AND MEANS NOTHING -- not
        hypothetical: the library fills one cog at a time, so for a long
        while every pool has exactly one known candidate, and a single
        Spin Doctor entry once matched every Lawbot level 6-10 at
        "confidence" for want of anything else to beat.

        So an unverified match is held to MAX_UNVERIFIED_DISTANCE
        instead: correct matches measure 0.000-0.028, wrong ones
        0.132-0.157, and this threshold sits nearer triple the worst
        correct reading than half the best wrong one.
        """
        if self.runner_up is None:
            return self.distance <= MAX_UNVERIFIED_DISTANCE
        return self.distance <= MAX_DISTANCE and self.margin > 0.02


def candidates(department: Optional[str], level: Optional[int]) -> List[str]:
    """Cog keys consistent with what the plate already told us.

    With neither reading available this is every cog; with both it is at
    most five, and sometimes exactly one.
    """
    out = []
    for dept, dept_data in data.COG_DEPARTMENTS.items():
        if department and dept != department:
            continue
        for cog in dept_data.cogs:
            if level is not None and level not in cog.levels:
                continue
            out.append(cog.key)
    return sorted(out)


def signature(frame: np.ndarray, plate: Plate) -> np.ndarray:
    """A comparable fingerprint of the head render in a plate's slot.

    The backdrop is masked out and the remaining pixels are normalised,
    so two captures of the same cog match even if the frame was brighter
    or the slot a different size on screen.
    """
    from PIL import Image

    x0, y0, x1, y1 = plate.slot
    patch = frame[max(0, y0):y1, max(0, x0):x1, :3]
    if patch.size == 0:
        return np.zeros(GRID + (4,), dtype=float)

    small = np.asarray(
        Image.fromarray(patch.astype(np.uint8)).resize(
            (GRID[1], GRID[0]), Image.LANCZOS), dtype=float)

    backdrop = np.all(np.abs(small - np.array(TEAL)) < TOLERANCE, axis=2)
    head = ~backdrop
    if head.sum() < 8:                       # slot is empty or all teal
        return np.zeros(GRID + (4,), dtype=float)

    # Normalise colour over the head pixels only, so overall scene
    # brightness drops out but the cog's own colouring survives.
    values = small[head]
    centred = (small - values.mean(axis=0)) / (values.std(axis=0) + 1e-6)
    centred[backdrop] = 0.0
    return np.dstack([centred, head.astype(float)])


def distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference over pixels either signature calls head."""
    overlap = np.maximum(a[:, :, 3], b[:, :, 3])
    total = overlap.sum()
    if total < 8:
        return float("inf")
    diff = np.abs(a[:, :, :3] - b[:, :, :3]).mean(axis=2)
    return float((diff * overlap).sum() / total / 6.0)


class HeadCatalogue:
    """Reference head signatures, on disk, one entry per cog."""

    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else DEFAULT_DIR
        self.index_path = self.directory / "index.json"
        self.entries: Dict[str, np.ndarray] = {}
        self._load()

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        for cog, values in raw.get("cogs", {}).items():
            self.entries[cog] = np.asarray(values, dtype=float).reshape(
                GRID + (4,))

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "grid": list(GRID),
            "note": ("Captured from rendered frames; see "
                     "solver/live/catalogue.py. Delete an entry to "
                     "relabel that cog."),
            "cogs": {cog: sig.reshape(-1).round(4).tolist()
                     for cog, sig in sorted(self.entries.items())},
        }
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")

    def add(self, cog: str, frame: np.ndarray, plate: Plate,
            keep_crop: bool = True) -> None:
        """Record `cog`'s head, overwriting any previous entry."""
        known = {c.key for d in data.COG_DEPARTMENTS.values() for c in d.cogs}
        if cog not in known:
            raise KeyError(f"unknown cog {cog!r}")
        self.entries[cog] = signature(frame, plate)
        if keep_crop:
            self._write_crop(cog, frame, plate)
        self.save()

    def _write_crop(self, cog: str, frame: np.ndarray, plate: Plate) -> None:
        """Keep the source image so a bad label can be seen and fixed."""
        from PIL import Image

        self.directory.mkdir(parents=True, exist_ok=True)
        x0, y0, x1, y1 = plate.slot
        patch = frame[max(0, y0):y1, max(0, x0):x1, :3]
        Image.fromarray(patch.astype(np.uint8)).save(
            self.directory / f"{cog}.png")

    def match(self, frame: np.ndarray, plate: Plate,
              among: Optional[Sequence[str]] = None) -> Optional[Match]:
        """Best known cog for this plate, restricted to `among` if given."""
        pool = [c for c in (among or self.entries) if c in self.entries]
        if not pool:
            return None
        sig = signature(frame, plate)
        ranked = sorted((distance(sig, self.entries[c]), c) for c in pool)
        best_distance, best = ranked[0]
        if len(ranked) == 1:
            return Match(best, best_distance)
        return Match(best, best_distance, ranked[1][1], ranked[1][0])

    def eliminate(self, frame: np.ndarray, plate: Plate,
                  among: Sequence[str]) -> Optional[str]:
        """The only cog left, when every known candidate is ruled out.

        The plate narrows a cog to at most five, and the library learns
        them one at a time, so there is a moment in every group where
        all but one are known. If none of those match, the remaining one
        is the answer by deduction, not resemblance -- the same
        reasoning as reading four names off a list of five.

        This is why the library never has to be finished: the last cog
        in each group needs no label, and since cogs appear at several
        levels, one unknown in one group is often deducible in another.

        Refuses unless airtight:

        * exactly one candidate unknown -- two leaves a choice
        * at least one candidate known -- a lone unknown rules out
          nothing
        * every known candidate ruled out at MAX_UNVERIFIED_DISTANCE
          (correct matches measure 0.000-0.028, wrong ones 0.132-0.157)

        Deliberately does NOT record what it deduces: a signature is
        written once and consulted forever, so a wrong entry poisons
        every later match, while a wrong deduction costs one battle.
        `read_battle --label` is where a human turns a deduction into a
        stored entry.
        """
        unknown = [c for c in among if c not in self.entries]
        known = [c for c in among if c in self.entries]
        if len(unknown) != 1 or not known:
            return None
        sig = signature(frame, plate)
        for cog in known:
            if distance(sig, self.entries[cog]) <= MAX_UNVERIFIED_DISTANCE:
                return None              # one of the known ones may be it
        return unknown[0]

    def missing(self, among: Optional[Iterable[str]] = None) -> List[str]:
        """Cogs with no reference yet."""
        every = among or [c.key for d in data.COG_DEPARTMENTS.values()
                          for c in d.cogs]
        return sorted(set(every) - set(self.entries))

    def __len__(self) -> int:
        return len(self.entries)
