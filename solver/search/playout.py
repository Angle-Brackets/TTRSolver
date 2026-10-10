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
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

from ..state import Action, BattleState

# The measured setting. More candidates or rollouts have not been tried.
TOP_K = 3
ROLLOUTS = 8
# `climb`'s budget when it builds the menu, as the panels run it.
CLIMB_BUDGET = 24
# Its budget when it plays out the rest of the fight inside a rollout,
# if climb is the player. 8 tied 24 on 200 paired solo VPs (72 vs 78
# wins, +37/-43, p = 0.58; cogs +0.85, se 0.76) at half the cost.
ROLLOUT_BUDGET = 8
# WHO plays out the rest of the fight: "net" -- `fastplayer`, a network
# trained to copy climb -- or "climb". The net is used only if its
# weights load; otherwise climb plays. Measured on 200 paired solo VPs,
# wide menu, against climb at 2/4/8 rollouts (71 wins, 3.37 s a move):
#
#     net, same 2/4/8 rollouts      63 wins   0.78 s a move   p = 0.42
#     net, 8/16/32 (about equal time) 111 wins  3.06 s a move
#     equal time: +60/-20, p < 0.001, +2.83 cogs a fight (se 0.63)
#
# Slightly worse per rollout, four times as many in the same time.
ROLLOUT_PLAYER = "net"
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


class Plan(list):
    """A round's actions, plus the unite used before them, if any.

    A unite is not an action -- it is applied in the planning phase,
    before the gag is chosen -- so `climb` returns it beside the plan
    (`hybrid.LAST_UNITE`) and applies it to the board it was handed.
    Every playout hands it a COPY, so until this existed the unite was
    discarded and the gag played without it: no simulated fight through
    `step_round` ever spent one, and the live Playout row could not
    advise one. Carrying it on the plan is what lets the round use it.
    """
    unite = None


def with_unite(plan, unite):
    """`plan` as a `Plan` carrying `unite` (None for none)."""
    if plan is None:
        return None
    out = Plan(plan)
    out.unite = unite
    return out


def unite_of(plan):
    return getattr(plan, "unite", None)


def climb_with_unite(state, rng, **kwargs):
    """`hybrid.climb` on `state`, its unite carried on the returned plan."""
    from . import hybrid

    hybrid.LAST_UNITE = None
    plan = hybrid.climb(state, rng, **kwargs)
    return with_unite(plan, hybrid.LAST_UNITE)


def playable(state: BattleState, plan) -> bool:
    """Can `plan` be played on `state` -- its unite first, if it has one?

    climb scores plans on boards a unite has already changed, so its
    menu holds plans that throw gags only a Gag-Up restocks. Played
    without that unite they ask for gags the toon does not hold.
    """
    from collections import Counter
    from .. import unites as unites_mod

    board = state
    unite = unite_of(plan)
    if unite is not None:
        if not state.toons:
            return False
        board = state.clone()
        toon = board.toons[0]
        if not (unites_mod.available(toon) and unites_mod.in_stock(toon, unite)):
            return False
        unites_mod.apply(toon, unite)
    need = Counter()
    for seat, action in enumerate(plan):
        if action is None or seat >= len(board.toons):
            continue
        toon = board.toons[seat]
        if action.sos is not None:
            need[(seat, "sos", action.sos)] += 1
            if need[(seat, "sos", action.sos)] > toon.sos_cards.get(action.sos, 0):
                return False
        elif action.fire:
            need[(seat, "fire")] += 1
            if need[(seat, "fire")] > toon.fires:
                return False
        elif action.track is not None:
            gag = (action.track, action.level)
            need[(seat,) + gag] += 1
            if need[(seat,) + gag] > toon.gag_counts.get(gag, 0):
                return False
    return True


def _key(plan) -> tuple:
    key = tuple(repr(a) for a in plan)
    unite = unite_of(plan)
    return key if unite is None else key + (("unite",) + tuple(map(repr, unite)),)


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


