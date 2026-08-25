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
import tempfile
from pathlib import Path
from typing import List, Optional

from .. import data
from . import ttr_assets
from .catalogue import HeadCatalogue, candidates
from .vision import (
    MIN_DEPARTMENT_MARGIN, find_plates, health_fraction, read_department,
    read_level,
    lure_indicator,
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
                    "lured": lure_indicator(frame, plate),
                    "level_score": score,
                    "level_margin": level_margin, "health": health_fraction(frame,
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
              f"hp {r['health']:>4.0%}"
              f"{'  LURED' if r.get('lured') else ''}  {who}")
        if r["department"] is None:
            print(f"           department unreadable "
                  f"(margin {r['department_margin']:.2f} < "
                  f"{MIN_DEPARTMENT_MARGIN})")
        if r["level"] is None:
            # SAY WHICH GATE FAILED. This printed the score against
            # MIN_LEVEL_SCORE whichever test failed, so a margin failure
            # read as "score 0.78 < 0.55" -- a false statement that sends
            # you looking at the wrong threshold.
            score, margin = r["level_score"], r.get("level_margin")
            if score < MIN_LEVEL_SCORE:
                print(f"           level unreadable: score {score:.2f} "
                      f"below {MIN_LEVEL_SCORE} -- nothing legible there")
            else:
                print(f"           level unreadable: score {score:.2f} is "
                      f"fine but margin "
                      f"{'?' if margin is None else format(margin, '.2f')} "
                      f"below {MIN_LEVEL_MARGIN} -- legible, but it could "
                      f"equally be another digit")


def comparison_sheet(frame, plate, pool: List[str],
                     out: Optional[Path] = None) -> Optional[Path]:
    """The head on screen, beside the art of every candidate.

    Labelling from the plate alone is guesswork, and it produced a wrong
    answer the first time it was tried: the portrait is 65x45 pixels,
    which is enough to see a shape and not enough to name it. Put it
    next to `visualizer/assets/cog-<dept>-<name>.png` and the same
    decision becomes obvious -- a Lawbot read as an Ambulance Chaser was
    plainly a Spin Doctor once the two were side by side, green head and
    brown hair against white with a red cross.

    Returns the path written, or None if PIL is missing or no candidate
    art exists. The caller must stay usable either way: this is an aid
    to the person answering, not a step in the pipeline.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:                              # pragma: no cover
        return None

    root = Path(__file__).resolve().parents[2] / "visualizer" / "assets"
    tiles, labels = [], []
    x0, y0, x1, y1 = plate.slot
    import numpy as np

    tiles.append(Image.fromarray(np.asarray(frame)[y0:y1, x0:x1, :3])
                 .resize((200, 200), Image.LANCZOS))
    labels.append("ON SCREEN")
    for key in pool:
        dept = data.department_of(key)
        path = root / f"cog-{dept}-{key}.png"
        if not path.is_file():
            continue
        art = Image.open(path).convert("RGB")
        # Top third: the plate shows a head, not a suit.
        tiles.append(art.crop((0, 0, art.width, art.height // 3))
                     .resize((200, 200), Image.LANCZOS))
        labels.append(key)
    if len(tiles) < 2:
        return None

    sheet = Image.new("RGB", (200 * len(tiles), 232), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    for i, (tile, name) in enumerate(zip(tiles, labels)):
        sheet.paste(tile, (200 * i, 30))
        draw.text((200 * i + 6, 9), name, fill=(255, 230, 80))
    # One file per cog. A single shared name overwrites the sheet for
    # cog 1 while it may still be open on screen, which is exactly when
    # it is being looked at.
    out = out or Path(tempfile.gettempdir()) / "ttr_label_candidates.png"
    sheet.save(out)
    return out


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
        sheet = comparison_sheet(
            frame, r["plate"], pool,
            out=Path(tempfile.gettempdir()) / f"ttr_label_cog{i + 1}.png")
        if sheet is not None:
            print(f"     compare: {sheet}")
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
    parser.add_argument("--live", action="store_true",
                        help="grab the game window now instead of reading a "
                             "saved screenshot. This is the path the panel "
                             "uses, and it can fail where a saved file "
                             "succeeds -- the capture is scoped to the "
                             "window and its size drives every threshold")
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

    if args.live:
        # THE PATH THE PANEL USES. A saved screenshot is a plain PNG of
        # the whole screen; the live grab is scoped to the game window and
        # every size threshold in `find_plates` is a fraction of what it
        # returns. So the two can disagree, and when they do this is the
        # only way to see it.
        from .watch import Capture
        from .window import game_rect

        rect = game_rect()
        cap = Capture()
        frame = cap.grab()
        if frame is None:
            print("  no frame: is the game running?")
            return 1
        print(f"live grab   : {frame.shape[1]}x{frame.shape[0]}")
        print(f"window rect : {rect if rect else 'not found -- full screen'}")
        if rect:
            left, top, right, bottom = rect
            print(f"window size : {right - left}x{bottom - top}")
        # THE PANEL'S OWN GATES, not just find_plates. The watcher does
        # not call find_plates directly: it goes through `locate_plates`,
        # which is gated on a subsampled `any_plates`, and then requires
        # the gag menu as well before it will call it a battle. A reader
        # that finds a plate here while the panel says "nothing on screen"
        # means one of those gates is the difference, and each is a
        # different bug.
        from .vision import any_plates, locate_plates
        from .gagpanel import find_panel

        print(f"any_plates  : {any_plates(frame)}"
              f"   (subsampled presence test the watcher gates on)")
        print(f"locate_plates: {len(locate_plates(frame))} plate(s)"
              f"   (what the watcher actually calls)")
        panel_box = find_panel(frame)
        print(f"gag menu    : {'found ' + str(panel_box) if panel_box is not None else 'NOT FOUND'}")
        print(f"              a battle needs plates AND the menu to start")

        rejects = []
        plates = find_plates(frame, rejects=rejects)
        print(f"plates found: {len(plates)}")
        for i, plate in enumerate(plates):
            x0, y0, x1, y1 = plate.slot
            print(f"   plate {i + 1}: {x1 - x0}x{y1 - y0} at ({x0},{y0})")
        if rejects:
            print(f"rejected    : {len(rejects)} candidate(s)")
            for r in rejects:
                x0, y0 = r["box"][0], r["box"][1]
                print(f"   {r['w']}x{r['h']} at ({x0},{y0})  {r['why']}")
        if not plates:
            # WHAT COLOUR IS UP THERE. When no candidate forms at all the
            # mask is the suspect, and the only way to tune it is to know
            # what it was looking at. Plates sit in the upper middle of
            # the frame, so sample that band and report the most
            # teal-leaning pixels in it.
            import numpy as np

            h, w = frame.shape[:2]
            band = frame[int(h * 0.08):int(h * 0.28),
                         int(w * 0.25):int(w * 0.75), :3].astype(np.int16)
            flat = band.reshape(-1, 3)
            lead = flat[:, 2] - flat[:, 0]
            order = np.argsort(lead)[::-1][:5]
            print("  most blue-over-red pixels where plates live:")
            for idx in order:
                r, g, b = (int(v) for v in flat[idx])
                print(f"     rgb({r:>3},{g:>3},{b:>3})  "
                      f"B-R {b - r:>4}  G-R {g - r:>4}  B-G {b - g:>4}")
        if not plates and not rejects:
            print("   -- no teal survived even as a candidate. Is "
                  "'show-cog-levels' on?")
    else:
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
