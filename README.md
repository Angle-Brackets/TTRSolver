# TTRSolver

A battle solver for [Toontown Rewritten](https://www.toontownrewritten.com/):
a simulator of the cog-battle rules, an expectimax search that plays them,
and a set of readers that can watch a live game and advise on the fight in
front of you.

It solves solo battles **exactly** — every action spends a gag, so the game
tree is finite and `expectimax.solve` plays a position to the end with no
heuristic at all. Party battles are searched approximately, because their
outcome space cannot be enumerated.

> **The [TTR wiki](https://toontownrewritten.wiki) is the source of truth.**
> The strategy guide this project started from describes *Toontown Online*
> and predates TTR's rebalancing passes; it has been caught wrong on Lure
> durations, Lure accuracy, which Lure levels are group gags, and the
> luredRatio rule. Everything in `solver/data/` has been audited against the
> wiki.

## The rule that shapes everything here

**A number that isn't confirmed is `None`, and the code raises rather than
substituting.** No plausible-looking fills, and when sources conflict the
cell stays open with a note on what looked wrong rather than being averaged
or guessed.

That sounds pedantic until you see what it catches. Toon-Up was modelled
healing the *thrower* — the rule exactly backwards, since
[the wiki says](https://toontownrewritten.wiki/Toon-Up) toons cannot heal
themselves. Group cog attacks weren't modelled at all, so parties took
strictly less damage than the game deals. Both were found because a search
produced advice a human looked at and said "nobody plays that."

Two things are deliberate exceptions, both tagged `[ASSUMED]` so they can
never read as data: the multi-Lure accuracy bonus, where the patch notes
give the magnitudes `(20/15/10)%` but never say which level gap selects
which; and the accuracy and frequency of twelve cog attacks that the wiki
confirms exist and publishes damage for, but never gives those two
columns. Nine of the twelve are group attacks, so leaving them unfired
understated cog threat — the exception is there because silence was the
worse error.

## Quick start

Standard library only — no install step.

```bash
python -m unittest discover tests      # ~700 tests
python -m solver.search.demo           # narrated solo fight
python -m solver.live.advise           # advise on a running game
```

Optional extras, each isolated so the core never depends on them:

```bash
pip install -r requirements-vision.txt     # numpy, for screen reading
pip install -r requirements-training.txt   # torch, for training only
```

## Layout

```
solver/
  state.py          BattleState / ToonState / CogState / Action
  mechanics.py      accuracy, damage, cog attacks, lure wake-up
  simulator.py      legal_actions() and step() -- samples
  outcomes.py       action_outcomes() -- enumerates, exactly
  party.py          party rules: pickup vs coordinated modes
  data/             game tables, one module per table, wiki-audited
  search/
    expectimax.py   exact solo search, star1/star2 pruning
    party_search.py sampled party search
    fitted.py       learned leaf evaluator (plain floats, stdlib)
    policy.py       trained policy head (needs numpy, optional)
    objective.py    what a round is worth -- the tunable weights
  live/             reading a running game (see below)
tools/              offline: label generation, fitting, training
docs/               findings, and what is not yet trustworthy
visualizer/         browser front end
```

## How the solver works: expectimax

### Why not minimax

Minimax assumes your opponent picks the move that hurts you most. Cogs do
not. A cog picks its attack from a **published frequency table** and rolls
to hit — it is indifferent to you, not hostile. Modelling cogs as an
adversary would produce advice braced against a worst case that only
happens 15% of the time, and would systematically over-value defence.

So the tree alternates two kinds of node:

- **MAX** — the toon chooses. Take the best branch.
- **CHANCE** — the dice choose. Take the *probability-weighted average* of
  the branches.

That is expectimax. It answers "what maximises my expected outcome",
which is the right question against an indifferent opponent.

### One round of the tree

A single round expands into three layers. The toon picks a gag, the gag
hits or misses, then every living cog attacks:

```mermaid
graph TD
    S["MAX<br/>toon to act<br/>62 laff, 2 cogs"]

    S -->|"Throw lvl 5"| A["CHANCE<br/>accuracy roll"]
    S -->|"group Lure"| B["CHANCE<br/>accuracy roll"]
    S -->|"Squirt lvl 4"| C["CHANCE<br/>..."]

    A -->|"hit&nbsp;&nbsp;p=0.83"| A1["cog 40→0 DEAD"]
    A -->|"miss p=0.17"| A2["no change"]

    A1 --> D["CHANCE<br/>cog phase"]
    A2 --> E["CHANCE<br/>cog phase"]

    D -->|"Bite&nbsp;&nbsp;p=0.50"| D1["MAX<br/>-8 laff"]
    D -->|"Chomp p=0.50"| D2["MAX<br/>-11 laff"]

    style S fill:#2d6a4f,color:#fff
    style A fill:#6a4c93,color:#fff
    style B fill:#6a4c93,color:#fff
    style C fill:#6a4c93,color:#fff
    style D fill:#6a4c93,color:#fff
    style E fill:#6a4c93,color:#fff
```

Green is a choice, purple is a roll. The value of a CHANCE node is the
weighted mean of its children; the value of a MAX node is the best child.
Recursion bottoms out when the battle ends.

### Why this terminates — and why it is exact

Here is the property that makes this project unusual: **solo battles are
solved exactly, with no heuristic at all.**

Every gag a toon throws is **spent**. The pouch only shrinks, so no line of
play can be longer than the number of gags carried, and no position can
repeat with the same pouch. The state graph is a **DAG**, not a cycle, and
the tree is finite:

```
round 1        pouch = 34 gags
round 2        pouch = 33 gags        strictly decreasing
round 3        pouch = 32 gags        ...so this must end
```

`expectimax.solve()` therefore plays to the end of the battle and returns
the *true* expected value of a position. Not an estimate. That is why the
learned evaluator in `fitted.py` can be trained on ground truth rather than
on its own predictions — a luxury most game AI does not have.

The one thing that could break the argument is the **pass** action, which
spends no gag. Passing is an ordinary choice — conserve a scarce gag, or
in a party decline to attack, since `pick_cog_target` makes a cog prefer
whoever damaged it most, so swinging pulls its next hit onto you. Given a
lone Wedding Cake and an 8hp cog, the exact solver passes rather than
spend it.

To keep the measure well-founded, an unlured pass draws on a small
budget (`state.free_passes`). Without one, the branch where every cog
*misses* leaves the state unchanged and the search recurses forever. So
the measure is `(gags, lure rounds, free passes)` lexicographically, and
still descends. A lured pass is free of the budget — the lure timer is
already the quantity going down.

### Three ways a battle ends

The third one is easy to forget and cost this project a real bug:

1. Laff hits zero.
2. Every cog is dead.
3. **The toon has no remaining way to damage a cog.** Nothing restocks a
   pouch mid-fight, so 80 Lures and no attacks is a *loss*, and so is
   Toon-Up plus Trap with no Lure.

Before (3) existed, hopeless positions fell through to the heuristic and
scored **+47.6** — and since training labels came from `solve()`, the
evaluator was partly fitted to its own optimism.

### Making it fast: star1 and star2 pruning

Alpha-beta does not apply directly, because a CHANCE node has no "best"
child to cut on. **star1** bounds it instead. If a chance node's children
must lie within `[L, U]`, then after seeing some of them you can bound the
whole node:

```
       seen so far          still unknown
     ┌───────────────┐   ┌─────────────────┐
     p1·v1 + p2·v2  +     p3·L ... p3·U        <- lower and upper bound
     └───────────────┘   └─────────────────┘

  if upper bound  <  alpha   ->  cut, this branch cannot win
  if lower bound  >  beta    ->  cut, opponent avoids it
```

This is why `fitted.value` is **clamped** into the range the bounds
promise, and why that clamp is a correctness requirement rather than
tidiness. Unclamped, the fitted model put **32% of positions outside the
envelope** — as high as 175 against a ceiling of 100 — and the search
quietly began cutting branches it had no warrant to cut.

**star2** adds a probe pass: try one child of each unseen branch first, and
if the probe already breaks the bound, skip the rest.

A transposition table catches the rest, since many action orders reach the
same position — `outcomes.state_key` keys on every toon **in order**,
deliberately, because a frozenset there would let the memo answer about one
party using another's value.

### Where it stops being exact

Parties. A party round's outcome space is the accuracy rolls (one per track
per target) times each cog's choice of attack, times its choice of *whom*
to hit, times the teammates' actions. That cannot be enumerated, so
`party_search` **samples** it — and its values are estimates that are not
comparable with `solve()`'s.

The invariant that catches most bugs there: **coordinated can never score
below pickup**, since coordinated may choose everything pickup may and
more. That inequality is what exposed a truncation quietly deleting the
best plan.


## Reading a live game

Two sources, both verified against a running client rather than from
documentation:

- **Local API** (`solver/live/ttr_local.py`) — official, opt-in via
  `"want-local-api"` in TTR's `settings.json`. Gives laff, gag tracks,
  organic, location, invasion. It does **not** expose the battle.
- **Screen reading** (`solver/live/vision.py`) — needs `"show-cog-levels"`
  on. Cog level, department and health come off the plate above each cog.
  This is the only route to the cogs.

`session.py` joins them into a `BattleState` and `advise.py` runs the solver
on it. `build_state` returns a state **or** the reasons there isn't one —
never a guess, because advice computed from an invented state is worse than
no advice.

## What the solver has found

Some of it was surprising, which is the point of building one:

- Against three level 10s and a level 11, four maxed toons, the best opening
  is **2 Foghorn + 2 Aoogah** — cheap mixed-level Sound, 159 damage against
  the 156 the toughest cog has. Sound emerged unprompted; nothing in the
  code knows what a Sound combo is.
- **Coordinated can never score below pickup**, since it may choose
  everything pickup may and more. That inequality has caught more party bugs
  than any test.
- A **wider damage margin** is not protection against the dice — gag damage
  is deterministic — it is protection against the model being wrong about
  training. A 10% shortfall breaks a 3-damage margin and not a 15-damage one.

`docs/party-strategy.md` has the numbers, and more usefully what they cannot
yet tell you.

## Machine learning

Two heads trained on searched positions — a **value** head (how good is this
position) and a **policy** head (which plans are worth searching). Both are
distilled from the search, not learned by reinforcement: for solo there is an
exact oracle to imitate, and for party the search is a cheaper teacher than
RL exploration would be.

The policy ranks plans about **3× better** than the hand-written heuristic
(regret@6 of 3.2 against 9.9, with random at 12.1) — and that number about
the *incumbent* is the more useful one, since a heuristic barely better than
random at choosing a shortlist is the mechanism behind most of this
project's silent-deletion bugs.

It is **off by default**, because wired in it made the search worse: the
policy's ranking is currently discarded before the final cut. Off until that
is fixed and re-measured. See `docs/ml-design.md`.

## Things worth knowing before trusting a number

- **Party values are estimates.** Exact `solve()` cannot reach a party
  position, so there are no labels to check against.
- **The objective's weights are chosen, not derived.** `laff_weight`,
  `scarcity_cost`, `turn_cost` and friends are swept and sane; nothing
  calibrates them against real play.
- **Pickup mode rests on a model of strangers.** `SensiblePrior` is a guess
  about how people play, labelled as one.
- **Six times a *reduction* has silently deleted the right answer** — a
  candidate cap, a lexicographic prefix, a global top-N, twice from the
  learned ranker. Each produced confident, plausible, wrong output. The
  habit that catches them is an invariant a truncation cannot satisfy by
  accident.

## Documentation

| | |
| --- | --- |
| [docs/data-confidence.md](docs/data-confidence.md) | every data gap, and why it is open |
| [docs/party-strategy.md](docs/party-strategy.md) | party findings, and their limits |
| [docs/ml-design.md](docs/ml-design.md) | the learning plan and its results |
| [docs/search-depth.md](docs/search-depth.md) | what depth is worth |
| [docs/roadmap.md](docs/roadmap.md) | what is next |

Not affiliated with Toontown Rewritten or the Walt Disney Company.
