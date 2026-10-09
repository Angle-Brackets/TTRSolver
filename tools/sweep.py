"""Paired sweeps: the same simulated fights, played by different engines.

    python tools/sweep.py --regime solo-vp --n 200 --arms climb playout
    python tools/sweep.py --regime my-building --arms playout playout:pouch=0
    python tools/sweep.py --regime solo-vp --arms playout:stages=16/32/64 playout

Every arm plays the SAME seeds, so the fights and dice match and only the
engine differs; results are compared on discordant seeds with a sign test.
This is the harness behind the figures in the playout, reader and pouch
commits -- see docs/experiment-log.md.

REGIMES
  solo-vp       a solo VP, 20 + 20 cogs, every track but Toon-Up, 140 laff,
                three slips and a ten-card SOS deck
  solo-building a solo toon in a building, drawn street-first
  my-building   the owner's toon (54 laff, 40-gag pouch, Toon-Up 5, Sound 6,
                Throw 5, Squirt 5, Drop 7 organic) in Daisy Gardens buildings
  party-building  a 2-4 toon building, you choosing, teammates modelled
  duo-vp        one side of a two-player VP: one toon, 10 + 10 cogs, two
                Restock All SOS and two Toon-Up SOS, no slips or Unites
  party-vp      one side of a four-player VP: two toons planned together,
                10 + 10 cogs
  ceo           the two-toon CEO side, 20 cogs then two leftovers

ARMS  (`name` or `name:key=value,key=value`)
  climb         the PPO row: `hybrid.climb`, budget 24
  playout       the Playout row: `playout.pick_wide` with shipped settings
  top3          `playout.pick` -- the scorer's top three, played out
  net           the fast network alone, one forward pass a decision (solo)
  search        the Search row: `expectimax.best_action_iterative`, collapse,
                epsilon 0.03 (keys budget=<s> depth=<max> beam=<k>
                leaf=<value-net weights> eps=<e> loss=<loss penalty>; solo)
  mcts          `mcts.pick` -- open-loop tree search over your decisions
                (keys iters=<n> c=<puct> k=<menu size>; solo, else playouts)
      keys: stages=8/16/32  pouch=<weight>  player=net|climb  rollouts=<n>
            net=<weights.json>  (the fast network's weights, default shipped)
            kit=owner  (restock every toon with `vp.OWNER_VP_POUCH` first)
            unites=<n>  (every toon holds n unites, of any kind)
            mates=off  (the ENGINE assumes teammates never use their unites;
                        in the fight itself they always do)
            mode=coordinated|pickup  (`playout.GROUP_MODE`)
            truth=prior|net   (how pickup teammates play in the fight)
            assume=prior|net  (what the engine's rollouts expect of them)
            style=<preset>  (the panel's preset, e.g. survive, "glass cannon")

Each board is shown to the engine as the live panel would see it: no
holdout, and in a boss fight the horizon the boss tracker would give.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DECK = {"Professor Pete": 2, "Flippy": 2, "Daffy Don": 2, "Moe Zart": 1,
        "Barnacle Bessie": 1, "Julius Wheezer": 1, "Sticky Lou": 1}
REGIMES = ("solo-vp", "solo-building", "my-building", "party-building",
           "duo-vp", "party-vp", "ceo")
# Toons in the whole boss fight where this side is not everyone.
PLAYERS = {"duo-vp": 2}


def _sampler(regime):
    from solver import ceo as ceo_mod, facility, sos as sos_mod, vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState, ToonState

    if regime == "solo-vp":
        def sample(rng):
            st = vp_mod.vp_position(rng)
            have = [t for t in Track if t is not Track.TOON_UP]
            toon = vp_mod.maxed_toon(rng, tracks=have, laff=140)
            toon.fires = 3
            toon.sos_cards = {k: v for k, v in DECK.items() if k in sos_mod.BY_NAME}
            st.toons = [toon]
            return st
        return sample, True, 400
    if regime == "solo-building":
        def sample(rng):
            st = env_mod.facility_position(rng)
            st.toons = st.toons[:1]
            return st
        return sample, True, 20
    if regime == "my-building":
        def sample(rng):
            street = rng.choice([s for s in facility.STREETS if s[1] == "Daisy Gardens"])
            exp = {Track.TOON_UP: 5, Track.SOUND: 6, Track.THROW: 5,
                   Track.SQUIRT: 5, Track.DROP: 7}
            toon = ToonState(54, 54, exp, {}, frozenset({Track.DROP}),
                             pouch_capacity=40)
            env_mod.restock(toon, rng)
            return BattleState(toons=[toon], cogs=[], kind="facility",
                               street=street[0])
        return sample, True, 20
    if regime == "party-building":
        return env_mod.facility_position, False, 20
    if regime == "duo-vp":
        # One side of a two-player VP: one toon, ten cogs a round, and the
        # owner's "a few SOS restocks and/or Toon-Up" -- no slips, no Unites.
        def sample(rng):
            st = vp_mod.vp_position(rng)
            st.toons = st.toons[:1]
            st.toons[0].fires = 0
            st.toons[0].sos_cards = {"Professor Pete": 2, "Flippy": 1, "Daffy Don": 1}
            return st
        return sample, True, 400
    if regime == "party-vp":
        return vp_mod.vp_position, True, 400
    if regime == "ceo":
        def sample(rng):
            ceo_mod.LEFTOVERS = 2
            return ceo_mod.ceo_position(rng)
        return sample, True, 400
    raise ValueError(regime)


def _parse_arm(spec):
    name, _, rest = spec.partition(":")
    opts = {}
    for item in filter(None, rest.split(",")):
        key, _, value = item.partition("=")
        opts[key] = value
    return name, opts


def _horizon(env, state):
    """What the boss tracker would say in a boss fight; None otherwise."""
    from solver.live.boss import BossTracker

    if state.kind not in ("vp", "ceo"):
        return None
    tracker = BossTracker(kind=state.kind,
                          party_size=getattr(env, "boss_players", None)
                          or len(state.toons))
    rounds = tracker.rounds()
    floor = getattr(env, "floor", 1)
    alive = sum(1 for c in state.cogs if c.hp > 0)
    defeated = sum(rounds[:floor - 1])
    if rounds[floor - 1] is not None:
        defeated += rounds[floor - 1] - alive - len(state.holdout)
    tracker.correct(defeated)
    return tracker.horizon(on_field=alive)


def play(job):
    regime, seed, spec = job
    from solver import ceo as ceo_mod
    from solver.rl import env as env_mod
    from solver.search import fastplayer, hybrid, playout

    if regime == "ceo":
        ceo_mod.enable_big_cheese()
    name, opts = _parse_arm(spec)
    # Settings are module globals and pool workers are REUSED: set every
    # one each job, or one arm's setting leaks into the next arm's fights.
    playout.ROLLOUT_PLAYER = opts.get("player", "net")
    playout.POUCH_WEIGHT["facility"] = float(opts.get("pouch", 2.0))
    fastplayer.use(opts.get("net") or fastplayer.DEFAULT_WEIGHTS)
    # `mates=off` changes what the ENGINE assumes, never the fight: the
    # real round always lets teammates use what they hold (the game), and
    # only the engine's own rollouts drop them.
    model_mates = opts.get("mates", "on") != "off"
    playout.GROUP_MODE = opts.get("mode", "coordinated")
    # Pickup teammates: `truth` is how they play in the fight, `assume` is
    # what the engine's rollouts expect -- separate so a model of people
    # can be tested against teammates who do not play like it.
    from solver import party as party_mod
    teammates = {"prior": None, "net": party_mod.NetTeammate()}
    playout.TEAMMATE_MODEL = teammates[opts.get("assume", "prior")]
    from solver.search import expectimax, valuenet
    expectimax.BEAM = None
    valuenet.USE = False
    from solver.search import objective as objective_mod
    playout.set_style(objective_mod.PRESETS[opts.get("style", "balanced")])
    stages = tuple(int(x) for x in opts.get("stages", "8/16/32").split("/"))

    sample, coordinated, cap = _sampler(regime)
    env = env_mod.BattleEnv(rng=random.Random(seed), sampler=sample,
                            coordinated=coordinated, max_rounds=cap)
    env.boss_players = PLAYERS.get(regime)
    env.teammate_model = teammates[opts.get("truth", "prior")]
    env.reset()
    if opts.get("kit") == "owner":
        from solver import vp as vp_mod
        for toon in env.state.toons:
            vp_mod.owner_vp_pouch(toon)
    if "unites" in opts:
        for toon in env.state.toons:
            toon.unites_held = int(opts["unites"])
    rng = random.Random(seed)
    done, info, rounds, spent = False, {}, 0, 0.0
    while not done and rounds < 400:
        state = env.state
        if state.toons[0].laff <= 0 and not coordinated:
            plan = [None]
        else:
            view = (playout.solo_view(state) if not coordinated
                    else playout._view(state))
            plan, t0 = None, time.perf_counter()
            playout.TEAMMATE_UNITES = model_mates
            if name == "playout":
                res = playout.pick_wide(state if not coordinated else view,
                                        _horizon(env, state), seed=seed * 1000 + rounds,
                                        stages=stages)
                plan = res.plan if res else None
            elif name == "top3":
                res = playout.pick(view, _horizon(env, state), seed=seed * 1000 + rounds,
                                   rollouts=int(opts.get("rollouts", 8)))
                plan = res.plan if res else None
            elif name == "mcts":
                from solver.search import mcts
                mcts.C_PUCT = float(opts.get("c", 1.5))
                mcts.MENU_K = int(opts.get("k", 4))
                res = mcts.pick(view, _horizon(env, state), seed=seed * 1000 + rounds,
                                iterations=int(opts.get("iters", mcts.ITERATIONS)))
                plan = res.plan if res else None
            elif name == "search":
                # The Search row: expectimax with the panel's settings
                # (collapse, epsilon 0.03), a time budget, optionally the
                # BEAM shortcut and the value network at the leaves.
                expectimax.BEAM = int(opts.get("beam", 0)) or None
                if opts.get("leaf"):
                    valuenet.use(opts["leaf"])
                    valuenet.USE = True
                import dataclasses
                search_obj = objective_mod.PRESETS[opts.get("style", "balanced")]
                if "loss" in opts:
                    search_obj = dataclasses.replace(search_obj, loss_penalty=float(opts["loss"]))
                _v, act = expectimax.best_action_iterative(
                    view.clone(), depth=int(opts.get("depth", 6)),
                    objective=search_obj,
                    time_budget=float(opts.get("budget", 2.0)),
                    exact_plies=0, epsilon=float(opts.get("eps", 0.03)))
                expectimax.BEAM = None
                valuenet.USE = False
                plan = [act] if act is not None else None
            elif name == "net":
                plan = fastplayer.act(view) if len(view.toons) == 1 else None
            elif name != "climb":
                raise ValueError(f"unknown arm {name!r}")
            spent += time.perf_counter() - t0
            if plan is None:
                plan = playout.climb_with_unite(view, rng, budget=24)
        playout.TEAMMATE_UNITES = True
        done, info = playout.step_round(env, plan)
        rounds += 1
    return seed, spec, bool(info.get("win")), rounds, spent / max(1, rounds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regime", choices=REGIMES, default="solo-vp")
    ap.add_argument("--n", type=int, default=200, help="paired seeds")
    ap.add_argument("--base", type=int, default=100000, help="first seed")
    ap.add_argument("--arms", nargs="+", default=["climb", "playout"])
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    jobs = [(args.regime, args.base + i, arm)
            for arm in args.arms for i in range(args.n)]
    wins = {arm: {} for arm in args.arms}
    cost = {arm: [] for arm in args.arms}
    lengths = {arm: [] for arm in args.arms}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for seed, arm, won, rounds, per in pool.map(play, jobs, chunksize=2):
            wins[arm][seed] = won
            cost[arm].append(per)
            lengths[arm].append(rounds)
    seeds = sorted(set.intersection(*(set(v) for v in wins.values())))
    print(f"{args.regime}: {len(seeds)} paired seeds from {args.base}, "
          f"{time.time() - t0:.0f}s")
    first = args.arms[0]
    for arm in args.arms:
        w = sum(wins[arm][s] for s in seeds)
        line = (f"  {arm:28s} {w:4d}/{len(seeds)}  {100.0 * w / len(seeds):5.1f}%"
                f"   {statistics.mean(cost[arm]):.2f}s a decision"
                f"   {statistics.mean(lengths[arm]):.1f} rounds")
        if arm != first:
            up = sum(1 for s in seeds if wins[arm][s] and not wins[first][s])
            dn = sum(1 for s in seeds if wins[first][s] and not wins[arm][s])
            d = up + dn
            p = (sum(comb(d, i) for i in range(min(up, dn) + 1)) / 2.0 ** d * 2
                 if d else 1.0)
            line += f"   vs {first}: +{up}/-{dn} p={min(1.0, p):.3f}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
