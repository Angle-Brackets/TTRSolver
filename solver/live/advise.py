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

# THE DEPTH ONLY BINDS ON ONE COG. `best_action_iterative` searches
# 1..depth and keeps the deepest pass that FINISHED, so 4 is a cap
# rather than a promise, and measuring what it actually reaches at this
# budget gives 12 boards a row, solo maxed toon, epsilon 0.03:
#
#     cogs  median s   max s  timed out   depth reached
#        1      5.85    9.43          0   4:12
#        2     15.03   15.08         11   3:11  4:1
#        3     15.09   15.20         12   2:10  3:2
#        4     15.19   15.40         12   2:12
#
# From two cogs up the budget binds, not the depth, and on four the
# search always stops at 2 having spent the whole fifteen seconds --
# most of it failing to finish a pass it then throws away.
#
# That is the exact opposite of what the note above this hoped for. It
# reasons that a ply deeper changes the move 40-42% of the time on three
# and four cogs, so "the crowded fights are where any further depth
# would earn its keep". Those are the boards that never get it.
#
# So RAISING `DEFAULT_DEPTH` does nothing above one cog, and lowering it
# to 2 would save nothing either -- the search already stops there. The
# only knob that can buy a ply inside a fixed budget is the pruning; see
# `DEFAULT_EPSILON`.
#
# Worth knowing separately: the panel takes the full fifteen seconds on
# any board with two or more cogs. If that is too slow in play, the
# depth table says a smaller budget costs very little on four cogs.
#
# WHICH RAISES WHETHER THE SEARCH IS WORTH RUNNING AT ALL HERE, since
# `hybrid.climb` answers the same board in a millisecond. Measured, 80
# single battles, four cogs, a WOUNDED toon (45-75 laff, because a maxed
# toon wins every one of these under either engine and separates
# nothing), paired on identical seeds:
#
#     engine        won   mean laff left   s/decision
#     rl         98.8%             56.7         0.007
#     search    100.0%             57.9        14.647
#
#     same outcome on 79 of 80; search only 1, RL only 0, p=1.0
#
# So they AGREE almost always, the search is a hair ahead inside noise,
# and it charges 2088x the time for it. That is a price difference
# rather than a quality one, and on a crowded board the price is fifteen
# seconds of a live fight.
#
# It is NOT a general verdict, and two limits matter. This is single
# battles: nothing here tests husbanding a pouch across floors, which is
# where the two engines have the most room to differ. And the RL engine
# has a failure mode the search cannot have -- its proposals can
# collapse onto one kind of move, which is what pink slips did to it --
# patched by `hybrid.PROBE_WHEN_DEGENERATE` but patched, not absent. The
# search enumerates legal actions and so cannot fail that way.

# Dropped probability mass per chance node. Checked against an exact
# search on four positions: at 0.03 every one picks the same move while
# running 1.5-1.8x faster, and at 0.08 the three-cog position changes its
# answer. Sitting at 0.03 keeps the speedup that has been verified not to
# change a decision.
DEFAULT_EPSILON = 0.03

# RAISING IT BUYS DEPTH THAT DOES NOT CHANGE THE PLAY. Since the depth
# cap does not bind above one cog (see above), pruning is the only knob
# that can reach a deeper pass inside the budget -- so it was measured,
# 14 boards a row at the panel's 15s, against a reference of epsilon
# 0.03 given 60s:
#
#     cogs  epsilon        depth reached   agrees with ref
#        3      ref                 3:14        --
#             0.03                 2:14        13/14
#             0.08          2:5 3:7 4:2        13/14
#             0.15          2:3 3:9 4:2        11/14
#        4      ref              2:7 3:7        --
#             0.03                 2:14        14/14
#             0.08             2:13 3:1        14/14
#             0.15             2:11 3:3        12/14
#
# 0.08 is a real gain in depth at no cost in agreement: three-cog boards
# go from every one stuck at depth 2 to seven reaching 3 and two
# reaching 4. 0.15 goes deeper still and starts disagreeing, which is
# the accuracy being spent.
#
# THEN THE GAMES SAID IT DOES NOT MATTER. 42 paired single battles,
# three cogs, maxed toon, 15s a decision -- the regime where 0.08 buys
# the ply -- came out 41 TIED, one better, none worse, +0.40 laff,
# p=1.0. A four-cog run at 2s was 117 tied of 120, but that one proves
# nothing: at 2s neither epsilon gets past the same shallow pass, so it
# was the wrong regime to ask in.
#
# So 0.03 stays, on the grounds that nothing justifies moving it rather
# than that 0.08 was refuted. The likely reason for all the ties is that
# a maxed toon against three cogs is not a CLOSE position, and a deeper
# search only changes an answer that was nearly balanced. If the panel
# is ever pointed at close positions -- low laff, or a boss -- this is
# worth asking again, in that regime rather than this one.

