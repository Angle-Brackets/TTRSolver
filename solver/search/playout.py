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


# ANYTIME. A panel asks for playouts in growing chunks and shows the best
# so far after each, so a decent move is up in a second or two and gets
# replaced as better evidence arrives. Cumulative rollouts per candidate
# after each chunk; the measured setting (8) is reached by chunk three.
#
# Chunks are at most four rollouts so a deadline is overshot by one short
# chunk at worst -- a 16-rollout chunk on a VP opening took five seconds.
SCHEDULE = (2, 4, 8, 12, 16, 20, 24, 28, 32)


def _seed(k: int) -> int:
    """Rollout k's seed -- what `pick` uses at seed 0, so a chunked run
    and a single `pick` see the same cogs and dice."""
    return k * 7919


def chunk_in_child(state: BattleState, horizon, reject, allow_level_7: bool,
                   k_from: int, k_to: int, only=None, wide: bool = True):
    """Rollouts k_from..k_to-1 for each candidate: (pairs, note).

    `pairs` is [(plan, [cogs defeated, one per rollout])], the scorer's
    pick first. Per rollout rather than summed, so the caller can pair
    candidates on the same rollout and tell a lead from noise. Stateless: the candidates are recomputed each
    call, and `candidates` is deterministic, so every chunk of one board
    grades the same plans -- the caller checks that by key anyway.

    `wide` builds the menu with `wide_candidates` (the measured winner,
    see below); `only` restricts the rollouts to the candidates whose
    keys it lists, which is how the caller runs successive halving
    across chunks. Pairs come back for every candidate, with an empty
    list for those not rolled this time, so the menu can still be
    checked by key.
    """
    from .. import state as state_mod
    from . import hybrid

    state_mod.ALLOW_LEVEL_7 = bool(allow_level_7)
    if len(state.active_toons()) != 1:
        return None, "solo only"
    if not hybrid.available() or state.is_terminal():
        return None, "unavailable"
    cands = (wide_candidates(state, reject) if wide
             else candidates(state, TOP_K, reject))
    if not cands:
        return None, "unavailable"
    if len(cands) == 1:
        return [(cands[0], [])], ""
    wanted = None if only is None else set(only)
    values = [[] for _ in cands]
    for k in range(k_from, k_to):
        for i, plan in enumerate(cands):
            if wanted is None or _key(plan) in wanted:
                values[i].append(rollout(state, plan, horizon, _seed(k)))
    return list(zip(cands, values)), ""


def leads(challenger: Sequence[float], incumbent: Sequence[float]) -> bool:
    """Does `challenger` beat `incumbent` by more than one standard error,
    paired rollout by rollout? Used only to stop the move on screen
    swapping on noise while playouts are still arriving."""
    diffs = [a - b for a, b in zip(challenger, incumbent)]
    n = len(diffs)
    if n < 2:
        return False
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    return mean > 0 and mean > (var / n) ** 0.5


# ---------------------------------------------------------------------
# A wider menu, so the one-round scorer does not decide what is tried
# ---------------------------------------------------------------------
#
# WHY. On the wide Monte-Carlo benchmark (797 solo-VP positions, nine
# candidates each, best chosen on half the rollouts and scored on the
# other half), gains over the average candidate were:
#
#     climb's pick (scorer #1)                    +0.37 cogs
#     best of the scorer's top 4                  +0.70
#     best of 4 RANDOM entries from climb's menu  +0.92
#     best of all nine                            +1.36
#
# Four random menu entries beat the scorer's own top four, and the best
# move lay outside that top four in 49% of positions. `TOP_K` playouts
# inherit that filter. This builds the menu for diversity instead and
# lets the rollouts, not the scorer, do the narrowing.
#
# MEASURED, solo VP, 200 fresh paired sides, against `pick` (top 3 x 8):
#
#     top 3 x 8 rollouts          38/200  19.0%
#     wide menu, halving 2/4/8    79/200  39.5%
#     paired +57/-16, p < 0.001; +1.00 cogs a fight (se 0.63)

WIDE_SCORER_TOP = 2      # the scorer's favourites
WIDE_POLICY_TOP = 2      # the network's favourites
WIDE_CAP = 10
# Successive halving: everyone gets HALVING[0] rollouts, the better half
# goes on to HALVING[1], and so on -- with the same seeds throughout.
HALVING = (2, 4, 8)
HALVING_KEEP_AT_LEAST = 2


