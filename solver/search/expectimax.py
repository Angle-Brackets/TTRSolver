"""
Depth-limited expectimax over the battle tree, with *-minimax pruning.

The tree alternates two node kinds:

  MAX node    -- the toon picks the action with the highest expected value
  CHANCE node -- the gag's hit roll and the cogs' counter-attack, whose
                 outcomes come from outcomes.action_outcomes() with exact
                 probabilities

Value of a state = max over legal actions of
    sum_outcomes P(outcome) * (reward + discount * value(next_state))

Rewards match simulator.step's convention (-laff lost, -lambda*gag level,
+/-100 terminal), so this optimizes the same objective a sampling agent
would.

PRUNING -- IMPLEMENTED, MEASURED, AND OFF BY DEFAULT
----------------------------------------------------
Plain alpha-beta doesn't apply to expectimax: a chance node is an average,
not a max, so one bad child can't refute it the way it can under a minimax.
The analogue is Ballard's *-minimax, and both levels are here: star1 bounds
a chance node by the unseen probability mass and cuts when that interval
leaves the (alpha, beta) window, and star2 first probes one action per
child (a MAX node is worth at least any single action, so a probe is a real
lower bound) to tighten the same test.

Both are exact -- `tests/test_search.py` checks they return the same value
AND the same move as an exhaustive search. **Both are also slower here, so
`prune` defaults to False.** Measured on a three-cog fight at depth 3:

    exhaustive   12s
    star1        52s
    star2        56s

The reason is not lost transposition sharing (the table stays 99% EXACT
either way) -- it is that the bounds are too loose to cut. A branch's value
can range over roughly 250 points, so the "unseen mass" term stays wide
until nearly every branch has been evaluated, and the cut almost never
fires. What's left is pure overhead: per-branch bound arithmetic, a sort,
and for star2 an extra subtree per branch.

Tighter admissible bounds would change this, and nothing else will. The
range is set by "could still win" (+100) against "could still lose all
remaining laff" -- so a bound that knew, say, how many rounds the cogs need
to finish the toon, or how few they need to die, would narrow it sharply.
That is the work worth doing before touching star2 again; the probe is not
the bottleneck, the interval it probes into is.

WHY A FULL SOLVE IS POSSIBLE
----------------------------
Every action consumes exactly one gag, so gags-remaining strictly decreases
down any line and the state graph is a DAG -- no cycles, and depth is
bounded by the size of the pouch rather than by anything we choose. `solve`
below exploits that: with no depth limit it plays to the end of the battle
and returns an exact optimum, not an estimate. Whether it *finishes* is a
question of branching, which is what the pruning and the symmetry
de-duplication are for.

A NOTE ON THE HEURISTIC
-----------------------
Unlike everything in solver/data/, the heuristic is not a game constant to
be transcribed -- it's a design choice, and its weights are tunable rather
than [CONFIRMED]. It only applies at a depth cutoff; a full solve never
consults it.
"""
from typing import Dict, List, Optional, Tuple

from .. import outcomes as outcomes_mod
from .. import simulator
from ..state import Action, BattleState

WIN_VALUE = 100.0
LOSS_VALUE = -100.0

# Bounds on the value of any node, needed by star1. Winning is worth +100
# and nothing beats it; the worst case is losing all remaining laff and then
# the battle. Deliberately loose -- a wrong bound would prune a real answer,
# whereas a slack one only prunes less.
VMAX = WIN_VALUE
def _vmin(state: BattleState) -> float:
    return LOSS_VALUE - float(state.toon.max_laff) - 100.0

EXACT, LOWER, UPPER = 0, 1, 2


def trim(branches, epsilon: float):
    """Keep the likeliest branches covering (1 - epsilon) of the probability,
    renormalised. Returns them plus the mass actually dropped.

    This is the one APPROXIMATE optimisation here, and it is the one that
    buys depth. A cog's damage distribution has a long thin tail -- twenty
    branches where four carry most of the mass -- and the tail costs as much
    to search as the head.

    The error is bounded, not hand-waved: dropping mass `m` from branches
    whose contributions lie in a range of width `R` moves the node's value
    by at most `m * R`. At epsilon=0.01 and R~250 that is under 2.5 points
    of EV, against decisions that are usually separated by tens. Set
    epsilon=0 for an exact search.
    """
    if epsilon <= 0 or len(branches) <= 1:
        return branches, 0.0
    ordered = sorted(branches, key=lambda b: b[0], reverse=True)
    kept, mass = [], 0.0
    for branch in ordered:
        if mass >= 1.0 - epsilon and kept:
            break
        kept.append(branch)
        mass += branch[0]
    if not kept or mass <= 0:
        return branches, 0.0
    scale = 1.0 / mass
    return [(prob * scale, nxt, reward) for prob, nxt, reward in kept], 1.0 - mass


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


# ---------------------------------------------------------------------
# Action set
# ---------------------------------------------------------------------

