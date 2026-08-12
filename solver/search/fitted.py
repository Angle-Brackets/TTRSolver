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
# Fitted by tools/fit_heuristic.py on 500 positions labelled with exact
# solve(), validated against 200 larger hold-out positions:
#
#                       bias     MAE   ordering
#     hand-written     -81.7    88.2
#     fitted            +2.6    25.6        88%
#
# Note trapped_with_lure at 10.86 against trapped_without_lure at 1.21 --
# the conjunction was learned from data rather than asserted.
WEIGHTS: Optional[List[float]] = [
        89.35447,   # bias
       114.29601,   # laff_ratio
       -35.41613,   # cog_hp_ratio
        -6.31769,   # cogs_alive
       123.70781,   # gags_ratio
        10.99404,   # killable_ratio
         6.01656,   # best_gag_over_weakest_cog
      -241.42101,   # incoming_ratio
       -28.90460,   # one_hit_from_death
        10.28524,   # lured_ratio
        10.85692,   # trapped_with_lure
         1.20922,   # trapped_without_lure
         5.05708,   # has_group_gag
      -118.68309,   # laff_after_worst_ratio
        22.45269,   # cog_hp_x_laff
]


def is_fitted() -> bool:
    return WEIGHTS is not None and len(WEIGHTS) == len(features.FEATURE_NAMES)


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
    if state.is_win():
        return WIN_VALUE
    if state.toon.laff <= 0:
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
