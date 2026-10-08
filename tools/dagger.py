"""Train the policy toward its own improvement operator (DAgger).

    python tools/dagger.py --iterations 6

WHY THIS, NOT THE EXPERT ITERATION THAT ALREADY FAILED
--------------------------------------------------------
`tools/gen_expert.py` cloned the SEARCH's play and collapsed to 7.5% of
buildings against PPO's 35%, for two reasons fixed here:

* **States came from the teacher.** Recording positions along the
  search's own trajectory trains on states the learner never visits --
  one early deviation and the errors compound (covariate shift). Here
  rollouts follow the LEARNER; only the labels come from the teacher.
* **The teacher was too far away.** The search's moves (e.g. trap5 +
  hold where the policy opens three Sounds) are outside what the policy
  can represent, so cloning them taught noise -- the clone didn't even
  copy the teacher's healing (1.3% vs 5.3%).

`hybrid.climb` is a better teacher for being a weaker player: its plans
are ONE-SEAT PERTURBATIONS of the policy's own output, so every label is
reachable, and it is cheap enough to run inline (0.6ms/decision vs the
search's 124ms) to label every visited state -- AlphaZero's loop, without
MCTS.

RESULT: IT DOES NOT COMPOUND. MEASURED.
------------------------------------------
The hope was a compounding loop: better policy -> better `climb`
candidates -> better teacher -> better policy. Six iterations, 120
episodes each, 15,393 aggregated states, warm-started from the
track-entropy policy, paired on the project's three standard seed sets
(180 buildings each):

    plain (argmax)   57.2 / 53.9 / 61.7  ->  57.8 / 54.4 / 54.4   -2.0
    climb, budget 8  68.3 / 61.7 / 65.0  ->  66.1 / 60.0 / 66.1   -0.9

Mixed signs, negative mean, both ways round -- kept because the reason is
worth more than the feature would have been. Agreement with the teacher
never rises either (44.3/37.6/43.1/44.1/42.7/45.8% across iterations)
even as loss falls monotonically (1.56 -> 1.26): a MOVING TARGET, not a
fixed point. Unlike MCTS, `climb` is a perturbation OF THE STUDENT'S OWN
PROPOSAL, so training the student moves the target with it. Same lesson
as everywhere else this project has been bitten: a judge must be
independent of the proposer. `climb` works as policy-plus-scorer, two
things with different blind spots; distilling it into the policy leaves
only `_quick_score`'s myopia (one all-hit round), training the policy to
swing.

TWO HARNESS BUGS THAT NEARLY BURIED THAT CONCLUSION
------------------------------------------------------
The first full run measured -12.4 plain, not -2.0. The teacher was
queried ONCE PER ROUND and seat k read its label off the resulting joint
plan -- so the label assumed seats 0..k-1 played the TEACHER's picks,
while the trajectory had played the STUDENT's. In a coordinated plan the
seats are chosen against each other, so those labels described positions
that never occurred (10.4 of the 12.4 points). `collect` now re-queries
the teacher at every seat with the committed prefix pinned
(`hybrid.climb(..., fixed=...)`); agreement fell 53.7% -> 41.2% the
moment the labels became honest, since a teacher that responds to the
student disagrees with it more.

Second: the cross-entropy ran over all 246 actions including illegal
ones inference never reads, so loss sat at 5.46 (near ln(246)=5.51,
i.e. near-uniform) while the student already agreed with the teacher
over half the time. The mask belongs in the loss; with it, loss starts
at 1.47.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid                              # noqa: E402

LIVE = Path("solver/rl/ppo_facility.json")


def action_index(action) -> int:
    if action is None or action.is_pass:
        return env_mod.PASS_INDEX
    for i, cand in enumerate(env_mod.ACTIONS):
        if (cand is not None and cand.track == action.track
                and cand.level == action.level
                and cand.target_index == action.target_index):
            return i
    return env_mod.PASS_INDEX


def collect(episodes: int, budget: int, seed: int, sampler):
    """Roll out with the POLICY; label every state with the climb.

    The distinction that makes this DAgger rather than the behaviour
    cloning that failed: the trajectory is the learner's, so the states
    are ones it actually reaches.
    """
    rows, agreed, total = [], 0, 0
    for offset in range(episodes):
        rng = random.Random(seed * 7919 + offset)
        e = env_mod.BattleEnv(rng=random.Random(seed * 104729 + offset),
                              sampler=sampler, coordinated=True)
        obs, mask = e.reset()
        done, guard = False, 0
        while not done and guard < 250:
            guard += 1
            seat = e.actor
            # Ask the teacher about the state that actually happened: the
            # prefix the STUDENT played, not a joint plan re-read per
            # seat (see the module docstring's first harness bug).
            committed = {i: e.pending[i] for i in range(seat)}
            teacher = hybrid.climb(e.state, rng, budget=budget,
                                   fixed=committed)
            student = hybrid.propose(e.state, rng, sample=False,
                                     fixed=committed)
            label = action_index(teacher[seat] if teacher
                                 and seat < len(teacher) else None)
            mine = action_index(student[seat] if student
                                and seat < len(student) else None)
            rows.append((obs, label, list(mask)))
            total += 1
            agreed += (label == mine)
            # Step with the LEARNER's move, not the teacher's.
            step = mine if mask[mine] else env_mod.PASS_INDEX
            obs, mask, _r, done, _info = e.step(step)
    return rows, (agreed / max(1, total) * 100.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--episodes", type=int, default=120)
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--keep", type=int, default=200_000,
                    help="cap on the aggregated dataset; DAgger keeps every "
                         "iteration's states, not just the newest")
    ap.add_argument("--start", default=str(LIVE))
    ap.add_argument("--export", default="")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    device = "cuda" if torch.cuda.is_available() else "cpu"
    payload = json.loads(Path(args.start).read_text(encoding="utf-8"))
    bad = env_mod.check_export(payload)
    if bad:
        print(f"  cannot start from {args.start}: {bad}")
        return 1
    hidden = payload["hidden"]
    print(f"  device: {device}   starting from {args.start} "
          f"({hidden} wide)")

    trunk = nn.Sequential(nn.Linear(env_mod.OBS_DIM, hidden), nn.Tanh(),
                          nn.Linear(hidden, hidden), nn.Tanh()).to(device)
    actor = nn.Linear(hidden, len(env_mod.ACTIONS)).to(device)
    with torch.no_grad():
        for i in (0, 2):
            trunk[i].weight.copy_(torch.tensor(payload["trunk"][f"{i}.weight"]))
            trunk[i].bias.copy_(torch.tensor(payload["trunk"][f"{i}.bias"]))
        actor.weight.copy_(torch.tensor(payload["actor"]["weight"]))
        actor.bias.copy_(torch.tensor(payload["actor"]["bias"]))

    params = list(trunk.parameters()) + list(actor.parameters())
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-5)

    def sampler(r):
        if r.random() < 0.5:
            return env_mod.facility_position(r)
        state = env_mod.mixed_position(r, 0.3, 0.25, 0.2)
        state.cogs_remaining = 0
        state.kind = "street"
        return state

    def export(path):
        out = dict(payload)
        out["trunk"] = {f"{i}.{k}": getattr(trunk[i], k).detach().cpu()
                        .tolist() for i in (0, 2) for k in ("weight", "bias")}
        out["actor"] = {"weight": actor.weight.detach().cpu().tolist(),
                        "bias": actor.bias.detach().cpu().tolist()}
        Path(path).write_text(json.dumps(out), encoding="utf-8")
        hybrid._MODEL, hybrid._TRIED = None, False

    dataset = []
    for iteration in range(1, args.iterations + 1):
        rows, agreement = collect(args.episodes, args.budget,
                                  args.seed + iteration, sampler)
        dataset.extend(rows)
        # DAgger aggregates: earlier iterations' states stay, so the
        # policy keeps answering for positions it has since stopped
        # visiting.
        if len(dataset) > args.keep:
            dataset = dataset[-args.keep:]

        X = torch.tensor([r[0] for r in dataset], dtype=torch.float32,
                         device=device)
        Y = torch.tensor([r[1] for r in dataset], dtype=torch.long,
                         device=device)
        # The mask belongs in the loss (see the module docstring's
        # second harness bug) -- otherwise cross-entropy runs over
        # illegal actions too and mostly measures noise.
        M = torch.tensor([r[2] for r in dataset], dtype=torch.bool,
                         device=device)
        losses = []
        for _epoch in range(args.epochs):
            order = torch.randperm(len(X), device=device)
            for start in range(0, len(order), args.batch):
                sel = order[start:start + args.batch]
                logits = actor(trunk(X[sel]))
                logits = logits.masked_fill(~M[sel], float("-inf"))
                loss = F.cross_entropy(logits, Y[sel])
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 0.5)
                opt.step()
                losses.append(loss.detach().item())
        export(LIVE)
        print(f"    iter {iteration}: {len(rows)} new / {len(dataset)} kept   "
              f"student already agreed {agreement:.1f}%   "
              f"loss {statistics.mean(losses[-40:]):.3f}", flush=True)

    if args.export:
        export(args.export)
        shutil.copy(args.export, LIVE)
        print(f"\n  exported to {args.export}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
