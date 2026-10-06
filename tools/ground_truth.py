"""A Monte-Carlo benchmark for judging moves, and a score for any judge.

    python tools/ground_truth.py build --n 600 --out gt.pkl
    python tools/ground_truth.py score gt.pkl

BUILD plays solo VPs with `hybrid.climb` up to a random round, then takes
the candidates a judge would choose between -- climb's own top plans plus
random entries from the rest of its menu and the pass -- and plays each
to the end of the fight from that board, many times, with common random
numbers (rollout k uses the same seeds for every candidate). Successive
halving spends the rollouts where candidates are close.

SCORE reports, for each judge, how many cogs its pick defeats over the
AVERAGE candidate, chosen on one half of the rollouts and scored on the
other -- so picking the best on the same noisy means cannot flatter it.

What this benchmark showed (797 positions, nine candidates each):

    ceiling (best on half A)          +1.36 cogs a decision
    best of 4 random menu entries     +0.92
    best of the scorer's top 4        +0.70
    climb's pick (the scorer's #1)    +0.37

and the best move lay outside the scorer's top four in 49% of positions.
That is what motivated `playout.wide_candidates`. A judge fitted to these
labels then failed in play (7% -> 3.6%, 0.4%): a one-decision label holds
only while the old player plays on. Use it to rank judges, and confirm
anything with `tools/sweep.py`.
"""
from __future__ import annotations

import argparse
import copy
import math
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOTAL_COGS = 40
TOP = 4
EXTRA = 4
STAGES = (10, 25, 40)


def _defeated(env):
    s = env.state
    return TOTAL_COGS - sum(1 for c in s.cogs if c.hp > 0) - len(s.holdout) - s.cogs_remaining


def _finish(env, rng):
    from solver.search import hybrid, playout

    done, info, guard = False, {}, 0
    while not done and guard < 400:
        guard += 1
        plan = hybrid.climb(playout._view(env.state), rng, budget=24)
        done, info = playout.step_round(env, plan)
    return _defeated(env)


def _key(plan):
    return tuple(repr(a) for a in plan)


def build_one(seed):
    from solver.rl import env as env_mod
    from solver.search import hybrid, playout
    from solver.state import Action

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sweep import _sampler

    sample, _coord, cap = _sampler("solo-vp")
    env = env_mod.BattleEnv(rng=random.Random(seed), sampler=sample,
                            coordinated=True, max_rounds=cap)
    env.reset()
    pick = random.Random(seed * 7 + 1)
    target, rng, done = pick.randint(0, 45), random.Random(seed), False
    while not done and env.rounds < target:
        done, _ = playout.step_round(env, hybrid.climb(playout._view(env.state), rng, budget=24))
    if done:
        return None

    seen, real = {}, hybrid._judge

    def spy(st, plan, deep):
        value = real(st, plan, deep)
        seen.setdefault(_key(plan), (list(plan), value))
        return value

    hybrid._judge = spy
    try:
        chosen = hybrid.climb(playout._view(env.state), random.Random(seed + 99), budget=24)
    finally:
        hybrid._judge = real
    if chosen is None:
        return None
    menu = [p for p, _v in sorted(seen.values(), key=lambda pv: -pv[1])]
    cands, keys = [], set()
    for plan in [list(chosen)] + menu:
        if _key(plan) not in keys and len(cands) < TOP:
            keys.add(_key(plan))
            cands.append({"plan": plan, "chosen": not cands, "extra": False, "d": []})
    rest = [p for p in menu if _key(p) not in keys]
    pick.shuffle(rest)
    for plan in rest[:EXTRA] + [[Action(track=None)]]:
        if _key(plan) not in keys:
            keys.add(_key(plan))
            cands.append({"plan": plan, "chosen": False, "extra": True, "d": []})
    if len(cands) < 2:
        return None

    alive, done_k = list(cands), 0
    for stage, upto in enumerate(STAGES):
        for k in range(done_k, upto):
            for c in alive:
                ek = copy.deepcopy(env)
                ek.rng = random.Random(seed * 100003 + k * 2)
                finished, _info = playout.step_round(ek, c["plan"])
                c["d"].append(_defeated(ek) if finished
                              else _finish(ek, random.Random(seed * 100003 + k * 2 + 1)))
        done_k = upto
        if stage + 1 < len(STAGES):
            alive.sort(key=lambda c: -sum(c["d"]) / len(c["d"]))
            alive = alive[:max(2, (len(alive) + 1) // 2)]
    return {"seed": seed, "round": env.rounds, "view": playout._view(env.state), "cands": cands}


def score(path):
    import numpy as np

    from solver.search import party_search as ps

    rows = [r for r in pickle.load(open(path, "rb")) if r and len(r["cands"]) >= 2]

    def half(c, h):
        values = c["d"][h::2]
        return float(np.mean(values)) if values else float("nan")

    def gain(pick):
        out = []
        for r in rows:
            cs = [c for c in r["cands"] if c["d"][1::2]]
            base = np.mean([half(c, 1) for c in cs])
            out.append(half(pick(cs, r), 1) - base)
        return np.mean(out), np.std(out) / math.sqrt(len(out))

    judges = {
        "ceiling (best on half A)": lambda cs, r: max(cs, key=lambda c: half(c, 0)),
        "climb's pick": lambda cs, r: next((c for c in cs if c["chosen"]), cs[0]),
        "one-round scorer": lambda cs, r: max(cs, key=lambda c: ps._quick_score(r["view"], c["plan"])),
        "best of the scorer's top 4": lambda cs, r: max((c for c in cs if not c["extra"]), key=lambda c: half(c, 0)),
        "best of the random extras": lambda cs, r: max((c for c in cs if c["extra"]) or cs, key=lambda c: half(c, 0)),
    }
    print(f"{len(rows)} positions; cogs defeated over the average candidate, "
          f"chosen on half A, scored on half B")
    for name, pick in judges.items():
        g, se = gain(pick)
        print(f"  {name:30s} {g:+.3f}  (se {se:.3f})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=600)
    b.add_argument("--base", type=int, default=50000)
    b.add_argument("--out", required=True)
    b.add_argument("--workers", type=int, default=10)
    s = sub.add_parser("score")
    s.add_argument("path")
    args = ap.parse_args()

    if args.cmd == "score":
        score(args.path)
        return 0
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        records = [r for r in pool.map(build_one, range(args.base, args.base + args.n)) if r]
    pickle.dump(records, open(args.out, "wb"))
    print(f"{len(records)} positions written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
