"""Train the fast rollout player: a small network that copies `climb`.

    python tools/train_fast_player.py --data climb_decisions.pkl

`--data` is a pickle of (features, mask, label) rows from
`solver.search.fastplayer.features` with `climb`'s move as the label.
Plain cross-entropy over the legal moves; whole rows held out for
validation. Exports `{"layers": [[W, b], ...]}` with W stored as
in x out, which is what `fastplayer.use` reads.

Copying `climb` is the goal, not beating it: the network replaces
`climb` only where speed buys more playouts. How well it copies is
reported as the held-out match rate; whether that is good enough is a
question for a paired sweep, not for this script.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--export", default="solver/rl/fast_player.json")
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--holdout", type=float, default=0.05)
    args = ap.parse_args()

    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    rows = []
    for path in args.data:
        rows += pickle.load(open(path, "rb"))
    random.Random(0).shuffle(rows)
    cut = int(len(rows) * (1 - args.holdout))
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    def tensors(part):
        X = torch.tensor(np.array([r[0] for r in part], dtype=np.float32), device=dev)
        M = torch.tensor(np.array([r[1] for r in part], dtype=bool), device=dev)
        Y = torch.tensor([r[2] for r in part], device=dev)
        return X, M, Y

    X, M, Y = tensors(rows[:cut])
    Xv, Mv, Yv = tensors(rows[cut:])
    n_in, n_out = X.shape[1], M.shape[1]
    print(f"  device {dev}  {len(X)} train / {len(Xv)} held out  "
          f"inputs {n_in}  outputs {n_out}")

    net = nn.Sequential(nn.Linear(n_in, args.hidden), nn.Tanh(),
                        nn.Linear(args.hidden, args.hidden), nn.Tanh(),
                        nn.Linear(args.hidden, n_out)).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    def evaluate():
        with torch.no_grad():
            out = net(Xv).masked_fill(~Mv, -1e9)
            return (out.argmax(-1) == Yv).float().mean().item()

    for epoch in range(args.epochs):
        perm = torch.randperm(len(X), device=dev)
        for s in range(0, len(X), args.batch):
            idx = perm[s:s + args.batch]
            out = net(X[idx]).masked_fill(~M[idx], -1e9)
            loss = F.cross_entropy(out, Y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        print(f"  epoch {epoch + 1:2d}  loss {loss.item():.3f}  "
              f"held-out match with climb {100 * evaluate():.1f}%", flush=True)

    layers = [m for m in net if isinstance(m, nn.Linear)]
    payload = {"layers": [[m.weight.detach().cpu().T.tolist(),
                           m.bias.detach().cpu().tolist()] for m in layers],
               "match": evaluate(), "rows": len(rows),
               "hidden": args.hidden, "epochs": args.epochs}
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  exported to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
