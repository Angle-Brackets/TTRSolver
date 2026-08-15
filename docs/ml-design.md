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

## 2b. P0 — a policy head, and why it now leads

**This is the proposal I would build first, and it did not exist when
this doc was written.** It came out of asking whether a faster leaf buys
depth. It does not, and the reason points somewhere better.

### The measurement that redirects everything

Cost per ply on a real party position, width held fixed at
`plans=12, per_track=3, samples=6`:

| depth | time | growth | value |
| --- | --- | --- | --- |
| 1 | 0.38s | — | +91.32 |
| 2 | 17.91s | **x46.5** | +92.04 |
| 3 | 198.97s | **x11.1** | +91.96 |

Two conclusions, both awkward for the plan above:

* **A faster leaf cannot buy depth.** The MLP leaf is ~10x quicker than
  `rollout_value` and about 3x end-to-end. Against a per-ply cost of
  11-46x that is not half a ply. No value network, however good, changes
  this.
* **Depth is not obviously the prize anyway.** Depth 3 scored *below*
  depth 2 here, within noise — no gain for eleven times the cost.

Search cost is roughly `(plans x samples)^depth`. The exponent is fixed
by the game; the base is ours. **Halving the effective branching factor
is worth more than a tenfold faster leaf**, and only one thing halves
it: knowing which plans deserve attention before evaluating them.

### What the policy head is for

Not an evaluator. A predictor of *which moves are worth searching* —
foresight about the fight ahead rather than a score for the position in
front of it.

- **Input:** the §4 observation.
- **Output:** a distribution over candidate plans (factored over
  `(track, level, target)` per toon, masked by `legal_actions`).
- **Target:** what a **deep** search preferred. One search already
  produces values for every shortlisted plan, so a single expensive
  position yields a full ranking over ~60 plans, not just an argmax.
  That is a far richer label per unit of compute than a value target.
- **Use:** rank candidates in `plans()` and `candidates()`, replacing
  `_quick_score` and the `SensiblePrior` ordering.

The payoff is compounding: a shortlist that is right at 6 plans instead
of 60 makes depth 3 cost what depth 2 costs now.

### The part that makes this more than a speedup

`plans()` is where this project keeps losing the right answer. In one
session: `PER_TRACK = 2` hid the best Sound mix; `max_plans` took a
lexicographic prefix; then a global top-N over an optimistic score;
then `SCORE_BUDGET` reintroduced the prefix bug one level down. Four of
the five reductions that deleted a correct answer were **hand-written
guesses about which plans deserve attention**. That is exactly the
function a policy head learns.

So P0 attacks the speed problem and the correctness problem with one
object, which neither P1 nor P2 does.

### Two constraints it must respect

**1. The policy must not be the only gate.** A learned shortlist is
still a reduction and can still delete the right answer — quietly, and
with more confidence than a heuristic. Keep the existing stratification
as a *floor*: every track family keeps a guaranteed slot, and the policy
allocates what is left. That preserves the invariant
(`test_no_family_takes_more_than_its_share`) that caught the global
top-N bug, and it means a bad policy degrades to today's behaviour
rather than to silence.

**2. The teacher must be wider than the student.** Labels come from
search, and search only ranks what its shortlist admitted. Train on
today's shortlist and the policy learns to reproduce today's blind
spots — including the bug that deleted 2 Foghorn + 2 Aoogah. Generate
labels with a deliberately **widened** shortlist (higher `max_plans`,
higher `PER_TRACK`, more samples), offline and slowly. The student is
allowed to be narrow; the teacher is not.

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

## 5b. Results so far

### Throughput (step 1) — better than this doc assumed

| operation | rate |
| --- | --- |
| `apply_party_round` | 58,726/s |
| `party.step` (one PPO env step) | **17,572/s** |
| `greedy_plan` | 1,242/s |
| `rollout_value` (whole battle) | 1,070/s |

