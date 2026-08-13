"""Features for scoring a position at the search's depth cutoff.

Everything here is pure standard library on purpose. The heuristic is
called ~81,000 times in a single three-cog depth-2 search, and it lives
in the core solver, which does not depend on numpy -- so the fitting is
done offline with numpy and only the resulting weights come back, as
plain floats. See `fitted.py`.

WHAT THE OLD HEURISTIC MISSED
-----------------------------
Measured against exact `solve()` values on 45 random positions, the
hand-written `100 * cog_progress - 100 * (1 - laff_kept)` carried a
systematic bias of **-100 points**: it averaged -6.5 where the truth
averaged 93.7. It scores a position relative to "full laff, untouched
cogs = 0", while the true value of a winnable position includes the
+100 the battle is on track to pay. A constant term fixes that, and it
is the single biggest thing on this list.

After that come the distinctions it could not express at all:

- Cog HP was summed, so where the damage went was invisible. What
  matters is how many cogs the pouch can still *kill*, which is a
  threshold and not a ratio.
- Gags remaining did not appear, so a toon that cannot finish the fight
  scored the same as one that can.
- Lure and trap did not appear.

CONJUNCTIONS
------------
Several features are only worth anything in combination, and a linear
model cannot discover that on its own -- the product has to be written
out. `trapped_with_lure` is the clearest: a trap does nothing until a
cog is lured onto it, so an armed trap is a stored gain with Lure in the
pouch and dead weight without it. Those two states differ only in a gag
count unrelated to the trap.

`one_hit_from_death` is the other kind of thing a ratio cannot say: laff
is a smooth slide right up until one round of incoming damage can end
the fight, which is a step.

WHAT A PROXY LOOKS LIKE WHEN YOU FIND ONE
-----------------------------------------
`gags_ratio` -- gags carried over 20 -- came back from the first fit on
exact labels with a weight of **244** on a scale where winning is 100.
A feature that has to shout is usually standing in for a question it
cannot answer, and this one was: "will this pouch finish this fight?"
depends on how hard the gags hit and how much cog is left, neither of
which a count knows.

`damage_budget_ratio` and `cannot_finish` ask it directly. Adding them
took hold-out MAE from 50.6 to 25.6 and correlation from 0.69 to 0.86,
and `gags_ratio` fell to 12.75 -- it had been carrying the other two on
its back. They exist because running out of usable gags is now a *loss*
(`BattleState.can_still_damage`) rather than a position the search would
guess at, so the continuous version of that question is worth asking a
few rounds before it becomes terminal.

It is also the feature that cost something. A model that can say "full
laff, but doomed" returns large negative values where the hand-written
form cannot go below zero, which broke the depth-aware pruning floor
that assumed otherwise -- see `expectimax.heuristic_floor`.
"""
from typing import Dict, List

from .. import data
from .. import outcomes as outcomes_mod
from .. import simulator
from ..state import BattleState, Track

# Feature order is part of the fitted model's contract: the weights in
# `fitted.py` are positional. Appending is safe, reordering is not.
FEATURE_NAMES: List[str] = [
    "bias",
    "laff_ratio",
    "cog_hp_ratio",
    "cogs_alive",
    "gags_ratio",
    "killable_ratio",
    "best_gag_over_weakest_cog",
    "incoming_ratio",
    "one_hit_from_death",
    "lured_ratio",
    "trapped_with_lure",
    "trapped_without_lure",
    "has_group_gag",
    "laff_after_worst_ratio",
    "cog_hp_x_laff",
    "damage_budget_ratio",
    "cannot_finish",
]


def _damage_budget(state: BattleState) -> int:
    """Total damage the whole pouch can still deal, if every gag lands.

    Deliberately optimistic -- every gag hits, every group gag hits
    every cog -- because it is a *budget*, and the useful thing to know
    is whether the ceiling clears the remaining cog HP at all. A toon
    whose entire pouch cannot out-damage what is left on the field has
    lost; that is now a terminal condition rather than a value judgement
    (`BattleState.can_still_damage`), and this is the continuous version
    of the same question, for positions a few rounds short of it.

    Trap counts only when a Lure is carried, matching the terminal rule:
    a trap with nothing to spring it deals nothing.
    """
    toon = state.toon
    n_alive = len(state.active_cogs()) or 1
    has_lure = any(n > 0 for (t, _l), n in toon.gag_counts.items()
                   if t == Track.LURE)
    total = 0
    for (track, level), count in toon.gag_counts.items():
        if count <= 0 or track in (Track.TOON_UP, Track.LURE):
            continue
        if track == Track.TRAP and not has_lure:
            continue
        if toon.track_exp.get(track, 0) <= 0:
            continue
        try:
            damage = data.gag(track, level).damage_at(
                1.0, organic=toon.is_organic(track))
        except (NotImplementedError, ValueError):
            continue
        if not damage:
            continue
        reach = n_alive if simulator.is_group_action(track, level) else 1
        total += damage * count * reach
    return total


