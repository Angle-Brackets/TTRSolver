"""
Depth-limited expectimax over the battle tree, with *-minimax pruning.

Two node kinds alternate: MAX (the toon picks the highest-EV action) and
CHANCE (the gag's hit roll and the cogs' counter-attack, with exact
probabilities from `outcomes.action_outcomes`). Rewards follow
`simulator.step`'s convention (-laff lost, -lambda*gag level, +/-100
terminal), so this optimizes the same objective a sampling agent would.

PRUNING
-------
Plain alpha-beta doesn't apply: a chance node is an average, not a max,
so one bad child can't refute it. The analogue is Ballard's *-minimax:
star1 bounds a chance node by the unseen probability mass and cuts when
that interval leaves (alpha, beta); star2 first probes one action per
child (a MAX node is worth at least any single action, a real lower
bound) to tighten the same test. Both exact -- `tests/test_search.py`
checks identical value AND move against exhaustive search.

Pruning only pays once the bounds are tight. The floor used to assume
the toon could lose its whole laff bar; made depth-aware instead (at
most `d` rounds of damage at depth `d` -- see `_value_bounds`), pruning
went from a loss to a 2.7-3.9x win that grows with cog count. Caching
the damage distribution, a gag-count-free merge key, and `__slots__`
added a further 7-25x on top (measured at depth 2, 2-4 cogs). Set
`prune=False` to measure against either change.

That floor must track whichever evaluator is installed
(`heuristic_floor`): the hand-written form bottoms out from laff alone,
but the fitted evaluator can score a full-laff toon at -98 (pouch can't
finish the fight), so it needs its own minimum. Pruning still wins with
it, just less tightly (2.0x cut vs. 1.3-1.4x for the hand-written form).

TERMINATION AND EXACTNESS
--------------------------
Every action but the pass spends a gag; the pass is legal only while a
cog is lured, and lured rounds tick down. So (gags remaining, lure
rounds remaining) strictly decreases down any line, the state graph is
a DAG, and `solve` terminates.

Exactness also needs `BattleState.can_still_damage` as a terminal
condition: without it, running out of gags with cogs still alive left
no legal actions and fell through to `heuristic_value` at a non-cutoff
node. Re-solving 300 cached positions under two heuristics changed 83%
of the answers before this was fixed. `heuristic_value` is now reached
only at a depth cutoff, so two `solve` results are comparable regardless
of which heuristic is installed.

What an out-of-gags position is worth (loss, fleeing, or playing out the
cog phase to defeat) is a modelling decision left open rather than
guessed at.

HEURISTIC
---------
Unlike `solver/data/`, the heuristic is a tunable design choice, not a
[CONFIRMED] game constant. It only applies at a depth cutoff; a full
solve never consults it.
"""
import time
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


class MissingData(Exception):
    """Every action at a node was unevaluable because of a [TODO] cell.

    Distinct from "no good move": the search could not look at all. The
    caller should say which cell, and fall back to something that can
    answer, rather than present an empty result as advice.
    """


class SearchTimeout(Exception):
    """Raised inside `evaluate` when a deadline passes.

    An abandoned pass is discarded whole. Iterative deepening always has
    a complete shallower answer to fall back on, and half a pass is not
    an answer -- the unexplored actions are exactly the ones that might
    have been best.
    """


# How many nodes to visit between clock checks. `time.monotonic()` is
# cheap but this is the hottest loop in the program, and the search
# visits ~300,000 nodes for a two-cog depth-2 position, so checking every
# node is measurable while checking every few hundred is not. The cost of
# the coarser check is overshooting a deadline by a few hundred nodes.
DEADLINE_CHECK_INTERVAL = 512

# Passing exact_plies=0 turns on `outcomes.collapse_damage`, subject to
# `may_collapse`. None disables collapsing entirely and is the default,
# so nothing approximates unless a caller asks.
#
# The number counts plies nearest the root that stay exact regardless.
# It is kept because it is the natural knob to reach for, but 1 is NOT a
# useful setting and the measurements say why: keeping the root exact
# removed the entire benefit on three and four cogs, because the saving
# compounds downward. Collapse near the root or do not bother.
COLLAPSE_EVERYWHERE = 0


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


