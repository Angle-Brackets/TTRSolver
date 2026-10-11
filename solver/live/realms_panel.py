"""The live panel, driven by Toontown Realms instead of by pixels.

    python -m solver.live.realms_panel
    python -m solver.live.realms_panel --objective survive --budget 8

A SECOND PANEL, deliberately: `overlay.Worker` polls a screen capture,
finds plates and hedges every number with a confidence, none of which
applies here, since `realms_session` is handed typed fields by the
server. Threading that through the TTR worker would put "if realms:"
through the one module whose entire job is being careful about pixels.

WHAT IT SHARES: `Model`, `CogRow` and `model_json` are imported and
never modified. They are the VIEW, and the built React app renders this
with no changes at all -- what differs is every line of reading. Health
is exact (not a fraction off a green bar), cog identity comes straight
from `setDNAString` (so the picker never appears), LURED and party size
are read from the battle roster rather than marked by hand.

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

from .overlay import CogRow, Model
from .worker import AdviceWorker
from .panel import DIST, model_json

# Evaluations `hybrid.climb` may spend per answer. See the call site:
# the old value of 8 starved the probes, costing about ten points of
# win rate for five milliseconds.
PANEL_BUDGET = 24

POLL_INTERVAL = 0.4

# Realms sends a field the moment it changes, so unlike the screen
# readers there is no flicker to smooth over and no agreement count. A
# search is started when the POSITION changes, which is what these
# summarise.
DEFAULT_DEPTH = 4
# Depth 4 never completes (CLAUDE.md: depth 3 is "many minutes"), so
# iterative deepening always runs to this deadline. On the owner's real
# 70-gag loadout the recommended move stopped changing by 2s across one,
# two and four cogs -- a longer budget bought nothing but CPU, which
# this shares with the UI thread and made the window drag.
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


def _pouch_of(state) -> list:
    """What the toon holds, in the shape the picker needs.

    Sorted by track then level so the rows do not reshuffle between
    polls -- a control that moves under the cursor while a count ticks
    down is worse than no control.
    """
    from .. import data

    out = []
    try:
        counts = getattr(state.toon, "gag_counts", {}) or {}
    except Exception:                          # noqa: BLE001
        return out
    for (track, level), count in counts.items():
        if count <= 0:
            continue
        try:
            gag = data.gag(track, level)
        except Exception:                      # noqa: BLE001
            continue
        out.append({"track": track.value, "level": int(level),
                    "count": int(count), "name": gag.display,
                    "group": bool(gag.group)})
    out.sort(key=lambda row: (row["track"], row["level"]))
    return out


def _policy_id() -> str:
    """Which policy proposed the moves in a record.

    A preference is relative to what it was offered: comparisons
    collected against one checkpoint are off-policy for the next, and a
    log that does not say which is one that cannot be split later.
    """
    try:
        from ..rl import policy as policy_mod

        return str(getattr(policy_mod, "EXPORT_ID", "") or "unknown")
    except Exception:                          # noqa: BLE001
        return "unknown"


def _outcome(before, after) -> dict:
    """What the round actually did, as metadata rather than as label.

    Kept SEPARATE from the preference on purpose. The label is about the
    decision, taken against the board as it stood; this is the roll that
    followed. Folding the two together is how outcome bias gets in --
    a correct 95% play that missed would train as a bad move.
    """
    out = {"hp": [], "laff": []}
    try:
        out["hp"] = [int(b.hp) - int(a.hp)
                     for b, a in zip(before.cogs, after.cogs)]
        out["laff"] = [int(b.laff) - int(a.laff)
                       for b, a in zip(before.toons, after.toons)]
    except Exception:                          # noqa: BLE001
        pass
    return out


def _entry_for(track, level):
    """Any `env.ACTIONS` entry with this track and level, for keying.

    The model carries the move as a slug and level, not an Action, so
    Reconsider needs something with the same `reject_key` -- any entry
    of that track and level does, since the key ignores the target.
    """
    from ..rl import env as env_mod

    for entry in env_mod.ACTIONS:
        if (entry is not None and not entry.fire
                and entry.track == track and entry.level == level):
            return entry
    raise LookupError(f"no action for {track} {level}")


def _track_of(action):
    """The page's track slug for an action, or None.

    "fire" is a SENTINEL, not a gag track -- it lets the advice line show
    a pink slip instead of the no-track styling a pass uses. A fire has
    `track=None` and `is_pass=False`, so a naive `action.track.value`
    raises; this guards it.
    """
    from .advise import track_of

    return track_of(action)


def _level_of(action):
    """A fire has no level; a gag has its own."""
    if (action is None or action.is_pass
            or getattr(action, "fire", False)
            or getattr(action, "sos", None)):
        return None
    return action.level


def _render(action, state) -> str:
    """Advice as one line, reusing the TTR panel's wording.

    Two panels phrasing the same move differently would be worse than
    the coupling, so this imports a formatter rather than any reading.
    """
    try:
        from .advise import _render as shared

        return shared(action, state)
    except Exception:                   # pragma: no cover - defensive
        if action is None or getattr(action, "is_pass", False):
            return "pass"
        # Guard the track-less actions FIRST -- this fallback must
        # survive even for the two actions (fire, SOS) most likely to
        # have broken the shared renderer in the first place.
        if getattr(action, "sos", None):
            return f"call {action.sos}"
        if getattr(action, "fire", False):
            return "pink slip"
        return f"{action.track.value} {action.level}"


def search_in_child(state, objective_name: str, depth: int,
                    budget: float, allow_level_7: bool):
    """Run the search in a SEPARATE PROCESS and return a plain result.

    A PROCESS, NOT A THREAD: the search is CPU-bound pure Python, so a
    thread holds the GIL and starves both the poll loop and the window.
    A process has its own interpreter and cannot interfere at all.

    Returns `(text, track, level, target)` rather than an `Action`, so
    only a string and three scalars cross the process boundary, and the
    child renders the wording so it stays identical either way.

    THE TARGET IS PART OF THE MOVE, not decoration: `reject_key` ignores
    it but `explain.describe` SIMULATES the round, and a move rebuilt
    with `target_index=None` reads to `simulator._targets_for` as every
    active cog -- a single-target gag described as hitting the whole
    lineup.

    Top-level rather than a closure: Windows spawns rather than forks,
    and a closure cannot be pickled into a fresh interpreter.
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
        # A [TODO] cell makes EVERY action unevaluable, since they all
        # run the same cog phase. The policy is unaffected, but the
        # caller has to be TOLD or the panel silently downgrades to it
        # and looks merely slow.
        return MISSING_DATA, str(exc), None, None
    if action is None:
        return "no legal move -- nothing left to throw", None, None, None
    return (_render(action, state), _track_of(action), _level_of(action),
            getattr(action, "target_index", None))