10M PPO steps is roughly **10 minutes single-core**, not the hours §5.3
feared. The bottleneck is the pure-Python environment, not gradients —
so a GPU idles here until the simulator is vectorised, and
multiprocessing (`search/parallel.py` already exists) is the cheaper
first move.

### S1, the MLP (step 2) — beats the linear model on calibration, ties on ordering

`tools/fit_mlp.py`, numpy only, same cache and same `score()` as
`fit_heuristic` so the comparison is like-for-like.

| model | train MAE | hold-out MAE | hold-out r | hold-out ordering |
| --- | --- | --- | --- | --- |
| linear | 20.8 | 27.1 | 0.83 | **91%** |
| MLP 64-32, decay 1e-5 | **4.4** | 32.0 | 0.77 | 77% |
| **MLP 16, decay 1e-2** | 14.4 | **19.0** | **0.89** | **91%** |

The first MLP **overfit badly** — near-perfect on train, worse than
linear on hold-out. That is exactly the risk §2 named: `solve()` is only
tractable on small positions, so anything fitted here must extrapolate
to crowded fights, and an unconstrained network fits the small ones
almost exactly and generalises worse.

A smaller, heavily regularised net fixes it and **cuts hold-out MAE by
31%** (27.1 → 19.0) with r up from 0.83 to 0.89.

**But ordering does not move — 91% either way.** Since the search only
needs to rank moves, this may not change play at all. What it does buy
is *calibration*, and calibration is worth something in two specific
places: `expectimax`'s pruning bounds, which need a leaf that stays
inside its promised envelope, and the party leaf in P1, where the value
is used as a value rather than as a ranking.

Two lessons worth keeping:

* **The first run's -23 bias with better-than-linear correlation was a
  harness bug, not a result.** The network had learned the shape and not
  the scale, because the targets span roughly -200..+100 and were not
  standardised. Reporting that as "an MLP cannot beat the linear model"
  would have been a conclusion about the training loop.
* **Capacity was never the constraint; regularisation was.** The bigger
  network was strictly worse. Any further work here should push on the
  *data* — labels for larger positions — rather than on model size, and
  `solve()` timing out on 794 of 1200 large hold-out attempts is exactly
  why that is hard.

### P0 and P1 trained (steps 3-4) — the policy works, and by a lot

2,500 positions searched wide (120 plans, per-track 5, 16 samples),
**299,976 ranked plans**, 2,125 train / 375 hold-out. One trunk, two
heads, GPU.

**Policy (P0).** The metric is `regret@6`: the teacher's best plan value
minus the best value among the six plans the ranker would have kept.
Zero means nothing was lost by searching only those six.

| ranking | regret@6 | lossless |
| --- | --- | --- |
| **learned policy** | **3.4** | **36%** |
| `_quick_score` (shipped) | 9.93 | 28.3% |
| uniform random | 12.09 | — |

**Roughly 3x better than the ranking the search actually ships.**

And a finding about the incumbent that is arguably more useful: at this
task `_quick_score` scores **9.93 against random's 12.09**. The
hand-written shortlist ranking is barely better than picking six plans
at random. That is not a small inefficiency — it is the mechanism behind
four of this project's five silent-deletion bugs, and it explains why
they were so easy to introduce. There was never much signal there to
lose.

**Value (P1).** Hold-out MAE ~8.4 on values around +90. Worth reading
against the label noise rather than against zero: the teacher used 16
samples on a per-round spread of ~31, so its own standard error is
about 7.8. **The value head is at the noise floor of its labels** —
more capacity or more epochs cannot help; only more samples per label
could.

**Top-1 accuracy is 6-8% and that is fine.** It asks "did the policy
pick the teacher's argmax", which is the wrong question twice: the
policy chooses a shortlist rather than a move, and the teacher's argmax
is itself a sampled estimate with its top plans within noise of each
other. Regret is the metric that matches the use.

**Caveat:** training is not converging cleanly — hold-out MAE bounces
8.35 to 11.59 across checkpoints and the best regret is at epoch 20, not
40. It wants a learning-rate schedule and early stopping before anything
is exported. The numbers above are a floor, not a tuned result.

