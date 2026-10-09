"""How deep the exact search reaches, and whether a speedup changes its answer.

    python tools/search_bench.py depth --limit 60          # time per depth by cog count
    python tools/search_bench.py agree --depth 3 --beam 6 --cogs 1 2  # a shortcut vs exact
    python tools/search_bench.py fight --depth 3           # per-decision time over fights
    python tools/search_bench.py stable --max-depth 6      # does the move change with depth?

POSITIONS are fixed by seed: a maxed toon (every track but Toon-Up) with the
owner's VP pouch partly spent, 30-137 laff, and 1-4 cogs of level 6-12 at
random health. Street battles, so nothing walks in -- the case where exact
search can reach the end.

`agree` searches each position twice at the same depth -- once exactly, once
with the options given -- and reports how often the move matches and how far
the value moves. An exact speedup must score 100% and 0.0.
`fight` plays whole battles, searching every round, with and without the memo
kept between rounds (`--persist`), and reports the time per decision.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def position(seed: int, cogs: int):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed * 101 + cogs)
    toon = vp_mod.maxed_toon(rng, tracks=[t for t in Track if t is not Track.TOON_UP],
                             laff=137)
    vp_mod.owner_vp_pouch(toon)
    for key in list(toon.gag_counts):
        if rng.random() < 0.4:
            toon.gag_counts[key] = rng.randint(0, toon.gag_counts[key])
    toon.gag_counts = {k: v for k, v in toon.gag_counts.items() if v > 0}
    toon.laff = rng.randint(30, 137)
    maker = env_mod.BattleEnv(rng=random.Random(seed))
    board = [maker._sellbot_cog(rng, rng.randint(6, 12)) for _ in range(cogs)]
    for cog in board:
        cog.hp = max(1, int(cog.hp * rng.uniform(0.3, 1.0)))
    return BattleState(toons=[toon], cogs=board, kind="street")


def search(state, depth, budget, **opts):
    from solver.search import expectimax, objective

    expectimax.BEAM = opts.pop("beam", None) or None
    expectimax.ORDER = bool(opts.pop("order", True))
    prune = opts.pop("prune", True)
    if not prune:
        opts["prune"] = False
    try:
        return expectimax.best_action_iterative(
            state, depth=depth, objective=objective.BALANCED, time_budget=budget,
            epsilon=opts.pop("epsilon", 0.0), **opts)
    finally:
        expectimax.BEAM = None
        expectimax.ORDER = True


def _shortcuts(args) -> dict:
    """The approximations named on the command line, as search options."""
    opts = {}
    if getattr(args, "beam", 0):
        opts["beam"] = args.beam
    if getattr(args, "exact_plies", None) is not None:
        opts["exact_plies"] = args.exact_plies
    if getattr(args, "no_order", False):
        opts["order"] = False
    if getattr(args, "no_prune", False):
        opts["prune"] = False
    return opts


def cmd_depth(args):
    for cogs in (1, 2, 3, 4):
        row = []
        for depth in range(1, args.max_depth + 1):
            times = []
            for seed in range(args.n):
                t0 = time.perf_counter()
                search(position(seed, cogs), depth, args.limit, **_shortcuts(args))
                times.append(time.perf_counter() - t0)
            mean = statistics.mean(times)
            capped = max(times) >= args.limit * 0.98
            row.append(f"d{depth} {mean:7.2f}s" + ("*" if capped else " "))
            if capped:
                break
        print(f"  {cogs} cogs: " + "  ".join(row), flush=True)
    print("  (* = hit the time limit; mean over", args.n, "positions)")


def cmd_agree(args):
    opts = _shortcuts(args)
    same = n = 0
    drift = []
    fast = slow = 0.0
    for cogs in args.cogs:
        for seed in range(args.n):
            st = position(seed, cogs)
            t0 = time.perf_counter()
            base = {}
            if args.base_exact_plies is not None:
                base["exact_plies"] = args.base_exact_plies
            if args.base_beam:
                base["beam"] = args.base_beam
            v0, a0 = search(st.clone(), args.depth, 1e9, **base)
            t1 = time.perf_counter()
            v1, a1 = search(st.clone(), args.depth, 1e9, **dict(opts))
            t2 = time.perf_counter()
            slow += t1 - t0
            fast += t2 - t1
            same += a0 == a1
            drift.append(abs(v0 - v1))
            n += 1
    print(f"  depth {args.depth}, {n} positions: same move {100 * same / n:.1f}%, "
          f"mean |value change| {statistics.mean(drift):.3f}, "
          f"max {max(drift):.3f}, time {slow:.1f}s -> {fast:.1f}s")


def cmd_fight(args):
    from solver.rl import env as env_mod
    from solver.search import playout

    for persist in (False, True):
        times, decisions = [], 0
        for seed in range(args.n):
            st = position(seed, args.cogs)
            env = env_mod.BattleEnv(rng=random.Random(seed), sampler=lambda _r, s=st: s.clone(),
                                    coordinated=True, max_rounds=40)
            env.reset()
            memo = {} if persist else None
            done = False
            while not done and decisions < 10_000:
                t0 = time.perf_counter()
                _v, action = search(env.state.clone(), args.depth, args.limit,
                                    **({"memo": memo} if persist else {}))
                times.append(time.perf_counter() - t0)
                decisions += 1
                done, _info = playout.step_round(env, [action])
        print(f"  {'kept memo' if persist else 'fresh memo'}: {len(times)} decisions, "
              f"mean {statistics.mean(times):.2f}s, median {statistics.median(times):.2f}s")


def cmd_stable(args):
    """How often the chosen move changes from one depth to the next."""
    opts = _shortcuts(args)
    changes = {d: 0 for d in range(2, args.max_depth + 1)}
    final = {d: 0 for d in range(1, args.max_depth + 1)}
    n = 0
    for cogs in args.cogs:
        for seed in range(args.n):
            st, memo, moves = position(seed, cogs), {}, []
            for depth in range(1, args.max_depth + 1):
                _v, a = search(st.clone(), depth, 1e9, memo=memo, **dict(opts))
                moves.append(repr(a))
            for d in range(2, args.max_depth + 1):
                changes[d] += moves[d - 1] != moves[d - 2]
            for d in range(1, args.max_depth + 1):
                final[d] += moves[d - 1] == moves[-1]
            n += 1
            print(f"    {cogs} cogs seed {seed}: " + " ".join(
                str(1 + sorted(set(moves), key=moves.index).index(m)) for m in moves),
                flush=True)
    print(f"  {n} positions; move changed going to depth d:")
    print("    " + "  ".join(f"d{d}: {100 * changes[d] / n:4.0f}%" for d in changes))
    print(f"  same move as depth {args.max_depth}:")
    print("    " + "  ".join(f"d{d}: {100 * final[d] / n:4.0f}%" for d in final))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("depth")
    d.add_argument("--n", type=int, default=3)
    d.add_argument("--limit", type=float, default=60.0)
    d.add_argument("--max-depth", type=int, default=4)
    d.add_argument("--beam", type=int, default=0)
    d.add_argument("--exact-plies", type=int, default=None,
                   help="collapse cog damage below this many plies (the panel uses 0)")
    a = sub.add_parser("agree")
    a.add_argument("--n", type=int, default=25)
    a.add_argument("--depth", type=int, default=2)
    a.add_argument("--beam", type=int, default=0)
    a.add_argument("--cogs", type=int, nargs="+", default=[1, 2, 3, 4])
    a.add_argument("--exact-plies", type=int, default=None)
    a.add_argument("--no-order", action="store_true", help="generation-order moves (ORDER off)")
    a.add_argument("--no-prune", action="store_true", help="turn *-minimax off")
    a.add_argument("--base-beam", type=int, default=0)
    a.add_argument("--base-exact-plies", type=int, default=None,
                   help="the reference search's collapse setting (default fully exact)")
    f = sub.add_parser("fight")
    f.add_argument("--n", type=int, default=5)
    f.add_argument("--cogs", type=int, default=2)
    f.add_argument("--depth", type=int, default=3)
    f.add_argument("--limit", type=float, default=120.0)
    st = sub.add_parser("stable")
    st.add_argument("--n", type=int, default=20)
    st.add_argument("--cogs", type=int, nargs="+", default=[1, 2])
    st.add_argument("--max-depth", type=int, default=6)
    st.add_argument("--beam", type=int, default=6)
    st.add_argument("--exact-plies", type=int, default=0)
    args = ap.parse_args()
    {"depth": cmd_depth, "agree": cmd_agree, "fight": cmd_fight,
     "stable": cmd_stable}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
