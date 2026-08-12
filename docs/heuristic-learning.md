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
