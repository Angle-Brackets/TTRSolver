"""Measure many policies on one fight, in parallel.

    python tools/eval_policies.py CEO0 a.json b.json c.json ...

WHY PARALLEL, AND WHY IT IS SAFE
--------------------------------
One evaluation pins about one core: the network is tiny and the time
goes to the pure-Python environment. Running twelve policies one after
another left eleven cores idle for the better part of an hour.

`hybrid` loads the policy from a module-level `_EXPORT` path, which a
single process can only point at one file at a time -- that is why the
sequential harnesses copy over `solver/rl/ppo_facility.json` and reset
`_MODEL`. Copying a shared file is exactly what cannot be parallelised,
so each worker instead repoints `_EXPORT` at its OWN policy before the
first load. No shared mutable file, no clobbering.

WHAT THE NUMBERS MEAN
---------------------
Boss rates carry enormous seed variance -- 23.3% to 62.5% across eight
policies differing only in their training seed -- so the ranking this
prints is mostly a ranking of luck. Read it to find candidates and
large regressions, then confirm the shortlist on seeds it did not
choose them on. Picking the maximum here and shipping it is the mistake
4b7da34 already recorded.
"""
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Clear of every training range: seed s uses env RNG seeds s*1000+i, so
# a policy trained at seed 39 owns 39000-39031. Sets numbered in that
# range share a random stream with the run being measured.
FIGHTS = {
    "CEO0": ("ceo", 0, 92000),
    "CEO2": ("ceo", 2, 92000),
    "CEO4": ("ceo", 4, 92000),
    "CEO6": ("ceo", 6, 92000),
    "CEO10": ("ceo", 10, 92000),
    "VP": ("vp", None, 91000),
    # Facilities run at the deployed climb budget of 8, not 24. A boss
    # side is worth thinking longer about and the shipped advisor spends
    # differently on the two, so measuring both at one budget would be
    # measuring a configuration nobody runs.
    "FAC": ("facility", None, 51000),
}
BUDGET = {"facility": 8}
N = 200


def _run_one(job):
    label, path, fight, n_left, base, count = job
    from solver import ceo as ceo_mod, vp as vp_mod
    from solver.rl import env as env_mod
    from solver.search import hybrid

    # Point THIS process at its own policy, before anything loads one.
    hybrid._EXPORT = Path(path)
    hybrid._MODEL, hybrid._TRIED = None, False

    if fight == "ceo":
        ceo_mod.enable_big_cheese()

        def sampler(rng):
            ceo_mod.LEFTOVERS = n_left
            return ceo_mod.ceo_position(rng)
    elif fight == "facility":
        sampler = env_mod.facility_position
    else:
        sampler = vp_mod.vp_position
    budget = BUDGET.get(fight, 24)

    won = 0
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
        won += bool(info.get("win"))
    return label, won / count


def main(argv):
    # `CEO0` uses the default seed base; `CEO0:95000` moves it. Selecting
    # a candidate on one base and confirming it on another is the whole
    # discipline here -- the maximum of twelve on any single set is a
    # measurement of luck as much as of policy.
    fight, _, override = argv[0].partition(":")
    paths = argv[1:]
    kind, n_left, base = FIGHTS[fight]
    if override:
        base = int(override)
        fight = f"{fight}@{base}"
    jobs = [(Path(p).stem, p, kind, n_left, base, N) for p in paths]

    print(f"  {fight}, {N} sides a policy, {len(jobs)} policies in parallel\n")
    rows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        for label, rate in pool.map(_run_one, jobs):
            rows.append((rate, label))
            print(f"    {label:<18} {rate:6.1%}", flush=True)

    rows.sort(reverse=True)
    print(f"\n  ranked ({fight}) -- seed luck, not a ship decision:")
    for rate, label in rows:
        print(f"    {label:<18} {rate:6.1%}")
    if rows:
        lo, hi = rows[-1][0], rows[0][0]
        print(f"\n    spread {lo:.1%} to {hi:.1%}"
              f"  ({(hi - lo) * 100:.0f} points across seeds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main([a for a in sys.argv[1:] if not a.startswith("--")]))
