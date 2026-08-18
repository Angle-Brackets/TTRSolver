"""PPO proposes, the search's scorer judges.

The policy costs a third of a millisecond a decision and the party
search costs a hundred, so there is room to spend a little of that gap
checking the policy's own suggestions. This samples a few joint plans
from the trained policy and keeps whichever one `_quick_score` likes
best.

Measured over 180 HELD-OUT buildings -- seeds never tuned against,
which matters because the tuned set flattered this badly:

    agent                floors  finished   plans/second
    plain PPO              2.44     61.7%           2266
    climb, budget 8        2.49     66.1%            656
    climb, budget 16       2.48     66.1%            467
    best-of-16 sampling       -         -            106
    full search            2.48     67.8%              1

`climb` recovers about two thirds of the distance from the policy to
the search for roughly double the policy's cost, and it is
deterministic -- it walks the policy's ranked logits rather than
sampling, so it returns the same plan every time.

THE SEARCH IS STILL AHEAD, by 1.7 points. On the tuned seeds this
scored 69.4% against the search's 65.0% and looked like a win; on fresh
buildings it is 66.1% against 67.8%. Same code, same budget. Anything
measured on the set it was chosen on is worth re-running elsewhere.

BUDGET 8 BEATS BUDGET 16 on the tuned set (69.4% against 66.7%) and
ties it here. `_quick_score` is an approximation, so climbing it harder
optimises the proxy rather than the game -- more budget is not
automatically better, which is the tell that the scorer, not the
search strategy, is now the ceiling.

WHERE THE REMAINING GAP IS
--------------------------
Usage over 80 held-out buildings, climb at budget 8 against the search:

    holds      2.1%   11.0%      <- the big one
    throw     44.4%   35.1%
    squirt    20.3%   23.4%
    sound     11.4%   14.1%
    drop      10.0%    8.2%
    lure       7.8%    9.5%
    toon_up    4.8%    6.7%
    trap       1.3%    2.9%

CLIMB ALWAYS SWINGS. It declines to act on 2.1% of decisions against
the search's 11.0%, throws 13% more gags over the same buildings (2159
against 1918), and skews to level 4 (38.1% against 27.9%) where the
search prefers 5 and 6. More gags, each weaker, and almost never a
hold.

Every one of those differences is the same thing: `_quick_score` pays
for damage landed, so an action that deals none scores near zero
whatever it saves. Healing is the visible case -- on seed 31003 the
search heals three times in seven rounds and holds the party at 48-55
laff, while the climb heals twice, the second time at [2, 17, 2], and
loses the building with two toons carrying Toon-Up 7.

A caution about the obvious fix, learnt the hard way: hold-variants
were forced into the SEARCH's shortlist once and play got worse, 2.07
floors to 1.83, and that was written down as "the overkill is not a
bug". It was ranked by `_quick_score` too. What that experiment
actually showed is that holding *as this scorer judges it* is bad --
the search's own 11% comes from sampled rollouts, which can see a
conserved gag spent later.

WHY IT WORKS
------------
PPO is a better PROPOSAL DISTRIBUTION than the search's enumeration.
`party_search.plans` builds joint plans combinatorially and then
truncates, and that truncation is where a long line of this project's
bugs have lived -- a stratified cut that dropped every Sound plan, a
shortlist that dropped Trap in 39 of 39 positions, a lexicographic
prefix that dropped the best line outright. The policy suggests a
handful of plausible plans directly and the scorer only has to rank
those.

THE JUDGE MUST NOT BE THE PROPOSER
----------------------------------
Ranking the same samples with PPO's own critic achieves nothing: 57.8%
at four plans and 58.3% at twelve, against 58.9% for plain argmax. It
asks the network to catch its own mistakes, and a network that could
would not be making them. `docs/ml-design.md` records the learned-leaf
evaluator losing in place for the same reason. `_quick_score` is an
independent opinion and that is the whole point of it.

Needs numpy, and says so by returning False from `available()` rather
than raising -- the same contract `search/policy.py` follows. Torch
never appears here; what ships is the plain-float export.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from ..state import Action, BattleState

# How much of the follow-up round counts when `judge="deep"`. Less than
# one because the second round is played by a greedy stand-in rather
# than by whatever will really happen.
LOOKAHEAD_DISCOUNT = 0.7

# Per-round discount for `rollout_judge`. Near one because a building is
# long and a gag saved on floor one is spent on floor four; the reward
# function already prices the horizon through `cogs_remaining`.
DISCOUNT = 0.95

_EXPORT = Path(__file__).resolve().parents[1] / "rl" / "ppo_facility.json"
_MODEL: Optional[dict] = None
_TRIED = False


def _load():
    """The exported policy, or None if it is missing or unusable."""
    global _MODEL, _TRIED
    if _TRIED:
        return _MODEL
    _TRIED = True
    try:
        import numpy as np                                   # noqa: F401
    except ImportError:
        return None
    if not _EXPORT.exists():
        return None
    try:
        payload = json.loads(_EXPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    from ..rl import env as env_mod
    if env_mod.check_export(payload):
        # Trained against a different observation or action table. A
        # silent mismatch reads 290 floats through weights expecting
        # 288 and returns confident nonsense.
        return None

    import numpy as np
    layers, i = [], 0
    while f"{i}.weight" in payload["trunk"]:
        layers.append((np.array(payload["trunk"][f"{i}.weight"]).T,
                       np.array(payload["trunk"][f"{i}.bias"])))
        i += 2
    _MODEL = {
        "trunk": layers,
        "aw": np.array(payload["actor"]["weight"]).T,
        "ab": np.array(payload["actor"]["bias"]),
    }
    return _MODEL


def available() -> bool:
    """Is a usable policy loadable? False means fall back, not fail."""
    return _load() is not None


def _logits(model, state: BattleState, seat: int, pending):
    import numpy as np

    from ..rl import env as env_mod

    x = np.array(env_mod.encode(state, seat, pending), dtype=float)
    for weight, bias in model["trunk"]:
        x = np.tanh(x @ weight + bias)
    out = x @ model["aw"] + model["ab"]
    mask = env_mod.legal_mask(state, seat)
    out = np.where(np.array(mask), out, -np.inf)
    return out


def _choose(values, rng, sample: bool) -> int:
    import numpy as np

    if not sample:
        return int(np.argmax(values))
    finite = np.isfinite(values)
    if not finite.any():
        return 0
    shifted = np.where(finite, values - values[finite].max(), -np.inf)
    weights = np.where(finite, np.exp(shifted), 0.0)
    total = float(weights.sum())
    if total <= 0:
        return int(np.argmax(values))
    roll = rng.random() * total
    for index, weight in enumerate(weights):
        roll -= float(weight)
        if roll <= 0:
            return index
    return int(np.argmax(values))


def propose(state: BattleState, rng, sample: bool = True,
            fixed: Optional[Mapping[int, Optional[Action]]] = None
            ) -> List[Optional[Action]]:
    """One joint plan, every standing toon choosing in turn.

    Later toons see the earlier ones' picks through `pending`, which is
    what makes this a joint plan rather than four independent ones.

    `fixed` pins seats that have ALREADY COMMITTED, which matters when
    the caller is midway through a round rather than starting one. It is
    a mapping rather than a list because `None` already means "pass" in
    a plan, and a pinned pass and an open seat are not the same thing.
    """
    from ..rl import env as env_mod

    model = _load()
    if model is None:
        raise RuntimeError("no usable policy; check hybrid.available()")

    fixed = dict(fixed or {})
    pending: List[Optional[Action]] = [None] * len(state.toons)
    for seat, action in fixed.items():
        pending[seat] = action
    for seat, toon in enumerate(state.toons):
        if seat in fixed or toon.laff <= 0:
            continue
        index = _choose(_logits(model, state, seat, pending), rng, sample)
        action = env_mod.action_at(index)
        pending[seat] = None if action.is_pass else action
    return pending


def rollout_judge(state: BattleState, plan, seed: int, depth: int = 3,
                  objective=None) -> float:
    """Play the plan, then let PPO play on, and total the real reward.

    The horizon `_quick_score` does not have. It plays one all-hit round
    and scores it with a hand-weighted sum whose weights turn out not to
    matter -- four random weight vectors finish 62.5-65.0% of the same
    buildings, and zeroing every term costs five points. So the terms
    matter and their sizes do not, which is what a flat proxy looks
    like.

    This scores the future with `round_reward` instead: the objective
    the environment actually pays, over several rounds of PPO's own
    play. It is Bertsekas's rollout with the learned policy as the base,
    which is what makes the guarantee interesting -- a rollout policy is
    no worse than its base when the evaluation is sound.

    NOT the two-ply judge that failed earlier. That one let
    `greedy_plan` answer for the next round, and greedy is a myopic
    proxy, so it added a guess about the future to a real reading of the
    present and weighted the guess at 0.7. It cost nearly three points.
    PPO is a considerably better base policy than greedy, and it is fast
    enough to run several rounds.

    COMMON RANDOM NUMBERS. Every candidate plan is rolled out from the
    same `seed`, so the accuracy rolls and cog attacks are identical
    across candidates and the comparison is paired. Without that the
    climb would reliably pick whichever plan drew the luckiest dice,
    which with eight candidates is most of them.

    IT IS OFF, AND THE REASON IS THE USEFUL PART. Over 180 held-out
    buildings, climb at budget 8:

        `_quick_score`, one round      64.4%   0.76 ms
        PPO rollout, two rounds        61.1%   2.50 ms
        PPO rollout, four rounds       60.6%   3.23 ms

    Deeper is monotonically worse, and cost is not the issue at three
    milliseconds. The judge is: scoring a plan by what happens when PPO
    PLAYS ON measures how well PPO exploits the resulting position, not
    how good the position is. A strong plan leading somewhere PPO
    handles badly is marked down. It is circular.

    Third time that has been established here. PPO's own critic ranking
    PPO's samples: 57.8-58.3% against 58.9% for plain argmax. A two-ply
    lookahead played by `greedy_plan`: nearly three points worse. This:
    three to four points worse. The only judge that has ever helped is
    `_quick_score`, which shares none of the proposer's blind spots and
    is worth 58.9% to 64.4%.

    It is also why the SEARCH works: `rollout_value` plays forward with
    `greedy_plan`, a different policy from the plans it grades.

    The horizon idea is not refuted, only this way of getting one --
    Toon-Up use does rise 4.1% to 5.3% with rollouts on, so the longer
    view pushes where it should. What is refuted is asking the policy to
    grade itself.
    """
    from .. import party as party_mod
    from . import objective as objective_mod
    from . import party_search as ps

    objective = objective or objective_mod.BALANCED
    rng = random.Random(seed)
    total, current, live = 0.0, state, list(plan)
    for step in range(max(1, depth)):
        if current.is_terminal():
            break
        try:
            nxt, _healed, _done = party_mod.step(
                current, live[0], mode=party_mod.Mode.COORDINATED,
                joint=live, rng=rng)
        except (NotImplementedError, ValueError, KeyError):
            break
        laff_lost = sum(max(0, b.laff - a.laff)
                        for b, a in zip(current.toons, nxt.toons))
        went_sad = sum(1 for b, a in zip(current.toons, nxt.toons)
                       if b.laff > 0 and a.laff <= 0)
        total += (DISCOUNT ** step) * ps.round_reward(
            objective, laff_lost, ps._spent(current, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win(),
            toons_lost=went_sad,
            cogs_remaining=current.cogs_remaining)
        current = nxt
        if current.is_terminal():
            break
        live = propose(current, rng, sample=False)
    return total


def _judge(state: BattleState, plan, deep: bool) -> float:
    """Rank a plan. One round, or two.

    `_quick_score` plays a single all-hit round, which is why a trap
    scores near zero and why climbing it harder stops paying: it cannot
    see anything that arrives next round. `deep` plays the plan, then
    lets `greedy_plan` answer for the round after, and counts that at
    LOOKAHEAD_DISCOUNT.

    This is what the search has and the climb did not. `party_search`
    scores its plans with `rollout_value`, several rounds of play; this
    is the cheapest possible imitation of it.

    IT IS OFF, having been measured. Over 180 held-out buildings:

        1-ply, budget 8      66.7% finished   0.61 ms
        1-ply, budget 12     65.0%            0.73 ms
        2-ply, budget 8      63.9%            1.82 ms
        2-ply, budget 12     63.9%            2.38 ms

    Nearly three points worse at three times the cost. The second round
    is played by `greedy_plan`, which is a myopic proxy itself, so this
    adds a GUESS about the next round to a real evaluation of this one
    and weights the guess at 0.7. A lookahead is only as good as the
    policy that plays it forward.

    Third judge improvement to fail: trap credit was worth +0.6 (noise),
    track probes -2.8, this -2.8. Plain one-ply `_quick_score` at budget
    8 has beaten all of them.
    """
    from .. import party as party_mod
    from . import objective as objective_mod
    from . import party_search as ps

    first = ps._quick_score(state, plan)
    if not deep:
        return first
    probe = state.clone()
    try:
        ps.simulator.apply_party_round(
            probe, list(plan), hits=[a is not None and not a.is_pass
                                     for a in plan])
    except (NotImplementedError, ValueError, KeyError):
        return first
    if probe.is_terminal():
        return first
    try:
        follow = ps.greedy_plan(probe, objective_mod.BALANCED)
        return first + LOOKAHEAD_DISCOUNT * ps._quick_score(probe, follow)
    except (NotImplementedError, ValueError, KeyError):
        return first


def climb(state: BattleState, rng=random, budget: int = 16,
          width: int = 3, probe_tracks: bool = False,
          deep: bool = False, rollout: int = 0,
          fixed: Optional[Mapping[int, Optional[Action]]] = None
          ) -> Optional[Sequence[Optional[Action]]]:
    """Coordinate ascent on the joint plan, instead of independent draws.

    `best_plan` re-rolls every seat on every sample, which spends its
    budget re-deciding the seats that were already right. A joint plan
    is one action per toon, so the natural move is to fix the others and
    vary one seat at a time -- the same structure the search exploits
    when it enumerates per toon.

    Starts from the policy's argmax plan, then sweeps the seats,
    offering each the policy's top `width` alternatives and keeping any
    that `_quick_score` prefers. Repeats until a full sweep changes
    nothing or the budget of scorer calls runs out.

    Budget is counted in `_quick_score` calls so this can be compared
    with `best_plan` at equal cost, which is the only fair comparison
    between two search strategies.

    `probe_tracks` offers each seat the best action of every track it
    holds, not just the policy's top `width`. It is OFF, having been
    tried and measured, and the reason it fails is worth more than the
    feature would have been.

    The motivation was real. The climb can only reorder what the policy
    proposes, and PPO gives Trap essentially no probability, so a plan
    containing one is unreachable however much budget is spent -- while
    the search opens the same position with `trap5` and a hold. Probing
    does fix that: on the position in question the climb goes from
    `sound5 + squirt5 + squirt4 + throw7` to `trap5 + sound5 + squirt4
    + throw7`, matching the search on three seats of four.

    It does not help, over 180 held-out buildings:

        no probes, budget 8      66.1% finished   trap 1.0%
        probes,    budget 8      63.3%            trap 1.2%
        no probes, budget 12     65.0%            trap 0.9%
        probes,    budget 12     65.0%            trap 1.2%

    Trap use barely moves, so the probes are being OFFERED and
    `_quick_score` is declining them -- it plays one all-hit round, and
    a trap pays the round after, so it scores near zero. Widening a
    proposal cannot help when the judge is blind to what was added, and
    the probes cost budget that the seat-swaps were using, which is why
    budget 8 gets worse rather than merely staying flat.

    The evaluator is the ceiling here, not the proposal width. Same
    conclusion the budget sweep reached from the other side: climbing
    `_quick_score` harder stops helping, because it is a proxy.
    """
    import numpy as np

    from ..rl import env as env_mod
    from . import party_search as ps

    if not available():
        return None
    model = _load()

    # One seed for every candidate this call compares, so the rollouts
    # are paired rather than a lottery.
    seed = rng.randrange(1 << 30)
    judge = ((lambda st, pl: rollout_judge(st, pl, seed, rollout))
             if rollout else (lambda st, pl: _judge(st, pl, deep)))

    fixed = dict(fixed or {})
    plan = list(propose(state, rng, sample=False, fixed=fixed))
    try:
        best_score = judge(state, plan)
    except (NotImplementedError, ValueError, KeyError):
        return plan
    spent = 1

    improved = True
    while improved and spent < budget:
        improved = False
        for seat, toon in enumerate(state.toons):
            if seat in fixed or toon.laff <= 0 or spent >= budget:
                continue
            pending = list(plan)
            pending[seat] = None
            values = _logits(model, state, seat, pending)
            order = list(np.argsort(values)[::-1][:width])
            if probe_tracks:
                # The best of every track this toon can actually play,
                # in the policy's own within-track order.
                seen_tracks = set()
                for i in order:
                    entry = env_mod.ACTIONS[int(i)]
                    if entry is not None and np.isfinite(values[int(i)]):
                        seen_tracks.add(entry.track)
                for index in np.argsort(values)[::-1]:
                    index = int(index)
                    if not np.isfinite(values[index]):
                        break
                    entry = env_mod.ACTIONS[index]
                    if entry is None:
                        continue          # ACTIONS has gaps
                    track = entry.track
                    if track in seen_tracks:
                        continue
                    seen_tracks.add(track)
                    order.append(index)
            for index in order:
                if not np.isfinite(values[index]):
                    continue
                action = env_mod.action_at(int(index))
                trial = list(plan)
                trial[seat] = None if action.is_pass else action
                if trial == plan:
                    continue
                try:
                    score = judge(state, trial)
                except (NotImplementedError, ValueError, KeyError):
                    continue
                spent += 1
                if score > best_score:
                    plan, best_score, improved = trial, score, True
                if spent >= budget:
                    break
    return plan


def best_plan(state: BattleState, rng=random, samples: int = 16
              ) -> Optional[Sequence[Optional[Action]]]:
    """Sample `samples` plans from the policy; keep the best.

    The first is the policy's argmax, so this can never be worse than
    plain greedy play except through the scorer's own error.
    """
    from . import party_search as ps

    if not available():
        return None
    seen, best, best_score = set(), None, -math.inf
    for i in range(max(1, samples)):
        plan = propose(state, rng, sample=(i > 0))
        key = tuple((a.track, a.level, a.target_index) if a is not None
                    else None for a in plan)
        if key in seen:
            continue
        seen.add(key)
        try:
            score = ps._quick_score(state, plan)
        except (NotImplementedError, ValueError, KeyError):
            continue
        if score > best_score:
            best, best_score = plan, score
    return best
