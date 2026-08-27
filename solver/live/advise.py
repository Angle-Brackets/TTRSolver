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
# before it is needed. What that buys, measured on realistic endgame
# loadouts with pruning on, epsilon 0.03 and the cog phase collapsed:
#
#     1 cog    depth 4-7
#     2 cogs   depth 3-4
#     3 cogs   depth 3
#     4 cogs   depth 2-3
#
# Those replace an older set that said depth 3 for one cog and depth 2
# for everything else. They were true when written and several rounds
# of optimisation have since passed; leaving them stale made the search
# look far weaker than it is, which matters because every argument for
# replacing the engine is an argument about buying depth.
#
# How much depth is worth: on the same positions, going a ply deeper
# changes the chosen move 15% of the time on two cogs and 40-42% on
# three and four. That is an upper bound on the benefit -- a changed
# move is not necessarily a better one, and exact values are not
# tractable at this size to say which -- but it does mean the crowded
# fights are where any further depth would earn its keep.
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

    def __init__(self, on_result: Callable[[list, object, object], None]):
        self.on_result = on_result
        self._generation = itertools.count()
        self._current = -1
        self._lock = threading.Lock()

    def submit(self, frame, readings, snapshot, objective, depth,
               budget=DEFAULT_BUDGET, ignore_checksum=False,
               allies=0) -> None:
        with self._lock:
            token = next(self._generation)
            self._current = token
        threading.Thread(target=self._run, daemon=True,
                         args=(token, frame, readings, snapshot, objective,
                               depth, budget, ignore_checksum,
                               allies)).start()

    def _run(self, token, frame, readings, snapshot, objective, depth,
             budget, ignore_checksum=False, allies=0):
        try:
            lines, state, action = advise(frame, readings, snapshot=snapshot,
                                  objective=objective, depth=depth,
                                  budget=budget,
                                  ignore_checksum=ignore_checksum,
                                  allies=allies)
        except Exception as exc:            # noqa: BLE001 -- see below
            # A search that dies takes its thread with it and nothing
            # else notices: no advice appears, which looks exactly like
            # a search still running. Report it as the reason there is
            # no state, which is the channel the caller already reads.
            import traceback

            lines = [f"the search failed: {exc.__class__.__name__}: {exc}",
                     *traceback.format_exc().strip().splitlines()[-3:]]
            state = None
            action = None
        with self._lock:
            superseded = token != self._current
        if not superseded:
            self.on_result(lines, state, action)

    @property
    def busy(self) -> bool:
        return False


# The Local API session, discovered once and kept. `discover()` probes
# six ports and builds fresh clients; calling it per advice cycle made
# the game pop its "allow this app to connect?" consent dialog over and
# over, several times a second, which is unusable. The session is also
# not re-discovered on a whim -- only after a failure, and not more
# often than REDISCOVER_AFTER seconds.
_SESSION = {"client": None, "snapshot": None, "taken": 0.0, "tried": 0.0}
SNAPSHOT_TTL = 5.0          # seconds; laff and training move slowly
REDISCOVER_AFTER = 15.0     # seconds between attempts when not connected


def reset_session() -> None:
    """Forget the cached client, for tests and for a restarted game."""
    _SESSION.update(client=None, snapshot=None, taken=0.0, tried=0.0)


def _snapshot(force: bool = False):
    """Local API state, cached, or None.

    Returns the cached snapshot unless it is older than SNAPSHOT_TTL.
    Nothing here changes fast: laff moves during a fight, but the gag
    training and organic flags that set accuracy do not change at all
    mid-battle, and laff is worth one request every few seconds rather
    than one every poll.
    """
    from .ttr_local import LocalAPIError, discover

    now = time.time()
    if not force and _SESSION["snapshot"] is not None \
            and now - _SESSION["taken"] < SNAPSHOT_TTL:
        return _SESSION["snapshot"]

    if _SESSION["client"] is None:
        if now - _SESSION["tried"] < REDISCOVER_AFTER:
            return _SESSION["snapshot"]
        _SESSION["tried"] = now
        try:
            sessions = discover()
        except LocalAPIError:
            return None
        if not sessions:
            return None
        _SESSION["client"] = sessions[0]

    try:
        snap = _SESSION["client"].snapshot()
    except LocalAPIError:
        # The game may have closed or the toon logged out. Drop the
        # client so the next attempt rediscovers, after the backoff.
        _SESSION["client"] = None
        return None
    _SESSION.update(snapshot=snap, taken=now)
    return snap


