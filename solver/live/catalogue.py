"""Telling one cog from another by the head render on its plate.

Department and level are readable straight off the plate, but they do not
identify a cog: only 8 of the 48 (department, level) pairs name a single
cog, and the worst pairs allow five. The remaining evidence is the little
3D render of the cog's head in the plate's slot.

WHY A COLLECTED LIBRARY RATHER THAN SHIPPED ART
-----------------------------------------------
There is no per-cog icon in the game files to match against. `cogIcons`
is the four department emblems; the per-cog images that turn up in the
phase files (`flunky.jpg`, `spin-doctor.jpg`, ...) are texture skins for
3D models, not flat icons. The slot holds a live render, so the reference
has to be captured from a rendered frame.

That is less fragile than it sounds. The render uses a fixed camera, a
fixed light and a constant teal backdrop, so the same cog produces very
nearly the same pixels every time -- which is exactly the condition
template matching wants.

It also does not need a grind. The plate already narrows the field to at
most five candidates, so labelling is picking one of a handful, and each
cog needs answering once ever. Play normally, label what shows up.

WHAT IS STORED
--------------
A signature per cog: the slot resized to a small fixed grid, with the
teal backdrop masked out so the comparison is about the cog and not the
proportion of background it happens to cover. Signatures live in a JSON
index beside the PNG crops they came from, so a bad label can be
inspected and deleted by hand.
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

    def missing(self, among: Optional[Iterable[str]] = None) -> List[str]:
        """Cogs with no reference yet."""
        every = among or [c.key for d in data.COG_DEPARTMENTS.values()
                          for c in d.cogs]
        return sorted(set(every) - set(self.entries))

    def __len__(self) -> int:
        return len(self.entries)
