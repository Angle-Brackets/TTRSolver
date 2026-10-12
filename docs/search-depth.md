# The expectimax search: what it enumerates, what it costs, and where it stops

This document describes the exact search in `solver/search/expectimax.py`:
how a round is enumerated, why depth is expensive, which optimisations are
in the code, and what the search cannot see. The search is in use today as
the **Search** row of the live panel and as the source of exact labels for
the leaf evaluator, but it is no longer the engine the panel leads with.
Since 2026-10-11 the Playout engine (`solver/search/playout.py`) leads in
every fight unless the player picks another engine; the measurement behind
that is under [What limits it](#what-limits-it).

Every timing and agreement figure below was measured on sampled positions
with the search itself; the win counts in the last section come from
simulated fights. None of it is a measurement of the live game.

Terms used throughout: a **toon** is the player's character, a **cog** is an
enemy, a **gag** is a consumable attack carried in a limited **pouch**, and
**laff** is the toon's hit points. A **ply** is one round: the toon acts,
then every cog still awake attacks.

## The tree

Two kinds of node alternate.

- A **MAX** node is the toon's choice. Its value is the best action's value.
- A **CHANCE** node is everything the toon does not control: whether the gag
  lands, which attack each cog picks, whether it hits, and for how much.
  Its value is a probability-weighted average.

The value of an action $a$ in state $s$ at depth $d$ is

$$Q_d(s, a) = \sum_{i} p_i \,\bigl(r_i + \gamma\, V_{d-1}(s_i)\bigr), \qquad V_d(s) = \max_a Q_d(s, a)$$

where the sum runs over the outcomes of $a$, $r_i$ is the reward of outcome
$i$ and $\gamma$ is a discount that defaults to 1. The reward is defined by
an `Objective` (see [scoring.md](scoring.md)): laff lost, the price of the
gag, a flat charge per round, and $\pm 100$ when the battle is won or lost.
A terminal state is worth 0, because the transition into it already paid
the $\pm 100$. At $d = 0$ the search stops and scores the position with a
leaf evaluator (`heuristic_value`; see
[heuristic-learning.md](heuristic-learning.md)).

`solve()` runs the same recursion with no depth cutoff. It terminates
because the state graph has no cycles: every action spends a gag, a pink
slip or an SOS card, except the pass, and a pass either burns a round of an
active Lure or draws on a small budget (`BattleState.free_passes`). The
triple (gags left, lure rounds left, free passes left) therefore decreases
on every line. A full solve never consults the leaf evaluator, which is what
makes its values usable as ground truth.

A battle is over when laff reaches zero, when every cog is dead, or when the
toon has no remaining way to damage a cog (`BattleState.can_still_damage`).
The third rule matters to the search: before it existed, a position with an
empty pouch had no legal actions and fell through to the leaf evaluator at a
node that was not a cutoff. Re-solving 300 cached positions under two
different evaluators changed 83% of the answers, which an exact search
cannot do.

## How a round is enumerated

`outcomes.action_outcomes(state, action)` returns every
`(probability, next_state, reward)` triple for one action, with
probabilities summing to 1.

The toon phase has at most two branches, hit and miss, with the hit
probability taken from the simulator's own accuracy function. The toon phase
itself is not reimplemented: both the sampling simulator and the enumerator
call `simulator.apply_toon_action`.

The cog phase is where the count could explode. Taken naively it is a joint
distribution over (which attack, hit or miss) for each cog; with five
attacks per cog and four cogs that is $(5 \times 2)^4 = 10{,}000$ branches.
Two facts collapse it. With one toon in the battle, which attack a cog chose
does not change the next state beyond the damage dealt, so the joint is
convolved into a distribution over **total damage**. The only per-cog state
the phase can change is whether a lured cog woke up. What survives is a
distribution over (set of cogs whose lure ended, total damage).

Outcomes that reach an identical state are merged and their probabilities
summed (`outcomes.merge_key`).

`tests/test_outcomes.py::test_matches_sampled_step` compares the enumerated
distribution against 8,000 samples of the sampling simulator, so the two
implementations of the cog phase are held to each other.

## Why depth is expensive

A ply costs (actions) × (chance outcomes per action). Measured on
2026-08-12:

| Position | Actions | Outcomes per action | Branches per ply |
|---|---|---|---|
| 2 Flunkies, 10 gags | 8 | 20 | 160 |
| Realistic loadout, 3 cogs | 40 | 55 | 2,200 |
| Maxed loadout, 4 cogs | 123 | 70 | about 8,600 |

The second factor resists the technique that makes deterministic game search
fast. Alpha-beta prunes a node as soon as one reply refutes it. A chance
node is an average, and one bad child does not refute an average; the search
has to bound the probability mass it has not looked at yet. That is weaker
pruning.

Branching does fall with depth, because gags are spent and are not
restocked. On one small position (same date):

| Depth | Nodes | Effective branching |
|---|---|---|
| 1 | 67 | |
| 2 | 3,430 | 51 |
| 3 | 62,499 | 18 |
| 4 | 515,889 | 8.3 |

## Measured cost

The maintainer's notes give this for a real endgame loadout (20 distinct
gags, 30 root actions, two cogs): depth 1 in 0.01 s, depth 2 in 9.3 s, and
depth 3 in "many minutes".

