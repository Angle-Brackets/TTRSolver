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

No — but `turn_cost` used to be `0.0` for every mode except `SPEEDRUN`,
and the *second* half of that was the problem. At zero the objective
asks neither for speed nor against stalling, so a party that has just
lured the board can hold, spend nothing, and burn a round of the lure
for free. That is what "overly cautious" looked like on the uneven
board: three toons holding behind a group Lure.

`turn_cost` now defaults to **1.0** on the dataclass, so every mode
charges for a round unless it overrides upward. Measured on that board,
toons held 0.75 times per round at 0.0, 0.38 at 1.0 and 0.00 at 2.0 —
1.0 rather than 2.0 because holding is sometimes genuinely right, and a
charge that abolishes the option trades one bad default for another.

The rest of the original note still stands: The pressure
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


## SensiblePrior had three jobs and deserved one

It was doing all of these, and only the first is a job for a model of
*people*:

1. **Predicting pickup teammates.** Legitimate and irreducible — you
   cannot control a stranger, so the right object is a distribution over
   what they might throw. `SensiblePrior` keeps this.
2. **Playing out the rollout.** Wrong. Nothing is being *predicted*
   here: the rollout exists to estimate what a position is worth, and a
   position is worth what it is worth **under good play**, not under
   average play.
3. **Ranking levels within a track in `candidates`.** A shortlist
   heuristic; harmless, since it only orders levels inside one track and
   never decides which track wins.

Job 2 is the one that mattered, and it is the mechanism behind "no Lure
strategy ever appears". A Lure opening's payoff arrives two rounds later
and was being handed to a policy that would not follow through — then
scored on the follow-through. The plan was not being rejected, it was
being *sabotaged by its own continuation*.

`party_search.greedy_plan` now plays the rollout: for each toon in turn,
the best action it can see one round ahead under the objective the
search is actually optimising, with later toons seeing what the earlier
ones chose so the team does not pile four gags onto a corpse. Greedy and
myopic, and still far better than a guess about strangers.

Measured on an under-geared four-toon position, mean rollout value over
five seeds:

| rollout policy | value | cost |
| --- | --- | --- |
| `SensiblePrior` (people-model) | 7.60 | 0.1s |
| `greedy_plan` | **21.49** | 0.3s |

Three times the cost for a policy that plays about three times better,
which is the right trade for a value estimate.

**This does not make the party numbers validated.** The rollout is still
an estimate under a myopic policy, and a greedy policy is not a good
one — it just clears the specific failure where the continuation was
actively worse than the plan being tested.

## Charging for waste, and why `scarcity_cost` was not enough

`scarcity_cost` prices a gag by how few fit in a pouch. What it cannot
see is whether the gag was *needed*: a Railroad costs 4.70 whether it
was the only thing that would kill the cog or a 120-damage answer to a
cog with 8 hit points left.

`objective.waste_weight` charges the difference, computed as plain
algebra rather than simulated — damage aimed at a cog minus the hit
points it has, when positive. (Totalled per (track, target) first,
because `calc_hp_bonus` gives same-track gags on one cog a combo bonus
on their combined total; summing gags independently would understate
both.) The charge scales with the wasted gag's scarcity, so throwing
away a level 7 costs far more than throwing away a level 1.

The "unless it is the only option" case falls out of the arithmetic
instead of being special-cased:

| gag | target | wasted |
| --- | --- | --- |
| level 7 Throw (120) | 8hp cog | **112** |
| level 7 Throw (120) | 132hp cog | **0** |
| level 1 Throw (6) | 8hp cog | 0 |

Over 60 random party positions the plan changes in **48%** of them and
level 7 choices fall from 5 to 3. Checked that it nudges rather than
bans, the same check `scarcity_cost` got: given only a level 6 (100) and
a level 7 (120) against a 110hp cog, the level 7 is still chosen —
there the overkill really is only 10.

### The group-gag correction

The first version charged waste per cog, and that was wrong in a way
worth keeping written down. A group gag's damage is **uniform by
construction** — the overkill it does to a weak cog is not a choice
anyone made, it is what a group gag *is*. Billing for it punishes
exactly the Sound lines the game is built around.

Charged per cog, 2 Foghorn + 2 Aoogah — sized within 3 damage of the
toughest cog — was billed **84** wasted damage and priced out of its own
win: the maxed position stopped returning it and answered Geyser + Lure
+ Trap at +88.05 instead.

