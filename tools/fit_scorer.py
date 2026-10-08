"""Fit the plan scorer's weights against buildings finished.

    python tools/fit_scorer.py --generations 120

Black-box, not regression: unlike `tools/fit_heuristic.py`'s leaf
evaluator, a party plan has no exact-solve labels to fit against --
`expectimax.solve` cannot reach a party position, and every attempt to
manufacture labels from a stronger search has lost end to end (the P0
ranking head in `docs/ml-design.md`; expert iteration, which cloned the
search's own play and finished 7.5% of buildings against PPO's 35%). So
this optimises buildings finished directly, with no label in between.

Cheap because `hybrid.climb` is deterministic -- it walks the policy's
ranked logits rather than sampling, so two weight vectors on identical
seeds differ with no sampling noise. One evaluation over 180 buildings
takes about three seconds.

Determinism is not generalisation, though: tuning and reporting on the
same seed set once produced 69.4% for a configuration that was 66.1% on
fresh buildings. So the fit and validation seed sets are disjoint, the
validation set is never optimised against, and a candidate is only
reported if it holds on both.

Fits `ps_weights.QUICK_W` (what `_quick_score`, and therefore climb,
uses). `GREEDY_W` is deliberately NOT fitted here -- it grades the
rollouts the search scores plans against, wants its own objective (the
search's finish rate), and costs about a hundred times as much a run.

Optimiser: a (1+lambda) evolution strategy with one-fifth-rule step
adaptation -- not CMA-ES (not installed), not a GA (suited to rugged
combinatorial spaces rather than five smooth continuous weights).
Restarts from the incumbent whenever the step size collapses.
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
from solver.search import party_search as ps
from solver.search import weights as ps_weights                  # noqa: E402

KEYS = ("heal", "armed", "kill", "kill_threat", "prevent", "risk", "price")

# Step scale per weight, so a move means the same thing to `kill` at 120
# as to `heal` at 2. A cog threatens 8-15 damage a round, so a
# `kill_threat` of 5 is worth about half a flat kill; `risk` is charged
# per toon, against a landed-damage term in the tens.
SCALE = {"heal": 2.0, "armed": 1.0, "kill": 120.0, "kill_threat": 5.0,
         "prevent": 6.0, "risk": 20.0, "price": 1.0}

# `prevent`'s scale was widened 2.0 -> 6.0 after a sweep moved its
# shipped weight from 2.0 to 9.0: at 2.0 a step is only +/-0.6 (sigma
# 0.30), too small to cross that range, so the fit would have reported
# convergence when the weight had barely moved. A scale goes stale when
# the weight it's sized for does.


def play(seed, sampler, budget: int) -> bool:
    """One side, at the current weights. True if it cleared.

    Two fixed bugs mattered for what this fits: the round used to be
    detected with `all(a is None for a in e.pending)`, which can't tell
    "nobody has chosen" from "everyone held" (a HOLD also stores None --
    see `tools/trace_building.py`), so `e.rounds` is used instead. And
    fire actions had no branch, silently becoming a pass -- which made
    every boss position unscoreable, since the fitter graded a CEO side
    by watching the party ignore the slips it held.
    """
    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                          coordinated=True)
    obs, mask = e.reset()
    rng = random.Random(seed)
    plan, done, guard, info, seen = None, False, 0, {}, -1
    while not done and guard < 900:
        guard += 1
        if e.rounds != seen:
            seen = e.rounds
            plan = hybrid.climb(e.state, rng, budget=budget)
        action = plan[e.actor] if plan and e.actor < len(plan) else None
        index = env_mod.PASS_INDEX
        if action is not None and action.fire:
            index = env_mod._FIRE_INDEX.get(action.target_index,
                                            env_mod.PASS_INDEX)
        elif action is not None and not action.is_pass:
            for i, cand in enumerate(env_mod.ACTIONS):
                if (cand is not None and not cand.fire
                        and cand.track == action.track
                        and cand.level == action.level
                        and cand.target_index == action.target_index):
                    index = i
                    break
        if not mask[index]:
            index = env_mod.PASS_INDEX
        obs, mask, _r, done, info = e.step(index)
    return bool(info.get("win"))


def finished(seeds, budget: int, sets=None) -> float:
    """Mean clear rate over the objective's fight types.

    `sets` is a list of (sampler, weight). The weights fitted before
    this were fitted on BUILDINGS ALONE, which is why they are
    miscalibrated on a boss: nothing in the objective ever contained a
    Version 2.0, a pink slip or a cog above level 12.
    """
    if sets is None:
        sets = [(env_mod.facility_position, 1.0)]
    total = weight_total = 0.0
    for sampler, weight in sets:
        won = [1.0 if play(s, sampler, budget) else 0.0 for s in seeds]
        total += statistics.mean(won) * 100.0 * weight
        weight_total += weight
    return total / max(1e-9, weight_total)


def evaluate(vector, seeds, budget: int, sets=None) -> float:
    # MERGED, NOT REPLACED. `KEYS` is the seven weights fitted here, but
    # `QUICK_W` has nine; rebinding to just the seven used to drop
    # `waste` and `survive`, which `_score_leaf` reads, crashing the
    # scorer with `KeyError: 'waste'`. Merging keeps the unfitted two at
    # their shipped values.
    fitted = {k: float(v) for k, v in zip(KEYS, vector)}
    ps_weights.QUICK_W = dict(ps_weights.QUICK_W, **fitted)
    return finished(seeds, budget, sets)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--generations", type=int, default=120)
    ap.add_argument("--children", type=int, default=8)
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--fit-seeds", type=int, default=240)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--boss-weight", type=float, default=0.0,
                    help="weight on VP and CEO sides in the objective, "
                         "against 1.0 on buildings. The shipped weights "
                         "were fitted on buildings ALONE, so nothing in "
                         "the objective ever held a Version 2.0, a pink "
                         "slip or a cog above level 12")
    ap.add_argument("--ceo-leftovers", type=int, default=5,
                    help="banquet survivors for the CEO half of the boss "
                         "objective. 5 is the difficulty with room to "
                         "move in both directions; 0 is nearly solved and "
                         "10 is nearly hopeless, so neither carries a "
                         "usable gradient")
    args = ap.parse_args()

    import numpy as np

    fit = list(range(31000, 31000 + args.fit_seeds))
    # Disjoint, never optimised against, and only looked at to decide
    # whether a candidate is real.
    validate = list(range(34000, 34000 + args.fit_seeds))

    sets = [(env_mod.facility_position, 1.0)]
    if args.boss_weight > 0:
        from solver import ceo as ceo_mod
        from solver import vp as vp_mod
        ceo_mod.enable_big_cheese()

        def ceo_side(rng, _n=args.ceo_leftovers):
            ceo_mod.LEFTOVERS = _n
            return ceo_mod.ceo_position(rng)

        sets.append((vp_mod.vp_position, args.boss_weight / 2.0))
        sets.append((ceo_side, args.boss_weight / 2.0))
        print(f"  objective: buildings 1.0, VP and CEO "
              f"{args.boss_weight / 2.0:.2f} each "
              f"({args.ceo_leftovers} leftovers)")

    rng = np.random.default_rng(args.seed)
    start = np.array([ps_weights.QUICK_W[k] for k in KEYS], dtype=float)
    scale = np.array([SCALE[k] for k in KEYS], dtype=float)

    best = start.copy()
    best_score = evaluate(best, fit, args.budget, sets)
    base_validate = evaluate(best, validate, args.budget, sets)
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
            children.append((evaluate(child, fit, args.budget, sets), child))
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
            held = evaluate(best, validate, args.budget, sets)
            print(f"    gen {generation:4d}  fit {best_score:5.1f}%  "
                  f"validate {held:5.1f}%  sigma {sigma:.3f}  "
                  f"({time.time() - began:.0f}s)", flush=True)

    final_fit = evaluate(best, fit, args.budget, sets)
    final_validate = evaluate(best, validate, args.budget, sets)
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
