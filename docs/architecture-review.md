# TTRSolver: two agents for Toontown Rewritten battles

Seeking an outside view on why a learned policy plateaus ~1-2 points below
a classical search, and which direction is worth pursuing next.

Everything below is measured. All performance figures are on **180 held-out
buildings** (fixed seeds, never used for tuning) unless stated otherwise.

## The problem

Toontown Rewritten party combat. Up to 4 toons vs up to 4 cogs (enemies).
Each round every toon picks one "gag" — a track from {Toon-Up, Trap, Lure,
Sound, Throw, Squirt, Drop} x a level 1-7 x a target. All gags resolve in a
fixed track order, then the surviving cogs attack.

The benchmark task is a **cog building**: 2-5 consecutive battles ("floors")
sharing one gag pouch and one laff (HP) pool, with no restocking and no
healing between floors. Dead cogs are replaced mid-floor from a holdout.
Metric: **percentage of buildings fully cleared**.

Action space as encoded: 246 (1 pass + 7 tracks x 7 levels x 5 targets).

Relevant mechanics: accuracy is rolled once per (track, target) so gags of
the same track at the same cog all land or all miss together; a lured cog
skips its attacks for 2-8 rounds depending on lure level; springing a trap
wakes the cog immediately; a toon cannot heal itself.

## Agent A - classical search

```
state
 |- plans()                      choose which joint plans to consider
 |    |- candidates(seat)        legal moves -> 4 per track, ordered by a
 |    |                          hand-written prior
 |    |- combos across seats     product, or multiset when toons are
 |    |                          interchangeable
 |    |- _playable() filter      can these toons actually throw this?
 |    +- stratify by track-signature, rank within stratum by _quick_score,
 |       cut to 60 plans
 +- for each plan: sample 6 outcome draws (accuracy rolls + cog attacks)
      +- at depth 0 -> rollout_value:
           play 12 rounds forward using greedy_plan, accumulating the real
           reward function
             +- greedy_plan: per seat, _cheap_score -> top 2 (+3 track
                probes) -> _greedy_score simulates one round -> pick best
```

**~124 ms/decision (~1 position/second). 67.8% of buildings cleared.**

Three hand-written scorers, used at different stages:

- `_cheap_score(state, seat, action)` — ranks a single action by arithmetic,
  no simulation.
- `_quick_score(state, plan)` — ranks a joint plan by simulating **one
  all-hit round**:
  `landed + 2*restored + armed_credit + 120*killed + 2*prevented - price`
- `_greedy_score(state, trial, obj)` — picks one seat's action inside a
  rollout.

## Agent B - PPO + local search ("PPO with Advice")

```
state
 |- encode() -> 290 floats
 |    per cog (x4):  alive, level, hp ratio, max hp, lured, trapped,
 |                   lure rounds left, dead, armed-trap damage
 |    per toon (x4): alive, laff ratio, max laff, 49 gag counts
 |    globals:       round, cogs alive, toons alive, cogs remaining in the
 |                   building, street-vs-facility, holdout size, whose turn,
 |                   what teammates already committed to this round
 |- MLP: 290 -> 256 -> 256 (tanh) -> 246 logits
 |       illegal actions masked to -inf inside the distribution
 |- propose(): each seat takes argmax in turn; a "pending" block lets later
 |             seats see earlier picks (this is the whole of coordination)
 +- climb(): start from that plan, then sweep seats — for each seat try the
             policy's top 3 alternatives, keep any that _quick_score
             prefers — until a full sweep changes nothing or a budget of 8
             scorer calls is spent
```

**~0.6 ms/decision (~656 positions/second). 66.7% of buildings cleared.**
Plain PPO with no climb: **61.7%**, 0.28 ms/decision.

PPO training: 6M steps, coordinated (one shared policy chooses for every
toon), GAE gamma=0.99 lambda=0.95, entropy 0.04, separate actor and critic
trunks, running reward normalisation, 50% of episodes multi-floor buildings.
Training saturates: 800k -> 6M steps is +8.3 points, 6M -> 16M is +1.1.

## Current standing

| agent | buildings cleared | ms/decision |
|---|---|---|
| classical search | **67.8%** | 124 |
| PPO + climb | 66.7% | 0.6 |
| plain PPO | 61.7% | 0.28 |

The local search recovers roughly two-thirds of the policy-to-search gap for
double the policy's cost, and lands ~1.1 points short at ~200x less time.

## What has been tried and failed

All on held-out data. Nearly all are negative results, which is why an
outside view might help.

### On the policy

1. **Expert iteration** — behaviour-clone the search's play, 12,445
   decisions. Collapsed to **7.5%** of buildings. It also failed to copy the
   behaviour that makes the teacher good: heals 1.3% against the teacher's
   5.3%.
2. **Entropy coefficient**, swept 0.01 / 0.04 / 0.10 — gag entropy came back
   **3.79 at every setting**. The bonus is over 246 *actions*, and the policy
   satisfies it by spreading across *targets* while still choosing the same
   track. Action entropy is not track entropy.
