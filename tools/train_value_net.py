"""Train `valuenet` on deep-search labels from `tools/gen_value_data.py`.

    python tools/train_value_net.py --data value_r1.pkl --export solver/rl/value_net.json

Regression on the label (`y`, the search's value of the board) from
`fastplayer.features`, scaled by 100. Whole boards held out. Reports the
held-out error in value points beside the FITTED leaf's error on the same
boards -- the number the network has to beat to be worth installing.
Torch, GPU if available; exports plain floats for numpy inference.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCALE = 100.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--export", required=True)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--holdout", type=float, default=0.1)
    ap.add_argument("--obs-version", type=int, default=4,
                    help="board encoding the DATA was written in "
                         "(gen_*'s --obs-version); recorded in the export so "
                         "the loader encodes boards the same way")
    args = ap.parse_args()

    import numpy as np
    import torch
    import torch.nn as nn

    rows = []
    for path in args.data:
        rows += pickle.load(open(path, "rb"))
    random.Random(0).shuffle(rows)
    cut = int(len(rows) * (1 - args.holdout))
    train, hold = rows[:cut], rows[cut:]
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    def tensors(part):
        X = torch.tensor(np.array([r["x"] for r in part], dtype=np.float32), device=dev)
        Y = torch.tensor([r["y"] / SCALE for r in part], dtype=torch.float32, device=dev)
        return X, Y

    X, Y = tensors(train)
    Xh, Yh = tensors(hold)
    have_fitted = all("fitted" in r for r in hold)
    fitted_mae = (statistics.mean(abs(r["y"] - r["fitted"]) for r in hold)
                  if have_fitted else float("nan"))
    print(f"  device {dev}  {len(train)} train / {len(hold)} held out  inputs {X.shape[1]}")
    print(f"  fitted leaf on the held-out boards: MAE {fitted_mae:.2f}")

    net = nn.Sequential(nn.Linear(X.shape[1], args.hidden), nn.Tanh(),
                        nn.Linear(args.hidden, args.hidden), nn.Tanh(),
                        nn.Linear(args.hidden, 1)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    def hold_mae():
        net.eval()
        with torch.no_grad():
            err = ((net(Xh).squeeze(-1) - Yh).abs() * SCALE)
        net.train()
        return err.mean().item(), err.median().item()

    best = (float("inf"), None)
    for epoch in range(args.epochs):
        perm = torch.randperm(len(X), device=dev)
        for s in range(0, len(X), args.batch):
            idx = perm[s:s + args.batch]
            loss = nn.functional.smooth_l1_loss(net(X[idx]).squeeze(-1), Y[idx], beta=0.05)
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        mae, med = hold_mae()
        if mae < best[0]:
            best = (mae, [[m.weight.detach().cpu().T.tolist(), m.bias.detach().cpu().tolist()]
                          for m in net if isinstance(m, nn.Linear)])
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  epoch {epoch + 1:3d}  held-out MAE {mae:6.2f}  median {med:6.2f}", flush=True)

    by_cogs = {}
    net.eval()
    with torch.no_grad():
        pred = (net(Xh).squeeze(-1) * SCALE).cpu().tolist()
    for r, p in zip(hold, pred):
        by_cogs.setdefault(r["cogs"], []).append(
            (abs(p - r["y"]), abs(r.get("fitted", float("nan")) - r["y"])))
    for cogs in sorted(by_cogs):
        pairs = by_cogs[cogs]
        print(f"  {cogs} cogs ({len(pairs)}): net MAE {statistics.mean(a for a, _ in pairs):6.2f}"
              f"   fitted MAE {statistics.mean(b for _, b in pairs):6.2f}")
    payload = {"layers": best[1], "scale": SCALE, "hold_mae": best[0],
               "fitted_mae": fitted_mae, "rows": len(rows), "hidden": args.hidden,
               "obs_version": args.obs_version}
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  best held-out MAE {best[0]:.2f} (fitted {fitted_mae:.2f}); exported to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
