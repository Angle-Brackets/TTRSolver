"""Train the party value head (P1) on searched party data.

    python tools/train_heads.py --epochs 60 --export solver/search/party_policy.json

A small network from a position's features to its searched value: the
value of the best plan the teacher search found there. `party_search.
evaluate(leaf="learned")` uses it as the search leaf in place of
`rollout_value` -- a forward pass is ~10x quicker than a rollout.

There used to be a second, policy head (P0) on the same trunk, trained
to rank plans for the shortlist. It looked strong on held-out regret
(3.22 vs `_quick_score`'s 9.93) and lost in play at every shortlist size;
docs/scoring.md has the measurements. It was removed with `policy.rank`.

Torch, GPU if available. Training lives in `tools/` and never in
`solver/`: what ships is a plain-float export (`--export`) so inference
stays numpy only, the same rule `search/fitted.py` follows.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.search import features                             # noqa: E402
from solver.state import Track                                 # noqa: E402
from visualizer import bridge                                  # noqa: E402

LABELS = Path(__file__).resolve().parents[1] / ".party_labels.json"
TRACK_ORDER = [Track.TOON_UP, Track.TRAP, Track.LURE, Track.SOUND,
               Track.THROW, Track.SQUIRT, Track.DROP]
MAX_TOONS, MAX_COGS = 4, 4


def load(path, holdout=0.15, seed=0):
    """(train, hold-out, teacher) rows of {"pos": features, "value": best}."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for entry in payload["positions"]:
        state = bridge.state_from_dict(entry["state"])
        rows.append({"pos": list(features.extract(state)),
                     "value": entry["values"][0]})
    rng = random.Random(seed)
    rng.shuffle(rows)
    cut = int(len(rows) * (1 - holdout))
    return rows[:cut], rows[cut:], payload.get("teacher", {})


class Nets:
    """Trunk plus value head. Built lazily so importing this module does
    not require torch."""

    def __init__(self, pos_dim, hidden=128, device="cpu"):
        import torch.nn as nn

        self.trunk = nn.Sequential(
            nn.Linear(pos_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU()).to(device)
        self.value = nn.Sequential(
            nn.Linear(hidden, 64), nn.ReLU(), nn.Linear(64, 1)).to(device)

    def parameters(self):
        return list(self.trunk.parameters()) + list(self.value.parameters())

    def forward(self, pos):
        return self.value(self.trunk(pos)).squeeze(-1)

    def train(self, on=True):
        self.trunk.train(on)
        self.value.train(on)


def tensors(rows, torch, device, vmean, vstd):
    pos = torch.tensor([r["pos"] for r in rows], dtype=torch.float32, device=device)
    val = torch.tensor([(r["value"] - vmean) / vstd for r in rows],
                       dtype=torch.float32, device=device)
    return pos, val


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--decay", type=float, default=1e-4)
    ap.add_argument("--export", default=None)
    args = ap.parse_args()

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    train_rows, hold_rows, teacher = load(args.labels)
    print(f"  {len(train_rows)} train / {len(hold_rows)} hold-out positions, "
          f"teacher={teacher}")
    vals = [r["value"] for r in train_rows]
    vmean = sum(vals) / len(vals)
    vstd = (sum((v - vmean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0

    nets = Nets(len(train_rows[0]["pos"]), args.hidden, device)
    opt = torch.optim.AdamW(nets.parameters(), lr=args.lr, weight_decay=args.decay)
    # Cosine decay: without a schedule the hold-out wandered between
    # checkpoints instead of converging.
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    X, Y = tensors(train_rows, torch, device, vmean, vstd)
    Xh, Yh = tensors(hold_rows, torch, device, vmean, vstd)

    def hold_mae():
        nets.train(False)
        with torch.no_grad():
            mae = ((nets.forward(Xh) - Yh).abs() * vstd).mean().item()
        nets.train(True)
        return mae

    best = {"mae": float("inf"), "epoch": 0, "state": None}
    for epoch in range(1, args.epochs + 1):
        perm = torch.randperm(len(X), device=device)
        for start in range(0, len(X), args.batch):
            idx = perm[start:start + args.batch]
            loss = torch.nn.functional.mse_loss(nets.forward(X[idx]), Y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        if epoch % 5 == 0 or epoch == args.epochs:
            mae, mark = hold_mae(), ""
            if mae < best["mae"]:
                best = {"mae": mae, "epoch": epoch,
                        "state": {name: {k: v.detach().cpu().clone()
                                         for k, v in mod.state_dict().items()}
                                  for name, mod in (("trunk", nets.trunk),
                                                    ("value", nets.value))}}
                mark = "  <- best"
            print(f"    epoch {epoch:3d}  hold-out value MAE {mae:6.2f}{mark}")

    print(f"\n  best epoch {best['epoch']}: value MAE {best['mae']:.2f}")
    if args.export:
        # Plain floats, not a torch checkpoint: `search/policy.py` reads
        # this with numpy alone.
        payload = {
            "vmean": vmean, "vstd": vstd,
            "pos_dim": len(train_rows[0]["pos"]),
            "track_order": [t.name for t in TRACK_ORDER],
            "max_toons": MAX_TOONS, "max_cogs": MAX_COGS,
            "mae": best["mae"], "epoch": best["epoch"],
            "nets": {name: {k: v.tolist() for k, v in mod.items()}
                     for name, mod in best["state"].items()},
        }
        Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
        size = Path(args.export).stat().st_size / 1e6
        print(f"  exported best epoch to {args.export} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
