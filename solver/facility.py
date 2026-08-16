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
from typing import Callable, Dict, List, Optional, Sequence

from . import data
from .state import BattleState, CogState, Track

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


def floor_size(floor: int, rng) -> int:
    """[ASSUMED] How many cogs a floor holds, counting the holdout.

    The wiki confirms the direction and not the numbers: "Each floor
    contains progressively more Cogs". So this grows with depth, and
    stays in a range where the holdout is a real feature of the fight
    without the floor becoming a siege:

        floor 1: 3-5    floor 2: 4-6    floor 3: 5-7
        floor 4: 6-8    floor 5+: 6-8   (the growth stops at 6)

    Depth alone decides it, not depth as a fraction of the building, so
    the second floor of a two-floor building holds what the second floor
    of a five-floor building holds. Nothing published says otherwise.

    If a count is ever published, replace this and nothing else.
    """
    low = min(3 + floor - 1, 6)
    return rng.randint(low, low + 2)


# [CONFIRMED] TTR wiki, Street. Cog level range per street, in
# playground order. A building's difficulty equals the level of the cog
# that took it over, so a street's cog range IS its range of building
# difficulties.
#
# This is what replaced scaling difficulty by party laff. The game does
# not size a building to whoever walks in -- it sizes it to the street,
# and you arrive with whatever you have. By the last two playgrounds
# that means difficulty 5-9 as the ordinary case, on toons who may be
# under 100 laff with untrained tracks.
STREETS = [
    ("Loopy Lane", "Toontown Central", (1, 3)),
    ("Punchline Place", "Toontown Central", (1, 3)),
    ("Silly Street", "Toontown Central", (1, 3)),
    ("Barnacle Boulevard", "Donald's Dock", (2, 4)),
    ("Seaweed Street", "Donald's Dock", (3, 6)),
    ("Lighthouse Lane", "Donald's Dock", (3, 6)),
    ("Elm Street", "Daisy Gardens", (2, 4)),
    ("Maple Street", "Daisy Gardens", (3, 6)),
    ("Oak Street", "Daisy Gardens", (3, 6)),
    ("Alto Avenue", "Minnie's Melodyland", (2, 4)),
    ("Baritone Boulevard", "Minnie's Melodyland", (3, 6)),
    ("Tenor Terrace", "Minnie's Melodyland", (3, 6)),
    ("Sleet Street", "The Brrrgh", (5, 7)),
    ("Walrus Way", "The Brrrgh", (5, 7)),
    ("Polar Place", "The Brrrgh", (7, 9)),
    ("Lullaby Lane", "Donald's Dreamland", (6, 9)),
    ("Pajama Place", "Donald's Dreamland", (6, 9)),
]

# [ASSUMED] How often each street is the one being played. Not a game
# rule -- nothing published says where players spend their time.
#
# Weighted toward the last two playgrounds because that is where the
# hard buildings are and where a solver earns its keep; a level 1-3
# building decides nothing. It is a training-distribution choice and
# nothing else reads it.
LATE_PLAYGROUNDS = ("The Brrrgh", "Donald's Dreamland")
LATE_WEIGHT = 4.0


# Where each playground sits in the progression, and what a toon
# fighting on its streets must already have.
#
# `laff` floors are [CONFIRMED] TTR wiki, Laff: the running total from
# ToonTasks, taken at the END of the PREVIOUS playground, because that
# is what you must have finished to be here. 15/25/34/43/52/61.
#
# The ceilings are [ASSUMED]. The same table shows laff that is not on
# the ToonTask track at all -- fishing +7, gardening +4, racing +3,
# golf +3, cog disguises +20 -- so a toon who has done side content
# arrives well above the floor. The owner puts a Dreamland toon around
# 100, which anchors the top of the range; the rest are interpolated.
#
# `pouch` floors are [CONFIRMED] TTR wiki, Gag pouch, read the same way:
# the capacity awarded by the previous playground's ToonTask.
PROGRESSION = {
    "Toontown Central":     {"stage": 1, "laff": (15, 25), "pouch": 20},
    "Donald's Dock":        {"stage": 2, "laff": (25, 40), "pouch": 25},
    "Daisy Gardens":        {"stage": 3, "laff": (34, 50), "pouch": 30},
    "Minnie's Melodyland":  {"stage": 4, "laff": (43, 60), "pouch": 35},
    "The Brrrgh":           {"stage": 5, "laff": (52, 75), "pouch": 40},
    "Donald's Dreamland":   {"stage": 6, "laff": (61, 100), "pouch": 50},
}

# Gag track acquisition, from the owner. A track is earned at the END of
# its playground, so it is in hand from the NEXT one -- which is why a
# toon fighting in Donald's Dock has three tracks and not four.
#
#   start   Throw + Squirt
#   TTC     Sound or Toon-Up
#   DD      Lure or Drop
#   DG      nothing
#   MM      the other of Sound/Toon-Up, or Trap
#   Brrrgh  whatever is left
#
# Six of the seven tracks; one is never acquired. [ASSUMED] that each
# branch is a coin flip -- the owner notes the real split is skewed,
# most obviously at the final Trap-vs-Drop choice. Weighting it later
# changes this function and nothing else.
STARTING_TRACKS = (Track.THROW, Track.SQUIRT)