def hand_written_value(state: BattleState) -> float:
    """Score a non-terminal state at the depth cutoff, on roughly the same
    scale as the terminal rewards (+/-100).

    Two terms: progress toward killing the cogs, and laff preserved. A toon
    at full laff facing untouched cogs scores 0; one that has destroyed half
    the cog HP while losing a quarter of its laff scores 50 - 25 = 25.

    The terminal branches below are for callers scoring a position directly;
    `evaluate` never reaches them, because it returns 0 for terminal states
    (the reward that got there already carried the win/loss value).
    `is_terminal` covers having no way left to damage a cog as well as
    running out of laff -- see `BattleState.can_still_damage`.
    """
    if state.is_win():
        return WIN_VALUE
    if state.is_terminal():
        return LOSS_VALUE

    total_max_hp = sum(c.max_hp for c in state.cogs)
    remaining_hp = sum(max(0, c.hp) for c in state.cogs if not c.status.is_dead)
    cog_progress = 1.0 - (remaining_hp / total_max_hp) if total_max_hp else 1.0
    laff_kept = state.toon.laff / state.toon.max_laff if state.toon.max_laff else 0.0
    return 100.0 * cog_progress - 100.0 * (1.0 - laff_kept)


def heuristic_value(state: BattleState) -> float:
    """Score a position at the depth cutoff.

    Dispatches to the fitted evaluator when weights are present and to
    `hand_written_value` otherwise, so the solver always has something to
    score with. Callers monkeypatch *this* name to benchmark a candidate.
    """
    from . import fitted, valuenet

    if valuenet.USE and valuenet.active():
        return valuenet.value(state)
    if fitted.is_fitted():
        return fitted.value(state)
    return hand_written_value(state)


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

# BEAM: below the root, search only the `BEAM` moves a one-round look-ahead
# (reward plus the leaf heuristic) ranks highest. Off (None) by default --
# it is a shortcut, so `tools/search_bench.py agree` measures how often it
# changes the answer before anything uses it. The root always gets every
# move. Only `best_action_iterative` marks the root (`_TOP`), so a direct
# `evaluate`/`solve` call is never trimmed.
BEAM: Optional[int] = None
_TOP: List = [None]

# ORDER: try moves best-first by the same one-round look-ahead, keeping
# every one. Exact -- *-minimax cuts most when the best move comes first,
# and order changes only how much it cuts, never the value. Measured:
# 1.24x on fully exact depth 3 (16/16 identical), 1.06x with collapse and
# BEAM=6 at depth 4 (12/12 identical). *-minimax itself is worth 9x there.
ORDER = True

# Fall back to the previous, shallower pass's best move for ordering and
# for star2's probe. Exact; measured in docs/experiment-log.md.
HINT_FROM_SHALLOWER = True


def _beam(state, actions, objective, width, keep):
    """The `width` best actions by one-round look-ahead, plus `keep`, with
    the outcomes computed for the ranking, to be reused."""
    scored, pre = [], {}
    for action in actions:
        try:
            branches = outcomes_mod.action_outcomes(state, action, objective)
        except NotImplementedError:
            continue
        pre[id(action)] = branches
        scored.append((sum(p * (r + heuristic_value(n)) for p, n, r in branches),
                       action))
    scored.sort(key=lambda va: -va[0])
    chosen = [a for _v, a in scored[:width]]
    if keep is not None and keep in actions:
        # A move a search has already found best goes first, ahead of
        # any one-round guess.
        chosen = [keep] + [a for a in chosen if a != keep]
    return chosen, pre


