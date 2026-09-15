"""ppo_v4 (kind one-hot live) against ppo_v4_nokind (bits zeroed).

Identical width, seed and settings; the ONLY difference is whether the
agent can see which fight it is in. Common random numbers, so each cell
is a paired comparison and the sign test is on discordant seeds.
"""
import pathlib, random, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, ".")

ARMS = {"kinds": "solver/rl/ppo_v4.json",
        "nokind": "solver/rl/ppo_v4_nokind.json"}


def _one(job):
    cell, arm, seed = job
    from solver import ceo as ceo_mod, vp as vp_mod
    from solver.rl import env as env_mod
    from solver.search import hybrid

    hybrid._EXPORT = pathlib.Path(ARMS[arm])
    hybrid._MODEL, hybrid._TRIED = None, False

    if cell == "street":
        def sampler(r):
            s = env_mod.mixed_position(r, 0.25, 0.25, 0.0)
            s.cogs_remaining = 0
            s.kind = "street"
            return s
        budget = 24
    elif cell == "facility":
        sampler, budget = env_mod.facility_position, 8
    else:
        def sampler(r):
            ceo_mod.LEFTOVERS = 0
            return ceo_mod.ceo_position(r)
        budget = 24

    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                          coordinated=True)
    e.reset(); rng = random.Random(seed)
    plan, done, guard, info, seen = None, False, 0, {}, -1
    while not done and guard < 900:
        guard += 1
        if e.rounds != seen:
            seen = e.rounds
            plan = hybrid.climb(e.state, rng, budget=budget)
        a = plan[e.actor] if plan and e.actor < len(plan) else None
        i = env_mod.PASS_INDEX
        if a is not None and a.fire:
            i = env_mod._FIRE_INDEX.get(a.target_index, env_mod.PASS_INDEX)
        elif a is not None and not a.is_pass:
            for k, c in enumerate(env_mod.ACTIONS):
                if (c is not None and not c.fire and c.track == a.track
                        and c.level == a.level
                        and c.target_index == a.target_index):
                    i = k; break
        _o, _m, _r, done, info = e.step(i)
    return cell, arm, seed, bool(info.get("win"))


def main(n=150):
    from math import comb
    cells = ("street", "facility")
    jobs = [(c, a, 95000 + i) for c in cells for a in ARMS for i in range(n)]
    res = {c: {a: {} for a in ARMS} for c in cells}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for cell, arm, seed, won in pool.map(_one, jobs):
            res[cell][arm][seed] = won
    print("\n  ppo_v4 (kinds) vs ppo_v4_nokind -- %d paired sides a cell\n" % n)
    for cell in cells:
        k, nk = res[cell]["kinds"], res[cell]["nokind"]
        seeds = sorted(set(k) & set(nk))
        a, b = sum(k[s] for s in seeds), sum(nk[s] for s in seeds)
        up = [s for s in seeds if k[s] and not nk[s]]
        dn = [s for s in seeds if nk[s] and not k[s]]
        d = len(up) + len(dn)
        p = (sum(comb(d, i) for i in range(min(len(up), len(dn)) + 1))
             / 2.0 ** d * 2) if d else 1.0
        print("    %-9s kinds %5.1f%%   nokind %5.1f%%   +%d/-%d discordant  p=%.3f"
              % (cell, 100.0*a/len(seeds), 100.0*b/len(seeds),
                 len(up), len(dn), min(1.0, p)))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
