"""A small always-on-top window: what to throw, and a way to disagree.

    python -m solver.live.overlay
    python -m solver.live.overlay --objective survive

Advice printed to a terminal is advice nobody reads mid-fight. This puts
the recommended gag on top of the game in type large enough to glance
at, and gives the player somewhere to say "I am in a fight" when the
detector has not worked it out.

WHY A MANUAL OVERRIDE AT ALL
----------------------------
Everything upstream infers a battle from pixels, and the two ways that
has gone wrong point in opposite directions: teal scenery read as cog
plates, and a camera cut mid-round read as the fight ending. The player
does not have to infer anything. They can see.

So the button is a first-class input, not a debugging aid. It is
deliberately *not* always available: an override that can be pressed
when there is no evidence of a fight is a way to ask for advice about a
battle that is not happening, and the answer would be assembled from
whatever the readers last saw. `Model.can_confirm` is what gates it, and
`Model.evidence` says in words why it is or is not offered -- a disabled
button with no explanation is worse than no button.

Confirming does not conjure cogs. Plates are still what the readers
read, so forcing a battle with nothing on screen gets "no cog plates",
same as before. What it does is skip the gag-menu requirement for
*entering* a fight, and stop the grace timer from ever ending one.

THREADS
-------
Tk owns the main thread and will not be called from another one. The
watcher and the solver run behind it and hand updates over a queue,
which the UI drains on a timer. Nothing else crosses the boundary: the
worker never touches a widget and the UI never blocks on a search.

The logic lives in `Model`, which knows nothing about Tk, so the part
with the decisions in it can be tested on a machine with no display.
"""
from __future__ import annotations

import argparse
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

# Poll cadence for the eye. The solver runs only when the battle
# changes, so this is the cost of noticing that it has.
POLL_INTERVAL = 0.5

# How long a recommendation stays on screen after the fight that
# produced it ends. Long enough to read, short enough not to be mistaken
# for advice about the next one.
ADVICE_LINGER = 4.0


# Shortest believable gap between two rounds. The gag menu is what the
# turn count is derived from, and a momentary misread of it would
# otherwise count a round; nothing in Toontown resolves a round and
# offers the menu again inside a few seconds.
MIN_TURN_GAP = 4.0


