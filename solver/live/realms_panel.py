"""The live panel, driven by Toontown Realms instead of by pixels.

    python -m solver.live.realms_panel
    python -m solver.live.realms_panel --objective survive --budget 8

A SECOND PANEL, deliberately. `overlay.Worker` polls a screen capture,
runs `find_plates`, reads a gag menu and hedges every number it produces
with a confidence. None of that applies here: `realms_session` is handed
typed fields by the server. Threading a second world through the TTR
worker would put "if realms:" through the one module whose entire job is
being careful about pixels, and the TTR panel would then be able to
break from an edit made for a game it does not read.

WHAT IT SHARES, AND WHY THAT IS NOT THE SAME THING. `Model`, `CogRow`
and `model_json` are imported and never modified. They are the VIEW --
a description of what a panel shows -- and both panels showing the same
thing is the point rather than a leak. The built React app renders this
with no changes at all. What is not shared is every line of reading.

WHAT THE PLAYER SEES DIFFERENTLY, all of it because the data is better:

  * cog names are never "?" and the picker is never needed -- identity
    comes from `setDNAString`, so there is nothing to guess at
  * health is exact. The TTR panel shows a fraction read off a green
    bar; this shows 20/20 because the server said 20/20
  * LURED is read from the battle roster rather than marked by hand
  * party size is read from `setMembers` rather than asked for

Realms balance must not reach `solver/data/` -- see `docs/realms.md`.
This panel reads a POSITION and prices it with TTR's rules, which is
also why its damage numbers will not match what Realms rolls.
"""
from __future__ import annotations

import argparse
import queue
import threading
import time
from itertools import count
from pathlib import Path
from typing import List, Optional

from .overlay import ADVICE_LINGER, CogRow, Model
from .panel import DIST, PULL_INTERVAL_MS, model_json

POLL_INTERVAL = 0.4

# Realms sends a field the moment it changes, so unlike the screen
# readers there is no flicker to smooth over and no agreement count. A
# search is started when the POSITION changes, which is what these
# summarise.
DEFAULT_DEPTH = 4
DEFAULT_BUDGET = 12.0
DEFAULT_EPSILON = 0.03


def _position_key(state) -> tuple:
    """What counts as a changed fight, for deciding to search again.

    Laff, each cog's health and lure, and the pouch. Deliberately NOT
    the battle's state string: it cycles through several values per
    round and would restart the search mid-think every time.
    """
    if state is None:
        return ()
    return (state.toon.laff,
            tuple(sorted((k[0].value, k[1], n)
                         for k, n in state.toon.gag_counts.items())),
            tuple((c.hp, c.status.lured, c.status.is_dead)
                  for c in state.cogs),
            state.allies_standing)


def _render(action, state) -> str:
    """Advice as one line. Reuses the TTR panel's wording where it can.

    Two panels phrasing the same recommendation differently would be a
    worse outcome than the coupling, and this imports a formatter rather
    than any of the reading.
    """
    try:
        from .advise import _render as shared

        return shared(action, state)
    except Exception:                   # pragma: no cover - defensive
        if action is None or getattr(action, "is_pass", False):
            return "pass"
        return f"{action.track.value} {action.level}"


def rows_from_state(state) -> List[CogRow]:
    """`CogRow`s from a searched state.

    `identified` is always True and `choices` always empty: the cog came
    from `setDNAString`, so the panel has nothing to ask the player and
    the picker never appears.
    """
    from .. import data

    out: List[CogRow] = []
    for index, cog in enumerate(state.cogs):
        entry = data.cog(cog.department, cog.cog_type)
        health = (cog.hp / cog.max_hp) if cog.max_hp else 0.0
        out.append(CogRow(name=entry.display, level=cog.level,
                          health=max(0.0, min(1.0, health)),
                          art_key=f"{cog.department}-{cog.cog_type}",
                          department=cog.department, index=index,
                          lured=cog.status.lured, choices=[],
                          identified=True))
    return out


