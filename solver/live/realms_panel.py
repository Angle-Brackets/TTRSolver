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
# WAS 12s, AND IT BOUGHT NOTHING. Depth 4 never completes -- CLAUDE.md
# measures depth 3 at "many minutes" -- so iterative deepening always
# runs to the deadline, however long that is. Measured on the owner's
# real 70-gag loadout, the recommended move stops changing by 2s in
# every position tried: one cog, two cogs and four.
#
# It is not free time either. The search is CPU-bound Python in the
# same process as the UI, so a long one starves the poll loop and the
# window both -- which showed up as a panel that dragged when moved and
# cog health that appeared to stop updating.
DEFAULT_BUDGET = 4.0
DEFAULT_EPSILON = 0.03

# Sentinel from `search_in_child`: the search could not run because the
# board holds a cog with an unconfirmed data cell.
MISSING_DATA = chr(0) + "missing-data"


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


def search_in_child(state, objective_name: str, depth: int,
                    budget: float, allow_level_7: bool):
    """Run the search in a SEPARATE PROCESS and return a plain result.

    WHY A PROCESS AND NOT A THREAD. The search is CPU-bound pure Python,
    so a thread holds the GIL for most of its slice and starves both the
    poll loop and the window. The panel dragged when moved and cog
    health appeared to stall; cutting the search from twelve seconds to
    four only made that less obvious rather than fixing it. A process
    has its own interpreter and cannot interfere at all.

    Returns `(text, track, level)` rather than an `Action`, so nothing
    crosses the process boundary but a string and two scalars, and the
    child renders the wording itself so it stays identical either way.

    Top-level rather than a closure because Windows spawns rather than
    forks, and a closure cannot be pickled into a fresh interpreter.
    """
    from .. import state as state_mod
    from ..search import expectimax, objective as objectives

    state_mod.ALLOW_LEVEL_7 = bool(allow_level_7)
    objective = objectives.PRESETS.get(objective_name, objectives.DEFAULT)
    try:
        _value, action = expectimax.best_action_iterative(
            state, depth=depth, objective=objective,
            epsilon=DEFAULT_EPSILON, time_budget=budget, exact_plies=1)
    except expectimax.MissingData as exc:
        # A [TODO] cell in a cog's table makes EVERY action unevaluable,
        # because they all run the same cog phase. The policy is
        # unaffected, so the caller keeps its answer -- but it has to be
        # told, or the panel silently downgrades to the policy on every
        # board holding that cog and looks like it is merely slow.
        return MISSING_DATA, str(exc), None
    if action is None:
        return "no legal move -- nothing left to throw", None, None
    return (_render(action, state),
            None if action.is_pass else action.track.value,
            None if action.is_pass else action.level)


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
                 budget: float, listener=None, engine: str = "both"):
        super().__init__(daemon=True)
        self.outbox = outbox
        self.objective = objective
        self.objective_name = getattr(objective, "name", "balanced")
        self.depth = depth
        self.budget = budget
        self.listener = listener
        # "rl", "search" or "both". WHICH IS BETTER IS NOT ESTABLISHED,
        # which is the honest reason this is a choice rather than a
        # decision made here. Everything offline in this project -- the
        # CEO sweeps, the building runs, the ship gate -- evaluates
        # `hybrid.climb`, so the search is the UNTESTED path in the
        # panel, not the policy. The owner reports preferring the
        # policy's picks and there is no measurement to contradict them.
        self.engine = engine
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
        self._executor = None

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
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

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

        next_full = 0.0
        while not self._stop.is_set():
            cycle = time.time()
            # THE FIGHT IS REFRESHED EVERY POLL, THE WORLD IS NOT.
            # Both used to share a five-second timer, so a cog's HP was
            # up to five seconds stale -- the server does not re-send
            # `setHP` on every hit, it sends `damageSuit` for the
            # animation, so the value in the store is only as fresh as
            # the last query. Advice computed against a cog that died
            # four seconds ago is worse than late advice.
            #
            # The asymmetry is what makes this cheap: the roster is two
            # to five objects, the full sweep was 137, and it was the
            # full sweep that needed throttling in the first place.
            try:
                self.listener.refresh_battle_members()
                if cycle >= next_full:
                    self.listener.refresh_all()
                    next_full = cycle + 10.0
            except Exception:           # pragma: no cover
                pass
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

    def _first_answer(self, state):
        """The trained policy's move, in milliseconds.

        `hybrid.climb` is what every offline evaluation in this project
        actually runs -- the CEO sweeps, the building runs, the ship
        gate -- and it is a thousand times faster than the search the
        panel was using: 1-224ms against 9-12s on the same positions.

        It is used here to answer IMMEDIATELY rather than to replace the
        search, because which of the two plays better is genuinely not
        established. They agreed on one of three test positions and
        differed on the other two, and nothing here has measured which
        was right. So the fast answer goes up first and the search
        replaces it if it disagrees.
        """
        try:
            import random

            from ..search import hybrid

            plan = hybrid.climb(state, random.Random(0), budget=8)
        except Exception:               # pragma: no cover - optional path
            return None
        return plan[0] if plan else None

    def _pool(self):
        """One worker process, made on first use and kept.

        Windows spawns rather than forks, so a fresh interpreter costs
        about half a second. Paid once rather than per search.
        """
        if self._executor is None:
            from concurrent.futures import ProcessPoolExecutor

            self._executor = ProcessPoolExecutor(max_workers=1)
        return self._executor

    def _run_search(self, token, state, objective, depth, budget) -> None:
        # Something on screen straight away. A blank panel for twelve
        # seconds is the complaint that started this.
        if self.engine != "search":
            quick = self._first_answer(state)
            if quick is not None:
                with self._lock:
                    fresh = token == self._current
                if fresh:
                    self._show(quick, state,
                               thinking=self.engine == "both", engine="rl")
            if self.engine == "rl":
                return              # the policy's answer stands

        try:
            future = self._pool().submit(
                search_in_child, state,
                getattr(objective, "name", self.objective_name),
                depth, budget, self.allow_level_7)
            # A margin past the child's own deadline. It should return
            # on time by itself; this only stops a wedged process
            # holding the panel on "thinking" for ever.
            text, track, level = future.result(timeout=budget + 20.0)
            if text == MISSING_DATA:
                # Keep the policy's move -- it is a real answer and the
                # only one available here -- and say what stopped the
                # search rather than letting it look like a slow one.
                with self._lock:
                    if token != self._current:
                        return
                self.model.problems = [
                    f"search unavailable, using the policy: {track}"]
                self.model.thinking = False
                self.model.engine = "rl"
                self._post()
                return
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
        self.model.engine = "search"
        self._post()

    def _show(self, action, state, thinking: bool = False,
              engine: str = "") -> None:
        """Put a move on the panel without ending the search.

        `engine` says WHICH one produced it, shown as a badge rather
        than folded into the sentence -- the advice is what gets read at
        a glance, and provenance is a property of it rather than part of
        it.

        It is not decoration. The objective control steers the search
        and does NOT steer the policy: `hybrid.climb` takes no objective
        and `party_search._quick_score` reads fixed global weights, so
        an "rl" answer is the same move whether the player picked
        "survive" or "glass cannon". Only the "search" that replaces it
        honours the setting, and a panel showing an objective-blind move
        under an objective dropdown without saying so is lying about
        what it is doing.
        """
        self.model.gag = _render(action, state)
        self.model.engine = engine
        self.model.gag_at = time.time()
        self.model.track = (None if action is None or action.is_pass
                            else action.track.value)
        self.model.gag_level = (None if action is None or action.is_pass
                                else action.level)
        self.model.thinking = thinking
        self._post()

    def _post(self) -> None:
        from copy import copy

        self.model.allow_level_7 = self.allow_level_7
        self.model.objective = self.objective_name
        self.model.budget = self.budget
        # LATEST WINS. This was a FIFO that dropped the NEWEST model when
        # it filled, so under load the panel rendered a queue of stale
        # ones and never caught up -- cog health visibly a round behind
        # the fight.
        #
        # A stale battle state is not merely late, it is wrong: the
        # advice beside it was computed for a cog that has since taken
        # damage or died. There is no value in an old model once a newer
        # one exists, so the old one is thrown away rather than the new.
        fresh = copy(self.model)
        while True:
            try:
                self.outbox.put_nowait(fresh)
                return
            except queue.Full:
                try:
                    self.outbox.get_nowait()
                except queue.Empty:     # pragma: no cover - raced
                    pass


