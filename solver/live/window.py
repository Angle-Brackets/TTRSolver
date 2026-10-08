"""Where the game is on the screen.

The teal portrait slot is distinctive inside the game but not across a
whole desktop: on a 2560x1440 desktop with the game windowed, capturing
the full screen found 1 "plate" (a 319x190 wallpaper blob) while
capturing just the window found the real 2 (65x45, 68x47), matching the
documented plate geometry. Cropping to the window fixes this at the
source.

Windows-only; returns None elsewhere, where the caller falls back to the
full screen. Reads no memory and touches no process -- just asks the
window manager where the window is, like any screenshot tool would.
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