A later benchmark (`tools/search_bench.py`, October 2026) used a maxed toon
with a partly spent pouch, 30 to 137 laff, and one to four cogs of level 6
to 12 at random health. Fully exact search, time per decision:

| Cogs | Depth 1 | Depth 2 | Depth 3 | Depth 4 |
|---|---|---|---|---|
| 1 | 0.01 s | 0.24 s | 6 s | over 60 s |
| 2 | 0.02 s | 2.8 s | over 60 s | |
| 3 | 0.07 s | 22 s | over 60 s | |
| 4 | 0.11 s | 42 s | over 60 s | |

The two sets of figures come from different positions and different
versions of the code, so they should not be compared cell by cell. Both say
the same thing: exact search answers at depth 2 and not at depth 3.

With the approximations described below, the same benchmark reached (mean of
three positions, 60 s cap):

| Cogs | Collapse only: depth 3 / 4 / 5 | Collapse + beam of 6: depth 3 / 4 / 5 |
|---|---|---|
| 1 | 0.3 s / 1.9 s / 9.6 s | 0.2 s / 0.8 s / 3.0 s |
| 2 | 1.0 s / 5.5 s / 27 s | 1.0 s / 4.0 s / 13 s |
| 3 | 2.9 s / 14 s / over 60 s | 2.9 s / 10 s / 30 s |
| 4 | 6.7 s / 35 s / over 60 s | 7.1 s / 23 s / about 55 s |

## What is in the code

Each row was checked against the current source. "Exact" means the value and
the chosen move are unchanged; `tests/test_search.py` pins pruned search
equal to exhaustive search.