def evaluate(state: BattleState, depth: int, objective=None,
             discount: float = 1.0, memo: Optional[Dict] = None,
             alpha: float = float("-inf"), beta: float = float("inf"),
             prune: bool = True, epsilon: float = 0.0,
             probe_only: bool = False,
             deadline: Optional[List] = None,
             exact_plies: Optional[int] = None,
             ) -> Tuple[float, Optional[Action]]:
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

    if deadline is not None:
        # deadline is [when, countdown] -- a list so the countdown is
        # shared across the whole recursion without a global.
        deadline[1] -= 1
        if deadline[1] <= 0:
            deadline[1] = DEADLINE_CHECK_INTERVAL
            if time.monotonic() >= deadline[0]:
                raise SearchTimeout

    if state.is_terminal():
        # Zero, NOT +/-WIN_VALUE. The transition that reached this state
        # already paid the +/-100 in its reward, and `evaluate` returns the
        # value of what is still to come.
        return 0.0, None
    if depth <= 0:
        return heuristic_value(state), None

    # A probe searches one action and returns a LOWER bound, so it must
    # never be stored as, or answered from, an exact entry.
    # exact_plies belongs in the key: the same state searched with
    # collapsed chance nodes is a different computation, and answering one
    # from the other would silently mix the two.
    key = (outcomes_mod.state_key(state), depth, epsilon, exact_plies, BEAM)
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
    # Entries are keyed by depth, so without a hint at THIS depth the move
    # the previous, shallower pass found here is the next best guess --
    # the whole point of iterative deepening, and one that only the root
    # used to get. Order only, so exact; it also picks star2's probe move.
    hint = hit[1] if hit is not None else None
    if hint is None:
        cached = memo.get(key) if probe_only else None
        hint = cached[1] if cached is not None else None
    if hint is None and HINT_FROM_SHALLOWER and depth > 1:
        shallower = memo.get((key[0], depth - 1) + key[2:])
        hint = shallower[1] if shallower is not None else None
    actions = distinct_actions(state)
    if hint is not None and hint in actions:
        actions = [hint] + [a for a in actions if a != hint]
    if probe_only:
        actions = actions[:1]
    pre = {}
    if (BEAM and not probe_only and depth >= 2 and _TOP[0] is not None
            and depth < _TOP[0] and len(actions) > BEAM):
        actions, pre = _beam(state, actions, objective, BEAM, hint)
    elif ORDER and not probe_only and depth >= 2 and len(actions) > 1:
        actions, pre = _beam(state, actions, objective, len(actions), hint)

    unevaluable = []
    for action in actions:
        try:
            branches = pre.get(id(action))
            if branches is None:
                branches = outcomes_mod.action_outcomes(state, action, objective)
        except NotImplementedError as exc:
            # Gag or cog data still marked TODO -- skip this action rather
            # than let a data gap take down the whole search.
            unevaluable.append(str(exc))
            continue

        branches, _dropped = trim(branches, epsilon)
        if (exact_plies is not None and exact_plies <= 0
                and may_collapse(objective)):
            branches = outcomes_mod.collapse_damage(branches)
        value = _chance_value(state, branches, depth, objective,
                              discount, memo, alpha, beta, prune, epsilon,
                              probe=not probe_only, deadline=deadline,
                              exact_plies=exact_plies)
        if value > best_value:
            best_value, best_action = value, action
        if prune:
            alpha = max(alpha, best_value)
            if alpha >= beta:
                break                      # this node is already refuted

    if best_action is None:
        if unevaluable and len(unevaluable) == len(actions):
            # EVERY action was unevaluable, which is a different thing
            # from a position with nothing worth doing, and it used to be
            # indistinguishable from one.
            #
            # Skipping per action assumes the gap is in that action's own
            # gag. A gap in a COG's table is not: every action's outcome
            # runs the same cog phase, so one TODO cell silently disables
            # the entire search and it returns a heuristic and no move.
            # Found on a VP board, where The Big Cheese at level 12 has a
            # TODO accuracy -- the panel had been quietly falling back to
            # the policy for every boss fight with one on the field.
            #
            # Raising is right because the caller can say so. Filling the
            # cell in would be worse than useless: it is TODO precisely
            # because nobody has confirmed it.
            raise MissingData(sorted(set(unevaluable))[0])
        result = (heuristic_value(state), None)
        memo[key] = (result[0], None, EXACT)
        return result

    if probe_only:
        return best_value, best_action      # a lower bound; never cached

    flag = (UPPER if best_value <= original_alpha
            else LOWER if best_value >= beta else EXACT)
    memo[key] = (best_value, best_action, flag)
    return best_value, best_action


def max_round_damage(state: BattleState) -> int:
    """Most laff the cogs could take in one round, assuming every one of
    them attacks and every attack hits for its highest roll.

    An over-estimate on purpose: it is used to bound how bad a position
    can get, and a bound that is too generous only prunes less, while one
    that is too tight prunes a real answer.
    """
    total = 0
    for cog in state.cogs:
        if cog.status.is_dead:
            continue
        try:
            total += outcomes_mod.worst_case_damage(cog)
        except NotImplementedError:
            return 10 ** 6              # unknown: assume the worst
    return total


def may_collapse(objective) -> bool:
    """Whether this objective tolerates averaging the cog phase.

    Collapsing replaces a damage distribution with its mean, which makes
    the search risk-*neutral* about damage. That is fine for an objective
    that scores laff linearly, and wrong for one that does not.

    Measured at equal depth on nine positions x two objectives: under
    `balanced` the collapsed search picked the same move 9/9, under
    `survive` only 7/9. Both disagreements were `survive`, and one of
    them was a toon at full laff -- so the distinction is the objective's
    attitude to risk, not the position's danger.

    An earlier version gated on whether the round could kill the toon.
    It was the wrong test twice over: it missed the full-laff `survive`
    disagreement, and with four cogs the worst-case round is large enough
    that it fired almost everywhere and gave back the entire speedup.
    """
    return getattr(objective, "laff_weight", 1.0) <= 1.0