class RealmsApi:
    """What the page may call. A strict subset of the TTR panel's.

    `name_cog` and `mark_lured` are INERT rather than absent, and that
    is a correction. They were left off entirely on the reasoning that
    the server states both and a player should not be able to overrule
    it with a guess -- which is right about what they should DO and
    wrong about whether they should exist. The page is shared, so a
    click reaches whatever the Api has, and a missing method fails at
    click time with nothing the player will ever see. They exist and do
    nothing.
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

    def name_cog(self, *_args) -> None:
        """Inert. Identity comes from `setDNAString`, so there is
        nothing to name -- and `rows_from_state` leaves `choices` empty,
        so the picker never appears in the first place."""
        return None

    def mark_lured(self, *_args) -> None:
        """Inert. Lure state comes from the battle roster."""
        return None

    def set_toon_count(self, count) -> None:
        """Accepted and ignored, with the reason said out loud.

        Party size is READ here, from `setMembers`. The TTR panel needs
        the player to supply it because nothing on screen counts toons
        reliably. Letting a click override the server would be strictly
        worse data, so the control does nothing -- but the page is
        shared, so the method has to exist or the click raises.
        """
        return None

    def ask_now(self) -> None:
        """Recompute now. The page's "Work it out" button."""
        self._worker.ask_now()

    def toggle_fight(self, *_args) -> None:
        """The page's "I'm in a fight" button.

        It RECOMPUTES rather than overriding detection, which is the
        opposite of what it does on the TTR panel. There it sets
        `forced`, because the screen readers genuinely miss fights and
        the player can see one the pixels cannot. Here the cluster
        states whether a battle exists, so asserting one would replace a
        fact with an opinion -- and if the reader cannot build a state,
        forcing changes nothing anyway: `build_state` still refuses and
        the panel still shows the reasons.

        What is useful about the button is the impatience behind it, so
        it does that part: refresh and re-search immediately.
        """
        try:
            self._worker.listener.refresh_all()
            self._worker.listener.refresh_battle_members()
        except Exception:               # pragma: no cover
            pass
        self._worker.ask_now()

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


