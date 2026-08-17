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
from typing import List, Optional, Sequence

from ..state import Action, BattleState

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


def propose(state: BattleState, rng, sample: bool = True
            ) -> List[Optional[Action]]:
    """One joint plan, every standing toon choosing in turn.

    Later toons see the earlier ones' picks through `pending`, which is
    what makes this a joint plan rather than four independent ones.
    """
    from ..rl import env as env_mod

    model = _load()
    if model is None:
        raise RuntimeError("no usable policy; check hybrid.available()")

    pending: List[Optional[Action]] = [None] * len(state.toons)
    for seat, toon in enumerate(state.toons):
        if toon.laff <= 0:
            continue
        index = _choose(_logits(model, state, seat, pending), rng, sample)
        action = env_mod.action_at(index)
        pending[seat] = None if action.is_pass else action
    return pending


def climb(state: BattleState, rng=random, budget: int = 16,
          width: int = 3, probe_tracks: bool = False
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

    plan = list(propose(state, rng, sample=False))
    try:
        best_score = ps._quick_score(state, plan)
    except (NotImplementedError, ValueError, KeyError):
        return plan
    spent = 1

    improved = True
    while improved and spent < budget:
        improved = False
        for seat, toon in enumerate(state.toons):
            if toon.laff <= 0 or spent >= budget:
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
                    score = ps._quick_score(state, trial)
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
