# Learning the leaf evaluator

Scope for replacing `expectimax.heuristic_value` with a fitted model.

**Stage 0 is built.** `solver/search/features.py`,
`solver/search/fitted.py` and `tools/fit_heuristic.py`. Measured against
exact play on 120 fights: agreement 86% -> 92%, and regret -- the EV
given up when the choice differs -- 243.8 -> 7.4. Searches are also
*faster*, 10.6s -> 6.1s over the same fights, because accurate leaf
values tighten the window and cut more. Stage 1 has not been started.

## Why this component and not the search

`heuristic_value` is the only *guessed* piece of the solver. Everything
in `solver/data/` is transcribed and `[CONFIRMED]`; the outcome
distributions and the search are exact arithmetic. The heuristic is two
hand-picked terms with hand-picked weights:

```python
100 * cog_progress - 100 * (1 - laff_kept)
```

It is also the thing that decides quality at the depth we can afford.
The search reaches depth 2 on most positions and depth 1 on crowded ones,
so nearly every line ends at a cutoff and is scored by this function.
Benchmarked against exact `solve()` on small fights it agrees with
optimal play about **78%** of the time. That number is the target.

Improving it costs no search time, which is the opposite of every other
lever left.

## What is actually wrong with the current one

Measured against exact `solve()` values on 45 random positions:

| | |
|---|---|
| heuristic mean | **-6.5** (range -66 to 63) |
| true value mean | **93.7** (range 67 to 100) |
| systematic bias | **-100.2 points** |
| mean absolute error | 100.2 |
| correlation with truth | 0.44 |
| pairwise ordering correct | 70% |

The bias is not noise and its size is not a coincidence. The heuristic
scores a position relative to "full laff, cogs untouched = 0". The true
value of a winnable position includes the **+100 the battle is on track
to pay**. The heuristic has no notion of who is going to win, so it omits
the term that dominates the entire value scale.

That matters inside the search, not just on paper. Terminal wins score
+100 and cutoff nodes score around -6, so any line that finishes is
flattered against any line that merely looks good and runs out of
horizon. The evaluator is not just imprecise, it is pulling in a
direction.

### Three things it cannot express at all

Positions it scores *identically* that are not worth the same:

| position | heuristic | true value |
|---|---|---|
| focus fire, one cog nearly dead | -18.8 | 68.5 |
| spread, same total cog HP | -18.8 | **89.8** |
| four gags against one cog | -35.4 | 99.0 |
| one gag against one cog | -35.4 | **92.0** |
| cog lured for three rounds | -35.4 | 99.6 |
| cog awake | -35.4 | 98.9 |

- **Cog HP is summed, so where the damage went is invisible.** Note the
  spread position is worth *more* here: both cogs sit inside one-shot
  range, while focusing leaves a full-health cog needing two gags from a
  hand of three. The quantity that matters is how many cogs can be
  killed with what is in the pouch, which is a threshold, not a ratio.
- **Gags remaining do not appear.** A toon that cannot finish the fight
  scores the same as one that can.
- **Lure and trap do not appear.** A lured cog is not attacking, which is
  most of what lure is for.

So the first job of a fitted evaluator is not subtle feature
engineering. It is calibration: predict the value the position actually
has, terminal reward included. The features above are the second job,
and worth perhaps twenty points where the calibration is worth a
hundred.

## Inference cost is not the constraint

This was the first thing to check, and it ruled out the objection the
scope was going to be built around. On a three-cog depth-2 search the
heuristic is called **81,202** times but accounts for only **0.09s of
4.67s — 2%**. Measured cost per call:

| evaluator | per call | per search | vs today |
|---|---|---|---|
| current, hand-written | 1.08 µs | 0.09s | — |
| linear over ~100 features | 1.05 µs | 0.09s | free |
| MLP 100-64-32-1, unbatched | 6.7 µs | 0.5s | +11% of search |
| same MLP, batched x256 | 0.44 µs | 0.04s | cheaper than today |

A small net is affordable **unbatched**. Batching would require
restructuring a depth-first search to collect a frontier, and the
numbers say not to bother.

## CORRECTION: the labels are not exact

This document was built on `solve()` playing a position to the end of
the battle. **It does not.** A line ends when the pouch empties, which is
not the same as the fight finishing: with cogs still standing there are
no legal actions, and the value returned is `heuristic_value` -- an
estimate, at the exact point the search was supposed to stop estimating.

Measured: re-solving 300 cached training positions under two different
heuristics changed **83% of the labels**, by 3.7 points on average. Under
genuinely exact labelling none would move at all.

So the fitting was partly circular. `tools/fit_heuristic.py` labels with
whatever heuristic is installed, and by the time the 5,000-position set
was built that was the fitted model -- a model being trained on its own
output wherever a line ran out of gags.

It is also how the problem surfaced. A regret metric computed the
reference value with weights installed and the comparison value without,
and reported *negative* regret, which is arithmetically impossible if
both sides are exact.

What this does and does not invalidate:

* The **calibration** finding stands. The hand-written heuristic was
  ~100 points below any plausible value scale, and that gap is far larger
  than the 3.7-point label noise.
* The **feature** work stands. Kill thresholds, gags remaining and the
  trap/lure conjunction are real distinctions regardless of how the
  targets were computed.
* The **specific weights** do not. They are fitted to partly circular
  targets and must be refitted -- see below, the hole they were fitted
  through is now closed.
* The **MAE and agreement figures** are measured against a reference that
  is not ground truth, so they overstate how well the model matches
  optimal play.

The fix was a modelling decision rather than a bug fix, and it has since
been made.

## RESOLVED: running out of options is a loss

Nothing restocks a pouch mid-fight in this model -- SOS cards, Unites and
Fires are not modelled -- so gags only ever run down. A position with no
remaining way to damage a cog therefore ends the battle exactly as surely
as running out of laff, and `BattleState.is_terminal` now says so, via
`can_still_damage()`.

"No way to damage a cog" is narrower than "no attack gags", and the
narrowness is the whole content of the rule:

| pouch | verdict |
| --- | --- |
| empty | loss |
| 80 Lures, no attacks | loss -- a long fight is still a lost one |
| Toon-Up and/or Trap only | loss solo; nothing springs the trap |
| Trap **and** Lure | not a loss; the pair works where neither half does |
| Lure only, cog already trapped | not a loss; the trap is on the board |
| a gag in an untrained track | loss; it is not a usable option |

Two things follow. Labels stop depending on the heuristic: the same
out-of-gags position that scored **+47.6** now scores a terminal 0 with
the loss penalty already paid on the transition into it, and re-solving
it under different weights gives the same answer. And the search gets
faster, because a dead end is a cutoff rather than a subtree. Measured on
positions where dead ends are reachable within the horizon:

| position | before | after | |
| --- | --- | --- | --- |
| Toon-Up + Trap only, 1 cog | +87.8 | 0.0 | 400x |
| Toon-Up + Trap only, 2 cogs | +55.9 | 0.0 | 260x |
| Lure-heavy, no attacks | +99.4 | 0.0 | 2200x |
| Throw runs out mid-line | +53.3 | **-101.8** | 4x |
| mixed, no dead end in horizon | +83.5 | +83.5 | 1.2x |

The fourth row is the one that matters for play quality rather than
speed: two Throws cannot finish a level-6 cog and the rest of the pouch
is Toon-Up and Trap, so the fight is lost -- and the old evaluator called
it a win in progress. The last row shows the rule costs nothing where it
does not apply.

### The exception: passing

There are positions with nothing to do that are *not* losses. With Trap
and Lure left against an already-lured cog, Trap will not go on a lured
cog and a Lure only refreshes a timer the toon wants to run down -- but
waiting for the lure to lapse, then trapping and re-luring, wins. So
`Action(track=None)` is a real move. On that fight, exact search goes
from **-100.6** (burn Lures until the pouch is dry) to **+94.3**, playing
pass, pass, pass, Trap, Lure.

It is offered only when a cog is lured *and* no other action is
productive, which is narrower than the game's own rule, for two reasons
given in full in `simulator.legal_actions`. Briefly: a pass while lured
costs no laff and no gag, so at a search horizon it looks free when it is
not, and offered unconditionally it swung a depth-2 search off a killing
blow and onto a Lure. And termination now rests on the lexicographic
measure (gags remaining, total lure rounds remaining) rather than on gags
alone, which only decreases if a pass requires a lured cog.

`solve()` is exact again, so the weights can be refitted against labels
that are actually ground truth.

## The refit

Verified first, rather than assumed: 400 positions re-solved under three
evaluators — the shipped weights, the hand-written form, and a
deliberately absurd one with a −500 intercept — moved **0%** of labels,
against 83% before. Wall-clock was identical for all three, which is the
other tell that the evaluator is never consulted in an exact solve.

Two holes turned up while setting that up, both the same shape as the
original bug — a rule change that some other component was not told
about:

* `RULE_FILES`, which keys the label cache, listed neither `state.py`
  nor `objective.py`. A change to *what counts as a loss* would not have
  invalidated the cache.
* `fitted.value` and `hand_written_value` both short-circuited terminal
  states with `laff <= 0`. A dead-end position went to the linear model
  instead, and it is the worst case for extrapolation: full laff, gags in
  the pouch, every feature reading healthy.

Fitted on 5,000 exact labels, validated on 526 larger hold-out positions:

| | bias | MAE | r | ordering |
| --- | --- | --- | --- | --- |
| hand-written | −51.0 | 95.9 | 0.07 | 52% |
| refit, 15 features | +10.1 | 50.6 | 0.69 | 90% |
| refit, + budget features | **+0.9** | **25.6** | **0.86** | **91%** |

The middle row is the honest apples-to-apples refit. The third adds
`damage_budget_ratio` and `cannot_finish`, prompted by `gags_ratio`
coming back with a weight of 244 on a ±100 scale — a proxy shouting
because it was carrying a question it could not answer. Adding the two
that answer it directly halved hold-out MAE and dropped `gags_ratio` to
12.75.

### What it cost

A model that can say "full laff, but this pouch cannot finish the fight"
returns values the hand-written form never could, and the depth-aware
pruning floor had that form's shape written into it. The new evaluator
returned −98 at a node the bound put at [0, 100], `*`-minimax cut
branches it had no warrant to cut, and pruned and exhaustive search
returned different values — 48.66 against 46.63.

The floor now asks the evaluator for its own minimum rather than
assuming one (`expectimax.heuristic_floor`). Pruning survives the looser
bound comfortably: the fitted evaluator cuts leaves 2.0x against
exhaustive where the hand-written form manages 1.3–1.4x, because a
sharper evaluator orders moves better, and move ordering is the other
half of what makes a cut fire.

## The advantage this was meant to have: exact labels

Most game-playing nets bootstrap from their own estimates. Here we can
generate ground truth. Every action either spends a gag or, if it is a
pass, burns a round of lure, so (gags remaining, lure rounds remaining)
strictly decreases, the state graph is a DAG, and `solve()` plays to the
end of the battle exactly — see the module docstring in `expectimax`.
That was aspirational when this section was written and is true now;
the section above is the correction it went through in between.

So training targets are true values, not TD estimates. That removes the
usual instability entirely.

**The catch, and the main risk of the whole project:** `solve()` is only
tractable on small positions — few gags, one or two cogs. Those are
exactly the positions where the heuristic matters least, because the
search reaches a terminal state anyway. A model fitted there has to
extrapolate to crowded fights with full pouches, which is a real
distribution shift and the thing most likely to make this fail.

Two mitigations, both worth doing:

- Label medium positions with deep bounded searches (depth 4-5). Not
  exact, but far better than the current heuristic, and drawn from the
  distribution that matters.
- Hold out large positions for validation and refuse to ship on
  training-set agreement alone.

## Features

Roughly 100 numbers, all cheap to compute from `BattleState`:

- `laff / max_laff`, and raw laff
- per cog slot (4 slots, zero-padded): `hp / max_hp`, level, department
  one-hot, lured, trapped, lure rounds remaining
- gag counts per `(track, level)` — 42 numbers
- `track_exp` per track — 6 numbers
- derived: cogs alive, total remaining cog HP over total max, worst-case
  incoming damage per round (`max_round_damage`, already written for the
  search bounds), whether one round of cog damage could kill the toon

That last one matters and the current heuristic cannot express it: being
one hit from death is a step change in value, not a linear slide in
`laff_kept`.

**Conjunctions, not just terms.** Several things here are worth
something only in combination, which a linear model cannot express no
matter how many features it is given.

The clearest is Trap. A trap does nothing until a cog is lured onto it,
so an armed trap with Lure in the pouch is a large stored gain and an
armed trap with no Lure left is dead weight. Those two states differ
only in a gag count that has nothing to do with the trap. The search
already gets this right, because the simulator models it -- given Trap
and Throw but no Lure, Trap ranks last at EV 31.9 against Throw's 88.6,
and adding Lure lifts it to 52.3 -- but the search pays depth to
discover it, and at a cutoff the heuristic sees only `trapped=True` and
scores both identically.