What a player actually chooses about a group gag is *how big a one to
bring*, and the binding constraint is the toughest cog it must kill. So
group waste is counted once, against that:

| plan | dealt | wasted | penalty |
| --- | --- | --- | --- |
| 2 Foghorn + 2 Aoogah | 159 | **3** | 0.13 |
| 4 Foghorn | 240 | 84 | 5.28 |
| 4 Opera Singer | 432 | 276 | 26.67 |

That is the exhaustive sweep's ordering, and the maxed position returns
2 Foghorn + 2 Aoogah again at +93.07. Single-target waste stays per cog,
because over-investing in one cog *is* the choice being made.

`waste_weight` is **chosen, not derived**, like every weight in
`objective`. It is consumed only on the party path: the solo search's
labels come from `solve()` under this objective and `fitted.py`'s
weights were fitted against those labels, so wiring it into
`step_reward` would silently invalidate the fitted evaluator.


## What depth found, and the bug underneath it

Run at depth 2 and 3 with the branching trimmed so it terminates:

| position | depth 1 (s=128, 3 seeds) | depth 2 | depth 3 |
| --- | --- | --- | --- |
| healthy street group | +94.36 / +93.91 / +93.82, **three different plans** | +93.97 / +94.68 | +94.63 |
| battered vs tough | +91.82 / +91.69 / +91.47 | **+93.31 / +93.13** | +93.73 |

Two clean readings:

* **Where the fight ends in one round, depth buys nothing.** The healthy
  position's three depth-1 seeds disagree completely while landing
  within **0.54** of each other. At that position the search is not
  choosing, it is tie-breaking on variance, and no amount of depth fixes
  a genuine tie.
* **Where the fight lasts, depth is worth about 1.5 points.** The
  battered position gains consistently at depth 2, and both depth-2
  settings return the *same plan*: trap one cog, group Lure to spring it
  and catch the rest, then Throws collecting the +50% lured bonus. That
  is a recognisable Toontown line arrived at by search.

Depth-1 seeds 1 and 2 on that position also agree exactly, on a plan
containing a **stacked Lure** — the play banned two commits earlier and
restored once the wiki was checked.

### Three fixes that were all real and none of which was the bug

Digging deep was worth more for what it exposed than for the numbers. A
party at **full laff** kept being advised to open with Toon-Up. The
symptom survived:

1. **Adding the hold option** — which made a no-op heal *equal* to
   holding rather than worse.
2. **Fixing the heal/damage clamp.** `min(max_laff, laff + healed -
   lost)` let a heal thrown at full laff absorb the round's damage. Real
   bug; does not bite when nobody is hurt.
3. **Redirecting the heal to teammates.** [CONFIRMED] TTR wiki: *"Toons
   cannot use Toon-Up gags to restore their own laff."* The model
   credited every heal to the thrower — the rule exactly backwards. Real
   bug; on a full-laff party it replaces one no-op with another.

The position's value did not move by **0.01** across any of them. The
actual fix was to refuse the no-op outright, like a Drop on a lured cog:
a heal with nobody to heal is not a cheap move, it is not a move. The
healthy position then went from +93.56 (with Toon-Up) to **+94.63**
without it — agreeing with what depth 2 and depth 3 had already found.

The lesson worth keeping: *a symptom that survives a correct fix is
evidence of a second cause, not of the fix being wrong.* Each of those
three was independently correct, and stopping at any of them would have
left the advice broken.

### Knock-on

Toon-Up now heals zero for a solo toon — there is nobody else in the
battle — so it is a spent gag rather than a self-heal. `solve()` values
move wherever Toon-Up appears, and `search/fitted.py`'s weights were
fitted against those labels. **Refit before relying on their
calibration.**


## Drop after Sound is a real play

The rule refusing Drop on a lured cog was too strong. [CONFIRMED] TTR
wiki (Lure): *"Lured Cogs are awakened by Sound gags"*, and
`ATTACK_ORDER` puts SOUND before DROP — so a Sound this round un-lures
the cog in time for the Drop to land on it. Every Sound gag is a group
gag, so one anywhere in the plan covers every cog.

It is a gamble rather than a guarantee: a Sound that misses leaves the
cog lured and the Drop misses too. That is the line `_playable` draws —
it refuses what **cannot** work, never what merely might not. Banning
Drop-after-Sound was the same category of error as banning stacked Lure.

