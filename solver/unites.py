"""Unites: the laff and gags a toon can put back mid-fight.

WHY THIS MATTERS MORE THAN ANY WEIGHT. Every solo VP loss measured ends
with about seventy gags in the pouch and no laff, at every wave size.
The pouch never binds; laff always does. At 16 and 20 cogs a round the
solver clears 0.0% across every policy, observation version and weight
tried -- while the owner beats that fight following the panel. Unites
are the difference, and nothing in this project models them.

[CONFIRMED] TTR wiki (Unite):

  * Awarded for defeating the Chief Financial Officer.
  * A toon holds up to 100 of each type.
  * ONE at a time, and it "only affects Toons within a short radius of
    the user" -- so it is a party effect, not a self-heal.
  * Toon-Up unites come in 20, 35, 50, 65 and 80.
  * Gag-Up restocks AT MOST 7 gags for a single track, and AT MOST 30
    across all tracks.
  * Three-ROUND cooldown inside a battle (three minutes outside), shown
    as the Unite Cooldown status effect. [CONFIRMED] TTR wiki (Status
    effects#Unite Cooldown): "Toon-Up and Gag-Up unites are subjected
    to a cooldown for 3 rounds when used by Toons."
  * Values were higher before the 3.0.0 rebalancing of 3 December 2021,
    so older guides and the Toontown Online lineage will disagree.

A UNITE IS FREE. [OWNER, from play] It is a SpeedChat phrase: you use
one AND still pick and throw a gag the same round. The wiki says
nothing either way, and the owner settled it the way
`POUCH_EXEMPT_LEVEL` and the pink slip rules were settled.

That decides the shape of everything here. A unite is NOT an action and
must never compete with a gag in the action table. It is a modifier on
the round, so the question is never "unite or throw" -- it is which
unite, and whether this one is wasted.

USED IN THE PLANNING PHASE, AND APPLIED IMMEDIATELY. [OWNER, from
play] They can be used between rounds, but the model only offers them
while planning, and the effect lands at once -- a Gag-Up Throw used in
the planning phase means your Throw gags are back BEFORE you choose
what to throw, and you may then throw one of them.

That is a deliberate narrowing of the real game, taken because it
makes evaluation tractable: a unite becomes a transformation of the
state the plan is chosen from, rather than an event that can arrive at
any moment and invalidate a searched line. Modelling the inter-round
case would multiply every node by "and also, at any point, this".

PRICED ABOVE PINK SLIPS. [OWNER] "An absolute last resort, I'd even
weigh them more than Fires." Which is the opposite of what the free-
action argument above would suggest on its own, and the owner is right:
costing no gag and no round makes a unite cheap WITHIN a battle and
says nothing about its cost outside one. They come only from defeating
the Chief Financial Officer -- a whole boss run for a handful -- so the
scarcity that matters is measured in CFO runs, not in rounds. A search
that cannot see that will spend them freely and be wrong every time,
exactly as it did with pink slips while `cogs_remaining` was 0.
"""
from __future__ import annotations

from typing import Dict, Optional

# [CONFIRMED] wiki. The five Toon-Up unites, by laff restored.
TOON_UP_VALUES = (20, 35, 50, 65, 80)

# [CONFIRMED] wiki: "restock a maximum of 7 gags for a single track and
# restock a maximum of 30 gags for all tracks".
GAG_UP_SINGLE_TRACK_MAX = 7
GAG_UP_ALL_TRACKS_MAX = 30

# [CONFIRMED] wiki: three rounds inside a battle.
COOLDOWN_ROUNDS = 3

# [CONFIRMED] wiki: "Toons can hold up to 100 unites per type."
CARRY_LIMIT = 100

# [OWNER, from play] A unite is a SpeedChat phrase used ALONGSIDE a
# gag, so it spends no action. Not in the wiki either way; see the
# module docstring for why this one fact decides the whole model.
UNITE_COSTS_THE_ROUND: Optional[bool] = False

# What a unite costs the SEARCH, in the same units as
# `party_search.FIRE_PRICE` (20.0) and `FIRE_FLOOR` (20.0).
#
# [OWNER] "weigh them more than Fires" -- they are an absolute last
# resort. Set well above a slip and NOT swept: the right value depends
# on how dearly the player holds them, which is a preference rather
# than a fact about the game, exactly like `objective.waste_weight`.
# The number to check it against is behavioural: a solo VP should reach
# for a unite when it is dying and never otherwise.
UNITE_PRICE = 200.0


