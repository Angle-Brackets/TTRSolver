"""A behaviour lock for refactoring. Nothing here tests a rule.

Every other test in this suite asserts something about the GAME. This
one asserts only that the code does today what it did yesterday, on a
spread of sampled positions, so that a move-things-around change can be
shown not to have altered a single decision.

It exists because this project's value is measured behaviour. A weight
that was swept, a term that was refuted, a probe that pays seven points
-- all of it lives in code that is about to be reorganised, and "pure
move, no logic change" is a claim until something checks it.

HOW TO USE IT DURING A REFACTOR

  1. Before touching anything, run with LOCK_WRITE=1 to record the
     baseline into tests/data/refactor_lock.json.
  2. Refactor.
  3. Run normally. Any drift fails with the position that moved.

The baseline is committed, so it also catches an unintended behaviour
change arriving through an ordinary edit months later.

WHAT IT COVERS: the observation, the fast scorer and the policy's
chosen action -- the three things every measurement this session
depended on. Not the exact search, which is slow and already pinned by
its own tests.
"""
import json
import os
import pathlib
import random
import unittest

from solver import data
from solver.rl import env as env_mod
from solver.search import party_search as ps
from solver.state import BattleState, CogState, ToonState, Track

BASELINE = pathlib.Path(__file__).parent / "data" / "refactor_lock.json"
SAMPLES = 120

SELLBOTS = ["cold_caller", "telemarketer", "name_dropper", "glad_hander",
            "mr_hollywood"]


def _position(rng):
    """A sampled board. Deterministic in `rng`, and deliberately varied:
    party sizes, wounded toons, lured and trapped cogs, slips held."""
    tracks = [t for t in Track if t is not Track.TOON_UP]
    toons = []
    for _ in range(rng.randint(1, 3)):
        cap = rng.choice([40, 65, 100, 137])
        toon = ToonState(rng.randint(1, cap), cap,
                         {t: rng.randint(1, 7) for t in tracks}, {},
                         frozenset(rng.sample(tracks, rng.randint(0, 2))),
                         pouch_capacity=80)
        env_mod.restock(toon, rng)
        toon.fires = rng.choice([0, 0, 2, 5])
        toons.append(toon)
    cogs = []
    for _ in range(rng.randint(1, 4)):
        key = rng.choice(SELLBOTS)
        spec = data.cog("sellbot", key)
        level = rng.choice(spec.levels)
        hp = data.cog_max_hp(level)
        cog = CogState(department="sellbot", cog_type=key, level=level,
                       hp=max(1, int(hp * rng.uniform(0.15, 1.0))),
                       max_hp=hp)
        if rng.random() < 0.35:
            cog.status.apply_lure(0.75, rng.randint(1, 5), level=5)
        cogs.append(cog)
    state = BattleState(cogs=cogs, toons=toons)
    state.round_num = rng.randint(0, 6)
    return state


def _fingerprint():
    """One dict of everything the lock watches."""
    from solver.search import hybrid

    out = {"obs_dim": env_mod.OBS_DIM, "obs_version": env_mod.OBS_VERSION,
           "n_actions": len(env_mod.ACTIONS), "positions": []}
    model = hybrid._load()
    for seed in range(SAMPLES):
        rng = random.Random(90000 + seed)
        state = _position(rng)
        entry = {
            "obs": [round(v, 6) for v in env_mod.encode(state, 0, None)],
            "legal": sum(1 for ok in env_mod.legal_mask(state, 0) if ok),
        }
        # The fast scorer, on a fixed plan rather than a searched one, so
        # this pins the SCORER and not the search.
        from solver import simulator
        actions = [a for a in simulator.legal_actions(state)
                   if not a.is_pass][:1]
        plan = [actions[0] if actions else None] + [None] * (
            len(state.toons) - 1)
        try:
            entry["quick"] = round(ps._quick_score(state, plan), 4)
        except Exception as exc:            # noqa: BLE001
            entry["quick"] = f"raised {exc.__class__.__name__}"

        # THE SCORER'S PARTS, not just its total. `armed_credit`,
        # `prevented`, `toons_at_risk` and `killed_threat` have no direct
        # test anywhere in the repo -- the lock reached them only through
        # the one number `_quick_score` returns, where an error in one
        # can be cancelled by an error in another. Pinned individually
        # before party_search.py is reorganised.
        after = state.clone()
        try:
            from solver import simulator as sim
            sim.apply_party_round(after, list(plan),
                                  hits=[True] * len(plan))
        except Exception:                   # noqa: BLE001
            after = state
        for name, call in (
                ("incoming", lambda: ps.expected_incoming(state)),
                ("survival", lambda: ps.survival_rounds(state)),
                ("at_risk", lambda: ps.toons_at_risk(state)),
                ("prevented", lambda: ps.prevented(state, after)),
                ("killed_threat", lambda: ps.killed_threat(state, after)),
                ("armed", lambda: ps.armed_credit(state, after)),
                ("waste", lambda: ps.plan_waste(state, plan)),
        ):
            try:
                value = call()
            except Exception as exc:        # noqa: BLE001
                entry[name] = f"raised {exc.__class__.__name__}"
                continue
            if isinstance(value, tuple):
                entry[name] = [round(float(v), 4) for v in value]
            else:
                entry[name] = round(float(value), 4)
        if model is not None:
            plan = hybrid.climb(state, random.Random(seed), budget=8)
            first = plan[0] if plan else None
            entry["pick"] = ("pass" if first is None or first.is_pass
                             else "fire" if first.fire
                             else f"{first.track.value}/{first.level}/"
                                  f"{first.target_index}")
        out["positions"].append(entry)
    return out


class RefactorLockTest(unittest.TestCase):

    def test_behaviour_is_unchanged(self):
        current = _fingerprint()
        if os.environ.get("LOCK_WRITE"):
            BASELINE.parent.mkdir(parents=True, exist_ok=True)
            BASELINE.write_text(json.dumps(current, indent=1),
                                encoding="utf-8")
            self.skipTest(f"baseline written to {BASELINE}")
        if not BASELINE.exists():
            self.skipTest("no baseline; run with LOCK_WRITE=1 to record")

        saved = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(saved["obs_dim"], current["obs_dim"],
                         "observation width moved")
        self.assertEqual(saved["n_actions"], current["n_actions"],
                         "action table moved")
        self.assertEqual(len(saved["positions"]), len(current["positions"]))
        for i, (was, now) in enumerate(zip(saved["positions"],
                                           current["positions"])):
            for key in ("legal", "quick", "pick", "incoming", "survival",
                        "at_risk", "prevented", "killed_threat", "armed",
                        "waste"):
                if key in was or key in now:
                    self.assertEqual(
                        was.get(key), now.get(key),
                        f"position {i}: {key} changed from "
                        f"{was.get(key)!r} to {now.get(key)!r}")
            self.assertEqual(was["obs"], now["obs"],
                             f"position {i}: observation changed")