### The policy loses in place, and the offline metric could not see it

Wired in properly -- the policy score reaching the final `max_plans` cut,
not just bucket membership -- and A/B'd over four seeds at four widths on
a real battered-party position:

| shortlist width | policy OFF | policy ON |
| --- | --- | --- |
| 8 | +88.06 | +87.29 |
| 16 | **+89.34** | +87.29 |
| 30 | **+89.34** | +87.29 |
| 60 | **+89.72** | +88.29 |

It loses everywhere, and the identical +87.29 at three widths says it is
steering to one particular mediocre plan regardless of how much room it
has.

**The cause is the labels, not the network.** The teacher estimated each
plan from 16 samples of a per-round spread of ~31, so its standard error
per plan is about **7.8** — while the median value gap between the best
plan and the sixth is **3.54**. The labels are noisier than the
distinctions they are meant to teach. Among good plans the teacher's
ordering is largely noise, and the policy reproduced it faithfully.

**And that is why regret@6 flattered it.** The metric scored the policy
against those same noisy values. When the top twenty plans sit within
noise of one another, almost any six score a low regret — so regret@6
measured *"avoids obviously bad plans"*, which the policy really does do
better than `_quick_score` (whose rank-1-to-median gap of 22 says it
sometimes picks genuinely bad ones), and was blind to *"picks the best
plan"*, which is the only thing the search needs from it.

**An offline metric computed against noisy labels cannot validate a
component whose job is to discriminate within that noise.** The
end-to-end A/B is the only test that counts, and it should have been run
before the regret number was reported as a win.

### Re-labelled at 128 samples: better, still losing

Regenerated 1,500 positions at `samples=128`, dropping the teacher's
standard error from 7.8 to **2.74** — now below the 3.12 median gap it
has to resolve, which was the whole hypothesis. Offline regret improved
to **2.86** against `_quick_score`'s 8.52.

| width | policy OFF | ON, 16-sample labels | ON, 128-sample labels |
| --- | --- | --- | --- |
| 8 | **+88.06** | +87.29 | +86.79 |
| 16 | **+89.34** | +87.29 | +86.79 |
| 30 | **+89.34** | +87.29 | +87.79 |
| 60 | **+89.72** | +88.29 | +89.23 |

**The noise diagnosis was partly right and not sufficient.** At width 60
the deficit closed from 1.43 to 0.49, so cleaner labels genuinely
helped — and the policy still loses at every width.

What the run now says about itself: the best epoch is **10 of 60**,
against 55 of 60 before. With 1,275 training positions instead of 2,125,
it overfits almost immediately. So the label quality went up and the
label *quantity* went down, and the second undid much of the first —
1,500 positions at 128 samples cost the same 38 minutes as 2,500 at 16.

### "A tiny degradation is fine if it is faster" — it is not faster

The right way to read the table is quality per second rather than
quality per width, since a better ranker should let you search NARROWER
for the same answer. Pairing each setting with what it cost:

| budget | policy OFF | policy ON |
| --- | --- | --- |
| ~1s | **+88.06** (w8, 0.9s) | +86.79 (w8, 1.2s) |
| ~1.5s | **+89.34** (w16, 1.3s) | +86.79 (w16, 1.6s) |
| ~2.5s | **+89.34** (w30, 2.2s) | +87.79 (w30, 2.6s) |
| ~4s | **+89.72** (w60, 3.9s) | +89.23 (w60, 4.3s) |

The policy is **Pareto-dominated**: at every budget it is both slower
and worse. The pair that settles it is `ON` at width 60 — **+89.23 in
4.3s** — against `OFF` at width 30 — **+89.34 in 2.2s**. Better answer,
half the time, policy off.

So the 0.49 deficit at width 60 is not a small price for a speedup;
there is no speedup. Inference adds 0.3-0.4s to the shortlist build, and
narrowing the width hurts the policy faster than it hurts the
arithmetic, which is the opposite of the property P0 was proposed on.

