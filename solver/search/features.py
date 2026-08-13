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
"""
from typing import Dict, List

from .. import data
from .. import outcomes as outcomes_mod
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
]


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
    ]


def as_dict(state: BattleState) -> Dict[str, float]:
    """Named features, for inspecting a position by hand."""
    return dict(zip(FEATURE_NAMES, extract(state)))
