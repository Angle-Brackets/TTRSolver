# Roadmap

## Done

- **Cog attack tables, all four departments.** 32 cogs, 124 attack rows of
  frequency / damage / accuracy from Appendices A/B/C, plus group-attack
  flags from Appendix B's Type column. Structural invariants pinned by
  `tests/test_data.py`. Two cells deliberately left `[TODO]` — see
  [data-confidence.md](data-confidence.md).
- **Lure wake-up.** A lured cog is no longer removed from the fight
  permanently: it ticks its timeout, rolls `wakeupChance`, and attacks the
  same round if either ends the lure. Brought `luredRatio` accuracy and
  `kbBonus` damage in with it.
- **Expectimax solver.** `solver/outcomes.py` enumerates the exact outcome
  distribution; `solver/search/expectimax.py` searches it with memoization.
  `python -m solver.search.demo --compare` measures it against a random
  policy.

## 1. Audit the rest of `data/` against the TTR wiki

Lure has been redone from <https://toontownrewritten.wiki> and the old
strategy guide was wrong about nearly every value (see
[data-confidence.md](data-confidence.md) for the diff). Everything else in
`data/` still comes from that guide and is now suspect: cog attack
frequency/damage/accuracy for all 32 cogs, gag damage, `tgtDef`, cog HP,
and the accuracy formula's other propAcc rows.

This is the top priority because those values look confirmed and aren't.

## 2. Remaining gag data (from the wiki, not the guide)

Trap per-level damage (blocks the trap+lure combo entirely — the detonation
path is implemented but raises), Toon-Up heal amounts, Throw L6, Squirt
L2-6, Sound L5-6, Drop L1-6. Also the per-gag `minE`/`maxE` experience
thresholds, which would let `calc_toon_damage` use the real exp-based
formula instead of interpolating min/max.

The wiki has a page per gag track (`/Throw`, `/Squirt`, `/Sound`, `/Drop`,
`/Trap`, `/Toon-Up`) in the same shape as `/Lure`, so this should be
largely mechanical.

## 3. Make the search fast enough to go deeper

A depth-2 evaluation on a three-cog fight takes ~1.3s. That's after the big
win — `copy.deepcopy` was 91% of the runtime, and replacing it with
`BattleState.clone()` cut a depth-2 search from 35s to 1.3s. Depth 3 is
usable; depth 4 still isn't.

Remaining options, cheapest first: cache `cog_damage_distribution` per
`(department, cog_type, level)` — it doesn't depend on mutable state but is
recomputed at every node; prune outcome branches below an epsilon
probability (the damage distribution has a long, nearly irrelevant tail);
order actions by a quick static score so an alpha-beta-style cutoff has
something to work with. Profile before each — the deepcopy result is a
reminder that the obvious algorithmic suspect wasn't the problem.

## 4. Validate the solver's advice against real play

The search is verified as an *algorithm* (`tests/test_search.py`) and the
distribution is verified against the sampler (`test_matches_sampled_step`),
but nothing yet checks that its advice matches what strong players actually
do. Worth picking a handful of known positions with a consensus best move
and seeing whether it agrees.

## 5. Decide what the visualizer visualizes

[visualizer/](../visualizer/) still carries its own hardcoded JS port of
the rules, which has now drifted further — it knows nothing about lure
wake-up, `luredRatio`, or `kbBonus`. Either regenerate it from the Python
tables or have it render precomputed trees exported as JSON from
`solver.search`. The second is the single-source-of-truth option and is
looking more attractive now that the Python side is the richer model.

## Later

Cog HP at levels 10–12 needs a second source. The non-tier-1 `tgtDef`
branch at cog levels 4–5 isn't modeled. Multi-toon play would need
`calc_prev_hits_bonus` and `pick_cog_target` filled in — both are
deliberate solo-play simplifications today, not stubs.
