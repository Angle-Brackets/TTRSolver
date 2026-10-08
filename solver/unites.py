"""Unites: the laff and gags a toon can put back mid-fight.

WHY THIS MATTERS: every solo VP loss measured ends with ~70 gags still
in the pouch and no laff, at every wave size -- the pouch never binds,
laff always does. At 16+ cogs a round the solver clears 0.0% across
every policy tried, while the owner beats that fight following the
panel. Unites are the difference, and nothing else in this project
models them.

[CONFIRMED] TTR wiki (Unite):

  * Awarded for defeating the Chief Financial Officer.
  * A toon holds up to 100 of each type.
  * ONE at a time, affecting only "Toons within a short radius of the
    user" -- a party effect, not a self-heal.
  * Toon-Up unites come in 20, 35, 50, 65 and 80.
  * Gag-Up restocks AT MOST 7 gags for a single track, AT MOST 30
    across all tracks.
  * Three-ROUND cooldown inside a battle (Status effects#Unite
    Cooldown).
  * Values were higher before the 3.0.0 rebalancing of Dec 2021, so
    older guides and the Toontown Online lineage will disagree.

A UNITE IS FREE. [OWNER, from play] It's a SpeedChat phrase: you use one
AND still pick and throw a gag the same round. That decides the shape
of everything here -- a unite is NOT an action in the action table, it
is a modifier on the round, so the question is never "unite or throw"
but which unite, and whether this one is wasted.

USED IN THE PLANNING PHASE, APPLIED IMMEDIATELY. [OWNER, from play] They
can be used between rounds in reality, but the model only offers them
while planning and the effect lands at once -- a Gag-Up Throw used in
planning restocks Throw gags BEFORE the gag is chosen. A deliberate
narrowing taken for tractability: a unite is a transformation of the
state the plan is chosen from, not an event that can invalidate an
already-searched line.

PRICED ABOVE PINK SLIPS. [OWNER] "An absolute last resort, I'd even
weigh them more than Fires" -- the opposite of what "costs nothing
within a battle" would suggest alone, because they come only from
defeating the CFO (a whole boss run for a handful), so the scarcity
that matters is measured in CFO runs, not rounds. A search blind to
that will spend them freely and be wrong, as it once did with pink
slips while `cogs_remaining` was 0.

MEASURED, AND THEY DON'T HELP -- FOR A REASON THAT ISN'T ABOUT THEM.
Wired into `hybrid.climb` and run on a solo VP (100-120 runs/cell), free
unites are used only 0.6-0.7 times in a 17-round fight that allows 5-6,
and the VP stays at 0.0% at 16+ cogs regardless of price. The reason:
THE SCORER CANNOT SEE LAFF. On a fixed board and plan, `_quick_score`
returns the identical value whether the toon sits at 30 laff or 80 --
`QUICK_W["heal"]` only credits laff restored BY A GAG during the round,
never laff a toon simply HAS. A unite applied before scoring is
invisible, so no price makes it worth buying. (Same blind spot as
`QUICK_W["risk"]` being a no-op constant, and `prevent` pricing 20
incoming damage the same at 100 laff as at 20: the scorer optimises one
round's damage dealt/prevented and has no notion of surviving.)

So unites are not the missing piece the 0.0% needed -- a scorer that
values being alive is. Until it has one, this module is correct
mechanics that nothing will choose to use.
"""
from __future__ import annotations

from typing import Dict, Optional

# [CONFIRMED] wiki. The five Toon-Up unites, by laff restored.
TOON_UP_VALUES = (20, 35, 50, 65, 80)

# A full heal, as a Toon-Up "value". Realms offers one where TTR does
# not, so it is a sentinel rather than a number: no laff figure is
# correct for it, since what it restores depends on the toon.
MAX_TOON_UP = "max"


