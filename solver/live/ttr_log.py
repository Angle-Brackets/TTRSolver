"""Where the toon is, from the TTR client's own log.

The Local API names a street or "Cog Building" but not a boss room, so
the panel could not tell a VP from Sellbot HQ's courtyard. The client's
log can: every place change writes one line,

    :vltf777d7a2: enter(requestStatus={'loader': 'CogHQLoader',
        'where': 'CogHQBossBattle', 'how': 'Movie', 'zoneId': 177131,
        'hoodId': 11000})

OBSERVED in a real session on 2026-10-10 (a VP, hood 11000 = Sellbot HQ),
alongside 'SuitInterior' for a Cog building. The module names are
obfuscated (`vltf777d7a2`), so the line is found by `enter(requestStatus=`
and the two keys, never by a module name, and a hood id that prints as
`<vlt63adacc8.vlt9070e393: 5000>` is read by its number.

A FILE THE GAME WRITES, read and nothing more -- no memory, no process.
Read incrementally: each poll reads only what was appended since the
last, and a new session's file (one per launch) is picked up by name.
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

# Where the logs are: `TTR_LOG_DIR` if set, else the default install's
# folder where one has been SEEN -- Windows so far. A Mac's or Linux
# install's folder is [TODO] until observed; set TTR_LOG_DIR there.
WINDOWS_LOG_DIR = r"C:\Program Files (x86)\Toontown Rewritten\logs"


def default_log_dir() -> Optional[str]:
    if os.environ.get("TTR_LOG_DIR"):
        return os.environ["TTR_LOG_DIR"]
    if os.name == "nt":
        return WINDOWS_LOG_DIR
    return None


_ENTER = "enter(requestStatus="
_WHERE = re.compile(r"'where':\s*'([^']+)'")
_HOOD = re.compile(r"'hoodId':\s*(?:<[^>]*?:\s*)?(\d+)")

Place = Tuple[str, Optional[int]]


def parse_place(line: str) -> Optional[Place]:
    """(where, hoodId) from one log line, or None if it is not a move."""
    if _ENTER not in line:
        return None
    where = _WHERE.search(line)
    if where is None:
        return None
    hood = _HOOD.search(line)
    return where.group(1), (int(hood.group(1)) if hood else None)


class PlaceWatcher:
    """The toon's latest place, kept current from the newest log file."""

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = log_dir or default_log_dir()
        self._file: Optional[str] = None
        self._offset = 0
        self._place: Optional[Place] = None

    def _newest(self) -> Optional[str]:
        if not self.log_dir:
            return None
        try:
            names = [n for n in os.listdir(self.log_dir)
                     if n.startswith("ttr-") and n.endswith(".log")]
        except OSError:
            return None
        if not names:
            return None
        return max((os.path.join(self.log_dir, n) for n in names),
                   key=os.path.getmtime)

    def place(self) -> Optional[Place]:
        """The last place the log records, or None if there is no log.

        Never raises: a missing install or an unreadable file just means
        the panel falls back to the player's picker.
        """
        try:
            newest = self._newest()
            if newest is None:
                return None
            if newest != self._file:
                self._file, self._offset, self._place = newest, 0, None
            with open(newest, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._offset)
                chunk = fh.read()
                self._offset = fh.tell()
            for line in chunk.splitlines():
                found = parse_place(line)
                if found is not None:
                    self._place = found
            return self._place
        except OSError:
            return None