class RealmsWorker(threading.Thread):
    """Reads the cluster, searches when the position moves, posts a Model."""

    def __init__(self, outbox: "queue.Queue", objective, depth: int,
                 budget: float, listener=None):
        super().__init__(daemon=True)
        self.outbox = outbox
        self.objective = objective
        self.objective_name = getattr(objective, "name", "balanced")
        self.depth = depth
        self.budget = budget
        self.listener = listener
        self.model = Model()
        # Owned here rather than on the Model the UI holds, for the same
        # reason `overlay.Worker` owns them: `_post` ships a fresh copy
        # every cycle and anything written onto the UI's model from
        # outside is overwritten within the poll interval.
        from .. import state as state_mod

        self.allow_level_7 = state_mod.ALLOW_LEVEL_7
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._generation = count()
        self._current = -1
        self._last_key: tuple = ()
        self._asked = threading.Event()

    # -- controls -----------------------------------------------------
    def set_objective(self, name: str) -> None:
        from ..search import objective as objectives

        preset = objectives.PRESETS.get(name)
        if preset is None:
            return
        with self._lock:
            self.objective, self.objective_name = preset, name
        self._last_key = ()             # re-search under the new one
        self.ask_now()

    def set_budget(self, seconds) -> None:
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.budget = max(1.0, min(60.0, value))
        self._post()

    def set_level_7(self, allow) -> None:
        from .. import state as state_mod

        with self._lock:
            self.allow_level_7 = bool(allow)
        state_mod.ALLOW_LEVEL_7 = bool(allow)
        self._last_key = ()
        self.ask_now()

    def ask_now(self) -> None:
        self._asked.set()

    def close(self) -> None:
        self._stop.set()

    # -- the loop ------------------------------------------------------
    def run(self) -> None:              # pragma: no cover - needs a cluster
        from . import realms as realms_mod

        if self.listener is None:
            try:
                self.listener = realms_mod.RealmsListener()
                self.listener.connect()
            except realms_mod.RealmsError as exc:
                self.model.problems = [str(exc)]
                self._post()
                return
            self.listener.start()

        next_refresh = 0.0
        while not self._stop.is_set():
            cycle = time.time()
            if cycle >= next_refresh:
                # The stream carries changes only, so anything generated
                # before we attached has never been described.
                try:
                    self.listener.refresh_all()
                    self.listener.refresh_battle_members()
                except Exception:       # pragma: no cover
                    pass
                next_refresh = cycle + 5.0
            try:
                self.tick()
            except Exception as exc:    # noqa: BLE001
                # A worker that dies leaves the panel frozen on its last
                # model, which from the outside is indistinguishable
                # from a fight it cannot read -- no error, no output,
                # just a window that never changes. Report it through
                # the channel the panel already shows.
                self.model.problems = [
                    f"the reader failed: {exc.__class__.__name__}: {exc}"]
                self.model.detected_battle = False
                self._post()
            time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))

    def tick(self) -> None:
        """One poll. Split out from `run` so it is testable with a fake
        listener and no cluster at all."""
        from . import realms_session

        result = realms_session.build_state(self.listener)
        model = self.model
        model.window_found = True
        model.detected_battle = result.state is not None
        model.plates = len(result.state.cogs) if result.state else 0
        model.menu_visible = result.state is not None

        if result.state is None:
            model.problems = list(result.problems)
            model.rows = []
            model.cogs = []
            self._last_key = ()
            self._post()
            return

        state = result.state
        model.problems = []
        model.rows = rows_from_state(state)
        model.cogs = [f"{r.name} (level {r.level})" for r in model.rows]
        model.toon_count = state.allies_standing + 1

        key = _position_key(state)
        if key != self._last_key or self._asked.is_set():
            self._last_key = key
            self._asked.clear()
            model.thinking = True
            self._search(state)
        self._post()

    def _search(self, state) -> None:
        with self._lock:
            token = next(self._generation)
            self._current = token
            objective, depth, budget = (self.objective, self.depth,
                                        self.budget)
        threading.Thread(target=self._run_search, daemon=True,
                         args=(token, state, objective, depth,
                               budget)).start()

    def _run_search(self, token, state, objective, depth, budget) -> None:
        from ..search import expectimax

        try:
            _value, action = expectimax.best_action_iterative(
                state, depth=depth, objective=objective,
                epsilon=DEFAULT_EPSILON, time_budget=budget, exact_plies=1)
            text = (_render(action, state) if action is not None
                    else "no legal move -- nothing left to throw")
            track = None if action is None or action.is_pass \
                else action.track.value
            level = None if action is None or action.is_pass \
                else action.level
        except Exception as exc:        # noqa: BLE001
            # A search that dies takes its thread with it and nothing
            # else notices: no advice appears, which looks exactly like
            # a search still running.
            text, track, level = (f"the search failed: "
                                  f"{exc.__class__.__name__}: {exc}"), None, None

        with self._lock:
            if token != self._current:
                return                  # the fight moved on
        self.model.gag = text
        self.model.gag_at = time.time()
        self.model.track = track
        self.model.gag_level = level
        self.model.thinking = False
        self._post()

    def _post(self) -> None:
        from copy import copy

        self.model.allow_level_7 = self.allow_level_7
        self.model.objective = self.objective_name
        self.model.budget = self.budget
        try:
            self.outbox.put_nowait(copy(self.model))
        except queue.Full:              # pragma: no cover
            pass