| Optimisation | Where | Exact? | Default | Measured effect |
|---|---|---|---|---|
| `BattleState.clone` instead of `copy.deepcopy` | `solver/state.py` | Yes | Always | `deepcopy` was 91% of a depth-2 search; `clone` is about 20× faster |
| Cached cog attack and damage distributions | `solver/outcomes.py` (`lru_cache` on department, cog type, level) | Yes | Always | A three-cog depth-2 search requested the damage distribution 1.1 million times |
| Cog phase convolved to total damage | `outcomes.cog_phase_outcomes` | Yes, for one toon | Always | Removes the 10,000-branch joint described above |
| Merging identical successors | `outcomes.merge_key` | Yes | Always | |
| Symmetry de-duplication | `expectimax.distinct_actions` | Yes | Always | The same gag at two cogs identical in type, level, health and status is searched once |
| Dropping moves that provably do nothing | `simulator.legal_actions` (`is_productive`) | Yes | Always | For example re-luring a lured cog, or Drop on a lured cog |
| Transposition table | `memo` in `expectimax.evaluate` | Yes | Always | Keyed on state, depth and the approximation settings, with exact, lower-bound and upper-bound entries |
| Star1 and star2 pruning with depth-aware bounds | `expectimax._chance_value`, `_value_bounds` | Yes | On (`prune=True`) | 2.7 to 3.9× once the floor became depth-aware; 9.2× at depth 4 with collapse and a beam of 6 |
| Best-first move ordering | `expectimax.ORDER` | Yes | On | 1.24× at fully exact depth 3 (16 of 16 moves identical); 1.06× at depth 4 with collapse and a beam of 6 |
| Shallower pass's move as the first move tried | `expectimax.HINT_FROM_SHALLOWER` | Yes | On | 1.42× at fully exact depth 3 over 16 positions; 1.09× at depth 4 with collapse and a beam of 6 |
| Iterative deepening with a deadline | `expectimax.best_action_iterative` | Yes, per completed pass | Used by the panels | See below |
| Epsilon trimming | `expectimax.trim` | No, bounded | Off (`epsilon=0.0`); panels pass 0.03 | 1.5 to 1.8× at 0.03 with the same move on four positions |
| Cog-phase collapse | `outcomes.collapse_damage`, `exact_plies` | No | Off (`exact_plies=None`); panels turn it on | One to two extra plies |
| Beam below the root | `expectimax.BEAM` | No | Off (`None`) | See below |

The October pass also made two profiled hot spots cheaper without changing
any answer (60 of 60 identical, 1.5× overall): `can_still_damage` tests the
common case first, and the leaf features cache their pouch-only parts.

### Star pruning

Star1 bounds a chance node from the mass it has not yet searched. If child
$i$ is known to lie in $[L_i, U_i]$, the node lies in

$$\Bigl[\sum_i p_i (r_i + \gamma L_i),\ \sum_i p_i (r_i + \gamma U_i)\Bigr]$$

and it can be cut as soon as that interval leaves the window
$(\alpha, \beta)$. Each child is then searched with the narrowest window
that could still change the answer. Two details make the bounds tighter than
the textbook form. The reward of each branch is known exactly, so only the
recursive value needs a bound. And star2 first searches a single action at
each child: a MAX node is worth at least any one of its actions, so that
gives a lower bound obtained by search instead of assumed.

The ceiling $U_i$ is always a win, $+100$. The floor depends on the depth
left. With $d$ plies remaining the toon can lose at most $d$ rounds of
damage, so with $D$ the most the live cogs could deal in one round,

$$L = -\bigl(w_{\text{laff}} \cdot \min(\text{laff},\, d \cdot D) + \lambda + d\,(g + t)\bigr) + \min(0,\ \text{leaf floor})$$

where $w_{\text{laff}}$ is the objective's laff weight, $\lambda$ is the loss
penalty if $d \cdot D$ can reach zero laff and 0 otherwise, $g$ is twice the
dearest single gag or SOS card the objective can charge, $t$ is the
per-round charge, and the leaf floor is the lowest value the installed leaf
evaluator can return. Before the floor was depth-aware it assumed the toon
could lose its whole laff bar at every node, the interval stayed wide, and
pruning was a net loss.

The leaf floor has to follow the evaluator. The hand-written evaluator
cannot go below a number set by laff alone. The fitted evaluator can score a
toon at full laff at $-98$ when its pouch cannot finish the fight, and when
the bound did not allow for that, pruned and exhaustive search returned
different values. Pruning still pays with the looser bound.

A tighter, jointly minimised floor for the fitted evaluator was built, shown
admissible, and removed: it searched exactly the same 1,134,228 nodes on a
two-cog depth-3 position and cost 186 s of bound arithmetic against 7 s.
Star2's probes already raise the floor to a searched value wherever they
run.

### Epsilon trimming

