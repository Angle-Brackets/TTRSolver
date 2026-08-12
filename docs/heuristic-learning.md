# Learning the leaf evaluator

Scope for replacing `expectimax.heuristic_value` with a fitted model.
Nothing here is built yet.

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

## The unusual advantage: exact labels

Most game-playing nets bootstrap from their own estimates. Here we can
generate ground truth. Every action spends a gag, so gags-remaining
strictly decreases, the state graph is a DAG, and `solve()` plays to the
end of the battle exactly — see the module docstring in `expectimax`.

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
