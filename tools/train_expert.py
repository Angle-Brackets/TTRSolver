"""Train a policy by imitating the search's play (expert iteration).

    python tools/train_expert.py --epochs 40

Behaviour cloning on trajectories from `tools/gen_expert.py`: predict
the move the search made, and the value it assigned. Exports in exactly
the format `tools/train_ppo.py` writes, so the same evaluation harness
reads either and the two can be compared on identical positions.

The ceiling is the search's own play, which is depth 1 with a guessed
continuation and therefore not optimal. That is the honest limit. It is
also far above a policy that lays a trap 9.3% of the time, which is
where PPO ended up after a curriculum built specifically to teach it.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                           # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=".expert_traj.json")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--decay", type=float, default=1e-4)
    ap.add_argument("--holdout", type=float, default=0.1)
    ap.add_argument("--export", default="solver/rl/ppo_expert.json")
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    payload = json.loads(Path(args.data).read_text(encoding="utf-8"))
    bad = env_mod.check_export(payload)
    if bad:
        print(f"  trajectories do not match this environment: {bad}")
        return 1

    rows = payload["rows"]
    random.Random(0).shuffle(rows)
    cut = int(len(rows) * (1 - args.holdout))
    train, hold = rows[:cut], rows[cut:]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  device: {device}   {len(train)} train / {len(hold)} hold-out "
          f"decisions   coordinated={payload.get('coordinated')}")

    vals = [r["val"] for r in train]
    vmean = statistics.mean(vals)
    vstd = statistics.pstdev(vals) or 1.0

    def tensors(rs):
        return (torch.tensor([r["obs"] for r in rs], dtype=torch.float32,
                             device=device),
                torch.tensor([r["act"] for r in rs], dtype=torch.long,
                             device=device),
                torch.tensor([(r["val"] - vmean) / vstd for r in rs],
                             dtype=torch.float32, device=device))

    Xtr, Atr, Vtr = tensors(train)
    Xho, Aho, Vho = tensors(hold)

    n_actions = len(env_mod.ACTIONS)
    trunk = nn.Sequential(nn.Linear(env_mod.OBS_DIM, args.hidden), nn.Tanh(),
                          nn.Linear(args.hidden, args.hidden),
                          nn.Tanh()).to(device)
    vtrunk = nn.Sequential(nn.Linear(env_mod.OBS_DIM, args.hidden), nn.Tanh(),
                           nn.Linear(args.hidden, args.hidden),
                           nn.Tanh()).to(device)
    actor = nn.Linear(args.hidden, n_actions).to(device)
    critic = nn.Linear(args.hidden, 1).to(device)
    params = (list(trunk.parameters()) + list(vtrunk.parameters())
              + list(actor.parameters()) + list(critic.parameters()))
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    best = {"acc": -1.0, "state": None, "epoch": 0}
    for epoch in range(1, args.epochs + 1):
        perm = torch.randperm(len(Xtr), device=device)
        for start in range(0, len(perm), args.batch):
            sel = perm[start:start + args.batch]
            logits = actor(trunk(Xtr[sel]))
            value = critic(vtrunk(Xtr[sel])).squeeze(-1)
            loss = (F.cross_entropy(logits, Atr[sel])
                    + 0.5 * F.mse_loss(value, Vtr[sel]))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 0.5)
            opt.step()
        sched.step()

        if epoch % 5 == 0 or epoch == args.epochs:
            with torch.no_grad():
                logits = actor(trunk(Xho))
                acc = (logits.argmax(1) == Aho).float().mean().item()
                top5 = (logits.topk(5, dim=1).indices
                        == Aho.unsqueeze(1)).any(1).float().mean().item()
                vmae = ((critic(vtrunk(Xho)).squeeze(-1) - Vho).abs().mean()
                        .item() * vstd)
            mark = ""
            if acc > best["acc"]:
                best = {"acc": acc, "epoch": epoch,
                        "state": {n: {k: v.detach().cpu().clone()
                                      for k, v in m.state_dict().items()}
                                  for n, m in (("trunk", trunk),
                                               ("vtrunk", vtrunk),
                                               ("actor", actor),
                                               ("critic", critic))}}
                mark = "  <- best"
            print(f"    epoch {epoch:3d}  move match {acc * 100:5.1f}%  "
                  f"top-5 {top5 * 100:5.1f}%  value MAE {vmae:6.2f}{mark}")

    payload_out = {
        "obs_dim": env_mod.OBS_DIM, "n_actions": n_actions,
        "hidden": args.hidden, "coordinated": payload.get("coordinated"),
        "match": best["acc"], "epoch": best["epoch"],
        **{name: {k: v.tolist() for k, v in mod.items()}
           for name, mod in best["state"].items()},
    }
    Path(args.export).write_text(json.dumps(payload_out), encoding="utf-8")
    print(f"\n  best epoch {best['epoch']}: matches the search on "
          f"{best['acc'] * 100:.1f}% of held-out decisions")
    print(f"  exported to {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
