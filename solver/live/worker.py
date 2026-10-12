"""What both panels do with an answer, once something has produced one.

Two front ends share one solver and differ in ONE thing: where a
`BattleState` comes from -- the screen panel infers it from pixels, the
other is handed it by a client that already knows. Everything after
that (which engine's answer is displayed, what "no, not that" rejects,
how a setting reaches the search, when the model ships to the page) is
the same problem, solved twice before this module existed and drifting
apart each time it was touched -- Reconsider broke in each panel from an
unrelated bug months apart, and only one panel grew a why-line. So a
DECISION ABOUT AN ANSWER lives here, written once; where the answer came
from stays in the subclass.

NOT HERE ON PURPOSE: `run` (one loop polls a screen and must survive
unreadable frames, the other reacts to a live client -- different
problems, and only one is testable without a server) and `_post` (what
a subclass refreshes on the model before shipping it differs).

Nothing here imports either backend, and nothing here may: this module
is shared by a Toontown Rewritten panel and one for a different game
whose data must never reach `solver/data`, a fitted weight or a policy
score. It deals only in `Model`, `Action` and the search.
"""
from __future__ import annotations

import threading
from typing import Optional

# The answers a panel shows side by side. "rl" is `hybrid.climb`, shown
# as PPO; "search" the expectimax child; "playout" `search.playout`.
ENGINES = ("rl", "search", "playout")
# Processes for the playouts. Rollouts of different candidates are
# independent, so four processes run a chunk about four times as fast.
# Four rather than all twelve threads, because the game and the screen
# reader are running on the same machine.
PLAYOUT_WORKERS = 4


