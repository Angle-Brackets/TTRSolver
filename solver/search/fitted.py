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
#
# Fitted on 5,000 positions labelled with exact solve(), validated on
# 406 hold-out positions:
#
#                       bias     MAE      r   ordering
#     hand-written     -51.2    94.3   0.07       53%
#     fitted            +4.5    24.3   0.78       89%
#
# Includes `trap_damage_ratio` (18th feature: HOW BIG an armed trap is,
# not just that one exists -- a Banana Peel and a Railroad were
# previously identical inputs).
#
# WATCH THIS PAIR: `trap_damage_ratio` fits NEGATIVE while
# `trapped_with_lure` is large and positive. Both fire under nearly the
# same condition (armed trap + lure in hand), so they are collinear and
# least squares splits them arbitrarily -- trust their SUM, not either
# number alone. Check jointly on trap+lure positions with
# scratchpad/evaltest.py (worst-case error, not MAE) before relying on
# either.
#
# Refit whenever a rule change alters what an exact label means
# (accuracy, damage, Toon-Up, turn_cost, scarcity, ...) -- gags_ratio
# and trapped_with_lure/trapped_without_lure are the conjunction and
# proxy features most worth re-checking after one. In practice each
# refit so far has moved hold-out MAE by about a point; that is only
# visible after refitting, not a reason to skip one.
WEIGHTS: Optional[List[float]] = [
        17.07794,   # bias
       160.14802,   # laff_ratio
        -5.19713,   # cog_hp_ratio
       -10.77392,   # cogs_alive
        10.00955,   # gags_ratio
        12.96260,   # killable_ratio
       -11.64607,   # best_gag_over_weakest_cog
      -206.74381,   # incoming_ratio
        -9.26712,   # one_hit_from_death
        14.33018,   # lured_ratio
         0.04219,   # trapped_with_lure
        -0.40809,   # trapped_without_lure
        -0.45375,   # trap_damage_ratio
         2.20267,   # has_group_gag
      -158.69354,   # laff_after_worst_ratio
         3.83806,   # cog_hp_x_laff
        51.01574,   # damage_budget_ratio
       -99.95419,   # cannot_finish
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

    # Terminal states are not estimated, they are known: nothing in the
    # feature set says "already over", so a linear model will happily
    # extrapolate a *lost* battle at +72. The search itself returns 0 for
    # terminal nodes, so this only bites a caller scoring a state directly.
    #
    # `is_terminal`, not `laff <= 0`: a toon with no way left to damage a
    # cog has also lost, and still reads healthy on every other feature.
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
