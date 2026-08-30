"""The Sellbot VP's turn-based rounds, as a two-floor facility.

WHAT THE WIKI CONFIRMS (Vice President)
---------------------------------------
  * "There are two turn-based combat rounds consisting of Cogs and
    Skelecogs separately."
  * Cog round: "Cogs that range from level 1 to level 12".
  * Skelecog round: "Skelecogs ranging from level 8 to level 12".
  * The final phase is thrown pies, not turn-based combat, so it is out
    of scope here -- nothing in this project models it and nothing
    should pretend to.

Skelecogs are modelled as ordinary cogs of the same level. The wiki says
they "behave and communicate like regular Cogs" and publishes no separate
stat table, and the project owner confirms they are identical.

WHAT IS NOT PUBLISHED, AND SO IS A PARAMETER
--------------------------------------------
How many cogs each round contains. The wiki gives the level bands and
nothing else. These were [ASSUMED] at 12 apiece; the owner has since
reported twenty across a solo VP, ten a round, and that is what they
now hold. Still parameters -- `vp_plan` takes them as arguments -- but
no longer guesses.

WHERE A SOLO VP IS LOST, measured at that size: the skelecog round, not
the cog round. It reaches round two 97% of the time and loses there
47% of the time holding five slips. Arriving at the skelecogs with laff
left is the whole problem, which is why the fights that fail do so with
about seventy gags still in the pouch.

A ROUND IS A FLOOR, and the waves are the holdout. That mapping is why
this fits the existing machinery with no new mechanics: four cogs on the
field at once, the rest walking in as slots free up, one pouch and one
laff pool across both rounds, no restocking and no healing between them.
Which is the VP, minus the pies.

THE PARTY
---------
Four toons, but they split two-and-two, so a `vp_position` is a TWO-toon
party -- one side of the room. Maxed: 137 laff, an 80-gag pouch, and
every track the toon owns trained to level 7.

Six tracks, not seven. A toon can never hold all seven -- see
`facility.sample_tracks`, where one of the five optional tracks is never
earned -- so "maxed" here means six tracks at 7, which is the real
ceiling.

No SOS cards, Unites or Fires, which is the standing assumption
everywhere in this project rather than a choice made for the VP.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from . import facility
from .data import gags as gags_mod
from .state import BattleState, CogState, ToonState, Track

# [OWNER, from play] -- twenty cogs across a SOLO VP, ten in each round.
# The wiki publishes neither count, so this was [ASSUMED] at 12 apiece
# until the owner reported the real number from a fight they had just
# won. Their observation beats the guess and beats anything derivable.
#
# TWENTY IS THE WHOLE FIGHT, not each round, and getting that wrong is
# worth recording because it inverted a conclusion. Set as 20 AND 20 --
# forty cogs -- a solo VP measured 0.0% cleared and died in the first
# round half the time, which said the fight was impossible while the
# owner was beating it. At 10 and 10 it reads 50.7% with five slips: a
# coin flip they won, which is what actually happened.
COG_ROUND = 10
SKELECOG_ROUND = 10

# [CONFIRMED] wiki: the two rounds' level bands.
COG_LEVELS = (1, 12)
SKELECOG_LEVELS = (8, 12)

MAXED_LAFF = 137
MAXED_POUCH = 80

# Laff the party brings. 137 is the true ceiling, but a toon with maxed
# GAGS and unmaxed LAFF is the commoner VP-goer: gag training and laff
# come from different grinds, and the wiki's own laff table hands out +17
# for fishing, gardening, racing and golf, none of which grants a point
# of gag experience. Sweep it -- with the first toon loss deciding a
# building, laff is the axis this model is most sensitive to.
# 100 to 137. Fixing it at 137 trained the policy on the ceiling only,
# and the owner's toon is 100 -- a 37-point gap worth about sixteen
# points of VP win rate, so the two are not the same fight. Sweeping the
# range puts both in the data.
LAFF_RANGE = (100, MAXED_LAFF)


def maxed_toon(rng, tracks: Optional[Dict[Track, int]] = None,
               laff: Optional[int] = None) -> ToonState:
    """A fully trained toon: 137 laff, 80 gags, every owned track at 7.

    Which six tracks is still a draw, because which one a toon skipped is
    a real difference between two maxed toons and the VP does not care
    which you brought.
    """
    have = tracks if tracks is not None else facility.sample_tracks(rng)
    exp = {track: 7 for track in have}

    # Read LAFF_RANGE at call time so a caller can sweep it; a default
    # argument would bind once at import and silently measure the same
    # party every time, which this module has already been caught doing
    # with the round sizes.
    if laff is None:
        laff = rng.randint(*LAFF_RANGE)
    toon = ToonState(laff=laff, max_laff=laff,
                     track_exp=exp, gag_counts={},
                     pouch_capacity=MAXED_POUCH)

    # Fill from the top down, exactly as `env._fill_pouch` does: the
    # heavy gags first, then whatever room is left goes to the cheap
    # ones. Level 7s are pouch-exempt so they are added outside the
    # budget, one each, which is the real carry limit.
    counts: Dict = {}
    for track in exp:
        counts[(track, 7)] = gags_mod.carry_limit(track, 7, 7)
    for level in range(6, 0, -1):
        for track in exp:
            room = MAXED_POUCH - gags_mod.pouch_total(counts)
            if room <= 0:
                break
            want = min(gags_mod.carry_limit(track, level, 7), room)
            if want > 0:
                counts[(track, level)] = want
    toon.gag_counts = {k: v for k, v in counts.items() if v > 0}
    return toon


def vp_plan(rng, cog_factory,
            cog_round: Optional[int] = None,
            skelecog_round: Optional[int] = None) -> facility.FacilityPlan:
    """Two floors: the cog round, then the skelecog round.

    `cog_factory(rng, level)` is injected for the same reason
    `facility.plan_facility` injects it -- which cogs are safe to sample
    is a caller's concern, not a rule of the fight.
    """
    # Read the module values at CALL time, not as default arguments.
    # Defaults bind once at definition, so a caller sweeping
    # `vp.COG_ROUND` would silently measure the same size four times --
    # which is exactly what happened the first time this was run.
    cog_round = COG_ROUND if cog_round is None else cog_round
    skelecog_round = (SKELECOG_ROUND if skelecog_round is None
                      else skelecog_round)

    floors: List[List[CogState]] = []
    for count, (lo, hi) in ((cog_round, COG_LEVELS),
                            (skelecog_round, SKELECOG_LEVELS)):
        floors.append([cog_factory(rng, rng.randint(lo, hi))
                       for _ in range(count)])
    return facility.FacilityPlan(floors)


def vp_position(rng) -> BattleState:
    """One side of the VP: two maxed toons, cogs supplied by the env.

    `kind="vp"` so `BattleEnv.reset` knows to build the plan from
    `vp_plan` rather than from a street's difficulty row -- the VP is not
    on a street and has no difficulty rating.
    """
    party = [maxed_toon(rng) for _ in range(2)]
    return BattleState(toons=party, cogs=[], kind="vp", street=None)
