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

~~Closing this would also let the twelve 4.0.0 attacks currently parked in
`"unmodeled_attacks"` be folded into the real tables.~~ **Done, with an
approximation rather than data.** `cogs._fill_unmodeled` gives each of them
the mean accuracy and frequency of the same cog's *modelled* attacks, so
the eight cogs carrying them are no longer under-estimated. It is tagged as
a borrow, not as data: "a preference for being roughly right over being
precisely silent, taken knowingly". If the wiki ever publishes the columns,
delete the function rather than tuning it.

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
- **Star1 and star2 (`*`-minimax) pruning** -- the alpha-beta analogue for
  chance nodes, star2 adding a probe of one action per child for a real
  lower bound. Both exact and verified against exhaustive search. **Both
  are slower here and default to off**: 12s exhaustive, 52s star1, 56s
  star2 at depth 3. Not a transposition problem (the table stays 99%
  EXACT); the bounds are simply too loose to cut, so all that is left is
  per-branch overhead. See the expectimax module docstring.
- **Transposition table with bound flags** and TT-move-first ordering.
  Iterative deepening is wired up (`best_action_iterative`) but currently
  runs *slower* -- the extra shallow passes don't repay while star1 is
  cutting so little.
- **Epsilon trimming** (approximate, off by default) -- drop the thin tail
  of the outcome distribution and renormalise. 1.7x at epsilon 0.05 for
  about 5 points of EV drift, same move chosen. Error is bounded by
  `dropped mass x value range`, so it is quantifiable rather than a guess.

Worth trying next, roughly in order of expected payoff:

1. **Tighter value bounds.** This is now the only thing standing between
   the pruning code and a real speedup, and it is measured rather than
   assumed: the interval a branch can occupy is ~250 points wide, set by
   "could still win" against "could still lose every remaining laff". A
   bound that knew how many rounds the cogs need to finish the toon, or how
   few they need to die in, would narrow it sharply. Star2's probe is
   already written and is *not* the bottleneck -- the interval it probes
   into is.
2. **Bucketing near-identical damage outcomes** (merge states differing by
   a point or two of laff). Attacks the branching factor itself, which is
   the actual cost driver, at the price of a coarser state space.
3. **Parallel root search** with a warm pool -- `parallel.rank_actions` is
   there, and the memo duplication it costs matters less at depth 4+.

**None of this helps the visualizer**, which runs single-threaded under
Pyodide with no `multiprocessing`; that would need web workers.

## 4. Improve the heuristic (attempted; nothing beat it yet)

There is now a way to *score* a heuristic instead of arguing about it:
small fights can be solved exactly to the end, so a shallow search using
heuristic X can be graded on how often it picks the exact solver's move,
and how much EV it gives up when it doesn't.

Baseline (HP progress minus laff lost): **78% optimal, 10.6 EV regret**
over 40 random fights.

Tried and rejected, all measured:

| idea | result |
| --- | --- |
| threat-weighted (dead cog = 0 threat) | 75%, regret 12.3 |
| blended threat + HP | 72%, regret 15.3 |
| lure-discounted threat | 65%, regret 20.9 |
| grid over (HP, kill-bonus, laff) weights | nothing beat 100/0/100 |

The reasoning behind the threat idea was sound -- a dead cog stops
attacking, a half-dead one hits just as hard -- and it still lost. HP
progress turns out to be the better proxy simply because the +100 win bonus
dominates the objective, and you collect it by removing HP, not by removing
threat. A kill bonus on top consistently hurt.

One candidate (60/0/30) showed lower regret on the first sample and turned
out to be noise: it was indistinguishable on two fresh samples of 50.

Worth trying next: features the current heuristic cannot see at all --
gags remaining in the pouch, and whether a cog is one hit from dying (a
step function, not the linear HP term).

## 5. Validate the solver's advice against real play

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