# Collapse the cog phase into its mean where the objective allows it.
# A ply costs actions x chance outcomes, and this attacks the second
# factor: two cogs reach depth 4 instead of 3, three and four reach 3
# instead of 2. `expectimax.may_collapse` holds it back for `survive`,
# which weights laff heavily enough that averaging damage changes the
# move.
DEFAULT_EXACT_PLIES = 0


def first_answer(state, reject=None):
    """The trained policy's move, evaluated in milliseconds."""
    try:
        import random
        from ..search import hybrid

        hybrid.LAST_UNITE = None
        plan = hybrid.climb(state, random.Random(0), budget=24,
                            reject=frozenset(reject or ()))
        chosen = hybrid.LAST_UNITE
        unite_str = ""
        if chosen is not None:
            from .. import unites as unites_mod
            unite_str = unites_mod.describe(chosen)
    except Exception:
        return None, ""
    action = plan[0] if plan else None
    return action, unite_str


_EXECUTOR = None


def _pool():
    global _EXECUTOR
    if _EXECUTOR is None:
        from concurrent.futures import ProcessPoolExecutor
        _EXECUTOR = ProcessPoolExecutor(max_workers=1)
    return _EXECUTOR


def search_in_child(state, objective_name: str, depth: int,
                    budget: float, allow_level_7: bool):
    """Run search in a separate process to avoid holding GIL on the UI thread."""
    from .. import state as state_mod
    from ..search import expectimax, objective as objectives
    from .. import unites as unites_mod

    state_mod.ALLOW_LEVEL_7 = bool(allow_level_7)
    objective = objectives.PRESETS.get(objective_name, objectives.DEFAULT)

    def _value_of(st):
        value, act = expectimax.best_action_iterative(
            st, depth=depth, objective=objective,
            epsilon=DEFAULT_EPSILON, time_budget=budget,
            exact_plies=DEFAULT_EXACT_PLIES)
        return act, (float("-inf") if act is None else value)

    global LAST_UNITE
    LAST_UNITE = None
    if unites_mod.OFFER_UNITES_IN_SEARCH:
        LAST_UNITE, action = unites_mod.best_with_unite(state, _value_of)
        if LAST_UNITE is not None:
            unites_mod.apply(state.toons[0], LAST_UNITE)
    else:
        action, _value = _value_of(state)

    if action is None:
        return ["no legal move -- nothing left to throw"], state, None, None
    # THE UNITE COMES BACK IN THE RETURN VALUE, not in `LAST_UNITE`.
    # This function runs in a CHILD PROCESS, so the global it sets is
    # set over there and the panel's process never sees it -- the search
    # path could not recommend a unite at all, silently, while the
    # policy path (in-process) could. The global is still assigned for
    # the in-process callers that read it.
    return [_render(action, state)], state, action, LAST_UNITE