def _best_damage(state: BattleState) -> int:
    """Most damage a single gag in the pouch can do to one cog.

    Uses `trained_fraction=1.0` and the toon's organic tracks -- that is,
    exactly what `simulator.apply_toon_action` will actually deal. This
    read `damage_at(0.0)`, the low end of the range, on the reasoning
    that a conservative estimate never over-promises. That was wrong: the
    simulator does not roll within the range, it always deals the maxed
    value, so the "conservative" figure was simply a different number
    from the one the game uses -- 36 against 40 for a Whole Cream Pie,
    75 against 85 for a Trapdoor.

    It matters because this feeds `killable_ratio`, and a kill is a
    threshold. Undercounting damage by a tenth turns "this gag removes
    that cog" into "it does not", which is the single distinction the
    feature exists to capture.
    """
    toon = state.toon
    best = 0
    for (track, level), count in toon.gag_counts.items():
        if count <= 0 or track in (Track.TOON_UP, Track.LURE, Track.TRAP):
            continue
        try:
            damage = data.gag(track, level).damage_at(
                1.0, organic=toon.is_organic(track))
        except (NotImplementedError, ValueError):
            continue
        if damage and damage > best:
            best = damage
    return best


def extract(state: BattleState) -> List[float]:
    """The feature vector for `state`, in `FEATURE_NAMES` order."""
    toon = state.toon
    max_laff = float(toon.max_laff) or 1.0
    laff_ratio = toon.laff / max_laff

    alive = [c for c in state.cogs if not c.status.is_dead]
    total_max_hp = sum(c.max_hp for c in state.cogs) or 1
    remaining_hp = sum(max(0, c.hp) for c in alive)
    cog_hp_ratio = remaining_hp / total_max_hp

    gags = sum(n for n in toon.gag_counts.values() if n > 0)
    lure_gags = sum(n for (t, _l), n in toon.gag_counts.items()
                    if t == Track.LURE and n > 0)

    best = _best_damage(state)
    killable = sum(1 for c in alive if best >= c.hp)
    weakest = min((c.hp for c in alive), default=1) or 1

    incoming = 0
    for cog in alive:
        try:
            incoming += outcomes_mod.worst_case_damage(cog)
        except NotImplementedError:
            pass

    budget = _damage_budget(state)
    lured = sum(1 for c in alive if c.status.lured)
    trapped = sum(1 for c in alive if c.status.trapped)
    n_alive = len(alive)
    group = any(data.gag(t, l).group
                for (t, l), n in toon.gag_counts.items()
                if n > 0 and t not in (Track.TOON_UP,))

    return [
        1.0,
        laff_ratio,
        cog_hp_ratio,
        float(n_alive),
        # Normalised so a full pouch and a nearly empty one are far
        # apart without the raw count swamping every other term.
        min(1.0, gags / 20.0),
        (killable / n_alive) if n_alive else 1.0,
        # How close the best gag comes to removing the easiest cog. Above
        # 1 means it kills it, and the ratio keeps "nearly" distinct from
        # "not at all".
        min(2.0, best / weakest) if weakest else 2.0,
        min(2.0, incoming / max_laff),
        1.0 if incoming >= toon.laff else 0.0,
        (lured / n_alive) if n_alive else 0.0,
        # The conjunction: an armed trap is only worth something while a
        # Lure remains to spring it.
        float(trapped) if lure_gags > 0 else 0.0,
        float(trapped) if lure_gags == 0 else 0.0,
        1.0 if group else 0.0,
        max(0.0, (toon.laff - incoming)) / max_laff,
        cog_hp_ratio * laff_ratio,
        # What `gags_ratio` was standing in for. A raw gag count knows
        # nothing about how hard the gags hit or how much cog is left,
        # and the fit leaned on it hard enough (weight 244 on a +/-100
        # scale) to suggest it was carrying a question it could not
        # actually answer.
        min(2.0, budget / remaining_hp) if remaining_hp else 2.0,
        # The threshold, stated separately, because losing is a step and
        # not a slope: below 1.0 the pouch cannot finish the fight.
        1.0 if remaining_hp and budget < remaining_hp else 0.0,
    ]


def as_dict(state: BattleState) -> Dict[str, float]:
    """Named features, for inspecting a position by hand."""
    return dict(zip(FEATURE_NAMES, extract(state)))