class TurnCounter:
    """Which round the battle is on, near enough to display.

    Nothing reports this. The Local API does not know a battle is
    happening and the plates do not say, so it is inferred from the gag
    menu: it opens once per round to take your choice, so a rising edge
    is a new round.

    An estimate, and labelled as one wherever it is shown. It cannot see
    a round the menu was never opened for -- if you sit out the timer
    the game picks for you and this misses it -- and it restarts at zero
    with each battle rather than trying to recover a count it lost.
    """

    def __init__(self) -> None:
        self.turn = 0
        self._menu_was_up = False
        self._last_turn_at = 0.0

    def observe(self, in_battle: bool, menu_visible: bool,
                now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        if not in_battle:
            self.turn, self._menu_was_up = 0, False
            return 0
        rising = menu_visible and not self._menu_was_up
        if rising and (self.turn == 0
                       or now - self._last_turn_at >= MIN_TURN_GAP):
            self.turn += 1
            self._last_turn_at = now
        self._menu_was_up = menu_visible
        return self.turn


@dataclass
class CogRow:
    """One plate, as the view needs it.

    `Model.cogs` stays a list of formatted strings because the problem
    lines share that field and the tests pin it. This is the same
    reading in the shape a health bar can be drawn from, and it carries
    only what a plate actually shows: a plate has no lure state, no trap
    and no Version 2.0 marker, so neither does this.
    """

    name: str
    level: Optional[int]
    health: float
    # `<department>-<key>`, matching visualizer/assets/cog-*.png, or None
    # when the plate was not identified to a single cog. The view falls
    # back to the department emblem, which is the honest picture: the
    # reader knows the department and not the cog, and drawing a
    # specific cog would assert more than was read.
    art_key: Optional[str] = None
    department: Optional[str] = None
    identified: bool = True


@dataclass
class Model:
    """What the window shows, and what it will let you press.

    Deliberately free of Tk. Every decision the overlay makes is here,
    so it can be checked without a display -- the UI below is a
    rendering of this and holds no logic of its own.
    """

    # What the readers can currently see.
    plates: int = 0
    menu_visible: bool = False
    window_found: bool = False
    # What the watcher believes, and what the player has insisted on.
    detected_battle: bool = False
    forced: Optional[bool] = None
    # The latest answer, and why there isn't one.
    gag: Optional[str] = None
    gag_at: float = 0.0
    cogs: List[str] = field(default_factory=list)
    rows: List["CogRow"] = field(default_factory=list)
    # The recommended gag's track, for the accent colour. None when the
    # advice is a pass, a pink slip, or absent.
    track: Optional[str] = None
    # Its level, 1-7. Track and level together name the gag, which is
    # what `visualizer/assets/gag-<track>-<level>.png` is keyed on. None
    # in exactly the cases `track` is None -- a pass and a pink slip are
    # not gags and have no picture.
    gag_level: Optional[int] = None
    problems: List[str] = field(default_factory=list)
    thinking: bool = False
    turn: int = 0

    @property
    def in_battle(self) -> bool:
        if self.forced is not None:
            return self.forced
        return self.detected_battle

    @property
    def can_confirm(self) -> bool:
        """May the player assert a battle right now?

        Only with something on screen that could be one. Confirming with
        no plates and no menu would ask for advice about a fight that is
        not happening, and the state would be built from whatever the
        readers last managed to see.
        """
        if self.in_battle:
            return True             # always allowed to say it is over
        return self.plates > 0 or self.menu_visible

    @property
    def evidence(self) -> str:
        """Why the button is offered or withheld, in words."""
        if not self.window_found:
            return "game window not found"
        seen = []
        if self.plates:
            seen.append(f"{self.plates} cog plate"
                        f"{'s' if self.plates != 1 else ''}")
        if self.menu_visible:
            seen.append("gag menu")
        if not seen:
            return "nothing on screen that looks like a battle"
        return "see: " + ", ".join(seen)

    @property
    def can_advise(self) -> bool:
        """May "work it out now" be pressed?

        The search otherwise runs only when the battle *changes* -- a
        cog dying, damage landing -- which leaves no way to retry the
        common failures. The gag menu opening after the fight started,
        or a cog being labelled mid-battle, both leave a stale problem
        on screen that nothing would recompute until something died.

        Withheld only while a search is already running, and when there
        is no battle to search.
        """
        return self.in_battle and not self.thinking

    @property
    def status(self) -> str:
        if self.in_battle:
            where = "confirmed" if self.forced else "detected"
            turn = f", turn ~{self.turn}" if self.turn else ""
            return f"in a battle ({where}{turn})"
        return "waiting for a battle"

    @property
    def status_short(self) -> str:
        """`status` without the turn, which the view shows separately.

        `status` keeps the long form: it is what the tests pin and what
        a terminal caller wants in one line.
        """
        if self.in_battle:
            return "confirmed" if self.forced else "in battle"
        return "waiting"

    def advice_text(self, now: Optional[float] = None) -> str:
        """The headline: the gag to throw, or why there isn't one."""
        now = time.time() if now is None else now
        if self.gag and (self.in_battle or now - self.gag_at < ADVICE_LINGER):
            return self.gag
        if self.thinking:
            return "thinking..."
        if not self.in_battle:
            return "-"
        return "-"

    def detail_lines(self) -> List[str]:
        if self.in_battle and self.cogs:
            return list(self.cogs)
        return list(self.problems)


class Worker(threading.Thread):
    """Runs the eye and the solver, and posts Models to the UI."""

    def __init__(self, outbox: "queue.Queue", objective, depth: int,
                 budget: float, ignore_checksum: bool = False):
        super().__init__(daemon=True)
        self.outbox = outbox
        self.objective = objective
        self.depth = depth
        self.budget = budget
        self.ignore_checksum = ignore_checksum
        self._forced: Optional[bool] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._asked = threading.Event()
        self.turns = TurnCounter()
        self.model = Model()

    # -- called from the UI thread --------------------------------------

    def set_forced(self, value: Optional[bool]) -> None:
        with self._lock:
            self._forced = value

    def forced(self) -> Optional[bool]:
        with self._lock:
            return self._forced

    def ask_now(self) -> None:
        """Run the search on the next poll, whatever the battle did.

        An Event rather than a direct call: the search must start on the
        worker thread, and the button is pressed on Tk's.
        """
        self._asked.set()

    def stop(self) -> None:
        self._stop.set()

    # -- the worker thread ----------------------------------------------

    def run(self) -> None:
        from . import advise as advise_mod
        from .gagpanel import find_panel
        from .watch import BattleWatcher
        from .window import game_rect

        watcher = BattleWatcher(battle_over=advise_mod._paid_out,
                                force_battle=self.forced)
        thinker = advise_mod.Thinker(self._on_advice)
        try:
            while not self._stop.is_set():
                cycle = time.time()
                events = watcher.poll()
                frame = watcher.capture.grab()
                model = self.model
                model.window_found = game_rect() is not None
                model.plates = len(watcher.view.cogs)
                model.menu_visible = find_panel(frame) is not None
                model.detected_battle = watcher.view.active
                model.forced = self.forced()
                model.cogs = [_describe_reading(r) for r in watcher.view.cogs]
                model.rows = [_row(r) for r in watcher.view.cogs]
                model.turn = self.turns.observe(model.in_battle,
                                                model.menu_visible)
                asked = self._asked.is_set()
                if asked:
                    self._asked.clear()
                if asked or any(e.kind in advise_mod.RECOMPUTE_ON
                                for e in events):
                    model.thinking = True
                    thinker.submit(frame, list(watcher.view.cogs), None,
                                   self.objective, self.depth, self.budget,
                                   self.ignore_checksum)
                self._post()
                time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))
        finally:
            watcher.close()

    def _on_advice(self, lines, state, action=None) -> None:
        from . import advise as advise_mod

        model = self.model
        model.thinking = False
        if state is None:
            model.problems = list(lines)
        else:
            model.problems = []
            if lines:
                model.gag, model.gag_at = lines[0], time.time()
                model.track = advise_mod.track_of(action)
                model.gag_level = (action.level if model.track else None)
        self._post()

    def _post(self) -> None:
        # A shallow copy per post: the UI must never read a Model that
        # the worker is halfway through updating.
        from copy import copy

        try:
            self.outbox.put_nowait(copy(self.model))
        except queue.Full:                        # pragma: no cover
            pass


