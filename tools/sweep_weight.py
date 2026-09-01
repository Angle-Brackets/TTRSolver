"""Sweep QUICK_W["risk"] on the CORRECTED rules, paired.

    python risk_sweep.py 0 2 5 10 20

The ES that zeroed this ran 2026-08-17, before the Railroad, two-trap
and simultaneous-Lure fixes. The last one is why the old answer cannot
stand: a group Lure used to re-catch a cog whose trap had just sprung,
so "the plan leaves a cog awake" was a state the simulator could barely
produce, and an optimiser will not price a risk the model never makes.

Paired on identical positions like `paired_confirm`, because the effect
being looked for is a point or two and independent rates cannot see it.
Weight 0 is the baseline and every other value is compared against it.
"""
import random
import statistics
import sys
from math import comb
from pathlib import Path

ROOT = r"C:/Users/ankit/OneDrive/Desktop/Appu/Programs/TTRSolver"
sys.path.insert(0, ROOT)

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid, party_search as ps          # noqa: E402
from solver.search import weights as ps_weights

SETS = (71000, 73000, 77000)
N = 300


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
            plan = hybrid.climb(e.state, rng, budget=24)
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


def main(values):
    seeds = [s + i for s in SETS for i in range(N)]
    print(f"  {len(seeds)} positions, paired, climb budget 8")
    print(f"  sweeping QUICK_W['risk'] on the corrected rules\n")
    rows = {}
    for v in values:
        ps_weights.QUICK_W["risk"] = v
        res = [play(s) for s in seeds]
        rows[v] = res
        per = [sum(res[j*N:(j+1)*N])/N for j in range(len(SETS))]
        print(f"    risk={v:<5} {sum(res)/len(res):6.1%}   "
              + "  ".join(f"{p:5.1%}" for p in per), flush=True)
    ps_weights.QUICK_W["risk"] = 0.0

    base = rows[values[0]]
    print(f"\n  vs risk={values[0]}:")
    for v in values[1:]:
        b = rows[v]
        up = sum(1 for x, y in zip(base, b) if y and not x)
        dn = sum(1 for x, y in zip(base, b) if x and not y)
        n = up + dn
        p = (min(1.0, 2.0 * sum(comb(n, i) for i in range(min(up, dn) + 1))
                 / 2 ** n) if n else 1.0)
        per = [sum(b[j*N:(j+1)*N])/N - sum(base[j*N:(j+1)*N])/N
               for j in range(len(SETS))]
        agree = all(x > 0 for x in per) or all(x < 0 for x in per)
        print(f"    risk={v:<5} {(sum(b)-sum(base))/len(seeds):+6.1%}"
              f"   discordant {n:>4}   p={p:.3f}"
              f"   {'ALL AGREE' if agree else 'mixed signs'}"
              f"   {'SIGNIFICANT' if p < 0.05 else ''}")
    return 0


if __name__ == "__main__":
    vals = [float(x) for x in sys.argv[1:] if not x.startswith("--")]
    raise SystemExit(main(vals or [0.0, 2.0, 5.0, 10.0, 20.0]))
