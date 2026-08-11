"""
Depth-limited expectimax over the battle tree.

The tree alternates two node kinds:

  MAX node    -- the toon picks the action with the highest expected value
  CHANCE node -- the gag's hit roll and the cogs' counter-attack, whose
                 outcomes come from outcomes.action_outcomes() with exact
                 probabilities

Value of a state = max over legal actions of
    sum_outcomes P(outcome) * (reward + discount * value(next_state))

Rewards match simulator.step's convention (-laff lost, -lambda*gag level,
+/-100 terminal), so this optimizes the same objective a sampling agent
would. At the depth cutoff a non-terminal state is scored by the heuristic
below.

A NOTE ON THE HEURISTIC
-----------------------
Unlike everything in solver/data/, the heuristic is not a game constant to
be transcribed -- it's a design choice, and its weights are tunable rather
than [CONFIRMED]. It should not be read as authoritative. The deeper you
search the less it matters; at depth >= 4 on small fights it rarely changes
the chosen action.
"""
from typing import Dict, List, Optional, Tuple

from .. import outcomes as outcomes_mod
from .. import simulator
from ..state import BattleState, Action

WIN_VALUE = 100.0
LOSS_VALUE = -100.0


def heuristic_value(state: BattleState) -> float:
    """Score a non-terminal state at the depth cutoff, on roughly the same
    scale as the terminal rewards (+/-100).

    Two terms: progress toward killing the cogs, and laff preserved. A toon
    at full laff facing untouched cogs scores 0; one that has destroyed half
    the cog HP while losing a quarter of its laff scores 50 - 25 = 25.

    The terminal branches below are for callers scoring a position directly;
    `evaluate` never reaches them, because it returns 0 for terminal states
    (the reward that got there already carried the win/loss value).
    """
    if state.is_win():
        return WIN_VALUE
    if state.toon.laff <= 0:
        return LOSS_VALUE

    total_max_hp = sum(c.max_hp for c in state.cogs)
    remaining_hp = sum(max(0, c.hp) for c in state.cogs if not c.status.is_dead)
    cog_progress = 1.0 - (remaining_hp / total_max_hp) if total_max_hp else 1.0

    laff_kept = state.toon.laff / state.toon.max_laff if state.toon.max_laff else 0.0

    return 100.0 * cog_progress - 100.0 * (1.0 - laff_kept)


def evaluate(state: BattleState, depth: int, gag_cost_lambda: float = 0.1,
             discount: float = 1.0,
             memo: Optional[Dict] = None) -> Tuple[float, Optional[Action]]:
    """Expected value of `state` under optimal play, plus the action that
    achieves it (None at a terminal or cutoff node).

    `memo` is reused across calls if you pass one in -- worth doing when
    evaluating many states from the same fight, since transpositions are
    common (the same HP/laff/inventory position is reachable by different
    action orders).
    """
    if memo is None:
        memo = {}

    if state.is_terminal():
        # Zero, NOT +/-WIN_VALUE. The transition that reached this state
        # already paid the +/-100 in its reward, and `evaluate` returns the
        # value of what is still to come. Returning the terminal bonus here
        # too would count every win twice and systematically overvalue any
        # line that ends the fight.
        return 0.0, None
    if depth <= 0:
        return heuristic_value(state), None

    key = (outcomes_mod.state_key(state), depth)
    cached = memo.get(key)
    if cached is not None:
        return cached

    best_value = float("-inf")
    best_action: Optional[Action] = None

    for action in simulator.legal_actions(state):
        try:
            branches = outcomes_mod.action_outcomes(state, action, gag_cost_lambda)
        except NotImplementedError:
            # Gag or cog data still marked TODO -- skip this action rather
            # than let a data gap take down the whole search. The project
            # rule is that missing data must not be silently substituted;
            # here that means "can't evaluate", not "assume zero".
            continue

        value = 0.0
        for prob, next_state, reward in branches:
            future, _ = evaluate(next_state, depth - 1, gag_cost_lambda,
                                 discount, memo)
            value += prob * (reward + discount * future)

        if value > best_value:
            best_value, best_action = value, action

    if best_action is None:
        # Every action was unevaluable (or there were none). Fall back to the
        # static score so the caller gets a number rather than -inf.
        result = (heuristic_value(state), None)
    else:
        result = (best_value, best_action)

    memo[key] = result
    return result


def best_action(state: BattleState, depth: int = 3,
                gag_cost_lambda: float = 0.1) -> Optional[Action]:
    """The action to take right now. None if nothing is playable."""
    return evaluate(state, depth, gag_cost_lambda)[1]


def rank_actions(state: BattleState, depth: int = 3,
                 gag_cost_lambda: float = 0.1) -> List[Tuple[float, Action]]:
    """Every legal action with its expected value, best first. Useful for
    seeing *how much* better the top choice is -- a 0.3 gap means the
    decision barely matters, a 40 gap means don't get it wrong."""
    memo: Dict = {}
    scored = []
    for action in simulator.legal_actions(state):
        try:
            branches = outcomes_mod.action_outcomes(state, action, gag_cost_lambda)
        except NotImplementedError:
            continue
        value = sum(
            prob * (reward + evaluate(next_state, depth - 1, gag_cost_lambda,
                                      1.0, memo)[0])
            for prob, next_state, reward in branches
        )
        scored.append((value, action))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored
