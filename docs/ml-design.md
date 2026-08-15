# Learning a policy: scope and design

Status: **proposal, for review.** Nothing here is built.

The short version: **PPO is the right tool for one half of this problem
and the wrong tool for the other half**, and the split is not where you
would expect. Solo has an exact oracle, so learning from it is
supervised and cheap. Party has no oracle at all, which is exactly
where reinforcement learning earns its keep — and also where the
simulator is least trustworthy, which is the main risk in the whole
plan.

---

## 1. What we already have, and what beating it means

| piece | state |
| --- | --- |
| Environment | `simulator` + `party.step` — complete, deterministic given a seed |
| Reward | `objective.step_reward` / `party_search.round_reward` |
| Action enumeration | `simulator.legal_actions`, `party_search.candidates` |
| Solo oracle | `expectimax.solve` — **exact**, plays to the end |
| Current evaluator | 17 hand-built features, least-squares fit |
| Current baseline | hold-out MAE 27, r 0.83, **ordering 91%** |

That last row is the number to beat. *Ordering* matters more than MAE:
the search only needs to rank moves correctly, and a model with worse
MAE but better ordering is a better evaluator.

**A learned model must be compared against the fitted linear model, not
against the hand-written heuristic.** The hand-written baseline scores
52% ordering — beating it proves nothing. This mistake is already
recorded in `tools/fit_heuristic.py`, where `score()` deliberately calls
`hand_written_value` so a shipped fit cannot silently grade itself
against its own predecessor.

---

## 2. Solo: do not use PPO

Solo has an **exact oracle**. `expectimax.solve` plays a position to the
end of the battle with no heuristic, because every action spends a gag,
so the state graph is a DAG. We can generate ground-truth labels for any
position we can afford to solve.

Where labels exist, reinforcement learning is the wrong instrument. PPO
would spend millions of environment steps rediscovering, noisily, a
value function we can compute exactly. The right move is supervised:

**Proposal S1 — replace the linear evaluator with a small MLP.**

- Input: the existing 17 features, or the raw state encoding from §4.
- Target: `solve()` value, same labels `tools/fit_heuristic.py` caches.
- Model: 2–3 hidden layers, ~64–128 units. This is a tabular-scale
  problem; nothing here wants a large network.
- Cost: labels are already cached (5,000 train / 406 hold-out). Training
  is minutes on CPU.
- Success: **ordering > 91% on the same hold-out**, at inference cost
  the search can afford.

Two things make this cheaper than it looks. Labelling is already
parallelised and cached, and the cache key digests the rule files, so a
rule change invalidates labels automatically rather than silently
poisoning them.

The honest risk: `solve()` is only tractable on **small** positions, and
small positions are where the evaluator matters least — the search
reaches a terminal state without consulting it. Anything fitted here
extrapolates to crowded fights. That is why `--holdout-big` exists, and
it is the number to watch.

---

## 3. Party: this is where RL belongs

There is **no oracle**. Exact `solve()` cannot reach a party position,
so there are no labels to fit and no ground truth to check against.
Everything currently reported for parties is an estimate under a
rollout policy that is itself a guess.

That is a genuine RL setting. Three candidate designs, in the order I
would try them:

### P1 — Learn the value function from rollout returns (recommended first)

Not PPO. Keep the existing search and replace only the leaf.

- Collect party positions, play each out with the current policy,
  record the return.
- Train a value network on (position → return).
- Feed it back as `party_search`'s leaf, replacing `rollout_value`.
- Iterate: better values → better rollouts → better targets.

This is TD-Gammon-shaped, and it is the smallest change that could
plausibly work. It reuses the search, the reward, and the evaluation
harness. It also directly fixes the known defect that a rollout costs
73% of search time — a network leaf is a single forward pass.

**Success criterion:** search with the learned leaf beats search with
`rollout_value` head-to-head at equal wall-clock. Equal *node count* is
the wrong comparison; the network's whole advantage is speed.

### P2 — PPO on the pickup-mode policy

Defensible, and the closest to what you asked for.

- One agent controls `toons[0]`; teammates sample from `SensiblePrior`.
- This is a genuine POMDP-ish single-agent problem with a stochastic
  environment, which is PPO's home ground.
- Output: a policy that plays pickup mode without search.

The prize is **latency**. Live advice currently needs a search; a
trained policy answers in one forward pass, which matters if this is
ever to advise during a real battle.

The catch: it learns to play *with `SensiblePrior` teammates*, and
`SensiblePrior` is an invented model of people. A policy trained against
it is fitted to our guess about strangers, not to strangers.

