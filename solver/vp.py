"""The Sellbot VP's turn-based rounds, as a two-floor facility.

WHAT THE WIKI CONFIRMS (Vice President): two turn-based rounds, Cogs
then Skelecogs separately; cog round levels 1-12, skelecog round levels
8-12; the final phase is thrown pies, not turn-based combat, and is out
of scope. Skelecogs are modelled as ordinary cogs of the same level --
the wiki says they "behave and communicate like regular Cogs" and
publishes no separate stat table, and the owner confirms they're
identical.

WHAT IS NOT PUBLISHED, AND SO IS A PARAMETER: how many cogs each round
contains. [ASSUMED] at 12 apiece until the owner reported twenty A ROUND
for a solo VP, which is what COG_ROUND/SKELECOG_ROUND hold now -- still
parameters (`vp_plan` takes them as arguments), no longer guesses.

THE ZERO AT TWENTY WAS THREE BUGS, NOT A VERDICT. This module used to
measure 0.0% cleared at twenty a round (150 solo runs/cell, five slips):

    cogs a round   cleared   died round 1   gags left
               8     81.3%           2.0%        76.8
              10     50.7%           2.7%        80.2
              20      0.0%          68.0%        71.0

Every one of those runs was crippled by bugs outside the model:
`unites.tick_cooldown` had no caller, so a unite's cooldown never
expired (one per battle, however many carried); `env.BattleEnv.max_rounds`
capped a FLOOR at 20 rounds while a solo VP floor runs into the forties,
so long fights were scored `truncated` rather than lost; and SOS cards
had no action index, so the harness silently passed instead of playing
them. Re-measured at twenty a round with those fixed (12 runs/cell,
identical seeds):

    carrying   cleared   rounds   laff left   gags left
    bare          0.0%     22.1         0.0        64.0
    unites        8.3%     48.5         5.2        64.2
    cards        33.3%     48.3        37.1        60.8

The fight IS winnable solo, about one in three with cards -- bare still
clears 0% and dies with two thirds of the pouch unthrown, so the
resource is still the whole story. A solo clear takes ~48 rounds, and
`train_ppo` builds its envs at the 20-round default, so the policy has
never played a fight of the length it would have to win.

A ROUND IS A FLOOR, and the waves are the holdout: four cogs on the
field at once, the rest walking in as slots free, one pouch and one
laff pool across both rounds, no restocking or healing between them --
the VP, minus the pies.

THE PARTY: four toons split two-and-two, so a `vp_position` is a
TWO-toon party, one side of the room. Maxed: 137 laff, an 80-gag pouch,
and every track the toon owns trained to 7. Six tracks, not seven -- a
toon can never hold all seven (`facility.sample_tracks` never earns one
of the five optional tracks), so "maxed" means six tracks at 7. No SOS
cards, Unites or Fires, the standing assumption everywhere in this
project rather than a VP-specific choice.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from . import facility
from .data import gags as gags_mod
from .state import BattleState, CogState, ToonState, Track

# [OWNER, from play] -- TWENTY A ROUND for a solo VP, so forty cogs
# across the fight. The wiki publishes neither count; these were
# [ASSUMED] at 12 apiece until the owner reported the real number.
#
# THE MODEL CANNOT WIN THIS FIGHT AND THE OWNER CAN: at 20 and 20 a solo
# VP measures 0.0% cleared over 150 runs, dying in the first round half
# the time, while the owner beats it following the panel's own advice.
# The losses end with ~70 gags still in the pouch and no laff -- the
# pouch never binds, laff does, and the owner's Unites and SOS cards
# (neither modelled here) are what restores it.
COG_ROUND = 20
SKELECOG_ROUND = 20

# [OWNER, from play] A VP is twenty cogs a round IN ALL. Alone you face
# all twenty; with company the toons split evenly across the two sides
# and each side faces half -- two players one a side, four players two
# a side, ten cogs a round either way. So a solo VP and a party VP are
# not the same fight scaled: a party side meets half the cogs.
PARTY_COG_ROUND = 10
PARTY_SKELECOG_ROUND = 10


def side_rounds(players: int) -> Tuple[int, int]:
    """(cog round, skelecog round) one side faces, for a VP of `players`
    toons in all -- not the toons on that side, which cannot tell a solo
    VP from one side of a two-player VP."""
    if players <= 1:
        return COG_ROUND, SKELECOG_ROUND
    return PARTY_COG_ROUND, PARTY_SKELECOG_ROUND

# [CONFIRMED] wiki: the two rounds' level bands.
COG_LEVELS = (1, 12)
SKELECOG_LEVELS = (8, 12)

MAXED_LAFF = 137
MAXED_POUCH = 80

# Laff the party brings, 100 to 137. 137 is the true ceiling, but a toon
# with maxed GAGS and unmaxed LAFF is the commoner VP-goer: gag training
# and laff come from different grinds. Fixing it at 137 trained the
# policy on the ceiling only, and the owner's toon is 100 -- a 37-point
# gap worth about sixteen points of VP win rate, so sweeping the range
# puts both in the data.
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


# [OWNER] The owner's solo VP pouch, Toon-Up-less, as (track, level):
# count. MAX is the game's carry limit -- TNT, Trunk and Foghorn are
# maxed "across both" games, whose Sound and Trap limits differ. Magnets
# are listed as 7-10 and take whatever room is left, up to 10. Level 7s
# are pouch-exempt and carried one each, as `maxed_toon` already does.
#
# It replaces `maxed_toon`'s top-down fill, which packs by LEVEL: a
# third of that pouch was Trap and it ran out of room before Big Magnet,
# so the toon could lure all four skelecogs on few rounds.
MAX = None
OWNER_VP_POUCH = {
    (Track.TRAP, 6): MAX, (Track.TRAP, 5): 7,
    (Track.LURE, 6): 3, (Track.LURE, 5): 7,
    (Track.SOUND, 6): MAX, (Track.SOUND, 5): MAX, (Track.SOUND, 4): 5,
    (Track.THROW, 6): 3, (Track.THROW, 5): 7, (Track.THROW, 4): 4,
    (Track.SQUIRT, 6): 3, (Track.SQUIRT, 5): 7, (Track.SQUIRT, 4): 4,
    (Track.DROP, 6): 3, (Track.DROP, 5): 7,
}
OWNER_MAGNETS = (7, 10)


def owner_vp_pouch(toon: ToonState) -> ToonState:
    """Restock `toon` with the owner's VP pouch, for the tracks it has."""
    counts: Dict = {}
    for track in toon.track_exp:
        counts[(track, 7)] = gags_mod.carry_limit(track, 7, 7)
    for (track, level), want in OWNER_VP_POUCH.items():
        if toon.track_exp.get(track, 0) >= level:
            limit = gags_mod.carry_limit(track, level, 7)
            counts[(track, level)] = limit if want is MAX else min(want, limit)
    if toon.track_exp.get(Track.LURE, 0) >= 4:
        room = toon.pouch_capacity - gags_mod.pouch_total(counts)
        counts[(Track.LURE, 4)] = max(0, min(OWNER_MAGNETS[1], room))
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