The next honest experiment is more positions at high sample count, which
is hours rather than minutes, and it should be run only if someone wants
the answer badly enough. `USE_POLICY` stays off. The value head (P1) is
unaffected by any of this and is wired in and working.

### The measurement that ends the ML line of attack

P1 wired in, benchmarked on an idle machine:

| | rate |
| --- | --- |
| `rollout_value` | 1,030/s |
| learned value head | **66,474/s** |

**65x faster leaf. 1% faster search** — 27.1s against 27.4s at depth 2.
Quality identical (+92.29 against +92.17).

Profiling that search says why, and it invalidates the premise both P0
and P1 rested on:

| | share of a depth-2 search |
| --- | --- |
| **`plans()`** | **65.5s of 68.6s — 95%** |
| ... `_cheap_score` | 25.0s over 4,063,199 calls |
| ... `_quick_score` | 23.1s over 183,587 calls |
| ... `_playable` | 9.6s over 1,473,480 calls |
| the leaf | does not appear |

**The search spends 95% of its time deciding what to consider and 5%
considering it.** A faster leaf cannot help because the leaf is free
already, and a learned ranker makes things worse because it adds cost to
the one stage that is expensive.

The headroom for better ranking is small too. With the arithmetic,
quality by width runs +88.06 (w8), +89.34 (w16), +89.34 (w30), +89.72
(w60) — **from width 16 upward there is 0.38 of a point on the table**.
A perfect ranker could win about 1.7 points, and only by shrinking to
width 1, which saves about 3 seconds. P0 was proposed to search 6 plans
as well as 60; the arithmetic already searches 16 as well as 30.

**So the bottleneck is combinatorial, not statistical.** `plans()` is
called ~100 times in one depth-2 search and re-enumerates thousands of
combos each time. The leverage is memoising it across nodes, or pruning
the enumeration before `_playable` and `_cheap_score` see it — ordinary
optimisation, no learning involved.

Both heads stay in the tree, both measured, both off or opt-in. They are
not wrong; they are aimed at a cost that turned out not to exist.

### P2, PPO: the one that worked

3M steps, ~2,900 env steps/s, GPU. Evaluated on 200 held-out positions
against the search on **the same positions in the same reward units**:

| | return | win | wall clock |
| --- | --- | --- | --- |
| **PPO policy** | **+60.31** | 93.0% | **0.41s** |
| search, samples=8 plans=12 | +57.98 | 92.0% | 24.09s |
| search, samples=32 plans=30 | +61.87 | 94.0% | 101.51s |
| uniform random | +23.10 | 80.0% | — |

**It beats the cheaper search outright at 59x less time, and comes
within 1.6 points of a search costing 248x more.** That is the claim P2
was proposed on, and unlike P0 it survives the end-to-end test rather
than only the offline one.

Why this worked where distillation did not:

* **No teacher ceiling.** P0 could only approach a teacher that is
  itself approximate. PPO learns from outcomes.
* **It never calls `plans()`**, the stage holding 95% of search runtime.
  It samples an action instead of enumerating thousands of joint plans.
* **It can pass.** 4.1% of its moves are passes — the action the search
  cannot currently offer, since widening it broke exact `solve()`. A
  policy has no transposition table to corrupt.

Learning curve: +56.5 at 100k steps, +63.7 peak at 1.74M, +60.3 at 3M.
Most of the gain arrives inside the first 500k; the rest is noise around
a plateau.

**What it is not.** Pickup mode only, so teammates are `SensiblePrior`
-- it has learned to play alongside a *model* of strangers. Trained and
tested on the same position sampler (different seeds), so it is
in-distribution. And it has learned this simulator, bugs included: a
search exposes a bad rule because a human reads the output and says
nobody plays that, and a policy hides one. The search stays as the
cross-check.

### The curriculum hypothesis, tested

