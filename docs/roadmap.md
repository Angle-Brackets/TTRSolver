# Roadmap

Where TTRSolver stands as of 2026-10-11: what is built, what is open, which
numbers in the game data are still missing, and what was started and put
down.

Three things to know before reading:

- **Results are from simulated fights unless a line says a running game was
  observed.** The measurements behind every figure here are in
  [experiment-log.md](experiment-log.md).
- **Data tags.** `[CONFIRMED]` means taken from the Toontown Rewritten (TTR)
  wiki, `[OWNER]` means the maintainer's judgement as an experienced player,
  `[ASSUMED]` marks a value chosen knowingly without a source, and `[TODO]`
  marks a value left empty so that code using it raises instead of guessing.
  [data-confidence.md](data-confidence.md) explains them in full.
- **The three engines.** The live panel shows three answers each round. The
  *PPO row* is a trained policy whose proposals are refined by a one-round
  scorer (`solver/search/hybrid.py`, called "climb" in the code). The
  *Search row* is an expectimax search (`solver/search/expectimax.py`). The
  *Playout row* plays each candidate move to the end of the fight many
  times and keeps the best (`solver/search/playout.py`). The Playout row
  leads by default.

## Contents

- [Done](#done)
- [Open work, in rough priority order](#open-work-in-rough-priority-order)
- [Known data gaps](#known-data-gaps)
- [Shelved: TTR teammates in the Playout row (not fully implemented)](#shelved-ttr-teammates-in-the-playout-row-not-fully-implemented)
- [Deferred: training throughput](#deferred-training-throughput)
- [Background: search speed](#background-search-speed)
- [Background: the leaf heuristic](#background-the-leaf-heuristic)

## Done

**Rules and data**

- Gag and cog tables for all four departments (32 cogs), audited against
  the TTR wiki and cross-checked against Open Toontown's
  `SuitBattleGlobals.py` (`tools/verify_against_tto.py`). Structural
  invariants are pinned by `tests/test_data.py`.
- The accuracy formula, including the rank-dependent `tgtDef` branch at
  cog levels 4 and 5, and the cog HP table with its level-12 boost.
- Lure in full: durations, wake-up, knockback, the `luredRatio` bonus, and
  the bonus for several Lures thrown together.
- Organic gags, Trap rules (two Traps cancel, a group Trap needs one
  unlured cog), Version 2.0 cogs, pink slips, Unites and the 29 SOS cards.
- The twelve cog attacks added in TTR 4.0.0. They have published damage
  but no published frequency or accuracy, so `cogs._fill_unmodeled` gives
  each the mean accuracy and frequency of the same cog's other attacks.
  This is a borrow, not data; see [Known data gaps](#known-data-gaps).
- Party rounds: `BattleState.toons` is a list, accuracy is rolled per
  track per target, cog targeting follows Open Toontown's algorithm
  (`mechanics.pick_cog_target`), the previous-hits bonus is modelled
  (`mechanics.calc_prev_hits_bonus`), and group cog attacks hit every
  standing toon (`data.GROUP_ATTACKS`, 14 group and 54 single attacks from
  the wiki's two categories).
- Fights that continue: buildings as consecutive floors
  (`solver/facility.py`), the VP (`solver/vp.py`) and the CEO
  (`solver/ceo.py`), with round sizes that depend on how many toons came.
- Three implementations of a round (exact outcomes, the solo simulator,
  the party simulator) held against each other by `tools/round_parity.py`.

**Engines**

- Exact expectimax with memoisation, symmetry de-duplication, `*`-minimax
  pruning, move ordering, and an optional collapse of the cog phase to its
  mean. See [Background: search speed](#background-search-speed).
- A fitted leaf evaluator that replaced the hand-written heuristic. See
  [Background: the leaf heuristic](#background-the-leaf-heuristic).
- A PPO policy trained on parties, buildings and boss fights, with a
  coordinate-ascent refinement over joint plans.
- The Playout engine: a wide candidate menu, successive halving with
  common random numbers, a rollout network trained by expert iteration on
  the playouts' own choices, a value network that cuts playouts short
  after eight rounds, and charges for gags spent and reach wasted.
- Panel presets (Balanced, Conserve, Survive, Speedrun, Glass Cannon) that
  shape the Search and Playout rows.

**Reading a live game**

- TTR: the official opt-in Local API (laff, gag training, location, pink
  slips held), screen reading of the game's own window (cog plates and the
  gag menu, with learned digit classifiers and a checksum against the
  menu's "Total gags" label), the client's log file (detects a VP), and a
  relay on Discord's Rich Presence pipe (a building's floor count).
- Toontown Realms: a second panel driven by that server's network stream
  rather than by pixels ([realms.md](realms.md)).
- A feedback log that records the board, each engine's proposal and the
  move the player actually made.

**Tooling**

- About 1,900 standard-library `unittest` tests.
- `tools/sweep.py` for paired sweeps over the same simulated fights,
  `tools/ground_truth.py` for a playout-labelled benchmark,
  `tools/video_scan.py` for running the screen readers over a recording,
  and `tools/search_bench.py` for the exact search.
- A visualizer that runs the real solver. `python -m visualizer.serve`
  answers the page's calls from a CPython process importing `solver/`; the
  page holds no copy of the rules.

## Open work, in rough priority order

### 1. Reconcile the model with play on a one-toon VP side

In a two-player VP each toon fights one side alone: ten cogs, then ten
skelecogs. Simulated with a light SOS deck and no pink slips or Unites,
the PPO row wins 6 of 60 and the Playout row 33 of 60. The maintainer, who
has played the fight many times, calls it trivial `[OWNER]`. Every traced
loss dies to the skelecogs with most of the pouch unthrown, which points
at cog damage or attack rate in the model and not at the search. Giving
the toon five Unites lifts the Playout row to 55 of 60, so part of the gap
was a simulator bug that discarded Unites (fixed 2026-10-06), but the
no-Unite figure still disagrees with play. This is the most direct
evidence that the cog attack tables are off, and it is tied to the first
row of [Known data gaps](#known-data-gaps).

What would move it: logged real fights on that side (cog attacks chosen,
hits and misses, laff over time) to compare against the simulator's
distribution.

### 2. Check the engines' advice against real play

The search is verified as an algorithm, the outcome distribution is
verified against the sampler, and the three round implementations are
held against each other. Agreement with strong play is barely measured.
One comparison exists: over a 34-board solo VP on Toontown Realms
(a running game, 2026-10-10), the PPO row matched the maintainer's move on
29% of boards, the Search row on 12% and the Playout row on 14%. That log
exposed several bugs (dying cogs targeted, Lures ageing two rounds a
round, SOS cards counted five times over) which were then fixed, and the
comparison has not been repeated since. Repeating it on fresh logs, on
both servers, is the next step.

### 3. Evidence about teammates on TTR

TTR shows the client one toon, so the Playout row plans around a count of
teammates. Knowing what the teammates hold was measured as worth about 11
wins in 300 simulated party buildings; guessing was worth nothing. The
half that could pay is not built. See
[Shelved](#shelved-ttr-teammates-in-the-playout-row-not-fully-implemented).

### 4. Party play beyond the rules

Only the rules are party-aware end to end. Open items:

- The party feature vector is defined but not validated: the exact solver
  cannot reach a party position, so there are no labels to check it
  against, and the evaluator is saturated on a maxed team.
- No result about Lure from the party search is trustworthy, because a
  one-ply coordinated search cannot find a multi-round plan
  ([party-strategy.md](party-strategy.md)).
- The rollout network plays one seat. Group playouts are played on by the
  slower PPO row, which plans every seat.
- `SensiblePrior`, the model of what a stranger throws, is a guess about
  people and nothing in the game can confirm it. The interface takes a
  distribution so that a model fitted from real play can replace it.

### 5. Gaps in live reading

- **SOS cards and Unites on TTR.** The Local API serves `/sos.json` and
  `/unites.json`, but no toon holding battle cards has been read, so the
  card names are unseen and neither endpoint is parsed. The panel's SOS
  box is inert on TTR; the Unites box takes a count the player types.
- **Boss fights other than the VP on TTR.** The client log line that names
  a boss room has only been observed for the VP. The CFO, CJ and CEO stay
  on a manual picker until each is seen.
- **Platforms other than Windows.** `solver/live/window.py` is
  Windows-only, the log folder is only known for a Windows install, and
  the Discord relay's Unix transport and its macOS and Linux restart
  commands follow the reference library but have never run on a real
  machine.
- **Teammates' laff on TTR** is not read from the screen.

### 6. The Search row

The Search row trails the Playout row badly wherever a fight has more
than one wave (6 of 60 against 33 of 60 on one-toon VP sides), because it
sees only the cogs on the field. Within a single battle its move stops
changing at depth 4. Two things remain untested in play:

- `expectimax.BEAM` at 6 would reach one ply deeper in the same time
  budget. It agrees with the exact search on every benchmark position but
  has not been measured in fights, and is off.
- A learned leaf (`solver/search/valuenet.py`) was tried three ways and
  was never better in play. It is off.

### 7. The Playout engine

Measured as not paying, so not worth repeating without a new idea: more
than 32 full rollouts per move, formulas fitted to playout labels, a
per-call price on SOS cards, open-loop tree search (MCTS) at one to four
times the budget, stand-in teammates, and three further rounds of expert
iteration for the rollout network on 2026-10-11. Open:

- One lead from those rounds was not followed up: a rollout network
  trained on Playout labels only won 113 against 103 of 1,000 simulated
  solo buildings (p 0.064) while being level on solo VPs. It needs a
  larger sample.
- A tree search retry would need chance nodes and the network's own
  choice below the root until a node is well visited.
- The PPO row ignores the panel's preset.
- In buildings, results are decided by laff, so the pouch-value and
  economy terms change which gag is advised without changing simulated
  wins. Their weights rest on the maintainer's preference `[OWNER]` and on
  "no wins lost", not on a measured gain.

### 8. Training throughput

Deferred. See [Deferred: training throughput](#deferred-training-throughput).

## Known data gaps

Each row is something the model does not know. "Handling" is what the code
does today; none of these is filled with a plausible-looking number
without a tag saying so.

| Gap | What is missing | Handling today | What would settle it |
|---|---|---|---|
| Cog attack frequency and accuracy | TTR 4.0.0 rebalanced both and the wiki publishes neither. The tables hold Toontown Online's values. | Used as they are. A sensitivity sweep on 2026-08-11 (`python -m solver.search.sensitivity`) found the exact solver's chosen move unchanged across ±20 accuracy points, first diverging at −30, so the gap costs forecast precision more than advice. | The wiki publishing the two columns, or a measurement: recorded battles large enough to estimate how often each attack is chosen and how often it hits. |
| The twelve 4.0.0 attacks | Frequency and accuracy for attacks whose damage is published. | Borrowed from the same cog's other attacks (`cogs._fill_unmodeled`). | The same as above. If the columns are ever published, delete the function rather than tune it. |
| `the_big_cheese/glower_power` accuracy | No accuracy at any level. | `[TODO]`: the cell is empty and raises. `solver/ceo.py` turns on a borrowed value (`BORROW_BLANK_ACCURACY`) because the CEO's second battle cannot be built without it. | A published or measured accuracy. |
| `the_mingler/power_trip` | The wiki's Mingler roster does not list this attack; TTR appears to have removed it. | Kept, tagged as unresolved, because removing it needs a redistribution of its 15% frequency that no source gives. | A source for The Mingler's current attack frequencies. |
| `tgtDef` for cog levels 13 to 19 | The wiki prints "Unknown". | `[ASSUMED]`: interpolated linearly between the published values at 12 and 20 (`solver/data/accuracy.py`). The CEO's cogs reach level 14, so the fight could not be built otherwise. | Measured gag hit rates against cogs at those levels. |
| Which Lure-bonus value goes with which level gap | The 4.0.0 notes give "(20/15/10)%" without saying which gap selects which. | `[ASSUMED]`: gaps of 0, 1 and 2 or more (`mechanics.MULTI_LURE_ACCURACY_BONUS`). | Hit rates from two group Lures at known levels, enough trials to separate the three values. |
| The 95% accuracy cap | Since 4.3.3 bonuses can push accuracy slightly above 95%; the wiki gives no figure. | Modelled as a hard cap; flagged by `data.ACCURACY_CAP_IS_SOFT_IN_GAME`. | A published ceiling or measured hit rates at the cap. |
| Carry limits between a starting and a full pouch | Only the two endpoints are published, and two accounts of the rule disagree. | `[TODO]`: every consumer reads the full-pouch limit (`max_carry`), which over-equips under-trained toons. | The rule, from the wiki or from several toons' gag menus at known training. |
| Cogs above their normal level range | Cogs can appear up to three levels higher; damage is published, frequency and accuracy are not. | Not modelled. | The same data as the first row. |
| Boss fight structure: CFO, CJ, and the CEO's second round | No published or observed cog counts. | `[TODO]`: `boss.rounds_for` returns no horizon, so playouts end with the battle on screen. | Counting cogs in each fight. |
| A solo CEO's first round | Twenty cogs a side is verified in game; forty for a lone toon is the maintainer's "I think" `[OWNER]`. | Used as forty. | One solo run counted. |
| SOS card and Unite names in the Local API | `/sos.json` and `/unites.json` have never been read from a toon that holds any. | Not parsed. | Reading both endpoints from a toon that holds cards. |
| Boss rooms in the log file the game writes | Only the VP's line has been observed. | `boss.TTR_BOSS_PLACES` has one entry; a guessed key could name the wrong fight. | Standing in each room once. |
| The Discord relay on macOS and Linux | The Unix-socket transport and the restart commands are untested on real machines. | Implemented from Discord's reference library; tests skip where the platform lacks Unix sockets. | A run on each platform. |
| Party evaluator | No exact labels exist for party positions. | Defined by pooling over standing toons; treated as untested. | A source of party labels, such as long playouts. |
| One-toon VP side | The model finds it hard; the maintainer finds it trivial. | See [open item 1](#1-reconcile-the-model-with-play-on-a-one-toon-vp-side). | Logged real fights. |

Two former gaps are closed and listed here only because older notes
mention them: the cog HP formula above level 11 (now matches every
published row) and `big_wig/finger_wag` damage (the conflicting page was
showing another attack's row). The experience-based damage formula
(`mechanics.gag_damage_from_exp`) is transcribed with its thresholds and
deliberately unused: wiring it in would require the live readers to
supply experience points instead of a training level, for little gain.

## Shelved: TTR teammates in the Playout row (not fully implemented)

TTR shows the client one toon, so the Playout row plans around a count of
teammates (the "Toon Party" selector on the panel). The count thins the
cogs' attacks and says nothing about anyone else's gags. Modelling the
teammates was started and shelved on 2026-10-11, with the maintainer's
agreement, because the half that could be built gains nothing.

Built, and switched off (`Worker.stand_in_teammates` in
`solver/live/overlay.py`; the panel's Strangers / My party toggle is
hidden while it is off):

- `party.assumed_teammates` and `with_assumed_teammates`: stand-in toons
  for the selector's count.
- `party.drawn_teammates` with `playout.REDRAW_ASSUMED`: the stand-ins
  redrawn in every pickup rollout.
- The group mode passed with each playout call (`Worker.group_mode`).

Measured on 300 simulated party buildings, with the real teammates
playing `SensiblePrior` (`tools/sweep.py --regime party-building`, arm
options `see=`, `keep=`, `redraw=`, `street=`):

| The Playout row sees | Won of 300 |
|---|---|
| the count alone (shipped) | 120 |
| one fixed set of stand-ins | 110 |
| stand-ins redrawn per rollout (true street / laff band) | 120 / 119 |
| the real teammates | 131 (p 0.04) |
| stand-ins with the real laff only | 114 |
| stand-ins with the real pouch and training | 129 |

So guessing is worth nothing and knowing is worth about 11 of 300, all of
it in what the teammates hold.

**NOT BUILT: the half that could pay.** That half is inferring a
teammate's training and pouch from play. The readable signal is cog
health that drops by more than your own throw explains. Gag damage is
distinct enough by track and level that a few rounds could weight
`drawn_teammates` toward teammates consistent with what was seen. The
open problems, none of them attempted: the health bar resolves only 2 to
3 HP on a high-level cog, several teammates' hits land in one round, and
nothing has been checked against live frames. The ceiling is the 11 wins
above, with perfect knowledge.

## Deferred: training throughput

Deferred by the maintainer and recorded so that the profile does not have
to be rediscovered. The figures are from 2026-08-23.

The GPU is not the constraint. Training already runs on CUDA
(`tools/train_ppo.py` picks it automatically); the policy is a
208K-parameter 302->256->256->250 network that the card evaluates at about
179,000 steps a second against the environment's roughly 7,400.

What the environment spends its time on, profiled over 6,000 steps:

| Part | Share |
|---|---|
| `rl.env.encode`, the 302-float observation | 36% |
| `legal_mask` and `simulator.legal_actions` | about 29% |
| `simulator.apply_party_round`, the battle itself | 8.8% |

Those 6,000 steps made 1.57 million `dict.get` calls and 1.02 million
`min()` calls, about 260 dictionary lookups a step, mostly
`gag_counts[(track, level)]` walked 49 times per toon.

**numpy would not help.** This is scalar, branchy work on 302-element
lists, where numpy's per-call overhead dominates. numpy pays only once the
environment steps many battles at a time as columns, which is a simulator
rewrite and not a dependency change. `solver/rl/env.py` is also not
training-only: `search/hybrid.py` imports it because the live advisor
calls `encode` and `legal_mask` to run the policy, so the
standard-library rule binds there.

In order of return:

1. **Run training seeds in parallel.** One run steps its 32 environments
   in a sequential loop and uses about one core. Four concurrent runs
   measured about 2,050 steps a second each against about 3,500 alone,
   roughly twice the aggregate.
2. **Cache the mask and the observation.** `legal_mask` recomputes
   `legal_actions` the caller often already has, and `encode` rebuilds all
   302 floats every step. Together they are about 65% of the runtime.
3. **Then** compile those two functions (mypyc or Cython), at the cost of
   a build step and a pure-Python fallback for the live path.

## Background: search speed

The exact search is no longer the engine that leads, so this section is
history a reader needs only to avoid repeating it. Full measurements are
in [experiment-log.md](experiment-log.md) (the exact-search entries of
2026-10-08 and 2026-10-09) and [search-depth.md](search-depth.md).

What was implemented, in order, and what each was worth:

| Change | Result |
|---|---|
| `BattleState.clone()` in place of `copy.deepcopy` (2026-08-11) | 35 s to 1.3 s at depth 2. The largest single gain. |
| Caching attack distributions by (department, type, level) | 1.34 s to 1.03 s. |
| Symmetry de-duplication (`distinct_actions`) | Exact. Three identical cogs: 8 actions become 4. |
| `*`-minimax pruning (star1, star2) | Slower than no pruning when first written (12 s exhaustive, 52 s star1, 56 s star2 at depth 3). After the value floor was made depth-aware on 2026-08-12 it pays: turning it off costs 9.2x at depth 4. On by default. |
| Epsilon trimming of thin chance tails | Approximate. First measured at 0.05: 1.7x for about 5 points of drift in expected value, same move chosen. The panel uses 0.03, which chose the same move as the exact search on four positions and ran 1.5 to 1.8 times faster. |
| Collapsing the cog phase to its mean (`exact_plies=0`) | Approximate. Same move as fully exact search at depth 3 on the benchmark; 86 s to 4.6 s on one cog. The panel uses it. |
| Best-first move ordering (`expectimax.ORDER`) | Exact. 1.24x at depth 3. On. |
| The shallower pass's move as a hint (`HINT_FROM_SHALLOWER`) | Exact. 1.4x to 1.85x. On. |
| Tighter static bounds for star1 (2026-10-08) | Admissible, searched exactly the same nodes, and cost more in arithmetic. Removed. |
| A beam below the root (`expectimax.BEAM`) | Same move as exact search at k=6. Not switched on: untested in play. |
| Iterative deepening with a transposition table | In use (`best_action_iterative`); the panel returns the deepest pass that finished inside its 15-second budget. |

Where it stands in the panel: a depth cap of 4 and a 15-second budget,
reaching depth 4 at two cogs and depth 3 at three or four. The move
chosen stops changing at depth 4 in a single battle, so further speed
buys little there; the search's weakness is that no depth reaches the
next wave or floor.

Not pursued: a parallel root search for the live path
(`parallel.rank_actions` exists for benchmarks), and merging outcomes
that differ by a point or two of laff.

## Background: the leaf heuristic

Small fights can be solved exactly to the end, so a shallow search using
a given leaf heuristic can be graded on how often it picks the exact
solver's move and how much expected value it gives up. "Small" is
literal: on 2026-08-11 a full solve took 2.5 s for 2 cogs and 10 gags,
8.3 s for 3 cogs and 8 gags, and did not finish in ten minutes at 3 cogs
and 11 gags.

The original hand-written heuristic (cog HP removed minus laff lost)
scored 78% optimal with 10.6 points of regret over 40 random fights on
2026-08-11. Variations tried then, all rejected:

| Idea | Result |
|---|---|
| Threat-weighted (a dead cog has no threat) | 75%, regret 12.3 |
| Blended threat and HP | 72%, regret 15.3 |
| Lure-discounted threat | 65%, regret 20.9 |
| Grid over (HP, kill bonus, laff) weights | Nothing beat 100/0/100 |

One candidate (60/0/30) showed lower regret on the first sample and was
indistinguishable on two fresh samples of 50: noise.

The roadmap then suggested features the heuristic could not see at all:
gags remaining in the pouch, and whether a cog is one hit from dying.
That is what was done. The leaf is now a linear model over structural
features (`solver/search/features.py`, `solver/search/fitted.py`) fitted
to exact values; [heuristic-learning.md](heuristic-learning.md) has the
method and the numbers. A neural leaf did not beat the fitted line on the
data available (2026-08-12), and three later attempts at a learned leaf
were no better in play (2026-10-09).
