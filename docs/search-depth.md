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

**Shipped, with the gate somewhere other than where I expected.**

Two attempts at the safety rule were wrong before the third worked.

*Depth-based (`exact_plies=1`, keep the root exact).* This was the late
move reduction analogy: full effort near the root, cheaper further down.
It gave back the entire benefit -- three cogs 4.66s to 4.66s, four cogs
13.94s to 13.54s. The saving compounds *downward*: collapsing a node
shrinks every subtree beneath it, so the shallow nodes are precisely
where it pays. Collapse near the root or do not bother.

*Position-based (skip collapsing when a round could kill).* Also wrong,
twice over. With four cogs the worst-case round is large enough that the
test fired nearly everywhere and four cogs fell back from depth 3 to
depth 2. And it missed the real failures anyway.

*Objective-based -- what shipped.* At equal depth over nine positions
and two objectives:

| objective | same move |
|---|---|
| balanced | 9/9 |
| survive | 7/9 |

Both disagreements were `survive`, and one was a toon at **full laff**.
So the distortion is not about danger: collapsing is risk-*neutral*, and
`survive` weights laff 3x, which is risk-*averse*. `may_collapse` gates
on the objective's `laff_weight`, and `collapse_damage` additionally
never merges a branch where the toon died into one where it survived.

## Move ordering: measured, and NOT worth doing

This looked like the obvious untapped lever -- chess gets most of its
effective branching reduction from ordering, and this search orders by
the transposition table's move and nothing else. So the plan was killer
moves and a history heuristic.

Measuring first killed it. Perfect ordering under alpha-beta examines
`sqrt(b)` actions per node; that is the floor, and nothing beats it:

| position | actions available | evaluated | sqrt(b) |
|---|---|---|---|
| 2 cogs | 28.4 | 6.1 | 5.3 |
| 3 cogs | 38.0 | 6.6 | 6.2 |

Already within 6-15% of the optimum. Two reasons it comes for free here.
The transposition move from the previous iterative-deepening pass is an
excellent first guess, and the domain has a handful of obviously
dominant actions -- a level 7 group gag is usually either the best move
or clearly not, with little in between.

There is nothing for a killer table to recover.

Worth recording what a killer *would* have meant, since defining it was
the part that needed thought. `Action` is `(track, level, target_index)`
and all three transfer across siblings: cogs are never removed from
`state.cogs`, only flagged dead, so a slot index means the same cog for
the whole battle. The wrinkle chess does not have is that actions consume
resources -- a killer can be *illegal* in a sibling because that gag ran
out along a different line -- so any such table would have to check
legality on lookup.

A history heuristic would also have suited this domain unusually well.
In chess a move's value depends heavily on position; here `(THROW, 7)`
is Wedding Cake everywhere in the tree and does the same thing, so
cutoff statistics keyed on the gag would generalise far better than
they do in chess. Filed as an observation, not a plan: the measurement
above says there is no gain to collect.

## Ranked

1. **Collapse the cog phase beyond depth k.** Validated in prototype,
   +1 to +2 plies, same move at equal depth. This is effectively the
   whole game: chance width is what is left once ordering is ruled out.
2. **Cut dominated actions.** Exact, and attacks the other factor -- 123
   actions on a maxed four-cog position. But modest: only 6.6 actions of
   38 are actually evaluated, so halving the action count buys about
   `sqrt(2)`, not 2x.
3. A better leaf evaluator (`docs/heuristic-learning.md`) -- buys
   quality at whatever depth the above reach, not depth itself.
4. ~~Move ordering.~~ Measured at the alpha-beta optimum already.
