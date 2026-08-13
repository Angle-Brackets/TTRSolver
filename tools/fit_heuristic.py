"""Fit the leaf evaluator against exact values, offline.

    python tools/fit_heuristic.py --positions 400

Labels are ground truth, not bootstrapped estimates. Every action spends
a gag, so the state graph is a DAG and `expectimax.solve` plays a
position to the end of the battle exactly. That is unusual and it is the
main reason this is worth doing at all.

Needs numpy, which the solver core does not. Nothing here ships: the
output is a block of plain floats to paste into
`solver/search/fitted.py`, so inference stays pure standard library.

THE RISK THIS CANNOT DESIGN AWAY
--------------------------------
`solve` is only tractable on small positions, and small positions are
where the heuristic matters least, because the search reaches a terminal
state without ever consulting it. Anything fitted here has to extrapolate
to crowded fights with full pouches. `--holdout-big` scores a separate
sample of larger positions for exactly that reason; a model that wins on
training and loses there has not earned anything.

KEEPING IT FAST
---------------
The first version took about forty minutes, and nearly all of that was
positions that were never going to finish. Three things fix it.

Cost is governed by the *total gag count*, not by cogs: every action
spends a gag, so that number bounds the depth of the DAG. Measured, the
median position solves in 39ms, but timeouts go 1-in-40 at three gags,
1-in-5 at four, and 1-in-2 at six. Sampling within a gag cap avoids
paying a full second to discover a position is intractable.

Labelling is cached. Features are the part that gets iterated on, and
re-labelling to change a feature is pure waste -- the cache stores
positions and their exact values, so a refit after a feature change is
seconds rather than a coffee break.

And labelling parallelises perfectly, since positions are independent.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import data                                    # noqa: E402
from solver.search import expectimax, features             # noqa: E402
from solver.state import (                                 # noqa: E402
    BattleState, CogState, ToonState, Track,
)
from visualizer import bridge                              # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / ".heuristic_labels.json"

# Files whose contents determine what an exact label means. The cache key
# includes a digest of them, so changing the rules invalidates the labels
# instead of silently reusing values computed under the old ones.
#
# This is not hypothetical. Trap damage was being taken from the wrong end
# of its range; fixing it moved 1.75% of the cached labels by up to 10
# points, and nothing would have noticed -- the key was only the sample
# parameters.
RULE_FILES = [
    "solver/simulator.py", "solver/mechanics.py", "solver/outcomes.py",
    "solver/data/gags.py", "solver/data/cogs.py", "solver/data/accuracy.py",
]


def rules_digest() -> str:
    import hashlib

    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for name in RULE_FILES:
        h.update((root / name).read_bytes())
    return h.hexdigest()[:12]

KINDS = [("flunky", 1, 5), ("pencil_pusher", 2, 6), ("yesman", 3, 7),
         ("micromanager", 4, 8)]
GAGS = [(Track.THROW, 3), (Track.THROW, 4), (Track.THROW, 5),
        (Track.SQUIRT, 3), (Track.SQUIRT, 4), (Track.SQUIRT, 5),
        (Track.SOUND, 4), (Track.LURE, 3), (Track.TRAP, 3)]


# Cog counts per band. The hold-out band is wider than the training one
# on purpose: it is still exactly labelled, but larger than anything the
# model was fitted on, which is the extrapolation this whole approach is
# exposed to.
#
# NOT tightened for speed. An earlier version squeezed positions down to
# 2-4 gags against 2-3 cogs to cut labelling time, which made almost
# every sample hopeless and quietly changed what was being measured --
# the hand-written heuristic's bias fell from -81.7 to -13.3, not
# because it improved but because a toon with three gags against three
# cogs really is losing. Speed comes from parallelism and the cache, not
# from sampling positions nobody plays.
TRAIN_COGS = [1, 1, 2]
HOLDOUT_COGS = [1, 2, 2, 3]


def sample(rng, big=False):
    """A random position, drawn to resemble one a real fight reaches."""
    cogs = []
    for _ in range(rng.choice(HOLDOUT_COGS if big else TRAIN_COGS)):
        kind, lo, hi = rng.choice(KINDS)
        level = rng.randint(lo, hi)
        hp = data.cog_max_hp(level)
        cogs.append(CogState(kind, "bossbot", level,
                             rng.randint(max(1, hp // 5), hp), hp))
    picks = rng.sample(GAGS, rng.randint(2, 4) if big else rng.randint(2, 3))
    counts = {g: rng.randint(1, 3 if big else 2) for g in picks}
    toon = ToonState(rng.randint(8, 50), 50, {t: 6 for t, _l in counts},
                     counts)
    state = BattleState(toon=toon, cogs=cogs)
    # Sometimes hand it a position mid-fight rather than at the start.
    if rng.random() < 0.3 and cogs:
        target = rng.choice(cogs)
        if rng.random() < 0.5:
            target.status.apply_lure(60, rng.randint(1, 3), level=3)
        else:
            target.status.trapped = True
            target.status.trap_level = 3
            target.status.trap_track = Track.TRAP
    return state


def _label_one(payload):
    """Solve one position exactly, or report that it was too slow.

    Top-level so it can be sent to a worker process.
    """
    state_dict, budget = payload
    state = bridge.state_from_dict(state_dict)
    try:
        value, _move = expectimax.evaluate(
            state, 10 ** 6, memo={},
            deadline=[time.monotonic() + budget,
                      expectimax.DEADLINE_CHECK_INTERVAL])
    except expectimax.SearchTimeout:
        return None
    except (NotImplementedError, ValueError, RecursionError):
        return None
    return value


def labelled(rng, count, big=False, budget=1.0, workers=None):
    """(state_dict, exact value) pairs.

    Positions that outrun the budget are dropped rather than
    approximated, so every label is a true value. Labelling is
    independent per position, so it is farmed out to worker processes.
    """
    wanted = [bridge.state_to_dict(sample(rng, big=big))
              for _ in range(count * 2)]
    labels = []
    attempted = 0
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for state_dict, value in zip(
                wanted, pool.map(_label_one,
                                 [(d, budget) for d in wanted],
                                 chunksize=4)):
            if value is not None:
                labels.append((state_dict, value))
            attempted += 1
            if len(labels) >= count:
                break
    # Only count what was actually tried; the pool is handed twice the
    # target and the surplus is never attempted.
    return labels, attempted - len(labels)


def load_cache():
    if not CACHE.is_file():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_cache(payload):
    CACHE.write_text(json.dumps(payload), encoding="utf-8")


def as_rows(labels):
    """Turn cached (state, value) pairs into (features, value, state).

    Features are re-extracted here rather than cached, which is the
    whole point: changing the feature set must not mean re-labelling.
    """
    rows = []
    for state_dict, value in labels:
        state = bridge.state_from_dict(state_dict)
        rows.append((features.extract(state), value, state))
    return rows


def fit(rows):
    import numpy as np

    X = np.array([f for f, _v, _s in rows], dtype=float)
    y = np.array([v for _f, v, _s in rows], dtype=float)
    weights, *_ = np.linalg.lstsq(X, y, rcond=None)
    return weights


def score(rows, predict):
    """Bias, error, correlation and pairwise ordering against the truth.

    `predict=None` scores the hand-written heuristic, so both are
    measured the same way on the same rows.

    Deliberately `hand_written_value` and not `heuristic_value`: the
    latter dispatches to whatever weights are currently installed, so
    once a fit has shipped it would silently compare the new model
    against the old one instead of against the baseline. That happened.
    """
    if predict is None:
        preds = [expectimax.hand_written_value(s) for _f, _v, s in rows]
    else:
        preds = [predict(f) for f, _v, _s in rows]
    vals = [v for _f, v, _s in rows]
    errs = [p - v for p, v in zip(preds, vals)]
    mv, mp = statistics.mean(vals), statistics.mean(preds)
    sv, sp = statistics.pstdev(vals), statistics.pstdev(preds)
    cov = sum((p - mp) * (v - mv) for p, v in zip(preds, vals)) / len(rows)
    r = cov / (sv * sp) if sv and sp else 0.0
    ok = tot = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if abs(vals[i] - vals[j]) < 2:
                continue
            tot += 1
            ok += (preds[i] - preds[j]) * (vals[i] - vals[j]) > 0
    return {"bias": statistics.mean(errs),
            "mae": statistics.mean(abs(e) for e in errs),
            "r": r,
            "order": 100.0 * ok / tot if tot else 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--positions", type=int, default=500)
    parser.add_argument("--holdout-big", type=int, default=150)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=float, default=1.0,
                        help="seconds to spend solving one position "
                             "exactly before skipping it")
    parser.add_argument("--refresh", action="store_true",
                        help="re-label from scratch instead of using the "
                             "cache")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    cache = {} if args.refresh else load_cache()
    key = (f"{args.seed}:{args.positions}:{args.holdout_big}:{args.budget}"
           f":{rules_digest()}")
    entry = cache.get(key)

    if entry:
        print(f"reusing {len(entry['train'])} train and "
              f"{len(entry['holdout'])} hold-out labels from {CACHE.name}")
        train_labels = [(d, v) for d, v in entry["train"]]
        holdout_labels = [(d, v) for d, v in entry["holdout"]]
    else:
        if cache:
            print(f"{CACHE.name} holds labels for other rule versions; "
                  f"the game rules have changed, so re-labelling")
        started = time.time()
        print(f"labelling {args.positions} train positions "
              f"with exact solve()...")
        train_labels, skipped_a = labelled(
            random.Random(args.seed), args.positions,
            budget=args.budget, workers=args.workers)
        print(f"  {len(train_labels)} labelled, {skipped_a} too slow")

        print(f"labelling {args.holdout_big} LARGER hold-out "
              f"positions...")
        holdout_labels, skipped_b = labelled(
            random.Random(args.seed + 1), args.holdout_big, big=True,
            budget=args.budget, workers=args.workers)
        print(f"  {len(holdout_labels)} labelled, {skipped_b} too slow")
        print(f"  labelling took {time.time() - started:.0f}s")

        cache[key] = {"train": train_labels, "holdout": holdout_labels}
        save_cache(cache)
        print(f"  cached to {CACHE.name} -- refits are now instant")

    train = as_rows(train_labels)
    holdout = as_rows(holdout_labels)
    if not train:
        print("no training positions; nothing to fit")
        return 1

    weights = fit(train)
    predict = lambda f: float(sum(w * x for w, x in zip(weights, f)))

    print(f"\n{'':>20} {'bias':>8} {'MAE':>7} {'r':>6} {'ordering':>9}")
    for tag, rows in (("train", train), ("HOLD-OUT (bigger)", holdout)):
        if not rows:
            print(f"  {tag:>17}   (no positions)")
            continue
        hand = score(rows, None)
        got = score(rows, predict)
        print(f"  {tag:>17}")
        print(f"    hand-written {hand['bias']:>8.1f} {hand['mae']:>7.1f} "
              f"{hand['r']:>6.2f} {hand['order']:>8.0f}%")
        print(f"    fitted       {got['bias']:>8.1f} {got['mae']:>7.1f} "
              f"{got['r']:>6.2f} {got['order']:>8.0f}%")

    print("\nPaste into solver/search/fitted.py:\n")
    print("WEIGHTS = [")
    for name, w in zip(features.FEATURE_NAMES, weights):
        print(f"    {w:>12.5f},   # {name}")
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
