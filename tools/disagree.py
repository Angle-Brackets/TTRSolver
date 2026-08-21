"""What does a disagreement between the two agents actually cost?

    python tools/disagree.py --buildings 60

THE QUESTION THIS ANSWERS
-------------------------
The policy and the search finish the same fraction of buildings (65.9%
against 65.0%, inside the noise). They do NOT play the same way, and the
usage tables only say so in aggregate: the policy holds 11.9% of rounds
and the search 11.0%, which is agreement about the RATE of holding and
says nothing about whether they hold in the same POSITIONS. A policy can
match every marginal and still hold in all the wrong rounds.

So: replay held-out buildings, find every round where the two disagree,
and measure what the disagreement is worth. That splits the difference
between them into two piles -- harmless style, and real cost -- and only
the second pile is worth any more work.

COMMON RANDOM NUMBERS, AND WHY WITHOUT THEM THIS MEASURES NOTHING
-----------------------------------------------------------------
The naive version plays branch A (the policy's action) and branch B (the
search's), then compares. But this game's outcome variance is enormous --
one missed 95% gag loses a floor -- so the difference between two
independently-rolled branches is mostly dice. It is exactly how the PPO
rollout judge came to be worth -3.3 to -3.8: it was reading noise.

CRN gives both branches the SAME dice. Fork the state, play A's action in
one and B's in the other, then continue BOTH under one fixed policy
(`greedy_plan`) with an identical random stream. Whatever difference
survives is caused by the action, because nothing else differed. It is a
trial on identical twins rather than on two strangers.

THE COUPLING IS PER ROUND, AND THAT IS A DELIBERATE COMPROMISE
--------------------------------------------------------------
Perfect coupling is not available through this simulator's interface.
`apply_party_round` draws accuracy per attack AS IT RESOLVES, because the
stun bonus depends on what has already landed, so the number of draws a
round makes depends on what was thrown. The moment branch A throws where
branch B holds, a single shared stream DESYNCHRONISES and every later
round is comparing strangers again.

Re-seeding both branches identically at the START OF EACH ROUND bounds
that: within a round the two may diverge, but they resynchronise at the
next boundary rather than drifting apart for twelve rounds. The residual
is real and is the reason `--repeats` exists -- averaging a few streams
removes what the coupling could not.

WHAT IT FOUND
-------------
500 forks over 47 held-out buildings, paired, cluster-bootstrapped by
BUILDING because ten forks from one building are not ten independent
observations.

    bucket    greedy continuation          policy continuation
    overall   +2.29 [+0.32, +4.30] *       +0.75 [-0.80, +2.43]
    target    +5.94 [+2.02, +9.40] *       +0.90 [-1.64, +3.29]
    track     +2.65 [+0.05, +5.41] *       +0.86 [-1.26, +3.27]
    hold      -0.18 [-2.52, +2.39]         -0.01 [-1.36, +1.37]
    sign test 78-47 to search, p=0.007     59-51, p=0.50

Three results, in descending order of how much they should change what
anyone does next.

**THE AGENTS DISAGREE ALMOST ALWAYS AND IT ALMOST NEVER MATTERS.** They
pick the same joint plan on 5.3% of rounds and three quarters of their
disagreements are worth under a point. Two agents playing what is very
nearly a different game, finishing the same fraction of buildings.

**HOLDING IS WORTH NOTHING**, on 233 samples with a tight interval around
zero under both continuations. Reward shaping, hold-variants, the wider
observation and four attempts to teach `_quick_score` patience were all
aimed at reproducing the search's 11% hold rate. It does not pay.

**AND THE SEARCH'S APPARENT EDGE IS AN ARTIFACT OF WHO PLAYS ON.** Under
`greedy_plan` the search leads by +2.29 and target selection by +5.94,
both surviving a sign test and a cluster bootstrap. Swap the continuation
for the climb and every one of those intervals covers zero. The reason is
that `greedy_plan` IS THE SEARCH'S OWN ROLLOUT POLICY: its moves were
chosen assuming that follow-up and were then scored under it, while the
policy's moves were chosen assuming the policy continues. A fourth
instance of the judge sharing the proposer's assumptions, and the most
expensive to have nearly missed.

Neither continuation is neutral -- greedy flatters the search, the climb
flatters the policy -- so the honest reading is not "no difference" but
something sharper: **the better move depends on who is playing after it.**
That is why every attempt to move the policy's behaviour toward the
search moved the behaviour and not the result. The search's moves are
good *for the search's continuation*, not good in themselves, and
transplanting them into a different player transplants nothing.

"""
from __future__ import annotations

