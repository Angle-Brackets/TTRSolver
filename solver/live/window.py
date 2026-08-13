"""Where the game is on the screen.

WHY THIS EXISTS, HAVING BEEN RULED OUT ONCE
-------------------------------------------
The plate reader was built to need no window handle, on the reasoning
that the teal portrait slot is distinctive enough to find anywhere in a
frame. That holds inside the game. It does not hold across a desktop:
played windowed, `Capture` grabs the whole screen, and everything behind
the game is fair game for the teal mask -- wallpaper, browser chrome,
another app's theme.

Measured on a real 2560x1440 desktop with the game windowed and a
blue-green wallpaper behind it:

    scope                 plates found
    whole desktop         1  -- wallpaper, 319x190, aspect 1.68
    game window only      2  -- 65x45 and 68x47, aspect 1.44 and 1.45

The two real ones are the documented plate geometry almost exactly. The
detector was never wrong; it was being shown the wrong picture, and the
wallpaper blob outscored the real plates because it was bigger. Every
reading came back `level unreadable / unidentified`, because scenery has
no level to read.

Cropping to the window fixes it at the source and costs nothing else.
This is Windows-only and degrades to None everywhere else, in which case
the caller falls back to the full screen and the old behaviour.

Nothing here reads memory, injects, or touches the game process. It asks
the window manager where a window is, which is the same question a
screenshot tool asks.
"""
from __future__ import annotations

import sys
from typing import Optional, Tuple

# The window title TTR sets. Matched exactly; the launcher and the patcher
# use different titles, so this will not attach to the wrong one.
GAME_TITLE = "Toontown Rewritten"

Rect = Tuple[int, int, int, int]        # left, top, right, bottom


def game_rect(title: str = GAME_TITLE) -> Optional[Rect]:
    """The game's client area in screen coordinates, or None.

    The *client* area rather than the window rect: the latter includes
    the title bar and the resize border, which are not the game and
    would put a strip of window chrome into every frame.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:                          # pragma: no cover
        return None

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        # Minimised windows report a client rect, and it is nonsense.
        return None

    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    origin = wintypes.POINT(rect.left, rect.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return origin.x, origin.y, origin.x + width, origin.y + height


def describe() -> str:
    """One line about where the game is, for the CLIs."""
    rect = game_rect()
    if rect is None:
        if not sys.platform.startswith("win"):
            return "not on Windows: reading the whole screen"
        return (f"no window titled {GAME_TITLE!r}: reading the whole screen "
                f"(anything teal behind the game may read as a cog plate)")
    left, top, right, bottom = rect
    return (f"game window at {right - left}x{bottom - top} "
            f"+{left}+{top}; reading only that")
