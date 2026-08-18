# TTRSolver: two agents for Toontown Rewritten battles

A 0.6 ms learned policy and a 124 ms classical search, measured against each
other over 540 held-out cog buildings -- and what happened when the gap
between them turned out not to exist. Still seeking an outside view, but on a
different question than this document originally asked.

## What changed since the last version of this document

Three suggestions were acted on. **One worked, and the two failures were
more informative than the success.**

| | result |
|---|---|
| Entropy on the *track marginal* | **+1.1 mean**, positive on all three sets — shipped |
| Capacity 256 -> 512 wide | -0.2, mixed signs — refuted |
| DAgger with the climb as teacher | -2.0 plain / -0.9 with climb — refuted |

Two things were learned that change how everything else here should be read.

**A noise floor was established, and it is about a point.** Three runs of the
same configuration differing only in the training seed score 65.0 / 66.1 /
65.9. Worse, they *reorder between sets*: the run that tops the three
reported sets comes last on a fourth. Most single-number results in the
earlier version of this document were within this.

**The behavioural gap this document was written to explain has largely
closed, and the outcome gap did not close with it.** Track-entropy moved the
policy's profile onto the search's on every axis re-measured — holds 2.0% ->
11.9% against 11.0%, throw 44.4% -> 33.8% against 35.1%, gag entropy 3.96 ->
4.39 against 4.37 — and bought +1.1. Two earlier changes each moved one row
into agreement and bought nothing. **Matching the search's behaviour is not
sufficient for matching its result, and may not be necessary.** That is the
central puzzle now, and it is a different puzzle from the one below.

**And the gap is gone.** The 67.8% the whole programme aims at was measured
on ONE set. Re-measured on three, paired, same buildings:

| set | search | PPO + climb | |
|---|---|---|---|
| 31000 | 65.6% | 69.4% | policy +3.8 |
| 33000 | 65.0% | 63.3% | search +1.7 |
| 36000 | 64.4% | 65.0% | policy +0.6 |
| **mean** | **65.0%** | **65.9%** | **+0.9** |

Mixed signs and a mean inside the noise floor: **the agents are tied**, and
the policy is 200x faster. Everything below this line was written to explain
a 2.8-point deficit that does not survive being measured on more than one
set.

**The 67.8% was never a regression, and this is measured rather than argued.**
Running the search on the same 180 buildings with the same battle dice, and
changing *only* the search's own sampling RNG:

| run | set 31000 |
|---|---|
| shipped seed | 65.6% |
| `armed_credit` disabled, same seed | 65.6% |
| sampling seed +500000 | 68.3% |
| sampling seed +900000 | 66.1% |

Spread 2.7, sd 1.44, against the 2.2-point difference three separate
hypotheses were invented to explain. The search draws 8 outcome samples per
plan, so it is deterministic given its seed -- the `armed_credit` row is the
control, identical to the decimal -- and the entire difference lives in the
seed. 67.8% and 65.6% are one measurement taken twice.

For the record, because the reasoning was wrong three times in a row: the
drop was attributed first to repo-wide mechanics fixes (no rules file has
been touched since the number was recorded -- `simulator`, `mechanics`,
`party`, `state`, `outcomes` unchanged across 21 commits), then to the search
relying on optimistic rollout bugs (that evidence comes from a *rejected*
experiment that is not in the code), then to `armed_credit` (65.6% with it
disabled). None of them survived. **No committed harness ever produced the
67.8%**, which is the root cause of all three: an unreproducible number
invites explanation instead of re-measurement.

**This makes the search's 65.0% an underestimate.** Each set above was
measured with one sampling thread, and on set 31000 that thread returned 65.6
against a three-thread mean of 66.7. With sd 1.44 per measurement the
three-set mean carries about 0.8 of standard error from the search's own dice
before the building draw is counted. The honest summary is that the two
agents cannot be separated at this sample size, and the ordering in the table
below should not be read as one.

**One asymmetry, now withdrawn.** The search scored 65.6 / 65.0 / 64.4 across
the three sets against the policy's 69.4 / 63.3 / 65.0, and a spread of 1.2
against 6.1 looked like a uniformly competent search against a spiky policy --
which is what the timing hypothesis predicts. But each of those search
numbers is a single draw from a distribution with sd 1.44, so a spread of 1.2
across three of them is luck, not uniformity. We do not know the search's
set-to-set spread, because every set was measured once.

Everything below is measured. Figures are on **three disjoint sets of 180
held-out buildings** (fixed seeds 31000 / 33000 / 36000, never used for
tuning), reported as the mean with the per-set numbers where the spread
matters. Earlier entries marked *(one set)* predate the move to three and
are on the 31000 set alone.

**The noise floor is about a point.** Three runs of the *same* configuration
differing only in the training seed score 65.0% / 66.1% / 65.9%. Nothing
below a point is distinguishable from the seed lottery, which is why results
here are only believed when every set agrees in sign.

The seeds also **reorder between sets**: the run that is best on the three
reported sets (66.1%) is the *worst* of the three on a fourth, disjoint set
(58.9% against 59.4% and 61.1%). Choosing a training seed on the sets you
report is therefore its own fitting, and the shipped policy is picked on
that fourth set instead.

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
| PPO + climb | **65.9%** (69.4 / 63.3 / 65.0) | 0.6 |
| classical search | 65.0% (65.6 / 65.0 / 64.4) * | 124 |
| plain PPO | 57.6% (57.2 / 53.9 / 61.7) | 0.28 |

\* One sampling thread per set, and the search's own dice are worth sd 1.44
per measurement -- on set 31000 three threads gave 65.6 / 68.3 / 66.1, mean
66.7. Read the search's row as "about 65-67".

The top two are tied and the ordering is noise. The 7-point gap between the
climb and plain PPO is not: the local search is the one component whose value
is comfortably larger than the measurement error.

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

5. **Entropy on the *track marginal*** — the one intervention on the policy
   that worked. Sum the action probabilities into 7 track probabilities and
   put the bonus on *that* distribution, which is what item 2 showed plain
   action entropy was not doing. Positive on all three sets (+1.7 / +1.1 /
   +0.6). Shipped.
6. **Capacity: 256 -> 512 wide** — -0.2 mean with mixed signs (-2.2 / +0.0 /
   +1.7), against 20.8 MB of weights for 7.5. Not the bottleneck.
7. **DAgger with the climb as teacher** — the loop this document asked
   about in question 2. Roll out with the *learner*, label every visited
   state with `climb`, aggregate, fine-tune, repeat: 6 iterations, 15,393
   states. **-2.0 plain and -0.9 with climb**, mixed signs on both.

   The diagnostic beat the number. **Agreement with the teacher never
   rises** — 44.3 / 37.6 / 43.1 / 44.1 / 42.7 / 45.8 across the six
   iterations — while the loss falls monotonically 1.56 -> 1.26. The
   student fits the labels and closes no distance on the teacher, because
   the target moves with it: MCTS is a fixed operator a policy can converge
   onto, whereas `climb` is *defined as a perturbation of the student's own
   proposal*. There is no fixed point to walk toward.

   Two harness bugs nearly buried that, and both are worth stating because
   they are easy to repeat. The teacher was queried once per round and seat
   *k* read off the resulting joint plan — so seat *k*'s label assumed
   seats 0..*k*-1 played the **teacher's** moves while the trajectory had
   played the **student's**. In a coordinated plan the seats are chosen
   against each other, so those labels described positions that never
   occurred: worth 10.4 of an apparent 12.4-point collapse. Separately, the
   cross-entropy ran over all 246 actions including illegal ones, whose
   logits inference never reads — the loss sat at 5.46 against ln(246) =
   5.51, near-uniform, while the student already agreed with the teacher on
   more than half its decisions.

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

Over 80 held-out buildings, usage measured when the gag is in hand. The
middle column is the SHIPPED policy (track-entropy); the first is what it
replaced, kept because most of this document's failures were measured
against it:

| | pre-track-entropy | shipped | search |
|---|---|---|---|
| gag entropy | 3.96 | **4.39** | 4.37 |
| **declines to act (hold)** | **2.1%** | **11.9%** | **11.0%** |
| throw | 44.4% | 33.8% | 35.1% |
| toon-up | 4.8% | 7.2% | 6.7% |
| squirt | 20.3% | not re-measured | 23.4% |
| sound | 11.4% | not re-measured | 14.1% |
| drop | 10.0% | not re-measured | 8.2% |
| lure | 7.8% | not re-measured | 9.5% |
| trap | 1.3% | not re-measured | 2.9% |

**On the four axes that were re-measured the profiles now agree**, holds
included. So the behavioural gap this section was written to describe is
largely closed, while the outcome gap it was written to explain moved only
+1.1. Two earlier attempts moved a single row toward the search (shaping:
throw 44.7 -> 35.7; wider observation: holds 2.0 -> 5.6) and changed
outcomes not at all. Matching this table is evidently not sufficient for
matching the result, and may not be necessary either.

The description that follows is of the PRE-track-entropy policy. The climb
threw ~13% more gags over the same buildings and preferred level 4 where the
search prefers 5-6. Every difference pointed the same way: **it always
swung.** `_quick_score` pays for damage landed, so any action that
deals none scores about zero regardless of what it saves. A concrete case:
on one building the search healed three times in seven rounds and held the
party at 48-55 laff, while the climb healed twice — the second time at
[2, 17, 2] laff — and lost, with two toons still carrying Toon-Up 7.

## What actually decides a building

Measured over 50 held-out buildings, each played by both agents
(`tools/trace_building.py --stats 50`):

| agent | cleared | toons lost | heal rounds | rounds |
|---|---|---|---|---|
| climb | 62.0% | 1.02 | 1.4 | 10.4 |
| search | 64.0% | 0.88 | 0.9 | 10.1 |

| | no toon lost | lost >=1 |
|---|---|---|
| climb | n=29, **100% cleared** | n=21, 9.5% |
| search | n=31, **100% cleared** | n=19, 5.3% |

**The outcome is the first toon loss and almost nothing else.** The clear
rate is very nearly the fraction of buildings where nobody goes sad -- 29/50
against 62% cleared, 31/50 against 64%.

Part of that is definitional: a building is lost when *every* toon is sad, so
losing implies losing toons. Two parts are not.

**No run was ever lost to gag exhaustion.** All 60 intact-party runs cleared.
The `can_still_damage` termination -- the pouch running dry, 80 Lures and no
attacks -- never fires at these pouch sizes. So the `price`, `scarcity_cost`,
`rare_gag_premium` and `horizon_cost` machinery in both scorers is defending
against a failure mode that does not occur, and `price` is the single largest
negative term in `_quick_score`. Every hour spent tuning conservation was
spent on the wrong axis.

**And healing more does not help.** The climb heals on 1.4 rounds a building
against the search's 0.9, and loses MORE toons, 1.02 against 0.88. More
healing, worse survival. The reading -- corroborated by the project owner's
own observation of play, independently of these numbers -- is that the search
is not out-healing the damage, it is **preventing** it: killing or luring the
threat a round earlier so there is less to heal. The climb heals reactively
once the damage has landed.

That is the first mechanism in this project connecting a behaviour to the
variable that decides buildings, and it suggests the objective everything has
been measured against -- buildings cleared -- has been hiding its own
structure. **Damage prevented before it lands** is the quantity to optimise,
and neither scorer prices it: `prevented` exists in `_quick_score` at weight
2.0 against a `landed` term with weight 1.0 per point of damage, which for a
cog threatening 8-15 a round is not close to parity with killing it.

## What the CRN experiment settled

Hypotheses 1 and 2 below were written before this ran. Both are now
answered, and the answers are more interesting than the hypotheses.

The design: replay held-out buildings, find every round where the two agents
choose a different joint plan, and fork. One branch plays the policy's
action, the other the search's; both then play the rest of the building out
under **one fixed continuation policy on identical dice**, so the only thing
that differs is the action. 500 forks over 47 buildings, bootstrapped by
BUILDING, because ten forks from one building are not ten independent
observations.

| bucket | greedy continuation | policy continuation |
|---|---|---|
| overall | **+2.29** [+0.32, +4.30] | +0.75 [-0.80, +2.43] |
| target | **+5.94** [+2.02, +9.40] | +0.90 [-1.64, +3.29] |
| track | **+2.65** [+0.05, +5.41] | +0.86 [-1.26, +3.27] |
| hold | -0.18 [-2.52, +2.39] | -0.01 [-1.36, +1.37] |
| sign test | 78-47 to search, p=0.007 | 59-51, p=0.50 |

**The agents disagree almost always and it almost never matters.** They pick
the same joint plan on 5.3% of rounds, and three quarters of their
disagreements are worth under a point. Two agents playing what is very nearly
a different game, finishing the same fraction of buildings.

**Holding is worth nothing.** 233 samples, a tight interval around zero,
under *both* continuations, so this one is not confounded. Reward shaping,
hold-variants, the wider observation, four attempts to teach `_quick_score`
patience and hypothesis 2 below were all aimed at reproducing the search's
11% hold rate. It does not pay.

**And the search's apparent edge was an artifact of who plays on.** Under
`greedy_plan` the search leads by +2.29, with target selection at +5.94,
surviving both a cluster bootstrap and a sign test at p=0.007. Swap the
continuation for the climb and every interval covers zero. The reason:
`greedy_plan` **is the search's own rollout policy**, so its moves were
chosen assuming that follow-up and then graded under it, while the policy's
moves were chosen assuming the policy continues. That is a fourth instance of
the judge sharing the proposer's assumptions, and the one that came closest
to being written up as a result -- it passed the statistics, because
statistics test whether an effect is real, not whether the design measures
what it claims.

Neither continuation is neutral, so the reading is not "no difference" but
something sharper: **the better move depends on who is playing after it.**
Which is why every attempt to move the policy's behaviour toward the search
moved the behaviour and not the result. The search's moves are good *for the
search's continuation*, not good in themselves, and transplanting them
transplants nothing.

`tools/disagree.py` is the experiment; `tools/trace_building.py` prints two
whole games side by side.

## Our current read, offered so you can attack it

Four hypotheses, in descending order of how much we believed them **when they
were written**. The section above has since answered 1 and gutted 2; they are
kept because the reasoning is what an outside reader is being asked to check.

### 1. We have been matching marginals when the thing that matters is conditionals

**Answered, and both halves were right for the wrong reason.** Conditional
agreement really is near zero -- 5.3% -- while the marginals agree. But the
disagreement is nearly free, so there was no blind spot hiding behind the
marginals. The premise held and the conclusion did not.

This is the one we would most like a second opinion on, because it
reinterprets nearly every result above.

Every behavioural measurement in this document is a **marginal frequency** --
how often each track gets used across a corpus. Track-entropy made those
marginals agree with the search's and bought +1.1. But a policy can hold
11.9% of the time, exactly matching the search's 11.0%, while holding in
*entirely different positions*. Marginal agreement constrains the repertoire
and says nothing about the timing, and it is the timing that wins battles:
the whole value of a hold is that it is the right round to do nothing.

If that is what is happening, the behavioural programme is exhausted -- we
have given the policy the search's vocabulary and it is still saying
different things with it -- and no further work on usage tables will help.

**It is cheaply testable and we have not done it.** Replay held-out
buildings, and on each decision record what the search would do and what the
policy does. Then measure *conditional* agreement: on the states where the
search holds, how often does the policy hold? Compare against the policy's
base rate of holding. If conditional agreement is at base rate, the marginals
are agreeing by accident and the gap is timing. This also yields a corpus of
maximum-disagreement states, which is the natural place to look next.

### 2. The evaluator we keep trying to fix may not be the organ responsible

**Gutted: the behaviour it is about is worth nothing.** The CRN result puts
holding at -0.18 and -0.01 under the two continuations, on 233 samples with
tight intervals. Everything below is an argument about *where in the
architecture* patience lives, and it was worth having only while patience was
assumed to be worth having. It is kept as a record of how long a plausible
premise can go unmeasured -- five separate interventions were aimed at this.

Four attempts above try to make `_quick_score` value not-acting, all failed.
But **the search's holds do not come from `_quick_score`.** That function
only shortlists which plans get sampled; the search's actual judgement is
`rollout_value`, twelve rounds played forward with `greedy_plan`. The
patience we are trying to reproduce is a *rollout* property.

The climb has no rollout. So "teach `_quick_score` to value holding" may be
trying to grow the behaviour on an organ that never carried it. The obvious
correction -- give the climb a rollout -- was tried and lost 3.3 to 3.8
points, which we attribute to variance across candidates too similar to
distinguish. Those two facts together are the tightest corner in this
project: the patience lives in a rollout, and the climb cannot afford a
rollout quiet enough to be read.

### 3. Being more correct about the game made the search play worse