So the feature set wants `trapped AND lure_gags_remaining > 0`, not
`trapped` and `lure_gags` separately. Others of the same shape: a gag
that can one-shot a cog versus one that leaves it at 1 HP, and laff
below one round of incoming damage.

This is the strongest argument for Stage 1 actually being needed. A
linear fit can only capture a conjunction if someone writes the product
term out by hand, and the useful ones are unlikely to all be guessed in
advance -- which is the same mistake the current two-term heuristic
represents.

**Out of scope: multi-toon trap interactions.** Two toons can both place
a trap on the same cog in one round, and the traps cancel -- which makes
"deliberately waste a cheap trap to cancel a teammate's Banana Peel, so
the Lure is not squandered on a level 12" a real play. It cannot arise
here: this solver is solo, a toon acts once per round, and
`legal_actions` refuses to trap an already-trapped or lured cog. Worth
recording because it is the kind of rule that looks like a modelling gap
rather than a scope boundary.

**Objective conditioning.** The heuristic is objective-independent today,
but the value scale is not — `survive` weights laff 3x, `conserve` prices
scarce gags at 12. Either feed the objective's parameters in as features
or fit one model per preset. Feeding them in is cleaner and lets the
model interpolate.

## Staging

**Stage 0 — refit the existing form.** Keep a linear model, expand from
2 features to the set above, fit by least squares on exact labels. Costs
the same 1.05 µs, needs no new dependency, and can ship the moment it
beats 78%. Most of the available win is probably here: the current
weights were chosen by hand, not fitted, and the feature set is missing
obvious terms.

### Stage 1 measured: not yet worth it

Five models on the same 500 labels, scored on the same 97 larger
hold-out positions:

| model | params | train MAE | hold-out MAE |
|---|---|---|---|
| linear (shipping) | 15 | 15.2 | **18.9** |
| quadratic | 135 | 9.0 | 21.9 |
| MLP-16 | 273 | 9.4 | 19.3 |
| MLP-32 | 545 | 8.1 | **18.5** |
| MLP-64 | 1089 | 7.2 | 22.3 |

Every nonlinear model fits the training set far better and none of it
survives to the hold-out; MLP-64 halves training error and is the worst
of the five. The best, MLP-32, beats the line by 0.4 MAE on 97
positions, which is noise.

That gap between train and hold-out is data starvation, not a ceiling on
capacity: 500 examples cannot constrain 545 parameters. It does not
contradict the conjunction argument above -- interactions are real, and
the linear model only sees `trapped x lure` because the product was
written out by hand -- but a net needs enough examples to tell a real
interaction from a coincidence, and 500 is not enough.

The experiment that settles it is simply more data. Labelling now runs
at roughly 500 positions per 46s, so 5,000 is about eight minutes; refit
all five and see whether the MLP pulls away or the curves stay flat.
The hard limit is that exact labels exist only for small positions, so
the data can grow in quantity but not much in size.

**Stage 1 — small MLP,** only if Stage 0 plateaus below what the exact
labels suggest is reachable. Train offline with torch; **ship the weights
as an `.npz` and run inference in numpy**, so the runtime keeps its
current dependency set and `requirements-vision.txt` stays the only
extra.

**Stage 2 — batching.** Only if profiling asks for it. It currently does
not.

## How to know it worked

`heur_bench.py` already exists and does the right thing: sample random
small fights, solve each exactly, and measure how often a depth-limited
search using the candidate heuristic picks the exact solver's move,
plus the EV given up when it differs. Baseline **78%**.

Three cautions learned from the last round of heuristic work, where
three plausible ideas all lost and one apparent winner turned out to be
noise:

1. Report agreement *and* regret. A heuristic can agree less often but
   lose less when it is wrong, which is the better one.
2. Use enough fights that the difference clears the noise. The earlier
   comparison of 75% against 78% on 40 fights was not significant.
3. Validate on positions bigger than the training set, since that is the
   failure mode this design is most exposed to.

## Where this sits against the alternative

The other lever is the action set. At maximum legal diversity — 42
distinct gag types, 80 pouch gags — a four-cog position offers **123**
actions against 50 for a typical loadout, and depth 2 goes from 13.6s to
over 60s. Cutting dominated actions attacks that directly and is exact,
where a learned heuristic is an approximation.

They are complementary: fewer actions buys depth, a better leaf
evaluator buys quality at whatever depth is affordable. If only one gets
done, the action set is the safer investment; the heuristic is the more
interesting one.