def _next_plies(exact_plies: Optional[int]) -> Optional[int]:
    """One ply further from the root. None means never collapse."""
    return None if exact_plies is None else exact_plies - 1


def heuristic_floor(state: BattleState, at_risk: float = 0.0) -> float:
    """Lowest value `heuristic_value` can return for `state`.

    Must track whichever evaluator is installed. `_value_bounds` needs it
    to stay admissible, and an admissible bound is a correctness
    requirement for star1 rather than a tuning knob: the cut assumes an
    unseen child cannot fall below the floor.

    `at_risk` is how much laff the horizon can still take, which lets the
    hand-written form give a much tighter answer than its global minimum.
    The fitted form gets no such help -- it can call a position lost on
    evidence that has nothing to do with laff, which is the whole reason
    it is better, and the price is a looser bound.
    """
    from . import fitted, valuenet

    if valuenet.USE and valuenet.active():
        return valuenet.value_floor(state)
    if fitted.is_fitted():
        return fitted.value_floor(state)
    max_laff = float(state.toon.max_laff) or 1.0
    laff = float(state.toon.laff)
    # Cog progress is at worst zero, so the hand-written form bottoms out
    # at the laff term alone, evaluated at the least laff the horizon can
    # leave behind.
    return -100.0 * (1.0 - max(0.0, laff - at_risk) / max_laff)


def _value_bounds(state: BattleState, depth: int,
                   objective: float) -> Tuple[float, float]:
    """Admissible [floor, ceiling] on the value of a state.

    The ceiling is winning outright. The floor used to be losing every
    remaining point of laff and then the battle, which is where nearly
    all the slack was: at a depth limit of `d` only `d` rounds actually
    happen, so the toon can lose at most `d` rounds' worth of damage, not
    its whole bar. And if that much damage cannot reach zero laff, the
    battle cannot be lost inside the horizon at all and the -100 does not
    belong in the bound either.

    This is what stood between the *-minimax code and a speedup. A
    branch's value ranged over ~300 points, so the unseen-mass interval
    stayed wide enough that the cut almost never fired; capping the loss
    at what the horizon permits narrows it sharply whenever the toon is
    not actually in danger, which at shallow depth is most of the time.
    """
    ceiling = WIN_VALUE
    laff = float(state.toon.laff)
    max_laff = float(state.toon.max_laff) or 1.0
    reachable = float(max_round_damage(state)) * depth
    at_risk = min(laff, reachable)

    # Every term that can push the value down has to appear here, and
    # each one is an objective knob rather than a constant. The previous
    # floor hard-coded a flat -100 that silently stood in for several of
    # them at once; once the loss term became conditional that cover went
    # away, the bound stopped being admissible, and pruning started
    # returning wrong values -- which the exactness tests caught.
    laff_weight = getattr(objective, "laff_weight", 1.0)
    loss_penalty = getattr(objective, "loss_penalty", 100.0)
    gag_cost = getattr(objective, "gag_cost", 0.1)
    scarcity = getattr(objective, "scarcity_cost", 0.0)
    turn_cost = getattr(objective, "turn_cost", 0.0)

    # Dearest a single gag can be: highest level, and the scarcity term
    # peaks at a gag you can only hold one of.
    worst_gag = gag_cost * 7.0 + scarcity

    # The battle can only be lost inside the horizon if the damage
    # available in it can actually reach zero laff.
    lethal = loss_penalty if reachable >= laff else 0.0

    # And the cutoff itself scores the leaf, so the bound has to cover
    # whatever the *installed* evaluator can return -- see
    # `heuristic_floor`. This read `-100 * (1 - laff_kept)`, which is the
    # hand-written form's own floor written out as if it were a property
    # of the search. It is not, and once the fitted evaluator learned to
    # say "full laff, but this pouch cannot finish the fight" it returned
    # -98 at a node this bound put at [0, 100]; star1 then cut branches
    # it had no warrant to cut and pruned and exhaustive search returned
    # different values. tests/test_search.py pins them equal.
    leaf = heuristic_floor(state, at_risk)

    floor = -(laff_weight * at_risk + lethal
              + (worst_gag + turn_cost) * depth) + min(0.0, leaf)
    return floor, ceiling


