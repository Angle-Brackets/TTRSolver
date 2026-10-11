"""Label climb's decisions, for training the fast rollout player.

    python tools/gen_fast_player_data.py --episodes 6000 --out climb.pkl
    python tools/gen_fast_player_data.py --episodes 4000 --out dagger1.pkl \\
        --player solver/rl/fast_player.json          # a DAgger round
    python tools/train_fast_player.py --data climb.pkl dagger1.pkl

climb (or, with `--teacher playout`, the Playout engine) plays solo fights
-- VP (60%), buildings (20%), the env's default street mix cut to one toon
(20%) -- seen as a rollout sees them (no holdout). Each decision is
recorded as `fastplayer.features` with the teacher's move as the label.

`--player` is DAgger: the given network plays and climb only LABELS, so
the data covers the states the network itself reaches, where its own
mistakes take it. Two rounds took the shipped network from 68% to 79%
agreement with climb and from 7/300 to 16/300 solo VP wins on its own.

UNITES. Toons carry 0-5 unites (`--unites`). Where one is usable, the
teacher's unite (or none) is recorded on the board BEFORE it -- a
("unite", features, mask, slot) row -- and its gag on the board AFTER
it, as the game orders them. Gag rows are ("act", features, mask, label);
older pickles hold bare (features, mask, label) gag rows from before the
unite inputs, which `train_fast_player.py` pads.
"""
from __future__ import annotations

import argparse
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _sampler(kind, unites=5):
    from solver import sos as sos_mod
    from solver.rl import env as env_mod

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sweep import DECK, _sampler as regime

    base = _base_sampler(kind, sos_mod, env_mod, DECK, regime)

    def sample(rng):
        st = base(rng)
        if unites and rng.random() < 0.7:
            st.toons[0].unites_held = rng.randint(1, unites)
        return st
    return sample


def _base_sampler(kind, sos_mod, env_mod, DECK, regime):
    if kind == "vp":
        return regime("solo-vp")[0]
    if kind == "ceo":
        return regime("solo-ceo")[0]

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


def _teach(env, view, seed, rounds, teacher, rng):
    """The teacher's move for this board, its unite carried on the plan.
    `view` is not changed."""
    from solver.search import playout

    if teacher == "playout":
        from sweep import _horizon

        res = playout.pick_wide(view, _horizon(env, env.state),
                                seed=seed * 1000 + rounds)
        if res is not None:
            return res.plan
    return playout.climb_with_unite(view.clone(), rng, budget=24)


def episode(job):
    seed, kind, player, teacher, unites = job[:5]
    with_horizon = bool(job[5]) if len(job) > 5 else False
    from solver import unites as unites_mod
    from solver.rl import env as env_mod
    from solver.search import fastplayer, playout

    if player:
        fastplayer.use(player)
    if kind == "ceo":
        from solver import ceo as ceo_mod
        ceo_mod.enable_big_cheese()
    env = env_mod.BattleEnv(rng=random.Random(seed),
                            sampler=_sampler(kind, unites), coordinated=True,
                            max_rounds=400 if kind in ("vp", "ceo") else 20)
    try:
        env.reset()
    except Exception:                    # noqa: BLE001 -- an unbuildable draw
        return []
    rng = random.Random(seed)
    rows, done, rounds = [], False, 0
    while not done and rounds < 400:
        view = playout._view(env.state)
        waiting = len(env.state.holdout)       # the view strips it
        try:
            plan = _teach(env, view, seed, rounds, teacher, rng)
        except Exception:                # noqa: BLE001
            break
        unite = playout.unite_of(plan)
        umask = fastplayer.unite_mask(view)
        if any(umask[1:]):
            slot = fastplayer._slot_of(view.toons[0], unite)
            if slot >= 0 and umask[slot]:
                rows.append(("unite", fastplayer.features(
                    view, waiting, with_horizon)[0], umask, slot))
        after = view
        if unite is not None:
            after = view.clone()
            unites_mod.apply(after.toons[0], unite)
        features, mask = fastplayer.features(after, waiting, with_horizon)
        label = fastplayer.index_of(plan[0] if plan else None)
        if label >= 0 and mask[label]:
            rows.append(("act", features, mask, label))
        move = fastplayer.act(view, holdout=waiting) if player else plan
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
    ap.add_argument("--teacher", choices=("climb", "playout"), default="climb",
                    help="who labels each decision. 'playout' is expert "
                         "iteration: the network learns the playouts' moves "
                         "(in a VP, with the boss tracker's horizon), which "
                         "then play on with it")
    ap.add_argument("--unites", type=int, default=5,
                    help="most unites a toon carries (0 for none)")
    ap.add_argument("--kinds", default="vp:6,building:2,street:2",
                    help="the fight mix, kind:weight -- vp, building, street, ceo")
    ap.add_argument("--horizon", action="store_true",
                    help="record `fastplayer.horizon` too: cogs waiting, later "
                         "waves and SOS calls left -- what a policy playing "
                         "like the playouts needs to see")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    kinds = []
    for part in args.kinds.split(","):
        kind, _, weight = part.partition(":")
        kinds += [kind.strip()] * max(1, int(weight or 1))
    jobs = [(args.base + i, kinds[i % len(kinds)], args.player, args.teacher,
             args.unites, args.horizon) for i in range(args.episodes)]
    rows = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(episode, jobs, chunksize=4):
            rows.extend(got)
            done += 1
            if done % 100 == 0:
                # Checkpoints, so a long run that dies still leaves data.
                pickle.dump(rows, open(args.out, "wb"))
                print(f"  {done}/{len(jobs)} fights, {len(rows)} rows", flush=True)
    pickle.dump(rows, open(args.out, "wb"))
    print(f"{len(rows)} labelled decisions written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
