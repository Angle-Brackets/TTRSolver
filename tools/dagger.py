"""Train the policy toward its own improvement operator (DAgger).

    python tools/dagger.py --iterations 6

WHY THIS AND NOT THE EXPERT ITERATION THAT ALREADY FAILED
---------------------------------------------------------
`tools/gen_expert.py` cloned the SEARCH's play and collapsed to 7.5% of
buildings against PPO's 35%. Two things were wrong with it and both are
fixed here.

**The states came from the teacher.** It recorded positions along the
search's own trajectory, so the policy was trained on states it would
never itself visit. One small deviation early puts the learner in a
position the training set never covered, and the errors compound --
textbook covariate shift. Here the rollouts follow the LEARNER and only
the labels come from the teacher, which is the whole of DAgger.

**The teacher was too far away.** The search plays a different game from
PPO: it opens with trap5 and a hold where the policy opens with three
Sounds. Those targets are outside what the policy can represent, so
cloning them mostly teaches noise -- and indeed the clone failed to copy
even the behaviour that made the teacher good, healing 1.3% against the
teacher's 5.3%.

`hybrid.climb` is a better teacher for exactly the reason it is a weaker
player: its plans are ONE-SEAT PERTURBATIONS of the policy's own output.
Every label is reachable. It is also cheap enough to run inline -- 0.6 ms
a decision against the search's 124 -- so labelling every visited state
costs nothing, which is what makes the AlphaZero loop affordable without
MCTS.

WHAT WOULD MAKE THIS FAIL
-------------------------
The teacher is only ~1.5 points better than the student it is teaching
(climb 65.0% against plain PPO's 61.7% on the same sets), so the signal
per round is small. If the policy converges to the teacher exactly, the
ceiling is the teacher -- and the interesting question is whether the
loop compounds: a better policy proposes better candidates, which makes
climb better, which teaches a better policy. That is the AlphaZero
argument, and it is what the iteration count is here to test.

IT DOES NOT COMPOUND. MEASURED.
-------------------------------
Six iterations, 120 episodes each, 15,393 aggregated states, warm-started
from the track-entropy policy. Paired on the same three seed sets every
comparison in this project uses, 180 buildings each:

    plain (argmax)   57.2 / 53.9 / 61.7  ->  57.8 / 54.4 / 54.4   -2.0
    climb, budget 8  68.3 / 61.7 / 65.0  ->  66.1 / 60.0 / 66.1   -0.9

Mixed signs and a negative mean, both ways round. The loop does not
help, and the run is kept because the reason is worth more than the
feature would have been.

**Agreement never rises.** 44.3 / 37.6 / 43.1 / 44.1 / 42.7 / 45.8 across
the six iterations, while the loss falls monotonically 1.56 -> 1.26. The
student fits the labels better and agrees with the teacher no more than
it did at the start. That is what a MOVING TARGET looks like, and it is
the structural difference from AlphaZero: MCTS is a fixed improvement
operator that a policy can converge onto, whereas `climb` is defined as
a perturbation OF THE STUDENT'S OWN PROPOSAL. Change the student and the
target moves with it. There is no fixed point to walk toward.

It is also the same lesson as everything else that has failed here, from
the other end: A JUDGE MUST BE INDEPENDENT OF THE PROPOSER. `climb`
works because it is policy AND scorer, two things with different blind
spots. Distilling it into the policy collapses the pair into one member
of it, and what survives is `_quick_score`'s myopia -- it scores one
all-hit round, so a policy trained to imitate it is trained to swing.

THE BUG THAT NEARLY BURIED THAT CONCLUSION
------------------------------------------
The first full run measured -12.4 plain rather than -2.0, and it was the
harness, not the idea. The teacher was queried ONCE PER ROUND and seat k
read off the resulting joint plan -- so seat k's label was the move that
was right when seats 0..k-1 played the TEACHER's picks, while the
trajectory had played the STUDENT's. In a coordinated plan the seats are
chosen against each other, so those labels described a position that
never occurred, and 10.4 of the 12.4 points were that alone.

`collect` now re-queries the teacher at every seat with the committed
prefix pinned (`hybrid.climb(..., fixed=...)`). The tell was in the
agreement number: it fell from 53.7% to 41.2% the moment the labels
became honest, because a teacher that actually responds to the student
disagrees with it more.

Second harness bug, same run: the cross-entropy was taken over all 246
actions including the illegal ones, whose logits inference never reads.
The loss sat at 5.46 against ln(246) = 5.51 -- near-uniform -- while the
student already agreed with the teacher on more than half of its
decisions. The mask belongs in the loss; with it the loss starts at 1.47.
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
            # ASK THE TEACHER ABOUT THE STATE THAT ACTUALLY HAPPENED.
            # Computing one joint plan per round and reading seat k off
            # it labels seat k with the move that was right when seats
            # 0..k-1 played the TEACHER's picks -- but the trajectory
            # played the STUDENT's, because that is what makes this
            # DAgger. Those labels answer a question about a position
            # that did not occur, and in a coordinated plan the seats
            # are chosen against each other, so it is not a small
            # difference: it is the whole of the coordination.
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
        # THE MASK BELONGS IN THE LOSS. Without it the cross-entropy is
        # taken over all 246 actions including the illegal ones, whose
        # logits inference never looks at -- so the loss came out at
        # 5.46 against ln(246) = 5.51, near-uniform, while the student
        # was already agreeing with the teacher on 53.7% of decisions.
        # It was mostly measuring noise the policy is never asked about.
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
