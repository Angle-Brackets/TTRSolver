"""Generate training data for the policy and value heads (P0 / P1).

    python tools/gen_party_data.py --positions 400

For each sampled party position this runs a **deliberately wide** search
and records what it thought of every plan on its shortlist. One position
therefore yields a VALUE label (the position's searched value, for P1)
and a full RANKING over ~100 plans, for P0 -- not an argmax, since the
search already computes a value for every shortlisted plan, so the
ranking is free once it has run and is far more signal per unit of
compute than a single best-move label.

THE TEACHER IS WIDER THAN THE STUDENT, DELIBERATELY: `docs/ml-design.md`
§2b notes labels come from search, and search only ranks what its
shortlist admitted. Training on the shipped shortlist would teach the
policy today's blind spots -- including the `QUICK_SCORED_PER_TRACK`
prefix bug that hid 2 Foghorn + 2 Aoogah for four commits. So generation
runs at `--teacher-plans` / `--teacher-per-track` well above the shipped
defaults and pays for it in wall clock. The student may be narrow; the
teacher may not.

Output is a JSON file of {state, plans, values}. States round-trip
through `visualizer.bridge`, the same as `fit_heuristic`'s cache, so
features can be recomputed when the feature set changes without
re-running any searches.
"""
import argparse
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import data                                        # noqa: E402
from solver.party import Mode                                  # noqa: E402
from solver.search import party_search as ps                   # noqa: E402
from solver.search import objective as objective_mod           # noqa: E402
from solver.state import (                                     # noqa: E402
    Action, BattleState, CogState, ToonState, Track,
)
from visualizer import bridge                                  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".party_labels.json"

TRACKS = [Track.THROW, Track.SQUIRT, Track.SOUND, Track.LURE,
          Track.TRAP, Track.DROP, Track.TOON_UP]

# Cogs whose tables are complete at every level we sample. A [TODO] cell
# raises mid-search, which would bias the dataset toward whichever cogs
# happen to be fully transcribed -- better to pick from a known-good set
# than to discover the gaps by exception.
SAFE_COGS = [("bean_counter", "cashbot", 4, 8),
             ("number_cruncher", "cashbot", 5, 9),
             ("loan_shark", "cashbot", 7, 11),
             ("double_talker", "lawbot", 3, 7),
             ("ambulance_chaser", "lawbot", 4, 8),
             ("backstabber", "lawbot", 5, 9),
             ("spin_doctor", "lawbot", 6, 10),
             ("legal_eagle", "lawbot", 7, 11),
             ("head_hunter", "bossbot", 6, 10),
             ("two_face", "sellbot", 6, 10),
             ("the_mingler", "sellbot", 7, 11)]


def _usable(track, level):
    """Is this gag fully transcribed?

    A [TODO] cell raises when the search touches it, which kills a whole
    worker mid-run -- `Heal for Lipstick (toon_up 3)` was the first to
    do it. Checking up front keeps the dataset to gags the simulator can
    actually resolve, rather than discovering the gaps by exception and
    biasing the sample toward whichever ones happen to be complete.
    """
    try:
        gag = data.gag(track, level)
        if track == Track.TOON_UP:
            gag.heal_at(1.0, False)
        elif track != Track.LURE:
            gag.damage_at(1.0, False)
        gag.prop_accuracy(organic=False)
        return True
    except (NotImplementedError, ValueError, KeyError):
        return False


_USABLE = {(t, l) for t in TRACKS for l in range(1, 8) if _usable(t, l)}


def random_toon(rng):
    """A plausible pouch: 3-5 tracks, weighted to the top, sometimes
    organic, sometimes part-trained."""
    tracks = rng.sample(TRACKS, rng.randint(3, 5))
    counts, exp = {}, {}
    for track in tracks:
        trained = rng.randint(4, 7)
        exp[track] = trained
        top = min(7, trained)
        for level in range(max(1, top - 3), top + 1):
            if (track, level) in _USABLE and rng.random() < 0.8:
                cap = data.gag(track, level).max_carry or 1
                counts[(track, level)] = rng.randint(1, min(cap, 4))
    if not counts:
        counts = {(Track.THROW, 4): 2}
        exp = {Track.THROW: 5}
    max_laff = rng.choice([50, 65, 80, 95, 110, 125, 137])
    laff = max(1, int(max_laff * rng.uniform(0.15, 1.0)))
    organic = frozenset([rng.choice(tracks)]) if rng.random() < 0.4 else frozenset()
    return ToonState(laff, max_laff, exp, counts, organic)


