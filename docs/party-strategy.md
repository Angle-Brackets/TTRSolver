# What a party should throw, and what we can and cannot tell yet

Notes from the first attempt to ask the solver a *strategic* question
rather than a mechanical one: given four toons and four cogs, what is
the best opening?

The short version. A recognisable Sound strategy came out unprompted,
including a variant better than the one it was being compared against.
Everything about Lure is still untested, for a structural reason worth
understanding before trusting any of this.

## The blind test

Four maxed toons — six tracks, no Toon-Up, pouches weighted to levels
4–7 — against three level 10s (132 hp) and a level 11 (156 hp).

Nothing in the code knows what Sound is. Every track gets the same
number of candidate slots, chosen within each track, and plans are
scored by playing the battle out and counting what it cost: won or
lost, laff spent, gags spent priced by `objective.BALANCED.gag_price`.

At 400 rollouts per plan:

| plan | score | laff | gag cost |
| --- | --- | --- | --- |
| **2 Foghorn + 2 Aoogah** | **189.5** | 3.0 | **7.5** |
| 1 Opera Singer + 3 Aoogah | 189.4 | 2.8 | 7.8 |
| 2 Foghorn + Elephant Trunk + Aoogah | 189.2 | 2.7 | 8.2 |
| 2 Aoogah + Lure + Wedding Cake | 188.9 | 3.2 | 7.8 |
| 2 Opera Singer | 188.3 | 1.8 | 9.9 |
| 2 Foghorn + 2 Elephant Trunk | 187.5 | 3.7 | 8.7 |
| 4 Foghorn | 186.8 | 2.2 | 11.0 |
| Lure + 3 Opera Singer | 180.7 | **0.1** | 19.2 |
| 4 Opera Singer | 176.6 | 3.6 | 19.8 |

The top four are within 0.6 of each other, which is close to noise even
at 400 samples. The finding is **cheap mixed-level Sound**, not one
particular mix. The gaps to 4 Foghorn (2.7) and to 4 Opera Singer
(12.9) are larger and look real.

Why it works: 2×50 + 2×16 = 132, and the same-track combo adds 20% of
the total, giving 159 against the 156 the toughest cog has. Four Opera
Singers deal 432 — the same kill, overkilling by 276, for two and a half
times the gag cost.

## Two things that decided the answer, and neither is a game rule

**Gag pricing.** Charged flat per gag, the winner was "spend two level
7s", which is not how anyone plays. Priced by scarcity — the solver's
own `gag_price`, which divides by how many fit in a pouch — the winner
became "four toons throw cheap Sound". Foghorn costs 2.60 against Opera
Singer's 4.70 because a toon carries two of one and one of the other.
The whole answer turns on that constant.

**Safety margin, which nothing values.** 2 Foghorn + 2 Aoogah clears by
**3** damage. 2 Foghorn + 2 Elephant Trunk clears by **15** and costs
1.00 more. The objective has no term for robustness, so it takes the
3-point line every time.

That is a real gap rather than a tuning detail. The 3-point margin is
exact only if every toon is maxed in Sound: Foghorn spans 25–50 across
the experience range and the model always uses the top. An experienced
player's preference for the wider margin is a preference for being
right when the model is slightly wrong, and the objective cannot
express it.

## Why no Lure strategy appeared

Two separate reasons, and the second is a limit of the experiment.

**Against a maxed team there is no round two.** Four Foghorns deal 240
to every cog and the toughest regular cog is a level 12 at 196, so four
maxed toons wipe *any* regular four-cog battle in one round. Lure buys
survival across rounds; where there are no further rounds it buys
nothing. `Lure + 3 Opera Singer` lost **0.1 laff** — essentially
untouched — and still finished ninth, because the damage it prevented
was damage nobody was going to take.

**And a one-ply search cannot find a multi-round plan.** Only the
opening round is chosen jointly; after that both sides play
`party.SensiblePrior`, a guess about individual players. Lure strategies
are nothing *but* sustained coordination — lure, focus the loose cog,
re-lure before it lapses — so a Lure opening is handed to a policy that
does not follow through, and the score measures the follow-through.

Run against an under-geared team (trained to 5, nothing above level 4,
60 laff, versus four level 9s) so that the fight lasts:

| plan | score | win% | rounds | laff |
| --- | --- | --- | --- | --- |
| 4 Aoogah | 98.7 | 97% | 4.8 | 81.2 |
| 2 Trap + group Lure + Throw | 81.3 | 96% | 7.8 | 88.8 |
| group Lure + 3 Throw | −10.0 | 82% | 8.4 | 127.4 |
| Lure left, kill right | **−97.1** | 69% | 9.6 | 163.7 |

