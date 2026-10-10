"""Three implementations of one round, held against each other.

    python tools/round_parity.py [positions] [samples]


exact   outcomes.action_outcomes      (what the Search row believes)
solo    simulator.step                (sampled, solo)
party   party.step with one toon      (sampled; what playouts/env use)

For each position and move, compare expected next-round quantities. A
disagreement beyond sampling error means one path implements a rule the
others do not.
"""
import math
import random
import sys
from collections import defaultdict

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solver import outcomes, party, simulator, sos as sos_mod, vp as vp_mod  # noqa: E402
from solver.rl import env as env_mod  # noqa: E402
from solver.state import Track  # noqa: E402

SAMPLES = 500


def metrics(before, after):
    n = len(before.cogs)
    m = {"laff": after.toons[0].laff,
         "n_cogs": len(after.cogs),
         "holdout": len(after.holdout),
         "toons_hit": after.toons_hit_rounds,
         "cogs_miss": after.cogs_miss_rounds,
         "free_passes": after.free_passes,
         "sos_left": sum((after.toons[0].sos_cards or {}).values()),
         "gags_left": sum(after.toons[0].gag_counts.values())}
    for i in range(n):
        c = after.cogs[i] if i < len(after.cogs) else None
        if c is None:
            continue
        m[f"hp{i}"] = max(0, c.hp)
        m[f"dead{i}"] = float(c.status.is_dead)
        m[f"lured{i}"] = float(c.status.lured)
        m[f"lure_left{i}"] = c.status.lure_rounds_remaining if c.status.lured else 0
        m[f"trapped{i}"] = float(c.status.trapped)
        m[f"suited{i}"] = float(c.status.suited)
    return m


def position(rng):
    pick = rng.random()
    if pick < 0.4:
        st = env_mod.default_position(rng)
    elif pick < 0.7:
        st = vp_mod.vp_position(rng)
        have = [t for t in Track if t is not Track.TOON_UP]
        st.toons = [vp_mod.maxed_toon(rng, tracks=have, laff=rng.randint(30, 140))]
        st.cogs = [env_mod.BattleEnv(rng=rng)._sellbot_cog(rng, rng.randint(6, 12))
                   for _ in range(rng.randint(1, 4))]
        for c in st.cogs:
            c.hp = rng.randint(1, c.max_hp)
    else:
        st = env_mod.facility_position(rng)
        st.toons = st.toons[:1]
    st.toons = st.toons[:1]
    st.allies_standing = 0
    toon = st.toons[0]
    if rng.random() < 0.5:
        toon.sos_cards = {k: 1 for k in rng.sample(list(sos_mod.BY_NAME), 4)}
        if rng.random() < 0.5:
            toon.sos_calls = rng.randint(0, 2)
    st.sos_one_round = rng.random() < 0.3
    if rng.random() < 0.25:
        st.toons_hit_rounds = rng.randint(1, 3)
    if rng.random() < 0.25:
        st.cogs_miss_rounds = rng.randint(1, 3)
    for c in st.cogs:
        r = rng.random()
        if r < 0.3 and not c.status.lured:
            c.status.apply_lure(80, rng.randint(1, 4), level=rng.choice([4, 5, 6, 7]))
        elif r < 0.45 and not c.status.lured:
            c.status.trapped = True
            c.status.trap_track = Track.TRAP
            c.status.trap_level = rng.randint(3, 7)
    return st


def exact(state, action):
    out = defaultdict(float)
    for p, nxt, _r in outcomes.action_outcomes(state, action):
        for k, v in metrics(state, nxt).items():
            out[k] += p * v
    return out


def sampled(state, action, how, seed):
    sums, sq = defaultdict(float), defaultdict(float)
    rng = random.Random(seed)
    for _ in range(SAMPLES):
        if how == "solo":
            random.seed(rng.random())
            nxt, _r, _d = simulator.step(state, action)
        else:
            nxt, _h, _d = party.step(state, joint=[action], mode=party.Mode.COORDINATED,
                                     rng=random.Random(rng.random()))
        for k, v in metrics(state, nxt).items():
            sums[k] += v
            sq[k] += v * v
    mean = {k: sums[k] / SAMPLES for k in sums}
    se = {k: math.sqrt(max(0.0, sq[k] / SAMPLES - mean[k] ** 2) / SAMPLES) for k in sums}
    return mean, se


def describe(a):
    if a.sos:
        return "SOS " + a.sos
    if a.fire:
        return f"fire@{a.target_index}"
    if a.track is None:
        return "pass"
    return f"{a.track.name}{a.level}@{a.target_index}"


def check(positions: int, seed: int = 7):
    """{description: [examples]} of every disagreement found."""
    rng = random.Random(seed)
    flags = defaultdict(list)
    checked = 0
    for n in range(positions):
        st = position(rng)
        legal = simulator.legal_actions(st)
        if not legal:
            continue
        for action in rng.sample(legal, min(3, len(legal))):
            try:
                ex = exact(st, action)
            except Exception as e:  # noqa: BLE001
                flags["exact raised " + type(e).__name__].append((n, describe(action), str(e)[:80]))
                continue
            for how in ("solo", "party"):
                try:
                    mean, se = sampled(st, action, how, seed=n * 100 + len(flags))
                except Exception as e:  # noqa: BLE001
                    flags[f"{how} raised " + type(e).__name__].append((n, describe(action), str(e)[:80]))
                    continue
                for k in set(ex) | set(mean):
                    a, b = ex.get(k, 0.0), mean.get(k, 0.0)
                    tol = 5 * se.get(k, 0.0) + 1e-6 + 0.02 * abs(a)
                    if abs(a - b) > tol:
                        key = k.rstrip("0123456789")
                        flags[f"{how} vs exact: {key}"].append(
                            (n, describe(action), round(a, 3), round(b, 3)))
            checked += 1
    return checked, flags


def main():
    global SAMPLES
    positions = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    checked, flags = check(positions)
    print(f"checked {checked} (position, move) pairs, {SAMPLES} samples each")
    for k, rows in sorted(flags.items(), key=lambda kv: -len(kv[1])):
        print(f"\n{k}: {len(rows)}")
        for r in rows[:6]:
            print("   ", r)


if __name__ == "__main__":
    main()
