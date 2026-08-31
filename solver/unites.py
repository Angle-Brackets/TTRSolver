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

MEASURED, AND THEY DO NOT HELP -- FOR A REASON THAT IS NOT ABOUT THEM.
Wired into `hybrid.climb` as a planning-phase transformation and run on
a solo VP, 100-120 runs a cell:

    cogs a round   no unites   unites@200   unites@0   used@0
               8       79.2%        78.3%          -      0.3
              12       25.8%        17.5%          -      0.3
              16        0.0%         0.0%       0.0%      0.6
              20        0.0%         0.0%       0.0%      0.7

Free unites are used 0.6 times in a seventeen-round fight that allows
five or six, and the VP stays at zero. The price is not what stops
them.

THE SCORER CANNOT SEE LAFF. On a fixed board and a fixed plan,
`_quick_score` returns 329.40 with the toon on 30 laff and 329.40 after
restoring 80. Exactly zero difference. `QUICK_W["heal"]` credits laff
restored BY A GAG during the round, computed from the round's own
healing; laff a toon simply HAS is not a term anywhere. So a unite
applied before scoring is invisible, and no price makes an invisible
benefit worth buying.

That is the same hole three other findings have circled:
`QUICK_W["risk"]` is 0.0 and re-sweeping it changed nothing because it
is constant across candidates; `prevent` prices twenty incoming damage
identically at 100 laff and at 20; and every VP loss ends with seventy
gags in the pouch. The scorer optimises damage dealt and damage
prevented within one round, and has no notion of surviving.

So unites are not the missing piece the 0.0% needed -- the missing
piece is a scorer that values being alive. Until it has one, this
module is correct mechanics that nothing will choose to use.
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
# [OWNER] "weigh them more than Fires" -- an absolute last resort,
# because "unites are extremely OP compared to Fires... otherwise it
# trivializes a lot of stuff".
#
# DO NOT SWEEP THIS FOR WIN RATE. That sweep has a known answer and it
# is the wrong one: a unite costs no gag and no round, restores up to
# 80 laff or 30 gags, and returns every three rounds, so cheaper unites
# will always clear more VPs. The search would find that and be right
# about the number while being wrong about the game -- it would be
# spending a resource the player farms whole CFO runs for, to win a
# fight they wanted to win on gags.
#
# This is a PREFERENCE, in the same category as
# `objective.waste_weight`: "a CHOSEN number... not a [TODO] standing
# in for a fact, it is a preference about how to play." The test it has
# to pass is behavioural, not statistical -- a solo VP should reach for
# a unite when it is dying and never otherwise -- and that is what
# `tests/test_unites.py` checks the shape of.
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

    # THE POUCH IS A THIRD CAP, and leaving it out let a Gag-Up add 30
    # every time with no ceiling: a toon restocked five times carried
    # 266 gags against a capacity of 80. The wiki's two caps are per
    # USE; the pouch is what a toon can hold at all.
    #
    # Level 7 is exempt from the pouch (POUCH_EXEMPT_LEVEL) and is not
    # restocked here anyway, so the total counts levels 1-6 only --
    # the same rule the gag menu's "Total gags" label follows.
    held = sum(n for (_t, level), n in toon.gag_counts.items()
               if level < gags_mod.POUCH_EXEMPT_LEVEL)
    pouch_room = max(0, int(getattr(toon, "pouch_capacity", 80)) - held)

    added = 0
    # TOP DOWN, AND EVENLY ACROSS TRACKS. [OWNER] Filling from level 1
    # upward, one track at a time, spends the whole 30 on Squirting
    # Flowers and Cupcakes and leaves the gags worth having untouched --
    # which made a Gag-Up look nearly worthless and was the first
    # version of this.
    #
    # Highest level first, one gag per track per pass, so a restock
    # tops up the scarce end evenly rather than emptying the budget
    # into whichever track happens to be first in the list.
    #
    # Four caps bind at once: each gag's own `max_carry`, 7 per track,
    # 30 in total, and what the pouch can still hold.
    per_track_added = {tr: 0 for tr in tracks}
    for level in range(gags_mod.POUCH_EXEMPT_LEVEL - 1, 0, -1):
        progressed = True
        while progressed:
            progressed = False
            for tr in tracks:
                if added >= budget or added >= pouch_room:
                    break
                if per_track_added[tr] >= per_track:
                    continue
                if toon.track_exp.get(tr, 0) < level:
                    continue
                try:
                    cap = gags_mod.gag(tr, level).max_carry
                except (KeyError, ValueError, NotImplementedError):
                    continue
                have = toon.gag_counts.get((tr, level), 0)
                if have >= cap:
                    continue
                toon.gag_counts[(tr, level)] = have + 1
                added += 1
                per_track_added[tr] += 1
                progressed = True
            if added >= budget or added >= pouch_room:
                break
        if added >= budget or added >= pouch_room:
            break
    toon.unite_cooldown = COOLDOWN_ROUNDS
    return added


