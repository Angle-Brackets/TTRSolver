"""
Does the solver actually play better than picking at random?

    python -m solver.search.demo              # one narrated fight
    python -m solver.search.demo --compare    # solver vs. random win rates

The narrated run prints, for each round, the action expectimax chose, its
expected value, and the gap to the runner-up. The gap is the interesting
column: a gap near zero means the decision didn't matter and you shouldn't
read anything into the choice; a large gap means the position has a real
right answer.

Every number here is transcribed data -- no synthetic stand-ins remain.
Cog frequency/damage/accuracy come from the strategy guide's appendices
(still pending a wiki re-check, see docs/data-confidence.md); Lure
durations and accuracy come from the TTR wiki.
"""
import argparse
import random

from .. import data, simulator
from ..state import Track, ToonState, CogState, BattleState
from ..testing import two_flunky_fight
from . import expectimax

MAX_ROUNDS = 30


def _pressed_fight() -> BattleState:
    """A fight tight enough that the policy matters.

    `two_flunky_fight` is won ~100% of the time by literally any policy, so
    it can't tell a solver from a coin flip -- only the laff differential
    says anything. This one is a mixed Bossbot group of escalating levels
    (30/42/56 HP) against a 45-laff toon holding barely enough gags, so
    choosing badly loses.

    Micromanager and The Big Cheese are deliberately absent: each has a
    [TODO] cell in its attack tables, so including one would make the whole
    fight unevaluable rather than merely hard.
    """
    toon = ToonState(
        laff=45, max_laff=45,
        track_exp={Track.THROW: 7, Track.SOUND: 7, Track.LURE: 7},
        gag_counts={
            (Track.THROW, 3): 4,
            (Track.THROW, 4): 2,
            (Track.SOUND, 4): 2,
            (Track.LURE, 2): 3,
        },
    )
    cogs = [
        CogState(cog_type=kind, department="bossbot", level=level,
                 hp=data.cog_max_hp(level), max_hp=data.cog_max_hp(level))
        for kind, level in (("flunky", 4), ("pencil_pusher", 5), ("yesman", 6))
    ]
    return BattleState(toon=toon, cogs=cogs)


SCENARIOS = {
    "default": two_flunky_fight,
    "pressed": _pressed_fight,
}


def _describe(action) -> str:
    target = "all" if action.target_index is None else f"cog {action.target_index}"
    return f"{action.track.value}/{action.level} -> {target}"


def narrate_fight(depth: int = 2, seed: int = 0, scenario: str = "default") -> None:
    random.seed(seed)
    state = SCENARIOS[scenario]()
    print(f"Start: laff {state.toon.laff}, cogs {[c.hp for c in state.cogs]}  "
          f"(expectimax depth {depth})\n")

    for _ in range(MAX_ROUNDS):
        if state.is_terminal():
            break
        ranked = expectimax.rank_actions(state, depth=depth)
        if not ranked:
            print("No evaluable actions left.")
            break

        value, action = ranked[0]
        gap = value - ranked[1][0] if len(ranked) > 1 else float("inf")
        gap_note = "only option" if gap == float("inf") else f"{gap:+.2f} vs next"

        state, reward, done = simulator.step(state, action)
        print(f"round {state.round_num:2d}  {_describe(action):<24} "
              f"EV {value:+7.2f}  ({gap_note:>16})  "
              f"reward {reward:+6.1f}  laff {state.toon.laff:3d}  "
              f"cogs {[('X' if c.status.is_dead else c.hp) for c in state.cogs]}")
        if done:
            print(f"\nBattle finished: {'WIN' if state.is_win() else 'LOSS'}")
            return
    print("\nHit the round cap without finishing.")


def _play(policy, depth, rng_seed, scenario="default"):
    """Play one fight to completion under `policy`.

    Both policies are held to the same action space. Some actions can't be
    played at all yet -- laying a Trap and then luring the cog onto it hits
    the TODO trap-damage table and raises. Expectimax skips those actions
    automatically (action_outcomes raises, evaluate catches), so the random
    policy retries past them too. Otherwise the comparison would partly be
    measuring which policy stumbles into a data gap, rather than which one
    plays better.
    """
    random.seed(rng_seed)
    state = SCENARIOS[scenario]()

    for _ in range(MAX_ROUNDS):
        if state.is_terminal():
            break
        actions = simulator.legal_actions(state)
        if not actions:
            break

        if policy == "random":
            candidates = list(actions)
            done = None
            while candidates:
                action = random.choice(candidates)
                try:
                    state, _reward, done = simulator.step(state, action)
                    break
                except NotImplementedError:
                    candidates.remove(action)
            if done is None:      # every remaining action was unplayable
                break
        else:
            action = expectimax.best_action(state, depth=depth)
            if action is None:
                break
            state, _reward, done = simulator.step(state, action)

        if done:
            break
    return state


def compare(trials: int = 50, depth: int = 2, scenario: str = "default") -> None:
    print(f"{trials} fights per policy, expectimax depth {depth}, "
          f"scenario '{scenario}'\n")
    print(f"{'policy':<12}{'win rate':>10}{'mean laff left':>16}")
    for policy in ("random", "expectimax"):
        wins = 0
        laff_total = 0
        for i in range(trials):
            final = _play(policy, depth, rng_seed=i, scenario=scenario)
            if final.is_win():
                wins += 1
                laff_total += final.toon.laff
        mean_laff = (laff_total / wins) if wins else 0.0
        print(f"{policy:<12}{wins / trials:>9.0%}{mean_laff:>16.1f}")
    print("\n(mean laff left is over winning fights only)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", action="store_true",
                        help="run the solver-vs-random win rate comparison")
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="default",
                        help="'pressed' is a harder fight that actually "
                             "discriminates between policies")
    args = parser.parse_args()

    if args.compare:
        compare(trials=args.trials, depth=args.depth,
                scenario=args.scenario)
    else:
        narrate_fight(depth=args.depth, seed=args.seed,
                      scenario=args.scenario)


if __name__ == "__main__":
    main()
