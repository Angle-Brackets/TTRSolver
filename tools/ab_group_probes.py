"""Group-aware track probes, paired on identical positions.

Comparing aggregate rates across two code versions gave +2.5 on one CEO
base and -4.5 on another. Only the games the two arms DISAGREE about
carry information, so this plays both arms on the same seeds and runs a
McNemar test on the discordant pairs.

Also prints the discordant SEEDS, so a case where the wider menu loses a
side the narrow one won can be traced round by round.

Note the __main__ guard: Windows spawns rather than forks, so without it
each worker re-imports this module, re-enters the pool and dies.
"""
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from math import comb

sys.path.insert(0, r"c:/Users/ankit/OneDrive/Desktop/Appu/Programs/TTRSolver")

POL = r"C:/Users/ankit/AppData/Local/Temp/claude/scratch/policies/v6_s36.json"
CELLS = [("FAC", None, 51000), ("FAC", None, 53000),
         ("FAC", None, 57000)]
N = 200
# The wider menu is ~12 entries a seat; two seats is 24, which IS the
# budget -- so it gets one sweep and cannot iterate, while the narrow
# menu gets one and a half. If that is the whole story, paying for the
# extra menu should restore it.
BUDGETS = [8, 15, 36]


def _one(job):
    fight, n_left, base, count, group_probes, budget = job
    from pathlib import Path
    from solver import ceo as ceo_mod
    from solver.rl import env as env_mod
    from solver.search import hybrid

    hybrid._EXPORT = Path(POL)
    hybrid._MODEL, hybrid._TRIED = None, False
    hybrid.GROUP_GAGS_PROBED_SEPARATELY = group_probes
    ceo_mod.enable_big_cheese()

    if fight == "FAC":
        sampler = env_mod.facility_position
    else:
        def sampler(rng):
            ceo_mod.LEFTOVERS = n_left
            return ceo_mod.ceo_position(rng)

    out = []
    for seed in range(base, base + count):
        e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                              coordinated=True)
        e.reset()
        rng = random.Random(seed)
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
                        i = k
                        break
            _o, _m, _r, done, info = e.step(i)
        out.append(bool(info.get("win")))
    return (fight, n_left, base, group_probes, budget), out


def main():
    jobs = [(f, n, b, N, g, bu) for (f, n, b) in CELLS
            for bu in BUDGETS for g in (False, True)]
    res = {}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for key, out in pool.map(_one, jobs):
            res[key] = out

    print(f"  group-aware probes, paired, {N} sides a cell\n")
    print(f"  {'cell':<14}{'budget':>7}{'off':>8}{'on':>8}{'delta':>9}  up/down      p")
    allup = alldn = 0
    losers = []
    for bu in BUDGETS:
     for (f, n, b) in CELLS:
        a = res[(f, n, b, False, bu)]
        c = res[(f, n, b, True, bu)]
        ra, rc = sum(a) / N, sum(c) / N
        up = [b + i for i, (x, y) in enumerate(zip(a, c)) if y and not x]
        dn = [b + i for i, (x, y) in enumerate(zip(a, c)) if x and not y]
        losers += [(f, n, s) for s in dn]
        allup += len(up)
        alldn += len(dn)
        m = len(up) + len(dn)
        k = min(len(up), len(dn))
        p = (min(1.0, 2.0 * sum(comb(m, i) for i in range(k + 1)) / 2 ** m)
             if m else 1.0)
        print(f"  {f}@{b:<9}{bu:>7}{ra:7.1%}{rc:7.1%}{rc - ra:+8.1%}"
              f"  {len(up):>3}/{len(dn):<3}   p={p:.3f}")

    m = allup + alldn
    k = min(allup, alldn)
    p = (min(1.0, 2.0 * sum(comb(m, i) for i in range(k + 1)) / 2 ** m)
         if m else 1.0)
    print(f"\n  POOLED: {allup} up / {alldn} down   p={p:.4f}   "
          f"{'SIGNIFICANT' if p < 0.05 else 'not significant'}")
    print(f"\n  sides the WIDER menu lost that the narrow one won:")
    for f, n, s in losers[:12]:
        print(f"    {f} {n} leftovers, seed {s}")


if __name__ == "__main__":
    main()