class RealmsApi:
    """What the page may call. A strict subset of the TTR panel's.

    `name_cog` and `mark_lured` are deliberately ABSENT rather than
    stubbed. Both exist on the TTR side to let the player supply what
    the readers could not see, and here the server says both outright --
    offering them would invite a player to override correct data with a
    guess.
    """

    def __init__(self, state: "RealmsPanelState", worker: RealmsWorker):
        self._state = state
        self._worker = worker

    def pull(self) -> str:
        return model_json(self._state.model)

    def set_objective(self, name) -> None:
        self._worker.set_objective(str(name))

    def set_budget(self, seconds) -> None:
        self._worker.set_budget(seconds)

    def set_level_7(self, allow) -> None:
        self._worker.set_level_7(allow)

    def set_toon_count(self, count) -> None:
        """Accepted and ignored, with the reason said out loud.

        Party size is READ here, from `setMembers`. The TTR panel needs
        the player to supply it because nothing on screen counts toons
        reliably. Letting a click override the server would be strictly
        worse data, so the control does nothing -- but the page is
        shared, so the method has to exist or the click raises.
        """
        return None

    def set_height(self, height: int) -> None:
        window = self._state.window
        if window is None:
            return
        try:
            window.resize(window.width, max(120, int(height) + 16))
        except Exception:               # pragma: no cover
            pass

    def close(self) -> None:
        self._state.closing = True


class RealmsPanelState:
    def __init__(self) -> None:
        self.model = Model()
        self.closing = False
        self.window = None


