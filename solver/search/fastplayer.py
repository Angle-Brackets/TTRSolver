"""A fast stand-in for `climb`, to play out the rest of a fight.

WHY. 91% of a playout's time is `hybrid.climb` choosing each later
round (2.3 ms a decision: ~33 one-round scores, probes, the unite check).
A small network trained to copy `climb` decides in a fraction of that --
the "rollout policy" of AlphaGo: a fast imitation of a slower, stronger
player, used where volume matters more than the last bit of quality.

It is NOT the PPO policy. PPO alone plays a solo VP badly (0/400); this
imitates `climb`, which is PPO plus the scorer plus the probes, and adds
the SOS cards PPO's action space has no slot for.

Features: `env.encode` (current layout) plus how many of each SOS card
are held. Outputs: the 250 env actions plus one per SOS card in
`sos.BY_NAME`, masked to what is legal and held.

Needs numpy. `available()` is False when it or the weights are missing,
and callers keep using `climb`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from ..state import Action, BattleState

DEFAULT_WEIGHTS = Path(__file__).resolve().parents[1] / "rl" / "fast_player.json"

_MODEL = None
_PATH: Optional[Path] = None


def sos_names() -> List[str]:
    from .. import sos as sos_mod
    return sorted(sos_mod.BY_NAME)


def n_outputs() -> int:
    from ..rl import env as env_mod
    return len(env_mod.ACTIONS) + len(sos_names())


def features(state: BattleState) -> Tuple[List[float], List[bool]]:
    """(input vector, legal mask) for seat 0."""
    from ..rl import env as env_mod

    x = list(env_mod.encode(state, 0, [None] * len(state.toons)))
    held = getattr(state.toons[0], "sos_cards", None) or {}
    names = sos_names()
    x += [min(int(held.get(n, 0)), 3) / 3.0 for n in names]
    mask = list(env_mod.legal_mask(state, 0))
    mask += [int(held.get(n, 0)) > 0 for n in names]
    return x, mask


def index_of(action) -> int:
    """The output index for `action`, or -1 when it has none."""
    from ..rl import env as env_mod

    if action is None or action.is_pass:
        return env_mod.PASS_INDEX
    if getattr(action, "sos", None):
        names = sos_names()
        return (len(env_mod.ACTIONS) + names.index(action.sos)
                if action.sos in names else -1)
    if action.fire:
        return env_mod._FIRE_INDEX.get(action.target_index, -1)
    for i, cand in enumerate(env_mod.ACTIONS):
        if (cand is not None and not cand.fire and cand.track == action.track
                and cand.level == action.level
                and cand.target_index == action.target_index):
            return i
    return -1


def action_of(index: int) -> Action:
    from ..rl import env as env_mod

    if index >= len(env_mod.ACTIONS):
        return Action(track=None, sos=sos_names()[index - len(env_mod.ACTIONS)])
    entry = env_mod.ACTIONS[index]
    return entry if entry is not None else Action(track=None)


def use(path) -> bool:
    """Load weights from `path` (an export of `tools/train_fast_player.py`)."""
    global _MODEL, _PATH
    path = Path(path)
    if _PATH == path and _MODEL is not None:
        return True
    try:
        import numpy as np

        payload = json.loads(path.read_text(encoding="utf-8"))
        layers = [(np.array(w, dtype=float), np.array(b, dtype=float))
                  for w, b in payload["layers"]]
    except Exception:                       # noqa: BLE001 -- unusable, not fatal
        _MODEL, _PATH = None, path
        return False
    if layers[0][0].shape[0] != len(features_dim_probe()) or \
            layers[-1][0].shape[1] != n_outputs():
        _MODEL, _PATH = None, path
        return False
    _MODEL, _PATH = layers, path
    return True


def features_dim_probe() -> List[float]:
    """A zero vector of the input width, for shape checks."""
    from ..rl import env as env_mod
    return [0.0] * (env_mod.OBS_DIM + len(sos_names()))


def available() -> bool:
    if _MODEL is None and _PATH is None:
        use(DEFAULT_WEIGHTS)
    return _MODEL is not None


def act(state: BattleState) -> List[Optional[Action]]:
    """A one-seat plan: the network's best legal move."""
    import numpy as np

    if not available():
        raise RuntimeError("no fast player weights")
    x, mask = features(state)
    h = np.array(x, dtype=float)
    for i, (w, b) in enumerate(_MODEL):
        h = h @ w + b
        if i < len(_MODEL) - 1:
            h = np.tanh(h)
    h = np.where(np.array(mask), h, -np.inf)
    return [action_of(int(np.argmax(h)))]