def _summarise_movie(value) -> str:          # pragma: no cover
    """`setMovie` in one readable line.

    struct BattleMovie {
        int8 movieHasBeenMade; uint32[] activeToons; uint32[] activeSuits;
        ToonAttack[] toonAttacks; SuitAttack[] suitAttacks;
    }
    struct ToonAttack { index, track, level, target, hp[], accBonus,
                        hpBonus, kbBonus[], suitDied, suitRevive }
    """
    if not isinstance(value, (list, tuple)) or len(value) < 5:
        return str(value)
    made, _toons, _suits, toon_attacks, suit_attacks = value[:5]
    if not made:
        return "not made yet"

    parts = []
    for attack in toon_attacks or ():
        try:
            _i, track, level, target, hp = attack[:5]
            died = attack[8] if len(attack) > 8 else 0
        except Exception:
            parts.append(str(attack)[:40])
            continue
        if int(track) < 0:
            continue
        total = sum(int(x) for x in (hp or ()))
        parts.append(f"toon track{track} lvl{int(level) + 1} -> {target} "
                     f"dmg{list(hp or ())}={total}"
                     + (" KILLED" if died else ""))
    for attack in suit_attacks or ():
        try:
            _i, track, target, hp = attack[:4]
        except Exception:
            continue
        parts.append(f"cog atk{track} -> {target} dmg{list(hp or ())}")
    return "; ".join(parts) or "no attacks"