def _chance_value(state, branches, depth, objective, discount, memo,
                   alpha, beta, prune, epsilon=0.0, probe=True,
                   deadline=None, exact_plies=None) -> float:
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
                                    memo, prune=False, epsilon=epsilon,
                                    deadline=deadline,
                                    exact_plies=_next_plies(exact_plies))[0])
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
                                 prune=True, epsilon=epsilon, probe_only=True,
                                 deadline=deadline,
                                 exact_plies=_next_plies(exact_plies))
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
                            child_alpha, child_beta, True, epsilon,
                            deadline=deadline,
                            exact_plies=_next_plies(exact_plies))
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

    Safe because every action spends a gag OR a unit of
    `state.free_passes`, so no line can run longer than the two together
    and the search cannot loop. `max_depth` is a safety valve, not part
    of the model: leave it None to solve properly.

    THE PASS BUDGET HAS TO BE IN HERE, and leaving it out is what made
    the wider pass look unsound. This counted gags only, on the stated
    assumption that "every action spends a gag" -- true of every action
    except a pass. A toon holding one gag therefore got `max_depth = 2`,
    the search truncated, and the leaves fell through to
    `heuristic_value`. That is where the phantom came from: in one
    position it returned the correct value +88.64 while naming `pass`
    as the best move, when passing is really worth +86.39 and throwing
    the last gag at a 2 hp cog wins outright.

    So the pass was never creating value; a depth limit computed from
    the wrong measure was. The termination measure has been
    (gags, lure rounds, free passes) since `free_passes` was added --
    this simply makes the depth budget agree with it.
    """
    if max_depth is None:
        max_depth = (sum(n for n in state.toon.gag_counts.values() if n > 0)
                     + max(0, state.free_passes) + 1)
    return evaluate(state, max_depth, objective, memo=memo)


def best_action(state: BattleState, depth: int = 3,
                objective=None) -> Optional[Action]:
    """The action to take right now. None if nothing is playable."""
    return evaluate(state, depth, objective)[1]


# A kept memo is cleared past this many entries: memory, not correctness.
MEMO_CAP = 3_000_000


def best_action_iterative(state: BattleState, depth: int = 4,
                           objective=None, epsilon: float = 0.0,
                           time_budget: Optional[float] = None,
                           exact_plies: Optional[int] = None,
                           memo: Optional[Dict] = None,
                           prune: bool = True,
                           ) -> Tuple[float, Optional[Action]]:
    """Search 1..depth, reusing the table between passes.

    Costs a little extra work at the shallow depths and usually more than
    repays it: each pass leaves its best move in the table, so the next pass
    tries that first and prunes almost immediately.

    `time_budget`, in seconds, turns this into an anytime search: it
    stops deepening once the next pass looks unaffordable and returns
    the deepest one that finished. Depth is the wrong thing to fix in
    advance because cost depends on the position, not the number --
    measured at depth 2, two cogs take 2.3s and three take 28s, and four
    are worse again. Fixing the depth means either waiting half a minute
    on a crowded battle or wasting the search on an easy one. Fixing the
    time instead spends what is available.

    Each pass is complete before its result is used, so a budget never
    yields a half-searched answer -- only a shallower one.

    `memo`, kept by the caller across a fight's rounds, carries the work
    forward: next round's board was searched one level shallower inside
    this round's tree, and entries are keyed by depth, so reusing them is
    exact. It is wiped if the objective changes (the key does not hold it)
    and past `MEMO_CAP` entries.
    """
    if memo is None:
        memo = {}
    tag = ("__objective__", repr(objective))
    if tag not in memo or len(memo) > MEMO_CAP:
        memo.clear()
        memo[tag] = True
    value, action = 0.0, None
    deadline = None
    if time_budget is not None:
        deadline = [time.monotonic() + time_budget, DEADLINE_CHECK_INTERVAL]

    for d in range(1, depth + 1):
        _TOP[0] = d
        try:
            value, action = evaluate(state, d, objective, memo=memo,
                                     prune=prune, epsilon=epsilon,
                                     deadline=deadline, exact_plies=exact_plies)
        except SearchTimeout:
            # Keep the last completed pass. Predicting the next ply's cost
            # from the previous one does not work here -- depth 1 to 2 on
            # a three-cog position is a jump from 0.01s to 28s -- so the
            # budget has to be enforced inside the search, not guessed at
            # between passes.
            break
        finally:
            _TOP[0] = None
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
