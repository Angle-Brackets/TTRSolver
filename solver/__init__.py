"""Toontown solo-toon-vs-cogs battle simulator.

The simulator layer only -- `simulator.step(state, action)` is the
environment an expectimax / value-iteration / RL solver plugs into.

Layout:
  state.py      -- BattleState / ToonState / CogState / Action
  mechanics.py  -- accuracy, damage, cog attack selection, lure wake-up
  simulator.py  -- legal_actions() and step()
  data/         -- hand-entered game tables, each tagged with a
                   confidence level (see docs/data-confidence.md)
  testing.py    -- clearly-labeled synthetic stand-ins for data that is
                   still TODO, so code paths can be exercised end-to-end
"""

__all__ = ["state", "mechanics", "simulator", "data"]
