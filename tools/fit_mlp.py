"""Fit a small MLP against the same exact labels as the linear model.

    python tools/fit_mlp.py

Design proposal S1 in docs/ml-design.md. The question it answers is
narrow and worth stating: **does learned function approximation buy
anything here at all?** If an MLP cannot beat the linear model given
EXACT labels on the same features, reinforcement learning is not going
to rescue the party case, where there are no labels at all.

Reuses `tools/fit_heuristic.py` wholesale -- the same cache, the same
`as_rows`, the same `score`. That is deliberate: the comparison is only
meaningful if both models see identical labels, identical features and
identical scoring. A new harness would be a new place for the two to
diverge.

Numpy only, no torch. The network is tiny and the dataset is 5,000 rows;
a framework would add a dependency for nothing. Training lives here in
`tools/` and never in `solver/`, same rule as `fit_heuristic`: whatever
ships must be plain floats so inference stays standard-library only.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fit_heuristic as fh                                    # noqa: E402


def standardise(X, mean=None, std=None):
    import numpy as np

    if mean is None:
        mean, std = X.mean(axis=0), X.std(axis=0)
        std[std < 1e-9] = 1.0
    return (X - mean) / std, mean, std


def train(X, y, hidden=(64, 32), epochs=4000, lr=3e-3, seed=0,
          weight_decay=1e-5):
    """Plain MLP, tanh hidden, linear output, full-batch Adam.

    Full batch because 5,000 x 17 is nothing, and it makes the run
    deterministic given the seed -- which matters here, since the whole
    point is a like-for-like comparison against a closed-form fit.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    sizes = [X.shape[1]] + list(hidden) + [1]
    Ws, bs = [], []
    for a, b in zip(sizes, sizes[1:]):
        # He-ish init, scaled for tanh.
        Ws.append(rng.normal(0, (1.0 / a) ** 0.5, size=(a, b)))
        bs.append(np.zeros(b))

    mW = [np.zeros_like(w) for w in Ws]
    vW = [np.zeros_like(w) for w in Ws]
    mb = [np.zeros_like(b) for b in bs]
    vb = [np.zeros_like(b) for b in bs]
    b1, b2, eps = 0.9, 0.999, 1e-8
    yv = y.reshape(-1, 1)

    for step in range(1, epochs + 1):
        acts = [X]
        for i, (W, b) in enumerate(zip(Ws, bs)):
            z = acts[-1] @ W + b
            acts.append(np.tanh(z) if i < len(Ws) - 1 else z)

        pred = acts[-1]
        err = pred - yv
        grad = 2.0 * err / len(X)

        gW, gb = [None] * len(Ws), [None] * len(bs)
        for i in range(len(Ws) - 1, -1, -1):
            gW[i] = acts[i].T @ grad + weight_decay * Ws[i]
            gb[i] = grad.sum(axis=0)
            if i:
                grad = (grad @ Ws[i].T) * (1.0 - acts[i] ** 2)

        for i in range(len(Ws)):
            mW[i] = b1 * mW[i] + (1 - b1) * gW[i]
            vW[i] = b2 * vW[i] + (1 - b2) * gW[i] ** 2
            mb[i] = b1 * mb[i] + (1 - b1) * gb[i]
            vb[i] = b2 * vb[i] + (1 - b2) * gb[i] ** 2
            mh = mW[i] / (1 - b1 ** step)
            vh = vW[i] / (1 - b2 ** step)
            Ws[i] -= lr * mh / (np.sqrt(vh) + eps)
            mh = mb[i] / (1 - b1 ** step)
            vh = vb[i] / (1 - b2 ** step)
            bs[i] -= lr * mh / (np.sqrt(vh) + eps)

    return Ws, bs


def predictor(Ws, bs, mean, std):
    import numpy as np

    def predict(features):
        a = (np.array(features, dtype=float) - mean) / std
        for i, (W, b) in enumerate(zip(Ws, bs)):
            a = a @ W + b
            if i < len(Ws) - 1:
                a = np.tanh(a)
        return float(a[0])

    return predict


def main():
    import numpy as np

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hidden", type=int, nargs="+", default=[64, 32])
    ap.add_argument("--epochs", type=int, default=4000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--decay", type=float, default=1e-5)
    args = ap.parse_args()

    cache = fh.load_cache()
    key = fh.rules_digest()
    entry = next((v for k, v in cache.items() if key in k), None)
    if entry is None:
        print("no labels for the current rules -- run tools/fit_heuristic.py")
        return 1

    train_rows = fh.as_rows(entry["train"])
    hold_rows = fh.as_rows(entry["holdout"])
    Xtr = np.array([f for f, _v, _s in train_rows], dtype=float)
    ytr = np.array([v for _f, v, _s in train_rows], dtype=float)
    print(f"  {len(train_rows)} train, {len(hold_rows)} hold-out, "
          f"{Xtr.shape[1]} features")

    linear = fh.fit(train_rows)
    lin_predict = lambda f: float(sum(w * x for w, x in zip(linear, f)))

    Xs, mean, std = standardise(Xtr)
    # Standardise the TARGET too. Without this the first run showed a
    # -23 bias with a BETTER correlation than the linear model, which is
    # the signature of a net that has learned the shape and not the
    # scale: labels span roughly -200..+100, and a linear output layer
    # starting near zero needs a long time to walk its bias out that
    # far. Reporting that as "an MLP cannot beat the linear model" would
    # have been a conclusion about the harness.
    ymean, ystd = float(ytr.mean()), float(ytr.std()) or 1.0
    ytr_s = (ytr - ymean) / ystd

    print(f"\n  {'model':>22} {'bias':>7} {'MAE':>7} {'r':>6} {'ordering':>9}")
    for tag, rows in (("train", train_rows), ("HOLD-OUT", hold_rows)):
        print(f"  {tag}")
        s = fh.score(rows, lin_predict)
        print(f"  {'linear (shipped form)':>22} {s['bias']:>7.1f} "
              f"{s['mae']:>7.1f} {s['r']:>6.2f} {s['order']:>8.0f}%")
        for seed in range(args.seeds):
            Ws, bs = train(Xs, ytr_s, tuple(args.hidden), args.epochs,
                           seed=seed, weight_decay=args.decay)
            raw = predictor(Ws, bs, mean, std)
            p = lambda f, _r=raw: _r(f) * ystd + ymean
            s = fh.score(rows, p)
            print(f"  {'MLP seed ' + str(seed):>22} {s['bias']:>7.1f} "
                  f"{s['mae']:>7.1f} {s['r']:>6.2f} {s['order']:>8.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
