"""
Decision-making layer: given a battle state, what should the toon do?

Built on `solver.outcomes.action_outcomes`, which enumerates the exact
probability distribution over next states, rather than on
`solver.simulator.step`, which samples one. Expectimax needs the former.

  expectimax.py -- depth-limited expectimax with memoization, plus the
                   leaf heuristic used at the depth cutoff
"""

__all__ = ["expectimax"]
