"""
Random-policy demo run: `python -m solver.demo`

Plays one fight by picking uniformly at random from legal_actions() each
round and printing the trace. This is a "does the round loop hold
together" demo, not a solver and not a benchmark -- it runs under
solver.testing.synthetic_bossbot_accuracy(), so the cog hit rates in
the output are FAKE. Don't read anything strategic into the result.
"""
import random

from . import simulator
from .testing import synthetic_bossbot_accuracy, two_flunky_fight

MAX_ROUNDS = 20


def run_random_policy(seed: int = 0, max_rounds: int = MAX_ROUNDS) -> None:
    random.seed(seed)
    state = two_flunky_fight()
    print(f"Start: toon laff={state.toon.laff}, "
          f"cogs hp={[c.hp for c in state.cogs]}")

    for _ in range(max_rounds):
        if state.is_terminal():
            break
        actions = simulator.legal_actions(state)
        if not actions:
            print("No legal actions left, stopping.")
            break
        action = random.choice(actions)
        state, reward, done = simulator.step(state, action)
        print(f"round={state.round_num:2d}  action={action.track.value}/{action.level} "
              f"-> target={action.target_index}  reward={reward:+.1f}  "
              f"toon laff={state.toon.laff}  "
              f"cogs hp={[('DEAD' if c.status.is_dead else c.hp) for c in state.cogs]}")
        if done:
            outcome = "WIN" if state.is_win() else "LOSS"
            print(f"Battle finished: {outcome}")
            break


if __name__ == "__main__":
    with synthetic_bossbot_accuracy():
        run_random_policy()
