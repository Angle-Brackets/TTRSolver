"""Generate expert trajectories: let the SEARCH play, and record it.

    python tools/gen_expert.py --episodes 400

Expert iteration, the AlphaZero shape. PPO could not discover Trap+Lure
because the payoff is a round away and conditional on a roll -- with 246
actions to choose between, the sequence is essentially never explored,
so the returns never contain it and the critic correctly grades those
positions as worthless *to that policy*. Curriculum moved the start
state closer and did not fix it; the lay rate stayed at 9.3%.

The search does not have to discover the sequence. It simulates the
trap trigger directly. So let it play, write down what it did, and train
on that.

WHY THIS IS NOT THE DISTILLATION THAT ALREADY FAILED
----------------------------------------------------
`docs/ml-design.md` P0 trained a ranker on shortlist orderings at
independently sampled positions, and it lost end to end. Two differences
here, and both matter:

* **Trajectories, not positions.** States are recorded along
  search-guided play, so the training distribution is the one a policy
  following the search would actually visit. Sampling positions
  independently trains on states no good player reaches.
* **Moves, not rankings.** The label is the move the search chose and
  the value it assigned, which is what a policy needs. The ranking
  labels were noisy sampled estimates whose top entries sat within noise
  of each other.

The teacher is `party_search.evaluate`. It is not optimal -- depth 1
with a rollout continuation -- so this is imitation of something
imperfect, and the ceiling is the search's own play. That is the honest
limit and it is still far above a policy that never lays a trap.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.party import Mode                                  # noqa: E402
from solver.rl import env as env_mod                           # noqa: E402
from solver.search import party_search as ps                   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".expert_traj.json"


def action_index(action):
    if action is None or action.is_pass:
        return env_mod.PASS_INDEX
    for i, cand in enumerate(env_mod.ACTIONS):
        if (cand is not None and cand.track == action.track
                and cand.level == action.level
                and cand.target_index == action.target_index):
            return i
    return env_mod.PASS_INDEX


def one_episode(args):
    seed, samples, max_plans, hard, strange, combo, coordinated = args
    rng = random.Random(seed)
    sampler = (lambda r: env_mod.mixed_position(r, hard, strange, combo))
    e = env_mod.BattleEnv(rng=rng, sampler=sampler, coordinated=coordinated)
    obs, mask = e.reset()
    rows, done, guard = [], False, 0

    while not done and guard < 60:
        guard += 1
        # The expert. In coordinated mode the search returns a joint
        # plan and we take the entry for whoever is deciding, so the
        # policy learns each seat's move in the plan the search chose.
        mode = Mode.COORDINATED if coordinated else Mode.PICKUP
        value, plan = ps.evaluate(e.state, depth=1, mode=mode,
                                  samples=samples, max_plans=max_plans,
                                  rng=rng)
        seat = e.actor if coordinated else 0
        action = plan[seat] if plan and seat < len(plan) else None
        index = action_index(action)
        if not mask[index]:
            index = env_mod.PASS_INDEX
        rows.append({"obs": obs, "act": index, "val": value})
        obs, mask, _r, done, _info = e.step(index)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--samples", type=int, default=12)
    ap.add_argument("--max-plans", type=int, default=14)
    ap.add_argument("--hard-fraction", type=float, default=0.3)
    ap.add_argument("--strange-fraction", type=float, default=0.25)
    ap.add_argument("--combo-fraction", type=float, default=0.2)
    ap.add_argument("--coordinated", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    jobs = [(args.seed * 7919 + i, args.samples, args.max_plans,
             args.hard_fraction, args.strange_fraction, args.combo_fraction,
             args.coordinated) for i in range(args.episodes)]
    started, rows = time.time(), []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for n, got in enumerate(pool.map(one_episode, jobs, chunksize=1), 1):
            rows.extend(got)
            if n % 25 == 0:
                rate = n / (time.time() - started)
                print(f"  {n}/{len(jobs)} episodes  {len(rows)} decisions  "
                      f"eta {(len(jobs) - n) / max(rate, 1e-9):.0f}s",
                      flush=True)

    Path(args.out).write_text(json.dumps(
        {"rows": rows, "obs_dim": env_mod.OBS_DIM,
         "n_actions": len(env_mod.ACTIONS),
         "coordinated": args.coordinated}), encoding="utf-8")
    print(f"\n  {len(rows)} decisions from {len(jobs)} episodes in "
          f"{time.time() - started:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
