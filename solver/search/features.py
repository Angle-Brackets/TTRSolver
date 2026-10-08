"""Features for scoring a position at the search's depth cutoff.

Pure standard library on purpose: the heuristic runs ~81,000 times in a
three-cog depth-2 search, inside the core solver, which must not depend
on numpy. Fitting happens offline with numpy; only the resulting weights
come back as plain floats -- see `fitted.py`.

WHAT THE OLD HEURISTIC MISSED
------------------------------
Against exact `solve()` values on 45 positions, the hand-written
`100 * cog_progress - 100 * (1 - laff_kept)` had a systematic bias of
-100 points (averaged -6.5 vs. a true 93.7): it scores relative to
"full laff, untouched cogs = 0" and ignores the +100 a winnable fight
is on track to pay. A constant term fixes most of that.

It also couldn't express which cogs the pouch can actually *kill* (a
threshold, not cog HP summed), whether gags remaining can finish the
fight, or lure/trap at all.

CONJUNCTIONS
------------
Some features only mean something as a product, which a linear model
can't discover on its own: `trapped_with_lure` (a trap is a stored gain
only with a Lure left to spring it) and `one_hit_from_death` (laff is a
smooth slide until one round of damage can end the fight, which is a
step).

PROXIES
-------
`gags_ratio` alone pulled a fit weight of 244 (vs. +/-100 for a win) --
a feature forced to stand in for a question it can't answer: will this
pouch finish the fight? Adding `damage_budget_ratio` and `cannot_finish`
to ask that directly took hold-out MAE from 50.6 to 25.6 (correlation
0.69 to 0.86) and let `gags_ratio` fall to 12.75. They also cost
something: a model that can say "full laff, but doomed" returns large
negatives where the hand-written form couldn't go below zero, which
broke the pruning floor's old assumption -- see
`expectimax.heuristic_floor`.
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
    "trap_damage_ratio",
    "has_group_gag",
    "laff_after_worst_ratio",
    "cog_hp_x_laff",
    "damage_budget_ratio",
    "cannot_finish",
]


def _fighting(state: BattleState):
    """The toons whose gags and laff still count.

    A sad toon has left the battle: their pouch is not going to be
    thrown and their laff is not going to be lost again. Falling back to
    every toon when none is standing keeps this total-free for a
    terminal state, which `fitted.value` short-circuits before asking
    but which a caller may still hand straight to `extract`.
    """
    return state.active_toons() or state.toons


def _damage_budget(state: BattleState) -> int:
    """Total damage the whole pouch can still deal, if every gag lands.

    Deliberately optimistic (every gag hits, group gags hit every cog) --
    this is a ceiling, and the useful question is whether it clears the
    remaining cog HP at all, matching the terminal rule in
    `BattleState.can_still_damage`. Trap counts only with a Lure carried,
    same as that rule.

    ARMED traps must count too: a laid trap leaves `gag_counts` and sits
    on the cog instead, so omitting it dropped the budget to zero the
    instant the setup move was played (an armed Trapdoor + Lure in hand:
    85 damage before laying it, 0 after), wrongly lighting
    `cannot_finish` on a winning position.
    """
    n_alive = len(state.active_cogs()) or 1
    toons = _fighting(state)
    # A Trap laid by one toon is sprung by anybody's Lure, so the pair
    # counts across the party as well as within a pouch.
    has_lure = any(n > 0 for toon in toons
                   for (t, _l), n in toon.gag_counts.items()
                   if t == Track.LURE)
    total = 0
    if has_lure:
        for cog in state.active_cogs():
            if not cog.status.trapped or cog.status.trap_level is None:
                continue
            try:
                total += data.gag(Track.TRAP, cog.status.trap_level).damage_at(
                    1.0, organic=False)
            except (NotImplementedError, ValueError, KeyError):
                pass
    for toon in toons:
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

    Uses `trained_fraction=1.0`, matching what
    `simulator.apply_toon_action` actually deals -- the simulator never
    rolls within the damage range, so using the low end undercounted
    every gag (36 vs 40 for a Whole Cream Pie, 75 vs 85 for a Trapdoor)
    and could wrongly flip `killable_ratio`'s threshold on a cog the
    real gag does remove.
    """
    best = 0
    for toon in _fighting(state):
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


