# Scoring: the objective, the one-round scorers and the leaf evaluator

This document is the inventory of every number that says what a move is
worth: the `Objective` the exact search maximises, the one-round scorer
`_quick_score` that judges the PPO row's plans, the two cheaper scorers
behind it, and the fitted leaf evaluator. It lists each term, which system
defines it, which code reads it, and where two systems price the same thing
differently.

Status today: all of it is still in the code and in use. The objective
drives the Search row, and `_quick_score` drives the PPO row
(`hybrid.climb`). Neither is what the panel leads with any more: since
2026-10-11 the Playout engine leads in every fight unless the player picks
another engine, and it judges moves by playing fights out, not by these
scores. The section [What the playouts changed](#what-the-playouts-changed)
says what carried over.

All win rates below are from simulated fights. Terms: a **toon** is a
player character and a **cog** an enemy; a **gag** is a consumable attack
from a limited **pouch**, in seven tracks (Toon-Up heals, Trap and Lure set
up, Sound, Throw, Squirt and Drop deal damage) and seven levels; **laff** is
hit points. A **pink slip** (or "fire") removes a cog outright, an **SOS
card** calls a helper and costs the turn, and a **unite** restores laff or
gags without costing the turn. A **Version 2.0** cog has a second health bar
behind the first. A **lured** cog skips its attacks until the lure runs out
or it is hit. Tags such as `[OWNER]` and `[CONFIRMED]` are explained in
[data-confidence.md](data-confidence.md).

## The weight systems at a glance

| System | Defined in | Read by | Scale |
|---|---|---|---|
| `Objective` | `solver/search/objective.py` | The exact search (every round's reward), the sampling party search, the price inside `_greedy_score`, the reinforcement-learning reward, and the Playout engine's preset adjustments | A win is +100, a point of laff is 1 |
| `QUICK_W` | `solver/search/weights.py` | `_quick_score`, which is the judge inside `hybrid.climb` and ranks candidate plans in `party_search.plans` | A point of cog damage is 1; totals run into the thousands |
| `GREEDY_W` | `solver/search/weights.py` | `_greedy_score`, which picks each toon's move in `greedy_plan`, the rollout policy of the party search | A point of cog damage is 1 |
| `_cheap_score` constants | `solver/search/weights.py` | `_cheap_score`, arithmetic that shortlists candidates for `_greedy_score` | A point of cog damage is 1 |
| Fitted leaf weights | `solver/search/fitted.py` | `expectimax.heuristic_value`, at the search's depth cutoff | Same as `Objective` |

The two fast scorers take no objective. They cannot read its fields, so
each concept the objective prices had to be priced again in their own
units. That is where the disagreements listed later come from.

## The objective

The reward is a choice, not a game rule; nothing in the game says what a
gag is worth in laff. `Objective` holds the choices.

| Field | Default | Meaning |
|---|---|---|
| `gag_cost` | 0.1 | Cost of a gag per level |
| `scarcity_cost` | 0.0 | Extra cost divided by the gag's carry limit, so a gag you can hold one of is dear |
| `horizon_cost` | 0.15 | Raises gag prices by this fraction per cog still to come after this battle |
| `turn_cost` | 1.0 | Flat charge per round |
| `laff_weight` | 1.0 | Multiplier on laff lost |
| `sos_cost` | 10.0 | Charge for calling an SOS card |
| `win_bonus`, `loss_penalty` | 100, 100 | Paid on the transition that ends the battle |
| `waste_weight` | 0.0 | Charge for overkill, scaled by scarcity (party search only) |
| `rare_gag_premium` | 0.0 | Extra charge per level 7 gag (party search only) |
| `toon_lost_penalty` | 0.0 | Charge when a toon's laff reaches zero (party search only) |
| `risk_aversion` | 0.0 | Standard deviations of a plan's sampled returns subtracted from its mean (party search only) |

### Gag price

For a gag of level $\ell$ whose holder may carry at most $c$ of it, with $n$
cogs still to come after this battle:

$$\text{price} = \Bigl(\text{gag cost} \cdot \ell + \frac{\text{scarcity cost}}{c}\Bigr)\,\bigl(1 + \text{horizon cost} \cdot n\bigr)$$

The carry limit depends on the holder's training in the track, so the same
gag costs different toons different amounts. A pass costs nothing. A pink
slip has no track and is also priced at zero by the objective.

### One round's reward

The exact search uses `Objective.step_reward`, with one toon:

$$r = -\,w_{\text{laff}} \cdot \text{laff lost} - \text{price} - \text{turn cost} + 100\,[\text{won}] - 100\,[\text{lost}]$$

`outcomes._accumulate` adds two charges on top. An SOS call costs
`sos_cost` $\times\,(1 + \text{wasted reach})$. A group gag pays its price
again in proportion to its wasted reach. **Wasted reach**
(`simulator.wasted_reach`) is the share of live cogs a hit-all gag or card
cannot affect: group Drop on lured cogs, group Lure on cogs already lured,
group Trap on cogs already trapped or lured. It is the maintainer's
preference (`[OWNER]`), and all three engines charge it.

`step_reward` calls the price without the horizon argument, so
`horizon_cost` never reaches the exact search.

The sampling party search uses `party_search.round_reward`, which sums over
the whole party's laff and gags, passes the horizon, and adds
`rare_gag_premium` per level 7 and `toon_lost_penalty` per toon lost. A
plan's value there is the mean of its sampled returns, minus
`risk_aversion` standard deviations, minus `waste_penalty`.

### Presets

Five presets ship. Fields not listed keep their defaults.

| Preset | `gag_cost` | `scarcity_cost` | `turn_cost` | `laff_weight` | `waste_weight` | `rare_gag_premium` |
|---|---|---|---|---|---|---|
| `balanced` (default) | 0.1 | 4.0 | 1.0 | 1.0 | 20.0 | 6.0 |
| `speedrun` | 0.02 | 0.0 | 2.0 | 1.0 | 0.0 | 0.0 |
| `conserve` | 0.1 | 12.0 | 1.0 | 1.0 | 0.0 | 0.0 |
| `survive` | 0.02 | 0.0 | 1.0 | 3.0 | 0.0 | 0.0 |
| `glass cannon` | 0.0 | 0.0 | 1.0 | 0.25 | 0.0 | 0.0 |

What a Throw gag costs under each, for a fully trained track with nothing
still to come (computed from the code; carry limits are 30, 15, 3 and 1 at
levels 1, 4, 6 and 7):

| Preset | Level 1 | Level 4 | Level 6 | Level 7 |
|---|---|---|---|---|
| `balanced` | 0.23 | 0.67 | 1.93 | 4.70 |
| `speedrun` | 0.02 | 0.08 | 0.12 | 0.14 |
| `conserve` | 0.50 | 1.20 | 4.60 | 12.70 |
| `survive` | 0.02 | 0.08 | 0.12 | 0.14 |
| `glass cannon` | 0 | 0 | 0 | 0 |

How the non-default values were chosen, from the comments beside them:

- `balanced.scarcity_cost` = 4.0. At 0 the preset did not price resources
  at all. On one real position (a Spin Doctor at 104 health and a Yesman at
  72) level 7 gags won by 2.2 over an almost free Lure; the choice flips
  between 1.0 and 2.0, and 4.0 clears that with room. A 90-health cog that
  only a level 7 one-shots still gets the level 7 at every laff from 60
  down to 8.
- `balanced.waste_weight` = 20.0. Chosen, not derived. Over 60 random party
  positions it changed the plan in 48% and cut level 7 choices from 5 to 3.
- `balanced.rare_gag_premium` = 6.0. On one maxed four-toon position a
  level 7 appeared in 2 of 8 plans at 0.0 and 0 of 8 at 4.0 and above. The
  comment records that most of that effect was a shortlist bug, not the
  premium.
- `horizon_cost` = 0.15. Over 40 coordinated battles with 30 cogs to come,
  values of 0.033, 0.15, 0.5 and 1.5 gave win rates of 70.0%, 67.5%, 62.5%
  and 52.5%. On 120 fresh seeds at 0.15, horizons of 0, 10 and 30 won
  54.2%, 53.3% and 50.8%: about 7% of the pouch saved for about 3 points of
  win rate.
- `turn_cost` = 1.0. At 0 a party that had just lured the board could hold
  for free; holds per round were 0.75, 0.38 and 0.00 at 0.0, 1.0 and 2.0.
- `sos_cost` = 10.0. Chosen: about twice a level 7 under `balanced`. It was
  0, and the Search row then called a restock card beside a cog one hit
  from dead.

`objective.from_axes(caution, thrift)` interpolates linearly between the
presets' extremes on two axes. The corners are the shipped presets; the
interior has not been evaluated, and nothing under `solver/` calls it.

## `_quick_score`: the one-round scorer

`_quick_score(state, plan)` values a joint plan (one action per toon) by
simulating the toon phase of one round. It does not simulate the cog phase;
the cogs enter through an expected-damage figure. It is what `hybrid.climb`
uses to choose among the plans the trained policy proposes.

### Expectation over the dice

Accuracy is rolled once per (track, target), so gags of one track aimed at
one cog land or miss together. `_expected_over_rolls` enumerates every
combination of hit and miss over those roll groups, at most 16 for four
toons, and averages the leaf score with the probabilities the simulator
itself reports for each branch. They are read per branch because accuracy
is conditional: a landed Throw lifts a following Drop from 54% to 79%, and a
second Lure or a trapped target lifts a Lure from 79% to 95%. Branches less
likely than `MIN_LEAF_PROB` (0.001) are skipped and the rest renormalised.

### The score of one outcome

With "before" the state as given and "after" the state once the toon phase
has resolved:

$$\begin{aligned}
\text{score} ={}& \text{damage landed} + 2\cdot\text{laff restored} + 1\cdot\text{trap credit} + 120\cdot\text{kills} \\
&+ 9\cdot\text{prevented} + 400\cdot\text{survival rounds} - 1\cdot\text{gag price} - 1\cdot\text{spend price}
\end{aligned}$$

| Term | `QUICK_W` key | Weight | Definition |
|---|---|---|---|
| Damage landed | none | 1 | Health removed, capped at what each cog had, counting both layers of a Version 2.0 cog |
| Laff restored | `heal` | 2.0 | Healing capped at each toon's headroom, then reduced by the expected incoming damage (`HEAL_DISCOUNTS_INCOMING`, on) |
| Trap credit | `armed` | 1.0 | `TRAP_DISCOUNT` (0.6) × the trap's damage capped at the cog's health, for a trap laid this round, and only if some toon holds a Lure to spring it |
| Kills | `kill` | 120.0 | Cogs removed this round, a flat count |
| Prevented | `prevent` | 9.0 | Expected incoming damage removed; see below |
| Survival rounds | `survive` | 400.0 | Rounds of incoming damage the lowest toon's laff covers, capped at 4; see below |
| Gag price | `price` | 1.0 | Gags spent, in scorer units; see below |
| Spend price | `spend` | 1.0 | Pink slips and SOS cards; see below |
| Kill threat | `kill_threat` | 0.0 | Off |
| Waste | `waste` | 0.0 | Off; see [Negative results](#negative-results) |
| Risk | `risk` | 0.0 | Off |
| Deadline | `deadline` | 0.0 | Off |

A zero weight skips the computation.

**Prevented** (`party_search.prevented`) is built on a cog's expected damage
per round, its **threat**. A kill counts the cog's threat once. A cog newly
lured counts its threat times the rounds it will stay quiet, which is its
lure duration capped by how long the party takes to reach it: with
`SLEEPERS_WAKE_IN_TURN` on, the sleepers are ranked by remaining health and
the one in position $k$ gets $\max(1, k / \text{toons standing})$ rounds. A
cog already lured earns nothing more (`LURE_IS_SPENT_ON_SLEEPERS`). Killing
a lured cog counts only the part of its threat the lure was not already
covering (`LURED_KILL_SILENCES_NOTHING`). Waking a lured cog is charged the
quiet it would still have provided (`WAKE_COSTS_PREVENTED`). All four flags
are on.

**Survival rounds** (`party_search.survival_rounds`) is
$\min(4,\ \text{lowest standing laff} / \text{incoming})$. It is the only
term that reads laff as a level instead of a change. The incoming figure is
the expected damage of the board **before** the plan, so the term is the
same for every ordinary gag choice and cannot reorder them. It differs only
when a unite or an SOS card changes laff. When every cog is lured the
incoming figure would be zero, so the term uses what the field would deal
once awake (`LURE_IS_A_REPRIEVE`, on).

**Gag price.** One gag costs

$$\text{units} = \ell + \frac{20}{m} + 40\,[m \le 1], \qquad m = \min(\text{held},\ \text{carry limit})$$

where 20 is `SCARCITY_UNITS`, 40 is `LAST_COPY_UNITS`, and "held" is how
many the party holds now (`SCARCITY_USES_HELD_COUNT`, on). The total is
multiplied by $1 + 0.15 \cdot \text{cogs remaining}$. A group gag also pays
its wasted reach. For a fully trained Lure track with a full pouch this
gives 1.67, 2.80, 4.00, 5.33, 7.86, 12.67 and 67.00 for levels 1 to 7.

**Spend price.** A pink slip costs
`FIRE_PRICE` × cogs remaining + `FIRE_FLOOR` = $20 n + 120$. An SOS call
costs `SOS_PRICE` = 250, plus 250 times its wasted reach.

**Unites** are not part of the plan. `hybrid.climb` applies each candidate
unite to a copy of the state, plans on the result, and keeps the unite only
if the plan's score beats the plan without it by more than `UNITE_PRICE` =
200 (`unites.best_with_unite`).

### How `climb` uses it

`hybrid.climb` starts from the policy's most likely joint plan and changes
one toon's action at a time, keeping any change `_quick_score` prefers,
until a sweep changes nothing or a budget of scorer calls runs out. Each
toon is offered the policy's top `width` actions plus targeted extras: the
smallest gag that kills each cog, the cheapest Lure, every SOS card held,
and, when there is more than one toon or the policy's menu has collapsed
onto one kind of move, the best action of each track and the pass. The
defaults are `width` = 16 and `budget` = 24, and both panels pass 24. SOS
cards do not count against the budget.

## `_greedy_score` and `_cheap_score`

The sampling party search values a position by playing it forward with
`greedy_plan`, which picks each toon's action in turn. `_cheap_score` ranks
that toon's candidates by arithmetic alone; the top `GREEDY_SHORTLIST` (2)
plus up to `TRACK_PROBES` (3) from tracks not yet represented are then
simulated and scored by `_greedy_score`:

$$\text{score} = \text{damage landed} + 2\cdot\text{laff restored} + 60\cdot\text{kills} + 2\cdot\text{prevented} - 10\cdot\text{price} - 0.25\cdot\text{wasted damage}\cdot\text{scarcity}$$

Here the price is the **objective's** gag price (or $20 n$ for a pink slip,
with no floor), "wasted damage" is damage aimed past a cog's health, and
"scarcity" is the sum of $1/\text{carry limit}$ over the gags in the plan.

`_cheap_score` uses the same gag units as `_quick_score`, and: for an
attack, damage capped at health plus `CHEAP_KILL_BONUS` (60) per cog it
finishes; for a Lure, `CHEAP_LURE_VALUE` (25) per cog caught; for a Trap,
0.6 × its damage minus `LAFF_POINT_VALUE` (2.0) × the target's threat × the
rounds of the cheapest Lure held; for Toon-Up, 2.0 × the laff it can
restore; for a pink slip, the health removed plus 120 plus the cog's threat
minus $20 n$.

## The inventory: one concept, every price

| Concept | `Objective` | `_quick_score` | `_greedy_score` | `_cheap_score` |
|---|---|---|---|---|
| Killing a cog | No term; +100 for winning | 120 per cog | 60 per cog | 60 per cog for a gag, 120 for a pink slip |
| Laff lost | `laff_weight` (1.0; 3.0 `survive`; 0.25 `glass cannon`) | Not simulated | Not simulated | Not simulated |
| Laff restored | Through laff lost later | 2.0, less incoming | 2.0 | 2.0 (`LAFF_POINT_VALUE`) |
| Laff level | None | 400 × survival rounds | None | None |
| Damage prevented | Through laff lost | 9.0 × prevented | 2.0 × prevented | 25 per cog lured |
| A gag spent | `gag_cost`·level + `scarcity_cost`/limit | level + 20/limit + 40 if last, × 1.0 | Objective's price × 10 | level + 20/limit + 40 if last |
| Cogs still to come | `horizon_cost`, party path only | 0.15, taken from a default `Objective()` | Through the objective's price | None |
| Overkill | `waste_weight` × wasted fraction × scarcity, party path only | `waste` = 0.0 | 0.25 × wasted damage × scarcity | None |
| Wasted reach | Yes | Yes | No | No |
| Unsprung trap | None; the search plays the Lure | 0.6 × damage, if a Lure is held | None | 0.6 × damage minus the lure forgone |
| Pink slip | 0 | $20n + 120$ | $20n$ × 10 | $20n$ |
| SOS card | 10 | 250 | 0 (a card has no track, so the objective's gag price is zero) | 0 |
| Unite | 200, applied to the search's value | 200 | Not offered | Not offered |
| A round passing | `turn_cost` 1.0 | None | None | None |
| Losing a toon | `toon_lost_penalty` 0.0 | `risk`, `deadline` = 0.0 | None | None |

A fourth weight on overkill sits outside this table: the reinforcement
learning environment has a `--precision` reward term that multiplies the
same wasted-fraction measure (`party_search._waste_fraction`).

## Where two systems disagree

These are recorded, not resolved. Each number was measured as it stands,
and changing one invalidates the measurements made around it.

1. **A kill has three prices.** 120 in `_quick_score`, 60 in
   `_greedy_score`, and inside `_cheap_score` 60 for a gag kill but 120 for
   a pink-slip kill, so one function prices the same event on two scales.
2. **Overkill is priced three ways, and the PPO row sees none of them.**
   `waste_weight` is 20.0 in `balanced`, but `_quick_score` receives no
   objective from any shipped caller, so its `waste_penalty` branch is
   unreachable; the only charge left is `QUICK_W["waste"]`, which is 0.0.
   `_greedy_score` charges raw wasted damage, not the wasted fraction the
   other two use. The training reward's `--precision` is a third weight on
   the same quantity.
3. **Healing is three constants with one value.** `QUICK_W["heal"]`,
   `GREEDY_W["heal"]` and `LAFF_POINT_VALUE` are all 2.0 and are not
   linked. Sharing one weight was tried: raising it to 12 gained the PPO
   row a point and cost the party search two to three, because it made the
   simulated future passive.
4. **Prevention is 9.0 in one scorer and 2.0 in the other.** The 9.0 was
   re-swept after `prevented` was corrected; `GREEDY_W` was not refitted.
5. **Gag price has two currencies with a fixed exchange rate inside each.**
   The objective's ratio of level to scarcity is `gag_cost : scarcity_cost`
   (0.1 : 4.0 in `balanced`, and different in every preset); the fast
   scorers' is 1 : 20 always, plus a last-copy charge the objective does
   not have. The fast scorers price scarcity by what is held, the objective
   by the carry limit.
6. **The horizon scaling ignores the caller's objective.** `_score_leaf`
   builds a default `Objective()` only to read `horizon_cost`, so the
   scorer scales gag prices by 0.15 per cog whatever preset is selected.
   The exact search never applies the horizon at all, and inside the party
   search `evaluate` passes it while `rollout_value` does not.
7. **A pink slip is free to the objective.** The Search row's reward
   charges nothing for one. The scorers charge $20n$, and only
   `_quick_score` adds the floor of 120.
8. **An SOS card is 10 to the objective, 250 to `_quick_score`, and free in
   `_greedy_score`.** The first two are on different scales, so the numbers
   are not directly comparable, but neither was derived from the other.
9. **The unite price is one number on two scales.** `UNITE_PRICE` = 200 is
   subtracted from a `_quick_score` total in the PPO row and from an
   expectimax value, where a win is 100, in the Search row.
10. **The presets reach the engines unevenly.** The Search row uses the
    selected preset. The Playout row applies it relative to `balanced`. The
    PPO row ignores it: `_quick_score` has no objective, and the deeper
    judge it can optionally use hard-codes `balanced`.

## The leaf evaluator

At its depth cutoff the exact search scores a position with
`expectimax.heuristic_value`. That dispatches to a learned network if one is
switched on (it is off), then to the fitted linear model in
`solver/search/fitted.py`, then to a hand-written fallback,
$100 \cdot \text{cog progress} - 100 \cdot (1 - \text{laff kept})$.

The fitted model is a dot product over 18 features
(`solver/search/features.py`), clamped to
$[-100 - \text{max laff},\ +100]$ so the search's pruning bounds stay valid.
The weights are checked in as plain floats:

| Feature | Definition | Weight |
|---|---|---|
| `bias` | 1 | 17.08 |
| `laff_ratio` | Laff over maximum laff | 160.15 |
| `cog_hp_ratio` | Live cogs' health over all cogs' maximum health | −5.20 |
| `cogs_alive` | Count of live cogs | −10.77 |
| `gags_ratio` | Gags held over 20, capped at 1 | 10.01 |
| `killable_ratio` | Share of live cogs the best single gag would kill | 12.96 |
| `best_gag_over_weakest_cog` | Best single-gag damage over the weakest cog's health, capped at 2 | −11.65 |
| `incoming_ratio` | Worst-case damage of one round over maximum laff, capped at 2 | −206.74 |
| `one_hit_from_death` | 1 if that worst case reaches the lowest toon's laff | −9.27 |
| `lured_ratio` | Share of live cogs lured | 14.33 |
| `trapped_with_lure` | Trapped cogs, if a Lure is held | 0.04 |
| `trapped_without_lure` | Trapped cogs, if no Lure is held | −0.41 |
| `trap_damage_ratio` | Mean armed-trap damage over the cog's health, capped at 2, if a Lure is held | −0.45 |
| `has_group_gag` | 1 if a group gag other than Toon-Up is held | 2.20 |
| `laff_after_worst_ratio` | Laff left after a worst-case round, over maximum laff | −158.69 |
| `cog_hp_x_laff` | `cog_hp_ratio` × `laff_ratio` | 3.84 |
| `damage_budget_ratio` | Damage the pouch can still deal over remaining cog health, capped at 2 | 51.02 |
| `cannot_finish` | 1 if that budget is below the remaining health | −99.95 |

Several features are collinear, so individual weights should not be read
as effects; `incoming_ratio`, `laff_ratio` and `laff_after_worst_ratio`
move together, as do the three trap features. How the model was fitted,
what it was fitted against, and what was tried after it are in
[heuristic-learning.md](heuristic-learning.md).

With more than one toon the features pool over the toons still standing.
Those values are defined but not validated, and on a maxed team the
evaluator is saturated: over the successors of three plans on a maxed
four-toon position the leaf read 98.03, 98.96 and 96.73 while the plans
finished the fight 87%, 98% and 95% of the time. The party search uses
rollouts for that reason.

## Measurements behind the `QUICK_W` weights

Unless noted, runs are paired on identical seeds, "+a/−b" counts seeds that
flipped each way, and p-values are sign tests. "Difficulty" is a cog
building's difficulty, 1 to 9. The two boss fights that appear are the Vice
President (VP) and the Chief Executive Officer (CEO); a "side" is one side's
battle in a boss fight, and CEO "leftovers" are the cogs that survive its
banquet phase and join its second battle.

### `prevent` = 9.0

The weight was 2.0, fitted against a `prevented` that overstated Lure. After
the correction it was re-swept and confirmed on untouched seeds at 200 sides
a cell: the CEO with no leftovers went from 9.0% to 54.0% (p < 0.0001),
buildings from 66.0% to 67.0%, and the VP was unchanged.

A later study ranked candidate moves by `_quick_score` and by 16 independent
playouts each, at difficulty 9:

| `prevent` | Rank correlation | Picked the playouts' best | Share of the random-to-best gap captured |
|---|---|---|---|
| 4 | +0.269 | 49 of 99 | 38% |
| 6 | +0.418 | 69 of 96 | 80% |
| **9** | **+0.545** | **88 of 94** | **96%** |
| 12 | +0.516 | 91 of 97 | 97% |
| 18 | +0.514 | 92 of 98 | 97% |
| 30 | +0.478 | 94 of 99 | 97% |

All six misses at 9.0 were the same choice: a long group Lure on a fresh
three- or four-cog board where the playouts preferred group Sound. Lowering
the weight to fix them made the ranking much worse, so it stayed.

`WAKE_COSTS_PREVENTED` was measured at 200 sides a cell, off to on:
buildings 64.5% to 67.0% and 68.5% to 71.5% (p = 0.031), CEO with no
leftovers 69.5% to 73.0%, with two 54.5% to 61.5% (p = 0.038); pooled 76 up
and 33 down. `SLEEPERS_WAKE_IN_TURN` was neutral in ordinary play (88.0%
against 86.8%, p = 0.375) and decisive on a solo VP: at 16 cogs a round
93.0% against 66.5% (+58/−5), held out 85.0% against 67.5%, and at 20 cogs
a round 26.5% against 15.0% (+40/−17, p = 0.003).

### `survive` = 400

Without this term a heal that is not a gag scored nothing: a unite read
329.40 before restoring 80 laff and 329.40 after.

The first version read the incoming damage after the plan, which paid for
prevention a second time. On solo buildings at difficulty 8 that cost
ordinary play 26.0% to 10.0% and 27.0% to 14.5% at weight 400 (p < 0.001 on
both seed blocks). With the pre-plan figure, the same buildings read 26.0%
and 27.0% at every weight from 0 to 800, with no seed moved.

Solo VP at 12 cogs a round, 5 pink slips, 200 runs a cell, two seed blocks
(A / B). The unite columns assumed an unlimited
stock; the SOS column is bounded at one of each of the 29 cards:

| `survive` | Unites only | SOS only | Both |
|---|---|---|---|
| 0 | 35.0% / 31.5% | 27.0% / 24.5% | 35.0% / 31.5% |
| 100 | 73.5% / 66.0% | 27.0% / 24.5% | 73.5% / 66.0% |
| 200 | — / 91.5% | — / 33.5% | — / 92.0% |
| **400** | **95.0% / 92.5%** | **52.5% / 49.0%** | **96.0% / 93.0%** |
| 600 | — / 91.0% | — / 53.0% | — / 92.5% |
| 800 | 92.5% / 91.0% | 57.5% / 52.0% | 95.0% / 94.0% |

Both curves are plateaus. On unmaxed parties (mean training 4.65 of 7, 250
runs a cell) the shape repeated: 77.6% / 74.4% at 0, 86.0% / 84.4% at 200,
87.2% / 84.0% at 400.

That sweep assumed an unlimited stock, which exposed that a unite had no
stock at all. `ToonState.unites_held` now defaults to 0. With 5 unites and a
full book of 29 cards held, at `survive` = 400 and 120 runs a cell:

| Fight | Win | Unites per run | Cards per run |
|---|---|---|---|
| Difficulty 3 | 100% | 0.00 | 0.00 |
| Difficulty 5 | 100% | 0.15 | 0.00 |
| Difficulty 7 | 100% | 2.54 | 0.00 |
| Difficulty 9 | 42% | 4.88 | 1.16 |
| VP, 12 cogs a round | 93% | 3.48 | 0.17 |

Easy fights spend nothing without any rule exempting them. This is the
measurement the comment on `hybrid.OFFER_UNITES` refers to. `OFFER_UNITES`
and `OFFER_SOS` are both on.

### Consumable prices

`UNITE_PRICE` (200) and `SOS_PRICE` (250) are preferences (`[OWNER]`: both
are last resorts), not tuned values. Sweeping either for win rate has a
known answer, since cheaper consumables always clear more fights. With both
prices set to zero over 90 positions, the best gag alone beat an SOS card
alone by a median of 203 points and a unite plus that gag beat it by 841, so
the scorer already charges an SOS for the turn it takes. `SOS_PRICE` was
400; the 200-point gap to a unite charged that turn twice. On unmaxed
parties, 250 runs a cell: 88.8% at 250, 87.2% at 400 (+0/−4), 89.6% at 150
(+3/−1).

`FIRE_PRICE` = 20 per cog still to come. With slips free, a two-toon side
spent all ten on the CEO's first battle and reached the second holding 0.3.
A flat price helped with five banquet leftovers (38.0% to 49.5%, p = 0.008)
and hurt with none (88.5% to 82.0%, p = 0.021), because it also held slips
back in the last battle. The proportional price is neutral at zero leftovers
and positive but not significant at five (p = 0.22); it is directional, not
proven.

`FIRE_FLOOR` = 120 exists because a board built by the live panel usually
reports zero cogs to come, which made slips free there. 150 runs a cell,
then 200 held out, 5 slips and 5 unites held:

| `FIRE_FLOOR` | Slips at difficulty 3 | At difficulty 5 | Difficulty 9 win | VP win | VP slips |
|---|---|---|---|---|---|
| 20 | 0.63 / 0.58 | 1.16 / 1.12 | 63% / 66% | 95% / 95% | 4.89 / 4.88 |
| 60 | 0.00 / 0.00 | 0.12 / 0.15 | 65% / 70% | 94% / 94% | 4.69 / 4.66 |
| **120** | **0.00 / 0.00** | **0.03 / 0.05** | **65% / 67%** | **95% / 94%** | **3.96 / 4.03** |
| 200 | 0.00 | 0.03 | 53% | 85% | 2.93 |

On unmaxed parties: 89.2% at 20, 88.8% at 120 (+5/−6, p = 1.000), 85.6% at
200 (p = 0.035).

### `price`, `spend` and scarcity

`price` and `spend` were one multiplier, which the code comments call a
trapdoor instead of a knob. Lowering it to loosen gag thrift also made pink
slips and SOS cards free, cancelling `FIRE_PRICE`, `FIRE_FLOOR` and
`SOS_PRICE` in one move; a sweep that showed 0.0 beating
1.0 (91.6% against 88.0%, p = 0.022) was measuring unpriced consumables.
After the split, with consumables on:

| `price` | Win | Gags spent |
|---|---|---|
| 0.0 | 86.8% (+6/−9, not significant) | 15.5 |
| **1.0** | **88.0%** | **14.0** |
| 2.0 | 87.2% (+5/−7, not significant) | 11.9 |
| 4.0 | 82.0% (+4/−19, p = 0.003) | 10.4 |

A later sweep on a solo VP at 20 cogs a round (10 runs a cell) had 2.0, 4.0
and 8.0 clear 50%, 60% and 0% against 80% at 1.0, with no win gained in any
cell. `spend` at 0.0 wins more (92.4%, p = 0.003), which is the expected
answer and not a reason to change a preference.

`SCARCITY_UNITS` = 20 was swept at 0, 20, 60 and 150 with no win-rate
signal. The reason is leverage: the whole price term is a median 4.79% of
the score across 120 boards. Pricing by held count instead of carry limit
was neutral over 1,000 paired runs (+6/−10, p = 0.454) and spent 2.4% fewer
gags; it is on because nothing restocks a pouch mid-run, which is an
argument and not a measurement.

`LAST_COPY_UNITS` = 40 was added because a one-round scorer cannot see the
cost of spending the only copy of a gag. On the VP, values of 0, 40, 100 and
200 won 53.0%, 57.5%, 56.5% and 40.0% (200 is worse, p = 0.003); 40 was
confirmed on fresh seeds at 300 paired sides, 53.0% to 60.3% (+45/−23,
p = 0.010).

### Budget and width

`budget` counts scorer calls. The panel once passed 8, which stopped the
sweep before the targeted extras were reached. On unmaxed parties, 250 runs
a cell:

| Budget | Block A win | Block B win | Slips per run | Latency |
|---|---|---|---|---|
| 8 | 88.8% | 85.2% | 18.4 | 1.9 ms |
| 16 | — | 95.6% | 17.7 | 2.7 ms |
| 20 | 98.4% | 98.4% | 16.0 | 5.0 ms |
| **24** | — | **99.2%** | **14.5** | **7 ms** |
| 30 | 98.4% | — | 13.0 | 8.6 ms |

Every measurement in this section older than that change was taken at
budget 8, so those absolute win rates are lower bounds; the comparisons
between weights stand.

`width` was 3 and is now 16. At 3 the exact search's preferred move was on
the menu in 0 of 4 inspected positions, and at 16 in 4 of 4. On a solo VP
at 20 cogs a round, 40 held-out runs: 48% at width 3 against 75% at 16
(+15/−4, p = 0.019); buildings were unchanged. Width and budget are
coupled: a menu wider than the budget never reaches the extras appended
after it.

Most of these sweeps forced fully trained toons, where the accuracy cap
flattens differences between gags. `FIRE_FLOOR`, `SOS_PRICE` and `survive`
were re-run on the sampler's own parties, as quoted above, and all three
held.

## Negative results

**A learned plan ranker.** A policy head (called P0) was trained to rank
candidate plans for the party search's shortlist. On 375 held-out positions
its regret at six plans was 3.22 against 9.93 for the arithmetic ranking and
12.09 for random choice. In play it lost at every shortlist width:

| Shortlist width | Without it | With it |
|---|---|---|
| 8 | +88.06 | +87.29 |
| 16 | +89.34 | +87.29 |
| 30 | +89.34 | +87.29 |
| 60 | +89.72 | +88.29 |

The cause was label noise. The teacher estimated each plan from 16 samples
with a per-round spread near 31, a standard error near 7.8, while the median
gap between the best plan and the sixth was 3.54. The offline metric was
computed against the same noisy values, so it measured "avoids bad plans"
and could not see "picks the best plan". Ranking by the model alone also
dropped the known best line on a test position. The code was removed. Trying
again needs many more samples per plan in the teacher, not a larger network.
(The code comments disagree on whether the 9.93 belongs to `_cheap_score` or
`_quick_score`.)

**Charging for overkill in `_quick_score`.** `QUICK_W["waste"]` was swept
from 0 to 400 and stays at 0. It looked like a VP gain on selection seeds
(72 to 85 of 150, p = 0.092) and did not hold on 400 held-out seeds (186 to
195, p = 0.448; buildings 313 to 302). Charging waste pushes the scorer onto
gags that do not quite kill, so buildings used more gags (14.1 to 15.0).
The maintainer regards the resulting overkill as a real defect in the PPO
row's picks; the Search row under `balanced` is the path that prices it.

**Group gags on a lone cog.** No penalty was added. Over 150 runs a cell,
group gags were thrown at a single live cog 0, 1 and 1 times out of 659,
1,410 and 1,476.

**`risk` and `kill_threat`.** Both stay at 0. The first refutation of `risk`
measured nothing, because the feature returned zero on every sampled
position. After the fix it looked real on a selection sweep (900 positions,
p = 0.012 at weight 20, a plateau from 10 to 40) and did not replicate on
1,600 held-out positions (+0.1%, p = 1.000).

**A two-round judge.** Scoring a plan plus a greedy follow-up round
(`deep=True`, discounted by 0.7) finished 63.9% of 180 held-out buildings at
1.82 ms against 66.7% at 0.61 ms for the one-round score. It is off.

**Refitting all the weights at once.** `tools/fit_scorer.py` runs an
evolution strategy over the `QUICK_W` weights against fights won. It gained
on its fitting set and nothing on validation; see
[scorer-audit.md](scorer-audit.md).

**`_quick_score` as a ranker, and a retraction.** The ranking study above
first reported a rank correlation of +0.013. That was a harness bug: every
one of the 16 playouts was seeded identically. Corrected:

| Difficulty | Positions with a choice | Rank correlation | Picked the best | Win rate: best / scorer / random / worst |
|---|---|---|---|---|
| 5 | 3 | +0.696 | 3 of 3 | 1.000 / 1.000 / 0.990 / 0.938 |
| 7 | 13 | +0.701 | 13 of 13 | 1.000 / 1.000 / 0.977 / 0.923 |
| 9 | 94 | +0.545 | 88 of 94 | 0.991 / 0.987 / 0.887 / 0.755 |

Candidates there were the best move of each track. This is a one-round
question on single buildings; the next section gives a different answer for
long fights.

**Two harness failures worth knowing about.** Measurement scripts mapped an
action they could not express to "pass", so a harness failure looked like a
strategy failure; that produced four false results. A sweep script's
catch-all branch silently swept `SOS_PRICE` for every knob it did not
recognise; three claims were re-measured. `solver/rl/harness.py` now raises
on an action it cannot play.

Policy and observation experiments that used to be recorded here (a wider
observation, six retrained policies that were not promoted) are in
[experiment-log.md](experiment-log.md), which keeps the full text of every
section this document once had.

## What the playouts changed

The Playout engine plays each candidate move to the end of the fight many
times and compares outcomes. Three findings from building it bear on
everything above.

- **The one-round scorer must not choose what gets played out.** On a
  benchmark labelled by playouts, four random entries from `climb`'s menu
  beat the scorer's own top four (+0.92 against +0.70 cogs over an average
  candidate), and the best move lay outside the scorer's top four in 49% of
  positions. Building the playout menu for variety instead took a solo VP
  from 38 to 79 wins of 200 (+57/−16, p < 0.001).
- **Formulas fitted to playout labels failed in play.** Two attempts to fit
  a scoring formula to those labels took a solo VP from 7% to 3.6% and to
  0.4%. A label for one decision holds only while the old player plays the
  rest of the fight.
- **`_quick_score` keeps a supporting role.** `climb`'s pick and the
  scorer's top two are among the roughly ten candidates the playouts start
  from, and `climb` is the player the playouts use for parties.

The playouts score in their own units (cogs defeated plus a laff term) and
reuse two things from this document: the objective's gag price, to charge
for gags spent, and the selected preset, applied relative to `balanced` so
that `balanced` is exactly the measured engine.