def random_state(rng):
    cogs = []
    for _ in range(rng.randint(2, 4)):
        key, dept, lo, hi = rng.choice(SAFE_COGS)
        level = rng.randint(lo, hi)
        full = data.cog_max_hp(level)
        cogs.append(CogState(key, dept, level,
                             rng.randint(max(1, full // 5), full), full))
    toons = [random_toon(rng) for _ in range(rng.randint(2, 4))]
    return BattleState(toons=toons, cogs=cogs)


def encode_plan(plan):
    """A plan as JSON: one entry per toon, null for hold."""
    return [None if a is None
            else [a.track.name, a.level, a.target_index] for a in plan]


def label_one(args):
    """Search one position wide and record every plan's value."""
    seed, plans_cap, per_track, samples, depth = args
    rng = random.Random(seed)
    state = random_state(rng)
    if state.is_terminal():
        return None

    objective = objective_mod.BALANCED
    shortlist = ps.plans(state, Mode.COORDINATED, per_track, plans_cap)
    if len(shortlist) < 2:
        return None

    scored = []
    for plan in shortlist:
        waste = ps.waste_penalty(objective, state, plan)
        returns = []
        for _ in range(samples):
            nxt, _h, _d = ps.party_mod.step(
                state, plan[0], mode=Mode.COORDINATED,
                joint=list(plan), rng=rng)
            lost = sum(max(0, b.laff - a.laff)
                       for b, a in zip(state.toons, nxt.toons))
            sad = sum(1 for b, a in zip(state.toons, nxt.toons)
                      if b.laff > 0 and a.laff <= 0)
            reward = ps.round_reward(
                objective, lost, ps._spent(state, nxt), nxt.is_win(),
                nxt.is_terminal() and not nxt.is_win(), toons_lost=sad)
            future = 0.0
            if depth > 1 and not nxt.is_terminal():
                future, _p = ps.evaluate(
                    nxt, depth - 1, Mode.COORDINATED, None, objective,
                    max(4, samples // 4), per_track, max(8, plans_cap // 8),
                    "rollout", rng)
            elif not nxt.is_terminal():
                future = ps.rollout_value(nxt, objective, rng)
            returns.append(reward + future)
        scored.append((sum(returns) / len(returns) - waste, plan))

    scored.sort(key=lambda row: -row[0])
    return {"state": bridge.state_to_dict(state),
            "plans": [encode_plan(p) for _v, p in scored],
            "values": [round(v, 3) for v, _p in scored]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--positions", type=int, default=400)
    ap.add_argument("--teacher-plans", type=int, default=120,
                    help="wider than the shipped MAX_PLANS, on purpose")
    ap.add_argument("--teacher-per-track", type=int, default=5,
                    help="wider than the shipped CANDIDATES_PER_TRACK, on purpose")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    jobs = [(args.seed * 1_000_003 + i, args.teacher_plans,
             args.teacher_per_track, args.samples, args.depth)
            for i in range(args.positions)]

    started = time.time()
    rows, skipped = [], 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, row in enumerate(pool.map(label_one, jobs, chunksize=1), 1):
            if row is None:
                skipped += 1
            else:
                rows.append(row)
            if i % 25 == 0:
                rate = i / (time.time() - started)
                print(f"  {i}/{len(jobs)}  {rate:.1f}/s  "
                      f"eta {(len(jobs) - i) / max(rate, 1e-9):.0f}s",
                      flush=True)

    payload = {"positions": rows,
               "teacher": {"plans": args.teacher_plans,
                           "per_track": args.teacher_per_track,
                           "samples": args.samples, "depth": args.depth}}
    Path(args.out).write_text(json.dumps(payload), encoding="utf-8")
    total_plans = sum(len(r["plans"]) for r in rows)
    print(f"\n  {len(rows)} positions, {skipped} skipped, "
          f"{total_plans} ranked plans in {time.time() - started:.0f}s")
    print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