import argparse
import copy
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                          # noqa: E402
from solver.search import hybrid                              # noqa: E402
from solver.search import party_search as ps                  # noqa: E402
from solver.search import objective as objective_mod          # noqa: E402


def _plan_of(plan, state):
    """A comparable tuple for a joint plan, one entry per seat."""
    out = []
    for seat in range(len(state.toons)):
        action = plan[seat] if plan and seat < len(plan) else None
        if action is None or action.is_pass:
            out.append(None)
        else:
            out.append((action.track, action.level, action.target_index))
    return tuple(out)


def _kind(a, b):
    """How two seat-actions differ: track, level, target, or not at all."""
    if a == b:
        return "same"
    if a is None or b is None:
        return "hold"
    if a[0] != b[0]:
        return "track"
    if a[1] != b[1]:
        return "level"
    return "target"


def branch_outcome(env, plan, dice, objective, continuation="greedy",
                   budget=8, max_steps=250):
    """Fork the ENV, force `plan` this round, then play the rest out.

    The first version of this forked the STATE and scored one battle with
    `apply_party_round`. Every fork came back at exactly +0.00, and the
    reason is worth keeping: a battle is not the task. `apply_party_round`
    does not advance floors -- that is the env's job -- so the building
    collapsed to its first fight, both agents won it, and the score
    saturated at "all cogs dead plus the win bonus" no matter what was
    thrown. The whole point of a building is that the pouch and the laff
    carry to the next floor, and that was exactly what got discarded.

    So the fork is a deepcopy of the env, the continuation plays every
    remaining floor, and the value is the thing actually wanted: did the
    building get cleared, and how far did it get.

    WHICH POLICY CONTINUES IS NOT A DETAIL.
    `greedy_plan` is THE SEARCH'S OWN ROLLOUT POLICY. Scoring both
    branches under it asks "whose action is better for a greedy
    follow-up", and the search picked its action assuming exactly that
    follow-up while the policy picked its own assuming it would keep
    playing. That is the judge sharing the proposer's assumptions, which
    this project has now been bitten by three times, so the continuation
    is a flag and the comparison is only worth believing if it survives
    both settings.
    """
    e = copy.deepcopy(env)
    # Both branches get the same dice from the fork onward. This is the
    # coupling; without it the comparison is two strangers again.
    e.rng = random.Random(dice)
    forced, steps = list(plan), 0
    while steps < max_steps:
        steps += 1
        if all(a is None for a in e.pending) and forced is None:
            if continuation == "policy":
                forced = hybrid.climb(e.state, random.Random(dice),
                                      budget=budget)
            else:
                forced = ps.greedy_plan(e.state, objective)
        action = (forced[e.actor]
                  if forced and e.actor < len(forced) else None)
        index = env_mod.PASS_INDEX
        if action is not None and not action.is_pass:
            for i, cand in enumerate(env_mod.ACTIONS):
                if (cand is not None and cand.track == action.track
                        and cand.level == action.level
                        and cand.target_index == action.target_index):
                    index = i
                    break
        mask = env_mod.legal_mask(e.state, e.actor)
        if not mask[index]:
            index = env_mod.PASS_INDEX
        _obs, _mask, _r, done, info = e.step(index)
        # The round has resolved exactly when `pending` is empty again.
        # Detecting it on `actor == 0` instead was wrong for any party of
        # more than one: the flag was only ever set on the FIRST seat, so
        # `forced` never cleared, both branches replayed the fork plan
        # every round, the mask rejected the spent gags, and the two
        # degenerated into passing -- which is why the deltas came back
        # at zero a second time.
        if all(a is None for a in e.pending):
            forced = None            # back to the rollout policy
        if done:
            return (100.0 if info.get("win") else 0.0) + float(info.get("floor", 0))
    return float(getattr(e, "floor", 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--buildings", type=int, default=60)
    ap.add_argument("--start", type=int, default=36000,
                    help="seed set; 36000 is held out and never tuned on")
    ap.add_argument("--rounds", type=int, default=6,
                    help="how far past the fork to play each branch")
    ap.add_argument("--repeats", type=int, default=3,
                    help="independent dice streams per fork, averaged; the "
                         "coupling is per-round so a little averaging is "
                         "still needed")
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--continuation", choices=("greedy", "policy"),
                    default="greedy",
                    help="who plays on after the fork. `greedy` is the SEARCH's own rollout policy and therefore favours it; `policy` is the climb. A real effect survives both.")
    ap.add_argument("--limit", type=int, default=400,
                    help="stop after this many forks")
    args = ap.parse_args()

    if not hybrid.available():
        print(f"  no usable policy: {hybrid.unavailable_reason()}")
        return 1

    objective = objective_mod.DEFAULT
    rows, agree, total_decisions = [], 0, 0

    for offset in range(args.buildings):
        seed = args.start + offset
        e = env_mod.BattleEnv(rng=random.Random(seed),
                              sampler=env_mod.facility_position,
                              coordinated=True)
        obs, mask = e.reset()
        rng = random.Random(seed)
        plan, done, guard = None, False, 0
        while not done and guard < 250 and len(rows) < args.limit:
            guard += 1
            if all(a is None for a in e.pending):
                state = e.state
                mine = hybrid.climb(state, random.Random(seed), budget=args.budget)
                theirs = ps.best_plan(state, mode=ps.Mode.COORDINATED,
                                      rng=random.Random(seed))
                total_decisions += 1
                key_a, key_b = _plan_of(mine, state), _plan_of(theirs, state)
                if key_a == key_b:
                    agree += 1
                else:
                    deltas = []
                    for r in range(args.repeats):
                        dice = seed * 7919 + guard * 31 + r
                        va = branch_outcome(e, mine, dice, objective,
                                            args.continuation, args.budget)
                        vb = branch_outcome(e, theirs, dice, objective,
                                            args.continuation, args.budget)
                        deltas.append(vb - va)
                    kinds = [_kind(a, b) for a, b in zip(key_a, key_b)]
                    rows.append({
                        "seed": seed, "round": guard,
                        "delta": statistics.mean(deltas),
                        "spread": (max(deltas) - min(deltas)),
                        "kinds": [k for k in kinds if k != "same"],
                        "mine": key_a, "theirs": key_b,
                    })
                plan = mine
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
            obs, mask, _r, done, _i = e.step(index)
        if len(rows) >= args.limit:
            break

    if not rows:
        print("  no disagreements found")
        return 0

    deltas = [r["delta"] for r in rows]
    coupling = statistics.mean(r["spread"] for r in rows)
    print(f"\n  continuation           {args.continuation}")
    print(f"  decisions compared     {total_decisions}")
    print(f"    identical joint plan {agree}"
          f"   ({agree / max(1, total_decisions) * 100:.1f}%)")
    print(f"    disagreements        {len(rows)}")
    print(f"\n  value delta (search minus policy), CRN-paired")
    # The mean alone decides nothing. `spread` below is a max-minus-min
    # RANGE over the dice streams of one fork, which is NOT a standard
    # error and must not be read as an error bar. What settles whether
    # the mean is real is the scatter of the per-fork deltas over the
    # root of how many forks there are.
    sd = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
    se = sd / (len(deltas) ** 0.5) if deltas else 0.0
    mean = statistics.mean(deltas)
    away = (abs(mean) / se) if se else 0.0
    print(f"    mean      {mean:+.2f}   sd {sd:.2f}   se {se:.2f}"
          f"   ({away:.1f} se from zero)")
    print(f"    median    {statistics.median(deltas):+.2f}")
    print(f"    search better in {sum(1 for d in deltas if d > 1):d}, "
          f"policy better in {sum(1 for d in deltas if d < -1):d}, "
          f"within +-1 in {sum(1 for d in deltas if abs(d) <= 1):d}")
    print(f"    dice-stream range per fork, averaged  {coupling:.2f}"
          f"   (a RANGE across streams, not an error bar)")

    print(f"\n  by what differed:")
    for kind in ("hold", "track", "level", "target"):
        sel = [r["delta"] for r in rows if kind in r["kinds"]]
        if sel:
            print(f"    {kind:8s} n={len(sel):4d}   mean {statistics.mean(sel):+7.2f}"
                  f"   median {statistics.median(sel):+7.2f}")

    out = Path(f"disagreements-{args.continuation}.tsv")
    with out.open("w", encoding="utf-8") as fh:
        fh.write("seed\tround\tdelta\tspread\tkinds\n")
        for r in rows:
            fh.write(f"{r['seed']}\t{r['round']}\t{r['delta']:.3f}\t"
                     f"{r['spread']:.3f}\t"
                     f"{','.join(sorted(set(r['kinds'])))}\n")
    print(f"\n  raw deltas written to {out}")

    worst = sorted(rows, key=lambda r: r["delta"], reverse=True)[:5]
    print(f"\n  where the search gained most:")
    for r in worst:
        print(f"    seed {r['seed']} round {r['round']:3d}  "
              f"delta {r['delta']:+7.2f}  differed in {','.join(sorted(set(r['kinds'])))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
