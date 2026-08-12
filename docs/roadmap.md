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

## 3. Search speed

Where it stands on a three-cog fight: depth 2 ~1.0s, depth 3 ~11s exact or
~7s at epsilon 0.05. A **full exact solve to the end of the battle** runs in
seconds for small fights (2 cogs / 10 gags: 2.5s; 3 cogs / 8 gags: 8.3s) and
does not finish in ten minutes at 3 cogs / 11 gags.

What's implemented, and what each was worth:

- **`BattleState.clone()` over `copy.deepcopy`** -- 35s to 1.3s at depth 2.
  The one that mattered, and it was not the algorithmic suspect.
- **Caching attack distributions** by (department, type, level) -- 1.34s to
  1.03s.
- **Symmetry de-duplication** -- targeting cogs identical in type, level, HP
  and status is the same move, so `distinct_actions` collapses them. Three
  identical cogs: 8 actions become 4. Free, exact, and identical cogs are
  the common case in a real battle.
- **Star1 (`*`-minimax) pruning** -- the alpha-beta analogue for chance
  nodes. Exact, verified against an exhaustive search, but only ~1-2x here.
  It works best when the utility range is narrow relative to the search
  window, and ours is wide (a branch can range over ~250 points), so the
  bounds stay loose and cuts come late.
- **Transposition table with bound flags** and TT-move-first ordering.
  Iterative deepening is wired up (`best_action_iterative`) but currently
  runs *slower* -- the extra shallow passes don't repay while star1 is
  cutting so little.
- **Epsilon trimming** (approximate, off by default) -- drop the thin tail
  of the outcome distribution and renormalise. 1.7x at epsilon 0.05 for
  about 5 points of EV drift, same move chosen. Error is bounded by
  `dropped mass x value range`, so it is quantifiable rather than a guess.

Worth trying next, roughly in order of expected payoff:

1. **Tighter value bounds.** Star1 lives or dies on them. A cheap admissible
   bound per state -- something like "cogs left x their max damage" for the
   floor -- would narrow the window far more than any amount of reordering.
2. **Star2**, which probes one child before committing, and needs those
   bounds anyway.
3. **Bucketing near-identical damage outcomes** (merge states differing by
   a point or two of laff). Attacks the branching factor itself, which is
   the actual cost driver, at the price of a coarser state space.
4. **Parallel root search** with a warm pool -- `parallel.rank_actions` is
   there, and the memo duplication it costs matters less at depth 4+.

**None of this helps the visualizer**, which runs single-threaded under
Pyodide with no `multiprocessing`; that would need web workers.

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