def sample_tracks(rng) -> Dict[Track, int]:
    """{track: the stage from which the toon has it}.

    Stage numbers match `PROGRESSION[...]["stage"]`, so a track earned
    at the end of Toontown Central (stage 1) is available from stage 2.
    """
    have = {t: 1 for t in STARTING_TRACKS}

    first = rng.choice([Track.SOUND, Track.TOON_UP])
    have[first] = 2                              # end of TTC -> from DD

    have[rng.choice([Track.LURE, Track.DROP])] = 3     # end of DD -> DG

    # End of Minnie's Melodyland -> in hand from The Brrrgh (stage 5).
    other = Track.TOON_UP if first is Track.SOUND else Track.SOUND
    third = rng.choice([other, Track.TRAP])
    have[third] = 5

    # End of The Brrrgh -> in hand from Dreamland (stage 6). Whatever is
    # left, and one of the remaining two is never earned at all.
    left = [t for t in (Track.SOUND, Track.TOON_UP, Track.LURE,
                        Track.DROP, Track.TRAP) if t not in have]
    if left:
        have[rng.choice(left)] = 6
    return have


def street_named(name):
    """The STREETS row with this name, or None."""
    for street in STREETS:
        if street[0] == name:
            return street
    return None


def sample_street(rng):
    """Pick the street this building is on."""
    weights = [LATE_WEIGHT if pg in LATE_PLAYGROUNDS else 1.0
               for _n, pg, _r in STREETS]
    total = sum(weights)
    roll = rng.random() * total
    for street, weight in zip(STREETS, weights):
        roll -= weight
        if roll <= 0:
            return street
    return STREETS[-1]


def difficulty_for(state, rng, street=None) -> int:
    """The difficulty of the building being fought.

    [CONFIRMED] in shape: difficulty is the level of the cog that took
    the building over, and a street's cog range bounds it. The street is
    chosen by `sample_street`, whose weighting is the assumed part.

    `state` is accepted and deliberately unused for difficulty. An
    earlier version scaled difficulty on the party's laff, which had the
    causality backwards: the game does not make buildings easier because
    a weak toon walked in. Party strength now decides how many FLOORS
    are attempted, which is a real choice -- see `floors_for`.
    """
    _name, _pg, (lo, hi) = street or sample_street(rng)
    return max(1, min(9, rng.randint(lo, hi)))


def floors_for(state, difficulty: int, rng) -> int:
    """[ASSUMED] How many floors this party takes on.

    THIS is where player choice legitimately enters, and the wiki
    supports that it is a choice: "Above the elevator are white lights
    that indicate how many floors the Cog Building has", so the count is
    known before entering and a toon can decline a five-storey building.
    Difficulty is not visible that way and is not chosen.

    Scaled on the party's total laff across the range the difficulty
    allows: a solo toon takes the fewest floors that building can have,
    a full team the most. The assumption is the mapping, not the fact
    that players pick -- the wiki is explicit about the lights.
    """
    lo, hi = DIFFICULTY[difficulty]["floors"]
    if hi <= lo:
        return lo
    strength = sum(t.max_laff for t in state.toons if t.laff > 0)
    frac = max(0.0, min(1.0, strength / 400.0))
    floors = lo + round(frac * (hi - lo))
    return max(lo, min(hi, floors + rng.randint(-1, 1)))


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
        size = floor_size(floor, rng)
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

    TAKES A VACATED SLOT, rather than extending the list, and this is
    load-bearing rather than tidy. Appending pushed `state.cogs` past
    four, so a walk-in sat at index 4 -- but `rl.env.ACTIONS` is built
    for `MAX_COGS = 4` and only encodes targets 0-3, and `encode` only
    describes four cogs. Every plan aimed at a reinforcement failed the
    action lookup and silently became a PASS, so the floor could never
    be cleared: 42% of building runs stalled until truncation, one cog
    left at full health, the party holding 131 unspent gags and passing
    for thirty rounds.

    It is also what the game does. There are four battle positions; a
    cog that walks in occupies one that has been vacated.

    Mutates `state`, and is called from the party round boundary so the
    search sees reinforcements too. A search that treated a kill as
    final progress when another cog immediately replaces it would
    systematically overvalue killing.
    """
    joined = 0
    while state.holdout and len(state.active_cogs()) < MAX_PRESENT:
        replacement = state.holdout.pop(0)
        for i, cog in enumerate(state.cogs):
            if cog.status.is_dead:
                state.cogs[i] = replacement
                break
        else:
            if len(state.cogs) >= MAX_PRESENT:
                # No vacancy and no room: put it back and stop.
                state.holdout.insert(0, replacement)
                break
            state.cogs.append(replacement)
        joined += 1
    return joined
