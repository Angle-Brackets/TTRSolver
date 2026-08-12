# Why depth 2, when chess engines reach depth 10

A fair question, and the answer is structural rather than a failing of
the pruning.

## Chess has one branching number; this has a product of two

A ply here costs **actions x chance outcomes**, because a toon move is
always followed by a cog phase:

| position | actions | outcomes/action | per ply |
|---|---|---|---|
| 2 flunkies, 10 gags | 8 | 20 | 160 |
| real loadout, 3 cogs | 40 | 55 | 2,200 |
| maxed loadout, 4 cogs | 123 | 70 | ~8,600 |

Chess is ~35. So before any pruning, a ply costs between 5x and 250x
what a chess ply costs.

Worse, the second factor resists the technique that makes chess work.
Alpha-beta gets its `sqrt(b)` from the max/min structure: one refutation
kills a node. **A chance node is an average** -- you cannot refute an
average by finding one bad child, you have to bound the unseen mass. That
is what star1/star2 do, and they buy ~3x here where good move ordering
buys ~6x per ply in chess, compounding.

Being in Python rather than C is worth perhaps another 50x, but it is not
the main story.

## What is not the problem

Measured on a small position, effective branching per ply *falls* with
depth:

| depth | nodes | branching |
|---|---|---|
| 1 | 67 | -- |
| 2 | 3,430 | 51 |
| 3 | 62,499 | 18 |
| 4 | 515,889 | 8.3 |

Pruning works, and the DAG property helps: every action spends a gag, so
the tree genuinely narrows. Depth 4 is reachable on a small position in
10s. The wall is the chance width at the top, not the search.

## The lever: collapse the cog phase at depth

The cog phase carries **no decision**. The cogs' attacks only subtract
laff; the only qualitative branch is the toon's own hit/miss, which
decides whether a cog dies. So beyond the first plies the whole damage
distribution can be replaced by its mean, keeping one branch per
toon-phase result.

That takes outcomes per action from 20-70 down to 2.

Prototyped in `scratchpad/collapse.py`. Depth reached inside 15s:

| position | exact | collapsed |
|---|---|---|
| 2 flunkies, 10 gags | 4 (9.7s) | **6** (3.9s) |
| real loadout, 2 cogs | 3 (14.0s) | **4** (3.6s) |
| real loadout, 3 cogs | 2 (4.8s) | **3** (2.1s) |

And the approximation is benign. Compared at *equal* depth, which is what
isolates the error from the benefit of the extra ply:

| position | exact move | collapsed move | EV error |
|---|---|---|---|
| 2 flunkies | throw4 | throw4 | 2.27 |
| 2 cogs fresh | sound7 | sound7 | 0.52 |
| 2 cogs hurt | sound6 | sound6 | 0.39 |
| 2 cogs low laff | sound7 | sound7 | 0.31 |
| 3 cogs | lure6 | lure6 | 1.08 |

Same move 5/5, error well under the tens of points that separate
decisions.

**Caveats before shipping this.** Five positions is not a sample -- the
last round of heuristic work had a 40-fight comparison turn out to be
noise. And collapsing to the mean makes the search risk-*neutral* about
cog damage, which is exactly wrong for `survive` (laff weighted 3x) and
possibly for a toon one hit from death. The design should therefore be
`collapse_beyond=k`: exact chance nodes for the first k plies where the
risk actually bites, collapsed after, with k tunable and defaulting to
at least 1. That mirrors late move reduction in chess -- full effort
near the root, cheaper further down.

## The other untapped lever: move ordering

Chess gets most of its effective branching reduction from ordering the
best move first -- hash move, killer moves, history heuristic, MVV-LVA.
This search orders by the transposition table's best move and nothing
else. Static ordering by expected damage or kill potential, plus a
killer/history table, is standard and unexplored here.

## Ranked

1. **Collapse the cog phase beyond depth k.** Validated in prototype,
   +1 to +2 plies, same move at equal depth. Biggest single win
   available.
2. **Move ordering.** Standard, exact, unexplored.
3. **Cut dominated actions.** Exact, attacks the other factor -- 123
   actions on a maxed four-cog position.
4. A better leaf evaluator (`docs/heuristic-learning.md`) -- buys
   quality at whatever depth the above reach, not depth itself.