class UnknownUniteRule(NotImplementedError):
    """Raised where the answer to the [TODO] above would be needed."""


def costs_the_round() -> bool:
    """Whether using a unite spends the toon's gag for that round.

    False, from play. Kept as a function rather than read directly so
    that anything depending on it is greppable, and so a future
    correction lands in one place.
    """
    if UNITE_COSTS_THE_ROUND is None:
        raise UnknownUniteRule(
            "does using a unite cost the round's gag? Unanswered -- see "
            "solver/unites.py.")
    return UNITE_COSTS_THE_ROUND


def toon_up_restored(value: int, laff: int, max_laff: int) -> int:
    """Laff a Toon-Up unite actually restores, capped by headroom.

    `value` must be one of the five the game issues; an arbitrary number
    is refused rather than rounded to the nearest, since the whole point
    of the table is that the game does not offer anything else.
    """
    if value not in TOON_UP_VALUES:
        raise ValueError(
            f"{value} is not a Toon-Up unite; the game issues "
            f"{', '.join(str(v) for v in TOON_UP_VALUES)}")
    return max(0, min(int(value), int(max_laff) - int(laff)))


def apply_toon_up(toon, value: int) -> int:
    """Heal `toon` now and start its cooldown. Returns laff restored.

    Immediate, because that is how the game behaves in the planning
    phase: the laff is back before the gag is chosen.
    """
    restored = toon_up_restored(value, toon.laff, toon.max_laff)
    toon.laff = min(toon.max_laff, toon.laff + restored)
    toon.unite_cooldown = COOLDOWN_ROUNDS
    return restored


def apply_gag_up(toon, track=None) -> int:
    """Restock `toon` now and start its cooldown. Returns gags added.

    `track` None means the all-tracks unite. Both caps bind: at most 7
    into one track, at most 30 in total, and never past a gag's own
    carry limit or the pouch's.

    Level 7 gags are POUCH_EXEMPT and are deliberately not restocked
    here -- the wiki describes a restock of gags, and treating the
    exempt tier as free refills would hand the search an unlimited
    supply of the strongest gag in the game. Left out rather than
    guessed; see the [TODO] below.
    """
    from .data import gags as gags_mod

    per_track = GAG_UP_SINGLE_TRACK_MAX
    budget = GAG_UP_ALL_TRACKS_MAX if track is None else per_track
    tracks = ([track] if track is not None
              else [t for t in toon.track_exp if toon.track_exp.get(t, 0) > 0])

    added = 0
    for tr in tracks:
        room_in_track = per_track
        for level in range(1, gags_mod.POUCH_EXEMPT_LEVEL):
            if added >= budget or room_in_track <= 0:
                break
            if toon.track_exp.get(tr, 0) < level:
                continue
            try:
                cap = gags_mod.gag(tr, level).max_carry
            except (KeyError, ValueError, NotImplementedError):
                continue
            have = toon.gag_counts.get((tr, level), 0)
            room = min(cap - have, room_in_track, budget - added)
            if room <= 0:
                continue
            toon.gag_counts[(tr, level)] = have + room
            added += room
            room_in_track -= room
    toon.unite_cooldown = COOLDOWN_ROUNDS
    return added


def tick_cooldown(toon) -> None:
    """One round passes. Called wherever lure timers are ticked."""
    if getattr(toon, "unite_cooldown", 0) > 0:
        toon.unite_cooldown -= 1


def available(toon) -> bool:
    """Is a unite usable by this toon this round?"""
    return getattr(toon, "unite_cooldown", 0) <= 0


def gag_up_capacity(track_count: int) -> Dict[str, int]:
    """The two caps a Gag-Up restock is subject to.

    Returned together because a single-track unite and an all-tracks
    unite are different rewards with different limits, and using one
    cap for both is the obvious way to get this wrong: seven per track
    across seven tracks would be 49, and the game allows 30.
    """
    return {"per_track": GAG_UP_SINGLE_TRACK_MAX,
            "total": GAG_UP_ALL_TRACKS_MAX,
            "tracks": int(track_count)}
