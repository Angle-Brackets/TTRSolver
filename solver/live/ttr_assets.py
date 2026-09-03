"""Pulling assets out of a Toontown Rewritten installation.

The screen reader needs two things the game already has on disk: the
interface font, so digit templates are exact rather than approximate,
and the department emblems, so the medallion on a cog plate can be
matched pixel for pixel.

They are read from the player's own installation at runtime and cached,
never vendored into this repository -- they are TTR's artwork, and a copy
here would both be a redistribution we have no right to make and go stale
the next time the game is patched.

WHAT IS AND IS NOT READABLE
---------------------------
`phase_*.mf` are ordinary Panda3D multifiles: a header, then a linked
list of index entries, with names stored XOR 0xFF. That is obfuscation,
not protection, and the game's art and fonts sit in there in the clear.

`TTRGame.vlt` is a different matter -- magic `VT17`, entropy 8.000
bits/byte, indistinguishable from random. The game's Python lives in
there, encrypted on purpose. This module does not touch it, and neither
should anything else here.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

MAGIC = b"pmf\0\n\r"

# Where a Windows install normally lands. TTR_DIR overrides for anyone
# who moved it, and is the only knob a non-Windows checkout needs.
DEFAULT_LOCATIONS = (
    r"C:\Program Files (x86)\Toontown Rewritten",
    r"C:\Program Files\Toontown Rewritten",
    os.path.expanduser("~/Library/Application Support/Toontown Rewritten"),
    os.path.expanduser("~/.var/app/com.toontownrewritten.Launcher"),
)

CACHE_DIR = Path(__file__).resolve().parent / "_ttr_cache"


class AssetError(RuntimeError):
    """The installation is missing, or does not contain what was asked."""


def install_dir(override: Optional[str] = None) -> Path:
    """Locate the game. `TTR_DIR` wins, then the usual places."""
    candidates = [override, os.environ.get("TTR_DIR"), *DEFAULT_LOCATIONS]
    for candidate in candidates:
        if candidate and (Path(candidate) / "phase_3.mf").is_file():
            return Path(candidate)
    raise AssetError(
        "cannot find a Toontown Rewritten installation (looked for "
        "phase_3.mf in: "
        + ", ".join(str(c) for c in candidates if c)
        + "). Set TTR_DIR to the install directory.")


def entries(multifile: Path) -> Iterator[Tuple[str, int, int, int]]:
    """Yield (name, offset, length, flags) for each subfile.

    The index is a linked list: every entry stores the byte offset of the
    next one, and offsets are divided by a scale factor stored in the
    header.
    """
    blob = multifile.read_bytes()
    if blob[:6] != MAGIC:
        raise AssetError(f"{multifile} is not a Panda3D multifile")

    _major, minor, scale = struct.unpack_from("<HHI", blob, 6)
    pos = 14 + (4 if minor >= 1 else 0)      # optional header timestamp

    while True:
        (next_index,) = struct.unpack_from("<I", blob, pos)
        data_start, data_length, flags = struct.unpack_from("<IIH", blob,
                                                            pos + 4)
        cur = pos + 14
        if flags & 0x0009:                   # compressed or encrypted
            cur += 4                         # uncompressed length
        if minor >= 1:
            cur += 4                         # per-subfile timestamp
        (name_len,) = struct.unpack_from("<H", blob, cur)
        cur += 2
        # Names are stored inverted; this is obfuscation, not encryption.
        name = bytes(b ^ 0xFF for b in blob[cur:cur + name_len]).decode(
            "utf-8", "replace")
        yield name, data_start * scale, data_length, flags
        if next_index == 0:
            return
        pos = next_index * scale


def extract(subfile: str, phase: str, override: Optional[str] = None,
            cache: Optional[Path] = None) -> Path:
    """Pull one file out of a phase multifile, caching it locally.

    `subfile` is matched on its basename, so callers do not have to know
    the full in-archive path.
    """
    cache_dir = Path(cache) if cache else CACHE_DIR
    cached = cache_dir / subfile
    if cached.is_file():
        return cached

    multifile = install_dir(override) / phase
    if not multifile.is_file():
        raise AssetError(f"{multifile} not found")

    blob = multifile.read_bytes()
    for name, start, length, flags in entries(multifile):
        if name.split("/")[-1] != subfile:
            continue
        if flags:
            raise AssetError(
                f"{subfile} is stored with flags {flags:#06x} "
                f"(compressed or encrypted); this reader handles only "
                f"stored subfiles.")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(blob[start:start + length])
        return cached
    raise AssetError(f"{subfile} not found in {phase}")


def find(pattern: str, override: Optional[str] = None) -> List[str]:
    """Every subfile across every phase whose name contains `pattern`."""
    root = install_dir(override)
    hits = []
    for multifile in sorted(root.glob("phase_*.mf")):
        for name, _start, length, _flags in entries(multifile):
            if pattern.lower() in name.lower():
                hits.append(f"{multifile.name}:{name} ({length:,}B)")
    return hits


# The interface font. Chosen by measurement, not by eye: rendered against
# a real "Level 6" plate it scores IoU 0.81, where Humanist -- the
# obvious guess, and the one this project first assumed -- manages 0.33.
INTERFACE_FONT = ("ImpressBT.ttf", "phase_3.mf")

# A 2x2 atlas of the four department emblems, read left-to-right then
# top-to-bottom. The order is NOT alphabetical and is not the c/l/m/s
# order the Local API uses for cog suits:
#
#     top-left     rising bar chart  -> Sellbot   (a sales chart)
#     top-right    dollar sign       -> Cashbot
#     bottom-left  gavel             -> Lawbot
#     bottom-right necktie           -> Bossbot   (the boss's tie)
#
# [CONFIRMED] against the wiki's own department icons, which carry the
# department in their filenames. This was wrong for its first several
# commits: the tiles were assigned by guessing what each picture
# depicted, which swapped Bossbot and Sellbot and made every reading of
# those two confidently incorrect -- a real Bossbot plate was reported as
# Sellbot with a 0.43 margin, well above the confidence floor. Guessing
# the mapping and then checking only that four emblems existed is what
# let it stand. If this order is ever touched, re-verify it against a
# named source rather than by eye.
COG_ICONS = ("ttr_t_ara_gen_cogIcons.jpg", "phase_3.5.mf")

# The battle status-effect atlas, 2x2 like the emblems. The lure magnet
# is the bottom-right cell -- the green horseshoe with white tips, which
# is what the game floats above a sleeping cog's plate.
#
# The alpha lives in a separate `_a.rgb` sibling, which is how Panda3D
# stores it; without it the icon carries the atlas's black backdrop.
STATUS_EFFECTS = ("battle_gui_status_effects_remastered_palette_4amla_1.jpg",
                  "phase_3.5.mf")
STATUS_ALPHA = ("battle_gui_status_effects_remastered_palette_4amla_1_a.rgb",
                "phase_3.5.mf")
LURE_CELL = (1, 1)          # column, row in the 2x2 atlas

# The shticker book's button icons, 4x2. The green globe at (1, 0) is
# the map, which is as close to "where you are" as the game draws.
BUTTON_ICONS = ("ttr_t_gui_sbk_buttonIcons.jpg", "phase_3.5.mf")
BUTTON_ALPHA = ("ttr_t_gui_sbk_buttonIcons_a.rgb", "phase_3.5.mf")
MAP_CELL = (1, 0)

# The organic indicator: the green leaf badge the game draws on a gag
# grown on a gag tree. Unlike the two above it is NOT on a regular grid
# -- the battle GUI palettes are packed sheets, not atlases with equal
# cells -- so it is an explicit box rather than a (column, row).
#
# Found by name rather than by eye: `ttr_m_gui_bat_gagGUI.bam` carries a
# node called `ttr_t_gui_bat_toonGUI_indicator_organic_card`, and the
# only green blob on the palettes that model references is this one.
# The box is the alpha bounding box of that blob with two pixels of
# margin, so a future repack shows up as a misaligned crop rather than
# as a silently wrong icon.
ORGANIC_PALETTE = ("battle_gui_remastered_palette_4amla_20.jpg",
                   "phase_3.5.mf")
ORGANIC_ALPHA = ("battle_gui_remastered_palette_4amla_20_a.rgb",
                 "phase_3.5.mf")
ORGANIC_BOX = (155, 2, 225, 68)
EMBLEM_ORDER = ("sellbot", "cashbot", "lawbot", "bossbot")


def interface_font(override: Optional[str] = None) -> Path:
    return extract(*INTERFACE_FONT, override=override)


def department_emblems(override: Optional[str] = None) -> Dict[str, Path]:
    """Split the 2x2 emblem atlas into one image per department."""
    from PIL import Image                    # optional extra, see vision

    atlas_path = extract(*COG_ICONS, override=override)
    out = {}
    with Image.open(atlas_path) as atlas:
        half_w, half_h = atlas.width // 2, atlas.height // 2
        for index, dept in enumerate(EMBLEM_ORDER):
            target = atlas_path.parent / f"emblem_{dept}.png"
            # Always re-crop rather than reusing what is on disk. The
            # filename records only the department, so when EMBLEM_ORDER
            # was corrected the cache kept serving tiles cut at the old
            # positions -- a fix that appeared not to take. Cropping a
            # 256x256 jpg costs nothing next to that class of bug.
            left, top = (index % 2) * half_w, (index // 2) * half_h
            atlas.crop((left, top, left + half_w, top + half_h)).save(target)
            out[dept] = target
    return out


def lure_icon(override: Optional[str] = None) -> Path:
    """The magnet the game shows above a lured cog, as a cut-out PNG.

    Extracted from the player's own installation like the font and the
    emblems, never vendored: it is TTR's artwork, and a copy in this
    repository would be a redistribution we have no right to make and
    would go stale at the next patch.

    Re-cropped every call rather than trusting what is on disk, for the
    reason `department_emblems` records -- a cached tile cut at the wrong
    offset makes a corrected offset look like it did nothing.
    """
    from PIL import Image

    atlas_path = extract(*STATUS_EFFECTS, override=override)
    target = atlas_path.parent / "status_lure.png"
    with Image.open(atlas_path) as atlas:
        half_w, half_h = atlas.width // 2, atlas.height // 2
        col, row = LURE_CELL
        left, top = col * half_w, row * half_h
        icon = atlas.crop((left, top, left + half_w, top + half_h))
        icon = icon.convert("RGBA")

        # The alpha is a separate SGI RGB file. If it is missing or
        # unreadable the icon still works -- it simply keeps the atlas
        # backdrop -- so this never raises for want of a mask.
        try:
            alpha_path = extract(*STATUS_ALPHA, override=override)
            with Image.open(alpha_path) as mask:
                mask = mask.convert("L").resize(atlas.size)
                icon.putalpha(mask.crop(
                    (left, top, left + half_w, top + half_h)))
        except Exception:
            pass
        icon.save(target)
    return target


def map_icon(override: Optional[str] = None) -> Path:
    """The shticker book's map globe, cut out of the button atlas.

    Same rule as `lure_icon` and the emblems: read from the player's
    installation at runtime, cached, never vendored.
    """
    from PIL import Image

    atlas_path = extract(*BUTTON_ICONS, override=override)
    target = atlas_path.parent / "icon_map.png"
    with Image.open(atlas_path) as atlas:
        cell_w, cell_h = atlas.width // 4, atlas.height // 2
        col, row = MAP_CELL
        left, top = col * cell_w, row * cell_h
        box = (left, top, left + cell_w, top + cell_h)
        icon = atlas.crop(box).convert("RGBA")
        try:
            alpha_path = extract(*BUTTON_ALPHA, override=override)
            with Image.open(alpha_path) as mask:
                mask = mask.convert("L").resize(atlas.size)
                icon.putalpha(mask.crop(box))
        except Exception:
            pass
        icon.save(target)
    return target


def organic_icon(override: Optional[str] = None) -> Path:
    """The green leaf the game puts on an organic gag, as a cut-out PNG.

    Same rule as `lure_icon` and the emblems: read from the player's
    installation at runtime, cached, never vendored.

    This is decoration, not evidence. Whether a track is organic is
    stated by the Local API, so nothing needs to recognise this badge on
    screen to know -- it exists so the panel can draw what the game
    draws instead of inventing a marker of its own.
    """
    from PIL import Image

    atlas_path = extract(*ORGANIC_PALETTE, override=override)
    target = atlas_path.parent / "indicator_organic.png"
    with Image.open(atlas_path) as atlas:
        icon = atlas.crop(ORGANIC_BOX).convert("RGBA")
        # The alpha is a separate SGI RGB file. A missing mask leaves the
        # palette backdrop behind the leaf rather than raising -- the
        # icon is still recognisable, and a decoration must never stop
        # the panel starting.
        try:
            alpha_path = extract(*ORGANIC_ALPHA, override=override)
            with Image.open(alpha_path) as mask:
                mask = mask.convert("L").resize(atlas.size)
                icon.putalpha(mask.crop(ORGANIC_BOX))
        except Exception:
            pass
        icon.save(target)
    return target


# The Silly Meter's reward badges: one per gag track, the same art the
# Silly Teams use for a double-experience week. Standalone files with
# their own alpha, so unlike the lure magnet and the map globe there is
# no atlas cell to cut -- extract, mask, done.
#
# Keyed by the SOLVER's track slug rather than the game's filename, so
# a caller can look one up with `model.track` and never has to know that
# the game writes "toonup" where `Track.TOON_UP` is "toon_up".
TRACK_ICON_FILES = {
    "toon_up": "toonup", "trap": "trap", "lure": "lure", "sound": "sound",
    "throw": "throw", "squirt": "squirt", "drop": "drop",
}
TRACK_ICON_PREFIX = "ttr_t_gui_sbk_sillyMeter_rewardIcons_"


def track_icon(track: str, override: Optional[str] = None) -> Path:
    """One track's Silly Team badge, as a cut-out PNG.

    Same rule as `lure_icon`, `map_icon` and `organic_icon`: read from
    the player's own installation at runtime, cached, never vendored.
    That matters more here than usual -- this art is also published on
    the wiki, and copying it in from there would put TTR's files in this
    repository by a different door.
    """
    from PIL import Image

    name = TRACK_ICON_FILES[track]
    atlas = extract(TRACK_ICON_PREFIX + name + ".jpg", "phase_3.5.mf",
                    override=override)
    target = atlas.parent / ("track_" + track + ".png")
    with Image.open(atlas) as art:
        icon = art.convert("RGBA")
        try:
            alpha = extract(TRACK_ICON_PREFIX + name + "_a.rgb",
                            "phase_3.5.mf", override=override)
            with Image.open(alpha) as mask:
                icon.putalpha(mask.convert("L").resize(icon.size))
        except Exception:
            pass
        icon.save(target)
    return target


def track_icons(override: Optional[str] = None) -> Dict[str, Path]:
    """Every track badge that could be read. Missing ones are omitted.

    Never raises for a missing file: a decoration that cannot be found
    must not stop the panel starting, and a partial set still leaves
    every track it did find looking right.
    """
    out: Dict[str, Path] = {}
    for track in TRACK_ICON_FILES:
        try:
            out[track] = track_icon(track, override=override)
        except Exception:                          # noqa: BLE001
            continue
    return out


# The floating markers TTR draws above a cog for each status effect.
#
# `ttr_m_gui_bat_statusEffect.bam` names every one of them --
# `..._icon_trapped`, `..._icon_lured`, `..._icon_v2_0` and thirty more
# -- and the art is packed two-by-two into the
# `battle_gui_status_effects_remastered_palette_*` sheets. The bam does
# not say WHICH cell, so the two that matter here were identified by
# eye against a live frame: the trap marker is a banana peel, the lure
# marker the red magnet.
#
# Only these two are mapped. The rest exist and are findable the same
# way, but an entry here is a claim that the cell is right, and a wrong
# cell would have the reader hunting for the wrong picture.
STATUS_ICON_CELLS = {
    "trapped": ("8", (1, 0)),
    "lured": ("5", (1, 0)),
}
STATUS_PALETTE = "battle_gui_status_effects_remastered_palette_4amla_%s"


def status_icon(name: str, override: Optional[str] = None) -> Path:
    """One status marker, cut out of its palette. See `STATUS_ICON_CELLS`.

    Same rule as every other asset here: read from the player's own
    installation at runtime, cached, never vendored.
    """
    from PIL import Image

    sheet, (col, row) = STATUS_ICON_CELLS[name]
    base = STATUS_PALETTE % sheet
    atlas_path = extract(base + ".jpg", "phase_3.5.mf", override=override)
    target = atlas_path.parent / ("status_%s.png" % name)
    with Image.open(atlas_path) as atlas:
        half_w, half_h = atlas.width // 2, atlas.height // 2
        box = (col * half_w, row * half_h,
               col * half_w + half_w, row * half_h + half_h)
        icon = atlas.crop(box).convert("RGBA")
        try:
            alpha_path = extract(base + "_a.rgb", "phase_3.5.mf",
                                 override=override)
            with Image.open(alpha_path) as mask:
                mask = mask.convert("L").resize(atlas.size)
                icon.putalpha(mask.crop(box))
        except Exception:
            pass
        icon.save(target)
    return target