def _trace(listener) -> int:                 # pragma: no cover
    """Log every field the fight receives, with timestamps.

    HP arriving exactly one round late is not latency -- latency does
    not quantise to rounds. It means the value we read is written at a
    different moment than the hit, and the only way to find out which is
    to watch what actually lands and when. Guessing produced two wrong
    answers about this already.
    """
    from . import realms as realms_mod

    started = time.time()
    interesting = {"setHP", "setMaxHP", "damageSuit", "setState",
                   "setMembers", "setChosenToonAttacks", "doExplode",
                   "setSkeleRevives", "doRevive", "setMovie"}

    def in_the_fight(do_id: int) -> bool:
        """Only the battle and its own cogs. The street sends a
        `setState` per wandering cog several times a second and it
        buried the four lines that matter."""
        for battle in listener.battles():
            if do_id == battle.do_id:
                return True
            members = realms_mod.parse_members(battle.get("setMembers"))
            if members and do_id in tuple(members.suits) + tuple(members.toons):
                return True
        return False

    def snapshot() -> str:
        """What `build_state` would report RIGHT NOW.

        The arrival log alone cannot tell a listener bug from a model
        bug: it shows the value landing and never what the panel holds
        a moment later. Printing both on the same line does.
        """
        from . import realms_session

        result = realms_session.build_state(listener)
        if result.state is None:
            return "build_state: " + ("; ".join(result.problems) or "no state")
        return "build_state: " + ", ".join(
            f"{c.cog_type} {c.hp}/{c.max_hp}"
            + ("*lured" if c.status.lured else "")
            + ("*trap" if c.status.trapped else "")
            for c in result.state.cogs)

    def on_event(name, obj):
        if name not in interesting or not in_the_fight(obj.do_id):
            return
        value = obj.get(name)
        if name == "setMembers":
            members = realms_mod.parse_members(value)
            if members is None:
                return
            value = (f"suits={list(members.suits)} "
                     f"lured={members.suits_lured!r} "
                     f"traps={members.suit_traps!r}")
        if name == "setMovie":
            # THE ROUND'S ACTUAL RESULT. `ToonAttack.hp` is the damage
            # dealt per target and `suitDied` says whether it finished
            # the cog, so this is what really happened -- as against
            # `setChosenToonAttacks`, which is only what was AIMED.
            #
            # It is also the discriminator the last capture lacked: with
            # only setHP to go on, "the server sends pre-round HP" and
            # "the server resolves instantly and that attack missed"
            # explain the same bytes.
            value = _summarise_movie(value)
        text = str(value)
        print(f"  {time.time()-started:7.2f}s  {obj.do_id:<11} "
              f"{name:<22} {text[:70]}")
        if name in ("setHP", "damageSuit", "setState"):
            print(f"           {'':11}  -> {snapshot()[:110]}")

    listener.on_event = on_event
    print("  tracing. Hit a cog and watch whether setHP arrives with the")
    print("  hit or only after the next round begins. Ctrl-C to stop.")
    print()
    try:
        while True:
            listener.refresh_battle_members()
            time.sleep(0.4)
    except KeyboardInterrupt:
        print()
        print("  stopped")
    finally:
        listener.close()
    return 0


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
                    f"lures={listener.lures_seen} "
                    f"traps={listener.traps_seen}")
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
                # The raw roster strings, so it is visible whether
                # `setMembers` ever refreshes its trap slots at all.
                for b in listener.battles():
                    from solver.live.realms import parse_members
                    m = parse_members(b.get("setMembers"))
                    if m is not None:
                        from solver.data import gags as _g
                        from solver.state import Track as _T
                        named = {}
                        for _id, _lvl in m.traps().items():
                            try:
                                named[_id] = _g.gag(_T.TRAP, _lvl).display
                            except Exception:
                                named[_id] = f"level {_lvl}"
                        print(f"    roster: lured={m.suits_lured!r} "
                              f"traps={m.suit_traps!r} -> {named} "
                              f"| watched={listener.chosen_traps}")
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
    parser.add_argument("--engine", default="both",
                        choices=("both", "rl", "search"),
                        help="'rl' is the trained policy alone, answering "
                             "in milliseconds and ignoring the objective. "
                             "'search' is expectimax alone, which honours "
                             "it. 'both' shows the policy first and lets "
                             "the search replace it. Which plays better "
                             "is genuinely unmeasured -- everything "
                             "offline here evaluates the policy, so the "
                             "search is the untested one.")
    parser.add_argument("--trace", action="store_true",
                        help="log every field the cogs and the battle "
                             "receive, with timestamps. For working out "
                             "WHY a value is late rather than guessing: "
                             "it shows whether the server re-sends setHP "
                             "on a hit or only damageSuit.")
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

    if args.trace:
        return _trace(listener)
    if args.headless:
        return _headless(listener, objectives.PRESETS[args.objective],
                         args.depth, args.budget)

    inbox: "queue.Queue" = queue.Queue(maxsize=4)
    worker = RealmsWorker(inbox, objectives.PRESETS[args.objective],
                          args.depth, args.budget, listener=listener,
                          engine=args.engine)
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
        """PUSH the model into the page. Do not merely store it.

        The page does not poll -- `App.jsx` installs `window.pushModel`
        and waits to be called, and `Api.pull` exists only for
        `npm run dev` where there is no Python. Updating `state.model`
        and stopping there left the page rendering its OWN defaults
        forever, which is why the panel showed "waiting for a battle"
        and a 15s budget while the reader could see the fight perfectly:
        15 is App.jsx's fallback, not this module's 12, and that
        mismatch is what gave it away.
        """
        while not state.closing:
            try:
                state.model = inbox.get(timeout=0.25)
            except queue.Empty:
                pass
            # Skip to the newest. `evaluate_js` is a round trip into
            # WebView2 and slower than the worker's poll, so models pile
            # up behind it; rendering each in turn shows the player a
            # replay rather than the fight.
            while True:
                try:
                    state.model = inbox.get_nowait()
                except queue.Empty:
                    break
            try:
                window.evaluate_js(
                    "window.pushModel && window.pushModel("
                    + model_json(state.model) + ")")
            except Exception:           # window gone
                break
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
