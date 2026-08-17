"""PPO proposes, the search's scorer judges.

The policy costs a third of a millisecond a decision and the party
search costs a hundred, so there is room to spend a little of that gap
checking the policy's own suggestions. This samples a few joint plans
from the trained policy and keeps whichever one `_quick_score` likes
best.

Measured over 180 identical buildings:

    agent                floors  finished  ms/decision
    plain PPO              2.48     58.9%         0.28
    PPO x16 + scorer       2.60     64.3%         2.89
    full search            2.63     65.0%       ~105

Indistinguishable from the search at a thirty-sixth of the cost, and
monotonic in `samples`, so it is a dial rather than a setting.

THE SPREAD IS PART OF THE RESULT. Sampling makes each run different:
three independent streams over the same 180 buildings finished 62.8%,
65.6% and 64.4%. Any single run of this is worth about three points
either way, which is wider than the gap to the search -- so "matches"
is the claim, and "beats" is not, however tempting one run looks.

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