3. **Potential-based reward shaping** on incoming damage (Ng-style, so the
   optimal policy is provably unchanged) — moved behaviour substantially
   (Throw 44.7% -> 35.7%, toward the search's 32.0%) and moved buildings
   finished **not at all** (52.2% either way).
4. **Wider observation** — added per-cog expected damage (threat), per-toon
   training level, and organic flags (290 -> 350 floats), on the theory that
   the policy could not distinguish a Throw-7 toon from a Throw-2 toon
   holding identical gags. It changed behaviour in the predicted direction
   (holds 2.0% -> 5.6%) and did not help: three training seeds gave climb
   64.4% / 66.1% / 63.3% against the 290-wide run's 66.7%. Reverted.

### On the evaluator

5. **Fitting the scorer weights** — (1+lambda) evolution strategy, 120
   generations, against buildings-finished with a disjoint validation set.
   Fit set 70.0% -> 75.0%; validation 60.0% -> 60.8%; a **third** untouched
   set identical to baseline.
6. **New scorer features** — "threat of the cogs killed" and "toons one
   round from going sad", both starting at zero weight so the optimiser
   could adopt them freely. It drove them to 0.044 and 0.592 (i.e. off), and
   a third seed set was again identical.
7. **Weights do not matter; terms do.** Four random weight vectors drawn
   from a hat scored 63.3%, 63.3%, 65.0%, 63.3%. Hand-tuned scored 62.5%.
   **All terms zeroed (pure damage) scored 57.5%.** So the scorer's *form*
   is worth ~5 points and its *coefficients* are worth nothing across a wide
   range.

### On giving the local search a horizon — three attempts, all negative

8. **Track probes** — offer each seat the best action of every track, so
   Trap becomes reachable (the policy proposes it with ~0 probability). It
   did become reachable, and `_quick_score` then *declined* it: Trap use
   1.0% -> 1.2%, finish rate **-2.8**.
9. **Two-ply lookahead** with `greedy_plan` playing the second round:
   **-2.8**.
10. **PPO rollout judge** — play the candidate plan, then let PPO play on for
    2-4 more rounds, score with the real reward function, common random
    numbers across candidates so the comparison is paired: **-3.3 to -3.8**,
    monotone in depth.

## The pattern we think we see

**A judge must be independent of the proposer.** Three separate
confirmations: PPO's own critic ranking PPO's samples (no gain over plain
argmax), a greedy two-ply (-2.8), a PPO rollout (-3.3 to -3.8). The only
evaluator that has ever helped is `_quick_score`, which shares none of the
policy's blind spots (58.9% -> 64.4%). It is also why the search works at
all — its rollouts use `greedy_plan`, a different policy from the plans
being graded.

**Hypothesis for why depth helps the search and hurts the climb.** The
search's candidate plans are *structurally different* from one another (a
trap+lure line sitting next to a Sound line), so their true values differ by
more than rollout noise. The climb's candidates are *one-seat perturbations*
of a single proposal, so their true values differ very little and a sampled
multi-round evaluation mostly measures dice. A deterministic one-round
scorer at least ranks small differences consistently.

If that is right, depth and diversity have to arrive **together** — which is
the one combination not yet tried (probes + rollout).

## The residual behavioural difference

Over 80 held-out buildings, usage measured when the gag is in hand:

| | climb | search |
|---|---|---|
| **declines to act (hold)** | **2.1%** | **11.0%** |
| throw | 44.4% | 35.1% |
| squirt | 20.3% | 23.4% |
| sound | 11.4% | 14.1% |
| drop | 10.0% | 8.2% |
| lure | 7.8% | 9.5% |
| toon-up | 4.8% | 6.7% |
| trap | 1.3% | 2.9% |

The climb throws ~13% more gags over the same buildings and prefers level 4
where the search prefers 5-6. Every difference points the same way: **it
always swings.** `_quick_score` pays for damage landed, so any action that
deals none scores about zero regardless of what it saves. A concrete case:
on one building the search healed three times in seven rounds and held the
party at 48-55 laff, while the climb healed twice — the second time at
[2, 17, 2] laff — and lost, with two toons still carrying Toon-Up 7.

## Questions we would value an outside view on

1. Is the "candidates too similar for a noisy evaluator" hypothesis right?
   If so, is probes+rollout together the correct test, or is there a better
   way to get candidate diversity that the evaluator will actually accept?
2. Behaviour cloning from the *search* failed catastrophically (7.5%). Would
   cloning from the **climb** work better, given that climb's plans are
   one-seat perturbations of PPO's own output and therefore inside its own
   distribution? (This is the AlphaZero loop with a cheap improvement
   operator in place of MCTS.)
3. Is a 256x2 MLP simply too small for a 290-input, 246-action problem, and
   is the 6M-step saturation a capacity limit rather than a data one?
4. Is there a principled way to make an evaluator value *not acting*? Every
   attempt to reward holding has failed, yet the search holds 5x more often
   and wins.
