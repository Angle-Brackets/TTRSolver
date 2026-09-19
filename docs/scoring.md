# Scorer Formulation and Parameter Tuning

Technical audit and empirical validation of `_quick_score` weights (`QUICK_W`), consumable pricing, and search evaluation parameters.

## Core Formulation: `_quick_score`

`_quick_score` evaluates candidate joint plans during coordinate ascent (`hybrid.climb`):

$$\text{Score} = \Delta_{\text{damage}} + 2 \cdot \Delta_{\text{heal}} + \text{trap\_stored} + 120 \cdot \text{kills} + 9 \cdot \text{prevented} - \text{price}_{\text{gag}} - \text{price}_{\text{spend}} + \text{survival\_bonus}$$

### Laff Level vs Delta: `survival_rounds`
Because `_score_leaf` evaluates the toon phase where laff deltas are zero, healing actions would score 0 without an absolute laff term.
- **Invariant Formulation**: `survival_rounds(state, incoming=expected_incoming(state))` evaluates laff against pre-plan expected incoming damage. Evaluating post-plan incoming damage caused double-counting with `prevented`, reducing solo win rates by 16% ($p < 0.001$).
- **Gating Invariant**: Pre-plan incoming damage makes `survival_rounds` constant across all standard gag actions, ensuring move ordering is invariant while correctly valuing pre-plan laff restoration from unites and SOS cards.

### `survival_rounds` Tuning (`QUICK_W["survive"] = 400`)

Solo VP encounter (12 cogs/round, 5 pink slips, 200 runs/cell):

| survive Weight | Unites Only (A / B) | SOS Only (A / B) | Combined (A / B) |
|---|---|---|---|
| 0 | 35.0% / 31.5% | 27.0% / 24.5% | 35.0% / 31.5% |
| 100 | 73.5% / 66.0% | 27.0% / 24.5% | 73.5% / 66.0% |
| 200 | — / 91.5% | — / 33.5% | — / 92.0% |
| **400** | **95.0% / 92.5%** | **52.5% / 49.0%** | **96.0% / 93.0%** |
| 600 | — / 91.0% | — / 53.0% | — / 92.5% |
| 800 | 92.5% / 91.0% | 57.5% / 52.0% | 95.0% / 94.0% |

Validation on realistic unmaxed toons (mean training 4.65, 250 runs/cell):
- Weight 0: 77.6% / 74.4%
- Weight 200: 86.0% / 84.4% ($p < 0.001$)
- Weight 400: **87.2% / 84.0%** (plateau region)

## Consumable Pricing

### Pricing Parameters
- `FIRE_PRICE`: Dynamic cost scaling with remaining cogs ($\text{base} + \text{cogs\_remaining}$).
- `FIRE_FLOOR = 120`: Minimum threshold required to trigger a pink slip.
- `UNITE_PRICE = 200`: Flat cost (0 turn opportunity cost).
- `SOS_PRICE = 250`: Flat cost (substitutes for toon turn action).

### Opportunity Cost Differentiation: SOS vs Unites
Unites execute via SpeedChat concurrently with gags (0 turn cost). SOS cards consume the toon's turn action. Across 90 sampled positions (with prices set to 0):
- Marginal advantage of best gag over standalone SOS card: $+203$ median ($+273$ mean).
- Marginal advantage of unite + gag over standalone SOS card: $+841$ median ($+892$ mean).

Setting `SOS_PRICE = 250` and `UNITE_PRICE = 200` properly balances the turn consumption cost without double-charging SOS cards.

### `FIRE_FLOOR` Optimization

Sweep across encounter difficulties (150 runs/cell, 5 slips/5 unites held):

| `FIRE_FLOOR` | Diff 3 Slips | Diff 5 Slips | Diff 9 Win Rate | VP Win Rate | VP Slips Spent |
|---|---|---|---|---|---|
| 20 | 0.63 | 1.16 | 63% | 95% | 4.89 |
| 60 | 0.00 | 0.12 | 65% | 94% | 4.69 |
| **120** | **0.00** | **0.03** | **65%** | **95%** | **3.96** |
| 200 | 0.00 | 0.03 | 53% | 85% | 2.93 |

`FIRE_FLOOR = 120` eliminates wasteful slip usage on low-difficulty battles and reduces consumption in boss battles by $\approx 1$ slip with zero win-rate degradation. Re-validated on realistic unmaxed toons: 88.8% win rate vs 89.2% ($p = 1.000$) with reduced slip expenditure.

### Consumable Consumption Scaling by Difficulty

Evaluated with full consumable availability (5 slips, 5 unites, 29 SOS cards; 150 runs/cell):

| Difficulty | Win Rate | Slips / Run | Unites / Run | SOS Cards / Run |
|---|---|---|---|---|
| 3 | 100% | 0.00 | 0.00 | 0.00 |
| 5 | 100% | 0.03 | 0.15 | 0.00 |
| 7 | 100% | 3.22 | 2.54 | 0.00 |
| 9 | 42% (65% w/ slips) | 4.73 | 4.88 | 1.16 |
| VP (12 cogs) | 95% | 3.96 | 3.48 | 0.17 |

Consumables scale naturally with difficulty based on expected damage and survival penalties, requiring no hardcoded mode exemptions.

## Search Budget Calibration (`PANEL_BUDGET = 24`)

Coordinate ascent evaluation budget in `hybrid.climb` (250 runs/cell, paired seeds):