def _kind(action) -> tuple:
    """What counts as a different KIND of move, for diversity."""
    if action is None or action.is_pass:
        return ("pass",)
    if getattr(action, "sos", None):
        from .. import sos as sos_mod
        card = sos_mod.BY_NAME.get(action.sos)
        return ("sos", getattr(card, "kind", action.sos))
    if action.fire:
        return ("fire",)
    return (action.track, action.target_index is None)


def wide_candidates(state: BattleState, reject=None,
                    cap: int = WIDE_CAP) -> list:
    """climb's pick, the scorer's and the network's favourites, the best
    of every kind of move climb considered, and the pass."""
    from . import hybrid
    from ..rl import env as env_mod

    scored = {}
    real = hybrid._judge

    def spy(st, plan, deep):
        value = real(st, plan, deep)
        scored.setdefault(_key(plan), (list(plan), value))
        return value

    probe = state.clone()
    hybrid._judge = spy
    try:
        chosen = hybrid.climb(probe, random.Random(0), budget=CLIMB_BUDGET,
                              reject=frozenset(reject or ()))
    finally:
        hybrid._judge = real
    if chosen is None:
        return []
    ranked = [p for p, _v in sorted(scored.values(), key=lambda pv: -pv[1])]

    out, seen = [], set()

    def add(plan):
        if plan is not None and _key(plan) not in seen and len(out) < cap:
            seen.add(_key(plan))
            out.append(list(plan))

    add(chosen)
    for plan in ranked[:WIDE_SCORER_TOP]:
        add(plan)
    try:
        model = hybrid._load()
        logits = hybrid._logits(model, state, 0, [None] * len(state.toons),
                                frozenset(reject or ()))
        order = sorted(range(len(logits)), key=lambda i: -logits[i])
        taken = 0
        for i in order:
            if taken >= WIDE_POLICY_TOP or logits[i] == float("-inf"):
                break
            entry = env_mod.ACTIONS[i]
            before = len(out)
            add([entry if entry is not None else Action(track=None)])
            taken += len(out) > before
    except Exception:                      # noqa: BLE001 -- the menu still stands
        pass
    best_of_kind = {}
    for plan in ranked:
        best_of_kind.setdefault(_kind(plan[0] if plan else None), plan)
    for plan in best_of_kind.values():
        add(plan)
    add([Action(track=None)])
    return out


def pick_wide(state: BattleState, horizon=None, seed: int = 0,
              reject=None, stages=HALVING) -> Optional[Result]:
    """Successive halving over `wide_candidates`, common random numbers."""
    from . import hybrid

    if not hybrid.available() or state.is_terminal():
        return None
    if len(state.active_toons()) != 1:
        return None
    cands = wide_candidates(state, reject)
    if not cands:
        return None
    if len(cands) == 1:
        return Result(cands[0], cands, [0.0], 0)
    values = {i: [] for i in range(len(cands))}
    alive, done_k = list(range(len(cands))), 0
    for stage, upto in enumerate(stages):
        for k in range(done_k, upto):
            for i in alive:
                values[i].append(rollout(state, cands[i], horizon,
                                         seed * 1000003 + k * 7919))
        done_k = upto
        if stage + 1 < len(stages):
            alive.sort(key=lambda i: (-sum(values[i]) / len(values[i]), i))
            alive = alive[:max(HALVING_KEEP_AT_LEAST, (len(alive) + 1) // 2)]
    best = max(alive, key=lambda i: (sum(values[i]) / len(values[i]), i == 0))
    means = [sum(values[i]) / len(values[i]) for i in range(len(cands))]
    return Result(cands[best], cands, means, done_k)


def menu_in_child(state: BattleState, reject, allow_level_7: bool,
                  wide: bool = True):
    """The candidate keys a chunk would roll, in order: (keys, note).

    Cheap -- one climb -- and lets a caller split the first, slowest
    chunk across processes instead of waiting on one.
    """
    from .. import state as state_mod
    from . import hybrid

    state_mod.ALLOW_LEVEL_7 = bool(allow_level_7)
    if len(state.active_toons()) != 1:
        return None, "solo only"
    if not hybrid.available() or state.is_terminal():
        return None, "unavailable"
    cands = (wide_candidates(state, reject) if wide
             else candidates(state, TOP_K, reject))
    if not cands:
        return None, "unavailable"
    return [_key(plan) for plan in cands], ""