# WHAT A PLAYOUT IS WORTH: cogs defeated, plus a tiebreak for the laff
# the team still has at the end. Without it, a playout that ends with the
# battle on screen -- a building, a party, any fight without a horizon --
# scores every reasonable move the same (all four cogs die), and the
# scorer's pick wins by default: on a party VP every candidate read 4.0.
# Worth at most half a cog, so a cog always outweighs laff. Set to 0 to
# score cogs alone.
LAFF_WEIGHT = 0.5

# SOONER BEATS LATER, BUT ONLY TO BREAK A TIE. On a board every playout
# wins, every move scored the same cogs and nearly the same laff, so a
# move that wastes the round tied with the one that ends it -- seen live,
# a Railroad over a lone lured cog at 26 hp rated level with the Cream Pie
# that kills it. A thousandth of a cog a round cannot outweigh a cog or a
# point of laff fraction; it only separates moves that tie on both.
ROUND_TIEBREAK = 0.001

# WHAT THE POUCH IS WORTH when a playout stops before the fight does: in
# a building the next floor's cogs are unknown, so without this, gags
# left over were worth nothing (a Foghorn beat a Whole Cream Pie on a
# lone 32hp Tightwad, spending one of two Foghorns on an already-won
# floor). Weight, in cogs, on the remaining pouch's worth as a fraction
# of its worth when the decision was made (`pouch_value`); keyed by
# fight kind, since a horizon fight plays every round and its pouch
# value is already in the result.
#
# Measured, owner's toon, 600 paired Daisy Gardens buildings against 413
# cleared at weight 0: 1/1.5/2/3 all within noise of 0 (407-414, p>0.5),
# 6 hoards and loses (378, p<0.001). Set at 2: just past the ~1.7 that
# turns the lone-Tightwad Foghorn into a Cream Pie, well inside the
# harmless range -- it buys advice that spends the gag an expert would,
# not more clears in a simulator that buildings decide by laff alone.
POUCH_WEIGHT = {"facility": 2.0}


# WHAT A GAG IS WORTH LATER: worth = damage per cog x cogs it can expect
# to hit (1 for single-target, GROUP_REACH for group). The group
# advantage scales with how hard the gag hits, which a flat "group = x2"
# got backwards: a Foghorn (~38 x 2.5) beats a Whole Cream Pie (~38) for
# a lone 32hp cog, but an Aoogah (~15 x 2.5) loses to a Safe (~65) for a
# cog on 1hp. Damage is the middle of the gag's range in the wiki-sourced
# tables (organic where the toon has it) -- the board knows a track's
# training level, not the points within it.
#
# [OWNER] 2.5, the typical cogs a group gag hits. Not measured.
GROUP_REACH = 2.5
# SCARCITY BY WHAT IS LEFT, not by what could be carried: the k-th last
# copy of a gag counts (1 + LAST_COPY / k) times -- spending one of two
# Foghorns costs more than one of three Cream Pies.
LAST_COPY = 1.0


def _worth(track, level, toon) -> Optional[float]:
    """Damage the gag could deal later, or None if it deals none."""
    from .. import data as gags_mod

    try:
        gag = gags_mod.gag(track, level)
        if not gag.damage:
            return None
        organic = bool(getattr(toon, "is_organic", lambda t: False)(track))
        damage = gag.damage_at(0.5, organic=organic)
    except Exception:                       # noqa: BLE001 -- no table entry
        return None
    return float(damage) * (GROUP_REACH if gag.group else 1.0)


def pouch_value(state: BattleState) -> float:
    """What the party's remaining gags could still do, in damage.

    Gags that deal none (Toon-Up, Lure) are priced as the search prices
    a throw, converted to damage at the rate the same toon's damage gags
    give -- one scale, without inventing a value for a heal or a lure.
    """
    from .objective import Objective

    price = Objective()
    total = 0.0
    for toon in state.toons:
        held = [(track, level, count)
                for (track, level), count in toon.gag_counts.items() if count]
        units, worths, rate_num, rate_den = [], [], 0.0, 0.0
        for track, level, count in held:
            unit = price.gag_price(track, level,
                                   unlocked=toon.track_exp.get(track, 6) or 6)
            worth = _worth(track, level, toon)
            units.append(unit)
            worths.append(worth)
            if worth is not None and unit > 0:
                rate_num += worth
                rate_den += unit
        rate = rate_num / rate_den if rate_den else 1.0
        for (track, level, count), unit, worth in zip(held, units, worths):
            each = worth if worth is not None else unit * rate
            total += each * sum(1.0 + LAST_COPY / k
                                for k in range(1, count + 1))
    return total


