"""Label boards with how the WHOLE fight actually goes from them, for `valuenet`.

    python tools/gen_value_outcomes.py --episodes 3000 --out value_out.pkl

`gen_value_data.py` labels a board with what a depth-limited search says it
is worth -- and that search sees only the cogs on the field, so its labels
carry its blind spot: on duo VP sides the Search row won 6/60 where the
Playout row won 33/60, and a network trained on those labels inherited it.
This labels a board with the reward actually collected from it to the END
of the fight -- every later wave included -- under the fast network's play,
averaged over `--rollouts` independent continuations. The units are the
search's own (`Objective.step_reward`: laff lost, gag prices, the turn cost,
+/-100 at the end), so the result drops straight in as a leaf.

Laff lost is measured as the drop in laff over a round, so a heal in the
same round is netted against damage -- slightly optimistic where heals are
used, which the search's own reward is not.

Rows match `gen_value_data.py` (minus "fitted"): {"x", "y", "cogs",
"regime", "state"}.
"""
from __future__ import annotations

import argparse
import copy
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REGIMES = ("duo-vp", "solo-vp", "my-building", "solo-building", "street")
TAKE = 0.3          # chance each round's board is labelled
MAX_BOARDS = 8      # per episode


def _env(regime, rng):
    from solver import vp as vp_mod
    from solver.rl import env as env_mod

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sweep import PLAYERS, _sampler

    if regime == "street":
        def sample(r):
            st = env_mod.BattleEnv(rng=r).sampler(r)
            st.toons = st.toons[:1]
            return st
        cap = 20
    else:
        sample, _coord, cap = _sampler(regime)
    env = env_mod.BattleEnv(rng=rng, sampler=sample, coordinated=True, max_rounds=cap)
    env.boss_players = PLAYERS.get(regime)
    env.reset()
    if regime in ("duo-vp", "solo-vp"):
        for toon in env.state.toons:
            vp_mod.owner_vp_pouch(toon)
    return env


def _play_out(env, objective, rng_seed) -> float:
    """Reward from the board in `env` to the end, the fast network playing."""
    from solver.search import fastplayer, playout

    env.rng = random.Random(rng_seed)
    total, guard, done = 0.0, 0, False
    while not done and guard < 400:
        guard += 1
        view = playout._view(env.state)
        # The view has its holdout stripped, so the count is handed over,
        # as the playouts do: without it the network plays every label
        # fight believing no more cogs are coming.
        plan = fastplayer.act(view, holdout=len(env.state.holdout))
        action = plan[0] if plan else None
        before = env.state.toons[0].laff
        remaining = env.state.cogs_remaining
        done, info = playout.step_round(env, plan)
        lost_laff = max(0, before - env.state.toons[0].laff)
        track = getattr(action, "track", None)
        price = (objective.gag_price(track, action.level, remaining)
                 if track is not None and not getattr(action, "sos", None) else 0.0)
        total += -objective.laff_weight * lost_laff - price - objective.turn_cost
        if done:
            total += objective.win_bonus if info.get("win") else -objective.loss_penalty
    return total


def _play_out_playout_units(env, rng_seed) -> float:
    """Cogs defeated from the board in `env` to the end, plus LAFF_WEIGHT x
    the laff fraction left -- the playouts' own score, from here."""
    from solver.search import fastplayer, playout

    env.rng = random.Random(rng_seed)
    left0 = playout._left(env.state)
    guard, done = 0, False
    while not done and guard < 400:
        guard += 1
        done, _info = playout.step_round(env, fastplayer.act(
            playout._view(env.state), holdout=len(env.state.holdout)))
    toon = env.state.toons[0]
    laff = max(0, toon.laff) / float(toon.max_laff or 1)
    return (left0 - playout._left(env.state)) + playout.LAFF_WEIGHT * laff


def episode(job):
    seed, rollouts, loss_penalty, units, extras = job
    import dataclasses
    from solver.search import fastplayer, objective, playout

    obj = objective.BALANCED
    if loss_penalty is not None:
        obj = dataclasses.replace(obj, loss_penalty=loss_penalty)
    rng = random.Random(seed)
    regime = REGIMES[seed % len(REGIMES)]
    try:
        env = _env(regime, rng)
    except Exception:                       # noqa: BLE001 -- an unbuildable draw
        return []
    rows, done, guard = [], False, 0
    while not done and guard < 400 and len(rows) < MAX_BOARDS:
        guard += 1
        view = playout._view(env.state)
        cogs = sum(1 for c in view.cogs if not c.status.is_dead)
        if cogs and not env.state.is_terminal() and rng.random() < TAKE:
            try:
                ys = [(_play_out_playout_units(copy.deepcopy(env), seed * 7919 + k)
                       if units == "playout" else
                       _play_out(copy.deepcopy(env), obj, seed * 7919 + k))
                      for k in range(rollouts)]
            except Exception:               # noqa: BLE001
                ys = []
            if ys:
                x = fastplayer.features(view)[0]
                if extras:
                    from solver.search import valuenet
                    x = x + valuenet.extras(len(env.state.holdout), env.state.cogs_remaining)
                rows.append({"x": x, "y": sum(ys) / len(ys),
                             "cogs": cogs, "regime": regime, "state": pickle.dumps(view)})
        try:
            done, _ = playout.step_round(env, fastplayer.act(
                view, holdout=len(env.state.holdout)))
        except Exception:                   # noqa: BLE001
            break
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes", type=int, default=3000)
    ap.add_argument("--base", type=int, default=800000)
    ap.add_argument("--rollouts", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--loss-penalty", type=float, default=None,
                    help="score a lost fight at -this (Balanced: 100)")
    ap.add_argument("--units", choices=("search", "playout"), default="search",
                    help="search: Objective rewards; playout: cogs defeated + laff")
    ap.add_argument("--extras", action="store_true",
                    help="add the holdout and later-wave counts to the inputs")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    jobs = [(args.base + i, args.rollouts, args.loss_penalty, args.units, args.extras)
            for i in range(args.episodes)]
    rows, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, got in enumerate(pool.map(episode, jobs, chunksize=2)):
            rows.extend(got)
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(jobs)} episodes, {len(rows)} boards, "
                      f"{time.time() - t0:.0f}s", flush=True)
                pickle.dump(rows, open(args.out, "wb"))
    pickle.dump(rows, open(args.out, "wb"))
    print(f"{len(rows)} labelled boards written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
