"""A reinforcement-learning view of a cog battle.

Standard library only, like the rest of `solver/`. Torch lives in
`tools/train_ppo.py` and never here -- the environment is just the
simulator wearing a different interface.
"""
from .env import ACTIONS, BattleEnv, action_at, encode

__all__ = ["ACTIONS", "BattleEnv", "action_at", "encode"]
