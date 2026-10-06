"""Run the screen readers over a recorded fight.

    python tools/video_scan.py "C:/Users/me/Videos/run.mp4" --out frames/

Extracts frames (two a second by default) with ffmpeg, then for every
frame with the gag menu up reports the cog plates (level read or refused)
and the menu (pouch total, label, accepted or refused) -- the menu votes
across frames the way the live panel does (`panel_memory`). Frames stay
local: nothing here is meant for the repo, which keeps game images out.

A compressed recording is harder than the panel's lossless screen grabs:
HEVC colour bleed was what exposed the old count reader's cropping. Record
lossless or high-bitrate H.264 if the reads matter.

Needs ffmpeg with HEVC support (the project's bundled build is too old;
`winget install Gyan.FFmpeg` works) and numpy.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def find_ffmpeg() -> str:
    """A modern ffmpeg: PATH first, then a WinGet install."""
    candidates = []
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    local = os.environ.get("LOCALAPPDATA", "")
    candidates += sorted(glob.glob(os.path.join(
        local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin",
        "ffmpeg.exe")), reverse=True)
    for path in candidates:
        try:
            out = subprocess.run([path, "-hide_banner", "-decoders"],
                                 capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if "hevc" in out:
            return path
    raise SystemExit("no ffmpeg with HEVC decoding found -- try "
                     "`winget install Gyan.FFmpeg`")


def scan(frames, training=None):
    import numpy as np
    from PIL import Image

    from solver.live import gagpanel, vision
    from solver.live.panel_memory import PanelMemory

    memory = PanelMemory()
    last = None
    plates_ok = plates_bad = menus_ok = menus_bad = 0
    for path in frames:
        frame = np.array(Image.open(path).convert("RGB"))
        located = gagpanel.find_panel(frame)
        index = int(Path(path).stem.lstrip("f") or 0)
        if located is None:
            memory.reset()
            last = None
            continue
        if last is not None and index != last + 1:
            memory.reset()                 # the menu closed between samples
        last = index
        top = min(located[2].values())
        for plate in vision.find_plates(frame):
            if plate.slot[1] >= top:
                continue                   # a gag cell, not a cog plate
            level, score, margin = vision.read_level(frame, plate)
            ok = (level is not None and score >= 0.55
                  and margin >= vision.MIN_LEVEL_MARGIN)
            plates_ok += ok
            plates_bad += not ok
        panel = gagpanel.read_panel(frame, track_exp=training)
        resolved = memory.resolve(panel)
        memory.observe(panel)
        problem = resolved.checksum_problem()
        menus_ok += problem is None
        menus_bad += problem is not None
        label = f"{resolved.label[0]}/{resolved.label[1]}" if resolved.label else "-"
        print(f"  {Path(path).name}  pouch {resolved.pouch_total():3d}  label {label:6s}"
              f"  {'REFUSED: ' + problem[:70] if problem else 'accepted'}")
    print(f"plates on menu frames: {plates_ok} read, {plates_bad} refused")
    print(f"menu frames: {menus_ok} accepted, {menus_bad} refused")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video")
    ap.add_argument("--out", required=True, help="folder for the frames")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--skip-extract", action="store_true",
                    help="reuse frames already in --out")
    ap.add_argument("--training", default=None,
                    help="track training as TRACK=LEVEL pairs, e.g. "
                         "toon_up=5,sound=6,throw=5,squirt=5,drop=7 "
                         "(as the Local API reports; untrained rows are skipped)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not args.skip_extract:
        subprocess.run([find_ffmpeg(), "-v", "error", "-i", args.video,
                        "-vf", f"fps={args.fps}", "-q:v", "2",
                        str(out / "f%04d.png")], check=True)
    training = None
    if args.training:
        from solver.state import Track

        given = dict(item.split("=") for item in args.training.split(","))
        training = {t: int(given.get(t.value, 0)) for t in Track}
    scan(sorted(glob.glob(str(out / "f*.png"))), training)
    return 0


if __name__ == "__main__":
    sys.exit(main())