# THE PANEL'S PRESET (an `Objective`; None is Balanced). It reaches the
# playouts as three changes to `value`, each RELATIVE TO BALANCED, so
# Balanced is exactly the measured engine and every other preset moves by
# its own numbers rather than new ones:
#   caution  LAFF_WEIGHT x laff_weight / Balanced's (glass x0.25, survive x3)
#   thrift   the pouch weight x what the preset charges for this pouch over
#            what Balanced does (glass 0: spend freely; conserve > 1)
#   speed    (turn_cost - Balanced's) / win_bonus of a whole fight per round
#            (speedrun only)
# A setting of the process: `chunk_in_child` sets it every call, because
# pool workers are reused.
STYLE = None


def set_style(objective) -> None:
    global STYLE
    STYLE = objective


def _style():
    from .objective import BALANCED
    return STYLE or BALANCED


def _laff_weight() -> float:
    from .objective import BALANCED
    return LAFF_WEIGHT * _style().laff_weight / BALANCED.laff_weight


def _thrift(state: BattleState) -> float:
    """What the preset charges for this pouch, over what Balanced does."""
    from .objective import BALANCED

    style = _style()
    if style is BALANCED:
        return 1.0
    mine = base = 0.0
    for toon in state.toons:
        for (track, level), count in toon.gag_counts.items():
            if count:
                unlocked = toon.track_exp.get(track, 6) or 6
                mine += count * style.gag_price(track, level, unlocked=unlocked)
                base += count * BALANCED.gag_price(track, level, unlocked=unlocked)
    return mine / base if base > 0 else 1.0


def _turn_charge(total: int) -> float:
    """Cogs a round costs under the preset, beyond what Balanced charges."""
    from .objective import BALANCED

    style = _style()
    extra = style.turn_cost - BALANCED.turn_cost
    return max(0.0, extra) / style.win_bonus * total if style.win_bonus else 0.0


def value(state: BattleState, total: int, pouch_start: float = 0.0,
          pouch_weight: float = 0.0, rounds: int = 0) -> float:
    toons = [t for t in state.toons if getattr(t, "max_laff", 0)]
    laff = (sum(max(0, t.laff) for t in toons)
            / float(sum(t.max_laff for t in toons))) if toons else 0.0
    score = total - _left(state) + _laff_weight() * laff
    if pouch_weight and pouch_start > 0:
        score += pouch_weight * pouch_value(state) / pouch_start
    if rounds:
        score -= (_turn_charge(total) + ROUND_TIEBREAK) * rounds
    return score


def _carry(state: BattleState, horizon) -> Tuple[float, float]:
    """(pouch value now, its weight) for a playout of `state`."""
    weight = 0.0 if horizon is not None else POUCH_WEIGHT.get(state.kind, 0.0)
    if weight:
        weight *= _thrift(state)
    return (pouch_value(state) if weight else 0.0), weight


def _left(state: BattleState) -> int:
    return (sum(1 for c in state.cogs if c.hp > 0) + len(state.holdout)
            + state.cogs_remaining)


def step_round(env, plan):
    """Play one round of `plan` through the environment."""
    from ..rl import env as env_mod

    start = env.rounds
    done, info = False, {}
    unite = unite_of(plan)
    if unite is not None and env.state.toons:
        from .. import unites as unites_mod

        toon = env.state.toons[0]
        if unites_mod.available(toon) and unites_mod.in_stock(toon, unite):
            unites_mod.apply(toon, unite)
    if TEAMMATE_UNITES and len(env.state.toons) > 1:
        _teammate_unites(env.state)
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