def rows_from_state(state) -> List[CogRow]:
    """`CogRow`s from a searched state.

    `identified` is always True and `choices` always empty: identity
    came from `setDNAString`, so the picker never appears.
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
                          lured=cog.status.lured,
                          trapped=getattr(cog.status, "trapped", False),
                          choices=[], identified=True))
    return out


class RealmsWorker(AdviceWorker):
    """Reads the cluster, searches when the position moves, posts a Model."""

    # CLASS-LEVEL, not only set in `__init__`: tests build an instance
    # with `__new__`, and 0 is the safe default -- it advises none of a
    # resource farmed from boss runs.
    max_fires = 0
    max_unites = 0
    max_sos = 0
    # Same reason: an instance built with `__new__` must read "not
    # recording" rather than raise. Off is the safe default.
    feedback_to = None
    _feedback = None
    _prev_state = None
    _last_rid = ""
    # WATCH MODE: record the fight as a trajectory, advice or no advice.
    watch_to = None
    _watch = None
    _episode = None
    # THE BOSS COUNT'S MEMORY between polls: the boss object the count
    # belongs to, and the last boss battle's (doId, cog ids).
    _boss_obj = None
    _boss_battle = None
    # The teammates this poll could read, for the playouts' pickup board.
    _allies = ()

    def __init__(self, outbox: "queue.Queue", objective, depth: int,
                 budget: float, listener=None, engine: str = "both"):
        # `model` FIRST: the base writes `allow_level_7` and the
        # holdings onto it, so it has to exist before that runs.
        self.model = Model()
        super().__init__(outbox, objective, depth, budget)
        self.listener = listener
        # "rl", "search" or "both". WHICH IS BETTER IS NOT ESTABLISHED:
        # everything offline in this project evaluates `hybrid.climb`,
        # so the search is the untested path here, not the policy.
        self.engine = engine
        # Playouts run wherever the search does: company, not a
        # replacement, until measured against it in live play.
        self.model.engines = {"both": ["rl", "search", "playout"],
                              "search": ["search", "playout"],
                              "rl": ["rl"]}.get(engine, [])
        self.record_to = None
        # HUMAN FEEDBACK. `feedback_to` is a path or None; the log is
        # built lazily so an unset flag costs nothing. `_prev_state` is
        # the board the standing advice was given for, kept so the next
        # round can diff the pouch against it -- see `solver.live.feedback`.
        self.feedback_to = None
        self._feedback = None
        self._prev_state = None
        self.recorded = 0
        self.record_error = None
        self._generation = count()
        self._current = -1
        self._last_key: tuple = ()
        self._executor = None

    # -- controls -----------------------------------------------------

    def _settings_changed(self) -> None:
        """Redraw, recompute -- and drop the position key.

        `tick` searches only when the position key CHANGES, so without
        this a setting changed mid-fight waits for the next cog action.
        `reconsider` deliberately does not come through here: clearing
        the key there would wipe the rejection before anything read it.
        """
        self._last_key = ()
        super()._settings_changed()
    def close(self) -> None:
        self._stop.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        if self._playout_executor is not None:
            self._playout_executor.shutdown(wait=False, cancel_futures=True)
            self._playout_executor = None

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
            # THE FIGHT IS REFRESHED EVERY POLL, THE WORLD IS NOT. The
            # server doesn't re-send `setHP` on every hit (it sends
            # `damageSuit` for the animation), so the store is only as
            # fresh as the last query -- advice against a cog that died
            # seconds ago is worse than late advice. The asymmetry keeps
            # this cheap: the roster is two to five objects, the full
            # sweep was 137, and only the full sweep needs throttling.
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
                # A dead worker leaves the panel frozen on its last
                # model -- indistinguishable from a fight it can't read.
                # Report it through the channel the panel already shows.
                self.model.problems = [
                    f"the reader failed: {exc.__class__.__name__}: {exc}"]
                self.model.detected_battle = False
                self._post()
            time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))

    # The toon's REAL holdings at the last poll that read them; None until
    # the first. See `_cap_holdings`.
    _held_last = None

    def _cap_holdings(self, result) -> None:
        """Tick the boxes down by what REALLY left the toon, then cap the
        board's slips, unites and SOS calls at them.

        The boxes are a session budget (`AdviceWorker.remaining`). The
        screen-reading panel cannot see a slip, unite or card leave the
        toon, so it charges the advice; this client can -- the toon's own
        counts arrive every poll -- so it charges only what was really
        spent. Charging advice here once emptied a five-card SOS budget
        within a few rounds of a VP without a card being called. A count
        that RISES (a reward, a restock) grants nothing: the box is what
        the player chose to spend, not what they hold.
        """
        state = getattr(result, "state", None)
        if state is None or not state.toons:
            return
        toon = state.toons[0]
        now = {"fires": int(toon.fires), "unites": int(toon.unites_held),
               "sos": sum(max(0, int(n)) for n in (toon.sos_cards or {}).values())}
        last = self._held_last
        self._held_last = now
        if last is not None:
            for name, held in now.items():
                if last[name] > held:
                    self.spend(name, last[name] - held)
        toon.fires = min(toon.fires, self.remaining("fires"))
        toon.unites_held = min(toon.unites_held, self.remaining("unites"))
        calls = self.remaining("sos")
        toon.sos_cards = ({name: min(int(n), calls)
                           for name, n in (toon.sos_cards or {}).items() if n > 0}
                          if calls else {})
        # ONE POOL: the cap above stops any single card exceeding the
        # budget, this stops them together exceeding it.
        toon.sos_calls = calls

    def tick(self) -> None:
        """One poll. Split out from `run` so it is testable with a fake
        listener and no cluster at all."""
        from . import realms_session

        # Read the toon's REAL holdings (uncapped), then cap them by what
        # this fight may still spend -- see `_cap_holdings`.
        big = 10 ** 6
        result = realms_session.build_state(self.listener, max_fires=big,
                                            max_unites=big, max_sos=big)
        model = self.model
        self._allies = tuple(getattr(result, "allies", ()) or ())
        # Boss first: a new fight resets the spending baseline, and that
        # has to land before this board is capped by it.
        self._track_boss(result)
        self._cap_holdings(result)
        if result.state is not None:
            result.state.realms_context = self._context_of(result)
        self._boss_into(model, on_field=len(result.state.cogs)
                        if result.state else 0)
        model.window_found = True
        model.detected_battle = result.state is not None
        model.plates = len(result.state.cogs) if result.state else 0
        model.menu_visible = result.state is not None

        if result.state is None:
            # THE FIGHT ENDED HERE, and this is the only place that
            # knows it. The round recorder keys off the board CHANGING,
            # so the last round of every fight went unrecorded -- which
            # for a trajectory is the one round that matters, since
            # whether a run was won is carried entirely by it.
            self._close_episode()
            model.problems = list(result.problems)
            model.rows = []
            model.cogs = []
            self._last_key = ()
            self._prev_state = None
            self._post()
            return

        state = result.state
        model.problems = []
        model.rows = rows_from_state(state)
        model.pouch = _pouch_of(state)
        model.cogs = [f"{r.name} (level {r.level})" for r in model.rows]
        model.toon_count = state.allies_standing + 1
        if self.boss_tracker().kind:
            # The pill shows the WHOLE fight in a boss room, as it is set.
            model.toon_count = max(model.toon_count,
                                   self.boss_tracker().party_size)

        key = _position_key(state)
        if key != self._last_key or self._asked.is_set():
            if key != self._last_key:
                # Record the round's feedback BEFORE the rejections are
                # dropped -- a Reconsider is the highest-signal label the
                # panel produces, about THIS board.
                if self._last_key:
                    self._record_feedback(state)
                    self._watch_step(state)
                # A NEW BOARD FORGETS THE REJECTIONS. Keeping them would
                # silently narrow later rounds. Not cleared when `_asked`
                # fires instead -- that's Reconsider itself asking, and
                # clearing there would undo the rejection just given.
                self._rejected.clear()
                # THE BOARD MOVED, so the last advice has been played.
                # Charge it against the holdings -- but not on the
                # `_asked` arm, which recomputes the SAME round.
                # Nothing is charged here: this client reports the toon's
                # real slips, unites and cards, so spending is OBSERVED
                # in `_cap_holdings` rather than assumed from the advice.
            self._prev_state = state
            self._last_key = key
            self._asked.clear()
            model.thinking = True
            self._search(state)
        self._post()

    def _context_of(self, result) -> dict:
        """Where this board sits in a boss fight, for the feedback log.

        Rides on the board (`state.realms_context`), which every row
        pickles whole. The first logged VP could not say whether a fresh
        wave after a lull was the other side's battle or the skelecog
        round, nor how many cogs round one held: the stream states both
        and nothing wrote them down. Never raises.
        """
        try:
            boss = getattr(result, "boss", None)
            store = getattr(self.listener, "store", None)
            skelecog = []
            for do_id in getattr(result, "suit_ids", ()) or ():
                obj = store.get(do_id) if store is not None else None
                value = obj.get("setSkelecog") if obj is not None else None
                if isinstance(value, (tuple, list)):
                    value = value[0] if value else None
                skelecog.append(None if value is None else bool(value))
            return {"battle_id": getattr(result, "battle_id", None),
                    "suit_ids": list(getattr(result, "suit_ids", ()) or ()),
                    "skelecog": skelecog,
                    "boss_kind": getattr(boss, "kind", None),
                    "boss_id": getattr(boss, "boss_id", None),
                    "battle_number": getattr(boss, "battle_number", None),
                    "side": getattr(boss, "side", None),
                    "players": getattr(boss, "players", None),
                    "defeated": self.boss_tracker().defeated}
        except Exception:                      # noqa: BLE001
            return {}

    def _track_boss(self, result) -> None:
        """Which boss fight this is and how many cogs it has lost.

        EXACT, because this client names its cogs: a cog id leaving a
        boss battle's roster died, nothing else removes one from a
        running battle. When the battle is replaced by the next one of
        the SAME boss, the round was cleared, so ids still in the old
        roster died too -- catching the last kill, which the roster may
        never otherwise report since the battle object goes first.

        No state means no fight on screen (between a VP's rounds, say)
        and leaves the count alone; clearing it there would restart the
        count every round.
        """
        if result.state is None:
            return
        boss = getattr(result, "boss", None)
        if boss is None and getattr(result, "boss_room", False):
            # A BOSS ROOM WHOSE BOSS HAS NOT RESOLVED -- the first board
            # after a VP's intermission can arrive before its link to the
            # boss. Read as "no boss" it would clear the kind, restarting
            # the count (twice, once more when the boss resolves) and, on
            # the next empty poll, the fight's budget. Unknown: keep both.
            return
        tracker = self.boss_tracker()
        self._observe_boss(boss.kind if boss else None)
        if boss is not None and boss.boss_id != self._boss_obj:
            if self._boss_obj is not None:
                tracker.reset()
            tracker.party_size = 1
            self._boss_obj = boss.boss_id
            self._boss_battle = None
        if boss is None:
            self._boss_battle = None
        else:
            now_ids = set(result.suit_ids)
            if self._boss_battle is not None:
                prev_id, prev_ids = self._boss_battle
                tracker.note_dead_ids(prev_ids - now_ids
                                      if prev_id == result.battle_id
                                      else prev_ids)
            self._boss_battle = (result.battle_id, now_ids)
        if tracker.kind:
            # The largest party seen this fight: a toon going sad does
            # not change how many cogs the fight was built with.
            tracker.party_size = max(tracker.party_size,
                                     result.state.allies_standing + 1,
                                     getattr(boss, "players", None) or 0,
                                     self._boss_players)
        tracker.apply(result.state)

    def _record_feedback(self, now_state) -> None:
        """One round's label: what was advised against what was thrown.

        THE MOVE IS OBSERVED, NEVER ASKED FOR: the pouch is read every
        poll, and a thrown gag takes exactly one off exactly one cell,
        so diffing the before/after board says what was played exactly
        -- no question put to a player mid-fight, no reliance on memory.

        A round it cannot read is recorded WITH THE REASON rather than
        dropped or guessed at -- these rows are training data and a
        wrong one is permanent in a way a missing one is not.
        `feedback.spent_gag` owns that judgement.

        Never raises: advice must not be lost to its own bookkeeping.
        """
        if not self.feedback_to:
            return
        try:
            from . import feedback as feedback_mod

            before = self._prev_state
            if before is None:
                return
            if self._feedback is None:
                # "realms" IS A QUARANTINE FLAG: nothing read from Realms
                # may train a TTR policy, and stamping it at write time
                # survives a later file rename.
                self._feedback = feedback_mod.FeedbackLog(
                    self.feedback_to, source="realms")

            key, why = feedback_mod.spent_gag(
                getattr(before.toon, "gag_counts", None),
                getattr(now_state.toon, "gag_counts", None))

            observed = None
            if key is not None:
                from .. import data
                from ..state import Action

                track, level = key
                try:
                    group = bool(data.gag(track, level).group)
                except Exception:              # noqa: BLE001
                    group = False
                observed = Action(
                    track=track, level=level,
                    target_index=feedback_mod.infer_target(
                        before.cogs, now_state.cogs, group))

            decision = feedback_mod.Decision(
                source="realms",
                round_num=getattr(before, "round_num", 0),
                state=before,
                rl=self._rl_action,
                search=self._search_action,
                playout=getattr(self, "_playout_action", None),
                observed=observed,
                unreadable=why,
                engine_shown=self.model.engine or "",
                rejected=tuple(sorted(map(repr, self._rejected))),
                objective=self.objective_name,
                policy_id=_policy_id(),
                outcome=_outcome(before, now_state))
            written = self._feedback.append(decision)
            self._show_receipt(decision, before, written)
        except Exception:                      # noqa: BLE001
            # Recording must never cost the advice it records.
            pass

    def _watch_step(self, now_state) -> None:
        """One round of a watched fight, appended to the open episode.

        INDEPENDENT OF THE ADVICE: runs whether or not either engine was
        consulted, since watch mode records how the fight was actually
        played and paying for search advice nobody reads would make a
        VP run unwatchable.

        The board recorded is the one BEFORE the action, so the pair is
        a transition rather than a snapshot.
        """
        if not self.watch_to:
            return
        try:
            from . import feedback as feedback_mod

            before = self._prev_state
            if before is None:
                return
            if self._watch is None:
                self._watch = feedback_mod.WatchLog(self.watch_to,
                                                    source="realms")
            if self._episode is None:
                self._episode = feedback_mod.Episode(
                    source="realms",
                    kind=str(getattr(before, "kind", "street") or "street"))

            key, why = feedback_mod.spent_gag(
                getattr(before.toon, "gag_counts", None),
                getattr(now_state.toon, "gag_counts", None))
            action = None
            if key is not None:
                from .. import data
                from ..state import Action

                track, level = key
                try:
                    group = bool(data.gag(track, level).group)
                except Exception:                  # noqa: BLE001
                    group = False
                action = Action(track=track, level=level,
                                target_index=feedback_mod.infer_target(
                                    before.cogs, now_state.cogs, group))

            self._episode.steps.append(feedback_mod.Step(
                round_num=getattr(before, "round_num", 0),
                state=before, action=action, unreadable=why,
                laff=tuple(int(t.laff) for t in before.toons),
                hp=tuple(int(c.hp) for c in before.cogs)))
            self._episode.final = now_state
        except Exception:                          # noqa: BLE001
            pass

    def _close_episode(self) -> None:
        """Write the fight that just ended, and start a fresh one.

        The outcome is read from the LAST board seen, not the absence of
        one: a battle can also vanish because the client dropped or the
        player walked away, and calling that a loss would teach the
        wrong lesson. `feedback.outcome_of` leaves it unknown instead.
        """
        episode = self._episode
        self._episode = None
        if episode is None or self._watch is None:
            return
        try:
            from . import feedback as feedback_mod

            # The final round: the board moved from `_prev_state` to
            # nothing, so the action is unreadable, but the STATE is the
            # terminal position and worth having on its own.
            if self._prev_state is not None:
                episode.steps.append(feedback_mod.Step(
                    round_num=getattr(self._prev_state, "round_num", 0),
                    state=self._prev_state, action=None,
                    unreadable="the fight ended on this round",
                    laff=tuple(int(t.laff) for t in self._prev_state.toons),
                    hp=tuple(int(c.hp) for c in self._prev_state.cogs)))
                episode.final = self._prev_state
            episode.outcome = feedback_mod.outcome_of(episode.final)
            self._watch.append(episode)
        except Exception:                          # noqa: BLE001
            pass

    def _show_receipt(self, decision, state, written: bool) -> None:
        """The strip under the advice: what was just logged, or why not.

        A RECEIPT, not a question: the move was read, not asked for, so
        the ordinary case needs no answer and the strip exists to be
        ignored -- it lets a player notice a bad write while they still
        remember the round.

        An unreadable round says so INSTEAD of naming a move: a gap
        found here costs one glance, a gap found at fit time costs the
        run.
        """
        from .. import data

        model = self.model
        model.feedback_move = ""
        model.feedback_against = ""
        model.feedback_problem = ""
        model.feedback_fixable = False
        model.feedback_needs_target = False
        model.feedback_stated = False

        if decision.unreadable:
            model.feedback_problem = decision.unreadable
        elif decision.observed is not None:
            try:
                model.feedback_move = data.gag(decision.observed.track,
                                               decision.observed.level).display
            except Exception:                  # noqa: BLE001
                model.feedback_move = "your move"
            # Name the engine departed from, not both: "differs from
            # both" is already what two names side by side say.
            beats = decision.beats()
            against = [name for name, differed in beats.items() if differed]
            if against:
                model.feedback_against = ", ".join(sorted(against))
            # Only worth asking about when the answer is missing AND
            # there is more than one cog it could have been.
            model.feedback_needs_target = (
                decision.observed.target_index is None
                and len(getattr(state, "cogs", ()) or ()) > 1)
        if written:
            self._last_rid = decision.rid
            model.feedback_fixable = True
        model.feedback_at = time.time()

    def suggest_move(self, track=None, level=None, target_index=None,
                     fire: bool = False, is_pass: bool = False) -> None:
        """The player naming the move they would make instead.

        WRITTEN AGAINST THE BOARD ON SCREEN, immediately, as its own row
        -- it does not wait for the round to resolve, since waiting
        would lose every preference stated on a fight's last round,
        exactly when the interesting ones get given.

        A row can therefore carry a stated move and, later, an observed
        one for the same board, deliberately: whether a player does what
        they say is worth counting. See `Decision.player_move`.

        Refuses a gag the toon is not carrying -- a preference for a
        move that was never available is not a preference.
        """
        if not self.feedback_to:
            return
        try:
            from .. import data
            from . import feedback as feedback_mod
            from ..state import Action, Track

            state = self._prev_state
            if state is None:
                return

            if is_pass:
                action = Action(track=None)
            elif fire:
                if target_index is None:
                    return
                action = Action(track=None, fire=True,
                                target_index=int(target_index))
            else:
                if track is None or level is None:
                    return
                key = (Track(str(track)), int(level))
                held = (getattr(state.toon, "gag_counts", {}) or {}).get(key, 0)
                if held <= 0:
                    self.model.feedback_problem = (
                        "not carrying that -- nothing recorded")
                    self.model.feedback_move = ""
                    self.model.feedback_at = time.time()
                    self._post()
                    return
                group = bool(data.gag(*key).group)
                action = Action(track=key[0], level=key[1],
                                target_index=(None if group or target_index is None
                                              else int(target_index)))

            if self._feedback is None:
                self._feedback = feedback_mod.FeedbackLog(
                    self.feedback_to, source="realms")
            decision = feedback_mod.Decision(
                source="realms",
                round_num=getattr(state, "round_num", 0),
                state=state,
                rl=self._rl_action,
                search=self._search_action,
                playout=getattr(self, "_playout_action", None),
                preferred=action,
                engine_shown=self.model.engine or "",
                rejected=tuple(sorted(map(repr, self._rejected))),
                objective=self.objective_name,
                policy_id=_policy_id())
            written = self._feedback.append(decision)

            model = self.model
            model.feedback_move = _render(action, state)
            model.feedback_problem = ""
            model.feedback_needs_target = False
            beats = decision.beats()
            against = [n for n, differed in beats.items() if differed]
            model.feedback_against = ", ".join(sorted(against))
            model.feedback_stated = True
            if written:
                self._last_rid = decision.rid
                model.feedback_fixable = True
            model.feedback_at = time.time()
            self._post()
        except Exception:                      # noqa: BLE001
            # Never at the cost of the advice on screen.
            pass

    def correct_feedback(self, target_index=None, discard: bool = False) -> None:
        """The player overruling the last row, from the strip.

        Only the most recent row can be amended. The log is append-only
        and a correction names the row it fixes, so offering this on an
        older one would quietly edit whichever row happened to be last.
        """
        rid = getattr(self, "_last_rid", "")
        if not rid or self._feedback is None:
            return
        index = None
        if target_index is not None and not discard:
            try:
                index = int(target_index)
            except (TypeError, ValueError):
                return
        self._feedback.correct(rid, target_index=index, discard=bool(discard))
        self._last_rid = ""
        self.model.feedback_fixable = False
        self.model.feedback_needs_target = False
        if discard:
            self.model.feedback_move = ""
            self.model.feedback_problem = "not logged -- you said it was wrong"
        self._post()

    def _record_position(self, state, advice: str) -> None:
        """Append the EXACT position searched, so it can be replayed.

        Reconstructing a board from a screenshot has failed twice on
        picks the owner reported, each time giving a sensible move that
        proved the panel searched something else -- hand rebuilding
        can't find that.

        Pickle rather than a summary: a summary only records what I
        thought to write down, which is the assumption that keeps
        being wrong.
        """
        if not self.record_to:
            return
        import pickle

        try:
            with open(self.record_to, "ab") as handle:
                pickle.dump({"state": state, "advice": advice,
                             "objective": self.objective_name,
                             "engine": self.engine,
                             "allow_level_7": self.allow_level_7,
                             "budget": self.budget, "depth": self.depth},
                            handle)
            self.recorded += 1
        except Exception as exc:        # noqa: BLE001
            # SAY SO, ONCE: a diagnostic that fails silently is worse
            # than none, since it is trusted.
            if not self.record_error:
                self.record_error = f"{exc.__class__.__name__}: {exc}"
                self.model.problems = list(self.model.problems) + [
                    f"--record is not writing to {self.record_to}: "
                    f"{self.record_error}"]

    def _search(self, state) -> None:
        # WATCH MODE RUNS NEITHER ENGINE: a VP is forty-plus rounds, and
        # spending CPU on advice nobody reads has no return. The board is
        # still read every poll, which is all the recorder needs.
        if self.engine == "none":
            self.model.thinking = False
            return
        with self._lock:
            token = next(self._generation)
            self._current = token
            objective, depth, budget = (self.objective, self.depth,
                                        self.budget)
        threading.Thread(target=self._run_search, daemon=True,
                         args=(token, state, objective, depth,
                               budget, self._allies)).start()

    def _first_answer(self, state):
        """The trained policy's move, in milliseconds.

        `hybrid.climb` is what every offline evaluation in this project
        runs, and is a thousand times faster than the search: 1-224ms
        against 9-12s on the same positions.

        Used here to answer IMMEDIATELY, not to replace the search --
        which of the two plays better is genuinely unmeasured (they
        agreed on one of three test positions, differed on two) -- so
        the fast answer goes up first and the search replaces it if it
        disagrees.
        """
        try:
            import random

            from ..search import hybrid

            hybrid.LAST_UNITE = None
            # BUDGET 24, not `climb`'s default of 8: at 8 the targeted
            # probes, appended after the track sweep, are never reached.
            # Measured on the sampler's parties, two seed blocks:
            # 88.8%->98.4% and 85.2%->99.2%, p<0.001 both, and fewer
            # slips spent (18.4->14.5). Costs 5ms against a poll
            # interval measured in hundreds.
            # A COPY: `climb` applies its unite in place, and this board
            # is the one the Search row, the explanations and the log read
            # next -- see `advise.first_answer`.
            plan = hybrid.climb(state.clone(), random.Random(0),
                                budget=PANEL_BUDGET,
                                reject=frozenset(self._rejected))
            # The unite `climb` chose, if any. Read straight after the
            # call: it's a module global the next call overwrites.
            chosen = hybrid.LAST_UNITE
            if chosen is None:
                self._advise_unite(self.model, "")
            else:
                from .. import unites as unites_mod
                self._advise_unite(self.model, unites_mod.describe(chosen))

            # Same helper the screen-reading panel uses, so the two front
            # ends never explain a move differently.
            from . import explain as explain_mod

            first = plan[0] if plan else None
            detail = explain_mod.describe(state, first)
            self.model.incoming = detail.get("incoming")
            self.model.survive = detail.get("survive")
            self.model.accuracy = detail.get("accuracy")
            self.model.reason = explain_mod.reason(detail)
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

    def _run_search(self, token, state, objective, depth, budget,
                    allies=()) -> None:
        # A NEW POSITION INVALIDATES THE STORED SEARCH ANSWER -- leaving
        # it would let the badge toggle show last round's move.
        self.model.search_gag = ""
        self.model.search_track = ""
        self.model.search_gag_level = 0
        self.model.search_ready = False

        # IN A GROUP, COORDINATED: PPO and the playouts plan with
        # teammates as toons, choosing the whole party's moves together
        # (a Lure for a teammate's Sound, 7s held for the round that
        # needs them), assuming they play theirs -- the panel shows only
        # YOUR part. Measured on 40 party VPs: planned together 23 wins,
        # each toon alone 0. The expectimax search still keeps allies as
        # a count.
        board = state
        if allies:
            import copy

            board = state.clone()
            board.toons = [board.toons[0]] + [copy.deepcopy(a) for a in allies]
            board.allies_standing = max(0, board.allies_standing - len(allies))

        if self.engine != "search":
            quick = self._first_answer(board)
            if quick is not None:
                with self._lock:
                    fresh = token == self._current
                if fresh:
                    self._rl_action = quick
                    self.model.rl_gag = _render(quick, state)
                    self.model.rl_track = _track_of(quick) or ""
                    self.model.rl_gag_level = _level_of(quick) or 0
                    # THE WHY-LINE, which this panel never had. Same
                    # solver, same numbers -- there was no reason for it
                    # to explain itself in one window and not the other.
                    self._describe_into(self.model, state, quick, "rl")
                    self._sync_explanation(self.model)
                    # Shown now whatever the preference: it is the only
                    # answer that exists this early, and a blank panel
                    # while the search runs is the complaint that
                    # started all of this.
                    self._show(quick, state,
                               thinking=self.engine == "both", engine="rl")
            if self.engine == "rl":
                self._record_position(state, _render(quick, state))
                return              # the policy's answer stands

        # THE THIRD ANSWER, alongside the search rather than after it.
        # Its own child process; the horizon is what the boss tracker
        # says is still coming, and nothing about which cogs.
        def _current(token=token):
            with self._lock:
                return token == self._current

        self._start_playout(
            board,
            self.boss_tracker().horizon(
                on_field=sum(1 for c in state.cogs if c.hp > 0)),
            budget, _current,
            lambda a, st: (_render(a, st), _track_of(a) or "",
                           _level_of(a) or 0),
            shown=state)

        try:
            future = self._pool().submit(
                search_in_child, state,
                getattr(objective, "name", self.objective_name),
                depth, budget, self.allow_level_7)
            # A margin past the child's own deadline, only to stop a
            # wedged process holding the panel on "thinking" forever.
            text, track, level, target = future.result(timeout=budget + 20.0)
            if text == MISSING_DATA:
                # Keep the policy's move -- the only real answer here --
                # and say what stopped the search, not that it's slow.
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
            # A search that dies takes its thread with it unnoticed: no
            # advice appears, looking exactly like one still running.
            text, track, level, target = (f"the search failed: "
                                          f"{exc.__class__.__name__}: {exc}"), None, None, None

        with self._lock:
            if token != self._current:
                return                  # the fight moved on

        # STORED ALWAYS, DISPLAYED ON REQUEST: the search runs whichever
        # engine is on screen, so swapping to it later costs nothing.
        #
        # THE SEARCH HANDS BACK TEXT, NOT AN ACTION -- `search_in_child`
        # runs in another process -- so the move is rebuilt by the same
        # route Reconsider uses: any `ACTIONS` entry of that track and
        # level, then the real target copied onto it. The target matters:
        # `target_index=None` means "every active cog" to the simulator,
        # which is true for `reject_key` but wrong for `explain.describe`,
        # which simulates the round.
        self._search_action = None
        rebuilt = None
        if track and track not in ("fire", "sos") and level:
            import dataclasses

            from ..state import Track

            try:
                rebuilt = _entry_for(Track(track), level)
            except (LookupError, ValueError):
                rebuilt = None
            if rebuilt is not None:
                # A COPY, carrying the real target: `_entry_for` hands
                # back the shared `env.ACTIONS` entry, so setting the
                # target directly would edit the action table for every
                # later lookup.
                rebuilt = dataclasses.replace(rebuilt, target_index=target)
        self._search_action = rebuilt
        self.model.search_gag = text
        self.model.search_track = track or ""
        self.model.search_gag_level = level or 0
        if rebuilt is not None:
            self._describe_into(self.model, state, rebuilt, "search")
        self._sync_explanation(self.model)
        self.model.search_ready = True
        self.model.thinking = False

        if self.model.preferred_engine == "search":
            # The expectimax path does not model unites, so a unite
            # suggested beside the POLICY's move must not linger over
            # the search's. Better no advice than advice for a plan
            # that is no longer on screen.
            self.model.unite = ""
            self.model.gag = text
            self.model.gag_at = time.time()
            self.model.track = track
            self.model.gag_level = level
            self.model.engine = "search"
        self._record_position(state, text)
        self._post()

    def _show(self, action, state, thinking: bool = False,
              engine: str = "") -> None:
        """Put a move on the panel without ending the search.

        `engine` says WHICH one produced it, shown as a badge rather than
        folded into the sentence. It's not decoration: the objective
        control steers the search but NOT the policy -- `hybrid.climb`
        takes no objective -- so an "rl" answer is the same move whatever
        the player picked, and the badge is what stops that from reading
        as a lie.
        """
        self.model.gag = _render(action, state)
        self.model.engine = engine
        self.model.gag_at = time.time()
        self.model.track = _track_of(action)
        self.model.gag_level = _level_of(action)
        self.model.thinking = thinking
        self._post()

    def _post(self) -> None:
        from copy import copy

        self.model.allow_level_7 = self.allow_level_7
        self.model.max_fires = self.max_fires
        self.model.max_unites = self.max_unites
        self.model.max_sos = self.max_sos
        self.model.fires_left = self.remaining("fires")
        self.model.unites_left = self.remaining("unites")
        self.model.sos_left = self.remaining("sos")
        self.model.objective = self.objective_name
        self.model.budget = self.budget
        # LATEST WINS, not FIFO: a stale battle state isn't merely late,
        # it's wrong (advice computed for a cog that has since died), so
        # when the queue is full the old model is dropped, not the new.
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

    `name_cog` and `mark_lured` are INERT rather than absent: the server
    states both, so a click should not override it, but the page is
    shared and a missing method fails at click time with nothing the
    player ever sees. They exist and do nothing.
    """

    def __init__(self, state: "RealmsPanelState", worker: RealmsWorker):
        self._state = state
        self._worker = worker

    def pull(self) -> str:
        return model_json(self._state.model)

    def prefer_engine(self, name) -> None:
        """Badge click: read the other engine's answer, already computed."""
        self._worker.prefer_engine(name)

    def suggest_move(self, track=None, level=None, target_index=None,
                     fire=False, is_pass=False) -> None:
        """The "I'd use" picker: the move the player says is right here."""
        self._worker.suggest_move(track=track, level=level,
                                  target_index=target_index,
                                  fire=bool(fire), is_pass=bool(is_pass))

    def correct_feedback(self, target_index=None, discard=False) -> None:
        """The strip's "wrong?" control.

        Two answers only: name the cog the reader could not pin, or
        discard the row. No way to edit the GAG from here -- that field
        was read off the pouch exactly, so disagreeing with it means
        something else is wrong and the row should go, not be patched.
        """
        self._worker.correct_feedback(target_index=target_index,
                                      discard=bool(discard))

    def set_max_fires(self, count) -> None:
        """The pink slip cap box. Zero means never advise a fire."""
        self._worker.set_max_fires(count)

    def set_max_unites(self, count) -> None:
        self._worker.set_max_unites(count)

    def set_max_sos(self, count) -> None:
        self._worker.set_max_sos(count)

    def reconsider(self, scope=None) -> None:
        """Reject the move on screen and offer the next best.

        `scope` is "gag" | "track" | omitted for the middle width, the
        same three the other panel offers -- one page renders both, so
        a control that worked in one window and not the other would be
        the drift this shares a worker to avoid.
        """
        self._worker.reconsider(str(scope) if scope else "kind")

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

    def set_cog_level(self, *_args) -> None:
        """Inert. Levels come from `setLevelDist`, exactly."""
        return None

    def mark_lured(self, *_args) -> None:
        """Inert. Lure state comes from the battle roster."""
        return None

    def mark_trapped(self, *_args) -> None:
        """Inert. Trap state comes from the battle roster."""
        return None

    def set_toon_count(self, count) -> None:
        """The pill: toons in the whole fight. Your battle's party is READ
        here, from `setMembers`, and a click never overrides it -- but in a
        boss fight a duo VP leaves you alone in your battle, so the pill
        is a floor on the fight's size, where the server says less."""
        self._worker.set_boss_players(count)

    def set_boss(self, kind) -> None:
        """Name the boss fight by hand, or "" to use detection."""
        self._worker.set_boss(str(kind or ""))

    def set_cogs_defeated(self, count) -> None:
        """Correct the cogs-defeated count."""
        self._worker.set_cogs_defeated(count)

    def ask_now(self) -> None:
        """Recompute now. The page's "Work it out" button."""
        self._worker.ask_now()

    def restart_discord(self) -> None:
        """Inert: the floor reader is the TTR panel's. The page is shared,
        so the click has to land somewhere; it is never shown here."""
        return None

    def toggle_fight(self, *_args) -> None:
        """The page's "I'm in a fight" button.

        It RECOMPUTES rather than overriding detection, the opposite of
        the TTR panel (which sets `forced` because its pixel reader can
        genuinely miss a fight). Here the cluster states whether a
        battle exists, so asserting one would replace a fact with an
        opinion -- and would change nothing anyway if the reader can't
        build a state. What's useful about the button is the
        impatience, so that's the part it serves: refresh and
        re-search immediately.
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
        """Only the battle and its own cogs -- the street sends a
        `setState` per wandering cog several times a second, which
        would bury the lines that matter."""
        for battle in listener.battles():
            if do_id == battle.do_id:
                return True
            members = realms_mod.parse_members(battle.get("setMembers"))
            if members and do_id in tuple(members.suits) + tuple(members.toons):
                return True
        return False

    def snapshot() -> str:
        """What `build_state` would report RIGHT NOW.

        The arrival log alone can't tell a listener bug from a model
        bug -- it shows the value landing, never what the panel holds a
        moment later. Printing both together does.
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
            # THE ROUND'S ACTUAL RESULT: `ToonAttack.hp` is damage dealt
            # per target and `suitDied` whether it finished the cog --
            # against `setChosenToonAttacks`, which is only what was
            # AIMED.
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
            # THROTTLED: a full refresh every poll put a few hundred
            # queries a second through the message director, mostly
            # re-describing objects that hadn't changed. The battle
            # roster is cheap and worth doing often; everything else
            # is not.
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
                        choices=("both", "rl", "search", "none"),
                        help="'rl' is the trained policy alone, in "
                             "milliseconds, ignoring the objective. "
                             "'search' is expectimax alone, which honours "
                             "it. 'both' shows the policy first and lets "
                             "the search replace it. Which plays better "
                             "is genuinely unmeasured.")
    parser.add_argument("--watch", metavar="PATH",
                        help="record the fight as a TRAJECTORY to PATH: "
                             "one episode per battle, written when the "
                             "fight ends so the terminal round is in it. "
                             "Pair with --engine none to watch without "
                             "paying for advice nobody reads. Rows are "
                             "stamped source=realms.")
    parser.add_argument("--feedback", metavar="PATH",
                        help="append one labelled row per round to PATH: "
                             "the board, both engines' proposals, and the "
                             "move ACTUALLY made, read off the pouch. "
                             "Unreadable rounds are recorded with the "
                             "reason. Rows are stamped source=realms, "
                             "quarantining them from TTR training -- see "
                             "solver/live/feedback.py.")
    parser.add_argument("--record", metavar="PATH",
                        help="append every searched position and its "
                             "advice to PATH, so a bad pick can be "
                             "replayed exactly -- rebuilding a board from "
                             "a screenshot has twice produced a position "
                             "the solver handles fine, proving only that "
                             "the reconstruction was wrong.")
    parser.add_argument("--trace", action="store_true",
                        help="log every field the cogs and the battle "
                             "receive, with timestamps -- for working out "
                             "WHY a value is late, e.g. whether the "
                             "server re-sends setHP on a hit.")
    parser.add_argument("--headless", action="store_true",
                        help="no window: print what the worker sees each "
                             "poll. The only way to tell a panel that "
                             "can't read the fight apart from one whose "
                             "reader thread died -- both look frozen.")
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
    if args.record:
        # FAIL AT STARTUP, not silently on every round. Create the
        # directory if it is missing and prove the file is writable now,
        # while the player is still looking at the terminal.
        record = Path(args.record)
        try:
            record.parent.mkdir(parents=True, exist_ok=True)
            with open(record, "ab"):
                pass
            print(f"  recording positions to {record}")
        except Exception as exc:
            print(f"  cannot record to {record}: "
                  f"{exc.__class__.__name__}: {exc}")
            return 1
    worker.record_to = args.record
    worker.feedback_to = args.feedback
    worker.watch_to = args.watch
    worker.objective_name = args.objective
    state = RealmsPanelState()
    state.model.objective = args.objective
    state.model.budget = args.budget
    state.model.allow_level_7 = not args.no_level_7
    api = RealmsApi(state, worker)

    window = webview.create_window(
        "TTR Solver - Realms", str(index), js_api=api,
        width=460, height=520, x=60, y=60,
        frameless=True, on_top=True, resizable=False,
        background_color="#0d1117")
    state.window = window
    worker.start()

    def pump() -> None:
        """PUSH the model into the page. Do not merely store it.

        The page does not poll -- `App.jsx` installs `window.pushModel`
        and waits to be called; `Api.pull` exists only for `npm run dev`
        where there is no Python. Stopping at `state.model = ...` would
        leave the page rendering its own defaults forever.
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
