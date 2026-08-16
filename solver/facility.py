"""Buildings, factories, field offices: fights that come one after another.

WHY THIS EXISTS
---------------
The solver has only ever modelled a single battle, and `cogs_remaining`
alone could not fix that. The horizon raised the price of a gag when
more cogs were coming, but the RL episode still ended when the battle
ended, so a gag saved was never spent and conserving paid nothing. PPO
correctly learned to ignore it: over 394 positions, moving the horizon
from 0 to 30 changed its move 4.3% of the time.

This module is the missing half. A facility is a sequence of battles
sharing one pouch, so a Wedding Cake spent on floor one is genuinely
absent on floor five, and the return contains the evidence.

TWO KINDS OF FIGHT
------------------
`BattleKind.STREET` is what the solver already modelled: one battle,
nothing after it, and a toon who is losing can walk away. That last part
is why the street stays the low-risk case and why its horizon is fixed
at zero.

`BattleKind.FACILITY` covers cog buildings, factories, field offices and
boss fights as one shape, because their differences are scenery. What
they share is what matters to a solver: several battles back to back, no
restocking between them, and [CONFIRMED] on the Cog Building page,
"Toons cannot run to the nearest playground" once inside.

THE SHAPE OF A FLOOR
--------------------
At most four cogs are ever present. A floor holding more than four does
not put them all on the field -- [CONFIRMED] Cog Building: "Each floor
contains progressively more Cogs that the Toons must battle. As Toons
continuously battle Cogs, more Cogs may exit from the elevator to join."

So a floor is a battle plus a `holdout`: cogs waiting off-field who walk
in as slots free. That is a materially harder fight than the same cogs
split into separate battles, because there is no gap to regroup in, and
it is the reason this is modelled rather than dividing a pool by four.

WHAT THE WIKI DOES NOT SAY
--------------------------
Two things here are `[ASSUMED]`, both labelled at their definitions:

* **How many cogs are on a floor.** The wiki's difficulty table gives
  floors, cog levels and boss level -- all [CONFIRMED] and encoded below
  -- but never a per-floor count. Only the direction is confirmed,
  "progressively more".
* **When a holdout cog walks in.** The wiki says they join, not on what
  trigger. Filling a freed slot immediately is the reading that the
  four-cog cap forces; the alternative is a delay, which would only make
  the fight easier.

Neither feeds advice about a real battle -- they shape the training
distribution -- but a policy trained on a fiction is a policy tuned to a
fiction, so they are tagged rather than quietly chosen.
"""
from __future__ import annotations

import enum
import random
from typing import Callable, List, Optional, Sequence

from . import data
from .state import BattleState, CogState

# At most four cogs on the field at once. The wiki has no page stating
# this outright, but it is the cap the whole codebase is built on
# (`rl.env.MAX_COGS`) and the reason a holdout has to exist at all.
MAX_PRESENT = 4


class BattleKind(enum.Enum):
    """Whether anything follows this fight."""

    STREET = "street"
    FACILITY = "facility"


# [CONFIRMED] TTR wiki, Cog Building, difficulty table. Difficulty equals
# the level of the cog that took over the building. `floors` and `cogs`
# are inclusive ranges; `boss` is the level of the top-floor cog.
#
# Note the "Cogs" column is cog LEVELS, not counts -- an easy misreading,
# and the reason the per-floor count below is assumed rather than taken
# from here.
DIFFICULTY = {
    1: {"floors": (1, 1), "cogs": (1, 3), "boss": 4},
    2: {"floors": (1, 2), "cogs": (2, 4), "boss": 5},
    3: {"floors": (1, 3), "cogs": (3, 5), "boss": 6},
    4: {"floors": (2, 3), "cogs": (4, 6), "boss": 7},
    5: {"floors": (2, 4), "cogs": (5, 7), "boss": 8},
    6: {"floors": (3, 4), "cogs": (6, 8), "boss": 9},
    7: {"floors": (3, 5), "cogs": (7, 9), "boss": 10},
    8: {"floors": (4, 5), "cogs": (8, 10), "boss": 11},
    9: {"floors": (5, 5), "cogs": (9, 11), "boss": 12},
}


