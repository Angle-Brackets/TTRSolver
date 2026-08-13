"""Read a battle off a screenshot, and teach it the cogs it doesn't know.

    python -m solver.live.read_battle                 # newest screenshot
    python -m solver.live.read_battle shot.png        # a specific frame
    python -m solver.live.read_battle --label         # label what's new
    python -m solver.live.read_battle --status        # library coverage

Reading and labelling are the same walk over the plates. The reader says
what it can about each cog -- department, level, health, and the cog
itself where the head is already in the library -- and `--label` stops at
the ones it cannot name and asks, choosing from the handful the plate
allows rather than from all thirty-two.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .. import data
from . import ttr_assets
from .catalogue import HeadCatalogue, candidates
from .vision import (
    MIN_DEPARTMENT_MARGIN, find_plates, health_fraction, read_department,
    read_level,
    MIN_LEVEL_MARGIN,
)

MIN_LEVEL_SCORE = 0.55


def newest_screenshot(directory: Optional[Path] = None) -> Path:
    folder = directory or (ttr_assets.install_dir() / "screenshots")
    shots = sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime)
    if not shots:
        raise SystemExit(
            f"no screenshots in {folder}. Press F9 in a battle first.")
    return shots[-1]


def load(path: Path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"))


def describe(frame, catalogue: HeadCatalogue) -> List[dict]:
    """One record per cog plate, left to right."""
    out = []
    for plate in find_plates(frame):
        dept, margin = read_department(frame, plate)
        if margin < MIN_DEPARTMENT_MARGIN:
            dept = None                      # too close to call
        level, score, level_margin = read_level(frame, plate)
        if score < MIN_LEVEL_SCORE or level_margin < MIN_LEVEL_MARGIN:
            level = None                     # illegible, or too close to call
        pool = candidates(dept, level)
        match = catalogue.match(frame, plate, among=pool)
        out.append({"plate": plate, "department": dept,
                    "department_margin": margin, "level": level,
                    "level_score": score, "health": health_fraction(frame,
                                                                    plate),
                    "candidates": pool, "match": match})
    return out


def display(cog_key: str) -> str:
    for dept in data.COG_DEPARTMENTS.values():
        for cog in dept.cogs:
            if cog.key == cog_key:
                return cog.display
    return cog_key


def report(records: List[dict]) -> None:
    if not records:
        print("no cog plates found -- is 'show-cog-levels' on, and is the "
              "gag menu covering the cogs?")
        return
    for i, r in enumerate(records):
        dept = r["department"] or "?"
        level = r["level"] if r["level"] is not None else "?"
        match = r["match"]
        if match and match.confident:
            who = f"{display(match.cog)} (d={match.distance:.3f})"
        elif r["candidates"]:
            who = f"one of {len(r['candidates'])}: " + ", ".join(
                display(c) for c in r["candidates"])
        else:
            who = "unknown"
        print(f"  cog {i + 1}: {dept:8s} level {str(level):>2}  "
              f"hp {r['health']:>4.0%}  {who}")
        if r["department"] is None:
            print(f"           department unreadable "
                  f"(margin {r['department_margin']:.2f} < "
                  f"{MIN_DEPARTMENT_MARGIN})")
        if r["level"] is None:
            print(f"           level unreadable "
                  f"(score {r['level_score']:.2f} < {MIN_LEVEL_SCORE})")


def label(frame, records: List[dict], catalogue: HeadCatalogue) -> int:
    """Ask about every plate whose cog is not confidently known."""
    added = 0
    for i, r in enumerate(records):
        match = r["match"]
        if match and match.confident:
            continue
        pool = r["candidates"]
        if not pool:
            print(f"  cog {i + 1}: no candidates -- department and level "
                  f"both unreadable, skipping")
            continue
        print(f"\n  cog {i + 1}: {r['department'] or '?'} "
              f"level {r['level'] if r['level'] is not None else '?'}")
        for n, key in enumerate(pool, 1):
            known = " (already known)" if key in catalogue.entries else ""
            print(f"     {n}. {display(key)}{known}")
        print("     s. skip")
        try:
            choice = input("  which cog is it? ").strip().lower()
        except EOFError:
            print("  (no input available; run this in a terminal)")
            return added
        if choice in ("s", "", "skip"):
            continue
        try:
            key = pool[int(choice) - 1]
        except (ValueError, IndexError):
            print("  not a listed option, skipping")
            continue
        catalogue.add(key, frame, r["plate"])
        added += 1
        print(f"  recorded {display(key)}")
    return added


def status(catalogue: HeadCatalogue) -> None:
    missing = catalogue.missing()
    total = len(missing) + len(catalogue)
    print(f"head library: {len(catalogue)}/{total} cogs")
    if missing:
        print("still needed: " + ", ".join(display(c) for c in missing))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", nargs="?", help="screenshot to read")
    parser.add_argument("--label", action="store_true",
                        help="ask about cogs the library cannot name")
    parser.add_argument("--status", action="store_true",
                        help="show how much of the library is filled in")
    parser.add_argument("--dir", help="head library directory")
    args = parser.parse_args(argv)

    catalogue = HeadCatalogue(Path(args.dir) if args.dir else None)
    if args.status:
        status(catalogue)
        return 0

    path = Path(args.image) if args.image else newest_screenshot()
    print(f"reading {path.name}")
    frame = load(path)
    records = describe(frame, catalogue)
    report(records)

    if args.label:
        added = label(frame, records, catalogue)
        print(f"\nadded {added} cog(s); library now holds "
              f"{len(catalogue)}")
        status(catalogue)
    return 0


if __name__ == "__main__":
    sys.exit(main())