## Making it fast enough to go deep

Profiled on a real battered-party position at depth 1, `samples=64`:

| | before | after |
| --- | --- | --- |
| whole search | 22.5s | **9.6s** |
| `_greedy_score` calls | 117,352 | 53,508 |
| `plans()` | 7.2s | *off the profile* |
| `apply_party_round` calls | 188,648 | 75,882 |

Wall clock on the two study positions: depth 1 at `samples=128` went
8.1s → 2.1s and 12.4s → 7.1s; depth 2 at `plans=16` went 19.4s → 8.8s
and 45.3s → 18.4s.

Two changes, and both are the same idea — **rank by arithmetic, simulate
only the survivors**:

* `plans()` was running a simulated `_quick_score` on *every* playable
  combo, ~50k of them, and then throwing almost all of the results away
  in the truncation. It now collects first and scores at most
  `SCORE_BUDGET` per track family. Per family, not globally, for exactly
  the reason the truncation is per family.
* `greedy_plan` was simulating a full round for every candidate of every
  toon on every round of every rollout, to pick one action. It now
  pre-ranks with `_cheap_score` — pure arithmetic — and simulates only
  the best `GREEDY_SHORTLIST`. The simulation, which knows about
  knockback, trap triggers and combo bonuses, still decides between the
  finalists.

`_cheap_score` gives Lure and Trap explicit credit rather than scoring
them zero for dealing no damage. A damage-only pre-rank would have
quietly deleted the Lure strategies for the fifth time.

**The cost is real and small.** Values came down by roughly 0.3–0.4
(battered depth 2: +93.31 → +92.96), which is inside the noise the same
position shows across seeds. Plan *shapes* are unchanged — depth 2 still
returns trap-one-cog, group-Lure, lured-Throws.

Remaining time is 73% in `greedy_plan`, split between `_greedy_score`
and `candidates`.

### The next obvious win was not one

`candidates` looked like the thing to cache or cheapen: 20k calls
rebuilding the same shortlists. Letting `greedy_plan` rank within a
track by `_cheap_score` instead of by `SensiblePrior` skips rotating the
state and running the prior, and the profile duly fell 9.6s → 8.8s.

On the wall clock of both study positions it bought **nothing** —
2.2s against 2.1s, 7.0s against 7.1s, 18.4s against 18.4s — while
dropping the battered position's depth-1 values by about 0.4. Reverted.
The prior orders the levels of a track better than damage arithmetic
does, which is the job it is still there for, and an 8% profile
improvement that does not show up in wall clock is not an improvement.

What *did* pay was smaller and duller: `_greedy_score` priced its action
by diffing every toon's whole gag dictionary against a probe, to
rediscover a fact the caller already had about a trial where one toon
throws one gag.

### How much the simulation was worth

Sweeping `GREEDY_SHORTLIST` on the battered position:

| shortlist | rollout quality | search | time |
| --- | --- | --- | --- |
| 1 | 74.88 | +91.84 | 3.51s |
| 2 | 74.88 | +91.49 | 4.12s |
| 4 | 74.88 | +91.53 | 5.25s |
| 6 | 74.88 | +91.32 | 6.30s |

Rollout quality is *identical to two decimal places* at every setting,
and search values stay inside their own seed-to-seed spread, while cost
rises steadily. Measured separately, `_cheap_score`'s pick agrees with
the simulation's on **288 of 328** decisions (88%) — the simulation is
mostly confirming the arithmetic.

Set to **2**, not 1 — and checking more positions is what settled it,
against the conclusion the single-position sweep invited. Adding how
often the plan actually differs between k=1 and k=4:

| position | plans differ | k=1 | k=2 | k=4 | k=6 |
| --- | --- | --- | --- | --- | --- |
| maxed vs 4 big | 0/6 | 87.17 | 87.17 | 87.17 | 87.17 |
| midgame vs 3 | 9/14 | 75.35 | 74.49 | 74.49 | 74.49 |
| weak vs 2 (long) | 0/17 | 88.35 | 88.35 | 88.35 | 88.35 |
| **mixed cog hp** | **5/5** | **91.88** | **93.42** | 93.42 | 93.42 |

`k >= 2` is identical everywhere, so nothing above 2 is worth paying
for. But **k=1 loses 1.54** on the mixed-hp position, where the plan
differs every single time. Uneven cog health is exactly where choosing
between two similar-damage options matters, and exactly where
arithmetic that cannot see knockback or trap triggers goes wrong.