`trim` keeps the likeliest branches of a chance node covering $1 - \epsilon$
of the probability and renormalises. A cog's damage distribution has a long
thin tail that costs as much to search as its head. Dropping mass $m$ from
branches whose contributions span a range $R$ moves the node's value by at
most $m \cdot R$; at $\epsilon = 0.01$ and $R \approx 250$ that is under 2.5
points, on a scale where a win is 100.

The panels use 0.03. Against an exact search on four positions it picked the
same move everywhere and ran 1.5 to 1.8× faster; 0.08 changed the move on a
three-cog position.

### Collapsing the cog phase

The cog phase carries no decision. Cogs cannot hurt each other or change
what is in the pouch; their attacks only subtract laff. `collapse_damage`
therefore merges outcomes that differ only in total damage into one outcome
carrying the mean laff, which takes 20 to 70 outcomes per action down to a
handful. Branches whose cog states differ stay separate, and a branch where
the toon died is never merged with one where it survived.

On 2026-08-12, at equal depth, the collapsed search picked the same move as
the exact one on five of five positions, with value errors of 0.31 to 2.27
points. In the October benchmark, collapse plus a beam of 6 picked the same
move as fully exact depth-3 search with a value difference of 0.004 to 0.005
points, and took a one-cog decision from 86 s to 4.6 s and a two-cog
decision from 534 s to 6.4 s.

Collapsing makes the search risk-neutral about damage, and the gate that
ships reflects that. Three gates were tried:

- **By depth** (`exact_plies=1`, keep the root exact). This gave back the
  whole benefit: three cogs 4.66 s to 4.66 s, four cogs 13.94 s to 13.54 s.
  The saving compounds downward, so the shallow nodes are where it pays. The
  October benchmark agreed: keeping the first ply exact was no more accurate
  and 4 to 13× slower.
- **By position** (do not collapse when a round could kill the toon). With
  four cogs the worst-case round is large enough that this fired almost
  everywhere, and it still missed the real failures.
- **By objective**, which is what `may_collapse` does. At equal depth on
  nine positions, the collapsed search matched the exact move 9 of 9 under
  the `balanced` objective and 7 of 9 under `survive`, which weights laff
  three times as heavily. One of the two disagreements was a toon at full
  laff. Collapsing is allowed only when the objective's `laff_weight` is at
  most 1.

### The beam

With `BEAM = k`, nodes below the root search only the $k$ moves that a
one-round look-ahead (reward plus leaf value) ranks highest. The root always
keeps every move, and direct calls to `evaluate` or `solve` are never
trimmed. Against fully exact search at depth 3: one cog at $k = 6$ picked
the same move on 100% of positions (value difference 0.003, 1.75× faster);
one cog at $k = 4$ on 93%; two cogs at $k = 4$ and $k = 6$ on 100%.

The beam is **off**. Its agreement with exact search was measured; its
effect on play was not, and the next section explains why more depth was not
expected to help.

## The entry point the panel uses

`best_action_iterative(state, depth, objective, epsilon, time_budget,
exact_plies, memo)` searches depth 1, then 2, and so on up to `depth`,
keeping the transposition table between passes so each pass tries the
previous pass's best move first.

With a `time_budget` it is an anytime search. A deadline is checked every
512 nodes (`DEADLINE_CHECK_INTERVAL`); when it passes, the pass in progress
is abandoned and the last completed pass is returned. A half-finished pass
is never used, because the moves it had not reached are the ones that might
have been best. The budget is enforced inside the search because the cost of
the next pass cannot be predicted from the last one: on a three-cog position
depth 1 took 0.01 s and depth 2 took 28 s.

The two live panels call it with these settings:

| Setting | Toontown Rewritten panel (`solver/live/advise.py`) | Realms panel (`solver/live/realms_panel.py`) |
|---|---|---|
| Depth cap | 4 | 4 |
| Time budget | 15 s | 4 s |
| `epsilon` | 0.03 | 0.03 |
| `exact_plies` | 0 (collapse everywhere) | 1 (root kept exact) |
| `BEAM` | Off | Off |

