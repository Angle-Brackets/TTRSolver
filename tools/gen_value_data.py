"""Label boards with what a deep search says they are worth, for `valuenet`.

    python tools/gen_value_data.py --episodes 4000 --out value_r1.pkl
    python tools/gen_value_data.py --episodes 4000 --out value_r2.pkl --leaf value_r1.json

Boards come from street battles, solo buildings, the owner's own building
toon and solo VPs; the fast network plays some rounds first so the boards
carry lures, traps, spent pouches and lower laff (a VP's boards are
spread over its waves). Each is seen as the panel
sees it (`playout._view`: no holdout) and labelled by
`expectimax.best_action_iterative` -- depth 5/4/4/3 for 1/2/3/4 cogs,
damage collapse (`exact_plies=0`), `BEAM` 6, an 8-second cap -- which on the
benchmark picks the move fully exact search picks.

`--leaf` labels with a trained value network at the search's leaves instead
of the fitted model: the ladder's next rung.

Rows: {"x": features, "y": label, "fitted": the fitted leaf's value,
"cogs": alive, "regime": source, "state": the board, pickled}.
"""
from __future__ import annotations

import argparse
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REGIMES = ("street", "solo-building", "my-building", "solo-vp")
DEPTH_BY_COGS = {1: 5, 2: 4, 3: 4, 4: 3}
BUDGET = 8.0


def _start(regime, rng):
    from solver.rl import env as env_mod

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sweep import _sampler

    if regime == "street":
        def sample(r):
            st = env_mod.BattleEnv(rng=r).sampler(r)
            st.toons = st.toons[:1]
            return st
        cap = 20
    else:
        sample, _coord, cap = _sampler(regime)
    env = env_mod.BattleEnv(rng=rng, sampler=sample, coordinated=True, max_rounds=cap)
    env.reset()
    return env


def episode(job):
    seed, leaf = job
    from solver.search import expectimax, fastplayer, fitted, objective, playout, valuenet

    if leaf:
        valuenet.use(leaf)
        valuenet.USE = True
    rng = random.Random(seed)
    regime = REGIMES[seed % len(REGIMES)]
    try:
        env = _start(regime, rng)
    except Exception:                       # noqa: BLE001 -- an unbuildable draw
        return []
    rows = []
    # When to take a board: early for short fights, spread over the
    # waves for a VP (about 45 rounds solo).
    targets = sorted(rng.sample(range(0, 40 if regime == "solo-vp" else 6), 3))
    played = 0
    for target in targets:
        done = False
        while played < target and not done:
            try:
                done, _ = playout.step_round(env, fastplayer.act(
                    playout._view(env.state), holdout=len(env.state.holdout)))
            except Exception:               # noqa: BLE001
                return rows
            played += 1
        if done or env.state.is_terminal():
            break
        view = playout._view(env.state)
        cogs = sum(1 for c in view.cogs if not c.status.is_dead)
        if not cogs:
            continue
        expectimax.BEAM = 6
        try:
            value, action = expectimax.best_action_iterative(
                view.clone(), depth=DEPTH_BY_COGS.get(cogs, 3),
                objective=objective.BALANCED, time_budget=BUDGET, exact_plies=0)
        except Exception:                   # noqa: BLE001 -- a data gap: skip the board
            continue
        finally:
            expectimax.BEAM = None
        if action is None:
            continue
        rows.append({"x": fastplayer.features(view)[0], "y": float(value),
                     "fitted": float(fitted.value(view)), "cogs": cogs,
                     "regime": regime, "state": pickle.dumps(view)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes", type=int, default=4000)
    ap.add_argument("--base", type=int, default=700000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--leaf", default="", help="value-net weights for the leaves")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    jobs = [(args.base + i, args.leaf) for i in range(args.episodes)]
    rows, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, got in enumerate(pool.map(episode, jobs, chunksize=2)):
            rows.extend(got)
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(jobs)} episodes, {len(rows)} boards, "
                      f"{time.time() - t0:.0f}s", flush=True)
                pickle.dump(rows, open(args.out, "wb"))
    pickle.dump(rows, open(args.out, "wb"))
    print(f"{len(rows)} labelled boards written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
