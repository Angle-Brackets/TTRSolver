# Roadmap

Ordered so that each item unblocks the next. Item 1 is the recommended
next task.

## 1. Fill in Bossbot cog accuracy

Transcribe the Bossbot section of Appendix C from
[QED1224/Toontown-Resources](https://github.com/QED1224/Toontown-Resources)
into the `"accuracy"` field of each cog in
[solver/data/bossbot.py](../solver/data/bossbot.py), following the
existing `[CONFIRMED]` / `[PARTIAL]` / `[TODO]` tagging convention.

This unblocks the whole Bossbot department for a real, non-synthetic run.
Once it's in, delete `synthetic_bossbot_accuracy()` from
[solver/testing.py](../solver/testing.py) and drop its uses from
`tests/test_smoke.py` and `solver/demo.py` — the tests should then run
on real data.

## 2. Wire lure wake-up into the cog phase

`mechanics.lure_wakeup_chance()` is confirmed and implemented but unused.
`simulator._resolve_cog_phase` currently skips any lured cog's attack
unconditionally. To fix: store the pre-bonus accuracy (propAcc + trackExp +
tgtDef, no bonus) the Lure landed with on `CogStatus` when Lure is applied,
then roll `mechanics.lure_wakes_up()` against it each round.

## 3. Add the remaining Bossbot cogs

Micromanager, Downsizer, Head Hunter, Corporate Raider, The Big Cheese —
same shape as Flunky / Pencil Pusher / Yesman in `data/bossbot.py`, just
more rows. Source: Appendix A/B.

## 4. Write the solver

Expectimax or value iteration against `simulator.step` /
`simulator.legal_actions`. The environment interface is stable enough to
build against now, even with the data gaps above. It belongs in a new
`solver/search/` package (not `solver/solver/` — the top-level package is
already named `solver`).

## 5. Decide what the visualizer visualizes

Once the solver exists, decide whether
[visualizer/](../visualizer/) should keep its own lightweight JS port of
the game logic (fast, no backend, but a second copy of the rules to keep in
sync) or instead render precomputed trees exported from the real Python
solver as JSON (single source of truth, but static rather than
interactively reconfigurable in-browser). Worth a deliberate call rather
than drifting into whichever happens first.

## Later, if the Bossbot department round-trips cleanly

Transcribe Sellbot / Cashbot / Lawbot tables — one module per department in
`solver/data/`, registered in `data/cogs.py`'s `COG_DEPARTMENTS`. Also
outstanding: Toon-Up heal amounts, the per-gag `minE`/`maxE` experience
thresholds needed to replace the min/max interpolation in
`calc_toon_damage`, and a second source for cog HP at levels 10–12.