def _trap_damage_ratio(alive) -> float:
    """Armed trap damage over the health it is sitting on, averaged
    across trapped cogs. 0 when nothing is trapped."""
    from .. import data
    from ..state import Track

    total, n = 0.0, 0
    for cog in alive:
        if not cog.status.trapped or cog.status.trap_level is None:
            continue
        try:
            dmg = data.gag(Track.TRAP, cog.status.trap_level).damage_at(
                1.0, organic=False)
        except (NotImplementedError, ValueError, KeyError):
            continue
        total += min(2.0, dmg / max(1, cog.hp))
        n += 1
    return total / n if n else 0.0


def extract(state: BattleState) -> List[float]:
    """The feature vector for `state`, in `FEATURE_NAMES` order."""
    # Pooled over toons still standing; with one toon, bit-identical to
    # the solo vector the fitted weights were trained on. Party values
    # are DEFINED, not VALIDATED -- exact solve can't reach a party
    # position to check against, so treat any party score as untested.
    fighters = _fighting(state)
    max_laff = float(sum(t.max_laff for t in fighters)) or 1.0
    team_laff = float(sum(t.laff for t in fighters))
    laff_ratio = team_laff / max_laff

    alive = [c for c in state.cogs if not c.status.is_dead]
    total_max_hp = sum(c.max_hp for c in state.cogs) or 1
    remaining_hp = sum(max(0, c.hp) for c in alive)
    cog_hp_ratio = remaining_hp / total_max_hp

    gags = sum(n for t in fighters for n in t.gag_counts.values() if n > 0)
    lure_gags = sum(n for t in fighters
                    for (tr, _l), n in t.gag_counts.items()
                    if tr == Track.LURE and n > 0)

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
    group = any(data.gag(tr, l).group
                for toon in fighters
                for (tr, l), n in toon.gag_counts.items()
                if n > 0 and tr not in (Track.TOON_UP,))

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
        # Someone is one round from going down. Per toon and not per
        # team: a round of cog attacks that removes a toon is a step
        # change, and averaging it over the party hides exactly the
        # thing the feature exists to notice.
        1.0 if incoming >= min(t.laff for t in fighters) else 0.0,
        (lured / n_alive) if n_alive else 0.0,
        # The conjunction: an armed trap is only worth something while a
        # Lure remains to spring it.
        float(trapped) if lure_gags > 0 else 0.0,
        float(trapped) if lure_gags == 0 else 0.0,
        # How big the armed trap is relative to remaining HP -- the two
        # flags above say only THAT a trap exists, so a Banana Peel (10
        # damage) and a Railroad (200) looked identical, and the fitted
        # evaluator's error on trap+lure positions ran to 176-212 points
        # (that range). No model capacity recovers information missing
        # from the input; an MLP and an explicit conjunction both failed
        # to help.
        _trap_damage_ratio(alive) if lure_gags > 0 else 0.0,
        1.0 if group else 0.0,
        max(0.0, (team_laff - incoming)) / max_laff,
        cog_hp_ratio * laff_ratio,
        # What `gags_ratio` stood in for (weight 244 on a +/-100 scale,
        # see module docstring): does the budget clear what's left.
        min(2.0, budget / remaining_hp) if remaining_hp else 2.0,
        # The threshold, stated separately, because losing is a step and
        # not a slope: below 1.0 the pouch cannot finish the fight.
        1.0 if remaining_hp and budget < remaining_hp else 0.0,
    ]


def as_dict(state: BattleState) -> Dict[str, float]:
    """Named features, for inspecting a position by hand."""
    return dict(zip(FEATURE_NAMES, extract(state)))