### P3 — Self-play for coordinated mode

Most interesting, least tractable. The joint action space is
(actions per toon)^4, which is why `party_search` samples rather than
enumerates. Options are centralised-critic multi-agent PPO, or treating
the team as one agent emitting a joint action with a factored head.

I would not start here. Start with P1, and only come back if P1's value
function turns out to be the binding constraint.

---

## 4. Representation

**Observation.** Fixed-size, permutation-aware:

- Per cog (pad to 4): level, hp / max_hp, department one-hot, lured,
  trapped, lure rounds remaining.
- Per toon (pad to 4): laff / max_laff, per-track training, per-(track,
  level) gag counts (49 values), organic flags.
- Global: round number, whose turn.

Cogs are **not** interchangeable (targets are indexed) and toons are
**not** interchangeable (`state_key` already keys on every toon in
order, deliberately, and a frozenset there would let the memo answer
about one party with another's value). So no set-pooling; keep the
ordering and let the network learn it.

**Action space.** Factored, not flat: `(track, level, target)` heads
plus a hold action. A flat space is ~7×7×5 = 245 mostly-illegal actions.
Mask illegal actions with `legal_actions` — masking, not penalising, so
the policy never spends probability mass on moves it cannot make.

**Reward.** Reuse `round_reward` exactly. Do **not** invent a training
reward: if the agent optimises something different from what the search
optimises, the comparison between them is meaningless.

---

## 5. The risks, in order of how much they worry me

**1. The simulator has bugs, and an agent will learn them.** This is the
big one. In one session this project found: Toon-Up healing the thrower
instead of teammates (the rule exactly backwards), group cog attacks not
modelled at all (parties took strictly less damage than the game deals),
and a heal absorbing the same round's damage. A search exposes such bugs
because a human reads its output and says "nobody plays that". **A
trained policy silently exploits them and looks confident.** Every one
of those bugs was found by a human noticing a weird recommendation.

Mitigation: keep the search as a cross-check, and treat any large
policy-vs-search disagreement as a suspected simulator bug until shown
otherwise.

**2. Known-unknowns in the rules.** `MULTI_LURE_ACCURACY_BONUS` is
`[ASSUMED]` and load-bearing on Lure strategy. The `maxE` window is
owner-stated, not wiki-confirmed. An agent trained now bakes those in.
Prefer training *after* the multi-Lure measurement, or accept that Lure
policy is provisional.

**3. Throughput.** The simulator is pure Python. A party round is
milliseconds; PPO wants millions of steps. Measure steps/sec **before**
committing to P2 — if it is ~1k/s, a 10M-step run is three hours per
seed, and that changes the plan. `solver/search/parallel.py` exists and
labelling already parallelises, so this is tractable, but it should be
measured rather than assumed.

**4. Reward weights are chosen, not derived.** `laff_weight`,
`scarcity_cost`, `waste_weight`, `rare_gag_premium`, `turn_cost` — all
swept and sane, none calibrated against real play. An agent will
optimise them *harder* than a shallow search does, so any mis-set weight
gets amplified rather than smoothed.

**5. Dependencies.** The core and the whole suite run on the standard
library alone; only `solver/live/vision.py` needs numpy, and
`tests/test_vision.py` skips rather than fails without it. **Torch must
stay in the same category**: training lives in `tools/`, inference ships
as plain floats or is optional, and `solver/` must not import it at
module level. Same shape as `search/fitted.py`, which is a block of
literals precisely so inference is stdlib-only.

---

## 6. What I would actually do

1. **Measure throughput.** Steps/sec for a party round. One afternoon,
   and it decides whether P2 is a weekend or a fortnight.
2. **S1** — MLP on cached `solve()` labels. Cheapest real signal about
   whether learned function approximation buys anything here at all. If
   an MLP cannot beat 91% ordering with exact labels, PPO will not save
   the party case.
3. **P1** — learned value leaf for `party_search`. Biggest expected win,
   reuses everything, and directly attacks the 73%-of-runtime rollout.
4. **P2** — PPO for pickup, only if latency turns out to matter, i.e.
   only if this is going live.
5. **P3** — not yet.

## 7. How we will know it worked

- **Solo:** ordering on the existing hold-out, against the linear model,
  under identical labels. Anything else is not a comparison.
- **Party:** head-to-head at equal wall-clock, plus the invariant that
  already catches most party bugs — **coordinated must never score below
  pickup**.
- **Both:** the sanity check no metric replaces. Show a human four real
  positions and ask whether the answers look like play. That is how
  every substantive bug in this project has actually been found, and a
  learned model makes it more necessary rather than less.
