"""Play one building with each agent and print what they did, round by round.

    python tools/trace_building.py --seed 36005
    python tools/trace_building.py --scan 40      # find divergent buildings

Both agents get the SAME building and the same dice, but each plays its
own trajectory -- this is not the CRN fork in `tools/disagree.py`, which
asks what one substituted action is worth. Here the question is what a
whole approach looks like.

READING THE ACTION COLUMN
-------------------------
`toon_up/5 -> t1` heals TOON 1. `throw/6 -> c3` hits COG 3. The arrow's
target means different things for different tracks -- `Action.describe`
prints the bare index, and reading a Toon-Up target as a cog once cost
this project an afternoon chasing a bug that did not exist. So the letter
is always printed here.

`-> all` is a group gag: Sound always, and the group Lures and Drops.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid                              # noqa: E402
from solver.search import party_search as ps                  # noqa: E402
from solver.state import Track                                # noqa: E402

HEALS = {Track.TOON_UP}


def show(action) -> str:
    if action is None or action.is_pass:
        return "hold"
    if action.target_index is None:
        target = "all"
    elif action.track in HEALS:
        target = f"t{action.target_index}"
    else:
        target = f"c{action.target_index}"
    return f"{action.track.value}/{action.level}->{target}"


def board(state) -> str:
    cogs = []
    for i, c in enumerate(state.cogs):
        if c.status.is_dead:
            continue
        marks = ""
        if c.status.lured:
            marks += "L"
        if c.status.trapped:
            marks += "T"
        cogs.append(f"c{i}:lv{c.level}={c.hp}{marks}")
    toons = " ".join(f"t{i}:{max(0, t.laff)}" for i, t in enumerate(state.toons))
    return f"[{' '.join(cogs) or 'none'}]  {toons}"


def pouch(state) -> int:
    return sum(n for t in state.toons if t.laff > 0
               for n in t.gag_counts.values() if n > 0)


def play(seed, agent, budget, verbose=True, label="", sampler=None):
    e = env_mod.BattleEnv(rng=random.Random(seed),
                          sampler=sampler or env_mod.facility_position,
                          coordinated=True)
    obs, mask = e.reset()
    rng = random.Random(seed)
    plan, done, guard, info = None, False, 0, {}
    rounds, floor_seen, lines = 0, -1, []
    seen_round = -1
    while not done and guard < 250:
        guard += 1
        # `e.rounds`, NOT `all(a is None for a in e.pending)`. A seat that
        # holds stores None in `pending`, so the pending list cannot tell
        # "everyone has yet to choose" from "everyone so far has held" --
        # and the first version of this printed the same round twice
        # whenever seat 0 held, which read exactly like the agent
        # stalling. It was not.
        if e.rounds != seen_round:
            seen_round = e.rounds
            state = e.state
            if e.floor != floor_seen:
                floor_seen = e.floor
                name = (("cog round", "skelecog round")[min(e.floor - 1, 1)]
                        if state.kind == "vp" else f"floor {e.floor + 1}")
                lines.append(f"    --- {name} "
                             f"({state.cogs_remaining} cogs still to come) ---")
            if agent == "search":
                plan = ps.best_plan(state, mode=ps.Mode.COORDINATED, rng=rng)
            else:
                plan = hybrid.climb(state, rng, budget=budget)
            rounds += 1
            lines.append(f"    r{rounds:<3d} {board(state)}  pouch={pouch(state)}")
            lines.append(f"         {'  '.join(show(a) for a in plan)}")
        action = plan[e.actor] if plan and e.actor < len(plan) else None
        index = env_mod.PASS_INDEX
        if action is not None and not action.is_pass:
            for i, cand in enumerate(env_mod.ACTIONS):
                if (cand is not None and cand.track == action.track
                        and cand.level == action.level
                        and cand.target_index == action.target_index):
                    index = i
                    break
        if not mask[index]:
            index = env_mod.PASS_INDEX
        obs, mask, _r, done, info = e.step(index)
    won = bool(info.get("win"))
    lost_toons = sum(1 for t in e.state.toons if t.laff <= 0)
    heals = sum(1 for line in lines if "toon_up" in line)
    play.last = {"won": won, "rounds": rounds, "lost_toons": lost_toons,
                 "heals": heals, "floor": info.get("floor", 0)}
    if verbose:
        print(f"\n  {label}")
        for line in lines:
            print(line)
        print(f"    => {'CLEARED' if won else 'lost'} after {rounds} rounds, "
              f"reached floor {info.get('floor', 0) + 1}, "
              f"pouch left {pouch(e.state)}")
    return won, rounds, info.get("floor", 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=36005)
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--stats", type=int, default=0,
                    help="play N buildings with each agent and report toon "
                         "losses against clear rate")
    ap.add_argument("--scan", type=int, default=0,
                    help="instead of tracing, report seeds where the two "
                         "agents disagree about the OUTCOME")
    ap.add_argument("--start", type=int, default=36000)
    ap.add_argument("--vp", action="store_true",
                    help="trace one side of the Sellbot VP instead of a "
                         "cog building: two maxed toons, the cog round then "
                         "the skelecog round")
    args = ap.parse_args()

    if not hybrid.available():
        print("  numpy or the policy is missing")
        return 1

    if args.stats:
        # Does losing a toon explain losing the building? A sad toon takes
        # their whole pouch out of the party -- `can_still_damage` pools
        # over the standing toons only -- so one loss is not one quarter
        # of the team, it is a step change in what the party can still do.
        print(f"  {args.stats} buildings from {args.start}\n")
        rows = {"climb": [], "search": []}
        for offset in range(args.stats):
            seed = args.start + offset
            for agent in ("climb", "search"):
                play(seed, agent, args.budget, verbose=False)
                rows[agent].append(dict(play.last))
        print(f"    {'agent':>8}  {'cleared':>8}  {'toons lost':>11}"
              f"  {'heal rounds':>12}  {'rounds':>7}")
        for agent, data in rows.items():
            n = len(data)
            print(f"    {agent:>8}  {sum(r['won'] for r in data) / n * 100:7.1f}%"
                  f"  {sum(r['lost_toons'] for r in data) / n:11.2f}"
                  f"  {sum(r['heals'] for r in data) / n:12.1f}"
                  f"  {sum(r['rounds'] for r in data) / n:7.1f}")
        print()
        for agent, data in rows.items():
            intact = [r for r in data if r["lost_toons"] == 0]
            bereaved = [r for r in data if r["lost_toons"] > 0]
            for label, sel in (("no toon lost", intact), ("lost >=1", bereaved)):
                if sel:
                    print(f"    {agent:>8}  {label:14s} n={len(sel):3d}  "
                          f"cleared {sum(r['won'] for r in sel) / len(sel) * 100:5.1f}%")
        return 0

    if args.scan:
        print(f"  scanning {args.scan} buildings from {args.start}\n")
        print(f"    {'seed':>6}  {'climb':>7}  {'search':>7}")
        splits = []
        for offset in range(args.scan):
            seed = args.start + offset
            a, _ra, _fa = play(seed, "climb", args.budget, verbose=False)
            b, _rb, _fb = play(seed, "search", args.budget, verbose=False)
            if a != b:
                splits.append((seed, a, b))
                print(f"    {seed:>6}  {'clear' if a else 'lost':>7}  "
                      f"{'clear' if b else 'lost':>7}   <- split")
        print(f"\n  {len(splits)} of {args.scan} buildings split the agents")
        return 0

    sampler = None
    if args.vp:
        from solver import vp as vp_mod
        sampler = vp_mod.vp_position
        print(f"\n  VP side {args.seed}   {vp_mod.COG_ROUND} cogs "
              f"then {vp_mod.SKELECOG_ROUND} skelecogs")
    else:
        print(f"\n  building {args.seed}")
    play(args.seed, "climb", args.budget, label="PPO + climb",
         sampler=sampler)
    if not args.vp:
        play(args.seed, "search", args.budget, label="classical search",
             sampler=sampler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
