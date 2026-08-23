"""Measure a candidate policy against the incumbent on EVERY fight.

    python tools/ship_gate.py incumbent.json candidate.json

WHY THIS EXISTS
---------------
0822c00 shipped a policy on a facility-only confirmation -- +1.2% over
1600 paired positions, p = 0.09 -- and it cost 16.5 points on the CEO
and 22.5 at two banquet leftovers. Facilities were level, so the
evidence that approved the swap could not see the damage. 76e2e05
reverted it.

The lesson is not "measure more". It is that a policy is deployed across
several distributions that a single held-out set does not represent, and
boss sides are the ones that differ most: they are the only positions
with Version 2.0 cogs, pink slips as standard, and cogs above level 12.
A gate that cannot see them cannot approve a swap.

READING THE OUTPUT, AND THE TRAP IN IT
--------------------------------------
CEO seed variance is enormous. Eight policies differing only in their
training seed spanned 23.3% to 62.5% on CEO 0 while their buildings
rates sat inside a two-point band. So:

  * A CEO difference of ten points between two policies is NOT evidence
    that one is better. It is inside the noise of which seed you drew.
  * Picking the best of N seeds on the CEO has been measured and
    refuted (4b7da34) -- the selection winner lost on held-out sides.
  * What this gate is for is catching a REGRESSION large enough to
    matter, not ranking two good policies.

Facilities are paired and get a McNemar test, because there the effect
sizes are small and the noise is low enough to resolve them. Boss cells
are reported as rates with the seed-variance caveat attached, because
pretending a p-value there means something is how a 39-point spread gets
read as a finding.
"""
import random
import shutil
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from solver import ceo as ceo_mod, vp as vp_mod                # noqa: E402
from solver.rl import env as env_mod                           # noqa: E402
from solver.search import hybrid                               # noqa: E402

LIVE = ROOT / "solver/rl/ppo_facility.json"

FACILITY_SETS = (51000, 53000, 57000, 59000)
FACILITY_N = 400
BOSS_BASE = 92000
BOSS_N = 200
VP_BASE = 91000


def _play(seed, sampler, budget):
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
    return bool(info.get("win"))


def _ceo_sampler(n):
    def s(rng):
        ceo_mod.LEFTOVERS = n
        return ceo_mod.ceo_position(rng)
    return s


def _load(path):
    shutil.copy(path, LIVE)
    hybrid._MODEL, hybrid._TRIED = None, False


def _mcnemar(a, b):
    up = sum(1 for x, y in zip(a, b) if y and not x)
    dn = sum(1 for x, y in zip(a, b) if x and not y)
    n = up + dn
    if not n:
        return 0, 0, 1.0
    k = min(up, dn)
    return up, dn, min(1.0, 2.0 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def main(paths):
    old, new = paths[0], paths[1]
    ceo_mod.enable_big_cheese()

    seeds = [s + i for s in FACILITY_SETS for i in range(FACILITY_N)]
    cells = [("facility", env_mod.facility_position, seeds, 8),
             ("VP", vp_mod.vp_position,
              [VP_BASE + i for i in range(BOSS_N)], 24),
             ("CEO 0", _ceo_sampler(0),
              [BOSS_BASE + i for i in range(BOSS_N)], 24),
             ("CEO 2", _ceo_sampler(2),
              [BOSS_BASE + i for i in range(BOSS_N)], 24)]

    results = {}
    for label, path in (("old", old), ("new", new)):
        _load(path)
        for name, sampler, sds, budget in cells:
            results[(label, name)] = [_play(s, sampler, budget) for s in sds]
            rate = sum(results[(label, name)]) / len(sds)
            print(f"    {Path(path).stem:<18} {name:<10} {rate:6.1%}",
                  flush=True)

    print(f"\n  {Path(new).stem} vs {Path(old).stem}\n")
    print(f"    {'cell':<10}{'old':>8}{'new':>8}{'delta':>9}   verdict")
    for name, _s, sds, _b in cells:
        a, b = results[("old", name)], results[("new", name)]
        ra, rb = sum(a) / len(sds), sum(b) / len(sds)
        if name == "facility":
            up, dn, p = _mcnemar(a, b)
            verdict = (f"{up}/{dn} discordant, p={p:.3f}"
                       + ("  REGRESSION" if p < 0.05 and rb < ra else ""))
        else:
            # No p-value on purpose -- see the module docstring.
            verdict = ("seed noise dominates; flag only large drops"
                       if abs(rb - ra) < 0.10
                       else "LARGE DROP -- do not ship without explaining it"
                       if rb < ra else "large gain -- verify on other seeds")
        print(f"    {name:<10}{ra:7.1%}{rb:7.1%}{rb - ra:+8.1%}   {verdict}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__.splitlines()[2])
        raise SystemExit(2)
    raise SystemExit(main(args))