def toon_up_values(toon=None) -> tuple:
    """The Toon-Up unites this toon's game issues.

    PER TOON, because the builds differ and neither may overwrite the
    other. `TOON_UP_VALUES` above is TTR, [CONFIRMED] wiki. Realms
    issues 10, 20, 40, 80 and MAX -- [OWNER] from its in-game menu --
    and that reading lives in `solver/live/realms.py` and is injected
    here by the Realms reader.

    docs/realms.md is the rule this obeys: Realms is Toontown Online
    lineage, so nothing read from it may become the solver's own table.
    Letting it set a value on the STATE keeps the reading where it
    belongs and leaves the shipped table meaning TTR.
    """
    values = getattr(toon, "toon_up_values", None)
    return tuple(values) if values else TOON_UP_VALUES

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
# `weights.FIRE_PRICE` (20.0) and `FIRE_FLOOR` (20.0).
#
# [OWNER] "weigh them more than Fires" -- an absolute last resort,
# because "unites are extremely OP compared to Fires... otherwise it
# trivializes a lot of stuff".
#
# DO NOT SWEEP THIS FOR WIN RATE: that sweep has a known, wrong answer,
# since a unite costs no gag and no round and cheaper ones will always
# clear more VPs -- correct about the number, wrong about the game,
# spending a resource farmed over whole CFO runs to win a fight winnable
# on gags. This is a PREFERENCE (same category as
# `objective.waste_weight`), tested behaviourally rather than
# statistically: a solo VP should reach for a unite when dying and never
# otherwise -- `tests/test_unites.py` checks the shape of that.
UNITE_PRICE = 200.0

# Whether the EXACT SEARCH offers unites. Separate from
# `hybrid.OFFER_UNITES` because the cost is different in kind: the
# policy re-plans in milliseconds, while `best_action_iterative` gets a
# time budget per call, so wrapping it multiplies the wait by one plus
# the number of candidates.
#
# Safe in the common case, and that is not luck. `candidates` returns
# nothing at all when the toon holds no unites, and `unites_held`
# defaults to 0 because the readers cannot see a unite pouch -- so a
# player the overlay knows nothing about pays exactly one search, as
# before. Only a toon known to be carrying them pays more, and
# `candidates` is pruned hard: a Toon-Up only if it heals within 5 of
# its face value, a Gag-Up only for a track with real room.
OFFER_UNITES_IN_SEARCH = True


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


def toon_up_restored(value, laff: int, max_laff: int, values=None) -> int:
    """Laff a Toon-Up unite actually restores, capped by headroom.

    `value` must be one the game issues, or `MAX_TOON_UP`; an arbitrary
    number is refused rather than rounded to the nearest, since the
    whole point of the table is that the game offers nothing else.

    `values` is that game's table -- see `toon_up_values`. Omitted, it
    means TTR's, which is what every offline harness wants.
    """
    if value == MAX_TOON_UP:
        return max(0, int(max_laff) - int(laff))
    if value not in (values or TOON_UP_VALUES):
        issued = values or TOON_UP_VALUES
        raise ValueError(
            f"{value} is not a Toon-Up unite; the game issues "
            f"{', '.join(str(v) for v in issued)}")
    return max(0, min(int(value), int(max_laff) - int(laff)))


def apply_toon_up(toon, value: int) -> int:
    """Heal `toon` now and start its cooldown. Returns laff restored.

    Immediate, because that is how the game behaves in the planning
    phase: the laff is back before the gag is chosen.
    """
    restored = toon_up_restored(value, toon.laff, toon.max_laff,
                                values=toon_up_values(toon))
    toon.laff = min(toon.max_laff, toon.laff + restored)
    toon.unite_cooldown = COOLDOWN_ROUNDS
    toon.unites_held = max(0, getattr(toon, "unites_held", 0) - 1)
    _spend_stock(toon, ("toon_up", value))
    return restored


