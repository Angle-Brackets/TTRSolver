# TTRSolver — Toontown solo-toon-vs-cogs solver

A Markov-state battle simulator for a single toon fighting a group of cogs,
plus an expectimax solver that plays it. Cog attack tables for all four
departments are transcribed from source; the remaining gaps are listed in
[docs/data-confidence.md](docs/data-confidence.md) and every one of them
raises rather than guessing.

## Layout

```
solver/
  state.py          BattleState / ToonState / CogState / Action
  mechanics.py      accuracy formula, damage, cog attacks, lure wake-up
  simulator.py      legal_actions(state) and step(state, action) -- samples
  outcomes.py       action_outcomes(state, action) -- enumerates, exactly
  search/
    expectimax.py   depth-limited expectimax over outcomes.py
    demo.py         narrated fight; --compare vs. a random policy
  data/             hand-entered game tables, one module per table
    accuracy.py       toon accuracy formula components
    gags.py           gag damage min/max by (track, level)
    cogs.py           cog HP formula + department registry
    bossbot.py        \
    sellbot.py         }  cog freq / damage / accuracy, 8 cogs each
    cashbot.py         /
    lawbot.py         /
  testing.py        clearly-labeled synthetic stand-ins for TODO data
  demo.py           random-policy baseline run
tests/              unittest suite
docs/
  data-confidence.md  what's confirmed vs. unverified, and the tagging rules
  roadmap.md          prioritized next steps
visualizer/         standalone React artifact: lazy expectimax tree explorer
```

## Running it

No dependencies beyond the standard library. From the repo root:

```
python -m unittest discover tests                    # 85 tests
python -m solver.search.demo                         # solver plays a fight
python -m solver.search.demo --compare --scenario pressed
python -m solver.demo                                # random-policy baseline
```

On the `pressed` scenario — a mixed Bossbot group (Flunky L4, Pencil
Pusher L5, Yesman L6) against a 45-laff toon with a tight gag supply —
100 fights per policy:

| policy | win rate | mean laff left |
| --- | --- | --- |
| random | 45% | 12.3 |
| expectimax (depth 2) | 98% | 29.6 |

The default `two_flunky_fight` scenario is *not* useful for this: every
policy wins it ~100% of the time, so it can't distinguish anything. If you
add a benchmark, make sure it's a fight that can actually be lost.

**One caveat on those numbers.** Cog tables are real, but Lure duration is
still `[TODO]`, so the runs above use
`solver.testing.synthetic_lure_durations()` — a made-up flat 3 rounds.
Anything the solver concludes *about Lure specifically* rests on that
number; the rest doesn't. See
[docs/data-confidence.md](docs/data-confidence.md).

## Ground rules

Carried over from the original design chat, and they matter more than the
code does:

- **Don't fill a `[TODO]` with a plausible-looking guess.** If a number
  isn't confirmed from the source repo (or a second corroborating source),
  leave it tagged `[TODO]` and make the code raise rather than silently use
  a fabricated value.
- **When a source contradicts itself, don't split the difference.** If a
  figure looks inconsistent with the surrounding pattern (Throw L6, Sound
  L5, and Micromanager's `brain_storm` accuracy have all hit this), leave
  it `[TODO]` with a note on what looked wrong rather than picking the
  "more plausible" number.
- **Delete a stand-in the moment its real data lands.** A synthetic value
  that outlives its gap stops being scaffolding and starts overwriting good
  data with bad — which is worse than having no stand-in at all. This
  already happened once with `synthetic_bossbot_accuracy()`.

## Where to start

[docs/roadmap.md](docs/roadmap.md) item 1: find a source for per-gag-level
**Lure duration**. It's the last gap that blocks a whole track from
resolving at all, and the only one that currently changes what the solver
concludes. The strategy guide doesn't have it — this needs decompiled
source or the TTR wiki.
