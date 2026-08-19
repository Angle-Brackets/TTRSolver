"""The CEO's two turn-based cog battles.

WHAT THE WIKI CONFIRMS (Chief Executive Officer)
------------------------------------------------
Four phases, of which two are turn-based combat and are what this models:

  1. First cog battle -- "waiter-suited Cogs, some of which are Version
     2.0, that range from level 9 to level 14".
  2. Banquet round -- feeding oil cans, real-time, NOT modelled. Two cans
     kill an ordinary cog and three kill a Version 2.0.
  3. Second cog battle -- "Toons first battle a level 14 Version 2.0 Big
     Cheese and then battle the leftover Cogs if there are any".
  4. Final battle -- golf balls and seltzer, real-time, NOT modelled.

THE BANQUET IS THE COUPLING, and it is why `LEFTOVERS` is a parameter
rather than a constant: whatever survives phase 2 walks into phase 3. The
minigame cannot be modelled, but its OUTPUT is just a count, so sweeping
that count covers the whole range of banquet outcomes from perfect play
to none at all.

WHAT IS ASSUMED, AND WHERE IT CAME FROM
---------------------------------------
`V2_FRACTION` -- the wiki says only "some of which are Version 2.0".
[ASSUMED] at 0.20 from the owner's observed play.

Open Toontown says otherwise and is recorded here because the
disagreement is the useful part: `SuitBuildingGlobals.SuitBuildingInfo`
entry 14 -- the building code the CEO's first battle passes -- is the
ONLY entry in that table carrying a sixth field, `REVIVES (1,)`, and
`SuitPlannerInteriorAI` applies that one value to every suit it
generates. In Toontown Online the first battle is therefore 100% Version
2.0. TTR evidently rebalanced it. Observed play wins; the source is kept
so a disagreement has somewhere to start.

`LEFTOVERS` are ALL Version 2.0. [OPEN TOONTOWN SOURCE], confirmed by the
owner: `generateDinerSuits` builds every diner with `revives=1`, and
`__genSuitObject` passes that straight to `setSkeleRevives`.

The second battle's opener is ONE level 14 Big Cheese, per the wiki. Open
Toontown makes it TWO at level 12; the wiki is the source of truth for
TTR, and the discrepancy is noted rather than split.

THE PARTY
---------
Four toons splitting two and two, exactly as the VP does, so a
`ceo_position` is one side of the room. Laff 100-119, gags maxed with
level 7s available, and five pink slips each -- which is a lot of
firepower, and deliberately so: the CEO is the fight pink slips are the
reward for.
"""
from __future__ import annotations

from typing import List, Optional

from . import facility, vp
from .state import BattleState, CogState

# [ASSUMED] owner's observed play. Open Toontown says 1.00 -- see above.
V2_FRACTION = 0.20

# [ASSUMED] neither the wiki nor the source gives a count for battle one.
ROUND_ONE = 12

# Banquet survivors carried into battle two. Swept, not guessed.
LEFTOVERS = 10

# [CONFIRMED] wiki: "range from level 9 to level 14".
COG_LEVELS = (9, 14)

# [CONFIRMED] wiki: battle two opens with a level 14 v2.0 Big Cheese.
BIG_CHEESE_LEVEL = 14

LAFF_RANGE = (100, 119)
FIRES_PER_TOON = 5
PARTY_SIZE = 2


def _as_v2(cog: CogState) -> CogState:
    """Put the outer suit on. A v2.0 carries a second full health pool."""
    cog.status.suited = True
    return cog


def ceo_plan(rng, cog_factory,
             round_one: Optional[int] = None,
             leftovers: Optional[int] = None,
             v2_fraction: Optional[float] = None) -> facility.FacilityPlan:
    """Two floors: the waiter battle, then the Big Cheese and leftovers.

    Read at call time rather than as default arguments, because binding
    these once at import is how `vp_plan` silently measured the same
    round size four times.
    """
    round_one = ROUND_ONE if round_one is None else round_one
    leftovers = LEFTOVERS if leftovers is None else leftovers
    v2_fraction = V2_FRACTION if v2_fraction is None else v2_fraction

    lo, hi = COG_LEVELS
    first: List[CogState] = []
    for _ in range(round_one):
        cog = cog_factory(rng, rng.randint(lo, hi))
        if rng.random() < v2_fraction:
            _as_v2(cog)
        first.append(cog)

    second: List[CogState] = [_as_v2(cog_factory(rng, BIG_CHEESE_LEVEL))]
    # Every banquet survivor is a Version 2.0.
    second += [_as_v2(cog_factory(rng, rng.randint(lo, hi)))
               for _ in range(leftovers)]

    return facility.FacilityPlan([first, second])


def ceo_position(rng) -> BattleState:
    """One side of the CEO: two toons, cogs supplied by the env."""
    party = [vp.maxed_toon(rng, laff=rng.randint(*LAFF_RANGE))
             for _ in range(PARTY_SIZE)]
    for toon in party:
        toon.fires = FIRES_PER_TOON
    return BattleState(toons=party, cogs=[], kind="ceo", street=None)