def restock_pouch(toon, track=None, budget=None, per_track=None) -> int:
    """Top up a pouch, highest levels first, evenly across tracks.

    THE SHARED RESTOCK: a Gag-Up unite and an SOS restock card do the
    same thing at different sizes -- [OWNER] "restock cards operate
    like unites, highest level gags to lowest, restock all is evenly
    done across all tracks" -- so one implementation serves both rather
    than two that could drift.

        Gag-Up unite      7 into one track    30 across all
        SOS restock      12 into one track    45 across all

    `budget` is the total this restock may add; `per_track` caps any
    single track, or None for no sub-cap. The single-track variants
    pass the same number for both, since one track IS the whole
    budget. The all-tracks variants leave `per_track` open: the wiki
    states a per-track figure only for the single-track reward, and the
    even round-robin below spreads the total anyway -- 30 over six
    tracks is five apiece and never approaches seven.

    Four caps bind at once and they are genuinely different rules:
    each gag's own `max_carry`, `per_track`, `budget`, and what the
    pouch can still hold.
    """
    from .data import gags as gags_mod

    if budget is None:
        budget = (GAG_UP_ALL_TRACKS_MAX if track is None
                  else GAG_UP_SINGLE_TRACK_MAX)
    if per_track is None and track is not None:
        per_track = budget
    limit = per_track if per_track is not None else budget

    tracks = ([track] if track is not None
              else [t for t in toon.track_exp if toon.track_exp.get(t, 0) > 0])

    # THE POUCH IS A THIRD CAP. Leaving it out let a restock add its
    # whole budget with no ceiling: 86 gags to 266 after five, and a VP
    # trace ending on 567 against a capacity of 80.
    #
    # Level 7 is pouch-exempt and is not restocked anyway, so the total
    # counts levels 1-6 -- the rule the gag menu's "Total gags" follows.
    held = sum(n for (_t, level), n in toon.gag_counts.items()
               if level < gags_mod.POUCH_EXEMPT_LEVEL)
    pouch_room = max(0, int(getattr(toon, "pouch_capacity", 80)) - held)

    # COPY ON WRITE. `ToonState.clone` SHARES `gag_counts`, so mutating
    # in place restocks every state that shares it -- including the one
    # being planned from. `_spend_gag` copies for this reason and this
    # did not, so every discarded candidate still refilled the pouch.
    counts = dict(toon.gag_counts)

    added = 0
    per_track_added = {tr: 0 for tr in tracks}
    for level in range(gags_mod.POUCH_EXEMPT_LEVEL - 1, 0, -1):
        progressed = True
        while progressed:
            progressed = False
            for tr in tracks:
                if added >= budget or added >= pouch_room:
                    break
                if per_track_added[tr] >= limit:
                    continue
                if toon.track_exp.get(tr, 0) < level:
                    continue
                try:
                    cap = gags_mod.gag(tr, level).max_carry
                except (KeyError, ValueError, NotImplementedError):
                    continue
                have = counts.get((tr, level), 0)
                if have >= cap:
                    continue
                counts[(tr, level)] = have + 1
                added += 1
                per_track_added[tr] += 1
                progressed = True
            if added >= budget or added >= pouch_room:
                break
        if added >= budget or added >= pouch_room:
            break
    toon.gag_counts = counts
    return added


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
    added = restock_pouch(
        toon, track,
        budget=(GAG_UP_ALL_TRACKS_MAX if track is None
                else GAG_UP_SINGLE_TRACK_MAX))
    toon.unite_cooldown = COOLDOWN_ROUNDS
    toon.unites_held = max(0, getattr(toon, "unites_held", 0) - 1)
    _spend_stock(toon, ("gag_up", track))
    return added


def tick_cooldown(toon) -> None:
    """One round passes. Called wherever lure timers are ticked."""
    if getattr(toon, "unite_cooldown", 0) > 0:
        toon.unite_cooldown -= 1


def available(toon) -> bool:
    """Is a unite usable by this toon this round?

    BOTH conditions. The cooldown alone made the supply unlimited, and
    an unlimited supply is not a modelling nicety -- it took solo
    buildings from 26% to 100% on one seed block and 27% to 99% on
    another, spending about four unites a building. See
    `ToonState.unites_held` for why the default is zero.
    """
    return (getattr(toon, "unite_cooldown", 0) <= 0
            and getattr(toon, "unites_held", 0) > 0)


def stock_key(choice) -> tuple:
    """The `ToonState.unite_stock` key a `candidates` pair spends.

    A Toon-Up keys on the KIND ALONE, deliberately. The wire says how
    many Toon-Up unites are held but not of which value, and the values
    a build offers are its own -- Realms carries a category TTR does not
    -- so keying on the number would invent a distinction the reading
    cannot support. A Gag-Up keys on its track, which the wire does give
    exactly.
    """
    kind, arg = choice
    if kind == "gag_up":
        return (kind, getattr(arg, "value", arg))
    return (kind, None)


def in_stock(toon, choice) -> bool:
    """Does this toon hold the unite `choice` needs?

    An EMPTY stock means unknown rather than none -- see
    `ToonState.unite_stock` -- so it permits everything, and
    `unites_held` remains the gate that says whether any unite exists.
    """
    stock = getattr(toon, "unite_stock", None)
    if not stock:
        return True
    return stock.get(stock_key(choice), 0) > 0


