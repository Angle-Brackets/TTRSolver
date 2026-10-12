# What a party should throw, and what can and cannot be concluded

This document records what TTRSolver has found about battles with more
than one toon: which openings scored best in simulation, how the party
search behaves, and what the later Playout engine measured in group and
boss fights. It is equally a record of what those results cannot tell
you. As of 2026-10-11 the battle rules are party-aware and several
findings are measured in simulation, but none has been validated against
real play, the party evaluator is saturated, and no result about Lure is
trustworthy.

Game terms (laff, lure, trap, knockback, organic, VP) are defined in
[mechanics-notes.md](mechanics-notes.md#terms). Source tags are defined
in [data-confidence.md](data-confidence.md).

## How to read this document

Every statement here is one of three kinds, and they should not be
confused.

| Kind | Meaning |
| --- | --- |
| Measured in simulation | A number from playing simulated battles. It is evidence about the simulator first and the game second. The simulator's cog attack frequency and accuracy are unverified for TTR ([data-confidence.md](data-confidence.md)). |
| Maintainer's judgement | An `[OWNER]` statement: how an experienced player says the game is played or should be played. Not a measurement. |
| Open | Not known. Said plainly where it applies. |

Headline findings, by kind:

| Finding | Kind |
| --- | --- |
| For four fully trained toons against four high-level cogs, cheap mixed-level Sound was the best one-round opening. | Measured in simulation (August 2026) |
| The wider damage margin an experienced player prefers protects against the toons being less trained than assumed, and that is measurable. | Measured in simulation |
| The party evaluator cannot tell good party positions apart on a strong team. | Measured |
| Whether Lure strategies are good or bad for a party. | Open |
| Planning a party's round jointly beats each toon planning alone, on a hard simulated VP. | Measured in simulation |
| Guessing what unseen teammates hold gains nothing; knowing it would gain a little. | Measured in simulation |
| One toon on one side of a two-player VP is hard in the simulator. The maintainer calls that fight trivial. | Measured, and contradicted by the maintainer's judgement. The gap is open. |
| What strangers in a pickup group actually throw. | Open. The model of them is a guess. |

**The early trials have not been re-run.** The sections from "The first
trials" through "The rollout continuation" date from 14 August 2026.
Since then the simulator gained the twelve cog attacks TTR added in
4.0.0 (15 August) and the rule that any landed attack, not only Sound,
wakes a lured cog (21 August). Their numbers are reported as recorded.
The rule change bears directly on any plan that hits lured cogs, which
is one more reason to distrust the Lure rows.

## Two ways to treat teammates

`solver/party.py` has two modes. Which is right is a question about the
players, not about the search.

- **Pickup** (`Mode.PICKUP`): you control one toon. The other toons are
  a chance event, like the cogs' attacks. Their actions are sampled from
  a model of what teammates tend to do.
- **Coordinated** (`Mode.COORDINATED`): every toon's action is chosen
  together. This is the only way to reach the plays that make
  coordinating worthwhile, such as stacking one track on a cog for the
  same-track damage bonus, or holding a Trap for someone else's Lure.

Using the wrong mode gives bad advice in both directions. Searching
teammates as choices you do not have produces "throw a level 1, my
teammate will throw a level 7 into the same cog". Modelling a
coordinated team as a distribution throws away the reason they
coordinated.

**The teammate model is a guess.** `party.SensiblePrior` is a model of
people: it assumes a teammate spends as little as possible, avoids
overkill, values a kill above damage and treats Lure as damage
prevented. Nothing in the wiki or any source can confirm what a stranger
throws. Every pickup-mode number rests on it. `party.NetTeammate`, which
asks the rollout network what to throw from the teammate's seat, is a
guess of the same standing. The interface takes a distribution so that a
model fitted from real play could replace either.

### The party search

`solver/search/party_search.py` searches a party position: it maximises
over your action (pickup) or the team's joint action (coordinated) and
takes an average over everything else.

It samples instead of enumerating. A party round's outcomes are the
accuracy rolls, times each cog's choice of attack, times its choice of
target, times the teammates' actions. So its values are estimates, and
they are **not comparable** with the exact solo search's values.

One invariant catches most bugs in it: coordinated can never score below
pickup, because a coordinated team may choose everything a pickup player
may, and more.

### What is party-aware and what is not

- **The rules are party-aware.** The end conditions, the pooling of gags
  for "can anyone still damage a cog", cog target selection, group cog
  attacks and the shared accuracy roll are all written for a team. See
  [mechanics-notes.md](mechanics-notes.md).
- **The evaluator's party features are defined, not validated.** They
  pool laff and gags over the toons still standing. Solo feature vectors
  are unchanged by this, which keeps the fitted weights valid for solo
  positions. For party positions there are no labels to check against,
  because the exact search cannot reach them. Treat any party number the
  evaluator produces as untested.
- **The TTR live readers see one toon.** The game's Local API reports
  the player's own laff and training. Teammates are a count. On Realms
  the stream does carry teammates, and only the playouts and the PPO row
  use them.

## The first trials: one-round openings

The first strategic question asked of the solver: given four toons and
four cogs, what is the best opening?

### The blind test

Four fully trained toons, six tracks each with no Toon-Up, pouches
weighted to levels 4 to 7, against three level 10 cogs (132 health) and
a level 11 (156 health). Nothing in the code knows what Sound is. Every
track got the same number of candidate slots, and each plan was scored by
playing the battle out: won or lost, laff spent, gags spent at the
objective's price.

At 400 rollouts per plan:

| Plan | Score | Laff lost | Gag cost |
| --- | --- | --- | --- |
| **2 Foghorn + 2 Aoogah** | **189.5** | 3.0 | **7.5** |
| 1 Opera Singer + 3 Aoogah | 189.4 | 2.8 | 7.8 |
| 2 Foghorn + Elephant Trunk + Aoogah | 189.2 | 2.7 | 8.2 |
| 2 Aoogah + Lure + Wedding Cake | 188.9 | 3.2 | 7.8 |
| 2 Opera Singer | 188.3 | 1.8 | 9.9 |
| 2 Foghorn + 2 Elephant Trunk | 187.5 | 3.7 | 8.7 |
| 4 Foghorn | 186.8 | 2.2 | 11.0 |
| Lure + 3 Opera Singer | 180.7 | 0.1 | 19.2 |
| 4 Opera Singer | 176.6 | 3.6 | 19.8 |

The top four are within 0.6 of each other, which is close to noise at
400 samples. The finding is **cheap mixed-level Sound**, not one
particular mix. The gaps to 4 Foghorn (2.7) and to 4 Opera Singer (12.9)
are larger and look real.

Why it works: 2 × 50 + 2 × 16 = 132, and the same-track bonus adds 20%
(27, rounded up), giving 159 against the 156 the toughest cog has. Four
Opera Singers deal 432, the same kill with 276 to spare, at two and a
half times the gag cost.

### Two things decided the answer, and neither is a game rule

**Gag pricing.** Charged a flat amount per gag, the winner was "spend
two level 7s", which is not how anyone plays. Priced by scarcity, using
the objective's own `gag_price`, the winner became "four toons throw
cheap Sound". A Foghorn costs 2.60 against an Opera Singer's 4.70,
because a toon carries two of one and one of the other. The whole answer
turns on that pricing, which is chosen, not derived.

**Safety margin.** 2 Foghorn + 2 Aoogah clears by 3 damage. 2 Foghorn +
2 Elephant Trunk clears by 15 and costs 1.00 more. The objective has no
term for robustness, so it takes the 3-point line every time. See
[The safety margin](#the-safety-margin) below.

### Re-measured with group cog attacks

The table above predates group cog attacks, when a party took less
damage than the game deals. Re-run on the same board, 400 playouts, all
plans winning every time:

| Plan | Score | Laff lost | Rounds |
| --- | --- | --- | --- |
| **2 Foghorn + 2 Aoogah** | **89.3** | 2.4 | 1.04 |
| 2 Foghorn + 2 Elephant Trunk | 88.3 | 2.4 | 1.04 |
| 4 Foghorn | 85.7 | 2.4 | 1.04 |
| 1 Opera Singer + 3 Aoogah | 83.0 | 2.4 | 1.04 |
| Lure + 3 Opera Singer | 65.0 | 0.6 | 1.05 |
| 4 Opera Singer | 53.3 | 2.4 | 1.04 |

The ordering survives. The scores are not comparable with the first
table: that one paid 200 for a win and this one pays 100.

## What the trials cannot tell you

### The party evaluator is saturated

The fitted evaluator's value is clamped at +100, and with four full
pouches pooled its damage-budget feature sits at its cap. Evaluating the
positions three plans led to on the board above, 60 rollouts each:

| Plan | Mean evaluation | Battles ended | Cogs left |
| --- | --- | --- | --- |
| 2 Trap + group Lure + group Throw | 98.03 | 87% | 0.53 |
| 2 Foghorn + 2 Aoogah | 98.96 | 98% | 0.07 |
| 4 Foghorn | 96.73 | 95% | 0.20 |

A 2.3-point spread across positions that differ by eleven points of
"did the battle actually end". On a strong team the evaluator is close
to a constant.

The party search therefore does not use it. Its leaf is a rollout
(`party_search.rollout_value`): it plays the battle to the end and adds
up what happened. A rollout is noisy and it measures value under the
rollout policy, not under best play, but it cannot saturate.

**A party search must not lean on the evaluator** until its features are
refitted against party positions, and there are no party labels to refit
against.

### Why no Lure strategy appeared

"No Lure strategy ever appears" in these trials, for two separate
reasons. The second is a limit of the experiment, not a fact about the
game.

**Against a fully trained team there is no second round.** Four Foghorns
deal 240 to every cog and the toughest street cog, a level 12, has 196
health. Four such toons clear any ordinary four-cog battle in one round.
Lure buys survival across rounds; where there are no further rounds it
buys nothing. Lure + 3 Opera Singer lost 0.1 laff and still finished
near the bottom, because the damage it prevented was damage nobody was
going to take.

**A one-round search cannot find a multi-round plan.** Only the opening
round was chosen jointly. After it, the rollout played a fixed policy.
Lure strategies are sustained coordination: lure, focus the loose cog,
re-lure before the lure lapses. A Lure opening was handed to a
continuation that did not follow through, and the score measured the
follow-through.

A trial against an under-geared team (trained to level 5, nothing above
level 4, 60 laff, against four level 9 cogs), so that the fight lasts:

| Plan | Score | Won | Rounds | Laff lost |
| --- | --- | --- | --- | --- |
| 4 Aoogah | 98.7 | 97% | 4.8 | 81.2 |
| 2 Trap + group Lure + Throw | 81.3 | 96% | 7.8 | 88.8 |
| Group Lure + 3 Throw | −10.0 | 82% | 8.4 | 127.4 |
| Lure the left cogs, kill the right | −97.1 | 69% | 9.6 | 163.7 |

The last row finishing last is not a result about the game. The plan
that did well, Trap plus group Lure, is the one whose payoff lands
inside the round it is set up in, so it survives a bad continuation. The
last plan needs three coordinated rounds and was given one.

**Nothing here is evidence for or against Lure.** Testing it needs
coordinated play sustained over a battle.

### Other limits of these trials

- **The continuation policy.** Every round after the first was played by
  a fixed policy: first `SensiblePrior`, later `greedy_plan` (see
  below). Neither is good play.
- **The scoring weights are chosen.** Win bonus, loss penalty, laff at
  face value, gags at `gag_price`.
- **The position does not stress survival.** Every plan on the
  fully trained board won every time, so the ranking was decided by
  efficiency alone.
- **A measurement taken through a model is only as true as the model.**
  A playout once scored a plan with two group Lures 8.6 points below the
  same plan with one, and that was taken as evidence that stacking Lure
  is bad. This document then explained the result away by saying the
  multi-Lure accuracy bonus was not modelled. That explanation was
  wrong: the bonus is modelled, and only its size is `[ASSUMED]`.
  Whatever the 8.6 points mean, they do not mean that.

## What a deeper search found

Run at depths 2 and 3 with the branching trimmed so that it finishes:

| Position | Depth 1 (three seeds) | Depth 2 | Depth 3 |
| --- | --- | --- | --- |
| Healthy street group | +94.36 / +93.91 / +93.82, three different plans | +93.97 / +94.68 | +94.63 |
| Battered team against tough cogs | +91.82 / +91.69 / +91.47 | +93.31 / +93.13 | +93.73 |

- **Where the fight ends in one round, depth buys nothing.** The three
  depth-1 seeds on the healthy position disagree on the plan while
  landing within 0.54 of each other. That is a tie being broken by
  noise.
- **Where the fight lasts, depth was worth about 1.5 points**, and both
  depth-2 runs returned the same plan: trap one cog, group Lure to
  spring it and catch the rest, then Throws for the knockback bonus.
  That is a recognisable Toontown line arrived at by search. It is one
  position, measured before the lure-waking rule changed, and it is not
  a general result about Lure.

Two of the depth-1 seeds on the battered position also agreed on a plan
containing two Lures in one round.

## The safety margin

The 3-point margin of 2 Foghorn + 2 Aoogah is exact only if every toon
is fully trained in Sound. A Foghorn's damage runs from 25 to 50 with
training, and the model uses the top. An experienced player's preference
for the wider margin is a preference for being right when the model is
slightly wrong.

**It is not a risk-aversion problem.** `objective.risk_aversion`
penalises the spread of a plan's sampled returns. It was swept at 0.1,
0.25, 0.5 and 1.0 and left at 0.0, because it changed nothing. The two
plans it was meant to separate have identical spread:

| Plan | Mean | Standard deviation | Cleared |
| --- | --- | --- | --- |
| 2 Foghorn + 2 Aoogah (clears by 3) | 85.87 | 31.20 | 96% |
| 2 Foghorn + 2 Elephant Trunk (clears by 15) | 84.87 | 31.20 | 96% |

They must. Gag damage in the model is deterministic, so all the variance
in a round is accuracy: the Sound lands and both plans kill, or it
misses and neither does. The margin protects against the model being
wrong about a parameter, not against the dice.

**It can be measured another way.** `mechanics.DAMAGE_TRAINED_FRACTION`
sets where every toon sits in a gag's damage range (1.0 is fully
trained). Re-running the two plans at lower values:

| Trained fraction | 2 Foghorn + 2 Aoogah | 2 Foghorn + 2 Elephant Trunk |
| --- | --- | --- |
| 1.00 | clears | clears |
| 0.95 | clears | clears |
| 0.90 | fails | clears |
| 0.80 | fails | clears |
| 0.60 | fails | fails |

A 10% shortfall in training breaks the 3-damage line, and the 15-damage
line survives to 20%. The objective still cannot express the preference,
and prices the cheaper line higher. But the cost of being wrong is now a
number.

(When this knob was first added it appeared to show a damage bug: a
cog died although the gags accounted for too little damage. The party
damage path was not reading the knob. The simulator had been dealing
correct damage all along; the instrument was wired into one path and not
the other.)

## Rules the plan shortlist enforces

`party_search._playable` refuses plans that waste a gag by construction.
It refuses what cannot work, never what merely might not.

| Refused | Reason | Source |
| --- | --- | --- |
| Two Traps on one cog | A cog takes one trap. Two single-target Traps in one round cancel. | `[OWNER]` |
| Drop on a cog that is lured, or that this round's Lure will catch, with no Sound in the plan | Drop always misses a lured cog, and Lure resolves before Drop. | `[CONFIRMED]` |
| Lure in the same round as Sound | Sound wakes what the Lure caught and collects no bonus. Niche uses exist; the plan does not earn a slot on a short list. | `[CONFIRMED]` rule; the exclusion is a search choice |
| Toon-Up when every other standing toon is at full laff | A toon cannot heal itself, so the gag does nothing. | `[CONFIRMED]` |
| Every toon passing | Legal, but it cannot win and only gives the cogs a free turn. | Search choice |

Two things it deliberately allows:

- **Two or more Lures in one round.** A rule refusing a second Lure was
  added by analogy with the Trap rule and was wrong. The wiki says
  multiple Lures thrown together raise accuracy. Stacking Lure is a real
  play and the search must be able to find it. See
  [mechanics-notes.md](mechanics-notes.md#multi_lure_accuracy_bonus--the-best-documented-assumed-value).
- **Drop after Sound.** Sound resolves before Drop and wakes lured cogs,
  so a Drop on a lured cog can land if a Sound in the same round hits.
  It is a gamble: if the Sound misses, so does the Drop.

**Holding.** A toon may hold (pass). Without that option, the search
made a toon on an already-winning board throw Toon-Up at a teammate on
full laff, because a cheap wasted gag was the least bad thing it could
say. No separate penalty for a wasted gag was added: the round's reward
already charges the gag's price, so once holding is available a gag that
achieves nothing is strictly worse.

**A symptom that survives a correct fix has a second cause.** The
full-laff Toon-Up advice survived three real fixes: adding the hold
option, correcting a clamp that let a heal on a full toon absorb the
round's damage, and redirecting heals to teammates as the wiki requires.
The position's value did not move by 0.01 across any of them. The fix
that worked was refusing the no-op outright.

## Objective settings that were tried

All of these live in `solver/search/objective.py`. All are chosen, not
derived from the game.

| Setting | Value | What happened |
| --- | --- | --- |
| `turn_cost` (charge per round) | 1.0 by default, 2.0 in the speedrun preset | At 0, a party that had just lured the board could hold for free. Toons held 0.75 times a round at 0, 0.38 at 1.0 and 0.00 at 2.0 on one uneven board. 1.0 was kept because holding is sometimes right. |
| `waste_weight` (charge for overkill) | 20 in the balanced preset, 0 by default | Changed the plan in 48% of 60 random party positions. For a group gag, waste is counted once against the toughest cog it must kill, not per cog: a group gag's spread is not a choice. Charged per cog, 2 Foghorn + 2 Aoogah was billed 84 wasted damage and lost its own win. |
| `rare_gag_premium` (extra charge for level 7) | 6.0 in the balanced preset | Sweeping it changed nothing at first, because the better plan was missing from the shortlist. After the shortlist fix, level 7 use on the fully trained board fell from 2 of 8 seeds to 0 of 8. |
| `toon_lost_penalty` | 0.0 | Swept at 25, 50 and 90 with no change in the plans. Losing a toon costs only their remaining laff in the reward; the gap is real, and this setting did not close it. |
| `risk_aversion` | 0.0 | No effect, for the reason in the previous section. |

**A setting that does not move the answer is a diagnostic.** Four times
a flat response to a sweep meant the setting could not reach the
decision. Twice that exposed a bug, and twice a question asked in the
wrong units.

The single-battle horizon also biases against multi-round plans. The
pressure toward a one-round clear is real: every extra round gives the
cogs another turn. But a plan whose payoff lands two rounds later is
scored on a continuation that will not follow through. That is the same
root cause as the Lure problem, and tuning weights does not fix it.

## Five reductions that deleted the right answer

Five times in this work, something that narrowed the candidates removed
the best line before the search could score it. Each produced confident,
plausible, wrong output.

1. `CANDIDATES_PER_TRACK` was 2. Sound offered only levels 7 and 6, so
   every mixed-level Sound plan, including the one that won, was
   unreachable. It is 4 now, and candidates are capped per track, not
   overall.
2. The cog-level reader padded two masks to the top left instead of
   centring them, and read a "Level 8" plate as a confident 6. (A
   screen-reading bug, listed because it has the same shape.)
3. `MAX_PLANS` took the first 60 joint plans in enumeration order. They
   were all arrangements of one Trap. The check that exposed it was
   coordinated scoring below pickup.
4. `MAX_PLANS` then took a global top 60 by an optimistic one-round
   score. One track family took almost every slot: 59 of 60 were
   Lure-and-Trap combinations, and the best known Sound line was not on
   the list. Each track family now gets its own slots
   (`test_no_family_takes_more_than_its_share`). Sound appeared in the
   winning plan in 0 of 6 seeds before and 6 of 6 after, at every sample
   count tried.
5. `QUICK_SCORED_PER_TRACK`, added as an optimisation, kept the first 40
   combinations per family in enumeration order, which again dropped 2
   Foghorn + 2 Aoogah. Each family is now ranked by arithmetic before it
   is cut. The optimisation's own benchmark had looked clean, because it
   measured time.

The lesson each time: the machinery was right and the thing feeding it
was quietly wrong. Keep a check that a truncation cannot satisfy by
accident.

A related lesson came from `GREEDY_SHORTLIST`, the number of candidates
the rollout policy simulates before choosing. On one position, rollout
quality was identical at 1, 2, 4 and 6, which suggested the simulation
could be dropped. On a position with uneven cog health, 1 scored 91.88
against 93.42 for 2 and above. It is set to 2. A measurement that does
not vary can mean the test cannot see the effect.

## The rollout continuation

`SensiblePrior` was once doing three jobs: predicting pickup teammates,
playing out the rest of each rollout, and ordering gag levels within a
track. Only the first is a job for a model of people. A rollout exists
to estimate what a position is worth under good play, not under average
play, and a Lure opening handed to a policy that would not follow
through was being scored on that failure.

`party_search.greedy_plan` now plays the rollout: each toon in turn
takes the best action it can see one round ahead under the objective,
with later toons seeing what earlier ones chose. On an under-geared
four-toon position, mean rollout value over five seeds was 7.60 under
`SensiblePrior` and 21.49 under `greedy_plan`, at about three times the
cost.

That does not validate the party numbers. A greedy, one-round policy is
still not good play. It removes the specific failure where the
continuation was worse than the plan being tested.

## Later findings: the Playout engine in groups

The Playout engine (`solver/search/playout.py`) judges about ten
candidate moves by playing each to the end of the fight. Its group
behaviour and the measurements below date from October 2026. All of
them are simulation results.

### Group modes

`playout.GROUP_MODE` selects how a board with teammates is played out.

- `"coordinated"` (the default): the candidates are joint plans for the
  whole party. The advice is your part of the best joint plan, on the
  assumption that the teammates play theirs.
- `"pickup"`: the candidates are your moves only, and the teammates are
  sampled from the teammate model each round. The teammate model is a
  guess, as above.

In a party, a toon's pass stays on the menu. That is how one toon
conserves gags while a teammate covers a cog (`[OWNER]`). A lone toon is
offered the pass only when nothing else is productive.

Party positions reached inside a playout are played on by the one-round
engine, which plans every seat. The fast rollout network is trained on
solo decisions only.

### Boss fights

A VP is 20 cogs a round in all (`[OWNER]`): alone, 20 cogs and then 20
Skelecogs; with company the toons split across two sides and each side
faces 10 and then 10.

| Fight (simulated) | Result | Kind |
| --- | --- | --- |
| 40 party VPs at the solo count (20 + 20 per side), planning the party together | 23 won | Measured |
| The same 40, each toon planning alone | 0 won | Measured |
| A two-toon side at 10 + 10, either way of planning | 40 of 40 won | Measured |
| One toon on a side at 10 + 10, light SOS, no pink slips or unites: one-round engine | 6 of 60 won | Measured |
| The same: Playout engine | 33 of 60 won | Measured |
| The same: exact-search row | 6 of 60 won | Measured |
| The same fight in the game | "Trivial" | Maintainer's judgement |

Three things to take from this.

**Planning together matters when the fight is hard**, and not when it is
easy. The 23-to-0 result was at twice the cog count a party side really
faces. At the real count a two-toon side won every time either way.

**Only the playouts see the later waves.** On the one-toon side the
Playout row won 33 of 60 where the exact-search row won 6, because the
search sees the cogs on the field and nothing behind them. The panel
therefore leads with the Playout row in boss fights unless the player
has picked an engine.

**The simulator disagrees with the maintainer about the one-toon side.**
Every traced loss there died to the Skelecogs with most of the pouch
unthrown. The maintainer calls the fight trivial. That gap points at the
model's cog damage or attack rate, which rest on unverified frequency
and accuracy tables, and not at the search. It is open.

### Unseen teammates: guessing gained nothing

On TTR the solver knows how many teammates are in the battle and nothing
about what they carry. A natural idea is to fill in stand-in teammates
and plan around them. It was measured on 300 simulated party buildings,
with the teammates actually playing `SensiblePrior`:

| What the Playout row was given | Buildings won of 300 |
| --- | --- |
| The count of teammates only | 120 |
| The real teammates | 131 (p = 0.04) |
| Stand-ins with the real pouches and training | 129 |
| One fixed guess at the teammates (`party.assumed_teammates`) | 110 |
| A guess redrawn every rollout (`party.drawn_teammates`) | 120 drawn from the building's own street, 119 drawn from a street matching the player's laff |

- **Knowing the teammates helps a little**, and all of the gain is in
  their pouch and training. Their real laff adds about nothing (114
  against 110 of 300).
- **One fixed guess is worse than no guess.** It is a specific wrong
  teammate, and the playouts plan around gags nobody holds.
- **A guess redrawn per rollout ties with the count.** Averaging over
  unseen teammates is what the count already does.

So the stand-in teammates are switched off in the TTR panel, and the
feature is shelved. The only lever left is evidence of what these
particular teammates hold, and it is worth at most about 11 buildings in
300. Both stand-in functions are guesses about people and are labelled
as such in the code.

This measurement has its own limit: the simulated teammates played
`SensiblePrior`. It says what knowing a `SensiblePrior` teammate is
worth, not what knowing a real one is.

## Open questions

- **Is Lure good for a party?** Not answerable from a one-round search
  with a fixed continuation, and the early Lure trials predate the rule
  that attacks wake lured cogs.
- **What do pickup teammates throw?** `SensiblePrior` is a guess. No
  model has been fitted from real play.
- **Why is the one-toon VP side hard in the simulator?** Cog damage and
  attack rate are the suspects.
- **Do the August results still hold?** They have not been re-run since
  the simulator changed.
- **How should robustness be valued?** The objective has no term for a
  damage margin or for bounding a bad outcome. The trained-fraction knob
  measures the cost of a thin margin and does not make the search prefer
  a wide one.
- **Party evaluation.** There are no exact labels for party positions,
  so the evaluator cannot be refitted or checked for them.
