"""The overlay, rendered in a webview instead of Tk.

    python -m solver.live.panel
    python -m solver.live.panel --objective survive

Same window behaviour as `overlay`: always on top, parked against the
game, updated from the same `Worker`. What changes is only the drawing
-- React and daisyUI in an Edge WebView2 window, because Tk cannot do
rounded corners, real spacing or a progress bar that is not a rectangle
someone drew.

WHY THE LOGIC DID NOT MOVE
--------------------------
`overlay.Model` stays where it is and stays Tk-free, and `overlay.Worker`
is reused verbatim. This module is a second VIEW over them. Every
decision the panel makes -- whether a fight can be confirmed, what the
evidence line says, when advice goes stale -- is still in `Model` and
still tested without a display.

So `Model.to_json` is the whole interface. If the JS needs something the
model does not expose, the fix is a property on `Model`, not a
calculation in JavaScript. Two implementations of "may the player
confirm a battle" would drift, and the one in the UI would be the one
nobody tests.

BUILT ASSETS ARE COMMITTED
--------------------------
`overlay_ui/dist` is in the repo, so running this needs Node no more
than running the solver needs a compiler. `npm run build` in
`overlay_ui/` is only for changing the UI. If `dist` is missing, this
says so and points at that command rather than opening a blank window.
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from .overlay import ADVICE_LINGER, Model, Worker

DIST = Path(__file__).resolve().parents[2] / "overlay_ui" / "dist"


def _icon_uri(getter) -> str:
    """Any cached game icon, inline for the page. "" if unavailable."""
    import base64

    try:
        raw = getter().read_bytes()
    except Exception:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _lure_icon_uri() -> str:
    """The game's own lure magnet, as a data URI for the page.

    Read from the player's installation at runtime and handed over
    inline. It is deliberately NOT bundled into `overlay_ui`: that would
    put TTR's artwork in this repository, which `ttr_assets` exists to
    avoid, and would go stale the next time the game is patched.

    Returns "" when the game is not installed or PIL is missing, and the
    panel falls back to a text badge. A missing decoration must never
    stop the panel starting.
    """
    import base64

    try:
        from . import ttr_assets

        raw = ttr_assets.lure_icon().read_bytes()
    except Exception:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


LURE_ICON = ""
MAP_ICON = ""

# The webview is told to poll this often. Python cannot push into the
# page from another thread safely, so the page asks -- which also means
# a page reloaded by hand recovers on its own.
PULL_INTERVAL_MS = 400


def model_json(model: Model) -> str:
    """`Model` in the shape the page renders.

    Deliberately flattened here rather than in JS: `advice_text` and
    `can_advise` are decisions, and decisions live in `Model`.
    """
    return json.dumps({
        "in_battle": model.in_battle,
        "status": model.status_short,
        "turn": model.turn,
        "advice": (model.gag or "") if model.in_battle
                  or (model.gag and time.time() - model.gag_at < ADVICE_LINGER)
                  else "",
        "track": model.track,
        "gag_level": model.gag_level,
        "rows": [{"name": r.name, "level": r.level,
                  "health": r.health, "identified": r.identified,
                  "art": r.art_key, "department": r.department,
                  "index": r.index, "choices": r.choices, "lured": r.lured}
                 for r in model.rows],
        "problems": list(model.problems),
        "evidence": model.evidence,
        "can_confirm": model.can_confirm,
        "can_advise": model.can_advise,
        "thinking": model.thinking,
        "allow_level_7": model.allow_level_7,
        "toon_count": model.toon_count,
        "engine": model.engine,
        "preferred_engine": model.preferred_engine,
        "max_fires": model.max_fires,
        "search_ready": model.search_ready,
        "rl_gag": model.rl_gag,
        "search_gag": model.search_gag,
        "lure_icon": LURE_ICON,
        "map_icon": MAP_ICON,
        "zone": model.zone,
        "neighborhood": model.neighborhood,
        "district": model.district,
        "invasion": model.invasion,
        "objective": model.objective,
        "budget": model.budget,
    })


class Api:
    """What the page may call. Small on purpose."""

    def __init__(self, worker: Worker, state: "PanelState"):
        self._worker = worker
        self._state = state

    def pull(self) -> str:
        return model_json(self._state.model)

    def prefer_engine(self, name) -> None:
        """INERT here. This panel has one engine.

        The other panel runs a policy and the search side by side and
        lets the badge swap between them. This one only ever runs the
        search, so there is nothing to swap to: `model.engine` is never
        set, the badge does not render, and the click cannot happen.

        It exists anyway, for the same reason `name_cog` and
        `mark_lured` exist over there -- THE PAGE IS SHARED. A call site
        in App.jsx reaches whatever Api is behind it, and a missing
        method fails at click time with nothing the player will ever
        see. `tests/test_panel_bridge` enforces that and is what caught
        this one.
        """

    def set_max_fires(self, count) -> None:
        """INERT here. Nothing on this side reads a pink slip count.

        Present because THE PAGE IS SHARED, the same reason
        `prefer_engine` is. See that method.
        """

    def reconsider(self) -> None:
        """INERT here. Present because THE PAGE IS SHARED.

        Same reason as `prefer_engine` and `set_max_fires`; see the
        first of those.
        """

    def toggle_fight(self) -> None:
        """Confirm a fight, or end one and reset.

        Reads the WORKER's view rather than the UI's Model: `_post` ships
        a fresh copy every cycle, so a decision made from the panel's
        copy races the next frame.
        """
        if self._worker.model.in_battle:
            self._worker.end_fight()
        else:
            self._worker.set_forced(True)
            self._worker.ask_now()

    def ask_now(self) -> None:
        self._worker.ask_now()

    def set_level_7(self, allow) -> None:
        """Offer level 7 gags, or hold them back.

        Delegates to the Worker, which owns the flag: `Worker._post`
        ships a fresh Model every cycle, so setting it on the UI's copy
        here would be overwritten within 250ms and the button would
        spring back. Recomputes too -- the advice on screen was worked
        out under the old setting.
        """
        self._worker.set_level_7(bool(allow))
        self._worker.ask_now()

    def close(self) -> None:
        self._state.closing = True

    def mark_lured(self, index, lured) -> None:
        """Mark a cog asleep on a Lure, or awake again.

        Nothing reads the game's lure indicator yet, and the difference
        is not cosmetic: Throw and Squirt are forced to 100% against a
        lured cog and collect the knockback bonus, Drop always misses
        one, and a lured cog does not attack. Advice given for an awake
        cog that is actually asleep is wrong in all four ways.
        """
        self._worker.mark_lured(index, bool(lured))
        self._worker.ask_now()

    def name_cog(self, slot, cog) -> None:
        """The player naming a plate the readers could not.

        Applies to this battle only. It is deliberately not written to
        the head catalogue -- a signature there is consulted forever, so
        a wrong entry poisons every later match, while a wrong name here
        costs one fight. `read_battle --label` is the way to teach it.
        """
        self._worker.name_cog(slot, cog)
        self._worker.ask_now()

    def set_objective(self, name) -> None:
        self._worker.set_objective(str(name))
        self._worker.ask_now()

    def set_budget(self, seconds) -> None:
        self._worker.set_budget(seconds)

    def set_toon_count(self, count) -> None:
        """How many toons are in the fight, counting you.

        Recomputes: the advice already on screen was worked out for a
        different party size, and party size changes how much damage
        every cog is expected to do to YOU.
        """
        self._worker.set_toon_count(count)
        self._worker.ask_now()

    def set_height(self, height: int) -> None:
        """Size the window to the page, rather than guessing at it.

        The panel grows with the number of cogs on screen and the length
        of the evidence line. The Tk overlay hardcoded a height and
        clipped its own last line; this measures instead.
        """
        window = self._state.window
        if window is None:
            return
        # 700 was the ceiling and an open cog picker needs more: four
        # rows plus a 208px list runs past it, and the clipped part is
        # exactly the part being clicked.
        height = max(160, min(900, int(height)))
        if abs(getattr(window, "height", 0) - height) > 2:
            try:
                window.resize(window.width, height)
            except Exception:
                pass


class PanelState:
    """The latest model, and whether the user has asked to quit."""

    def __init__(self) -> None:
        self.model = Model()
        self.closing = False
        self.window = None


def _geometry() -> tuple[int, int, int, int]:
    """Sit against the game rather than in the middle of it."""
    from .window import game_rect

    width, height = 430, 330
    rect = game_rect()
    if rect is None:
        return width, height, 60, 60
    _left, top, right, _bottom = rect
    return width, height, max(0, right - width - 20), top + 20


def main(argv: Optional[list] = None) -> int:
    # `solver.objectives` does not exist -- the presets live in
    # `search.objective`, which is how `advise` imports them.
    from ..search import objective as objectives
    from . import advise as advise_mod

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--objective", default="balanced",
                        help="one of " + ", ".join(sorted(objectives.PRESETS)))
    parser.add_argument("--depth", type=int, default=advise_mod.DEFAULT_DEPTH)
    parser.add_argument("--budget", type=float,
                        default=advise_mod.DEFAULT_BUDGET)
    parser.add_argument("--ignore-checksum", action="store_true")
    parser.add_argument("--no-level-7", action="store_true",
                        help="start with level 7 gags held back; the "
                             "panel can toggle it live")
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

    if args.no_level_7:
        from .. import state as state_mod
        state_mod.ALLOW_LEVEL_7 = False

    global LURE_ICON, MAP_ICON
    from . import ttr_assets

    LURE_ICON = _lure_icon_uri()
    MAP_ICON = _icon_uri(ttr_assets.map_icon)

    objective = objectives.PRESETS[args.objective]
    objective_name = args.objective
    inbox: "queue.Queue" = queue.Queue(maxsize=4)
    worker = Worker(inbox, objective, args.depth, args.budget,
                    args.ignore_checksum)
    state = PanelState()
    state.model.allow_level_7 = not args.no_level_7
    state.model.objective = objective_name
    state.model.budget = args.budget
    worker.objective_name = objective_name
    api = Api(worker, state)

    width, height, left, top = _geometry()
    window = webview.create_window(
        "TTR solver", str(index), js_api=api,
        width=width, height=height, x=left, y=top,
        on_top=True, frameless=True, easy_drag=True,
        background_color="#0d1117", resizable=True,
    )

    state.window = window

    def drain() -> None:
        """Keep `state.model` current, and hand it to the page.

        The page also pulls on a timer, so a dropped push is a late
        frame rather than a stuck panel.
        """
        worker.start()
        while not state.closing:
            try:
                state.model = inbox.get(timeout=0.25)
            except queue.Empty:
                pass
            try:
                window.evaluate_js(
                    f"window.pushModel && window.pushModel({model_json(state.model)})")
            except Exception:                     # window gone
                break
        worker.stop()
        try:
            window.destroy()
        except Exception:
            pass

    threading.Thread(target=drain, daemon=True).start()
    webview.start()
    worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
