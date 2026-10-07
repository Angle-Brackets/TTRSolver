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

    rows, unite_rows = [], []
    for path in args.data:
        for row in pickle.load(open(path, "rb")):
            if len(row) == 3:
                # From before the unite inputs: those fights held no
                # unites, so "0 held, no cooldown" is exactly right.
                features, mask, label = row
                rows.append((list(features) + [0.0, 0.0], mask, label))
            elif row[0] == "act":
                rows.append(row[1:])
            elif row[0] == "unite":
                unite_rows.append(row[1:])
    random.Random(0).shuffle(rows)
    random.Random(1).shuffle(unite_rows)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    def tensors(part):
        X = torch.tensor(np.array([r[0] for r in part], dtype=np.float32), device=dev)
        M = torch.tensor(np.array([r[1] for r in part], dtype=bool), device=dev)
        Y = torch.tensor([r[2] for r in part], device=dev)
        return X, M, Y

    def split(part):
        cut = int(len(part) * (1 - args.holdout))
        return tensors(part[:cut]), tensors(part[cut:])

    (X, M, Y), (Xv, Mv, Yv) = split(rows)
    have_unites = len(unite_rows) >= 20
    if have_unites:
        (XU, MU, YU), (XUv, MUv, YUv) = split(unite_rows)
    n_in, n_out = X.shape[1], M.shape[1]
    print(f"  device {dev}  {len(X)} gag rows / {len(Xv)} held out, "
          f"{len(unite_rows)} unite rows  inputs {n_in}  outputs {n_out}")

    trunk = nn.Sequential(nn.Linear(n_in, args.hidden), nn.Tanh(),
                          nn.Linear(args.hidden, args.hidden), nn.Tanh()).to(dev)
    act_head = nn.Linear(args.hidden, n_out).to(dev)
    unite_head = (nn.Linear(args.hidden, MU.shape[1]).to(dev)
                  if have_unites else None)
    params = list(trunk.parameters()) + list(act_head.parameters())
    if unite_head is not None:
        params += list(unite_head.parameters())
    opt = torch.optim.Adam(params, lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    def match(head, Xs, Ms, Ys):
        with torch.no_grad():
            out = head(trunk(Xs)).masked_fill(~Ms, -1e9)
            return (out.argmax(-1) == Ys).float().mean().item()

    for epoch in range(args.epochs):
        perm = torch.randperm(len(X), device=dev)
        for s in range(0, len(X), args.batch):
            idx = perm[s:s + args.batch]
            out = act_head(trunk(X[idx])).masked_fill(~M[idx], -1e9)
            loss = F.cross_entropy(out, Y[idx])
            if unite_head is not None:
                uidx = torch.randint(0, len(XU), (min(args.batch, len(XU)),), device=dev)
                uout = unite_head(trunk(XU[uidx])).masked_fill(~MU[uidx], -1e9)
                loss = loss + F.cross_entropy(uout, YU[uidx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        line = (f"  epoch {epoch + 1:2d}  loss {loss.item():.3f}  "
                f"held-out gag match {100 * match(act_head, Xv, Mv, Yv):.1f}%")
        if unite_head is not None:
            line += f"  unite match {100 * match(unite_head, XUv, MUv, YUv):.1f}%"
        print(line, flush=True)

    layers = [m for m in trunk if isinstance(m, nn.Linear)] + [act_head]
    payload = {"layers": [[m.weight.detach().cpu().T.tolist(),
                           m.bias.detach().cpu().tolist()] for m in layers],
               "match": match(act_head, Xv, Mv, Yv), "rows": len(rows),
               "unite_rows": len(unite_rows),
               "hidden": args.hidden, "epochs": args.epochs}
    if unite_head is not None:
        payload["unite"] = [unite_head.weight.detach().cpu().T.tolist(),
                            unite_head.bias.detach().cpu().tolist()]
        payload["unite_match"] = match(unite_head, XUv, MUv, YUv)
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  exported to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
