"""Fit the plan scorer's weights against buildings finished.

    python tools/fit_scorer.py --generations 120

WHY BLACK-BOX AND NOT REGRESSION
--------------------------------
`tools/fit_heuristic.py` fits the LEAF evaluator by regression, and it
can: a solo battle is finite, so `expectimax.solve` gives exact labels
to fit against. A party plan has no such thing. Exact solve cannot
reach a party position, and every attempt in this project to
manufacture labels from a stronger search has lost end to end -- the P0
ranking head in `docs/ml-design.md`, and expert iteration, which
cloned the search's own play and finished 7.5% of buildings against
PPO's 35%.

So the objective here is the thing actually wanted -- buildings
finished -- measured directly. That side-steps the proxy problem
entirely: no label, no distillation, no ranking loss standing in for
play.

WHY THIS IS CHEAPER THAN IT SOUNDS
----------------------------------
`hybrid.climb` is deterministic: it walks the policy's ranked logits
rather than sampling, so the same weights on the same seeds give the
same answer every time. One evaluation over 180 buildings takes about
three seconds. Two coefficient vectors compared on identical seeds
differ EXACTLY -- there is no sampling noise to average away, which is
why a coarse grid earlier showed clean monotone gradients.

WHAT STILL GOES WRONG, AND THE GUARD FOR IT
-------------------------------------------
Determinism is not generalisation. Tuning on one seed set and reporting
the same set produced 69.4% for a configuration that was 66.1% on fresh
buildings -- a fitted result that evaporated. So the fit set and the
validation set are disjoint, validation is never optimised against, and
a candidate is only worth reporting if it holds on both.

WHICH WEIGHTS
-------------
`party_search.QUICK_W`, which `_quick_score` uses and therefore the
hybrid climb uses. `GREEDY_W` is deliberately NOT fitted here: it plays
the rollouts the SEARCH grades plans against, so it wants its own
objective (the search's finish rate) and its own run, at about a
hundred times the cost per evaluation.

THE OPTIMISER
-------------
A (1+lambda) evolution strategy with one-fifth-rule step adaptation.
Not CMA-ES, which is not installed and would be better; not a genetic
algorithm, which suits combinatorial or rugged spaces rather than five
smooth continuous weights. Restarts from the incumbent whenever the
step size collapses, so a plateau does not end the run early.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid                              # noqa: E402
from solver.search import party_search as ps                  # noqa: E402

KEYS = ("heal", "armed", "kill", "kill_threat", "prevent", "risk", "price")

# Step scale per weight, so a move means the same thing to `kill` at 120
# as to `heal` at 2 -- and so the two new terms, which start at zero,
# can actually travel. A cog threatens 8-15 damage a round, so a
# `kill_threat` of 5 is worth about half a flat kill; `risk` is charged
# per toon, against a landed-damage term in the tens.
SCALE = {"heal": 2.0, "armed": 1.0, "kill": 120.0, "kill_threat": 5.0,
         "prevent": 2.0, "risk": 20.0, "price": 1.0}


def finished(seeds, budget: int) -> float:
    """Percentage of buildings the climb finishes, at the current weights."""
    won = []
    for seed in seeds:
        e = env_mod.BattleEnv(rng=random.Random(seed),
                              sampler=env_mod.facility_position,
                              coordinated=True)
        obs, mask = e.reset()
        rng = random.Random(seed)
        plan, done, guard, info = None, False, 0, {}
        while not done and guard < 250:
            guard += 1
            if all(a is None for a in e.pending):
                plan = hybrid.climb(e.state, rng, budget=budget)
            action = plan[e.actor] if plan and e.actor < len(plan) else None
            index = env_mod.PASS_INDEX
            if action is not None and not action.is_pass:
                for i, cand in enumerate(env_mod.ACTIONS):
                    if (cand is not None and cand.track == action.track
                            and cand.level == action.level
                            and cand.target_index == action.target_index):
                        index = i
                        break
            if not mask[index]:
                index = env_mod.PASS_INDEX
            obs, mask, _r, done, info = e.step(index)
        won.append(1.0 if info.get("win") else 0.0)
    return statistics.mean(won) * 100.0


def evaluate(vector, seeds, budget: int) -> float:
    ps.QUICK_W = {k: float(v) for k, v in zip(KEYS, vector)}
    return finished(seeds, budget)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--generations", type=int, default=120)
    ap.add_argument("--children", type=int, default=8)
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--fit-seeds", type=int, default=240)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import numpy as np

    fit = list(range(31000, 31000 + args.fit_seeds))
    # Disjoint, never optimised against, and only looked at to decide
    # whether a candidate is real.
    validate = list(range(34000, 34000 + args.fit_seeds))

    rng = np.random.default_rng(args.seed)
    start = np.array([ps.QUICK_W[k] for k in KEYS], dtype=float)
    scale = np.array([SCALE[k] for k in KEYS], dtype=float)

    best = start.copy()
    best_score = evaluate(best, fit, args.budget)
    base_validate = evaluate(best, validate, args.budget)
    print("  start " + str({k: round(float(v), 2)
                            for k, v in zip(KEYS, best)}))
    print(f"  fit {best_score:.1f}%   validate {base_validate:.1f}%\n")

    sigma = 0.30
    began = time.time()
    for generation in range(1, args.generations + 1):
        children = []
        for _ in range(args.children):
            step = rng.normal(0.0, sigma, size=len(KEYS)) * scale
            child = np.maximum(best + step, 0.0)
            children.append((evaluate(child, fit, args.budget), child))
        score, child = max(children, key=lambda row: row[0])
        wins = sum(1 for s, _c in children if s > best_score)

        if score > best_score:
            best, best_score = child, score
        # One-fifth rule: grow the step while progress is common, shrink
        # it when it is not.
        sigma *= 1.15 if wins > len(children) / 5 else 0.85
        if sigma < 0.02:
            sigma = 0.30          # restart from the incumbent

        if generation % 10 == 0 or generation == args.generations:
            held = evaluate(best, validate, args.budget)
            print(f"    gen {generation:4d}  fit {best_score:5.1f}%  "
                  f"validate {held:5.1f}%  sigma {sigma:.3f}  "
                  f"({time.time() - began:.0f}s)", flush=True)

    final_fit = evaluate(best, fit, args.budget)
    final_validate = evaluate(best, validate, args.budget)
    weights = {k: round(float(v), 3) for k, v in zip(KEYS, best)}
    print(f"\n  best {weights}")
    print(f"    fit      {final_fit:5.1f}%   (started {best_score:.1f})")
    print(f"    validate {final_validate:5.1f}%   (started {base_validate:.1f})")
    print(f"\n  A gain on `fit` that does not show on `validate` is the "
          f"fitting this file exists to catch; report both or neither.")
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"QUICK_W": weights, "fit": final_fit,
             "validate": final_validate,
             "validate_before": base_validate}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
