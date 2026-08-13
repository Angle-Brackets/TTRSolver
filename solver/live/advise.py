"""Watch a battle and say what to do.

    python -m solver.live.advise                  # follow the screen
    python -m solver.live.advise --once           # read one frame, advise
    python -m solver.live.advise --objective speedrun

Everything upstream of this is about *knowing* the battle; this is the
part that answers the question the project exists for. It follows the
screen, assembles a BattleState whenever the picture is complete, runs
the solver, and prints the move.

WHEN IT STAYS QUIET
-------------------
A state is only built when every part of it is known. If a cog's face is
not in the head library, or the gag menu is closed, or the Local API is
not answering, it says which and waits. It never advises from a state it
had to guess at -- a recommendation is worth having only if the fight it
was computed for is the fight being played.

The reader is fast enough to run every poll, but the solver is not, so
the search runs only when the battle actually changes: a cog defeated,
damage landing, a new fight starting. Between those, the previous answer
still stands.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import threading
import time
from typing import Callable, List, Optional

from .. import data
from ..search import objective as objectives
from .session import build_state, describe
from .watch import BattleWatcher, Event

# Events that change the position. Anything else -- a cog identified, a
# reading settling -- leaves the previous advice valid.
RECOMPUTE_ON = {"battle_started", "cog_joined", "cog_defeated", "damage"}

# Depth is capped rather than fixed: the search is given a time budget
# and returns the deepest pass that finished inside it. Cost depends on
# the position far more than on the number -- at depth 2 a two-cog fight
# takes 0.8s and a four-cog fight 27s -- so a fixed depth either stalls
# on a crowded battle or under-searches an easy one.
#
# The budget comes from the game rather than from taste: Toontown runs a
# countdown of about thirty seconds for choosing a gag, so fifteen is
# half the time available and still leaves the answer on screen well
# before it is needed. What that buys, with pruning on and epsilon 0.03:
#
#     1 cog    depth 3   (0.78s)
#     2 cogs   depth 2   (0.48s)
#     3 cogs   depth 2   (4.76s)
#     4 cogs   depth 2   (13.6s)
#
# Fifteen rather than ten specifically so four cogs clear depth 2, which
# is the hardest case the game routinely produces and the one where a
# ply matters most.
DEFAULT_DEPTH = 4
DEFAULT_BUDGET = 15.0

# Dropped probability mass per chance node. Checked against an exact
# search on four positions: at 0.03 every one picks the same move while
# running 1.5-1.8x faster, and at 0.08 the three-cog position changes its
# answer. Sitting at 0.03 keeps the speedup that has been verified not to
# change a decision.
DEFAULT_EPSILON = 0.03

# Collapse the cog phase into its mean where the objective allows it.
# A ply costs actions x chance outcomes, and this attacks the second
# factor: two cogs reach depth 4 instead of 3, three and four reach 3
# instead of 2. `expectimax.may_collapse` holds it back for `survive`,
# which weights laff heavily enough that averaging damage changes the
# move.
DEFAULT_EXACT_PLIES = 0


class Thinker:
    """Runs searches off the polling thread, newest request wins.

    Polling has to stay at its cadence -- it is what notices a cog dying
    -- and a depth-2 search takes about nine seconds, so the two cannot
    share a thread. Requests supersede rather than queue: if the battle
    moves on while a search is running, the answer it is computing is
    already about a position that no longer exists.
    """

    def __init__(self, on_result: Callable[[str, object], None]):
        self.on_result = on_result
        self._generation = itertools.count()
        self._current = -1
        self._lock = threading.Lock()

    def submit(self, frame, readings, snapshot, objective, depth,
               budget=DEFAULT_BUDGET) -> None:
        with self._lock:
            token = next(self._generation)
            self._current = token
        threading.Thread(target=self._run, daemon=True,
                         args=(token, frame, readings, snapshot, objective,
                               depth, budget)).start()

    def _run(self, token, frame, readings, snapshot, objective, depth,
             budget):
        lines, state = advise(frame, readings, snapshot=snapshot,
                              objective=objective, depth=depth,
                              budget=budget)
        with self._lock:
            superseded = token != self._current
        if not superseded:
            self.on_result(lines, state)

    @property
    def busy(self) -> bool:
        return False


def _snapshot():
    """Local API state, or None with the reason printed."""
    from .ttr_local import LocalAPIError, discover

    try:
        sessions = discover()
        return sessions[0].snapshot() if sessions else None
    except LocalAPIError:
        return None


def _panel(frame):
    from .gagpanel import read_panel

    return read_panel(frame)


def advise(frame, readings, snapshot=None, objective=None,
           depth: int = DEFAULT_DEPTH, budget: float = DEFAULT_BUDGET):
    """(text, state) for what to do now, or (reasons, None)."""
    from ..search import expectimax

    snapshot = snapshot or _snapshot()
    panel = _panel(frame)
    if snapshot is not None and panel is not None:
        # Entitlements from the API, counts from the screen.
        panel = _panel_with_training(frame, snapshot)

    result = build_state(snapshot=snapshot, panel=panel, readings=readings)
    if not result:
        return result.problems, None

    state = result.state
    objective = objective or objectives.DEFAULT
    _value, action = expectimax.best_action_iterative(
        state, depth=depth, objective=objective,
        epsilon=DEFAULT_EPSILON, time_budget=budget,
        exact_plies=DEFAULT_EXACT_PLIES)
    if action is None:
        return ["no legal move -- nothing left to throw"], state
    return [_render(action, state)], state


def _panel_with_training(frame, snapshot):
    from .gagpanel import read_panel

    return read_panel(frame, track_exp=snapshot.track_exp())


def _render(action, state) -> str:
    if action.is_pass:
        return "pass -- wait for the lure to lapse"
    gag = data.gag(action.track, action.level)
    if action.target_index is None:
        return f"{gag.display} on all cogs"
    cog = state.cogs[action.target_index]
    entry = data.cog(cog.department, cog.cog_type)
    return (f"{gag.display} on cog {action.target_index + 1} "
            f"({entry.display}, {cog.hp}/{cog.max_hp} hp)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objective", default="balanced",
                        help="one of " + ", ".join(sorted(objectives.PRESETS)))
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                        help=f"maximum search depth (default {DEFAULT_DEPTH})")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                        help=f"seconds per search; the deepest pass that "
                             f"finishes wins (default {DEFAULT_BUDGET})")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--once", action="store_true",
                        help="read a single frame and stop")
    args = parser.parse_args(argv)

    try:
        objective = objectives.get(args.objective)
    except KeyError as exc:
        print(exc)
        return 2

    watcher = BattleWatcher()
    print(f"advising with the '{objective.name}' objective, up to depth "
          f"{args.depth} within {args.budget}s per search; Ctrl-C to stop")

    if args.once:
        frame = watcher.capture.grab()
        readings = watcher.read_frame(frame)
        _report(frame, readings, objective, args.depth, budget=args.budget)
        watcher.close()
        return 0

    state_of = {"last_problems": []}

    def show(lines, state):
        if state is None:
            if lines != state_of["last_problems"]:
                for line in lines:
                    print(f"  waiting: {line}", flush=True)
            state_of["last_problems"] = lines
            return
        state_of["last_problems"] = []
        print()
        print(describe(state))
        for line in lines:
            print(f"  -> {line}", flush=True)

    thinker = Thinker(show)
    try:
        while True:
            cycle = time.time()
            events = watcher.poll()
            for event in events:
                if event.kind in ("battle_started", "cog_defeated",
                                  "battle_ended"):
                    print(f"  [{event.kind}] {event.detail}", flush=True)
            if any(e.kind in RECOMPUTE_ON for e in events):
                # Hand the frame to the search and carry on polling; a
                # nine-second think must not stall the eye.
                thinker.submit(watcher.capture.grab(),
                               list(watcher.view.cogs), None, objective,
                               args.depth, args.budget)
            time.sleep(max(0.0, args.interval - (time.time() - cycle)))
    except KeyboardInterrupt:
        pass
    watcher.close()
    return 0


def _report(frame, readings, objective, depth,
            last_problems: Optional[List[str]] = None,
            budget: float = DEFAULT_BUDGET) -> List[str]:
    lines, state = advise(frame, readings, objective=objective, depth=depth,
                          budget=budget)
    if state is None:
        # Don't repeat the same complaint every poll.
        if lines != last_problems:
            for line in lines:
                print(f"  waiting: {line}")
        return lines
    print()
    print(describe(state))
    for line in lines:
        print(f"  -> {line}")
    return []


if __name__ == "__main__":
    sys.exit(main())
