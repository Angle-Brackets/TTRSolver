"""A leaf evaluator fitted against exact values.

The weights below were produced by `tools/fit_heuristic.py`, which
labels random positions with `expectimax.solve` -- an exact play-to-the-
end, not a bootstrapped estimate -- and solves for the least-squares fit
over `features.FEATURE_NAMES`.

They are checked in as plain floats rather than loaded from a file, and
inference is a dot product in pure Python, so the solver core keeps its
standard-library-only dependency set. numpy is needed to *fit*, never to
*run*.

WHY THIS EXISTS
---------------
The hand-written `heuristic_value` scores a position relative to "full
laff, untouched cogs = 0", while a position's true value includes the
+100 the battle is on track to pay. Measured on random positions it
therefore ran about **100 points below the truth**, which is not merely
imprecise: terminal wins score +100 and cutoff nodes scored around -6,
so any line that finished was flattered against any line that merely
looked good and ran out of horizon.

An intercept fixes that on its own. The rest of the features supply
distinctions the old form could not express at all -- how many cogs the
pouch can still kill (a threshold, not an HP ratio), how many gags are
left, whether a trap has a Lure to spring it.

REFITTING
---------
Re-run the tool and paste the block. The order of `WEIGHTS` must match
`features.FEATURE_NAMES` exactly; it is positional, and a silent
mismatch would be very hard to notice from the outside.
"""
from typing import List, Optional

from ..state import BattleState
from . import features

# Set by tools/fit_heuristic.py. None means "not fitted yet", and
# `value` falls back to the hand-written heuristic so the solver always
# has something to score with.
# Fitted by tools/fit_heuristic.py on 5,000 positions labelled with exact
# solve(), validated against 526 larger hold-out positions:
#
#                       bias     MAE      r   ordering
#     hand-written     -51.0    95.9   0.07       52%
#     fitted            +0.9    25.6   0.86       91%
#
# These replace a set fitted before `can_still_damage` existed, when a
# line that ran the pouch dry was scored by the heuristic instead of
# being a loss -- so those weights were fitted partly to their own
# output. Re-solving 400 positions under three different evaluators
# (including a deliberately absurd one) now moves 0% of the labels,
# where it moved 83% before, so these are fitted to ground truth.
#
# Two things worth reading off the numbers. `trapped_with_lure` at 30.49
# against `trapped_without_lure` at -2.00 -- the conjunction was learned
# from data rather than asserted. And `gags_ratio` fell from 244.15 to
# 12.75 when `damage_budget_ratio` and `cannot_finish` were added: a raw
# gag count had been standing in for "can this pouch actually finish the
# fight", which it cannot answer, and was being leaned on hard because
# nothing else could. Hold-out MAE went 50.6 -> 25.6 on that change
# alone.
WEIGHTS: Optional[List[float]] = [
         6.09791,   # bias
        50.26370,   # laff_ratio
       -13.59214,   # cog_hp_ratio
       -20.79878,   # cogs_alive
        12.75310,   # gags_ratio
        12.26483,   # killable_ratio
        -5.58024,   # best_gag_over_weakest_cog
       -96.63270,   # incoming_ratio
       -10.17342,   # one_hit_from_death
        14.34086,   # lured_ratio
        30.49091,   # trapped_with_lure
        -2.00390,   # trapped_without_lure
        -0.89792,   # has_group_gag
       -58.60173,   # laff_after_worst_ratio
        17.60506,   # cog_hp_x_laff
        60.42902,   # damage_budget_ratio
       -70.43923,   # cannot_finish
]


def is_fitted() -> bool:
    return WEIGHTS is not None and len(WEIGHTS) == len(features.FEATURE_NAMES)


def value_floor(state: BattleState) -> float:
    """The lowest number `value` can return for `state`.

    This is the clamp floor below, and it has to stay in step with it:
    `expectimax._value_bounds` uses it to keep star1's pruning
    admissible, so a `value` that can dip below what this promises makes
    the search cut branches it should have looked at.
    """
    from .expectimax import LOSS_VALUE

    return LOSS_VALUE - float(state.toon.max_laff)


def value(state: BattleState) -> float:
    """Estimated value of `state`, on the same scale as the search's
    terminal rewards.

    The result is clamped into the envelope `expectimax._value_bounds`
    promises, and that is a correctness requirement rather than tidiness.
    star1 prunes by bounding a chance node with the value range its
    unseen children could occupy; a leaf outside that range makes the cut
    unsound. Unclamped, this model put **32% of random positions outside
    the bounds**, as high as 175.7 against a ceiling of 100, and the
    search quietly started cutting branches it had no warrant to cut.

    Clamping loses nothing real. Winning is worth +100 and nothing beats
    it, so a leaf claiming 175 is not carrying extra information -- it is
    a linear model extrapolating past the top of the scale.
    """
    if not is_fitted():
        from .expectimax import hand_written_value

        return hand_written_value(state)

    from .expectimax import LOSS_VALUE, WIN_VALUE

    # Terminal states are not estimated, they are known. The fitted form
    # dropped this at first and scored a *lost* battle at +72, because
    # nothing in the feature set says "already over" and a linear model
    # will happily extrapolate a position with plenty of gags left. The
    # search itself returns 0 for terminal nodes before ever asking, so
    # this only bites callers scoring a position directly -- which is
    # exactly what makes it easy to miss.
    #
    # `is_terminal` and not `laff <= 0`: a toon with no way left to
    # damage a cog has also lost, and that is the case a linear model
    # extrapolates worst -- it still has laff, and may still have a
    # pocketful of Lures, so every feature here reads healthy.
    if state.is_win():
        return WIN_VALUE
    if state.is_terminal():
        return LOSS_VALUE

    total = 0.0
    for weight, feature in zip(WEIGHTS, features.extract(state)):
        total += weight * feature

    floor = LOSS_VALUE - float(state.toon.max_laff)
    if total > WIN_VALUE:
        return WIN_VALUE
    if total < floor:
        return floor
    return total


def explain(state: BattleState) -> List[tuple]:
    """(feature, value, weight, contribution), largest contribution first.

    For asking why a position scored what it did -- the fitted form is
    harder to read at a glance than two hand-written terms, and this is
    the compensation for that.
    """
    if not is_fitted():
        return []
    rows = [(name, x, w, w * x)
            for name, x, w in zip(features.FEATURE_NAMES,
                                  features.extract(state), WEIGHTS)]
    return sorted(rows, key=lambda r: -abs(r[3]))
