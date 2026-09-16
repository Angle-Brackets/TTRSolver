"""Paired sweep of LAST_COPY_UNITS on win rate. Common random numbers."""
import pathlib, random, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, ".")
POLICY = "solver/rl/ppo_facility.json"     # the shipped one, not a test arm

def _one(job):
    cell, value, seed = job
    from solver.rl import env as env_mod
    from solver.search import hybrid, weights
    hybrid._EXPORT = pathlib.Path(POLICY); hybrid._MODEL, hybrid._TRIED = None, False
    weights.LAST_COPY_UNITS = value
    if cell == "vp":
        from solver import vp as vp_mod
        sampler, budget = vp_mod.vp_position, 24
    elif cell == "street":
        def sampler(r):
            s = env_mod.mixed_position(r, 0.25, 0.25, 0.0)
            s.cogs_remaining = 0; s.kind = "street"; return s
        budget = 24
    else:
        sampler, budget = env_mod.facility_position, 8
    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler, coordinated=True)
    e.reset(); rng = random.Random(seed)
    plan, done, guard, info, seen = None, False, 0, {}, -1
    while not done and guard < 900:
        guard += 1
        if e.rounds != seen:
            seen = e.rounds; plan = hybrid.climb(e.state, rng, budget=budget)
        a = plan[e.actor] if plan and e.actor < len(plan) else None
        i = env_mod.PASS_INDEX
        if a is not None and a.fire:
            i = env_mod._FIRE_INDEX.get(a.target_index, env_mod.PASS_INDEX)
        elif a is not None and not a.is_pass:
            for k, c in enumerate(env_mod.ACTIONS):
                if (c is not None and not c.fire and c.track == a.track
                        and c.level == a.level and c.target_index == a.target_index):
                    i = k; break
        _o, _m, _r, done, info = e.step(i)
    return cell, value, seed, bool(info.get("win"))

def main(n=150, values=(0.0, 40.0)):
    from math import comb
    cells = ("vp",)
    jobs = [(c, v, 97000 + i) for c in cells for v in values for i in range(n)]
    res = {c: {v: {} for v in values} for c in cells}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for cell, value, seed, won in pool.map(_one, jobs):
            res[cell][value][seed] = won
    print("\n  LAST_COPY_UNITS, %d paired sides a cell, policy=%s\n"
          % (n, POLICY.split('/')[-1]))
    for cell in cells:
        base = res[cell][values[0]]
        seeds = sorted(base)
        print("    %s" % cell)
        for v in values:
            cur = res[cell][v]
            a = sum(cur[s] for s in seeds)
            up = [s for s in seeds if cur[s] and not base[s]]
            dn = [s for s in seeds if base[s] and not cur[s]]
            d = len(up) + len(dn)
            p = (sum(comb(d, i) for i in range(min(len(up), len(dn)) + 1))
                 / 2.0 ** d * 2) if d else 1.0
            tag = "  (baseline)" if v == values[0] else (
                "  +%d/-%d  p=%.3f" % (len(up), len(dn), min(1.0, p)))
            print("      %6.1f -> %5.1f%%%s" % (v, 100.0*a/len(seeds), tag))

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
