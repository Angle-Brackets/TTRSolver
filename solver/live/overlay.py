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
    problems: List[str] = field(default_factory=list)
    thinking: bool = False

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
    def status(self) -> str:
        if self.in_battle:
            where = "confirmed" if self.forced else "detected"
            return f"in a battle ({where})"
        return "waiting for a battle"

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
        self.model = Model()

    # -- called from the UI thread --------------------------------------

    def set_forced(self, value: Optional[bool]) -> None:
        with self._lock:
            self._forced = value

    def forced(self) -> Optional[bool]:
        with self._lock:
            return self._forced

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
                if any(e.kind in advise_mod.RECOMPUTE_ON for e in events):
                    model.thinking = True
                    thinker.submit(frame, list(watcher.view.cogs), None,
                                   self.objective, self.depth, self.budget,
                                   self.ignore_checksum)
                self._post()
                time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))
        finally:
            watcher.close()

    def _on_advice(self, lines, state) -> None:
        model = self.model
        model.thinking = False
        if state is None:
            model.problems = list(lines)
        else:
            model.problems = []
            if lines:
                model.gag, model.gag_at = lines[0], time.time()
        self._post()

    def _post(self) -> None:
        # A shallow copy per post: the UI must never read a Model that
        # the worker is halfway through updating.
        from copy import copy

        try:
            self.outbox.put_nowait(copy(self.model))
        except queue.Full:                        # pragma: no cover
            pass


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

BG = "#101418"
FG = "#e8eef4"
DIM = "#8fa0b0"
GOOD = "#6ee7a0"
WARN = "#ffcf6b"


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
        self.root.minsize(320, 150)

        self.status = tk.Label(self.root, text="", bg=BG, fg=DIM,
                               font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", padx=10, pady=(8, 0))

        self.advice = tk.Label(self.root, text="-", bg=BG, fg=FG,
                               font=("Segoe UI", 15, "bold"),
                               anchor="w", justify="left", wraplength=380)
        self.advice.pack(fill="x", padx=10, pady=(2, 4))

        self.detail = tk.Label(self.root, text="", bg=BG, fg=DIM,
                               font=("Segoe UI", 8), anchor="w",
                               justify="left", wraplength=380)
        self.detail.pack(fill="x", padx=10)

        self.button = tk.Button(self.root, text="I'm in a fight",
                                command=self._toggle, font=("Segoe UI", 9),
                                relief="flat", bg="#1d2732", fg=FG,
                                activebackground="#27343f",
                                disabledforeground="#4a5560")
        self.button.pack(fill="x", padx=10, pady=(6, 2))

        self.why = tk.Label(self.root, text="", bg=BG, fg=DIM,
                            font=("Segoe UI", 8), anchor="w")
        self.why.pack(fill="x", padx=10, pady=(0, 8))

        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.model = Model()
        self.root.after(100, self._drain)

    def _corner_of_game(self) -> str:
        """Sit against the game rather than in the middle of it."""
        from .window import game_rect

        rect = game_rect()
        if rect is None:
            return "380x170+40+40"
        left, top, right, _bottom = rect
        return f"380x170+{max(0, right - 400)}+{top + 20}"

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
        self.status.configure(
            text=model.status,
            fg=GOOD if model.in_battle else DIM)
        self.advice.configure(
            text=model.advice_text(),
            fg=FG if model.gag and model.in_battle else DIM)
        self.detail.configure(text="\n".join(model.detail_lines()[:4]))
        self.button.configure(
            text="Fight is over" if model.in_battle else "I'm in a fight",
            state="normal" if model.can_confirm else "disabled")
        self.why.configure(text=model.evidence,
                           fg=DIM if model.can_confirm else WARN)

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
