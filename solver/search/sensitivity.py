"""
How much does the unknown cog accuracy actually matter?

    python -m solver.search.sensitivity

Cog attack accuracy is the project's one unclosable data gap: TTR does not
publish it, and 4.0.0 rebalanced it away from the Toontown Online values we
have (see docs/data-confidence.md). We can't fix that by looking harder.

What we *can* do is bound its consequences. The stored numbers are real
TTO values, not invention, so the truth is some perturbation of them. This
module sweeps an offset across every cog accuracy cell and asks two
different questions:

  1. Does the solver still choose the same MOVE? If the recommended action
     is stable across a wide accuracy band, the gap doesn't affect advice,
     only the confidence attached to it.
  2. Does the PREDICTED OUTCOME move? Win rate and expected laff loss are
     absolute quantities and will shift; how much tells you how loudly to
     caveat them.

A policy that survives +/-20 accuracy points is worth trusting even though
its inputs are stale. One that flips at +/-5 would mean the solver is
mostly reporting an artifact of old data.

Nothing here is a stand-in for missing data -- it never writes a value that
outlives the measurement, and `perturbed_cog_accuracy` restores the real
tables on exit.
"""
import argparse
import random
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

from .. import data, simulator
from ..state import BattleState
from . import expectimax
from .demo import SCENARIOS

DEFAULT_OFFSETS = (-20, -10, -5, 0, 5, 10, 20)


@contextmanager
def perturbed_cog_accuracy(offset: int):
    """Shift every cog accuracy cell by `offset` points, clamped to 0-100.

    Restores the real tables on exit. An offset of 0 still round-trips the
    tables, so a bug here shows up as the baseline disagreeing with itself.
    """
    saved: List[Tuple[dict, str, list]] = []
    for cogs in data.COG_DEPARTMENTS.values():
        for table in cogs.values():
            acc = table.get("accuracy")
            if not acc:
                continue
            for attack, row in acc.items():
                saved.append((acc, attack, list(row)))
                acc[attack] = [None if v is None else max(0, min(100, v + offset))
                               for v in row]
    try:
        yield
    finally:
        for acc, attack, row in saved:
            acc[attack] = row


def _action_key(action) -> Optional[Tuple]:
    if action is None:
        return None
    return (action.track.value, action.level, action.target_index)


def sample_states(scenario: str, depth: int, seed: int,
                   limit: int = 8) -> List[BattleState]:
    """States the solver actually reaches playing this scenario, so the
    comparison is over positions that come up rather than synthetic ones."""
    random.seed(seed)
    state = SCENARIOS[scenario]()
    seen = []
    for _ in range(limit):
        if state.is_terminal():
            break
        seen.append(state)
        action = expectimax.best_action(state, depth=depth)
        if action is None:
            break
        try:
            state, _reward, done = simulator.step(state, action)
        except NotImplementedError:
            break
        if done:
            break
    return seen


def policy_stability(scenario: str, depth: int, offsets, seed: int) -> Dict:
    """For each offset: how often the recommended move matches the one the
    unperturbed tables give, over the same set of positions."""
    states = sample_states(scenario, depth, seed)
    baseline = [_action_key(expectimax.best_action(s, depth=depth))
                for s in states]

    rows = []
    for offset in offsets:
        with perturbed_cog_accuracy(offset):
            picks = [_action_key(expectimax.best_action(s, depth=depth))
                     for s in states]
        agree = sum(1 for a, b in zip(baseline, picks) if a == b)
        rows.append({
            "offset": offset,
            "agree": agree,
            "total": len(states),
            "first_move_same": bool(picks and picks[0] == baseline[0]),
        })
    return {"states": len(states), "rows": rows}


def outcome_sensitivity(scenario: str, depth: int, offsets, trials: int) -> List[Dict]:
    """Win rate and mean laff remaining under each offset."""
    from .demo import _play

    rows = []
    for offset in offsets:
        with perturbed_cog_accuracy(offset):
            wins, laff = 0, 0
            for i in range(trials):
                final = _play("expectimax", depth, rng_seed=i, scenario=scenario)
                if final.is_win():
                    wins += 1
                    laff += final.toon.laff
        rows.append({
            "offset": offset,
            "win_rate": wins / trials if trials else 0.0,
            "mean_laff": (laff / wins) if wins else 0.0,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="pressed")
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--trials", type=int, default=0,
                        help="fights per offset for the outcome sweep "
                             "(0 skips it; it is much slower)")
    args = parser.parse_args()

    print(f"scenario '{args.scenario}', depth {args.depth}\n")

    print("Does the recommended MOVE change?")
    stability = policy_stability(args.scenario, args.depth,
                                 DEFAULT_OFFSETS, args.seed)
    print(f"  over {stability['states']} positions the solver actually reaches\n")
    print(f"  {'accuracy':>10}  {'same move':>10}  {'opening move':>13}")
    for row in stability["rows"]:
        pct = 100.0 * row["agree"] / row["total"] if row["total"] else 0.0
        tag = "baseline" if row["offset"] == 0 else f"{row['offset']:+d} pts"
        print(f"  {tag:>10}  {row['agree']}/{row['total']} ({pct:3.0f}%)"
              f"  {'same' if row['first_move_same'] else 'CHANGED':>13}")

    if args.trials:
        print("\nDoes the PREDICTED OUTCOME change?")
        print(f"  {args.trials} fights per offset\n")
        print(f"  {'accuracy':>10}  {'win rate':>9}  {'mean laff':>10}")
        for row in outcome_sensitivity(args.scenario, args.depth,
                                       DEFAULT_OFFSETS, args.trials):
            tag = "baseline" if row["offset"] == 0 else f"{row['offset']:+d} pts"
            print(f"  {tag:>10}  {row['win_rate']:>8.0%}  {row['mean_laff']:>10.1f}")
    else:
        print("\n(pass --trials N for the win-rate sweep; it is much slower)")


if __name__ == "__main__":
    main()
