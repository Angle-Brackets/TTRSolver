"""Does a shallow search with the value network play like the deep one?

    python tools/value_eval.py --data value_r1.pkl --net value_r1.json --n 200

Takes boards the network did NOT train on (the tail of the shuffled data,
the same split `train_value_net.py` holds out) and, for each, the move the
deep labelling search picks (depth 5/4/4/3 by cogs, collapse, BEAM 6, fitted
leaf). Then reports how often depth 1, 2 and 3 pick that move with the
fitted leaf and with the network at the leaves, and how long each took.
"""
from __future__ import annotations

import argparse
import pickle
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def search(state, depth, leaf_net: bool, budget=30.0):
    from solver.search import expectimax, objective, valuenet

    valuenet.USE = leaf_net
    expectimax.BEAM = 6
    try:
        t0 = time.perf_counter()
        _v, action = expectimax.best_action_iterative(
            state.clone(), depth=depth, objective=objective.BALANCED,
            time_budget=budget, exact_plies=0)
        return repr(action), time.perf_counter() - t0
    finally:
        expectimax.BEAM = None
        valuenet.USE = False


def job(args):
    blob, net, depths = args
    from solver.search import valuenet

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gen_value_data import DEPTH_BY_COGS

    valuenet.use(net)
    state = pickle.loads(blob)
    cogs = sum(1 for c in state.cogs if not c.status.is_dead)
    ref, _t = search(state, DEPTH_BY_COGS.get(cogs, 3), False, budget=60.0)
    out = {"cogs": cogs}
    for d in depths:
        for leaf in (False, True):
            move, t = search(state, d, leaf)
            out[(d, leaf)] = (move == ref, t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--holdout", type=float, default=0.1)
    ap.add_argument("--depths", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    rows = pickle.load(open(args.data, "rb"))
    random.Random(0).shuffle(rows)                   # the training split
    hold = rows[int(len(rows) * (1 - args.holdout)):][:args.n]
    jobs = [(r["state"], args.net, args.depths) for r in hold]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(job, jobs, chunksize=2))
    print(f"  {len(results)} held-out boards; same move as the deep search:")
    for d in args.depths:
        for leaf in (False, True):
            hits = [r[(d, leaf)][0] for r in results]
            secs = [r[(d, leaf)][1] for r in results]
            print(f"    depth {d}, {'network' if leaf else 'fitted '} leaf: "
                  f"{100 * sum(hits) / len(hits):5.1f}%   mean {statistics.mean(secs):.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