# SHORTENED PLAYOUTS: after ROLLOUT_DEPTH rounds, stop and ask
# ROLLOUT_VALUE (a `valuenet.load` model trained on the playouts' own units:
# cogs defeated from a board to the end plus LAFF_WEIGHT x laff left, under
# the fast network, seeing the holdout and later-wave counts --
# `tools/gen_value_outcomes.py --units playout --extras`) for the rest.
# Solo playouts only. "auto" loads `PLAYOUT_VALUE_WEIGHTS` when numpy and
# the file are there and plays in full otherwise; None turns it off.
# Measured with HALVING doubled: solo VP 175 vs 163 of 260 in 28% less
# time a decision, duo VP 57 vs 52 of 100 (1.72s vs 1.37s -- short fights
# save less than the extra playouts cost).
ROLLOUT_DEPTH: Optional[int] = 8
ROLLOUT_VALUE = "auto"
PLAYOUT_VALUE_WEIGHTS = (Path(__file__).resolve().parents[1] / "rl"
                         / "playout_value.json")
_AUTO_VALUE: list = []


def _rollout_value():
    """The model shortened playouts use, or None to play in full."""
    if ROLLOUT_VALUE != "auto":
        return ROLLOUT_VALUE
    if not _AUTO_VALUE:
        try:
            from . import valuenet
            _AUTO_VALUE.append(valuenet.load(PLAYOUT_VALUE_WEIGHTS))
        except Exception:                  # noqa: BLE001 -- no numpy or no file
            _AUTO_VALUE.append(None)
    return _AUTO_VALUE[0]


def rollout(state, plan, horizon, seed: int) -> float:
    """`value` at the end of one playout that opens with `plan`."""
    from . import hybrid

    rng = random.Random(seed)
    env = build_env(state, horizon, rng)
    total = _left(env.state)
    pouch_start, pouch_weight = _carry(state, horizon)
    policy_rng = random.Random(seed + 1)
    done, _info = step_round(env, plan)
    guard = 0
    use_net = False
    # The net knows one seat; a party is played on by climb, which plans
    # every seat jointly, at the menu's budget.
    party = len(state.active_toons()) > 1
    if ROLLOUT_PLAYER == "net" and not party:
        from . import fastplayer
        use_net = fastplayer.available()
    while not done and guard < ROUND_CAP:
        guard += 1
        if use_net and ROLLOUT_DEPTH is not None and guard > ROLLOUT_DEPTH:
            model = _rollout_value()
            if model is not None:
                from . import valuenet
                return (total - _left(env.state)
                        + valuenet.predict(model, _view(env.state),
                                           holdout=len(env.state.holdout)))
        if use_net:
            nxt = fastplayer.act(_view(env.state))
        else:
            view = _view(env.state)
            if party:
                # Gags from climb, the unite from the network's unite
                # head -- as the teammates choose theirs. climb's own
                # unite check re-plans the whole round once per option
                # (up to 13), which took a CEO side from 4 s to 25 s a
                # decision. The first move keeps climb's full check.
                nxt = with_unite(hybrid.climb(view, policy_rng, budget=CLIMB_BUDGET,
                                              allow_unites=False),
                                 _net_unite(view))
            else:
                nxt = climb_with_unite(view, policy_rng, budget=ROLLOUT_BUDGET)
        if nxt is None:
            break
        done, _info = step_round(env, nxt)
    return value(env.state, total, pouch_start, pouch_weight, rounds=guard + 1)


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
        chosen = climb_with_unite(probe, random.Random(0), budget=CLIMB_BUDGET,
                                  reject=frozenset(reject or ()))
    finally:
        hybrid._judge = real
    if chosen is None:
        return []
    out, seen = [chosen], {_key(chosen)}
    for plan, _value in sorted(scored.values(), key=lambda pv: -pv[1]):
        if len(out) >= top_k:
            break
        if _key(plan) not in seen and playable(state, plan):
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
SCHEDULE = (2, 4, 8) + tuple(range(12, 65, 4))