def _paid_out() -> bool:
    """Has a fight just paid out, per the Local API?

    The toon's merit totals tick up the moment a battle resolves, so a
    rise is proof the fight is over and arrives immediately -- far
    sooner than the watcher's timer, which has to wait out the longest
    animation it might be looking at.

    It is a one-way signal. Merits only move for a department whose suit
    the toon already owns and only for that department's cogs, so this
    confirms an end and can never rule one out. `False` means "no news",
    never "still fighting".
    """
    global _LAST_MERITS

    snap = _snapshot()
    if snap is None:
        return False
    merits = dict(snap.merits)
    previous, _LAST_MERITS = _LAST_MERITS, merits
    if previous is None:
        return False
    return any(current > previous.get(dept, (0, 0))[0]
               for dept, (current, _target) in merits.items()
               if dept in previous)


_LAST_MERITS = None


def _panel(frame):
    from .gagpanel import read_panel

    return read_panel(frame)


def advise(frame, readings, snapshot=None, objective=None,
           depth: int = DEFAULT_DEPTH, budget: float = DEFAULT_BUDGET,
           ignore_checksum: bool = False, allies: int = 0):
    """(text, state) for what to do now, or (reasons, None)."""
    from ..search import expectimax

    snapshot = snapshot or _snapshot()
    panel = _panel(frame)
    if snapshot is not None and panel is not None:
        # Entitlements from the API, counts from the screen.
        panel = _panel_with_training(frame, snapshot)

    result = build_state(snapshot=snapshot, panel=panel, readings=readings,
                         ignore_checksum=ignore_checksum, allies=allies)
    if not result:
        return result.problems, None, None

    state = result.state
    objective = objective or objectives.DEFAULT
    _value, action = expectimax.best_action_iterative(
        state, depth=depth, objective=objective,
        epsilon=DEFAULT_EPSILON, time_budget=budget,
        exact_plies=DEFAULT_EXACT_PLIES)
    if action is None:
        return ["no legal move -- nothing left to throw"], state, None
    return [_render(action, state)], state, action


def _panel_with_training(frame, snapshot):
    from .gagpanel import read_panel

    return read_panel(frame, track_exp=snapshot.track_exp())


def track_of(action) -> Optional[str]:
    """The recommended gag's track name, for a caller that wants to
    colour it. None for a pass or a pink slip, which have no track."""
    if action is None or action.is_pass or getattr(action, "fire", False):
        return None
    return action.track.value


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
    parser.add_argument("--no-level-7", action="store_true",
                        help="advise as if the pouch held no level 7 "
                             "gags. They are the ones worth saving, so "
                             "a player holding them for the boss wants "
                             "advice that does not spend them")
    parser.add_argument("--ignore-checksum", action="store_true",
                        help="advise even when the gag counts disagree "
                             "with the menu's own total. UNSAFE: the "
                             "pouch is known wrong, so the advice is for "
                             "a slightly different fight")
    args = parser.parse_args(argv)

    # A module global read at move-generation time, so setting it here
    # covers the search, the climb and the scorers without threading a
    # flag through any of them.
    if args.no_level_7:
        from .. import state as state_mod
        state_mod.ALLOW_LEVEL_7 = False

    try:
        objective = objectives.get(args.objective)
    except KeyError as exc:
        print(exc)
        return 2

    watcher = BattleWatcher(battle_over=_paid_out)
    # Say what is being looked at. Reading the whole screen instead of
    # the game is silently wrong rather than loudly broken -- it reports
    # cogs off wallpaper -- so it should never be a thing you have to
    # go and discover.
    from .window import describe as describe_window

    print(describe_window())
    if args.ignore_checksum:
        print("  !! --ignore-checksum: gag counts that disagree with the "
              "menu's own total will be used anyway. The pouch may be "
              "wrong, and so may the advice.")
    print(f"advising with the '{objective.name}' objective, up to depth "
          f"{args.depth} within {args.budget}s per search; Ctrl-C to stop")

    if args.once:
        frame = watcher.capture.grab()
        readings = watcher.read_frame(frame)
        # Same gate as the polling path. Without it `--once` reported
        # cogs off any teal-ish scenery, which is how the false
        # positives were first mistaken for a real read.
        if not watcher.in_battle(frame, bool(readings)):
            readings = []
        _report(frame, readings, objective, args.depth, budget=args.budget,
                ignore_checksum=args.ignore_checksum)
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
                               args.depth, args.budget,
                               args.ignore_checksum)
            time.sleep(max(0.0, args.interval - (time.time() - cycle)))
    except KeyboardInterrupt:
        pass
    watcher.close()
    return 0


def _report(frame, readings, objective, depth,
            last_problems: Optional[List[str]] = None,
            budget: float = DEFAULT_BUDGET,
            ignore_checksum: bool = False) -> List[str]:
    lines, state, _action = advise(frame, readings, objective=objective, depth=depth,
                          budget=budget, ignore_checksum=ignore_checksum)
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
