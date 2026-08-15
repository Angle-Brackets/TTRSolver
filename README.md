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

Exactly one value in the project is a deliberate exception, tagged
`[ASSUMED]` so it can never read as data: the multi-Lure accuracy bonus,
where the patch notes give the magnitudes `(20/15/10)%` but never say which
level gap selects which.

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