def _seed(k: int) -> int:
    """Rollout k's seed -- what `pick` uses at seed 0, so a chunked run
    and a single `pick` see the same cogs and dice."""
    return k * 7919


def chunk_in_child(state: BattleState, horizon, reject, allow_level_7: bool,
                   k_from: int, k_to: int, only=None, wide: bool = True,
                   style: Optional[str] = None):
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
    from .objective import PRESETS
    set_style(PRESETS.get(style or "balanced"))
    if not hybrid.available() or state.is_terminal():
        return None, "unavailable"
    # A board with teammates on it is PICKUP: your move from the menu,
    # theirs from the teammate model inside every rollout.
    if state.toons and state.toons[0].laff <= 0:
        return None, "you are out"
    pickup = len(state.toons) > 1 and GROUP_MODE == "pickup"
    menu_board = solo_view(state) if pickup else state
    cands = (wide_candidates(menu_board, reject) if wide
             else candidates(menu_board, TOP_K, reject))
    if not cands:
        return None, "unavailable"
    if len(cands) == 1:
        return [(cands[0], [])], ""
    play = rollout_pickup if pickup else rollout
    wanted = None if only is None else set(only)
    values = [[] for _ in cands]
    for k in range(k_from, k_to):
        for i, plan in enumerate(cands):
            if wanted is None or _key(plan) in wanted:
                values[i].append(play(state, plan, horizon, _seed(k)))
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
WIDE_CAP = 12             # 10, plus room for the two unite variants
# Successive halving: everyone gets HALVING[0] rollouts, the better half
# goes on to HALVING[1], and so on -- with the same seeds throughout.
#
# (8, 16, 32): the equal-time measurement above, with the net playing.
# (2, 4, 8) was the first measured setting, with climb playing.
# Doubling to (16, 32, 64) did not pay with full playouts: 146 vs 139 wins
# of 200, +36/-29, p = 0.46, at twice the time. With shortened playouts
# (ROLLOUT_DEPTH) each one is cheap enough that it does -- see there.
HALVING = (16, 32, 64)
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