class AdviceWorker(threading.Thread):
    """The half of a panel worker that does not care where state comes from.

    Subclasses own `run`, `_post`, and whatever produces a state; they
    call `_describe_into` / `_sync_explanation` when an engine answers
    and inherit the rest.
    """

    # CLASS-LEVEL, not only set in `__init__`, because a worker built
    # any other way must still answer "nothing on screen to turn down"
    # rather than raising -- the tests construct one with `__new__`, and
    # a subclass already carries the consumable caps for exactly this
    # reason. Both are immutable, so sharing the default is safe in a
    # way a shared `_rejected` set would not be.
    _rl_action = None
    _search_action = None
    _playout_action = None
    _playout_executor = None
    # The boss fight, if any. Class-level None for the same reason as the
    # two above; `boss_tracker` builds it on first use.
    _boss = None
    # What the player picked by hand, or None for "whatever is detected".
    _boss_manual = None
    # Toons in the whole boss fight as the player states it. One toon in
    # your battle cannot tell a solo VP from one side of a two-player VP,
    # and the two meet different counts (`boss.rounds_for`).
    _boss_players = 1

    def __init__(self, outbox, objective, depth: int, budget: float):
        super().__init__(daemon=True)
        self.outbox = outbox
        self.objective = objective
        self.objective_name = getattr(objective, "name", "balanced")
        self.depth = depth
        self.budget = budget
        # OWNED HERE, not on the Model the UI holds. `_post` ships a
        # fresh copy every cycle, so anything written onto the UI's model
        # from outside is overwritten within a poll.
        from .. import state as state_mod

        self.allow_level_7 = state_mod.ALLOW_LEVEL_7
        self.toon_count = 1
        self.max_fires = 0
        self.max_unites = 0
        self.max_sos = 0
        # Keys of moves the player has turned down, per `reject_key`.
        self._rejected = set()
        # The ACTION behind each engine's answer, kept because
        # `reconsider` has to reject the move rather than its wording.
        self._rl_action = None
        self._search_action = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._asked = threading.Event()

    # -- subclass hooks --------------------------------------------------

    def _post(self) -> None:                      # pragma: no cover
        """Ship the current model to the UI. Subclasses implement."""
        raise NotImplementedError

    def _settings_changed(self) -> None:
        """A setting moved and the answer on screen predates it.

        Redraw so the control shows its new value at once, and recompute
        because the advice was worked out under the old one. A subclass
        that decides "the board has not changed" from a cached position
        key has to invalidate that key here too, or the change is
        honoured only once the board moves on its own.
        """
        self._post()
        self.ask_now()

    # -- the controls ----------------------------------------------------

    def ask_now(self) -> None:
        """Search on the next cycle, whatever the battle did.

        An Event rather than a direct call: the search must start on the
        worker thread, and the button is pressed on the UI's.
        """
        self._asked.set()

    def stop(self) -> None:
        self._stop.set()

    def set_objective(self, name: str) -> None:
        """Switch how the solver is being asked to play, mid-fight."""
        from ..search import objective as objectives

        preset = objectives.PRESETS.get(name)
        if preset is None:
            return
        with self._lock:
            self.objective = preset
            self.objective_name = name
            self.model.objective = name
        self._settings_changed()

    def set_budget(self, seconds) -> None:
        """Seconds per search. Clamped: below a second nothing finishes,
        and past a minute the advice arrives after the round."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        value = max(1.0, min(60.0, value))
        with self._lock:
            self.budget = value
            self.model.budget = value
        self._post()

    def set_level_7(self, allow) -> None:
        """Offer level 7 gags, or hold them back for a boss."""
        from .. import state as state_mod

        value = bool(allow)
        with self._lock:
            self.allow_level_7 = value
            self.model.allow_level_7 = value
        state_mod.ALLOW_LEVEL_7 = value
        self._settings_changed()

    def set_toon_count(self, count) -> None:
        """How many toons are in the fight, counting you.

        Player-set, and authoritative when it is. A miscount is not
        cosmetic: it scales how dangerous every cog looks, because a
        single-target attack has other places to land in a full group.
        """
        try:
            value = int(count)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.toon_count = max(1, min(4, value))
        self._post()

    # THE BOXES ARE A SESSION BUDGET [OWNER]: what the panel may still
    # plan with while it is open. Every spend ticks its box down, on
    # screen too, and when one runs out the player raises it. Nothing
    # resets -- there is no fight boundary to detect, so none to get
    # wrong. Per-fight baselines were tried and broke twice: a second VP
    # inherited the first one's spending, and a VP's intermission could
    # read as the fight ending.

    def remaining(self, name: str) -> int:
        """What is left of one holding: its box. Never below zero."""
        return max(0, int(getattr(self, "max_" + name, 0)))

    def spend(self, name: str, count: int = 1) -> None:
        """Tick one box down by `count`, in the model the page draws too."""
        box = "max_" + name
        left = max(0, int(getattr(self, box, 0)) - max(0, int(count)))
        setattr(self, box, left)
        model = getattr(self, "model", None)
        if model is not None:
            setattr(model, box, left)

    def note_spent(self, action, unite=None) -> None:
        """Charge a round's advice against the boxes.

        For a client that cannot SEE a slip, unite or card leave the toon
        (TTR's screen): it ASSUMES the advice was taken. Called once per
        ROUND, not once per recomputation -- the same move is re-scored
        several times while the player thinks. Correctable: the box is a
        control the player can put a number back into.
        """
        # A holding the client READS is ticked down by what really left
        # the toon (`observed`), never by the advice as well.
        observed = getattr(self, "observed", ())
        if unite is not None and "unites" not in observed:
            self.spend("unites")
        if action is None:
            return
        if getattr(action, "fire", False):
            if "fires" not in observed:
                self.spend("fires")
        elif getattr(action, "sos", None):
            self.spend("sos")

    # -- the boss fight ----------------------------------------------------

    def boss_tracker(self):
        from .boss import BossTracker

        if self._boss is None:
            self._boss = BossTracker()
        return self._boss

    def set_boss(self, kind) -> None:
        """The player naming the fight: "vp", "cfo", "cj", "ceo", or ""
        to go back to whatever is detected.

        A detected boss outranks this, because detection here reads the
        server's own objects -- but where nothing is detected, which on
        a screen-reading client is everywhere until a boss room's zone
        name has been seen, this is the only way the solver learns it.
        """
        from .boss import BOSS_KINDS

        kind = (str(kind or "").strip().lower()) or None
        if kind is not None and kind not in BOSS_KINDS:
            return
        with self._lock:
            self._boss_manual = kind
            self.boss_tracker().set_kind(kind)
        self._settings_changed()

    def allies_in_battle(self) -> int:
        """Teammates in your battle, from the toon-count pill.

        The pill is the toons in the WHOLE fight -- the one count a player
        knows. In a two-sided boss fight your battle holds your share of
        them (`boss.toons_in_battle`); anywhere else, all of them.
        """
        from . import boss as boss_mod

        return max(0, boss_mod.toons_in_battle(
            self.boss_tracker().kind, self.toon_count) - 1)

    def set_boss_players(self, count) -> None:
        """A floor on the toons in the whole boss fight, for a client that
        reads your battle's party itself: a duo VP leaves you alone in it."""
        try:
            value = max(1, min(8, int(count)))
        except (TypeError, ValueError):
            return
        with self._lock:
            self._boss_players = value
            self.boss_tracker().party_size = value
        self._settings_changed()

    def set_cogs_defeated(self, count) -> None:
        """The player correcting the count. They can see the fight."""
        try:
            value = int(count)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.boss_tracker().correct(value)
        self._settings_changed()

    def _observe_boss(self, detected) -> None:
        """Name the fight from detection, falling back to the player's
        pick. `detected` None means "nothing says it is a boss"."""
        kind = detected or self._boss_manual
        self.boss_tracker().set_kind(kind)

    # THE PLAYOUT ROW LEADS unless the player has picked an engine
    # themselves. First only in boss fights -- on duo VP sides the Search row
    # won 6/60 and the Playout row 33/60 (docs/experiment-log.md), since only
    # the playouts see the waves to come -- and since 2026-10-11 in every
    # fight: [OWNER] "I prefer playout's choice, I think it's the best in all
    # instances". PPO's instant answer shows until the playouts post theirs.
    _engine_chosen = False      # the player pressed an engine
    # The playouts' group mode for this panel's boards: None for the
    # playouts' own default, or "pickup" / "coordinated".
    group_mode = None

    def _boss_into(self, model, on_field: int = 0) -> None:
        """Mirror the tracker onto the model the page draws."""
        tracker = self.boss_tracker()
        if not self._engine_chosen and model.preferred_engine != "playout":
            model.preferred_engine = "playout"
        model.boss_kind = tracker.kind or ""
        model.boss_manual = self._boss_manual or ""
        model.boss_players = max(1, tracker.party_size)
        model.cogs_defeated = tracker.defeated if tracker.kind else 0
        left = tracker.left_in_fight(on_field) if tracker.kind else None
        model.cogs_left = -1 if left is None else left

    def _set_holding(self, name: str, count) -> None:
        """One player-declared consumable count, clamped and mirrored.

        Three boxes with one implementation. They were three copies of
        the same eight lines in each panel, which is six.
        """
        try:
            value = int(count)
        except (TypeError, ValueError):
            return
        value = max(0, min(99, value))
        with self._lock:
            setattr(self, name, value)
            setattr(self.model, name, value)
        self._settings_changed()

    def set_max_fires(self, count) -> None:
        self._set_holding("max_fires", count)

    def set_max_unites(self, count) -> None:
        self._set_holding("max_unites", count)

    def set_max_sos(self, count) -> None:
        self._set_holding("max_sos", count)

    # -- the two engines -------------------------------------------------

    # The unite PPO / the search advised, kept while the playouts' move
    # (and so the playouts' unite) is the one on screen.
    _advised_unite = ""

    def _advise_unite(self, model, text) -> None:
        """PPO's or the search's unite. `model.unite` is the one beside
        the move on screen, so it follows only while that move is theirs."""
        self._advised_unite = text or ""
        if model.engine != "playout":
            model.unite = self._advised_unite

    def prefer_engine(self, name) -> None:
        """Swap which engine's answer is on screen.

        Both are computed every round, so this costs nothing: it reads a
        value that is already here rather than starting a search.
        """
        import time

        choice = str(name).lower()
        if choice not in ENGINES:
            choice = "rl"
        with self._lock:
            model = self.model
            model.preferred_engine = choice
            self._engine_chosen = True
            swapped = False
            ready = (bool(model.rl_gag) if choice == "rl"
                     else getattr(model, choice + "_ready", False))
            if ready and getattr(model, choice + "_gag", ""):
                model.gag = getattr(model, choice + "_gag")
                model.track = getattr(model, choice + "_track") or None
                model.gag_level = getattr(model, choice + "_gag_level") or None
                model.engine = choice
                model.unite = (model.playout_unite if choice == "playout"
                               else self._advised_unite)
                swapped = True
            # SYNCED ON EVERY PATH, including the refused one. A swap can
            # be declined -- the search has not answered yet -- and then
            # `preferred_engine` moves while `engine` does not. The
            # displayed reasons follow `engine`, so syncing only on the
            # branch that swapped would leave the invariant resting on
            # how the model happened to be assembled.
            self._sync_explanation(model)
            if swapped:
                model.gag_at = time.time()
        self._post()

    @staticmethod
    def _describe_into(model, state, action, engine: str) -> None:
        """One engine's reasons, filed under that engine.

        `incoming` and `survive` are written straight to the model
        because they describe the board rather than the move, and both
        engines are looking at the same board.

        NEVER LEAVES A HALF-WRITTEN EXPLANATION. Every value is computed
        before the first assignment, so a raise anywhere in here cannot
        land a fresh accuracy beside a stale reason. See
        `_clear_engine`, which is what the callers use to make the same
        guarantee across the label as well.
        """
        from . import explain as explain_mod

        detail = explain_mod.describe(state, action)
        accuracy = detail.get("accuracy")
        why = explain_mod.reason(detail)
        organic = bool(detail.get("organic"))
        try:
            tracks = sorted(t.name.lower()
                            for t in state.toon.organic_tracks)
        except Exception:                          # noqa: BLE001
            tracks = None

        model.incoming = detail.get("incoming")
        model.survive = detail.get("survive")
        setattr(model, engine + "_accuracy", accuracy)
        setattr(model, engine + "_reason", why)
        setattr(model, engine + "_organic", organic)
        if tracks is not None:
            model.organic_tracks = tracks

    @staticmethod
    def _clear_engine(model, engine: str) -> None:
        """Drop one engine's whole answer -- label AND explanation.

        THE PAIR IS THE UNIT: a gag name and the numbers under it are one
        statement about one move. Writing the label first and the reason
        several statements later (with unite-table calls in between)
        let a raise in between leave a fresh gag on screen under the
        previous round's numbers -- seen live as a level 4 Throw still
        showing a group gag's "147 damage across 4 cogs" from the round
        before.
        """
        setattr(model, engine + "_gag", "")
        setattr(model, engine + "_track", "")
        setattr(model, engine + "_gag_level", 0)
        setattr(model, engine + "_accuracy", None)
        setattr(model, engine + "_reason", "")
        setattr(model, engine + "_organic", False)
        if engine == "search":
            model.search_ready = False
        if engine == "playout":
            model.playout_ready = False
            model.playout_note = ""
            model.playout_unite = ""
            model.playout_rollouts = 0
            model.playout_done = False

    @staticmethod
    def _sync_explanation(model) -> None:
        """Point the displayed reasons at the DISPLAYED engine's move.

        Called wherever `model.engine` is decided, so the pair the page
        renders can never belong to the move it is not showing.
        """
        engine = model.engine or "rl"
        model.accuracy = getattr(model, engine + "_accuracy", None)
        model.reason = getattr(model, engine + "_reason", "")
        model.organic = bool(getattr(model, engine + "_organic", False))

    # -- "no, not that" --------------------------------------------------

    @staticmethod
    def _reject_key(action, scope: str = "kind") -> object:
        """The key one rejection stores, at the width the player asked.

        A pass is its own constant whatever the scope: `ACTIONS` holds it
        as a literal None, with no track or level to widen to.
        """
        from ..search import hybrid

        if action.is_pass:
            return "pass"
        if scope == "gag":
            return hybrid.gag_reject_key(action)
        if scope == "track":
            return hybrid.track_reject_key(action)
        return hybrid.reject_key(action)

    def displayed_action(self):
        """The action behind the advice currently on screen, or None."""
        engine = self.model.engine
        if engine == "search":
            return self._search_action
        if engine == "playout":
            return self._playout_action
        return self._rl_action

    # -- the third engine: play it out ------------------------------------

    def _playout_pool(self):
        """Child processes for playouts, made on first use and kept.

        Their own, not the search's: the two run side by side, and a
        playout is pure Python that would otherwise hold the GIL the poll
        loop needs. Several, because rollouts of different candidates are
        independent -- see PLAYOUT_WORKERS.
        """
        if self._playout_executor is None:
            from concurrent.futures import ProcessPoolExecutor

            self._playout_executor = ProcessPoolExecutor(
                max_workers=PLAYOUT_WORKERS)
        return self._playout_executor

    def _start_playout(self, state, horizon, budget, is_current,
                       describe, shown=None) -> None:
        """Play the top moves out in the background and post the winner.

        `is_current()` says whether the board this was started for is
        still the one on screen; `describe(action, state)` gives
        (text, track, level) in the panel's own words. Never raises:
        a failed playout leaves a note on its row and costs nothing else.
        """
        import threading

        from ..search import playout as playout_mod

        with self._lock:
            self._clear_engine(self.model, "playout")
            self._playout_action = None
            self.model.playout_pending = True
        reject = frozenset(self._rejected)
        # The board the row's reasons are worded against: the panel's own,
        # not a playout board with teammates added for group play. Its
        # own name: `run` below uses `shown` for the candidate on screen,
        # and sharing the name handed the wording a key instead of a
        # board -- every move after the first came out as raw "drop/5 -> 0".
        worded_on = state if shown is None else shown

        def run():
            import time

            began = time.monotonic()
            values, plans, order, done_k = {}, {}, [], 0
            shown, last_chunk = None, 0.0
            alive = None           # keys still being rolled; None = all
            for upto in playout_mod.SCHEDULE:
                if not is_current():
                    return
                elapsed = time.monotonic() - began
                # Do not START a chunk that would end past the budget,
                # judged by how long the last one took.
                if (done_k >= playout_mod.MIN_ROLLOUTS
                        and elapsed + last_chunk > float(budget)):
                    break
                chunk_began = time.monotonic()
                try:
                    pairs, note = self._playout_chunk(
                        state, horizon, reject, done_k, upto, alive, budget)
                except Exception as exc:           # noqa: BLE001
                    pairs, note = None, f"failed: {exc.__class__.__name__}"
                last_chunk = time.monotonic() - chunk_began
                if not is_current():
                    return
                if pairs is None:
                    if not order:          # nothing shown yet: say why
                        self._deliver_playout(worded_on, None, note, describe)
                        return
                    break                  # keep the best already shown
                keys = [playout_mod._key(plan) for plan, _v in pairs]
                if order and keys != order:
                    break                  # a different menu: keep what we have
                order = keys
                for key, (plan, got) in zip(keys, pairs):
                    plans[key] = plan
                    values.setdefault(key, []).extend(got)
                done_k = upto
                if len(order) == 1:
                    plan = plans[order[0]]
                    self._deliver_playout(worded_on, plan[0] if plan else None,
                                          "", describe,
                                          unite=playout_mod.unite_of(plan))
                    return                 # nothing to choose between
                # SUCCESSIVE HALVING, at `playout.HALVING`'s points (8 and
                # 16 rollouts, as measured): the weaker half stops being
                # rolled, and survivors refine while the think time lasts.
                # A move is still shown from the first two rollouts.
                live = alive if alive is not None else list(order)
                if done_k in playout_mod.HALVING[:-1]:
                    live = sorted(live, key=lambda k: (
                        -sum(values[k]) / len(values[k]), order.index(k)))
                    live = live[:max(playout_mod.HALVING_KEEP_AT_LEAST,
                                     (len(live) + 1) // 2)]
                alive = live
                # While refining, the move on screen changes only for a
                # lead beyond noise; the scorer's pick holds it at first.
                if shown is None or shown not in alive:
                    shown = max(alive, key=lambda k: (
                        sum(values[k]) / len(values[k]), k == order[0]))
                best = max(alive, key=lambda k: (sum(values[k]) / len(values[k]),
                                                 k == order[0]))
                n = min(len(values[best]), len(values[shown]))
                if best != shown and playout_mod.leads(values[best][:n],
                                                       values[shown][:n]):
                    shown = best
                plan = plans[shown]
                self._deliver_playout(worded_on, plan[0] if plan else None, "",
                                      describe, rollouts=done_k,
                                      finished=False,
                                      unite=playout_mod.unite_of(plan))
            if not order or not is_current():
                return
            # FINISHED: the measured rule, plain best mean (ties to the
            # scorer's pick), whatever was on screen while refining.
            final = max(alive or order, key=lambda k: (
                sum(values[k]) / len(values[k]), k == order[0]))
            plan = plans[final]
            self._deliver_playout(worded_on, plan[0] if plan else None, "",
                                  describe, rollouts=done_k, finished=True,
                                  unite=playout_mod.unite_of(plan))

        threading.Thread(target=run, daemon=True).start()

    def _playout_chunk(self, state, horizon, reject, k_from, k_to, alive,
                       budget):
        """One chunk of rollouts, the candidates split across processes.

        Every process rebuilds the same menu (it is deterministic) and
        rolls only its share; the shares are merged by key. A menu that
        differs between processes is treated as a failed chunk rather
        than merged, since the keys would no longer line up.
        """
        from ..search import playout as playout_mod

        pool = self._playout_pool()
        allow7 = bool(self.allow_level_7)
        timeout = float(budget) + 30.0
        keys = alive
        if keys is None:
            keys, note = pool.submit(playout_mod.menu_in_child, state, reject,
                                     allow7, True, self.group_mode
                                     ).result(timeout=timeout)
            if keys is None:
                return None, note
        workers = max(1, min(PLAYOUT_WORKERS, len(keys)))
        parts = [keys[i::workers] for i in range(workers)]
        style = getattr(self, "objective_name", "balanced")
        futures = [pool.submit(playout_mod.chunk_in_child, state, horizon,
                               reject, allow7, k_from, k_to, part, True, style,
                               self.group_mode)
                   for part in parts]
        merged, order = None, None
        for future in futures:
            pairs, note = future.result(timeout=timeout)
            if pairs is None:
                return None, note
            got = [playout_mod._key(plan) for plan, _v in pairs]
            if merged is None:
                merged = [(plan, list(values)) for plan, values in pairs]
                order = got
            elif got != order:
                return None, "menus disagreed"
            else:
                for (_plan, into), (_p, values) in zip(merged, pairs):
                    into.extend(values)
        return merged, ""

    def _deliver_playout(self, state, action, note, describe,
                         rollouts: int = 0, finished: bool = True,
                         unite=None) -> None:
        """Post the playouts' current best. Called after every chunk, so
        the move on screen improves while the player reads it."""
        import time

        model = self.model
        with self._lock:
            previous = model.playout_gag
            self._clear_engine(model, "playout")
            self._playout_action = action
            if action is not None:
                try:
                    text, track, level = describe(action, state)
                    model.playout_gag = text
                    model.playout_track = track or ""
                    model.playout_gag_level = level or 0
                except Exception:                  # noqa: BLE001
                    # THE MOVE STILL STANDS even if wording it fails --
                    # falling back to plain wording rather than dropping
                    # the move. Traceback goes to the console so the
                    # cause is visible rather than guessed at.
                    import sys
                    import traceback

                    print("playout: could not word the move "
                          f"{action!r}:", file=sys.stderr)
                    traceback.print_exc()
                    model.playout_gag = (action.describe()
                                         if hasattr(action, "describe")
                                         else repr(action))
                    track = getattr(action, "track", None)
                    model.playout_track = (getattr(track, "value", "") or "")
                    model.playout_gag_level = int(getattr(action, "level", 0) or 0)
                try:
                    self._describe_into(model, state, action, "playout")
                except Exception:                  # noqa: BLE001
                    import sys
                    import traceback

                    print("playout: could not explain the move "
                          f"{action!r}:", file=sys.stderr)
                    traceback.print_exc()
            model.playout_unite = ""
            if action is not None and unite is not None:
                from .. import unites as unites_mod

                model.playout_unite = unites_mod.describe(unite)
            model.playout_ready = True
            model.playout_note = note or ""
            model.playout_rollouts = int(rollouts)
            model.playout_done = bool(finished)
            model.playout_pending = not finished
            changed = model.playout_gag != previous
            if (model.preferred_engine == "playout" and model.playout_gag
                    and (changed or model.engine != "playout")):
                model.gag = model.playout_gag
                model.gag_at = time.time()
                model.track = model.playout_track or None
                model.gag_level = model.playout_gag_level or None
                model.engine = "playout"
            if model.engine == "playout":
                # OUTSIDE the gag-changed test: a later chunk often keeps
                # the move and adds (or drops) its unite, and gating this
                # on the gag left the unite off screen until a swap.
                model.unite = model.playout_unite
            self._sync_explanation(model)
        self._post()

    def reconsider(self, scope: str = "kind") -> None:
        """Turn down the move on screen and ask for another.

        Rejects a KEY, not the exact action: every fire shares one, so
        dismissing "pink slip on cog 2" dismisses spending a slip at all,
        rather than cycling the same move across every other cog.

        `scope` sets how wide the "no" is: "gag" turns down this gag
        alone, "track" turns down the track entirely (the cog is lured,
        so no Drop at any level), and the default is the middle width --
        single-target Drops, leaving the group one available.

        Rejections last for THIS BOARD only, dropped as soon as it
        changes, so they cannot quietly narrow the rest of the fight.
        """
        with self._lock:
            action = self.displayed_action()
            if action is None:
                return                  # nothing on screen to turn down
            self._rejected.add(self._reject_key(action, scope))
        self.ask_now()
