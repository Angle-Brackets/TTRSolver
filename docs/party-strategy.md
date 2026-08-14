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
coordinated play sustained over a battle, which is the party tree
search that does not exist yet.

## What else is not trustworthy yet

* **The party evaluator is saturated.** `fitted.value` is clamped to
  +100 and, with four maxed pouches pooled, `damage_budget_ratio` pins
  at its cap — so nearly every plan evaluates to exactly the ceiling
  and it cannot rank them at all. Every number here comes from playing
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
