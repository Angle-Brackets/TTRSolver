"""Remember the gag menu while it stays open, and vote on every cell.

WHY. One frame of the menu can be wrong in ways no single frame can
detect. The mouse cursor sitting on a digit is the common case: on a
recorded building run it turned a "4" into nothing and a "5" into a "1",
and while a gag is hovered the "Total gags" label is replaced by the
gag's card, so there is no total to catch it either. The learned reader
flags most of these as doubtful, which refuses the board -- a round with
no advice -- and the rest it cannot flag at all.

But counts CANNOT CHANGE while the menu is open: gags are spent when the
round resolves, and the menu is gone while that happens. So every frame
the panel polls during one opening of the menu is another look at the
same numbers. The cursor moves; the digit under it does not.

This keeps, per cell, the confident reads seen since the menu opened,
and resolves each new read against them:

* a DOUBTFUL cell takes the cell's most common confident value, if it
  has been seen at all and leads outright;
* a confident cell that DISAGREES with a value seen at least twice more
  often than its own is overruled the same way -- the "5" read as "1"
  under the cursor.

Anything else is left exactly as read, doubts included, so the label
check and `build_state`'s refusal still apply. `reset()` whenever the
menu closes or the battle ends: that is when counts may really change.
"""
from __future__ import annotations

import threading
from collections import Counter
from dataclasses import replace
from typing import Dict, Optional, Tuple

from ..state import Track

# Confident sightings needed before a remembered value can OVERRULE a
# confident read that disagrees with it.
MIN_VOTES = 2
# ...and before it can stand in for a read the reader itself called
# doubtful. One is enough: a doubtful read is not evidence, so a single
# unopposed confident sighting outweighs it. On the recording, a cursor
# frame whose only earlier frame had read the cell cleanly was refused
# for want of a second sighting.
MIN_VOTES_FOR_DOUBT = 1


class PanelMemory:
    """Votes per gag-menu cell for one opening of the menu."""

    def __init__(self):
        self._votes: Dict[Tuple[Track, int], Counter] = {}
        self._lock = threading.Lock()
        self.overrides = 0          # cells resolved from memory, for the log

    def reset(self) -> None:
        with self._lock:
            self._votes = {}

    def observe(self, panel) -> None:
        """Record a read's confident, unlocked cells."""
        if panel is None:
            return
        with self._lock:
            for cell in panel.cells:
                if cell.count is None or cell.uncertain or not cell.unlocked:
                    continue
                self._votes.setdefault((cell.track, cell.level),
                                       Counter())[cell.count] += 1

    def _settled(self, key) -> Optional[Tuple[int, int, int]]:
        """(value, its votes, runner-up votes) for a cell, or None."""
        votes = self._votes.get(key)
        if not votes:
            return None
        ranked = votes.most_common(2)
        value, count = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        return value, count, second

    def resolve(self, panel):
        """`panel` with doubtful or outvoted cells taken from memory."""
        if panel is None:
            return None
        changed = False
        cells = []
        with self._lock:
            for cell in panel.cells:
                settled = (self._settled((cell.track, cell.level))
                           if cell.count is not None else None)
                if settled is None:
                    cells.append(cell)
                    continue
                value, votes, second = settled
                need = MIN_VOTES_FOR_DOUBT if cell.uncertain else MIN_VOTES
                if votes < need or votes <= second:
                    cells.append(cell)
                    continue
                own = self._votes[(cell.track, cell.level)].get(cell.count, 0)
                if cell.uncertain or (cell.count != value and votes > own):
                    cells.append(replace(cell, count=value, uncertain=False))
                    changed = True
                    self.overrides += 1
                else:
                    cells.append(cell)
        return replace(panel, cells=cells) if changed else panel
