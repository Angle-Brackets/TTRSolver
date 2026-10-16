"""Rewrite training rows from board encoding 4 to 5 (the lure input).

    python tools/reencode_lure.py IN.pkl OUT.pkl

Version 5 changes one input per cog slot: a lured cog's
`min(rounds left, 8) / 8` becomes `env.lure_safety(rounds left)`. The
conversion is EXACT for TTR-rule data, because no TTR lure lasts more than
8 rounds, so the old value never saturated and `round(value * 8)` recovers
the rounds left. Rows written under longer lures (Realms rules) cannot be
converted this way and must be generated at version 5 instead
(`gen_*.py --obs-version 5`).

Handles both row shapes the data tools write: tuples whose first float
list is the input vector (`gen_fast_player_data.py`, including
("unite", x, ...) rows), and dicts with an "x" key (`gen_value_*.py`).
Where a dict row carries its pickled board ("state"), the converted input
is checked against encoding the board directly at version 5.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod  # noqa: E402

# One lure input per cog slot: found by encoding a board at both versions
# and diffing (`env.encode`), so a layout change shows up as a failed check
# rather than silently converting the wrong inputs.
LURE_SLOTS = tuple(8 + 11 * i for i in range(env_mod.MAX_COGS))


def _convert(x: list) -> list:
    x = list(x)
    for i in LURE_SLOTS:
        rounds = int(round(float(x[i]) * 8))
        x[i] = env_mod.lure_safety(rounds) if rounds > 0 else 0.0
    return x


def convert_row(row):
    if isinstance(row, dict):
        out = dict(row)
        out["x"] = _convert(row["x"])
        return out
    items = list(row)
    for k, item in enumerate(items):
        if isinstance(item, (list, tuple)) and len(item) >= env_mod.OBS_DIM \
                and all(isinstance(v, (int, float)) for v in item[:4]):
            items[k] = _convert(item)
            break
    return type(row)(items) if isinstance(row, tuple) else items


def check_slots() -> None:
    """The slots really are the lure inputs at the current layout."""
    from solver import data
    from solver.state import BattleState, CogState, ToonState, Track

    toon = ToonState(80, 100, {Track.THROW: 7}, {(Track.THROW, 5): 3})
    found = []
    for slot in range(env_mod.MAX_COGS):
        cogs = []
        for i in range(env_mod.MAX_COGS):
            hp = data.cog_max_hp(6)
            cog = CogState("name_dropper", "sellbot", 6, hp, hp)
            if i == slot:
                cog.status.apply_lure(90, 3, level=5)
            cogs.append(cog)
        board = BattleState(toons=[toon], cogs=cogs)
        a = env_mod.encode(board, obs_version=4)
        b = env_mod.encode(board, obs_version=5)
        found += [k for k in range(len(a)) if a[k] != b[k]]
    if tuple(found) != LURE_SLOTS:
        raise SystemExit(f"lure inputs moved: {found} != {LURE_SLOTS}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inp")
    ap.add_argument("out")
    args = ap.parse_args()
    check_slots()
    rows = pickle.load(open(args.inp, "rb"))
    out = [convert_row(r) for r in rows]
    checked = mismatched = 0
    for before, after in zip(rows, out):
        if isinstance(before, dict) and before.get("state"):
            board = pickle.loads(before["state"])
            direct = list(env_mod.encode(board, 0, [None] * len(board.toons),
                                         obs_version=5))
            checked += 1
            if any(abs(p - q) > 1e-9 for p, q in zip(direct, after["x"][:len(direct)])):
                mismatched += 1
    pickle.dump(out, open(args.out, "wb"))
    print(f"{len(out)} rows rewritten to encoding 5 -> {args.out}"
          + (f"; checked {checked} against their boards, {mismatched} differ"
             if checked else ""))
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
