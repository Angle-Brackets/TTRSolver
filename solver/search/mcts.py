"""Open-loop Monte Carlo tree search over your own decisions.

`playout.pick_wide` searches one decision: each first move is played to
the end of the fight by the fast network, which wins 22% of solo VPs on
its own, so a move that needs the right follow-up is judged by a player
that may not find it. This searches several decisions deep and lets the
network play only past the frontier.

OPEN-LOOP because the game is mostly dice. The tree holds sequences of
YOUR plans, not board states; every iteration draws its own future (dice,
and the unseen cogs from `boss.Horizon`, exactly as a playout does) and
replays the sequence through it. A plan that cannot be played in that
future -- its target slot empty, its gag spent -- is replaced by the
network's move for that iteration only.

Each iteration:
  1. draw a future (`playout.build_env`);
  2. descend, choosing at each of your decisions by PUCT -- mean value
     plus a bonus for the prior and for being tried little;
  3. expand one new decision node (the network's top `MENU_K` plans);
  4. play the rest of the fight with the network (`playout.value` at the
     end, so the preset and the pouch count exactly as in a playout);
  5. add the result to every edge on the path.

The root's menu is `playout.wide_candidates`, with uniform priors -- it is
already a curated list, and the network's prior is what that list exists
to correct. Deeper menus come from the network with its probabilities.
The answer is the most-visited root plan.

Solo only for now: a party falls back to `playout.pick_wide`.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

from ..state import BattleState
from . import playout

# Matched to `pick_wide`'s cost: ten candidates halved at 8 and 16, kept
# to 32, is 10*8 + 5*8 + 3*16 = 168 playouts.
ITERATIONS = 168
MENU_K = 4          # plans per decision below the root
C_PUCT = 1.5        # exploration weight, on values normalised to [0, 1]

LAST_ROOT = None    # the last search's tree, for diagnostics


class _Node:
    __slots__ = ("plans", "priors", "n", "w", "children", "visits")

    def __init__(self, plans, priors):
        self.plans = plans
        self.priors = priors
        self.n = [0] * len(plans)
        self.w = [0.0] * len(plans)
        self.children: dict = {}
        self.visits = 0

    def choose(self, lo: float, hi: float) -> int:
        span = (hi - lo) or 1.0
        mean = (sum(self.w) / self.visits) if self.visits else 0.0
        root = math.sqrt(self.visits + 1)
        best, best_score = 0, -math.inf
        for i, prior in enumerate(self.priors):
            # Unvisited edges start at the node's mean (first-play urgency),
            # so the prior decides the order they are tried in.
            q = self.w[i] / self.n[i] if self.n[i] else mean
            score = (q - lo) / span + C_PUCT * prior * root / (1 + self.n[i])
            if score > best_score:
                best, best_score = i, score
        return best


def _legal(view: BattleState, plan) -> bool:
    from ..rl import env as env_mod
    from . import fastplayer

    if not playout.playable(view, plan):
        return False
    index = fastplayer.index_of(plan[0] if plan else None)
    return index >= 0 and (index >= len(env_mod.ACTIONS)
                           or env_mod.legal_mask(view, 0)[index])


def _menu(view: BattleState) -> _Node:
    from . import fastplayer

    ranked = fastplayer.ranked(view, MENU_K)
    if not ranked:
        return _Node([None], [1.0])
    return _Node([plan for plan, _p in ranked], [p for _plan, p in ranked])


def pick(state: BattleState, horizon=None, seed: int = 0, reject=None,
         iterations: int = ITERATIONS) -> Optional[playout.Result]:
    """The most-visited first plan after `iterations` tree playouts."""
    from . import fastplayer, hybrid

    if (not hybrid.available() or state.is_terminal() or not state.toons
            or state.toons[0].laff <= 0):
        return None
    if len(state.active_toons()) > 1 or not fastplayer.available():
        return playout.pick_wide(state, horizon, seed=seed, reject=reject)
    cands = playout.wide_candidates(state, reject)
    if not cands:
        return None
    if len(cands) == 1:
        return playout.Result(cands[0], cands, [0.0], 0)

    root = _Node(cands, [1.0 / len(cands)] * len(cands))
    pouch_start, pouch_weight = playout._carry(state, horizon)
    lo, hi = math.inf, -math.inf
    for it in range(iterations):
        rng = random.Random(seed * 1000003 + it * 7919)
        env = playout.build_env(state, horizon, rng)
        total = playout._left(env.state)
        node, path, rounds, done = root, [], 0, False
        while True:
            i = node.choose(lo, hi) if lo <= hi else 0
            plan = node.plans[i]
            if plan is None or (node is not root
                                and not _legal(playout._view(env.state), plan)):
                plan = fastplayer.act(playout._view(env.state),
                                      holdout=len(env.state.holdout))
            path.append((node, i))
            done, _info = playout.step_round(env, plan)
            rounds += 1
            if done:
                break
            child = node.children.get(i)
            if child is None:
                node.children[i] = _menu(playout._view(env.state))
                break                        # expanded: the network plays on
            node = child
        guard = 0
        while not done and guard < playout.ROUND_CAP:
            guard += 1
            done, _info = playout.step_round(env, fastplayer.act(
                playout._view(env.state), holdout=len(env.state.holdout)))
            rounds += 1
        v = playout.value(env.state, total, pouch_start, pouch_weight, rounds=rounds)
        lo, hi = min(lo, v), max(hi, v)
        for n, i in path:
            n.n[i] += 1
            n.w[i] += v
            n.visits += 1

    global LAST_ROOT
    LAST_ROOT = root
    best = max(range(len(cands)), key=lambda i: (root.n[i], root.w[i] / max(1, root.n[i])))
    means = [root.w[i] / root.n[i] if root.n[i] else 0.0 for i in range(len(cands))]
    return playout.Result(cands[best], cands, means, iterations)


def depth_reached(root: _Node) -> int:
    """How many decisions deep the tree grew -- for diagnostics."""
    deepest, stack = 0, [(root, 1)]
    while stack:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        stack.extend((child, depth + 1) for child in node.children.values())
    return deepest