Both run the search in a separate process, because it is CPU-bound pure
Python and would otherwise stall the window. At these settings the first
panel reaches depth 4 with two cogs and depth 3 with three or four. The
second panel's budget is short because, on the maintainer's 70-gag loadout,
the recommended move stopped changing by 2 s with one, two and four cogs.

A caller may also pass a `memo` kept across the rounds of one fight. It is
exact, since entries are keyed by depth, but it barely helps (median 6.5 s
to 4.7 s, mean unchanged): the new board's deepest level was never searched
in the previous round.

If every action at a node is unevaluable because a data cell is still marked
`[TODO]` (see [data-confidence.md](data-confidence.md)), the search raises
`MissingData` naming the cell. It does not substitute a value, and the panel
reports the gap.

## What limits it

**It sees one battle.** The tree contains the cogs on the field. It does not
contain the cogs waiting to walk in, the later waves of a boss fight, or the
next floor of a building, and no depth reaches them. This is the measured
reason the Playout engine first took the lead in boss fights. On simulated
two-toon Vice President (VP) fights, a boss fight in which each side faces
ten cogs and then ten more, the Search row won 6 to 8 of 60 sides and the
Playout row 33 of 60 (+28/−1 paired). In cog buildings, where a floor is one
battle, the two were level: 146 against 149 of 200. The extension of the
Playout lead to every fight on 2026-10-11 is recorded in the code as the
maintainer's preference (`[OWNER]`; see
[data-confidence.md](data-confidence.md) for the tags), not as a further
measurement.

**More depth does not change single-battle answers.** With collapse and a
beam of 6, the move chosen at depth 4 was the deepest search's move on every
benchmark position (20 one-cog, 10 two-cog, 6 three-cog positions; deepest
depths 7, 6 and 5). An earlier test raised `epsilon` to 0.08 to buy depth on
three-cog boards and played 42 paired battles at 15 s a decision: 41 tied,
one improved, none got worse. Stable is not the same as correct, since a
biased leaf is shared by every depth, but it means the remaining error is in
the leaf and the horizon.

**The leaf is an estimate.** Below the cutoff the value comes from a fitted
linear evaluator. Three attempts to replace it with a learned network did
not play better; see [heuristic-learning.md](heuristic-learning.md).

**It is a one-toon search.** The enumeration relies on a single toon
absorbing all cog damage. Teammates enter only as a count that dilutes
single-target cog attacks. A party is searched by a different, sampling
search (`solver/search/party_search.py`), whose values are estimates and are
not comparable with `solve()`.

**It is slow next to the policy.** On 80 single battles with a wounded toon,
the Search row and the PPO row agreed on 79 of 80 decisions, and the search
won 100% against 98.8%, at 14.6 s a decision against 0.007 s.

**Its inputs include unconfirmed cog accuracy.** `python -m
solver.search.sensitivity` perturbs every cog accuracy cell and reports
whether the chosen move and the predicted outcome change. It is a tool for
bounding that uncertainty, not a correction for it.

## Ideas measured and not adopted

- **Killer moves and a history heuristic** (2026-08-12). With the
  transposition move tried first, the search evaluated 6.1 of 28.4 available
  actions per node on two-cog positions and 6.6 of 38.0 on three-cog
  positions, against a best case of $\sqrt{b}$ = 5.3 and 6.2. There was
  little left to collect, and neither was built. The cheaper best-first
  ordering in the table above was added in October and is exact.
- **Keeping the root exact while collapsing below it.** Described above; no
  speedup.
- **A tighter static floor for star1.** Described above; no extra pruning,
  and slower.
- **`epsilon` = 0.08.** More depth on three-cog boards, no change in play.
- **A beam of 6.** Agreement measured, play not measured; off.

## Reproducing

`tools/search_bench.py` has four modes, `depth`, `agree`, `fight` and
`stable`; run `python tools/search_bench.py --help`. The timing tables above
show what a single deep decision costs, so expect long runs. The fuller
record of the October measurements is in
[experiment-log.md](experiment-log.md).
