# Learned Leaf Evaluation for Expectimax

Specification, training, and benchmarking of the fitted leaf evaluation function (`solver/search/fitted.py`) replacing the heuristic baseline (`expectimax.heuristic_value`).

## Overview & Performance Summary

Stage 0 linear model trained on 5,000 exact expectimax labels (`tools/fit_heuristic.py`):

| Metric | Hand-Written Baseline | Stage 0 Fitted Model |
|---|---|---|
| Move Agreement vs Exact | 78% (86% on benchmark) | **92%** |
| Expected Value Regret | 243.8 | **7.4** |
| 120-Fight Search Time | 10.6s | **6.1s** |
| Hold-Out MAE (526 positions) | 95.9 | **25.6** |
| Correlation ($r$) | 0.07 | **0.86** |
| Pairwise Move Ordering Accuracy | 52% | **91%** |

Accurate leaf estimation narrows star1/star2 bounds, accelerating alpha-beta cutoffs and reducing total search time.

## Analysis of Hand-Written Heuristic Baseline

The baseline heuristic evaluated:
$$\text{heuristic\_value}(s) = 100 \cdot \text{cog\_progress} - 100 \cdot (1 - \text{laff\_kept})$$

Evaluated against exact `solve()` on 45 test positions:
- **Mean Bias**: $-100.2$ points (heuristic mean $-6.5$ vs true mean $+93.7$). The heuristic centers on 0 for untouched states, omitting the $+100$ terminal win bonus that dominates winnable positions. Cutoff nodes scored $\approx -6$ against terminal $+100$, systematically distorting minimax line selection against depth-limited horizons.
- **Structural Blind Spots**:
  1. Aggregated Cog HP: Summing HP obscures focus-fire vs spread distributions and one-shot kill thresholds.
  2. Inventory Blindness: Pouch count and damage capacity are omitted.
  3. Status Omission: Lure duration and armed trap states are unvalued.

| Board Position | Hand-Written | Exact Value |
|---|---|---|
| Focus fire (1 cog near death) | -18.8 | 68.5 |
| Spread damage (identical total HP) | -18.8 | **89.8** |
| 4 gags against 1 cog | -35.4 | 99.0 |
| 1 gag against 1 cog | -35.4 | **92.0** |
| Lured (3 rounds remaining) | -35.4 | 99.6 |
| Unlured (awake) | -35.4 | 98.9 |

## Computational Complexity & Latency

Profiling on 3-cog depth-2 expectimax (81,202 leaf evaluations per search):

| Evaluator | Latency per Call | Latency per Search | Search Share |
|---|---|---|---|
| Hand-written baseline | 1.08 µs | 0.09s | 2.0% |
| Linear model (~100 features) | 1.05 µs | 0.09s | 2.0% |
| MLP (100-64-32-1, unbatched) | 6.70 µs | 0.50s | 11.0% |
| MLP (batched $\times 256$) | 0.44 µs | 0.04s | 0.9% |

Linear evaluation in pure Python incurs zero search overhead relative to baseline.

## Ground-Truth Label Generation & Terminal Conditions

Solo battles form a finite DAG because gags are permanently consumed, allowing `expectimax.solve()` to generate ground-truth labels.

### Zero-Damage Defeat Condition
A position with no remaining capacity to inflict damage terminates as an immediate defeat (`BattleState.is_terminal` via `can_still_damage()`):
- Empty pouch: Defeat.
- Utility gags only (Lure, Toon-Up): Defeat.
- Trap without Lure (solo): Defeat.
- Trap and Lure held: Non-terminal (activatable sequence).
- Lure held with cog already trapped: Non-terminal.

Previously, exhausted states defaulted to heuristic leaf values (+47.6), corrupting training labels with circular estimates. Immediate terminal classification resolved this bias:

| Position | Pre-Fix Value | Post-Fix Value | Search Speedup |
|---|---|---|---|
| Toon-Up + Trap only (1 cog) | +87.8 | 0.0 | $400\times$ |
| Toon-Up + Trap only (2 cogs) | +55.9 | 0.0 | $260\times$ |
| Lure-heavy, no attacks | +99.4 | 0.0 | $2200\times$ |
| Damage gags exhausted mid-line | +53.3 | **-101.8** | $4\times$ |
| Standard mixed pouch | +83.5 | +83.5 | $1.2\times$ |

### Pass Action Termination
Passing is legal when a cog is lured and no immediate attack is advantageous (e.g. waiting for lure expiration to place higher trap). Unlured passes consume `state.free_passes`; lured passes decrement lure duration. The lexicographic measure `(gags, lure rounds, free passes)` strictly decreases, preserving DAG termination.

## Model Training and Feature Engineering

Trained on 5,000 exact labels, evaluated on 526 hold-out positions:

| Model Architecture | Bias | MAE | Correlation ($r$) | Ordering Accuracy |
|---|---|---|---|---|
| Hand-written baseline | -51.0 | 95.9 | 0.07 | 52% |
| Linear (15 base features) | +10.1 | 50.6 | 0.69 | 90% |
| Linear (+ budget features) | **+0.9** | **25.6** | **0.86** | **91%** |

Adding `damage_budget_ratio` and `cannot_finish` resolved proxy inflation on `gags_ratio` (weight dropped from 244 to 12.75) and halved MAE.

### Search Envelope Interaction
The fitted evaluator outputs negative values for unwinnable states that previous heuristic baselines marked positive. The star1/star2 pruning floor queries the evaluator's empirical minimum via `expectimax.heuristic_floor` rather than assuming fixed $[0, 100]$ bounds, preventing unsound branch cutoffs.

### Feature Specification

Feature representation (~100 floats):
- Laff metrics: `laff / max_laff`, raw laff.
- Cog array ($4 \times$ zero-padded slots): `hp / max_hp`, level, department one-hot, lured status, trapped status, lure duration.
- Inventory: Gag counts per `(track, level)` (42 floats), `track_exp` (6 floats).
- Contextual conjunctions:
  - `trapped AND lure_gags > 0` (armed trap activation).
  - One-shot kill threshold indicators.
  - Lethal incoming damage indicator (`laff <= max_round_incoming_damage`).
  - `damage_budget_ratio`: Total damage in pouch / remaining cog HP.

## Model Architecture Comparison

Evaluated on 500 training positions and 97 hold-out positions:

| Architecture | Parameters | Train MAE | Hold-Out MAE |
|---|---|---|---|
| Linear (Stage 0, Shipped) | 15 | 15.2 | **18.9** |
| Quadratic | 135 | 9.0 | 21.9 |
| MLP-16 | 273 | 9.4 | 19.3 |
| MLP-32 | 545 | 8.1 | **18.5** |
| MLP-64 | 1089 | 7.2 | 22.3 |

Nonlinear models overfit on limited sample sizes (MLP-64 degraded to 22.3 hold-out MAE). The linear model with explicit conjunction features achieves parity with MLP-32 while requiring zero runtime dependencies.
