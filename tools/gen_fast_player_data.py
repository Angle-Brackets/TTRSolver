"""Label climb's decisions, for training the fast rollout player.

    python tools/gen_fast_player_data.py --episodes 6000 --out climb.pkl
    python tools/gen_fast_player_data.py --episodes 4000 --out dagger1.pkl \\
        --player solver/rl/fast_player.json          # a DAgger round
    python tools/train_fast_player.py --data climb.pkl dagger1.pkl

climb plays solo fights -- VP (60%), buildings (20%), the env's default
street mix cut to one toon (20%) -- seen as a rollout sees them (no
holdout). Each decision is recorded as `fastplayer.features` with climb's
move as the label.

`--player` is DAgger: the given network plays and climb only LABELS, so
the data covers the states the network itself reaches, where its own
mistakes take it. Two rounds took the shipped network from 68% to 79%
agreement with climb and from 7/300 to 16/300 solo VP wins on its own.
"""
from __future__ import annotations

import argparse
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _sampler(kind):
    from solver import sos as sos_mod
    from solver.rl import env as env_mod

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sweep import DECK, _sampler as regime

    if kind == "vp":
        return regime("solo-vp")[0]

    def sample(rng):
        st = (env_mod.facility_position(rng) if kind == "building"
              else env_mod.BattleEnv(rng=rng).sampler(rng))
        st.toons = st.toons[:1]
        if rng.random() < 0.5:
            names = [n for n in DECK if n in sos_mod.BY_NAME]
            st.toons[0].sos_cards = {n: rng.randint(1, 2) for n in
                                     rng.sample(names, rng.randint(1, len(names)))}
        if rng.random() < 0.5:
            st.toons[0].fires = rng.randint(0, 3)
        return st
    return sample


def episode(job):
    seed, kind, player = job
    from solver.rl import env as env_mod
    from solver.search import fastplayer, hybrid, playout

    if player:
        fastplayer.use(player)
    env = env_mod.BattleEnv(rng=random.Random(seed), sampler=_sampler(kind),
                            coordinated=True,
                            max_rounds=400 if kind == "vp" else 20)
    try:
        env.reset()
    except Exception:                    # noqa: BLE001 -- an unbuildable draw
        return []
    rng = random.Random(seed)
    rows, done, rounds = [], False, 0
    while not done and rounds < 400:
        view = playout._view(env.state)
        try:
            plan = hybrid.climb(view.clone(), rng, budget=24)
        except Exception:                # noqa: BLE001
            break
        features, mask = fastplayer.features(view)
        label = fastplayer.index_of(plan[0] if plan else None)
        if label >= 0 and mask[label]:
            rows.append((features, mask, label))
        move = fastplayer.act(view) if player else plan
        try:
            done, _ = playout.step_round(env, move)
        except Exception:                # noqa: BLE001
            break
        rounds += 1
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes", type=int, default=6000)
    ap.add_argument("--base", type=int, default=100000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--player", default="", help="network weights: DAgger mode")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    kinds = ["vp"] * 6 + ["building"] * 2 + ["street"] * 2
    jobs = [(args.base + i, kinds[i % 10], args.player)
            for i in range(args.episodes)]
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(episode, jobs, chunksize=4):
            rows.extend(got)
    pickle.dump(rows, open(args.out, "wb"))
    print(f"{len(rows)} labelled decisions written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
