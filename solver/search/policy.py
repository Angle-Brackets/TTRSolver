"""The trained party value head (P1): a position's worth, for a search leaf.

`party_search.evaluate(leaf="learned")` scores a leaf with it instead of
playing a rollout -- a forward pass is ~10x quicker. Trained by
`tools/train_heads.py`.

A policy head (P0) that ranked plans for the shortlist lived here too. It
beat `_quick_score` on held-out regret@6 (3.22 vs 9.93) and lost in play at
every shortlist size -- the labels were too noisy to rank by (docs/scoring.md
has the measurements) -- so it was removed.

Optional, like `live/vision.py`: needs numpy, and `available()` returns
False rather than raising, so the core and the tests run without it.
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
