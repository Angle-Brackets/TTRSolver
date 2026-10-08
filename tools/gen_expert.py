"""Generate expert trajectories: let the SEARCH play, and record it.

    python tools/gen_expert.py --episodes 400

Expert iteration, the AlphaZero shape. PPO could not discover Trap+Lure
because the payoff is a round away and conditional on a roll -- with 246
actions to choose between the sequence is essentially never explored, so
the critic correctly grades those positions as worthless *to that
policy*. Curriculum moved the start state closer and didn't fix it; the
lay rate stayed at 9.3%. The search doesn't have to discover the
sequence -- it simulates the trap trigger directly -- so let it play,
write down what it did, and train on that.

NOT THE DISTILLATION THAT ALREADY FAILED: `docs/ml-design.md` P0 trained
a ranker on shortlist orderings at independently sampled positions and
lost end to end. Two differences here matter. **Trajectories, not
positions** -- states are recorded along search-guided play, so training
sees the distribution a policy following the search would actually
visit, rather than states no good player reaches. **Moves, not
rankings** -- the label is the move the search chose and the value it
assigned, what a policy actually needs, rather than noisy sampled
rankings whose top entries sit within noise of each other.

The teacher is `party_search.evaluate`: depth 1 with a rollout
continuation, not optimal, so this is imitation of something imperfect
and the ceiling is the search's own play. Still far above a policy that
never lays a trap.
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
    (seed, samples, max_plans, hard, strange, combo, coordinated,
     facility) = args
    rng = random.Random(seed)
    def sampler(r, _h=hard, _s=strange, _c=combo, _f=facility):
        # Facility positions matter most here: the search's edge over
        # PPO is almost entirely multi-floor play (heals and traps whose
        # payoff arrives a round later), which street-only trajectories
        # would not contain.
        if r.random() < _f:
            return env_mod.facility_position(r)
        state = env_mod.mixed_position(r, _h, _s, _c)
        state.cogs_remaining = 0
        state.kind = "street"
        return state
    e = env_mod.BattleEnv(rng=rng, sampler=sampler, coordinated=coordinated)
    obs, mask = e.reset()
    rows, done, guard = [], False, 0

    # 400 decisions is generous -- the env already truncates per floor,
    # so this just needs to not cut a multi-floor building short.
    while not done and guard < 400:
        guard += 1
        # The expert. Coordinated mode returns a joint plan; take the
        # entry for whoever is deciding so the policy learns each seat's
        # move in the plan the search chose.
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
    ap.add_argument("--facility-fraction", type=float, default=0.5,
                    help="share of episodes that are multi-floor "
                         "facilities, where the search's edge lives")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    jobs = [(args.seed * 7919 + i, args.samples, args.max_plans,
             args.hard_fraction, args.strange_fraction, args.combo_fraction,
             args.coordinated, args.facility_fraction)
            for i in range(args.episodes)]
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