def _target_signature(state: BattleState, action: Action):
    """What the targets of an action look like, ignoring which slot they
    are in."""
    if action.target_index is None:
        return None
    cog = state.cogs[action.target_index]
    st = cog.status
    return (cog.cog_type, cog.department, cog.level, cog.hp, st.is_dead,
            st.lured, st.lure_rounds_remaining, st.trapped, st.trap_level)


def distinct_actions(state: BattleState) -> List[Action]:
    """Legal actions with symmetric duplicates removed.

    Throwing the same pie at two cogs that are identical in type, level, HP
    and status produces the same distribution over successor states, so
    searching both doubles the work for nothing. Three identical cogs turn
    eight actions into far fewer -- and identical cogs are the common case
    in this game, since a battle is usually several of the same cog.
    """
    seen, out = set(), []
    for action in simulator.legal_actions(state):
        key = (action.track, action.level, _target_signature(state, action))
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


# ---------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------

def evaluate(state: BattleState, depth: int, objective=None,
             discount: float = 1.0, memo: Optional[Dict] = None,
             alpha: float = float("-inf"), beta: float = float("inf"),
             prune: bool = False, epsilon: float = 0.0,
             probe_only: bool = False) -> Tuple[float, Optional[Action]]:
    """Expected value of `state` under optimal play, plus the action that
    achieves it (None at a terminal or cutoff node).

    `depth` counts plies; pass a huge number (or use `solve`) to play to the
    end of the battle.

    `prune` enables *-minimax. It is exact but currently slower than not
    pruning -- see the module docstring for the measurements and why. Left
    in because it becomes worthwhile the moment the value bounds get
    tighter, and because it is the thing to measure against.
    """
    if memo is None:
        memo = {}

    if state.is_terminal():
        # Zero, NOT +/-WIN_VALUE. The transition that reached this state
        # already paid the +/-100 in its reward, and `evaluate` returns the
        # value of what is still to come.
        return 0.0, None
    if depth <= 0:
        return heuristic_value(state), None

    # A probe searches one action and returns a LOWER bound, so it must
    # never be stored as, or answered from, an exact entry.
    key = (outcomes_mod.state_key(state), depth, epsilon)
    hit = None if probe_only else memo.get(key)
    if hit is not None:
        value, action, flag = hit
        if flag == EXACT:
            return value, action
        if flag == LOWER and value >= beta:
            return value, action
        if flag == UPPER and value <= alpha:
            return value, action

    original_alpha = alpha
    best_value, best_action = float("-inf"), None

    # Try the transposition table's move first: a good first move makes the
    # window tight immediately, and every later cutoff depends on that.
    actions = distinct_actions(state)
    if hit is not None and hit[1] is not None and hit[1] in actions:
        actions = [hit[1]] + [a for a in actions if a != hit[1]]
    elif probe_only:
        cached = memo.get(key)
        if cached is not None and cached[1] in actions:
            actions = [cached[1]]       # probe the move we already like
    if probe_only:
        actions = actions[:1]

    for action in actions:
        try:
            branches = outcomes_mod.action_outcomes(state, action, objective)
        except NotImplementedError:
            # Gag or cog data still marked TODO -- skip this action rather
            # than let a data gap take down the whole search.
            continue

        branches, _dropped = trim(branches, epsilon)
        value = _chance_value(state, branches, depth, objective,
                              discount, memo, alpha, beta, prune, epsilon,
                              probe=not probe_only)
        if value > best_value:
            best_value, best_action = value, action
        if prune:
            alpha = max(alpha, best_value)
            if alpha >= beta:
                break                      # this node is already refuted

    if best_action is None:
        result = (heuristic_value(state), None)
        memo[key] = (result[0], None, EXACT)
        return result

    if probe_only:
        return best_value, best_action      # a lower bound; never cached

    flag = (UPPER if best_value <= original_alpha
            else LOWER if best_value >= beta else EXACT)
    memo[key] = (best_value, best_action, flag)
    return best_value, best_action


def _value_bounds(state: BattleState, depth: int,
                   objective: float) -> Tuple[float, float]:
    """Admissible [floor, ceiling] on the value of a state.

    The ceiling is winning outright. The floor is losing every remaining
    point of laff and then the battle, plus the gag costs along the way.
    Both are loose -- deliberately, since a bound that is wrong prunes a
    real answer while a bound that is slack only prunes less -- but the
    floor uses CURRENT laff rather than max laff, which is both valid and
    considerably tighter as a fight wears on.
    """
    ceiling = WIN_VALUE
    floor = -(float(state.toon.laff) + 100.0
              + getattr(objective, "gag_cost", 0.1) * 7.0 * depth)
    return floor, ceiling


