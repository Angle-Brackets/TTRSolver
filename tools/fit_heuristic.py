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
"""
import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import data                                    # noqa: E402
from solver.search import expectimax, features             # noqa: E402
from solver.state import (                                 # noqa: E402
    BattleState, CogState, ToonState, Track,
)

KINDS = [("flunky", 1, 5), ("pencil_pusher", 2, 6), ("yesman", 3, 7),
         ("micromanager", 4, 8)]
GAGS = [(Track.THROW, 3), (Track.THROW, 4), (Track.THROW, 5),
        (Track.SQUIRT, 3), (Track.SQUIRT, 4), (Track.SQUIRT, 5),
        (Track.SOUND, 4), (Track.LURE, 3), (Track.TRAP, 3)]


def sample(rng, big=False):
    """A random position. `big` widens it past what solve() can label."""
    n_cogs = rng.choice([1, 2, 2, 3]) if big else rng.choice([1, 1, 2])
    cogs = []
    for _ in range(n_cogs):
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


def labelled(rng, count, big=False, budget=3.0):
    """(features, true value) pairs, skipping anything unlabelable.

    Each position gets a deadline. `solve` plays to the end of the
    battle, which is exact but only tractable while the pouch is small --
    the first version of this hung on the larger hold-out sample, which
    is the whole risk of the approach showing up immediately. Positions
    that outrun the budget are dropped rather than approximated, so every
    label here is a true value.
    """
    import time as _time

    rows = []
    attempts = skipped = 0
    while len(rows) < count and attempts < count * 10:
        attempts += 1
        state = sample(rng, big=big)
        try:
            value, _move = expectimax.evaluate(
                state, 10 ** 6, memo={},
                deadline=[_time.monotonic() + budget,
                          expectimax.DEADLINE_CHECK_INTERVAL])
        except expectimax.SearchTimeout:
            skipped += 1
            continue
        except (NotImplementedError, ValueError, RecursionError):
            continue
        rows.append((features.extract(state), value, state))
    if skipped:
        print(f"    ({skipped} positions skipped as too slow to solve exactly)")
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
    """
    if predict is None:
        preds = [expectimax.heuristic_value(s) for _f, _v, s in rows]
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
    parser.add_argument("--positions", type=int, default=300)
    parser.add_argument("--holdout-big", type=int, default=120)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--budget", type=float, default=1.0,
                        help="seconds to spend solving one "
                             "position exactly before skipping it")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    print(f"labelling {args.positions} small positions with exact solve()...")
    train = labelled(rng, args.positions, budget=args.budget)
    print(f"  got {len(train)}")
    print(f"labelling {args.holdout_big} LARGER hold-out positions...")
    holdout = labelled(random.Random(args.seed + 1), args.holdout_big,
                       big=True, budget=args.budget)
    print(f"  got {len(holdout)}")

    weights = fit(train)
    predict = lambda f: float(sum(w * x for w, x in zip(weights, f)))
    old = lambda f, rows=None: None

    print("\n                    bias    MAE      r   ordering")
    for tag, rows in (("train", train), ("HOLD-OUT (bigger)", holdout)):
        hand = score(rows, lambda _f, r=rows: 0.0)   # placeholder, replaced
        # Score the hand-written heuristic on the same rows.
        hand_rows = [(features.extract(s), v, s) for _f, v, s in rows]
        h = score(hand_rows, lambda f, rows=rows: 0.0)
        old_scores = {
            "bias": statistics.mean(
                expectimax.heuristic_value(s) - v for _f, v, s in rows),
            "mae": statistics.mean(
                abs(expectimax.heuristic_value(s) - v) for _f, v, s in rows),
        }
        f = score(rows, predict)
        print(f"  {tag:>17}")
        print(f"    hand-written  {old_scores['bias']:>7.1f} "
              f"{old_scores['mae']:>6.1f}")
        print(f"    fitted        {f['bias']:>7.1f} {f['mae']:>6.1f} "
              f"{f['r']:>6.2f} {f['order']:>8.0f}%")

    print("\nPaste into solver/search/fitted.py:\n")
    print("WEIGHTS = [")
    for name, w in zip(features.FEATURE_NAMES, weights):
        print(f"    {w:>12.5f},   # {name}")
    print("]")


if __name__ == "__main__":
    main()
