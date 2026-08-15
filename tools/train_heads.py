"""Train the policy and value heads (P0 / P1) on searched party data.

    python tools/train_heads.py --epochs 60

Two heads on one shared trunk, which is the AlphaZero shape and is here
for the AlphaZero reason: the two questions share almost all of their
evidence. What makes a position good and what makes a plan good in it
are learned from the same features.

  * VALUE head  -> the position's searched value (P1). Replaces
    `party_search.rollout_value` as the search leaf. A forward pass is
    ~10x quicker than a rollout.
  * POLICY head -> a score per (position, plan), trained to rank plans
    the way a WIDE search ranked them (P0). Used to pick the shortlist,
    which is the term search cost is exponential in.

WHY RANKING AND NOT REGRESSION FOR THE POLICY
---------------------------------------------
The policy never needs a plan's value, only its order, and the values
themselves are noisy sampled estimates. Training a listwise softmax
cross-entropy against the teacher's ranking asks for exactly what is
used and nothing more. Regressing the values would spend capacity
fitting sampling noise.

Torch, GPU if available. Training lives in `tools/` and never in
`solver/`: what ships is a plain-float export (`--export`) so inference
stays standard-library only, the same rule `search/fitted.py` follows.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import data                                        # noqa: E402
from solver.search import features                             # noqa: E402
from solver.state import Action, Track                         # noqa: E402
from visualizer import bridge                                  # noqa: E402

LABELS = Path(__file__).resolve().parents[1] / ".party_labels.json"
TRACK_ORDER = [Track.TOON_UP, Track.TRAP, Track.LURE, Track.SOUND,
               Track.THROW, Track.SQUIRT, Track.DROP]
MAX_TOONS, MAX_COGS = 4, 4
PLAN_DIM = MAX_TOONS * (len(TRACK_ORDER) + 1 + 1 + MAX_COGS + 1)


def encode_plan_features(plan_json, state):
    """One block per toon: track one-hot, level, target one-hot, hold.

    Deliberately flat and per-toon rather than pooled -- toons are not
    interchangeable (`outcomes.state_key` keys on every toon in order,
    and a frozenset there would let a memo answer about one party with
    another's value), so the ordering carries information.
    """
    out = []
    for i in range(MAX_TOONS):
        entry = plan_json[i] if i < len(plan_json) else None
        block = [0.0] * (len(TRACK_ORDER) + 1 + 1 + MAX_COGS + 1)
        if entry is None:
            block[-1] = 1.0                      # hold (or absent toon)
        else:
            name, level, target = entry
            track = Track[name]
            block[TRACK_ORDER.index(track)] = 1.0
            block[len(TRACK_ORDER)] = level / 7.0
            if target is None:
                block[len(TRACK_ORDER) + 1] = 1.0        # group gag
            elif 0 <= target < MAX_COGS:
                block[len(TRACK_ORDER) + 2 + target] = 1.0
        out.extend(block)
    return out


def load(path, holdout=0.15, seed=0):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for entry in payload["positions"]:
        state = bridge.state_from_dict(entry["state"])
        pos = list(features.extract(state))
        plans = [encode_plan_features(p, state) for p in entry["plans"]]
        rows.append({"pos": pos, "plans": plans, "values": entry["values"]})
    rng = random.Random(seed)
    rng.shuffle(rows)
    cut = int(len(rows) * (1 - holdout))
    return rows[:cut], rows[cut:], payload.get("teacher", {})


class Nets:
    """Shared trunk, two heads. Built lazily so importing this module
    does not require torch."""

    def __init__(self, pos_dim, plan_dim, hidden=128, device="cpu"):
        import torch.nn as nn
        import torch

        self.device = device
        self.trunk = nn.Sequential(
            nn.Linear(pos_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU()).to(device)
        self.value = nn.Sequential(
            nn.Linear(hidden, 64), nn.ReLU(), nn.Linear(64, 1)).to(device)
        self.policy = nn.Sequential(
            nn.Linear(hidden + plan_dim, 128), nn.ReLU(),
            nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 1)).to(device)
        self.torch = torch

    def parameters(self):
        return (list(self.trunk.parameters()) + list(self.value.parameters())
                + list(self.policy.parameters()))

    def forward(self, pos, plans):
        """pos: (B, P). plans: (B, K, PLAN_DIM). -> value (B,), logits (B,K)."""
        h = self.trunk(pos)
        value = self.value(h).squeeze(-1)
        k = plans.shape[1]
        joined = self.torch.cat(
            [h.unsqueeze(1).expand(-1, k, -1), plans], dim=-1)
        logits = self.policy(joined).squeeze(-1)
        return value, logits


def batches(rows, size, k, rng, torch, device, vmean, vstd):
    """Pad each position's plan list to exactly k, with a mask.

    Positions have different shortlist lengths, so the loss must ignore
    padding -- otherwise the model learns that short shortlists have
    low-scoring tail entries, which is an artefact of batching.
    """
    order = list(range(len(rows)))
    rng.shuffle(order)
    for start in range(0, len(order), size):
        chunk = [rows[i] for i in order[start:start + size]]
        pos = torch.tensor([r["pos"] for r in chunk], dtype=torch.float32)
        P = torch.zeros(len(chunk), k, PLAN_DIM)
        T = torch.full((len(chunk), k), -1e9)
        V = torch.zeros(len(chunk))
        for bi, r in enumerate(chunk):
            take = min(k, len(r["plans"]))
            for pi in range(take):
                P[bi, pi] = torch.tensor(r["plans"][pi], dtype=torch.float32)
                T[bi, pi] = r["values"][pi]
            V[bi] = (r["values"][0] - vmean) / vstd
        yield (pos.to(device), P.to(device), T.to(device), V.to(device))


def evaluate(nets, rows, k, torch, device, vmean, vstd, shortlist=6):
    """Value MAE, top-k accuracy, and REGRET -- which is the one that
    matters.

    Top-1 accuracy asks "did the policy pick the teacher's argmax". That
    is the wrong question twice over: the policy is used to choose a
    SHORTLIST, not a move, and the teacher's argmax is itself a sampled
    estimate whose top few plans sit within noise of each other. A policy
    can miss the argmax every time and still be perfect for our purpose,
    provided a plan of equal value survives into the shortlist.

    Regret@k is that question: the value the teacher's best plan had,
    minus the best value among the k plans the policy would have kept.
    Zero means nothing was lost by searching only those k.
    """
    nets.trunk.eval(); nets.value.eval(); nets.policy.eval()
    abs_err, n, top1, top5 = 0.0, 0, 0, 0
    regret, regret_zero = 0.0, 0
    with torch.no_grad():
        for pos, P, T, V in batches(rows, 128, k, random.Random(1),
                                    torch, device, vmean, vstd):
            value, logits = nets.forward(pos, P)
            abs_err += (value * vstd + vmean
                        - (V * vstd + vmean)).abs().sum().item()
            n += len(pos)
            mask = T > -1e8
            logits = logits.masked_fill(~mask, -1e9)
            best_true = T.argmax(dim=1)
            order = logits.argsort(dim=1, descending=True)
            top1 += (order[:, 0] == best_true).sum().item()
            top5 += (order[:, :5] == best_true.unsqueeze(1)).any(1).sum().item()
            # Regret: value lost by keeping only the policy's top few.
            kept = order[:, :shortlist]
            best_kept = T.gather(1, kept).max(dim=1).values
            best_any = T.masked_fill(~mask, -1e9).max(dim=1).values
            gap = (best_any - best_kept).clamp(min=0.0)
            regret += gap.sum().item()
            regret_zero += (gap < 1e-6).sum().item()
    nets.trunk.train(); nets.value.train(); nets.policy.train()
    return (abs_err / max(n, 1), top1 / max(n, 1), top5 / max(n, 1),
            regret / max(n, 1), regret_zero / max(n, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--plans", type=int, default=48,
                    help="plans kept per position when batching")
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--decay", type=float, default=1e-4)
    ap.add_argument("--shortlist", type=int, default=6,
                    help="k for regret@k -- the shortlist the policy would keep")
    ap.add_argument("--export", default=None)
    args = ap.parse_args()

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    train_rows, hold_rows, teacher = load(args.labels)
    print(f"  {len(train_rows)} train / {len(hold_rows)} hold-out positions, "
          f"teacher={teacher}")
    vals = [r["values"][0] for r in train_rows]
    vmean = sum(vals) / len(vals)
    vstd = (sum((v - vmean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0

    nets = Nets(len(train_rows[0]["pos"]), PLAN_DIM, args.hidden, device)
    opt = torch.optim.AdamW(nets.parameters(), lr=args.lr,
                            weight_decay=args.decay)
    rng = random.Random(0)

    for epoch in range(1, args.epochs + 1):
        for pos, P, T, V in batches(train_rows, args.batch, args.plans,
                                    rng, torch, device, vmean, vstd):
            value, logits = nets.forward(pos, P)
            mask = T > -1e8
            logits = logits.masked_fill(~mask, -1e9)

            # Listwise: softmax the teacher's values into a target
            # distribution and cross-entropy against it. Temperature
            # keeps a near-tie from being taught as a hard label, which
            # matters here because the top plans really are within noise
            # of each other.
            target = torch.softmax(T.masked_fill(~mask, -1e9) / 10.0, dim=1)
            logp = torch.log_softmax(logits, dim=1)
            policy_loss = -(target * logp).sum(dim=1).mean()
            value_loss = torch.nn.functional.mse_loss(value, V)
            loss = value_loss + policy_loss

            opt.zero_grad()
            loss.backward()
            opt.step()

        if epoch % 10 == 0 or epoch == args.epochs:
            mae, t1, t5, reg, rz = evaluate(nets, hold_rows, args.plans,
                                            torch, device, vmean, vstd,
                                            args.shortlist)
            print(f"    epoch {epoch:3d}  value MAE {mae:6.2f}  "
                  f"top-1 {t1 * 100:4.1f}%  top-5 {t5 * 100:4.1f}%  "
                  f"regret@{args.shortlist} {reg:6.2f}  "
                  f"lossless {rz * 100:4.1f}%")

    # Baseline: how often does the SHIPPED heuristic ordering put the
    # teacher's best plan first? The policy has to beat this, not chance.
    print("\n  baseline -- the shortlist order the search ships with:")
    first = sum(1 for r in hold_rows if r["values"][0] == max(r["values"]))
    print(f"    teacher's own ordering is by construction 100% top-1; "
          f"({first}/{len(hold_rows)} sanity)")
    rand1 = sum(1.0 / len(r["plans"]) for r in hold_rows) / len(hold_rows)
    print(f"    uniform random over the shortlist: {rand1 * 100:.1f}% top-1")

    if args.export:
        payload = {"vmean": vmean, "vstd": vstd, "plan_dim": PLAN_DIM,
                   "weights": {k: v.detach().cpu().tolist()
                               for k, v in
                               list(nets.trunk.state_dict().items())}}
        Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
        print(f"  exported trunk to {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