def _chance_value(state, branches, depth, objective, discount, memo,
                   alpha, beta, prune, epsilon=0.0, probe=True) -> float:
    """Expected value of one action, with *-minimax pruning.

    Two things make the bounds tighter than a textbook star1:

    1. Each branch's reward is *known* -- it comes in the tuple -- so only
       the recursive value needs bounding. Wrapping reward and value in one
       interval, as the first cut did, threw that away and widened every
       bound by the spread of the rewards.

    2. Star2's probing phase (`probe`). Each branch leads to a MAX node, and
       a MAX node is worth at least any single action, so evaluating one
       action per child is a genuine lower bound obtained by search rather
       than assumed. Those bounds replace the static floor, and if they
       already sum past beta the whole node is refuted before a single full
       child search runs.
    """
    if not prune:
        return sum(prob * (reward + discount *
                           evaluate(nxt, depth - 1, objective, discount,
                                    memo, prune=False, epsilon=epsilon)[0])
                   for prob, nxt, reward in branches)

    # Most probable first: they close the gap between lower and upper
    # fastest, so the thin tail is what gets cut.
    branches = sorted(branches, key=lambda b: b[0], reverse=True)
    bounds = [_value_bounds(nxt, depth - 1, objective)
              for _p, nxt, _r in branches]

    floors = [f for f, _c in bounds]
    if probe and depth > 1:
        # Probe: one action per child. Cheap relative to a full child search
        # (a MAX node here has ~4-8 actions) and often decisive.
        for i, (prob, nxt, reward) in enumerate(branches):
            if nxt.is_terminal():
                floors[i] = 0.0
                continue
            probed, _ = evaluate(nxt, depth - 1, objective, discount,
                                 memo, alpha=float("-inf"), beta=float("inf"),
                                 prune=True, epsilon=epsilon, probe_only=True)
            floors[i] = max(floors[i], probed)

        best_case_now = sum(p * (r + discount * c)
                            for (p, _n, r), (_f, c) in zip(branches, bounds))
        worst_case_now = sum(p * (r + discount * f)
                             for (p, _n, r), f in zip(branches, floors))
        if worst_case_now >= beta:
            return worst_case_now       # refuted before any full search
        if best_case_now <= alpha:
            return best_case_now

    lower = sum(p * (r + discount * f)
                for (p, _n, r), f in zip(branches, floors))
    upper = sum(p * (r + discount * c)
                for (p, _n, r), (_f, c) in zip(branches, bounds))

    total = 0.0
    for i, (prob, nxt, reward) in enumerate(branches):
        floor, ceiling = floors[i], bounds[i][1]
        contrib_floor = prob * (reward + discount * floor)
        contrib_ceiling = prob * (reward + discount * ceiling)

        # What this branch must return for the node to reach either edge.
        a_i = (alpha - (upper - contrib_ceiling)) / prob
        b_i = (beta - (lower - contrib_floor)) / prob

        child_alpha = max((a_i - reward) / discount, floor)
        child_beta = min((b_i - reward) / discount, ceiling)
        if child_alpha >= child_beta:
            child_alpha, child_beta = floor, ceiling

        value, _ = evaluate(nxt, depth - 1, objective, discount, memo,
                            child_alpha, child_beta, True, epsilon)
        f = reward + discount * value

        if f <= a_i:
            return alpha            # fails low: parent already has better
        if f >= b_i:
            return beta             # fails high: parent will cut anyway

        lower += prob * (reward + discount * value) - contrib_floor
        upper += prob * (reward + discount * value) - contrib_ceiling
        total += prob * f

    return total


def solve(state: BattleState, objective=None,
           max_depth: Optional[int] = None,
           memo: Optional[Dict] = None) -> Tuple[float, Optional[Action]]:
    """Play the battle out to the end -- exact, no heuristic.

    Safe because every action spends a gag, so no line can run longer than
    the pouch and the search cannot loop. `max_depth` is a safety valve, not
    part of the model: leave it None to solve properly.
    """
    if max_depth is None:
        max_depth = sum(n for n in state.toon.gag_counts.values() if n > 0) + 1
    return evaluate(state, max_depth, objective, memo=memo)


def best_action(state: BattleState, depth: int = 3,
                objective=None) -> Optional[Action]:
    """The action to take right now. None if nothing is playable."""
    return evaluate(state, depth, objective)[1]


def best_action_iterative(state: BattleState, depth: int = 4,
                           objective=None
                           ) -> Tuple[float, Optional[Action]]:
    """Search 1..depth, reusing the table between passes.

    Costs a little extra work at the shallow depths and usually more than
    repays it: each pass leaves its best move in the table, so the next pass
    tries that first and prunes almost immediately.
    """
    memo: Dict = {}
    value, action = 0.0, None
    for d in range(1, depth + 1):
        value, action = evaluate(state, d, objective, memo=memo)
    return value, action


def rank_actions(state: BattleState, depth: int = 3,
                 objective=None) -> List[Tuple[float, Action]]:
    """Every legal action with its expected value, best first.

    Unpruned by construction: a window that is tight enough to prune is also
    tight enough to return a bound instead of a value for the losing moves,
    and the whole point here is to show how much worse they are. Use
    `best_action` when only the choice matters.
    """
    memo: Dict = {}
    scored = []
    for action in simulator.legal_actions(state):
        try:
            branches = outcomes_mod.action_outcomes(state, action, objective)
        except NotImplementedError:
            continue
        value = sum(
            prob * (reward + evaluate(nxt, depth - 1, objective,
                                      1.0, memo)[0])
            for prob, nxt, reward in branches
        )
        scored.append((value, action))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored
