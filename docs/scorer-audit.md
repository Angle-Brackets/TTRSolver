# Party Scorer Audit and Defect Resolution

Audit of party search evaluation logic, mechanics discrepancies, and observation space limitations.

## Corrected Benchmark Summary

Initial benchmarks contained an unfilled mechanics rule: `LURE_ENDS_ON_DAMAGE = None` allowed lured cogs to remain asleep after taking non-sound damage. Correcting the rule reduced baseline CEO win rate to 54%; cumulative resolution of the four party defects restored performance to 88.5%:

| Encounter | Initial Uncorrected Rule | Corrected Mechanics (All Fixes) |
|---|---|---|
| Cog Buildings | 71.5% | **73.5%** |
| Sellbot VP | 99.4% | **99.5%** |
| CEO (Banquet Cleared) | 88.9% | **88.5%** (78.3% full fight) |
| CEO (2 Leftovers) | — | 73.5% (54.0% full fight) |
| CEO (4 Leftovers) | — | 45.0% (20.2% full fight) |
| CEO (5 Leftovers) | 43.1% | 32.5% (10.6% full fight) |
| CEO (10 Leftovers) | 2.0% | 3.0% (0.1% full fight) |

*(Held-out seeds, 200 sides/cell; full fight requires clearing both 2-toon sides).*

### Initial Hypotheses Ruled Out
1. **Gag Exhaustion**: Parties wipe with 163 of 172 gags remaining. Pouch exhaustion is mathematically unreachable in 20–30 round encounters.
2. **Slip Hoarding**: Slip consumption rates were identical in wins (0.70 slips/round) and losses (0.61 slips/round).
3. **Unpriced Toon Loss**: Sweeping `toons_at_risk` from 0 to 240 produced zero outcome change.
4. **Difficulty Variation**: Mean cog level (11.65 in clears vs 11.73 in losses) and party laff (219 vs 216) show no predictive separation.

## Resolved Party Scorer Defects

### 1. Deterministic All-Hit Assumption in Plan Scorers
`_quick_score` and `_greedy_score` evaluated plans assuming all gags hit. While approximately valid at 70–95% building accuracy, high-level cogs (levels 13–14) span 51–95% accuracy, causing all-hit scorers to select high-damage, low-probability actions (e.g. un-stunned Drop).

- **Resolution**: Both scorers evaluate expected value over all outcomes via `_expected_over_rolls`.
- **Enumeration**: Exact enumeration over roll groups ($\le 16$ branches for 4 toons). Gags sharing a (track, target) pair share a single random variable.
- **Conditional Accuracy State**: Probabilities are drawn directly from simulator state records to preserve conditional modifiers:

| Scenario | Accuracy |
|---|---|
| Drop 7 (un-stunned) | 54% |
| Drop 7 (Throw landed first / stun bonus) | **79%** |
| Single Lure 6 $\to$ Dual Lure 6 (multi-lure bonus) | 79% $\to$ **95%** |
| Lure 6 vs untrapped $\to$ trapped target | 79% $\to$ **95%** |

- **Empirical Impact**: Win rate improved 69.5% $\to$ 75.0% on 200 CEO sides ($+24/-13$, sign test $p = 0.049$). Latency on climb: 1.7 ms $\to$ 3.3 ms per decision.

### 2. Forced Accuracy Corruption
Rules mandate fixed accuracies for specific interactions (Trap: 100%, Throw/Squirt into lured: 100%, Drop into lured: 0%). `apply_party_round` previously added same-round stun bonuses to these forced constants and applied a 95% ceiling:
- Trap after heal: Resolved at 95% (5% miss rate introduced).
- Throw into lured after heal: Resolved at 95%.
- Drop into lured after Throw: Resolved at 25% ($0\% + 25\%$ stun bonus).

- **Resolution**: Enforced immutable overrides via `mechanics.forced_accuracy`.

### 3. Party Accuracy Evaluated Against Toon 0
`toon_action_accuracy` queried `state.toon` for all party members, evaluating all 4 gags using toon 0's track experience and organic buffs.
- **Resolution**: Parameterized by acting seat index `actor`.

### 4. Zero-Cost Pink Slips in Candidate Ranking
`_cheap_score` priced fires at 0, depleting all 10 slips during preliminary rounds and leaving 0.3 slips for the final boss encounter.

- **Resolution**: `FIRE_PRICE = 20 * cogs_remaining`. Slips scale in cost when subsequent cogs remain, dropping to 0 at encounter termination. Unstuck 10-leftover CEO win rate from 0%.
- **Opportunity Cost Refutation**: An opportunity cost formulation (pricing slips against the $F$-th best target in the holdout) degraded CEO win rate (88.0% $\to$ 76.0%, $p = 0.0003$). It deferred early slip usage, forfeiting the long-term cumulative damage prevention that early removals provide.

## Observation Vector Expansion (290 $\to$ 302 Floats)

Auditing revealed three feature omissions in the 290-dimensional observation vector:
1. Version 2.0 cogs and standard cogs encoded identically (suit layer omitted).
2. Pink slip counts were unrepresented (policy proposed fires blindly, relying on the legality mask).
3. Level 14–15 cogs exceeded previous normalization ranges (`level / 12.0`, `max_hp / 200.0`).

- **Updates**: Added `suited` flag, remaining work ratio ($\frac{\text{hp} + \text{max hp}}{\text{max hp}}$ for v2.0), per-toon pink slip counts, and expanded normalization ceilings to level 20 and 476 HP.
- **Retraining on Boss Scenarios (`--boss-fraction 0.25`)**:

| Encounter | Control (302-wide, no boss) | Boss-Trained (`boss_s2`) | $\Delta$ (Climb) |
|---|---|---|---|
| Buildings | 72.5% | 69.2% (69.6% held-out) | Neutral (seed noise) |
| Sellbot VP | 98.1% | **99.7%** | +1.6% ($p = 0.035$) |
| CEO (0 leftovers) | 79.2% | **88.1%** | **+8.9%** ($p < 0.0001$) |
| CEO (5 leftovers) | 28.6% | **40.0%** | **+11.4%** ($p = 0.0003$) |

Providing boss scenarios during training shifts the initial coordinate ascent starting point, enabling convergence to superior local optima.

## Refuted Hypotheses & Negative Findings

### 1. Boss Encounter Healing
Forcing healing candidates on boss encounters via `probe_tracks` degraded CEO performance by 7.5 percentage points (88.3% $\to$ 80.8%, $p = 0.025$). Boss waiter battles are high-DPS damage races where offensive elimination mitigates more aggregate damage than Toon-Up restores.

### 2. Candidate Window Expansion
Widening coordinate ascent candidate width from 3 to 5 (`w5 b14` vs `w3 b8`) appeared beneficial on discovery seeds but was neutral across 240 held-out sides (48.8% vs 48.8%, $+50/-50$).

### 3. Evolutionary Scorer Refitting
Running an evolutionary strategy across all 7 scoring weights over 45 generations produced +6% on the training set but was neutral on validation (70.4% $\to$ 70.8%) and out-of-sample sets. Evaluation variance on 180-side sets forms a noise floor that black-box optimization overfits.

### 4. Multi-Seed Best-of-N Selection
Selecting the top-performing seed from an 8-seed sweep on CEO 0 (`v4_s18`, 62.5% on selection set) degraded on 200 held-out sides relative to baseline `v2_s3` (CEO 2: 42.0% vs 53.0%, $p = 0.006$; buildings: 66.0% vs 72.5%, $p = 0.005$). Maximizing across high-variance evaluation distributions overfits sample draws.

## Evaluation Methodology Rules

1. **Sample Size Floor**: Minimum 200 paired sides with common random numbers and sign tests. 40-seed samples overestimated effect sizes by $2\times$ in multiple instances.
2. **Strict Exception Handling**: Test harnesses must raise on unmappable actions or invalid configurations rather than defaulting to passive actions (`PASS_INDEX`).