class Thinker:
    """Runs searches off the polling thread, newest request wins.

    Polling has to stay at its cadence -- it is what notices a cog dying
    -- and a depth-2 search takes about nine seconds, so the two cannot
    share a thread. Requests supersede rather than queue: if the battle
    moves on while a search is running, the answer it is computing is
    already about a position that no longer exists.
    """

    def __init__(self, on_result: Callable[[list, object, object], None],
                 on_first_answer: Optional[Callable[[object, str, object], None]] = None):
        self.on_result = on_result
        self.on_first_answer = on_first_answer
        self._generation = itertools.count()
        self._current = -1
        self._lock = threading.Lock()

    def submit(self, frame, readings, snapshot, objective, depth,
               budget=DEFAULT_BUDGET, ignore_checksum=False,
               allies=0, fires=0, reject=None) -> None:
        with self._lock:
            token = next(self._generation)
            self._current = token
        threading.Thread(target=self._run, daemon=True,
                         args=(token, frame, readings, snapshot, objective,
                               depth, budget, ignore_checksum,
                               allies, fires, reject)).start()

    def _run(self, token, frame, readings, snapshot, objective, depth,
             budget, ignore_checksum=False, allies=0, fires=0, reject=None):
        try:
            snap = snapshot or _snapshot()
            pnl = _panel(frame)
            if snap is not None and pnl is not None:
                pnl = _panel_with_training(frame, snap)
            res = build_state(snapshot=snap, panel=pnl, readings=readings,
                              ignore_checksum=ignore_checksum, allies=allies,
                              fires=fires)
            if res is None or res.state is None:
                with self._lock:
                    superseded = token != self._current
                if not superseded:
                    # `res is not None`, NOT `res`. `BuildResult.__bool__`
                    # is `state is not None`, so a result carrying the
                    # reasons there is no state is FALSY -- and the
                    # truthiness test therefore threw those reasons away
                    # and substituted "no battle detected" every single
                    # time. The panel's whole job at this moment is to
                    # say what it could not read ("cog 1: level
                    # unreadable", "gag menu not visible"); it said the
                    # one thing that helps nobody instead.
                    self.on_result(
                        res.problems if res is not None
                        else ["no battle detected"], None, None, None)
                return

            state = res.state

            if self.on_first_answer:
                try:
                    quick_act, quick_unite = first_answer(state, reject=reject)
                    with self._lock:
                        superseded = token != self._current
                    if not superseded and quick_act:
                        self.on_first_answer(quick_act, quick_unite, state)
                except Exception:
                    pass

            objective_name = getattr(objective, "name", "balanced")
            allow_level_7 = getattr(state, "allow_level_7", True)

            future = _pool().submit(search_in_child, state, objective_name, depth, budget, allow_level_7)
            lines, state, action, unite = future.result(timeout=budget + 15.0)
        except Exception as exc:            # noqa: BLE001 -- see below
            import traceback

            lines = [f"the search failed: {exc.__class__.__name__}: {exc}",
                     *traceback.format_exc().strip().splitlines()[-3:]]
            state = None
            action = None
            unite = None
        with self._lock:
            superseded = token != self._current
        if not superseded:
            self.on_result(lines, state, action, unite)

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


# The unite the last `advise` call chose, or None. A module global for
# the same reason `hybrid.LAST_UNITE` is one: a unite is not the move,
# so it cannot ride back inside the action, and every caller of this
# already unpacks a fixed 3-tuple.
LAST_UNITE = None


