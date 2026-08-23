"""Shipped vs one retrained policy, PAIRED on identical positions.

    python paired_confirm.py old.json new.json

WHY PAIRED, AND WHY FRESH SEEDS
-------------------------------
`eval_retrain.py` reports each policy's rate on three sets and eyeballs
the gap. At 120 games a set the standard error on a single rate is about
4 points, so it cannot resolve the 1-2 point differences it prints -- and
picking the best of six seeds on those same sets is selection, not
measurement. This project has been burned by exactly that before.

Two fixes here. Both policies play the SAME positions, so the comparison
is paired and only the games they DISAGREE on carry information -- a
McNemar test on the discordant pairs, which is far more sensitive than
comparing two independent-looking rates. And the seeds are ones no
policy was chosen on, so this confirms rather than re-selects.
"""
import random
import shutil
import statistics
import sys
from pathlib import Path

ROOT = r"C:/Users/ankit/OneDrive/Desktop/Appu/Programs/TTRSolver"
sys.path.insert(0, ROOT)

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid                              # noqa: E402

LIVE = Path(ROOT) / "solver/rl/ppo_facility.json"
# Deliberately NOT 31000/33000/39000 -- those chose the candidate.
SETS = (51000, 53000, 57000, 59000)
N = 400


def play(seed):
    e = env_mod.BattleEnv(rng=random.Random(seed),
                          sampler=env_mod.facility_position,
                          coordinated=True)
    obs, mask = e.reset()
    rng = random.Random(seed)
    plan, done, guard, info, seen = None, False, 0, {}, -1
    while not done and guard < 250:
        guard += 1
        if e.rounds != seen:
            seen = e.rounds
            plan = hybrid.climb(e.state, rng, budget=8)
        a = plan[e.actor] if plan and e.actor < len(plan) else None
        idx = env_mod.PASS_INDEX
        if a is not None and not a.is_pass:
            for i, c in enumerate(env_mod.ACTIONS):
                if (c is not None and c.track == a.track
                        and c.level == a.level
                        and c.target_index == a.target_index):
                    idx = i
                    break
        if not mask[idx]:
            idx = env_mod.PASS_INDEX
        obs, mask, _r, done, info = e.step(idx)
    return bool(info.get("win"))


def run(path, seeds):
    shutil.copy(path, LIVE)
    hybrid._MODEL, hybrid._TRIED = None, False
    return [play(s) for s in seeds]


def main(paths):
    old, new = paths[0], paths[1]
    seeds = [start + i for start in SETS for i in range(N)]
    print(f"  {len(seeds)} positions, paired, climb budget 8")
    print(f"  fresh seeds {SETS} -- not the sets the candidate was picked on\n")

    a = run(old, seeds)
    print(f"    {Path(old).stem:<18} {sum(a)/len(a):6.1%}", flush=True)
    b = run(new, seeds)
    print(f"    {Path(new).stem:<18} {sum(b)/len(b):6.1%}", flush=True)

    # Only the disagreements carry information.
    new_only = sum(1 for x, y in zip(a, b) if y and not x)
    old_only = sum(1 for x, y in zip(a, b) if x and not y)
    n = new_only + old_only
    print(f"\n    agree on {len(seeds) - n} of {len(seeds)}")
    print(f"    {Path(new).stem} wins alone: {new_only}")
    print(f"    {Path(old).stem} wins alone: {old_only}")

    # Exact two-sided binomial (McNemar) on the discordant pairs.
    if n:
        from math import comb
        k = min(new_only, old_only)
        p = min(1.0, 2.0 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
        print(f"    difference {(sum(b) - sum(a)) / len(seeds):+.1%}"
              f"   McNemar p = {p:.3f}"
              f"   {'SIGNIFICANT' if p < 0.05 else 'not significant'}")

    # Per-set breakdown, to see whether the sign is stable.
    print()
    for j, start in enumerate(SETS):
        lo, hi = j * N, (j + 1) * N
        da = sum(a[lo:hi]) / N
        db = sum(b[lo:hi]) / N
        print(f"    set {start}:  {da:6.1%} -> {db:6.1%}   {db - da:+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main([x for x in sys.argv[1:] if not x.startswith("--")]))
