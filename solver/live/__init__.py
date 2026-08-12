"""Reading live state out of a running Toontown Rewritten client.

`ttr_local` is stdlib-only and is re-exported here. `vision` is not:
reading the screen needs numpy, and the Local API client should stay
usable on a checkout that has not installed it. Import it directly --
`from solver.live.vision import find_plates` -- and let the ImportError
say what is missing.
"""
from .ttr_local import (
    LocalAPIError,
    NotRunning,
    ConsentRequired,
    Snapshot,
    TTRLocal,
    discover,
)

__all__ = [
    "LocalAPIError", "NotRunning", "ConsentRequired",
    "Snapshot", "TTRLocal", "discover",
]