def _headless(listener, objective, depth, budget) -> int:  # pragma: no cover
    """Run the worker with no window and narrate every poll."""
    inbox: "queue.Queue" = queue.Queue(maxsize=64)
    worker = RealmsWorker(inbox, objective, depth, budget, listener=listener)

    print(f"  attached; polling every {POLL_INTERVAL}s. "
          f"Ctrl-C to stop.")
    next_full = 0.0
    print()
    last = None
    try:
        while True:
            cycle = time.time()
            # THROTTLED. This used to refresh every poll, which with 133
            # objects at 2.5 polls a second put a few hundred queries a
            # second through the message director -- 6,000 GET_ALL
            # replies in one fight, most of them re-describing a
            # butterfly that had not changed. The battle roster is
            # cheap and worth doing often; everything else is not.
            try:
                if cycle >= next_full:
                    listener.refresh_all()
                    next_full = cycle + 10.0
                listener.refresh_battle_members()
            except Exception as exc:
                print(f"  refresh failed: {exc}")
            try:
                worker.tick()
            except Exception as exc:
                import traceback
                print(f"  TICK RAISED: {exc.__class__.__name__}: {exc}")
                traceback.print_exc()
                time.sleep(2.0)
                continue

            model = worker.model
            line = (f"battles={len(listener.battles())} "
                    f"cogs={len(listener.cogs())} "
                    f"toons={len(listener.toons())} "
                    f"objects={len(listener.store)} "
                    f"datagrams={listener.datagrams} "
                    f"undecoded={listener.undecoded} "
                    f"attacks={listener.attacks_seen} "
                    f"lures={listener.lures_seen}")
            if line != last:
                print(f"  {line}")
                if listener._unknown:
                    top = sorted(listener._unknown.items(),
                                 key=lambda kv: -kv[1])[:6]
                    print("    unknown message types: "
                          + ", ".join(f"{t}x{n}" for t, n in top))
                for msgtype, seen in sorted(listener._entered.items()):
                    names = sorted(listener._entered_classes.get(msgtype, ()))
                    print(f"    msgtype {msgtype} delivered {seen} objects: "
                          + ", ".join(names[:8]))
                for problem in model.problems:
                    print(f"    ! {problem}")
                for row in model.rows:
                    print(f"    {row.name} L{row.level} "
                          f"{row.health:.0%}{' LURED' if row.lured else ''}")
                if model.gag:
                    print(f"    -> {model.gag}")
                last = line
            time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))
    except KeyboardInterrupt:
        print()
        print("  stopped")
    finally:
        worker.close()
        listener.close()
    return 0


def main(argv: Optional[list] = None) -> int:   # pragma: no cover
    from ..search import objective as objectives

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objective", default="balanced",
                        help="one of " + ", ".join(sorted(objectives.PRESETS)))
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    parser.add_argument("--no-level-7", action="store_true")
    parser.add_argument("--dir", help="Realms install directory")
    parser.add_argument("--headless", action="store_true",
                        help="no window: print what the worker sees each "
                             "poll. This is the only way to tell a panel "
                             "that cannot read the fight from a panel "
                             "whose reader thread has died -- both look "
                             "like a window that never changes.")
    args = parser.parse_args(argv)

    index = DIST / "index.html"
    if not index.exists():
        print(f"  no built UI at {DIST}")
        print("  build it once:  cd overlay_ui && npm install && npm run build")
        return 1
    try:
        import webview
    except ImportError:
        print("  pywebview is not installed:  pip install pywebview")
        return 1

    from . import realms as realms_mod

    try:
        listener = realms_mod.RealmsListener(
            index=realms_mod.DCIndex(override=args.dir))
        listener.connect()
    except realms_mod.RealmsError as exc:
        print(f"  {exc}")
        return 1
    listener.start()

    if args.no_level_7:
        from .. import state as state_mod
        state_mod.ALLOW_LEVEL_7 = False

    if args.headless:
        return _headless(listener, objectives.PRESETS[args.objective],
                         args.depth, args.budget)

    inbox: "queue.Queue" = queue.Queue(maxsize=4)
    worker = RealmsWorker(inbox, objectives.PRESETS[args.objective],
                          args.depth, args.budget, listener=listener)
    worker.objective_name = args.objective
    state = RealmsPanelState()
    state.model.objective = args.objective
    state.model.budget = args.budget
    state.model.allow_level_7 = not args.no_level_7
    api = RealmsApi(state, worker)

    window = webview.create_window(
        "TTR Solver - Realms", str(index), js_api=api,
        width=430, height=330, x=60, y=60,
        frameless=True, on_top=True, resizable=False,
        background_color="#0d1117")
    state.window = window
    worker.start()

    def pump() -> None:
        while not state.closing:
            try:
                state.model = inbox.get(timeout=0.2)
            except queue.Empty:
                continue
        worker.close()
        listener.close()
        try:
            window.destroy()
        except Exception:               # pragma: no cover
            pass

    threading.Thread(target=pump, daemon=True).start()
    webview.start()
    worker.close()
    listener.close()
    return 0


if __name__ == "__main__":              # pragma: no cover
    raise SystemExit(main())