def _spend_stock(toon, choice) -> None:
    """Take one from the stock, COPY-ON-WRITE.

    `clone` shares this dict, so mutating it in place would spend a
    real pouch from a discarded search candidate -- the aliasing bug
    that once grew a Trap pouch from 25 to 51 with no unite used.
    """
    stock = getattr(toon, "unite_stock", None)
    if not stock:
        return
    key = stock_key(choice)
    if key not in stock:
        return
    fresh = dict(stock)
    fresh[key] = max(0, fresh[key] - 1)
    toon.unite_stock = fresh


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
    for value in toon_up_values(toon):
        if value == MAX_TOON_UP:
            # ONLY WHEN IT STRICTLY OUT-HEALS THE BIGGEST NUMBER. A MAX
            # and an 80 restore the same 40 to a toon down 40, cost the
            # same `UNITE_PRICE`, and TIE -- and `climb` breaks ties by
            # evaluation order, which would spend the premium card to do
            # a lesser card's job. The rule is about offering the
            # cheaper card when the heal is equal, not about ordering.
            # Also drops MAX for a toon down 2, where every option is
            # waste and the right move is to throw a gag.
            numbers = [v for v in toon_up_values(toon) if v != MAX_TOON_UP]
            if headroom > max(numbers, default=0):
                out.append(("toon_up", value))
        elif headroom >= value - 5:
            out.append(("toon_up", value))
    # Largest first: they are mutually exclusive this round, and a
    # bigger heal that is NOT wasted always beats a smaller one. MAX
    # sorts above every number, and must not reach the numeric key,
    # which would raise on a string.
    def _heal_rank(kv):
        if kv[0] != "toon_up":
            return 0
        return float("-inf") if kv[1] == MAX_TOON_UP else -kv[1]

    out.sort(key=_heal_rank)

    owned = [t for t, xp in toon.track_exp.items() if xp > 0]
    # ALL-TRACKS FIRST, and the order is load-bearing. A single-track
    # restock and an all-tracks one usually TIE on a one-round score (both
    # put the same best gag in hand this round), and `climb` breaks ties
    # by evaluation order -- measured, both scored 3985.0 on the same
    # board and the panel took the single track, 7 gags instead of 30 for
    # the same cooldown. The one-round scorer can't see the extra 23 gags
    # paying off later, so the tie is broken here in favour of more.
    if len(owned) > 1:
        out.append(("gag_up", None))
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
    # WHAT IS ACTUALLY HELD, when the reading says. A toon carrying only
    # a Lure restock was still offered a Squirt one, because a single
    # `unites_held` count cannot tell them apart; `unite_stock` can, and
    # an empty stock still permits everything.
    return [c for c in out if in_stock(toon, c)]


def apply(toon, choice) -> int:
    """Apply a `candidates` pair to `toon` in place. Returns what it gave."""
    kind, arg = choice
    if kind == "toon_up":
        return apply_toon_up(toon, arg)
    if kind == "gag_up":
        return apply_gag_up(toon, arg)
    raise ValueError(f"unknown unite {kind!r}")


def best_with_unite(state, value_of, price: Optional[float] = None):
    """Pick the best (unite, answer) pair for `state`, or (None, answer).

    UNITE FIRST, THEN THROW. Evaluated by transforming the state and
    re-planning on it, so the gag is chosen against the laff and gags
    the unite just restored -- which is what the game does in the
    planning phase.

    `value_of(state) -> (answer, value)` is the engine. Passing it in is
    the point: the policy path and the exact search both need this and
    had no way to share it, so the exact search simply never considered
    a unite and TTR could not use one at all.

    The unite is charged separately, so a plan that uses one has to beat
    the plan that does not BY MORE than the price, rather than merely
    beat it.
    """
    if price is None:
        price = UNITE_PRICE
    best_answer, best_value = value_of(state)
    best_choice = None
    if not state.toons:
        return None, best_answer
    for choice in candidates(state.toons[0]):
        probe = state.clone()
        try:
            apply(probe.toons[0], choice)
        except Exception:               # noqa: BLE001 - unpriced gag
            continue
        answer, value = value_of(probe)
        if value - price > best_value:
            best_value, best_choice, best_answer = value - price, choice, answer
    return best_choice, best_answer


def describe(choice) -> str:
    """One phrase for the panel."""
    kind, arg = choice
    if kind == "toon_up" and arg == MAX_TOON_UP:
        return "full Toon-Up unite"
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
