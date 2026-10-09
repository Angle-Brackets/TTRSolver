"""A learned leaf for the exact search: a board's value, as deep search sees it.

`expectimax` scores the boards at its depth cutoff with `heuristic_value`
(the fitted linear model, or the hand-written one). Its move stops changing
by depth 4 on single battles, so what is left to gain is the leaf, not the
depth. This network is trained to reproduce what a DEEP search says a board
is worth (`tools/gen_value_data.py`, `tools/train_value_net.py`), so a
shallow search with it at the leaves can play like a deeper one.

Inputs are `fastplayer.features` (the board, the pouch, slips, SOS cards,
unites); the output is on the search's own scale (value of what is still
to come, a win +100), clamped to [FLOOR, +100] so star1's bounds stay
admissible (`value_floor`).

Off unless `USE` is set and weights load -- `heuristic_value` asks this
module first only then. Needs numpy; `available()` is False without it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..state import BattleState

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "rl" / "value_net.json"

USE = False                 # route `heuristic_value` here when True
_MODEL = None
_PATH: Optional[Path] = None
_CACHE: dict = {}           # leaf values by state key; leaves repeat


def use(path=None) -> bool:
    """Load weights (default `DEFAULT_WEIGHTS`). True on success."""
    global _MODEL, _PATH
    path = Path(path or DEFAULT_WEIGHTS)
    if _PATH == path and _MODEL is not None:
        return True
    _CACHE.clear()
    try:
        import numpy as np

        payload = json.loads(path.read_text(encoding="utf-8"))
        layers = [(np.array(w, dtype=float), np.array(b, dtype=float))
                  for w, b in payload["layers"]]
        scale = float(payload.get("scale", 100.0))
    except Exception:                       # noqa: BLE001 -- unusable, not fatal
        _MODEL, _PATH = None, path
        return False
    _MODEL, _PATH = (layers, scale), path
    return True


def active() -> bool:
    return USE and (_MODEL is not None or use())


# Whole-fight returns (`tools/gen_value_outcomes.py`) reach far below the
# fitted model's floor -- a solo VP board can be worth -560: every point of
# laff lost over 40 cogs, then the loss. The clamp keeps star1's bounds
# admissible; star2's probes set the floors that actually prune, so a low
# one costs little (docs/experiment-log.md).
FLOOR = -3000.0


def value_floor(state: BattleState) -> float:
    """The lowest `value` can return -- star1 relies on it."""
    return FLOOR


def raw(state: BattleState) -> float:
    """The network's estimate, unclamped, for a non-terminal board."""
    import numpy as np
    from . import fastplayer

    layers, scale = _MODEL
    x, _mask = fastplayer.features(state)
    h = np.array(x, dtype=float)
    for i, (w, b) in enumerate(layers):
        h = h @ w + b
        if i < len(layers) - 1:
            h = np.tanh(h)
    return float(h[0]) * scale


def value(state: BattleState) -> float:
    """The leaf value: terminal boards are known, the rest estimated and
    clamped into star1's envelope."""
    from .. import outcomes
    from .expectimax import LOSS_VALUE, WIN_VALUE

    if state.is_win():
        return WIN_VALUE
    if state.is_terminal():
        return LOSS_VALUE
    key = outcomes.state_key(state)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    v = min(WIN_VALUE, max(value_floor(state), raw(state)))
    if len(_CACHE) > 500_000:
        _CACHE.clear()
    _CACHE[key] = v
    return v
