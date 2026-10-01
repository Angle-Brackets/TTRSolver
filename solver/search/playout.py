"""Judge a move by playing the rest of the fight out.

WHY. `_quick_score` looks one round ahead with hand-set weights, and on
a Monte-Carlo benchmark it was barely better than picking at random
among `climb`'s own top four (regret 0.65 cogs against 0.73). Playing
each candidate to the end of the fight is the judge it approximates.

MEASURED, solo VP, 500 paired sides, live-equivalent view:

    shipped climb                 36/500   7.2%   31.3 cogs defeated
    top 3 played out 8 times     106/500  21.2%   33.2 cogs defeated
    paired +90/-20, p < 0.0001; +1.87 cogs a fight (se 0.35)

Confirmed through THIS module on 200 fresh seeds, the horizon coming
from `BossTracker` exactly as a panel would supply it: 10/200 -> 54/200,
+50/-6, p < 0.0001, +3.02 cogs a fight (se 0.56).

Fitting a formula to the same labels failed twice in play (3.6% and
0.4%): a one-decision label holds only while the old player plays on,
and a fitted judge used every round is a different player. So the
playouts themselves are the judge.

NO PEEKING. A playout starts from the board the player sees. Cogs they
cannot see -- the rest of this round, later rounds -- are drawn from the
level band, in the numbers `boss.Horizon` says are coming, with a fresh
draw per playout. Without a horizon (a street, a building, a fight whose
size is unconfirmed) the playout ends with the battle on screen, since
the next floor is unknown to the player too. The owner signed off on
boss-fight structure and nothing more; see `solver/live/boss.py`.

SOLO ONLY for now: a party playout needs the teammate model to play the
other seats, and has not been measured. `pick` returns None for a party
and the caller keeps its own answer.

Needs numpy, like `hybrid`, because the continuation is `hybrid.climb`.
"""
from __future__ import annotations

import copy
import random
import time
from typing import List, NamedTuple, Optional, Sequence

from ..state import Action, BattleState

# The measured setting. More candidates or rollouts have not been tried.
TOP_K = 3
ROLLOUTS = 8
# The continuation's own budget, as the panels run `climb`.
CLIMB_BUDGET = 24
# Fewest rollouts per candidate before a deadline may cut the playouts
# short. Below this the means are too noisy to overrule the scorer.
MIN_ROLLOUTS = 2
ROUND_CAP = 400


class Result(NamedTuple):
    plan: Sequence[Optional[Action]]
    # Mean cogs defeated by the end of the playout, per candidate, in
    # the order tried -- the scorer's own pick first.
    candidates: List[Sequence[Optional[Action]]]
    means: List[float]
    rollouts: int


def _key(plan) -> tuple:
    return tuple(repr(a) for a in plan)


def _view(state: BattleState) -> BattleState:
    """What the continuation sees -- the live panel's view, which has no
    holdout. Measured that way, so played that way."""
    view = state.clone()
    view.holdout = []
    return view


def build_env(state: BattleState, horizon, rng):
    """A simulator fight starting from `state`, with the unseen cogs drawn.

    `horizon` is a `boss.Horizon` or None. Draws are from `rng`, so each
    playout sees a different -- but equally plausible -- set of cogs.
    """
    from .. import facility
    from ..rl import env as env_mod

    start = state.clone()
    kind = start.kind
    # Reset as a plain battle, which builds no plan of its own; the plan
    # is ours, built from what the player knows.
    start.kind = "street"
    start.holdout, start.cogs_remaining = [], 0
    env = env_mod.BattleEnv(rng=rng, sampler=lambda _r: start,
                            coordinated=True, max_rounds=ROUND_CAP)
    env.reset()
    env.state.kind = kind
    if horizon is None:
        return env
    make = env._sellbot_cog if horizon.department == "sellbot" else env._boss_cog
    lo, hi = horizon.band
    env.state.holdout = [make(rng, rng.randint(lo, hi))
                         for _ in range(horizon.holdout)]
    floors = [[make(rng, rng.randint(blo, bhi)) for _ in range(count)]
              for count, (blo, bhi) in horizon.later]
    if floors:
        env.plan = facility.FacilityPlan(floors)
        env.state.cogs_remaining = env.plan.remaining()
    return env


def _left(state: BattleState) -> int:
    return (sum(1 for c in state.cogs if c.hp > 0) + len(state.holdout)
            + state.cogs_remaining)


