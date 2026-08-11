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

Leads are thin — the wiki, its linked rebalancing PDFs, and community
sources have all been checked and none publish it. Realistically this needs
decompiled `SuitBattleGlobals.py` from a TTR client, or enough recorded
battle logs to estimate hit rates empirically.

**Before spending effort here, note it may not be worth it.**
`python -m solver.search.sensitivity` shows the solver's recommended move
is unchanged across ±20 accuracy points and only diverges at −30. The gap
costs forecast precision, not advice quality. Chase it if you want
trustworthy absolute win rates; skip it if you want good moves.

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

Where it stands: a depth-2 evaluation on a three-cog fight is ~1.0s, and
the 24-fight benchmark runs in 9s across 12 cores where it used to take 45.

What got it there, in order of how much it bought:

- **`copy.deepcopy` was 91% of runtime.** `BattleState.clone()` took a
  depth-2 search from 35s to 1.3s. The lesson worth keeping: profile first.
  The algorithmic suspect was not the problem either time.
- **Caching attack distributions.** `cog_attack_outcomes` depends only on
  (department, type, level), and a depth-2 search called it 11,111 times
  for three distinct cogs. 1.34s -> 1.03s.
- **Parallel fights.** Benchmarks and sweeps play independent fights, so
  `solver/search/parallel.py` spreads them over cores: ~5x on 12 cores
  (not 12x -- the random policy is nearly free, so half the batch is
  trivial, and 24 fights over 12 workers is coarse).

Left to try, cheapest first: prune outcome branches below an epsilon
probability (the damage distribution has a long, nearly irrelevant tail);
order actions by a static score so an alpha-beta-style cutoff has something
to work with; and only then consider splitting a single search at the root,
which `parallel.rank_actions` does but which loses to the serial version
unless you already have a warm pool -- workers can't share the memo, so they
redo each other's transpositions.

**None of this helps the visualizer.** Pyodide is single-threaded and has no
`multiprocessing`; the page's per-node latency needs web workers instead.

## 4. Validate the solver's advice against real play

The search is verified as an *algorithm* (`tests/test_search.py`) and the
distribution is verified against the sampler (`test_matches_sampled_step`),
but nothing yet checks that its advice matches what strong players actually
do. Worth picking a handful of known positions with a consensus best move
and seeing whether it agrees.

## Done: the visualizer runs the real solver

Resolved in favour of one source of truth. `python -m visualizer.serve`
loads `solver/` into the browser with Pyodide; `visualizer/bridge.py` is
the only translation layer and holds no game rules. The JavaScript port is
deleted.

## Later

Cog HP at levels 10–12 needs a second source. The non-tier-1 `tgtDef`
branch at cog levels 4–5 isn't modeled. Multi-toon play would need
`calc_prev_hits_bonus` and `pick_cog_target` filled in — both are
deliberate solo-play simplifications today, not stubs.
