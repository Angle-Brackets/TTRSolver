"""
Multi-core helpers for the parts of this that are actually parallel.

TWO KINDS OF WORK, ONLY ONE OF THEM WORTH SPLITTING BY DEFAULT
--------------------------------------------------------------
Playing N independent fights is embarrassingly parallel: no shared state,
no communication, one small tuple back per fight. That is what the
benchmark and the sensitivity sweep spend all their time on, and it scales
about as well as the core count allows.

Splitting a *single* search across cores is a much worse deal. The root's
legal actions are independent subtrees, so they divide cleanly, but:

  - the memo table can't be shared between processes, and transpositions
    across sibling actions are common, so the workers redo each other's
    work -- real speedup lands well under the core count;
  - Windows spawns rather than forks, so each worker re-imports the whole
    package. That is ~1s of startup against a ~1s search.

So `rank_actions` below takes a pool you already have. It pays off inside a
loop that reuses one pool, and loses to the single-process version for a
one-off call. `best_action_parallel` measures nothing and promises nothing:
if you have one decision to make, call the ordinary solver.

NONE OF THIS HELPS THE VISUALIZER. Pyodide runs single-threaded in the
browser tab; `multiprocessing` isn't available there at all. The page's
per-node latency is what it is, and would need web workers instead.
"""
import multiprocessing as mp
from typing import Dict, List, Optional, Sequence, Tuple

from .. import simulator
from ..state import Action, BattleState
from . import expectimax

MAX_ROUNDS = 30


def default_workers() -> int:
    """One per core, but never more than is useful."""
    return max(1, (mp.cpu_count() or 2))


# ---------------------------------------------------------------------
# Whole fights -- the case worth parallelising
# ---------------------------------------------------------------------

def _play_one(args) -> Tuple[bool, int, int]:
    """(won, laff remaining, rounds). Top-level and picklable because
    Windows spawns workers rather than forking them."""
    import random

    from .demo import SCENARIOS

    policy, depth, seed, scenario = args
    random.seed(seed)
    state = SCENARIOS[scenario]()

    for _ in range(MAX_ROUNDS):
        if state.is_terminal():
            break
        actions = simulator.legal_actions(state)
        if not actions:
            break

        done = None
        if policy == "random":
            candidates = list(actions)
            while candidates:
                action = random.choice(candidates)
                try:
                    state, _r, done = simulator.step(state, action)
                    break
                except NotImplementedError:
                    candidates.remove(action)
            if done is None:
                break
        else:
            action = expectimax.best_action(state, depth=depth)
            if action is None:
                break
            state, _r, done = simulator.step(state, action)
        if done:
            break

    return state.is_win(), state.toon.laff, state.round_num


def play_many(policy: str, trials: int, depth: int, scenario: str,
               workers: Optional[int] = None, pool=None) -> List[Tuple[bool, int, int]]:
    """Play `trials` independent fights, in parallel where it's worth it.

    Seeds are the fight index, so results are identical whatever the worker
    count -- parallelising must not change the answer, only how long it
    takes to get it.
    """
    jobs = [(policy, depth, seed, scenario) for seed in range(trials)]
    workers = workers if workers is not None else default_workers()

    if workers <= 1 or trials <= 2:
        return [_play_one(job) for job in jobs]
    if pool is not None:
        return pool.map(_play_one, jobs, chunksize=1)
    with mp.Pool(processes=min(workers, trials)) as p:
        return p.map(_play_one, jobs, chunksize=1)


# ---------------------------------------------------------------------
# One search, split at the root -- only inside a reused pool
# ---------------------------------------------------------------------

def _score_action(args) -> Tuple[float, int]:
    from .demo import SCENARIOS      # noqa: F401  (keeps workers importable)
    state, action, depth, gag_cost_lambda, index = args
    from .. import outcomes as outcomes_mod

    try:
        branches = outcomes_mod.action_outcomes(state, action, gag_cost_lambda)
    except NotImplementedError:
        return float("-inf"), index

    memo: Dict = {}
    value = sum(
        prob * (reward + expectimax.evaluate(nxt, depth - 1, gag_cost_lambda,
                                             1.0, memo)[0])
        for prob, nxt, reward in branches
    )
    return value, index


def rank_actions(state: BattleState, depth: int = 3,
                  gag_cost_lambda: float = 0.1,
                  pool=None) -> List[Tuple[float, Action]]:
    """Same result as expectimax.rank_actions, split across a pool.

    Falls back to the single-process version when no pool is given, because
    standing one up costs more than the search saves. Every worker starts
    with an empty memo, so this trades duplicated work for parallelism --
    worth it at depth 3+, a loss at depth 1.
    """
    actions = simulator.legal_actions(state)
    if pool is None or len(actions) < 2:
        return expectimax.rank_actions(state, depth, gag_cost_lambda)

    jobs = [(state, a, depth, gag_cost_lambda, i)
            for i, a in enumerate(actions)]
    scored = pool.map(_score_action, jobs, chunksize=1)

    out = [(value, actions[index]) for value, index in scored
           if value != float("-inf")]
    out.sort(key=lambda pair: pair[0], reverse=True)
    return out
