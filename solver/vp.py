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
nothing else. These were [ASSUMED] at 12 apiece; the owner reports
twenty A ROUND for a solo, and that is what they now hold. Still
parameters -- `vp_plan` takes them as arguments -- but no longer
guesses.

THE ZERO AT TWENTY WAS THREE BUGS, NOT A VERDICT. This module used to
record 0.0% cleared at twenty a round and conclude the model could not
play the fight. Measured across sizes, 150 solo runs a cell with five
slips, that table read:

    cogs a round   cleared   died round 1   gags left
               8     81.3%           2.0%        76.8
              10     50.7%           2.7%        80.2
              20      0.0%          68.0%        71.0

Every one of those runs was crippled by things outside the model:

  * `unites.tick_cooldown` had NO CALLER in `solver/`, so a unite set a
    three-round cooldown that never expired -- one unite per battle
    however many were carried. A traced run died on round 37 holding
    seven of eight.
  * `env.BattleEnv.max_rounds` capped a FLOOR at 20 rounds. A solo VP
    floor is twenty cogs with four on the field and runs into the
    forties, so every long fight ended `truncated`, which is the
    harness calling time rather than a defeat. See `VP_FLOOR_ROUNDS`.
  * SOS cards were never played by the measuring harness at all:
    `BattleEnv.step` takes an index and no SOS has one, so each card
    fell to `PASS_INDEX` and the toon stood still while the run
    recorded a card as spent.

Re-measured at twenty a round with those fixed, 12 runs a cell on
identical seeds:

    carrying   cleared   rounds   laff left   gags left
    bare          0.0%     22.1         0.0        64.0
    unites        8.3%     48.5         5.2        64.2
    cards        33.3%     48.3        37.1        60.8

So the fight IS winnable solo, about one in three with cards, and the
resource is still the whole story -- bare is 0% and dies with two
thirds of the pouch unthrown. What that costs in rounds is the thing to
carry forward: a solo clear takes about 48 rounds, and `train_ppo`
builds its envs at the 20-round default, so the policy has never played
a fight of the length it would have to win.

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

# [OWNER, from play] -- TWENTY A ROUND for a solo VP, so forty cogs
# across the fight. The wiki publishes neither count, so these were
# [ASSUMED] at 12 apiece until the owner reported the real number.
#
# THE MODEL CANNOT WIN THIS FIGHT AND THE OWNER CAN. At 20 and 20 a
# solo VP measures 0.0% cleared over 150 runs, dying in the first round
# half the time; the owner beats it following the panel's own advice.
# That gap is not a tuning error, it is something missing from the
# model, and the losses say which: they end with about SEVENTY GAGS
# still in the pouch and no laff. The pouch never binds. Laff does.
#
# The owner uses Unites and SOS cards, and this project models neither
# -- see the standing assumption above. Both restore laff. Until they
# are modelled, a solo VP at its real size is a fight the solver
# believes is lost from the first round, and its advice there is being
# computed for a position it has already written off.
COG_ROUND = 20
SKELECOG_ROUND = 20

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
