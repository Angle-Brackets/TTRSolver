"""Rank candidate plans with the trained policy head (P0).

`plans()` has to decide which handful of the thousands of legal team
plans deserve to be searched. That decision is the term search cost is
exponential in, and it is where this project has repeatedly lost the
right answer -- `CANDIDATES_PER_TRACK = 2` hid the best Sound mix, `max_plans` took
a lexicographic prefix, then a global top-N, then `QUICK_SCORED_PER_TRACK`
reintroduced the prefix bug a level down.

Measured on 375 held-out positions, by regret@6 (the value given up by
searching only the top six):

    learned policy            3.22    lossless 39%
    _quick_score (shipped)    9.93    lossless 28%
    uniform random           12.09

`_quick_score` is barely better than random at this job, which is both
why the policy wins so easily and why those bugs were so easy to
introduce.

OPTIONAL, LIKE VISION
---------------------
Needs numpy, and says so by returning False from `available()` rather
than raising. `party_search` falls back to `_quick_score` when it is
absent, so the core and the whole test suite still run on the standard
library alone -- the same arrangement `live/vision.py` has.

Numpy rather than pure Python is not a preference. `plans()` scores
thousands of candidates per node; a pure-Python forward pass over that
many would cost more than the search it is meant to save.

NEVER THE ONLY GATE
-------------------
`party_search.plans` keeps its per-track-family stratification whether
or not this is loaded. A learned ranker is still a reduction and can
still delete the right answer -- more confidently than a heuristic, and
less legibly. Stratification is the floor that makes a bad policy
degrade to today's behaviour instead of to silence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..state import Track

WEIGHTS_PATH = Path(__file__).with_name("party_policy.json")

_MODEL = None
_LOADED = False


def _load():
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    try:
        import numpy as np
    except ImportError:
        _MODEL = None
        return None
    if not WEIGHTS_PATH.is_file():
        _MODEL = None
        return None
    try:
        raw = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
        nets = {}
        for name, layers in raw["nets"].items():
            ordered = []
            index = 0
            while f"{index}.weight" in layers:
                ordered.append((np.array(layers[f"{index}.weight"]).T,
                                np.array(layers[f"{index}.bias"])))
                index += 2          # nn.Sequential: Linear, ReLU, Linear
            nets[name] = ordered
        _MODEL = {
            "np": np,
            "nets": nets,
            "track_order": [Track[t] for t in raw["track_order"]],
            "max_toons": raw["max_toons"],
            "max_cogs": raw["max_cogs"],
            "vmean": raw["vmean"], "vstd": raw["vstd"],
        }
    except (ValueError, KeyError, OSError):
        _MODEL = None
    return _MODEL


def available() -> bool:
    """Is a trained policy loadable? False means fall back, not fail."""
    return _load() is not None


def _mlp(np, layers, x, final_relu=False):
    for i, (W, b) in enumerate(layers):
        x = x @ W + b
        if final_relu or i < len(layers) - 1:
            x = np.maximum(x, 0.0)
    return x


def _encode_plans(model, plans, n_toons):
    """Same layout `tools/train_heads.encode_plan_features` produces.

    Kept deliberately close to the training encoder: a mismatch here
    would not raise, it would silently rank badly, which is the failure
    mode hardest to notice.
    """
    np = model["np"]
    tracks = model["track_order"]
    max_toons, max_cogs = model["max_toons"], model["max_cogs"]
    block = len(tracks) + 1 + 1 + max_cogs + 1
    out = np.zeros((len(plans), max_toons * block), dtype=np.float32)
    for pi, plan in enumerate(plans):
        for ti in range(max_toons):
            action = plan[ti] if ti < len(plan) else None
            base = ti * block
            if action is None:
                out[pi, base + block - 1] = 1.0
                continue
            try:
                out[pi, base + tracks.index(action.track)] = 1.0
            except ValueError:
                continue
            out[pi, base + len(tracks)] = action.level / 7.0
            if action.target_index is None:
                out[pi, base + len(tracks) + 1] = 1.0
            elif 0 <= action.target_index < max_cogs:
                out[pi, base + len(tracks) + 2 + action.target_index] = 1.0
    return out


def rank(state, plans, position_features) -> Optional[list]:
    """Scores for each plan, higher is better. None if unavailable.

    Returning None rather than raising is the point: every caller is
    expected to have a hand-written ranking to fall back to.
    """
    model = _load()
    if model is None or not plans:
        return None
    np = model["np"]
    try:
        pos = np.array([position_features], dtype=np.float32)
        h = _mlp(np, model["nets"]["trunk"], pos, final_relu=True)
        plan_x = _encode_plans(model, plans, len(state.toons))
        joined = np.concatenate(
            [np.repeat(h, len(plans), axis=0), plan_x], axis=1)
        return _mlp(np, model["nets"]["policy"], joined).reshape(-1).tolist()
    except (ValueError, KeyError, IndexError):
        return None


def value(state, position_features) -> Optional[float]:
    """The value head (P1), in the search's own units. None if absent."""
    model = _load()
    if model is None:
        return None
    np = model["np"]
    try:
        pos = np.array([position_features], dtype=np.float32)
        h = _mlp(np, model["nets"]["trunk"], pos, final_relu=True)
        raw = _mlp(np, model["nets"]["value"], h).reshape(-1)[0]
        return float(raw) * model["vstd"] + model["vmean"]
    except (ValueError, KeyError, IndexError):
        return None
