"""Does reaching the SOS cards actually WIN, or only score better?

Two arms on IDENTICAL seeds, differing in one flag:
  charged   -- cards cost a judge call, so the budget truncates them
                (the behaviour before the fix)
  free      -- cards are always judged (shipped)

The default VP toon carries no cards at all, so the harness stocks a
plausible endgame deck. Without that the two arms are identical by
construction and the sweep measures nothing.

An SOS action has no index in `env.ACTIONS`, so it MUST be passed to
`step` as `action=`. Mapping it through the index table alone silently
turns every card call into a pass -- which is how a previous run of this
measurement came back saying cards were worthless.
"""
import random
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, ".")

DECK = {"Flippy": 1, "Daffy Don": 1, "Professor Pete": 1,
        "Moe Zart": 1, "Barnacle Bessie": 1,
        "Julius Wheezer": 1, "Sticky Lou": 1}
FIRES = 3
BUDGET = 24
TOONS = 1
UNITES = 0


def _play(args):
    seed, charged, toons, unites = args
    global TOONS, UNITES
    TOONS, UNITES = toons, unites
    from solver import sos as sos_mod
    from solver.rl import env as env_mod
    from solver.search import hybrid
    from solver import vp as vp_mod

    hybrid.SOS_CHARGED_TO_BUDGET = charged

    def sampler(rng):
        state = vp_mod.vp_position(rng)
        # SOLO. A two-toon maxed party is near-saturated on the VP,
        # so the win rate can barely tell the arms apart -- see
        # docs/party-strategy.md. Solo is the unsaturated regime and
        # the one the recorded run that started this was played in.
        state.toons = state.toons[:TOONS]
        for toon in state.toons:
            toon.fires = FIRES
            toon.unites_held = UNITES
            toon.sos_cards = {k: v for k, v in DECK.items()
                              if k in sos_mod.BY_NAME}
        return state

    env = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                            coordinated=True, max_rounds=400)
    env.reset()
    rng = random.Random(seed)
    plan, done, guard, info, seen = None, False, 0, {}, -1
    calls = 0
    while not done and guard < 4000:
        guard += 1
        if env.rounds != seen:
            seen = env.rounds
            plan = hybrid.climb(env.state, rng, budget=BUDGET)
        a = plan[env.actor] if plan and env.actor < len(plan) else None
        index, passthrough = env_mod.PASS_INDEX, None
        if a is not None and getattr(a, "sos", None):
            passthrough = a                      # no index exists for a card
            calls += 1
        elif a is not None and a.fire:
            index = env_mod._FIRE_INDEX.get(a.target_index, env_mod.PASS_INDEX)
        elif a is not None and not a.is_pass:
            for k, c in enumerate(env_mod.ACTIONS):
                if (c is not None and not c.fire and c.track == a.track
                        and c.level == a.level
                        and c.target_index == a.target_index):
                    index = k
                    break
        try:
            if passthrough is not None:
                _o, _m, _r, done, info = env.step(index, action=passthrough)
            else:
                _o, _m, _r, done, info = env.step(index)
        except Exception:                        # noqa: BLE001
            return seed, charged, False, calls, env.rounds
    return seed, charged, bool(info.get("win")), calls, env.rounds


def main(n=80, base=90000):
    jobs = [(base + i, charged, TOONS, UNITES)
            for i in range(n) for charged in (True, False)]
    out = {True: {}, False: {}}
    cards = {True: 0, False: 0}
    rounds = {True: 0, False: 0}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for seed, charged, won, calls, rds in pool.map(_play, jobs):
            out[charged][seed] = won
            cards[charged] += calls
            rounds[charged] += rds
    seeds = sorted(set(out[True]) & set(out[False]))
    a = sum(out[True][s] for s in seeds)
    b = sum(out[False][s] for s in seeds)
    flips_up = [s for s in seeds if out[False][s] and not out[True][s]]
    flips_dn = [s for s in seeds if out[True][s] and not out[False][s]]
    print("\n  VP, %d paired sides, budget %d, deck of %d cards + %d slips"
          % (len(seeds), BUDGET, len(DECK), FIRES))
    print("    charged (pre-fix) : %3d/%d  %5.1f%%   cards called %4d   rounds %5d"
          % (a, len(seeds), 100.0*a/len(seeds), cards[True], rounds[True]))
    print("    free    (shipped) : %3d/%d  %5.1f%%   cards called %4d   rounds %5d"
          % (b, len(seeds), 100.0*b/len(seeds), cards[False], rounds[False]))
    print("\n    paired: +%d won only when free, -%d won only when charged"
          % (len(flips_up), len(flips_dn)))
    # Rounds-to-finish reads more sensitively than win/loss when the
    # arms are close: the same outcome reached sooner is still better.
    print("    rounds: charged %.1f/side, free %.1f/side"
          % (rounds[True]/len(seeds), rounds[False]/len(seeds)))
    n_disc = len(flips_up) + len(flips_dn)
    if n_disc:
        # Exact two-sided sign test on the discordant pairs.
        from math import comb
        k = min(len(flips_up), len(flips_dn))
        p = sum(comb(n_disc, i) for i in range(0, k + 1)) / 2.0 ** n_disc * 2
        print("    sign test on %d discordant pairs: p = %.4f" % (n_disc, min(1.0, p)))
    else:
        print("    no discordant pairs -- the flag changed no outcome")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        TOONS = int(sys.argv[2])
    if len(sys.argv) > 3:
        UNITES = int(sys.argv[3])
    print("  config: %d toon(s), %d unites, %d slips, %d cards"
          % (TOONS, UNITES, FIRES, len(DECK)))
    main(n=int(sys.argv[1]) if len(sys.argv) > 1 else 80)
