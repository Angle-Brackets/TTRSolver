# TTRSolver — Toontown solo-toon-vs-cogs solver

A Markov-state battle simulator for a single toon fighting a group of cogs,
built to be the environment an expectimax / value-iteration / RL solver
plugs into. **Simulator layer only so far — the solver isn't written yet.**

## Layout

```
solver/             the simulator package
  state.py          BattleState / ToonState / CogState / Action
  mechanics.py      accuracy formula, damage, cog attack selection, lure wake-up
  simulator.py      legal_actions(state) and step(state, action)
  data/             hand-entered game tables, one module per table
    accuracy.py       toon accuracy formula components
    gags.py           gag damage min/max by (track, level)
    cogs.py           cog HP formula + department registry
    bossbot.py        Bossbot cog freq / damage / accuracy tables
  testing.py        clearly-labeled synthetic stand-ins for TODO data
  demo.py           random-policy demo run
tests/              unittest suite
docs/
  data-confidence.md  what's confirmed vs. unverified, and the tagging rules
  roadmap.md          prioritized next steps
visualizer/         standalone React artifact: lazy expectimax tree explorer
```

## Running it

No dependencies beyond the standard library. From the repo root:

```
python -m unittest discover tests     # test suite
python -m solver.demo                 # one random-policy fight, printed
```

Both run under `solver.testing.synthetic_bossbot_accuracy()`, which
patches in a **fake** cog accuracy table because the real one is still
untranscribed. They prove the code paths connect; they are not
game-accurate. See [docs/data-confidence.md](docs/data-confidence.md).

## Ground rules

Carried over from the original design chat, and they matter more than the
code does:

- **Don't fill a `[TODO]` with a plausible-looking guess.** If a number
  isn't confirmed from the source repo (or a second corroborating source),
  leave it tagged `[TODO]` and make the code raise rather than silently use
  a fabricated value.
- **When a source contradicts itself, don't split the difference.** If a
  wiki figure looks inconsistent with the surrounding pattern (already
  happened with Throw L6 and Sound L5), leave it `[TODO]` with a note on
  what looked wrong rather than picking the "more plausible" number.

## Where to start

[docs/roadmap.md](docs/roadmap.md) item 1: transcribe the Bossbot cog
attack accuracy tables (Appendix C of
[QED1224/Toontown-Resources](https://github.com/QED1224/Toontown-Resources))
into [solver/data/bossbot.py](solver/data/bossbot.py). That's the one
gap forcing the synthetic-data workaround above; closing it lets the whole
Bossbot department run for real.