def step_round(env, plan):
    """Play one round of `plan` through the environment."""
    from ..rl import env as env_mod

    start = env.rounds
    done, info = False, {}
    while not done and env.rounds == start:
        action = plan[env.actor] if plan and env.actor < len(plan) else None
        index, through = env_mod.PASS_INDEX, None
        if action is not None and getattr(action, "sos", None):
            through = action
        elif action is not None and action.fire:
            index = env_mod._FIRE_INDEX.get(action.target_index,
                                            env_mod.PASS_INDEX)
        elif action is not None and not action.is_pass:
            for i, cand in enumerate(env_mod.ACTIONS):
                if (cand is not None and not cand.fire
                        and cand.track == action.track
                        and cand.level == action.level
                        and cand.target_index == action.target_index):
                    index = i
                    break
        _obs, _mask, _r, done, info = (env.step(index, action=through)
                                       if through else env.step(index))
    return done, info


def rollout(state, plan, horizon, seed: int) -> int:
    """Cogs defeated by the end of one playout that opens with `plan`."""
    from . import hybrid

    rng = random.Random(seed)
    env = build_env(state, horizon, rng)
    total = _left(env.state)
    policy_rng = random.Random(seed + 1)
    done, _info = step_round(env, plan)
    guard = 0
    while not done and guard < ROUND_CAP:
        guard += 1
        nxt = hybrid.climb(_view(env.state), policy_rng, budget=CLIMB_BUDGET)
        if nxt is None:
            break
        done, _info = step_round(env, nxt)
    return total - _left(env.state)


def candidates(state: BattleState, top_k: int = TOP_K, reject=None):
    """`climb`'s pick first, then the best-scored others it considered."""
    from . import hybrid

    scored = {}
    real = hybrid._judge

    def spy(st, plan, deep):
        value = real(st, plan, deep)
        scored.setdefault(_key(plan), (list(plan), value))
        return value

    probe = state.clone()             # climb may apply a unite in place
    hybrid._judge = spy
    try:
        chosen = hybrid.climb(probe, random.Random(0), budget=CLIMB_BUDGET,
                              reject=frozenset(reject or ()))
    finally:
        hybrid._judge = real
    if chosen is None:
        return []
    out, seen = [list(chosen)], {_key(chosen)}
    for plan, _value in sorted(scored.values(), key=lambda pv: -pv[1]):
        if len(out) >= top_k:
            break
        if _key(plan) not in seen:
            seen.add(_key(plan))
            out.append(plan)
    return out


def pick(state: BattleState, horizon=None, seed: int = 0,
         top_k: int = TOP_K, rollouts: int = ROLLOUTS,
         deadline: Optional[float] = None, reject=None) -> Optional[Result]:
    """The candidate that played out best, or None when this cannot run.

    `deadline` is a `time.monotonic()` value. Rollouts are dealt round-
    robin, so every candidate always has the same number; past the
    deadline no new round starts once each has `MIN_ROLLOUTS`.
    Common random numbers: rollout k draws the same cogs and dice seed
    for every candidate, so they differ only by the opening move.
    """
    from . import hybrid

    if not hybrid.available() or state.is_terminal():
        return None
    if len(state.active_toons()) != 1:
        return None                   # party playouts are not built yet
    cands = candidates(state, top_k, reject)
    if not cands:
        return None
    if len(cands) == 1:
        return Result(cands[0], cands, [0.0], 0)
    totals = [0.0] * len(cands)
    done_k = 0
    for k in range(rollouts):
        if (deadline is not None and k >= MIN_ROLLOUTS
                and time.monotonic() >= deadline):
            break
        for i, plan in enumerate(cands):
            totals[i] += rollout(state, plan, horizon,
                                 seed * 1000003 + k * 7919)
        done_k = k + 1
    means = [t / done_k for t in totals]
    # Ties keep the scorer's pick, which is first.
    best = max(range(len(cands)), key=lambda i: (means[i], i == 0))
    return Result(cands[best], cands, means, done_k)


def pick_in_child(state: BattleState, horizon, budget: float,
                  reject=None, allow_level_7: bool = True):
    """`pick` for a panel's child process: (action, note).

    `note` says why there is no action -- "solo only", "unavailable" --
    so the panel can label the row instead of leaving it thinking. The
    level-7 switch is a module global, so it is set here, in the process
    that reads it; the panel's setting would otherwise never arrive.
    """
    from .. import state as state_mod

    state_mod.ALLOW_LEVEL_7 = bool(allow_level_7)
    if len(state.active_toons()) != 1:
        return None, "solo only"
    deadline = time.monotonic() + max(0.5, float(budget))
    result = pick(state, horizon, seed=0, deadline=deadline, reject=reject)
    if result is None:
        return None, "unavailable"
    first = result.plan[0] if result.plan else None
    return first, ""