def floor_size(floor: int, floors: int, rng) -> int:
    """[ASSUMED] How many cogs a floor holds, counting the holdout.

    The wiki confirms the direction and not the numbers: "Each floor
    contains progressively more Cogs". So this grows with depth and is
    kept inside a range where the holdout is a real feature of the fight
    without the floor becoming a siege -- floor one lands at three or
    four, a fifth floor at six to eight.

    If a count is ever published, replace this and nothing else.
    """
    low = min(3 + floor - 1, 6)
    return rng.randint(low, low + 2)


class FacilityPlan:
    """The floors of one facility, and the pouch that has to last them.

    Deliberately held by the *environment* rather than by `BattleState`:
    a toon on floor two cannot see what is waiting on floor four, and a
    state that carried the whole plan would let the search read cogs it
    has no way of knowing about. The state gets a count of what is left
    (`cogs_remaining`) and the cogs actually walking into the current
    fight (`holdout`), which is what a player knows.
    """

    def __init__(self, floors: List[List[CogState]]):
        self.floors = floors
        self.index = 0

    @property
    def exhausted(self) -> bool:
        return self.index >= len(self.floors)

    def remaining(self) -> int:
        """Cogs in floors not yet started.

        `index` already points at the next floor to be taken, so this
        counts from there. Slicing from `index + 1` skipped a whole
        floor -- a five-floor plan reported 18 cogs left where 22 were
        waiting, which would have under-priced every gag in the
        building.
        """
        return sum(len(f) for f in self.floors[self.index:])

    def take_floor(self):
        """Pop the next floor as (on-field cogs, holdout)."""
        if self.exhausted:
            return [], []
        cogs = self.floors[self.index]
        self.index += 1
        return list(cogs[:MAX_PRESENT]), list(cogs[MAX_PRESENT:])


def plan_facility(rng, difficulty: int,
                  cog_factory: Callable[[object, int], CogState],
                  floors: Optional[int] = None) -> FacilityPlan:
    """Build a facility from the wiki's difficulty table.

    `cog_factory(rng, level)` supplies a cog of a given level. It is
    injected because which cogs are safe to sample is a training
    concern -- only those whose attack tables are complete, so a [TODO]
    cell cannot raise mid-episode -- and does not belong in here.
    """
    if difficulty not in DIFFICULTY:
        raise ValueError(f"no wiki difficulty row for {difficulty}")
    row = DIFFICULTY[difficulty]
    n_floors = floors if floors is not None else rng.randint(*row["floors"])
    lo, hi = row["cogs"]

    built: List[List[CogState]] = []
    for floor in range(1, n_floors + 1):
        size = floor_size(floor, n_floors, rng)
        cogs = [cog_factory(rng, rng.randint(lo, hi)) for _ in range(size)]
        if floor == n_floors:
            # [CONFIRMED] the top floor has a "boss" at the table's boss
            # level. The wiki is explicit that it is a boss in name only:
            # "their abilities and appearance are the same as the rest".
            cogs[-1] = cog_factory(rng, row["boss"])
        built.append(cogs)
    return FacilityPlan(built)


def reinforce(state: BattleState) -> int:
    """Walk waiting cogs into freed slots. Returns how many joined.

    [ASSUMED] on timing only: a freed slot is filled at once. The wiki
    confirms that cogs join and not when, and the four-cog cap means
    they can only ever join as slots open. A delay would make the fight
    easier, so this is the conservative reading.

    Mutates `state`, and is called from round resolution so that the
    search sees reinforcements too. A search that treated a kill as
    final progress when another cog immediately replaces it would
    systematically overvalue killing.
    """
    joined = 0
    while state.holdout and len(state.active_cogs()) < MAX_PRESENT:
        state.cogs.append(state.holdout.pop(0))
        joined += 1
    return joined