Lure-left-kill-right finishing last is not a result about the game.
The plan that did well — Trap + group Lure — is the one whose payoff
lands *inside* the round it is set up in, so it survives a bad
continuation. LLKR needs three coordinated rounds and is given one.

**Nothing here is evidence for or against Lure.** Testing it needs
coordinated play sustained over a battle. The party tree search now
exists (`solver/search/party_search.py`) but does not yet settle this,
for the reason in the next section.

## What else is not trustworthy yet

* **The party evaluator is saturated, and this is now measured.**
  `fitted.value` is clamped to +100 and, with four maxed pouches pooled,
  `damage_budget_ratio` pins at its cap. Evaluating the successor states
  of three plans on the maxed position, 60 rollouts each:

  | plan | mean leaf | battles ended | cogs left |
  | --- | --- | --- | --- |
  | 2 trap + group lure + group throw | 98.03 | 87% | 0.53 |
  | 2 Foghorn + 2 Aoogah | 98.96 | 98% | 0.07 |
  | 4 Foghorn | 96.73 | 95% | 0.20 |

  A **2.3-point spread** across positions that differ by eleven points
  of "did you actually win". At depth 1 the leaf is a near-constant, so
  the ranking falls entirely to `round_reward` — laff and gag price —
  and the search cannot see a continuation at all.

  The leaf is therefore a rollout now, not the evaluator
  (`party_search.rollout_value`). A rollout cannot saturate, because it
  does not estimate: it plays to the end and adds up what happened. It
  is noisy and it measures value *under `SensiblePrior`* rather than
  under best play, which is a real limit — but a noisy signal beats a
  constant.

  Swapping the leaf changed almost nothing on its own, and that turned
  out to be the useful clue. See below. Every number here comes from playing
  the battle out instead. A party search must not lean on the evaluator
  until its features are refitted against party positions, and there
  are no party labels to refit against, because exact `solve()` cannot
  reach them.
* **The continuation policy is a guess.** `SensiblePrior` is a model of
  people, not a rule, and it decides every round after the first.
* **The scoring weights are chosen, not derived.** +200 to win, −200 to
  lose, laff at face value, gags at `gag_price`.
* **The position does not stress survival.** Every plan in the maxed
  trial won 100% of the time, so the ranking is decided by efficiency
  alone.

## The pattern worth remembering

Twice in this work a *reduction* quietly deleted the right answer.

Candidates were capped at two per track, so Sound only ever offered
levels 7 and 6 and the entire family of mixed-level Sound plans was
unreachable — including the one that won. The sweep reported "4
Foghorn" with total confidence and would have gone on doing so. It took
someone saying "there is a better line" to find it; `PER_TRACK` is 4
now.

The same shape as the cog-level reader, where padding two masks to the
top left instead of centring them turned a "Level 8" plate into a
confident 6. In both cases the machinery was right and the thing
feeding it was quietly wrong, and in both cases the output looked
entirely reasonable.


## The shortlist was deleting the answer, again

Swapping the saturated evaluator for a rollout leaf barely moved the
maxed position's answer. The reason it barely moved is that on that
position the battle **ends in round one** 87–98% of the time, so
`evaluate` returns at the terminal check and the leaf almost never
fires. The leaf was never the binding constraint.

The binding constraint was `plans()`. Asked for its shortlist on the
maxed position:

| | |
| --- | --- |
| `_quick_score` of 2 Foghorn + 2 Aoogah | **988** |
| `_quick_score` range of the 60 plans returned | **1081–1089** |
| all-Sound plans on the shortlist | **none** |

59 of the 60 were Lure+Trap combinations. The best known line was not
outranked by the search — it was **removed before the search could
sample it**.

`_quick_score` plays one round with *everything hitting*, and adds a
flat +25 per cog lured. Under that rule a group Lure never misses and
is charged nothing for the risk, so luring four cogs is +100 free and
Sound's reliability is invisible. The optimism is tolerable; the
optimism plus a global top-N cut is not.

The fix is the one `PER_TRACK` already encodes one level down: **give
each track family its own slots** rather than taking a global top-N.
That does not make `_quick_score` honest, it stops the dishonesty being
fatal — each family's best offering reaches the sampled evaluation and
is judged there.

Sound in the winning plan, six seeds per row, before and after:

| samples | before | after |
| --- | --- | --- |
| 16 | 0/6 | 6/6 |
| 48 | 0/6 | 6/6 |
| 96 | 0/6 | 6/6 |
| 160 | 0/6 | 6/6 |

The exact mix still wobbles between pure Sound, Lure+Sound and
Sound+Trap. That wobble is honest: the exhaustive sweep had its top
four lines within 0.6 of each other.

### Fourth time

This is now the fourth occasion in this work that a *reduction* quietly
deleted the right answer, and they all look identical in the output —
a confident, plausible, wrong recommendation:

1. `PER_TRACK = 2` — Sound offered only levels 7 and 6, so every
   mixed-level Sound plan was unreachable.
2. Mask padding to the top-left instead of centring — a "Level 8" plate
   read as a confident 6.
3. `max_plans` taking a lexicographic prefix — the first 60 joint plans
   were all arrangements of one Trap.
4. `max_plans` taking a *global* top-N over an optimistic score — one
   track family took all 60 slots.

The lesson each time: the machinery was right and the thing feeding it
was quietly wrong. Keep an invariant a truncation cannot satisfy by
accident — for (3) it was *coordinated ≥ pickup*; for (4) it is
`test_no_family_takes_more_than_its_share`.


## Rules the shortlist enforces, and one it wrongly enforced

`party_search._playable` refuses plans that waste a gag by construction.
Each rule below is a wiki fact, not a heuristic:

* **Two Traps on one cog** — a cog takes one trap.
* **Drop on a cog that is lured, or that this round's Lure will catch.**
  [CONFIRMED] TTR wiki (Lure): "Drop gags always miss on lured Cogs."
  Lure resolves before Drop, so the miss is guaranteed. Caught on a real
  recommendation where the Drop and the toon doing *nothing* left an
  identical board.
* **Lure in the same round as Sound.** [CONFIRMED] TTR wiki (Lure):
  "Lured Cogs are awakened by Sound gags without a damage bonus" — the
  Sound wakes what the Lure just caught and does not even collect the
  lured bonus. Niche uses exist; the plan is dominated by joining the
  Sound or throwing an attack gag.
* **The whole team holding** — legal, but cannot win, and nothing
  restocks a pouch.

### Stacked Lure is NOT one of them, and briefly was

A rule refusing a second Lure was added here by analogy with the Trap
rule, on the evidence that dropping one of two group Lures scored 8.6
better over 300 playouts. That evidence was real and the conclusion was
wrong.

[CONFIRMED] TTR wiki (Lure): *"Using multiple Lure gags simultaneously
increases the accuracy"*, and the update notes: *"Multiple Lure gags of
the same type used simultaneously now grant a bonus (20/15/10)% accuracy
depending on the gag level discrepancies of the additional Lure gags,
with the bonus being smaller if low-level Lure gags are used."*

Stacking Lure is a real TTR play. The playout said otherwise because
**the bonus is not modelled** (`mechanics.MULTI_LURE_ACCURACY_BONUS` is
`[TODO]`), so the second Lure was simulated as pure cost with none of
its benefit — the measurement faithfully reported a defect in the model
as a fact about the game.

The lesson is narrower than "measure things": a measurement taken
*through* a model can only be as true as the model. A playout is
evidence about the simulator first and the game second.

Stacked Lure is now searched at single-Lure accuracy, so it is
**undervalued but reachable**. That is the right way round — rejecting
it made a genuine play impossible to find.

## Holding, and why there is no "wasted gag" penalty

Toons may now hold (`None`). Without it the search made a toon on an
already-winning board throw Toon-Up at a teammate on **full laff**,
because a cheap wasted heal was the least bad thing it was allowed to
say.

No separate waste penalty was added and none is needed: `round_reward`
already charges `objective.gag_price` for whatever is spent, so once
holding is available a gag that achieves nothing is strictly worse.
Adding a penalty on top would double-charge, and would need a number
nothing in the game supports.

This is *not* `simulator.legal_actions`' pass, which stays deliberately
narrow to protect the solo search's termination argument. This search is
depth-limited and sampled and has no such argument to protect.

## Does it insist on winning in one round?

No, and nothing in the objective asks it to. `BALANCED` has
`turn_cost = 0.0` — only `SPEEDRUN` charges per round. The pressure
toward a one-round wipe is that **every extra round gives the cogs
another turn to hit you**, and that laff shows up in `round_reward` at
face value. That is a real cost, not an artificial preference for speed.

What *does* bias against multi-round plans is the horizon. Only the
first round is chosen; everything after it is `SensiblePrior`, a guess
about people. A plan whose payoff lands two rounds later is handed to a
policy that will not follow through, and then scored on the
follow-through. This is the same root cause as the Lure problem and it
is not fixed by tuning weights — it needs a deeper coordinated search.

## Reproducibility

Seeded runs were not reproducible: `rng` reached only
`mechanics.pick_cog_target`, while `roll_hit`, `accuracy_roll`,
`pick_cog_attack`, the cog damage ranges and the lure wake-up all drew
from the **global** `random`. Two runs of an identical seeded call gave
different plans, which quietly undermines every A/B comparison made
against it.

All of them take an `rng` now, defaulting to the global module so
existing callers are unchanged. The same seed gives the same plan and
the same value across processes.