def _row(reading) -> "CogRow":
    """A reading in the shape the view draws."""
    from .. import data

    art_key = None
    if reading.cog:
        try:
            entry = data.cog(reading.department, reading.cog)
            name = entry.display
            art_key = f"{entry.department}-{entry.key}"
        except (KeyError, ValueError):            # pragma: no cover
            name = reading.cog
        identified = True
    else:
        name = (reading.department or "unknown").title()
        identified = False
    return CogRow(name=name, level=reading.level,
                  health=max(0.0, min(1.0, float(reading.health))),
                  identified=identified, art_key=art_key,
                  department=reading.department)


def _describe_reading(reading) -> str:
    from .. import data

    if reading.cog:
        try:
            name = data.cog(reading.department, reading.cog).display
        except (KeyError, ValueError):            # pragma: no cover
            name = reading.cog
    else:
        name = f"{reading.department or 'unknown'} (unidentified)"
    level = f"lvl {reading.level}" if reading.level else "lvl ?"
    return f"{name}  {level}  {reading.health:.0%}"


# ---------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------

BG = "#0d1117"
PANEL = "#151b23"
LINE = "#232c38"
FG = "#e9eef5"
DIM = "#7d8b9a"
FAINT = "#4a5563"
GOOD = "#4ec98a"
WARN = "#e0a44a"
BAD = "#e0574f"

# Accent per gag track, so WHAT KIND of move it is reads before the
# words do. Chosen for contrast on this background and explicitly NOT
# the game's palette -- the gag menu's colours are not confirmed
# anywhere in this project, and inventing them and calling them the
# game's is the error the data rules exist to prevent.
TRACK_COLOUR = {
    "toon_up": "#e08ac4", "trap": "#e8834a", "lure": "#6fc96f",
    "sound": "#5ba8e8", "throw": "#e8c34a", "squirt": "#4fcdd6",
    "drop": "#9b8ee8",
}