The policy trained on the original sampler under-used Lure -- caught on
a real position where it threw for a kill while the search re-lured, and
the search was right. The proposed cause was the position distribution:
with several toons and mixed cogs you can usually out-damage the board,
so "kill the biggest thing" wins and Lure never has to be learned.

Retrained with 35% hard solo positions (one toon against three or four
cogs of 132-196 hp) and 30% mid-fight boards. On 150 held-out
hard/strange positions:

| | return | win | time | **Lure share** |
| --- | --- | --- | --- | --- |
| PPO policy | -52.27 | 43.3% | **0.31s** | **19.5%** |
| search s=16 p=20 | **-48.26** | **44.7%** | 21.98s | 9.4% |

**Lure usage more than doubled**, 9.4% to 19.5%, and now exceeds the
search's. The hypothesis was right: it was the curriculum, not credit
assignment.

**And the quality ranking flipped.** On the easy sampler the policy beat
the cheap search (+60.31 against +57.98); on the hard one the search is
ahead by 4 points. Two things worth separating there. The policy is
still 71x faster. And both scores are deeply negative, because these
positions are mostly losing -- a random baseline on the training
distribution scored -21.19, and this set is harder still. Comparing
-52 with the earlier +60 means nothing; different distributions, not
different skill.

### A shortlist bug that was not there

The obvious suspicion, given this project's history, was that the search
under-lures because `_quick_score` credits a Lure +25 per cog against
damage plans scoring 100+, so Lure plans lose the shortlist cut before
anything evaluates them. A first measurement seemed to confirm it: Lure
reached the shortlist 35.9% of the time, and scored better than every
alternative 61.8% of the time when forced.

**Both numbers were wrong, in different ways.**

The 35.9% counted positions where a Lure appeared in the shortlist over
*all* positions, without checking whether the toon held a Lure gag at
all. Restricted to positions where a Lure candidate exists, it is
**100%** -- at every credit value, including 25. The shortlist never
drops Lure.

The 61.8% compared **one round's reward only**. Lure looks excellent for
exactly one round, because you take no damage; the search's `evaluate`
includes the continuation, where the delayed kill is paid for. Measured
properly with the full evaluation, forcing Lure beats the search's free
choice **15.6%** of the time, with a median gap of **-0.68**.

So the search's ~9% Lure rate is consistent with its own evaluation. It
is not being denied the option; it is declining it. The lesson is the
one this document keeps recording, turned on its head: a metric that
confirms a suspicion deserves the same scrutiny as one that refutes it,
and both of these were measuring something other than the question.

### Which is right about Lure remains open

 The policy lures twice as often as the search, and the search's own
evaluation says that is not warranted. But that evaluation is depth-1
with a guessed continuation, so "the search says Lure is not worth it"
is not the same as "Lure is not worth it" -- and on the one position
examined by hand, the search's preference for re-luring was correct
while its aggregate rate is low.

Settling it needs ground truth, which for small SOLO positions exact
`solve()` can supply. That is a concrete experiment rather than more
tuning, and it is the next thing worth doing here.

## 6. What I would actually do

~~1. Measure throughput.~~ **Done** — see §5b. 17.5k steps/s.

~~2. S1 — MLP on cached labels.~~ **Done** — see §5b. Beats the linear
model on calibration (hold-out MAE 27.1 → 19.0), ties on ordering.

**Revised ordering, after the per-ply measurement:**

1. **P0 — the policy head.** Now first. It is the only proposal that
   attacks the branching factor, which is the term the cost is
   exponential in, and it targets the exact machinery that has produced
   four of this project's five silent-deletion bugs.
2. **P1** — learned value leaf. Still worth it, but reclassified: it is
   a **speed and calibration** win (≈3x end-to-end, hold-out MAE down
   31%), **not** a depth win. Pairs naturally with P0, since AlphaZero's
   two heads are exactly these two.
3. **P2** — PPO for pickup, only if latency matters, i.e. only if this
   goes live.
4. **P3** — not yet.

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