def tick_cooldown(toon) -> None:
    """One round passes. Called wherever lure timers are ticked."""
    if getattr(toon, "unite_cooldown", 0) > 0:
        toon.unite_cooldown -= 1


def available(toon) -> bool:
    """Is a unite usable by this toon this round?"""
    return getattr(toon, "unite_cooldown", 0) <= 0


def candidates(toon):
    """Unite options worth evaluating for this toon, best-value first.

    A ROUND IS TWO DECISIONS -- unite, then throw -- and the unite is
    modelled as a transformation of the state the gag is chosen from,
    never as an entry in the action table. Putting it in the table
    would multiply 246 actions by every unite on offer; wrapping the
    choice instead costs one extra evaluation per candidate.

    Pruned hard, because a unite priced at `UNITE_PRICE` will lose
    almost every comparison and evaluating hopeless ones is wasted
    search:

      * nothing at all while the cooldown runs,
      * a Toon-Up only if it heals within 5 of its face value, so an 80
        is never offered to a toon down 12,
      * a Gag-Up only for a track with real room in it.

    Returns (kind, argument) pairs. `kind` is "toon_up" or "gag_up";
    the argument is the laff value, or the Track (None = all tracks).
    """
    from .data import gags as gags_mod

    if not available(toon):
        return []
    out = []

    headroom = int(toon.max_laff) - int(toon.laff)
    for value in TOON_UP_VALUES:
        if headroom >= value - 5:
            out.append(("toon_up", value))
    # Largest first: they are mutually exclusive this round, and a
    # bigger heal that is NOT wasted always beats a smaller one.
    out.sort(key=lambda kv: -kv[1] if kv[0] == "toon_up" else 0)

    owned = [t for t, xp in toon.track_exp.items() if xp > 0]
    for track in owned:
        room = 0
        for level in range(1, gags_mod.POUCH_EXEMPT_LEVEL):
            if toon.track_exp.get(track, 0) < level:
                continue
            try:
                cap = gags_mod.gag(track, level).max_carry
            except (KeyError, ValueError, NotImplementedError):
                continue
            room += max(0, cap - toon.gag_counts.get((track, level), 0))
        if room >= GAG_UP_SINGLE_TRACK_MAX:
            out.append(("gag_up", track))
    if len(owned) > 1:
        out.append(("gag_up", None))
    return out


def apply(toon, choice) -> int:
    """Apply a `candidates` pair to `toon` in place. Returns what it gave."""
    kind, arg = choice
    if kind == "toon_up":
        return apply_toon_up(toon, arg)
    if kind == "gag_up":
        return apply_gag_up(toon, arg)
    raise ValueError(f"unknown unite {kind!r}")


def describe(choice) -> str:
    """One phrase for the panel."""
    kind, arg = choice
    if kind == "toon_up":
        return f"{arg} Toon-Up unite"
    return ("Gag-Up unite (all tracks)" if arg is None
            else f"Gag-Up unite ({arg.value})")


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