class Overlay:
    """The Tk window. A rendering of `Model`, with no decisions in it."""

    def __init__(self, worker: Worker, inbox: "queue.Queue"):
        import tkinter as tk

        self.worker = worker
        self.inbox = inbox
        self.tk = tk
        self.root = tk.Tk()
        self.root.title("TTR solver")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.geometry(self._corner_of_game())
        self.root.minsize(400, 120)

        # -- status row -------------------------------------------
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=14, pady=(12, 0))
        self.dot = tk.Canvas(top, width=9, height=9, bg=BG,
                             highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 8, 8, fill=FAINT,
                                           outline="")
        self.dot.pack(side="left", pady=(3, 0))
        self.status = tk.Label(top, text="", bg=BG, fg=DIM,
                               font=("Segoe UI Semibold", 9))
        self.status.pack(side="left", padx=(7, 0))
        self.turn = tk.Label(top, text="", bg=BG, fg=FAINT,
                             font=("Segoe UI", 9))
        self.turn.pack(side="right")

        # -- the recommendation ------------------------------------
        card = tk.Frame(self.root, bg=PANEL)
        card.pack(fill="x", padx=14, pady=(9, 0))
        self.rail = tk.Frame(card, bg=FAINT, width=3)
        self.rail.pack(side="left", fill="y")
        inner = tk.Frame(card, bg=PANEL)
        inner.pack(side="left", fill="x", expand=True, padx=(11, 10), pady=9)
        self.eyebrow = tk.Label(inner, text="", bg=PANEL, fg=FAINT,
                                font=("Segoe UI Semibold", 8), anchor="w")
        self.eyebrow.pack(fill="x")
        self.advice = tk.Label(inner, text="-", bg=PANEL, fg=FG,
                               font=("Segoe UI", 16, "bold"), anchor="w",
                               justify="left", wraplength=360)
        self.advice.pack(fill="x")

        # -- the board ---------------------------------------------
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x", padx=14,
                                                    pady=(11, 8))
        self.board = tk.Frame(self.root, bg=BG)
        self.board.pack(fill="x", padx=14)
        self._rows: List = []

        # -- controls ----------------------------------------------
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x", padx=14,
                                                    pady=(10, 8))
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=14)
        self.button = tk.Button(row, text="I'm in a fight",
                                command=self._toggle, font=("Segoe UI", 9),
                                relief="flat", bg=PANEL, fg=DIM,
                                activebackground="#1d2b3a", bd=0,
                                padx=12, pady=5,
                                disabledforeground=FAINT)
        self.button.pack(side="left")
        self.advise_button = tk.Button(row, text="Work it out",
                                       command=self.worker.ask_now,
                                       font=("Segoe UI", 9), relief="flat",
                                       bg="#1d2b3a", fg=FG, bd=0,
                                       activebackground="#26374a",
                                       padx=12, pady=5,
                                       disabledforeground=FAINT)
        self.advise_button.pack(side="left", padx=(7, 0))

        self.why = tk.Label(self.root, text="", bg=BG, fg=FAINT,
                            font=("Segoe UI", 8), anchor="w")
        self.why.pack(fill="x", padx=14, pady=(9, 12))

        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.model = Model()
        self.root.after(100, self._drain)

    def _corner_of_game(self) -> str:
        """Sit against the game rather than in the middle of it."""
        from .window import game_rect

        rect = game_rect()
        if rect is None:
            return "430x150+40+40"
        left, top, right, _bottom = rect
        return f"430x150+{max(0, right - 450)}+{top + 20}"

    def _toggle(self) -> None:
        # Tri-state underneath, two-state to press: confirming a fight
        # sets True, ending one goes back to None rather than False, so
        # detection takes over again instead of being suppressed until
        # the next press.
        self.worker.set_forced(None if self.model.in_battle else True)

    def _close(self) -> None:
        self.worker.stop()
        self.root.destroy()

    def _drain(self) -> None:
        latest = None
        try:
            while True:
                latest = self.inbox.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self.model = latest
            self._render(latest)
        self.root.after(120, self._drain)

    def _render(self, model: Model) -> None:
        live = model.in_battle
        self.dot.itemconfigure(self.dot_id, fill=GOOD if live else FAINT)
        self.status.configure(text=model.status_short.upper(),
                              fg=GOOD if live else DIM)
        self.turn.configure(
            text=f"turn ~{model.turn}" if model.turn else "")

        accent = TRACK_COLOUR.get(model.track or "", FAINT)
        showing = bool(model.gag) and live
        self.rail.configure(bg=accent if showing else FAINT)
        # An empty eyebrow still occupies a line, which left the idle
        # card a tall box with a dash in it. Unpack it instead.
        label = (model.track or "").replace("_", "-").upper() if showing else ""
        if label:
            self.eyebrow.configure(text=label, fg=accent)
            if not self.eyebrow.winfo_ismapped():
                self.eyebrow.pack(fill="x", before=self.advice)
        elif self.eyebrow.winfo_ismapped():
            self.eyebrow.pack_forget()
        text = model.advice_text()
        if text == "-":
            text = ("waiting for a battle" if not live
                    else "no move to recommend")
        self.advice.configure(
            text=text,
            fg=FG if showing else DIM,
            font=("Segoe UI", 16, "bold") if showing
            else ("Segoe UI", 11))

        self._draw_board(model)

        self.button.configure(
            text="Fight is over" if live else "I'm in a fight",
            state="normal" if model.can_confirm else "disabled")
        self.advise_button.configure(
            text="thinking..." if model.thinking else "Work it out",
            state="normal" if model.can_advise else "disabled")
        self.why.configure(text=model.evidence,
                           fg=FAINT if model.can_confirm else WARN)
        self._fit()

    def _draw_board(self, model) -> None:
        """Cog plates as health bars, or the problems when there are none.

        Rebuilt rather than updated. Four rows is cheap, and a partial
        update that leaves a stale row behind reads as a cog that will
        not die.

        Only what a plate actually shows: level, cog, health. No lure or
        Version 2.0 marker, because vision cannot see either.
        """
        tk = self.tk
        for widget in self._rows:
            widget.destroy()
        self._rows = []

        rows = model.rows if model.in_battle else []
        if not rows:
            for line in model.detail_lines()[:4]:
                label = tk.Label(self.board, text=line, bg=BG, fg=DIM,
                                 font=("Segoe UI", 8), anchor="w",
                                 justify="left", wraplength=390)
                label.pack(fill="x")
                self._rows.append(label)
            return

        for row in rows[:4]:
            line = tk.Frame(self.board, bg=BG)
            line.pack(fill="x", pady=1)
            self._rows.append(line)
            tk.Label(line, text=str(row.level or "?"), bg=BG, fg=FAINT,
                     font=("Consolas", 9), width=3,
                     anchor="e").pack(side="left")
            tk.Label(line, text=row.name, bg=BG,
                     fg=DIM if row.identified else FAINT,
                     font=("Segoe UI", 9), width=15,
                     anchor="w").pack(side="left", padx=(6, 0))
            bar = tk.Canvas(line, width=100, height=7, bg=BG,
                            highlightthickness=0)
            bar.create_rectangle(0, 0, 100, 7, fill="#1c2530", outline="")
            colour = (GOOD if row.health > 0.6
                      else WARN if row.health > 0.25 else BAD)
            bar.create_rectangle(0, 0, max(2, int(100 * row.health)), 7,
                                 fill=colour, outline="")
            bar.pack(side="left", padx=(4, 7))
            tk.Label(line, text=f"{row.health:.0%}", bg=BG, fg=DIM,
                     font=("Consolas", 9), width=4,
                     anchor="e").pack(side="left")

    def _fit(self) -> None:
        """Height from the content, not from a guess.

        The window was a hardcoded 400x180 and the last line -- the one
        saying WHY the buttons are disabled -- fell off the bottom.
        """
        self.root.update_idletasks()
        want = self.root.winfo_reqheight()
        if abs(self.root.winfo_height() - want) > 2:
            self.root.geometry(f"{self.root.winfo_width()}x{want}")

    def run(self) -> None:
        self.root.mainloop()


def main(argv: Optional[List[str]] = None) -> int:
    from ..search import objective as objectives
    from .advise import DEFAULT_BUDGET, DEFAULT_DEPTH
    from .window import describe as describe_window

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objective", default="balanced",
                        help="one of " + ", ".join(sorted(objectives.PRESETS)))
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    parser.add_argument("--ignore-checksum", action="store_true",
                        help="advise even when the gag counts disagree "
                             "with the menu's own total (UNSAFE)")
    args = parser.parse_args(argv)

    try:
        objective = objectives.get(args.objective)
    except KeyError as exc:
        print(exc)
        return 2

    try:
        import tkinter                                  # noqa: F401
    except ImportError:
        print("the overlay needs tkinter, which this Python was built "
              "without; `python -m solver.live.advise` prints the same "
              "advice to the terminal")
        return 2

    print(describe_window())
    inbox: "queue.Queue" = queue.Queue(maxsize=8)
    worker = Worker(inbox, objective, args.depth, args.budget,
                    ignore_checksum=args.ignore_checksum)
    worker.start()
    Overlay(worker, inbox).run()
    worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