The flat 74.88 was an artefact of a position where the shortlist never
changes the plan at all. **A measurement that does not vary is not
evidence that the thing does not matter — it can equally mean the test
cannot see it.** Dropping the simulation entirely, which that sweep
suggested and which would have been the larger speedup, would have been
a real regression.


## A fifth truncation, this one self-inflicted

Player feedback on four sample positions said the maxed team should not
be spending a level 7. It was doing so in **9 of 10 seeds**, and the
line it preferred was worse on both things the objective already
measures:

| line | gag price | wasted damage |
| --- | --- | --- |
| Opera7 + Foghorn6 (chosen) | 7.30 | 12 |
| 2 Foghorn + 2 Aoogah | 6.80 | 3 |

An `objective.rare_gag_premium` was added for it — level 7s are
pouch-exempt and restocked on a different scale, which `scarcity_cost`
cannot express because `1/max_carry` saturates. Sweeping it changed
**nothing**: level 7 in 5/8 seeds at premium 0, and 5/8 at 4, 8 and 14.

That flat response is the tell. The premium was working perfectly —
`round_reward` took the level 7 plan from +92.70 to +72.70 — and the
plan still won, because **2 Foghorn + 2 Aoogah was not on the shortlist
at all.** No objective term can reach a plan that is not a candidate.

The cause was `SCORE_BUDGET`, added while optimising: it kept the first
40 combos per stratum, which is a **lexicographic prefix** — the same
bug `max_plans` had, reintroduced one level down, deleting the same
line. `combinations_with_replacement` reaches every combo built from
Sound 7 before it reaches [Foghorn, Foghorn, Aoogah, Aoogah].

Fixed by ranking each stratum with `_cheap_score` — pure arithmetic, no
simulations — and scoring only the best `SCORE_BUDGET` of them. With
that in place:

| premium | level 7 in plan | most common plan |
| --- | --- | --- |
| 0.0 | 2/8 | SO4 SO4 SO6 SO6 |
| 4.0 | **0/8** | SO4 SO4 SO6 SO6 |
| 6.0 | 0/8 | SO4 SO4 SO6 SO6 |

`SO4 SO4 SO6 SO6` is 2 Foghorn + 2 Aoogah. Most of the correction was
the shortlist fix, not the premium; the premium finishes it. Set to 6.0,
and it nudges rather than bans — on a toon at 12 laff where only a level
7 kills the cog, the level 7 is still chosen at premium 0, 6 and 20.

### The count is now five

`PER_TRACK = 2`; top-left mask padding; `max_plans` lexicographic prefix;
`max_plans` global top-N; and now `SCORE_BUDGET` lexicographic prefix.
Every one produced confident, plausible, wrong output. The newest was
introduced by an optimisation whose own benchmark looked clean, because
the benchmark measured *time* and the plans it compared happened not to
be the ones that were lost.

## Losing a toon costs only their remaining laff

Feedback on the survival position was that Toon-Up should have been
thrown as insurance against the Lure missing. Checking, `round_reward`
charges a toon dropping 6 laff to zero exactly six points — there is no
term for losing a **combatant**, their pouch, and every action they
would have taken.

`objective.toon_lost_penalty` exists for it and is **left at 0.0**.
Swept at 25, 50 and 90, Toon-Up usage on that position stayed at 2/8
seeds — the plan kills all three cogs in the round, so no toon goes sad
in the sampled outcomes and the term rarely fires. The gap is real; this
lever does not close it, and shipping a weight that changes nothing
measured would just be decoration.

What the feedback is actually asking for is **variance reduction** — pay
a gag to bound the downside if the Lure misses — and an expected-value
search does not want that by construction. That is the same missing
robustness term already recorded above for the 3-damage Sound margin.


## Re-measured with group cog attacks

Every number above predates group cog attacks, when a party took
strictly less damage than the game deals. Re-run on the maxed board,
400 playouts, all plans winning 100%:

| plan | score | laff | rounds |
| --- | --- | --- | --- |
| **2 Foghorn + 2 Aoogah** | **89.3** | 2.4 | 1.04 |
| 2 Foghorn + 2 Elephant Trunk | 88.3 | 2.4 | 1.04 |
| 4 Foghorn | 85.7 | 2.4 | 1.04 |
| 1 Opera + 3 Aoogah | 83.0 | 2.4 | 1.04 |
| Lure + 3 Opera Singer | 65.0 | 0.6 | 1.05 |
| 4 Opera Singer | 53.3 | 2.4 | 1.04 |