def advise(frame, readings, snapshot=None, objective=None,
           depth: int = DEFAULT_DEPTH, budget: float = DEFAULT_BUDGET,
           ignore_checksum: bool = False, allies: int = 0,
           fires: int = 0):
    """(text, state) for what to do now, or (reasons, None).

    A unite chosen alongside the gag is left in `LAST_UNITE`, the way
    `hybrid.climb` reports one, because it is not an alternative to the
    action and does not belong in the returned move.
    """
    from ..search import expectimax
    from .. import unites as unites_mod

    snapshot = snapshot or _snapshot()
    panel = _panel(frame)
    if snapshot is not None and panel is not None:
        # Entitlements from the API, counts from the screen.
        panel = _panel_with_training(frame, snapshot)

    result = build_state(snapshot=snapshot, panel=panel, readings=readings,
                         ignore_checksum=ignore_checksum, allies=allies,
                         fires=fires)
    if not result:
        return result.problems, None, None

    state = result.state
    objective = objective or objectives.DEFAULT

    def _value_of(st):
        value, act = expectimax.best_action_iterative(
            st, depth=depth, objective=objective,
            epsilon=DEFAULT_EPSILON, time_budget=budget,
            exact_plies=DEFAULT_EXACT_PLIES)
        return act, (float("-inf") if act is None else value)

    # UNITE FIRST, THEN THROW -- the same comparison the policy path
    # makes, through the same helper. This path had none, so TTR could
    # not use a unite at all: they were a wrapper that existed only
    # around `hybrid.climb`, and this overlay runs the exact search.
    #
    # A unite costs no action, so it is not an alternative to the gag
    # and never replaces `action`; it is reported alongside it.
    global LAST_UNITE
    LAST_UNITE = None
    if unites_mod.OFFER_UNITES_IN_SEARCH:
        LAST_UNITE, action = unites_mod.best_with_unite(state, _value_of)
        if LAST_UNITE is not None:
            # In place: the round is played from this state and the
            # unite lands before the gag.
            unites_mod.apply(state.toons[0], LAST_UNITE)
    else:
        action, _value = _value_of(state)
    if action is None:
        return ["no legal move -- nothing left to throw"], state, None
    return [_render(action, state)], state, action


def _panel_with_training(frame, snapshot):
    from .gagpanel import read_panel

    return read_panel(frame, track_exp=snapshot.track_exp())


def track_of(action) -> Optional[str]:
    """The recommended action's slug for the page, or None for a pass.

    "fire" and "sos" are SENTINELS, not gag tracks. The page keys its
    icon and accent off this, so returning None for them showed the
    styling a pass gets -- and firing, calling for help and doing
    nothing should not look alike.

    Both track-less actions have `track=None` with `is_pass` False, so
    the old guard reached `action.track.value` and raised on an SOS.
    That was unreachable until `hybrid._sos_probes` could propose one.

    This is the single implementation; `realms_panel._track_of` defers
    to it, because two panels colouring the same recommendation
    differently would be worse than the coupling.
    """
    if action is None or action.is_pass:
        return None
    if getattr(action, "fire", False):
        return "fire"
    if getattr(action, "sos", None):
        return "sos"
    return action.track.value


def _render(action, state) -> str:
    if action.is_pass:
        return "pass -- wait for the lure to lapse"
    if getattr(action, "fire", False):
        # A FIRE HAS NO TRACK AND NO LEVEL, and `is_pass` is False for
        # it, so every renderer that guards only on `is_pass` reaches
        # `action.track.value` and raises. That was unreachable while
        # nothing read the slip count; it is reachable now.
        if action.target_index is None:
            return "pink slip"
        cog = state.cogs[action.target_index]
        entry = data.cog(cog.department, cog.cog_type)
        return (f"pink slip on cog {action.target_index + 1} "
                f"({entry.display}, {cog.hp}/{cog.max_hp} hp)")
    if getattr(action, "sos", None):
        # LIKE A FIRE, an SOS has no track and no level and `is_pass` is
        # False, so it fell through to `data.gag(None, None)` and raised
        # `no gag at no track (a pass) level 0`. Unreachable while
        # nothing could propose a card; reachable since `_sos_probes`.
        from .. import sos as sos_mod

        card = sos_mod.BY_NAME.get(action.sos)
        if card is None:
            return f"call {action.sos}"
        standing = sum(1 for t in state.toons if t.laff > 0) or 1
        return "call " + sos_mod.describe(card, standing)
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
                # The frame the watcher just graded, for the reason
                # `overlay.run` records: a second grab makes
                # `menu_visible` and `read_panel` disagree about the
                # same check on two different moments.
                thinker.submit(watcher.last_frame or watcher.capture.grab(),
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