| Budget | Block A Win Rate | Block B Win Rate | Slips / Run | Latency |
|---|---|---|---|---|
| 8 | 88.8% | 85.2% | 18.4 | 1.9 ms |
| 16 | — | 95.6% | 17.7 | 2.7 ms |
| 20 | 98.4% | 98.4% | 16.0 | 5.0 ms |
| **24** | — | **99.2%** | **14.5** | **7.0 ms** |
| 30 | 98.4% | — | 13.0 | 8.6 ms |

Budget 8 starved targeted heuristic probes (`PROBE_CHEAPEST_KILL`) that execute following per-track coordinate sweeps. Increasing the budget to 24 improved win rates by 14 percentage points ($p < 0.001$) and reduced slip usage by allowing low-cost gag kills to evaluate.

## Accuracy and Prevention Terms

### `_quick_score` Rank Correlation with True Win Probability

Evaluated across candidate moves per track with independent Monte Carlo rollouts ($K=16$, independent seeds):

| Difficulty | Tested Positions | Rank Correlation ($\rho$) | Best Action Picked | Scorer Win Rate | Random Pick |
|---|---|---|---|---|---|
| 5 | 3 | +0.696 | 3/3 (100%) | 1.000 | 0.990 |
| 7 | 13 | +0.701 | 13/13 (100%) | 1.000 | 0.977 |
| 9 | 94 | +0.545 | 88/94 (93.6%) | 0.987 | 0.887 |

`_quick_score` captures 96–100% of the win-rate gap between random choice and Monte Carlo optimality.

### Prevention Weight Optimization (`QUICK_W["prevent"] = 9.0`)

Difficulty 9 candidate ranking sensitivity to `prevent` weight:

| prevent Weight | Rank Correlation ($\rho$) | Best Action Picked | Performance Gap Captured |
|---|---|---|---|
| 4.0 | +0.269 | 49/99 (49%) | 38% |
| 6.0 | +0.418 | 69/96 (72%) | 80% |
| **9.0** | **+0.545** | **88/94 (94%)** | **96%** |
| 12.0 | +0.516 | 91/97 (94%) | 97% |
| 18.0 | +0.514 | 92/98 (94%) | 97% |
| 30.0 | +0.478 | 94/99 (95%) | 97% |

Lowering `prevent` below 9.0 degrades ranking correlation ($\rho = 0.269$ at 4.0). `prevent = 9.0` anchors the plateau.

### `SLEEPERS_WAKE_IN_TURN`
Evaluates whether lured cogs waking during the current round are counted in incoming damage:
- Standard facility battles: Neutral (88.0% vs 86.8%, $p = 0.375$).
- Solo VP high cog density (200 runs/cell, paired seeds):
  - 16 cogs/round: **93.0% vs 66.5%** ($+58/-5, p < 0.001$).
  - 20 cogs/round: **26.5% vs 15.0%** ($+40/-17, p = 0.003$).

Retained as active (`True`).

## Scarcity and Conservation Pricing

### Scarcity Formula
$$\text{scarcity\_cost} = \frac{\text{SCARCITY\_UNITS}}{\min(\text{inventory}, \text{carry\_limit})}$$

- `SCARCITY_UNITS = 20`: Swept over $\{0, 20, 60, 150\}$; win rates were statistically indistinguishable due to damage and prevention terms dominating the objective ($\approx 95\%$ of score weight).
- `SCARCITY_USES_HELD_COUNT = True`: Evaluates held inventory rather than static capacity limit. Yields $2.4\%$ reduction in gags consumed with neutral win rates across 1,000 paired runs (88.0% vs 88.4%, $p = 0.454$).

### Split Price Weights: `price` vs `spend`
Initially, `QUICK_W["price"]` multiplied gags, pink slips, and SOS cards simultaneously, causing gag conservation sweeps to inadvertently unprice consumables.

`_score_leaf` partitions price into two independent multipliers:
1. `price = 1.0`: Multiplies standard gag unit costs and horizon scaling ($1 + \eta \cdot \text{cogs\_remaining}$).
2. `spend = 1.0`: Multiplies consumable costs (`FIRE_PRICE`, `SOS_PRICE`).

Ablation with consumables active:

| Gag `price` | Win Rate | Gags Consumed |
|---|---|---|
| 0.0 | 86.8% (ns) | 15.5 |
| **1.0** | **88.0%** | **14.0** |
| 2.0 | 87.2% (ns) | 11.9 (15% reduction) |
| 4.0 | 82.0% ($p = 0.003$) | 10.4 |

## Policy and Observation Architecture Invariants

1. **Learned Plan Ranker Removal**: An auxiliary neural network previously shortlisted candidate plans. Labels generated from 16 Monte Carlo rollouts had a standard error of $\approx 7.8$ on plan spreads of $\approx 3.5$, resulting in noisy supervision that eliminated optimal plans (e.g. 2 Foghorns + 2 Aoogahs). Shortlisting was restored to arithmetic `_cheap_score`.
2. **Observation Version 3**: Evaluated 306-dimension observation (adding absolute laff scalars) across 9 paired seeds (2,250 runs): win rate was neutral (73.6% vs 74.1%, $p = 0.478$). `OBS_VERSION = 3` is retained in the environment; shipped model retains 302-dimensional weights.
3. **Model Promotion Criteria**: Fresh policies showing marginal lifts over shipped weights ($+1.2\%$ to $+4.0\%$) failed paired significance tests ($p = 0.076$ to $0.664$). Baseline policy retained.