The ordering survives. Absolute scores are not comparable with the
original table — that one paid +200 for a win and this pays +100 — but
cheap mixed-level Sound is still first and 4 Opera Singer still last.

## Why the safety-margin gap is not a risk-aversion problem

`objective.risk_aversion` penalises the spread of a plan's sampled
returns. It is implemented, swept at 0.1 / 0.25 / 0.5 / 1.0, and left
at **0.0**, because it changes nothing: the maxed board keeps choosing
the same Sound levels and the survival board keeps throwing Toon-Up in
2 of 6 seeds either way.

Measuring why was worth more than the term. The two plans this was
supposed to separate —

| plan | mean | **stdev** | cleared |
| --- | --- | --- | --- |
| 2 Foghorn + 2 Aoogah (clears by 3) | 85.87 | **31.20** | 96% |
| 2 Foghorn + 2 Elephant Trunk (by 15) | 84.87 | **31.20** | 96% |

— have *identical* spread, and they must. Gag damage in this model is
deterministic: `calc_toon_damage` interpolates at
`trained_fraction=1.0`, so a maxed toon always deals exactly max. All
variance in a round is therefore **accuracy** variance — the Sound
lands and both plans kill, or it misses and neither does. The margin
never gets a chance to matter.

So the wider margin is not protection against the dice. It is
protection against the **model being wrong about the damage** — a toon
not quite maxed, or the interim `trained_fraction` standing in for
experience thresholds nobody has transcribed. That is uncertainty about
a *parameter*, not spread in an *outcome*, and no weight over sampled
returns can express it.

That makes four objective levers now — `toon_lost_penalty`,
`rare_gag_premium` (before the shortlist fix), `risk_aversion`, and
`turn_cost` on position 2 — where a flat response to a sweep meant the
lever could not reach the decision. **A knob that does not move the
answer is a diagnostic, not a failure.** Twice it exposed a bug; twice
it exposed a question that was being asked in the wrong units.

Closing this one properly means either transcribing the minE/maxE
experience thresholds so damage varies with real training, or searching
against a deliberately pessimistic damage assumption and comparing the
two answers.


## Searching against a pessimistic damage assumption

`mechanics.DAMAGE_TRAINED_FRACTION` is the global stand-in for where a
toon sits in a gag's damage range (1.0 = fully trained). It is a knob so
a search can be run against a pessimistic assumption and the answers
compared, which is the only way to ask *how much does this
recommendation depend on everyone actually being maxed* — the question
behind a player's preference for a wide damage margin, and one no
amount of outcome variance can answer.

The recommendation turns out to be **stable**: at fractions 1.0, 0.9 and
0.8 the search returns the same Sound mix.

### ⚠ An unresolved discrepancy, found while checking that

Dropping the fraction did not stop the plan clearing the board, and it
should have. Resolved directly against a single level-11 Loan Shark
(156hp), all four gags forced to hit:

| fraction | gag damage | sum | hpBonus | total | cog ends at |
| --- | --- | --- | --- | --- | --- |
| 1.0 | 50, 50, 16, 16 | 132 | 27 | 159 | 0 |
| 0.9 | 48, 48, 16, 16 | 128 | 26 | 154 | 0 |
| **0.6** | **40, 40, 15, 15** | **110** | **22** | **132** | **0** |

At 0.6 the gags account for 132 damage against a 156hp cog and the cog
dies anyway. There is no Lure in the round, so no knockback bonus and no
luredRatio; nothing legitimate explains the extra 24.

So `apply_party_round` deals more damage than the gags in it account
for, at least for stacked same-track group gags. **This is a live bug
and it inflates every party damage number in this document**, including
the re-measured table above. Reproduction is the three lines in the
table: build one level-11 cog, four toons with Sound, throw
`[6, 6, 4, 4]` as group gags with `hits=[True] * 4`, and compare the
cog's hp against `sum(calc_toon_damage(...)) + calc_hp_bonus(sum, 4)`.

Suspects worth checking first: whether `calc_hp_bonus` is being added
once per gag instead of once per target, and whether the group
expansion applies each gag's damage more than once per cog.