def _unite_variants(state: BattleState, chosen) -> list:
    """climb's gags opened with each kind of unite worth trying, for the
    playouts to judge by outcome.

    climb proposes a unite only when it clears `unites.UNITE_PRICE` (200,
    against ~2 a point of laff healed), so short of near-death it never
    does, and a unite then never reached the menu at all: seen live, a toon
    at 33/100 laff with five unites and no cooldown was offered none. The
    playouts charge no price -- a unite is worth what it changes about how
    the fight ends -- so the biggest Toon-Up worth its heal and the
    all-tracks Gag-Up go on the menu whenever one could be used.
    """
    from .. import unites as unites_mod

    if not state.toons or chosen is None or unite_of(chosen) is not None:
        return []
    toon = state.toons[0]
    if not unites_mod.available(toon):
        return []
    options = unites_mod.candidates(toon)
    picks = []
    heal = next((c for c in options if c[0] == "toon_up"), None)
    if heal is not None:
        picks.append(heal)
    restock = next((c for c in options if c[0] == "gag_up"), None)
    if restock is not None:
        picks.append(restock)
    return [with_unite(list(chosen), c) for c in picks]


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
        chosen = climb_with_unite(probe, random.Random(0), budget=CLIMB_BUDGET,
                                  reject=frozenset(reject or ()))
    finally:
        hybrid._judge = real
    if chosen is None:
        return []
    ranked = [p for p, _v in sorted(scored.values(), key=lambda pv: -pv[1])]

    out, seen = [], set()

    def add(plan):
        if (plan is not None and _key(plan) not in seen and len(out) < cap
                and playable(state, plan)):
            seen.add(_key(plan))
            out.append(plan if isinstance(plan, Plan) else list(plan))

    add(chosen)
    if unite_of(chosen) is not None:
        add(list(chosen))      # the same gags without it: the unite must earn its use
    for plan in _unite_variants(state, chosen):
        add(plan)
    for plan in ranked[:WIDE_SCORER_TOP]:
        add(plan)
    if len(state.active_toons()) > 1:
        # A PARTY: every candidate is a joint plan from climb's own menu,
        # kept diverse by what EACH seat does. The network's single-seat
        # favourites and a lone pass are not whole plans, so they are
        # left out.
        best_joint = {}
        for plan in ranked:
            best_joint.setdefault(tuple(_kind(a) for a in plan), plan)
        for plan in best_joint.values():
            add(plan)
        return out
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
              reject=None, stages=HALVING,
              mode: Optional[str] = None) -> Optional[Result]:
    """Successive halving over `wide_candidates`, common random numbers.

    A board with teammates on it is handled as `mode` says -- default
    `GROUP_MODE`, exactly as the panels' chunked playouts handle it:
    "coordinated" chooses among joint plans, "pickup" chooses your move
    with the teammates modelled. On the CEO, coordinated party playouts
    were neutral (48 vs 43 of 200, p = 0.44) for want of a horizon.
    """
    from . import hybrid

    if not hybrid.available() or state.is_terminal():
        return None
    if state.toons and state.toons[0].laff <= 0:
        return None
    pickup = len(state.toons) > 1 and (mode or GROUP_MODE) == "pickup"
    cands = wide_candidates(solo_view(state) if pickup else state, reject)
    if not cands:
        return None
    play = rollout_pickup if pickup else rollout
    if len(cands) == 1:
        return Result(cands[0], cands, [0.0], 0)
    values = {i: [] for i in range(len(cands))}
    alive, done_k = list(range(len(cands))), 0
    for stage, upto in enumerate(stages):
        for k in range(done_k, upto):
            for i in alive:
                values[i].append(play(state, cands[i], horizon,
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
    if not hybrid.available() or state.is_terminal():
        return None, "unavailable"
    if state.toons and state.toons[0].laff <= 0:
        return None, "you are out"
    pickup = len(state.toons) > 1 and GROUP_MODE == "pickup"
    menu_board = solo_view(state) if pickup else state
    cands = (wide_candidates(menu_board, reject) if wide
             else candidates(menu_board, TOP_K, reject))
    if not cands:
        return None, "unavailable"
    return [_key(plan) for plan in cands], ""


# ---------------------------------------------------------------------
# Pickup: choose YOUR move; teammates are modelled, not controlled
# ---------------------------------------------------------------------
#
# In a group you control one toon. The candidates are your moves alone,
# so the menu stays ~10 however many toons there are, and the rollouts
# play the teammates from `party.DEFAULT_MODEL` -- `SensiblePrior`, a
# MODEL OF PEOPLE, labelled as a guess in `solver/party.py`. Any number
# this path produces rests on it. `TEAMMATE_MODEL` swaps it (None is
# `party.DEFAULT_MODEL`), e.g. for `party.NetTeammate`.
TEAMMATE_MODEL = None


# HOW A BOARD WITH TEAMMATES ON IT IS PLAYED OUT in the panels.
# "coordinated": candidates are joint plans for the whole party and the
# rollouts play every seat together with climb -- the teammates are
# assumed to play their part of the best joint plan. "pickup": your
# moves only, teammates sampled from the teammate model each round.
# Coordinated is the live default: in simulation, planning the party
# together won 23 of 40 party VPs and planning each toon alone won 0,
# with either teammate model.
GROUP_MODE = "coordinated"


# TEAMMATES USE UNITES TOO, in both group modes. A unite costs no turn --
# it opens the round beside the gag -- so a teammate holding one uses it
# whatever they throw. Each standing teammate's unite is chosen from
# THEIR seat by the fast network's unite head (`fastplayer.choose_unite`,
# which copies climb's unite choice, 96% held out). In coordinated mode
# that is the team's plan; in pickup mode it is a model of what a
# stranger does with a unite, a guess in the same way `SensiblePrior` is.
# Nothing is invented: a teammate uses only unites they are recorded as
# holding, and the live readers record none for anyone but you.
TEAMMATE_UNITES = True


def seat_view(state: BattleState, seat: int) -> BattleState:
    """The board from `seat`'s chair: that toon first, the others a count."""
    view = state.clone()
    me = view.toons[seat]
    others = sum(1 for i, t in enumerate(view.toons) if i != seat and t.laff > 0)
    view.toons = [me]
    view.allies_standing = others + max(0, int(getattr(state, "allies_standing", 0)))
    view.holdout = []
    return view


def _net_unite(view: BattleState):
    """The fast network's unite for seat 0 of `view`, or None."""
    from . import fastplayer

    if not view.toons or not fastplayer.available():
        return None
    return fastplayer.choose_unite(seat_view(view, 0))


def _teammate_unites(state: BattleState) -> None:
    """Every standing teammate opens the round with the unite their seat
    calls for, if they hold one. In place, on the real fight."""
    from .. import unites as unites_mod
    from . import fastplayer

    if not fastplayer.available():
        return
    for seat in range(1, len(state.toons)):
        toon = state.toons[seat]
        if toon.laff <= 0 or not unites_mod.available(toon):
            continue
        choice = fastplayer.choose_unite(seat_view(state, seat))
        if choice is not None and unites_mod.in_stock(toon, choice):
            unites_mod.apply(toon, choice)


def solo_view(state: BattleState) -> BattleState:
    """You, with the others reduced to a count -- the shape the live
    panels build, and the shape the menu and the fast net were made on."""
    view = state.clone()
    others = sum(1 for t in view.toons[1:] if t.laff > 0)
    view.toons = view.toons[:1]
    view.allies_standing = others + max(0, int(getattr(state, "allies_standing", 0)))
    view.holdout = []
    return view


def rollout_pickup(state: BattleState, plan, horizon, seed: int) -> float:
    """One pickup playout: your `plan` now, then the net (or climb) for
    you and the teammate model for everyone else, to the end."""
    from . import hybrid
    from ..rl import env as env_mod
    from .. import facility

    rng = random.Random(seed)
    start = state.clone()
    kind = start.kind
    start.kind = "street"
    start.holdout, start.cogs_remaining = [], 0
    env = env_mod.BattleEnv(rng=rng, sampler=lambda _r: start,
                            coordinated=False, max_rounds=ROUND_CAP)
    env.teammate_model = TEAMMATE_MODEL
    env.reset()
    env.state.kind = kind
    if horizon is not None:
        make = (env._sellbot_cog if horizon.department == "sellbot"
                else env._boss_cog)
        lo, hi = horizon.band
        env.state.holdout = [make(rng, rng.randint(lo, hi))
                             for _ in range(horizon.holdout)]
        floors = [[make(rng, rng.randint(a, b)) for _ in range(n)]
                  for n, (a, b) in horizon.later]
        if floors:
            env.plan = facility.FacilityPlan(floors)
            env.state.cogs_remaining = env.plan.remaining()
    total = _left(env.state)
    pouch_start, pouch_weight = _carry(state, horizon)
    use_net = False
    if ROLLOUT_PLAYER == "net":
        from . import fastplayer
        use_net = fastplayer.available()
    policy_rng = random.Random(seed + 1)
    done, _info = step_round(env, plan)
    guard = 0
    while not done and guard < ROUND_CAP:
        guard += 1
        if env.state.toons[0].laff <= 0:
            nxt = [None]                   # you are out; the others play on
        else:
            mine = solo_view(env.state)
            nxt = (fastplayer.act(mine) if use_net
                   else climb_with_unite(mine, policy_rng, budget=ROLLOUT_BUDGET))
        done, _info = step_round(env, nxt)
    return value(env.state, total, pouch_start, pouch_weight, rounds=guard + 1)


def pick_pickup(state: BattleState, horizon=None, seed: int = 0,
                reject=None, stages=HALVING) -> Optional[Result]:
    """Your best move in a group, the teammates modelled: `pick_wide` in
    pickup mode."""
    return pick_wide(state, horizon, seed, reject, stages, mode="pickup")
