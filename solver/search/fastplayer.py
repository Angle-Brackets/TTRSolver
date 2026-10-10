"""A fast stand-in for `climb`, to play out the rest of a fight.

WHY. 91% of a playout's time is `hybrid.climb` choosing each later
round (2.3 ms a decision: ~33 one-round scores, probes, the unite check).
A small network trained to copy `climb` decides in a fraction of that --
the "rollout policy" of AlphaGo: a fast imitation of a slower, stronger
player, used where volume matters more than the last bit of quality.

It is NOT the PPO policy. PPO alone plays a solo VP badly (0/400); this
imitates `climb`, which is PPO plus the scorer plus the probes, and adds
the SOS cards PPO's action space has no slot for.

Features: `env.encode` (current layout -- it carries the pouch and the
slips held), how many of each SOS card are held, and the unites held and
their cooldown. Outputs: the env actions plus one per SOS card in
`sos.BY_NAME`, masked to what is legal and held -- and a second head for
the unite opening the round (`UNITE_SLOTS`), masked to
`unites.candidates`. The network sees everything a toon could carry; the
loadout decides what it may pick.

THE UNITE COMES FIRST, as in the game and in `climb`: the unite head
reads the board as it is, and the action head reads it after the unite.
Weights without a unite head (`"unite"` absent) never use one.

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
_UNITE = None
_PATH: Optional[Path] = None

# Unites held are scaled against this; more than it reads as "plenty".
UNITES_SCALE = 5.0


def unite_slots() -> List[tuple]:
    """The unite head's outputs: none, the five Toon-Up values by ORDINAL
    (the toon's own game says which numbers -- TTR's and Realms' differ),
    Gag-Up all tracks, then Gag-Up per track."""
    from ..rl import env as env_mod
    return ([None] + [("toon_up", i) for i in range(5)] + [("gag_up", None)]
            + [("gag_up", t) for t in env_mod.TRACKS])


def _slot_of(toon, choice) -> int:
    """The unite head's index for a `unites.candidates` pair, or -1."""
    from .. import unites as unites_mod

    if choice is None:
        return 0
    kind, arg = choice
    if kind == "toon_up":
        values = unites_mod.toon_up_values(toon)
        return 1 + values.index(arg) if arg in values else -1
    try:
        return unite_slots().index(("gag_up", arg))
    except ValueError:
        return -1


def _choice_of(toon, slot: int):
    from .. import unites as unites_mod

    entry = unite_slots()[slot]
    if entry is None:
        return None
    kind, arg = entry
    if kind == "toon_up":
        return ("toon_up", unites_mod.toon_up_values(toon)[arg])
    return entry


def unite_mask(state: BattleState) -> List[bool]:
    """Which unite slots this toon may use now: always "none", and every
    option `unites.candidates` offers (held, off cooldown, worth it)."""
    from .. import unites as unites_mod

    mask = [False] * len(unite_slots())
    mask[0] = True
    if state.toons:
        toon = state.toons[0]
        for choice in unites_mod.candidates(toon):
            slot = _slot_of(toon, choice)
            if slot > 0:
                mask[slot] = True
    return mask


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
    toon = state.toons[0]
    names = sos_names()
    held = {n: toon.sos_held(n) for n in names}
    x += [min(int(held[n]), 3) / 3.0 for n in names]
    x += [min(int(getattr(toon, "unites_held", 0)), UNITES_SCALE) / UNITES_SCALE,
          int(getattr(toon, "unite_cooldown", 0)) / 3.0]
    mask = list(env_mod.legal_mask(state, 0))
    mask += [int(held[n]) > 0 for n in names]
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
    global _MODEL, _UNITE, _PATH
    path = Path(path)
    if _PATH == path and _MODEL is not None:
        return True
    try:
        import numpy as np

        payload = json.loads(path.read_text(encoding="utf-8"))
        layers = [(np.array(w, dtype=float), np.array(b, dtype=float))
                  for w, b in payload["layers"]]
        unite = payload.get("unite")
        unite = (None if unite is None else
                 (np.array(unite[0], dtype=float), np.array(unite[1], dtype=float)))
    except Exception:                       # noqa: BLE001 -- unusable, not fatal
        _MODEL, _UNITE, _PATH = None, None, path
        return False
    width = len(features_dim_probe())
    if layers[0][0].shape[0] == width - 2:
        # Weights from before the unite inputs: zero rows for them keep
        # the network exactly as trained, blind to unites.
        w0, b0 = layers[0]
        layers[0] = (np.vstack([w0, np.zeros((2, w0.shape[1]))]), b0)
    if layers[0][0].shape[0] != len(features_dim_probe()) or \
            layers[-1][0].shape[1] != n_outputs() or             (unite is not None and unite[0].shape[1] != len(unite_slots())):
        _MODEL, _UNITE, _PATH = None, None, path
        return False
    _MODEL, _UNITE, _PATH = layers, unite, path
    return True


def features_dim_probe() -> List[float]:
    """A zero vector of the input width, for shape checks."""
    from ..rl import env as env_mod
    return [0.0] * (env_mod.OBS_DIM + len(sos_names()) + 2)


def available() -> bool:
    if _MODEL is None and _PATH is None:
        use(DEFAULT_WEIGHTS)
    return _MODEL is not None


def _trunk(x):
    import numpy as np

    h = np.array(x, dtype=float)
    for w, b in _MODEL[:-1]:
        h = np.tanh(h @ w + b)
    return h


def choose_unite(state: BattleState):
    """The unite to open this round with, or None."""
    import numpy as np

    if _UNITE is None or not state.toons:
        return None
    mask = unite_mask(state)
    if not any(mask[1:]):
        return None
    x, _ = features(state)
    w, b = _UNITE
    logits = np.where(np.array(mask), _trunk(x) @ w + b, -np.inf)
    return _choice_of(state.toons[0], int(np.argmax(logits)))


def ranked(state: BattleState, k: int = 4) -> List[Tuple[list, float]]:
    """The network's top `k` legal one-seat plans with their probabilities
    (renormalised over the k), each carrying the unite it opens with.
    The move head reads the board after the unite, as `act` does."""
    import numpy as np
    from .. import unites as unites_mod
    from .playout import with_unite

    if not available():
        raise RuntimeError("no fast player weights")
    unite = choose_unite(state)
    board = state
    if unite is not None:
        board = state.clone()
        unites_mod.apply(board.toons[0], unite)
    x, mask = features(board)
    w, b = _MODEL[-1]
    logits = np.where(np.array(mask), _trunk(x) @ w + b, -np.inf)
    order = [int(i) for i in np.argsort(-logits)[:k] if np.isfinite(logits[i])]
    if not order:
        return []
    top = np.array([logits[i] for i in order])
    probs = np.exp(top - top.max())
    probs /= probs.sum()
    return [(with_unite([action_of(i)], unite), float(p)) for i, p in zip(order, probs)]


def act(state: BattleState) -> List[Optional[Action]]:
    """A one-seat plan: the network's best legal move, carrying the unite
    it opens with (`playout.Plan`). `state` is not changed."""
    import numpy as np
    from .. import unites as unites_mod
    from .playout import with_unite

    if not available():
        raise RuntimeError("no fast player weights")
    unite = choose_unite(state)
    board = state
    if unite is not None:
        board = state.clone()
        unites_mod.apply(board.toons[0], unite)
    x, mask = features(board)
    w, b = _MODEL[-1]
    h = np.where(np.array(mask), _trunk(x) @ w + b, -np.inf)
    return with_unite([action_of(int(np.argmax(h)))], unite)
