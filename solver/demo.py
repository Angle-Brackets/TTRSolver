"""
Random-policy demo run: `python -m solver.demo`

Plays one fight by picking uniformly at random from legal_actions() each
round and printing the trace. This is a "does the round loop hold
together" demo, not a solver and not a benchmark. For a policy that
actually plays well, see `python -m solver.search.demo`.
"""
import random

from . import simulator
from .testing import two_flunky_fight

MAX_ROUNDS = 20


def _cog_str(cog) -> str:
    if cog.status.is_dead:
        return "DEAD"
    tags = ""
    if cog.status.lured:
        tags += f" lured({cog.status.lure_rounds_remaining})"
    if cog.status.trapped:
        tags += " trapped"
    return f"{cog.hp}{tags}"


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

        # Some legal actions still can't be resolved -- luring a trapped cog
        # needs per-level Trap damage, which is [TODO]. Retry past those
        # rather than dying, so the demo exercises the rest of the loop.
        reward = done = None
        candidates = list(actions)
        while candidates:
            action = random.choice(candidates)
            try:
                state, reward, done = simulator.step(state, action)
                break
            except NotImplementedError:
                candidates.remove(action)
        if done is None:
            print("Every remaining action depends on [TODO] data, stopping.")
            break

        print(f"round={state.round_num:2d}  action={action.track.value}/{action.level} "
              f"-> target={action.target_index}  reward={reward:+.1f}  "
              f"toon laff={state.toon.laff}  "
              f"cogs hp={[_cog_str(c) for c in state.cogs]}")
        if done:
            outcome = "WIN" if state.is_win() else "LOSS"
            print(f"Battle finished: {outcome}")
            break


if __name__ == "__main__":
    run_random_policy()
