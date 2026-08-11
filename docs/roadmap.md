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

## 1. Find TTR cog attack frequency and accuracy

The wiki publishes neither, and 4.0.0 rebalanced both — so `data/*.py`
holds pre-rebalance values for a game that changed them, with no published
replacement. This is the largest remaining source of error and it bounds
what the solver can honestly claim (see
[data-confidence.md](data-confidence.md)).

Leads, roughly in order of promise:
- the rebalancing PDFs linked from the wiki at `cdn.toontownrewritten.com`
- decompiled `SuitBattleGlobals.py` from a TTR client
- community spreadsheets, if any post-date 4.0.0

Closing this would also let the **twelve 4.0.0 attacks** currently parked in
`"unmodeled_attacks"` be folded into the real tables. They have confirmed
damage and targeting but no frequency, so today the simulator simply
under-estimates the eight cogs that have them — nine of the twelve are
group attacks.

## 2. Smaller data gaps

- `lawbot/big_wig/finger_wag` damage: two wiki pages disagree; needs a
  third source.
- `sellbot/the_mingler/power_trip`: probably removed from the cog in 4.0.0.
  Removing it needs a frequency redistribution no source gives.
- Trapdoor organic damage and Lipstick minimum heal: three-way conflicts.
- Per-gag `minE`/`maxE` experience thresholds, which would replace the
  min/max interpolation in `calc_toon_damage` with the real formula. The
  gag infoboxes' `prevexp`/`nextexp` fields are the likely source.

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
