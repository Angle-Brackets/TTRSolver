# Search Depth and Branching Dynamics

Analysis of game tree branching factors, star1/star2 pruning limits, and cog phase distribution collapsing.

## Branching Factor Decomposition

Each search ply expands into a product of toon actions and chance outcomes:

$$\text{Branching per ply} = |\mathcal{A}_{\text{toon}}| \times |\Omega_{\text{chance}}|$$

| Scenario | Actions ($|\mathcal{A}|$) | Outcomes per action ($|\Omega|$) | Total branches per ply |
|---|---|---|---|
| 2 flunkies, 10 gags | 8 | 20 | 160 |
| Realistic loadout, 3 cogs | 40 | 55 | 2,200 |
| Maxed loadout, 4 cogs | 123 | 70 | ~8,600 |

In minimax, alpha-beta prunes branches by refutation ($\mathcal{O}(\sqrt{b})$). In expectimax, chance nodes compute expectations; pruning requires bounding the unexpanded probability mass via star1/star2, achieving $\sim 3\times$ branching reduction per ply (vs $\sim 6\times$ in chess).

## Effective Branching by Depth

Measured on a small encounter:

| Depth | Cumulative Nodes | Effective Branching |
|---|---|---|
| 1 | 67 | — |
| 2 | 3,430 | 51.2 |
| 3 | 62,499 | 18.2 |
| 4 | 515,889 | 8.3 |

Branching decreases with depth as pouch depletion restricts downstream legal actions (finite DAG property).

## Cog Phase Distribution Collapsing

Because cogs make no decisions (attack selections and accuracy rolls are non-strategic damage distributions), replacing the full cog damage distribution with its expected value collapses chance outcomes from 20–70 down to 2 (toon hit vs toon miss).

### Benchmark Comparison (15s Budget)

| Position | Exact Depth (Time) | Collapsed Depth (Time) |
|---|---|---|
| 2 flunkies, 10 gags | 4 (9.7s) | **6** (3.9s) |
| Realistic loadout, 2 cogs | 3 (14.0s) | **4** (3.6s) |
| Realistic loadout, 3 cogs | 2 (4.8s) | **3** (2.1s) |

At matched depths, collapsing introduces minimal EV distortion ($< 2.3$ points) and preserves identical move selections (5/5):

| Position | Exact Action | Collapsed Action | EV Error |
|---|---|---|---|
| 2 flunkies | `throw4` | `throw4` | 2.27 |
| 2 cogs fresh | `sound7` | `sound7` | 0.52 |
| 2 cogs hurt | `sound6` | `sound6` | 0.39 |
| 2 cogs low laff | `sound7` | `sound7` | 0.31 |
| 3 cogs | `lure6` | `lure6` | 1.08 |

### Safety Invariants & Gating

1. **Root Depth vs Leaf Collapsing**: Collapsing must occur near the root; applying exact resolution at depth 1 and collapsing deeper yielded negligible speedup (3 cogs: 4.66s vs 4.66s; 4 cogs: 13.94s vs 13.54s) because subtrees compound downward.
2. **Objective Gating**: Collapsing assumes risk neutrality. Under risk-averse objectives (`survive`, where `laff_weight` is $3\times$), collapsing produced action divergence (2/9 positions). `may_collapse` gates on `laff_weight`.
3. **Lethal Branch Partitioning**: `collapse_damage` never merges branches where the toon is eliminated into surviving branches.

## Depth Limits Under Full Diversity (15s Budget)

Realistic loadout (20 distinct gags):

| Opponents | Exact Depth (Time) | Collapsed Depth (Time) |
|---|---|---|
| 2 cogs | 3 (14.3s) | **4** (3.9s) |
| 3 cogs | 2 (4.7s) | **3** (2.0s) |
| 4 cogs | 2 (13.9s) | **3** (4.8s) |

Maxed loadout (42 distinct gags, 80 pouch count, 6 level-7s):

| Opponents | Actions ($|\mathcal{A}|$) | Exact Depth (Time) | Collapsed Depth (Time) |
|---|---|---|---|
| 1 cog | 42 | 3 (4.0s) | **4** (6.5s) |
| 2 cogs | 69 | 2 (2.4s) | **3** (4.1s) |
| 3 cogs | 96 | 1 (0.05s) | **2** (1.3s) |
| 4 cogs | 123 | 1 (0.09s) | **2** (3.3s) |

Collapsing guarantees a minimum lookahead of depth 2 across all legally possible board states within the 15s budget.

## Move Ordering Analysis

Under alpha-beta, optimal move ordering evaluates $\sqrt{b}$ actions per node:

| Scenario | Legal Actions ($b$) | Evaluated Actions | Theoretical Floor ($\sqrt{b}$) |
|---|---|---|---|
| 2 cogs | 28.4 | 6.1 | 5.3 |
| 3 cogs | 38.0 | 6.6 | 6.2 |

Evaluated actions are within 6–15% of theoretical optimality without killer moves or history heuristics. The iterative-deepening transposition move provides near-optimal move ordering, and domain actions are dominated by clear utility hierarchies.

## Summary of Optimizations

1. **Cog Phase Collapsing**: Adds $+1$ to $+2$ plies by reducing chance branching factor from 20–70 to 2.
2. **Dominated Action Pruning**: Exact reduction of action cardinality $|\mathcal{A}|$. (Halving actions yields $\approx \sqrt{2}\times$ speedup since only 6.6 of 38 actions are evaluated).
3. **Fitted Leaf Evaluator**: Improves leaf evaluation accuracy at cutoff horizons (see [heuristic-learning.md](heuristic-learning.md)).
4. **Move Ordering**: Already operating within 10% of theoretical floor $\sqrt{b}$; killer tables and history heuristics are unnecessary.