The strangest evidence here, and we would value a view on whether it
generalises. Three corrections were made to the scorer, each *right* about
TTR's mechanics: weight a lure's damage-prevention by whether the lure
actually lands; apply per-cog lure durations rather than one mean; stop
multiplying kills by lure duration (a plain accounting error). Measured:

    67.8%   as written, defects and all
    64.4%   + accuracy weighting
    65.0%   + per-cog rounds
    65.6%   + both, re-swept

Every correction cost points. The cause is a **dual role**: `_greedy_score`
is not only an evaluator, it is the policy that plays the rollouts grading
every plan. Making it more careful about lures did not make the search
patient -- it made the search's *model of the future* passive, and holds in
the simulated continuation went 11.0% to 17.4%. The search then compared
plans against a future in which it plays badly.

We think the general form is: **when a rollout policy and a leaf evaluator
share an implementation, fidelity improvements to the shared code are not
sign-definite**, because a rollout policy wants to be *strong and fast* while
an evaluator wants to be *accurate*. Is that the right reading, and is the
standard answer simply to pay for two implementations?

### 4. Self-referential improvement operators have no fixed point

From the DAgger failure. AlphaZero distils MCTS, an operator defined
*independently* of the policy -- the student chases a target that stands
still. `climb` is defined as a perturbation *of the policy's own output*, so
distilling it moves the target by exactly the amount the student moves.
Agreement with the teacher stayed flat at 37-46% across six iterations while
the loss fell monotonically: the student got better at the labels and no
closer to the teacher.

We suspect this rules out the whole family of cheap self-referential
improvement operators as distillation targets, which is a shame, because the
cheapness was the point. The only anchor we have that the student does not
control is the classical search, at 200x the cost per label.

## Questions we would value an outside view on

0. **The search's lead is gone and the disagreement is free.** The agents tie
   at ~65%, choose the same joint plan on 5.3% of rounds, and three quarters
   of their disagreements are worth under a point. What is the right
   objective now? The policy is 200x faster, so it is the better agent on
   every axis that remains; the search's value would be as an independent
   judge and a source of labels. Is there a principled use for a slower,
   equal-strength second agent, or is the move to retire it as the benchmark
   and find a harder task -- higher floors, tighter pouches -- where the two
   separate again?
1. **How should an experiment like the CRN fork be made neutral?** Ours
   reversed sign depending on whether the continuation was the search's
   rollout policy or the climb, because each agent's move was chosen assuming
   its own follow-up. Averaging the two continuations feels like splitting a
   difference rather than removing a bias. Is there a standard construction
   for comparing two policies' actions without privileging either one's
   continuation -- and is "the better move depends on who plays after it" a
   known phenomenon with a name?
2. **Four times now, an evaluator sharing the proposer's assumptions has
   produced a result that then vanished.** PPO's critic on PPO's samples, a
   greedy two-ply, a PPO rollout judge, and now a CRN fork continued by the
   search's own rollout policy -- the last passing a cluster bootstrap and a
   sign test at p=0.007. Is there a checkable property that would have caught
   all four in advance, short of running every experiment twice with the
   roles swapped?
3. Is the "candidates too similar for a noisy evaluator" hypothesis right?
   If so, is probes+rollout together the correct test, or is there a better
   way to get candidate diversity that the evaluator will actually accept?
3. ~~Would cloning from the **climb** work better than cloning from the
   search?~~ **Answered: no** (item 7). The follow-up we would value a view
   on: is a self-referential improvement operator — one defined as a
   perturbation of the student's own output — *ever* a usable distillation
   target, or does the missing fixed point rule the whole family out? If
   the latter, the operator has to be anchored to something the student
   does not control, and the cheapest such anchor we can see is the
   classical search, which is 200x too slow to label with.
4. ~~Is a 256x2 MLP too small?~~ **Answered: no** (item 6). Doubling the
   trunk did nothing, so the 6M-step saturation is not capacity.
6. ~~Is there a principled way to make an evaluator value *not acting*?~~
   **Withdrawn.** This was the last live question of the original four, and
   it rested on the search holding 5x more often *and winning*. It does not
   win, and holding measures at -0.18 and -0.01 per disagreement under the
   two continuations. Five interventions were aimed at teaching an evaluator
   patience; none of them should have been. The question we should have asked
   first, and are now asking about everything else here, is whether the
   behaviour we were trying to copy was worth anything.
