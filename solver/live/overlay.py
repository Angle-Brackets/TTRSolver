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

from .worker import AdviceWorker

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

# How long to wait before asking again after a read that produced no
# state. Slow enough not to re-run the gag-menu scan every poll, fast
# enough that a player who has just watched a round resolve gets their
# advice while they are still choosing.
RETRY_INTERVAL = 2.0

# How far past its own budget a search may run before `thinking` stops
# being believed. The child process is given `budget + 15` by
# `Thinker._run`, so this sits outside that: anything later is not a
# slow answer, it is one that will never arrive.
STUCK_SLACK = 25.0


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
    # Absolute hit points, so a view can say "needs 90" rather than
    # drawing a bar. Only set when the LEVEL is known, because that is
    # what `cog_max_hp` needs -- an unread plate leaves both None rather
    # than guessing a maximum.
    hp: Optional[int] = None
    max_hp: Optional[int] = None
    # `<department>-<key>`, matching visualizer/assets/cog-*.png, or None
    # when the plate was not identified to a single cog. The view falls
    # back to the department emblem, which is the honest picture: the
    # reader knows the department and not the cog, and drawing a
    # specific cog would assert more than was read.
    art_key: Optional[str] = None
    department: Optional[str] = None
    # Plate order, which is what a hand-named cog is keyed on. The slot
    # was tried first and is a detected bounding box that moves by a few
    # pixels between frames, so a name keyed on it matched once and never
    # again.
    index: Optional[int] = None
    # Asleep on a Lure. Marked by the player, not read from the plate.
    lured: bool = False
    # Trapped by a Trap gag. Marked by the player or read from state.
    trapped: bool = False
    # What this plate could be, given its department and level. Offered
    # in the panel when the readers cannot name it: at most five, often
    # fewer, and the player can simply see which one it is.
    choices: List[dict] = field(default_factory=list)
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
    # Whether level 7 gags are being offered. Mirrors
    # `state.ALLOW_LEVEL_7` so the panel can show and toggle it: a player
    # saving their 7s for a boss wants advice that does not spend them.
    allow_level_7: bool = True
    # The live controls. Mirrored from the Worker, which owns them, so
    # the buttons show what the solver is doing rather than what the page
    # last asked for.
    objective: str = "balanced"
    budget: float = 15.0
    # How many toons are in this fight, 1-4, INCLUDING you. Changes the
    # cog phase: a single-target attack has three other places to land
    # in a full group, so the same cog is far less dangerous to you --
    # see `BattleState.allies_standing`. Group attacks are unaffected,
    # which is why a Big Wig stays nearly as bad in a four-toon fight
    # as it is solo.
    toon_count: int = 1
    # Which engine produced the advice on screen: "rl", "search", or ""
    # for neither. Shown as a badge rather than folded into the advice
    # text, because the advice is the thing being read at a glance and
    # provenance is a property OF it rather than part of it.
    engine: str = ""
    # BOTH ENGINES' ANSWERS, KEPT SIDE BY SIDE, so the badge can be a
    # toggle instead of a label. The search takes fifteen seconds on any
    # board with two or more cogs (see `advise.DEFAULT_DEPTH`), so a
    # player who swaps to it after the fact would otherwise pay that
    # cost mid-fight. It runs in the background regardless of which
    # answer is on screen; swapping then reads a value that is already
    # here.
    #
    # `preferred_engine` is the player's choice and persists across
    # rounds. `engine` stays what actually PRODUCED the text currently
    # displayed, which is not always the preference -- the search may
    # not have finished yet, and on the first round of a fight it never
    # has.
    rl_gag: str = ""
    rl_track: str = ""
    rl_gag_level: int = 0
    search_gag: str = ""
    search_track: str = ""
    search_gag_level: int = 0
    search_ready: bool = False
    preferred_engine: str = "rl"
    # THE REASONS ARE PER ENGINE, for the same reason the gag is. They
    # describe a MOVE, and the two engines routinely pick different
    # ones -- so a single pair of fields shows one engine's numbers
    # under the other engine's advice. That is not hypothetical: with
    # the RL badge on, a live board read "Grand Piano on cog 1 -- 95%
    # acc, kills 2" while the piano was 70% and killed one. The 95 and
    # the 2 belonged to a group Wedding Cake the search had picked and
    # the page never displayed.
    #
    # `incoming` and `survive` stay single because they describe the
    # BOARD, which both engines read identically.
    rl_accuracy: Optional[int] = None
    rl_reason: str = ""
    rl_organic: bool = False
    search_accuracy: Optional[int] = None
    search_reason: str = ""
    search_organic: bool = False
    # Whether the DISPLAYED gag's track is organic, and which tracks are.
    # Both come from the Local API rather than the screen: it states
    # organic outright, so nothing has to recognise the sprout on the
    # gag button to know.
    organic: bool = False
    organic_tracks: List[str] = field(default_factory=list)
    # The most pink slips the solver may PLAN with, whatever the toon
    # actually holds. Zero -- the default -- means never advise a fire.
    #
    # A cap rather than a count, because the count is read from the game
    # (`setPinkSlips`) and is always right. What it cannot know is how
    # many the player is WILLING to spend, and slips are the one
    # resource here that costs real money to replace.
    #
    # It also needs no tracking across rounds or floors, which is the
    # trap it looks like it should fall into. The game decrements
    # `setPinkSlips` when one is fired and the panel re-reads it every
    # cycle, so "how many are left" is always the live value. There is
    # no used-count to maintain and nothing to reset when a VP moves to
    # its second wave or a building to its next floor.
    max_fires: int = 0

    # The most UNITES and SOS CARDS the solver may plan with, whatever
    # the toon holds. Zero like `max_fires`, and for the same reason:
    # both are farmed from boss runs, so spending one is the player's
    # call rather than the solver's. A cap of zero means never advise
    # one, which is also what an unread pouch gives -- so the safe
    # default and the unknown case agree.
    max_unites: int = 0
    max_sos: int = 0
    # WHAT IS LEFT, after the advice already given this fight. The
    # `max_*` above are what the player says they carry; these are what
    # the solver is actually planning with, so the page can show
    # "2 of 5" and a spent resource visibly runs down.
    fires_left: int = 0
    unites_left: int = 0
    sos_left: int = 0

    # The unite the panel is advising ALONGSIDE the gag, as a phrase
    # ("80 Toon-Up unite"), or "" for none.
    #
    # A separate field rather than part of the advice, because a unite
    # is not the move. It costs no action, so the round is "use this,
    # THEN throw that" -- two things, and folding them into one line
    # would read as a choice between them. An SOS is the opposite: it
    # costs the turn, so it IS the move and goes in `gag` like any gag.
    unite: str = ""

    # WHY, not just what. The solver computes all of these on every
    # score and the panel used to discard them, so the advice arrived
    # as an instruction with no argument attached.
    #
    # `incoming` and `survive` describe the BOARD -- expected damage
    # this round, and how many rounds the party's laff covers, capped
    # at 4. The rest describe the recommended move. All are optional:
    # an explanation that cannot be computed must never cost you the
    # advice it was explaining, so they stay at their defaults.
    incoming: Optional[float] = None
    survive: Optional[float] = None
    accuracy: Optional[int] = None
    reason: str = ""
    # Where the toon is, from the Local API. The solver does not use it
    # -- a street does not change a round -- but it tells the player at a
    # glance whether the panel is talking to the game at all, which the
    # cog readers cannot: they work off pixels and would look identical
    # with the API disconnected.
    zone: str = ""
    neighborhood: str = ""
    district: str = ""
    invasion: str = ""
    turn: int = 0

    @property
    def in_battle(self) -> bool:
        if self.forced is not None:
            return self.forced
        return self.detected_battle

    @property
    def can_confirm(self) -> bool:
        """May the player assert a battle right now?

        ALWAYS, once the game window is there. This used to require
        plates or the menu already visible, which gated the override on
        the very thing it exists to override: detection takes a poll or
        two to settle, and during exactly that window the button was
        greyed out.

        Asserting a fight that is not happening is not dangerous. It sets
        `forced`, and `build_state` still refuses without readings -- so
        the panel says what it cannot see rather than inventing advice.
        The old worry, that a forced battle would be answered from
        whatever the readers last saw, is handled there rather than here.
        """
        if self.in_battle:
            return True             # always allowed to say it is over
        return self.window_found

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


class Worker(AdviceWorker):
    """Runs the eye and the solver, and posts Models to the UI.

    The screen half. Everything about WHICH answer is shown, what a
    rejection means and how a setting reaches the search lives in
    `AdviceWorker`; what is here is the part that has to look at
    pixels -- and the player overrides for what pixels cannot say.
    """

    def __init__(self, outbox: "queue.Queue", objective, depth: int,
                 budget: float, ignore_checksum: bool = False):
        # `model` FIRST: the base sets `allow_level_7` and the holdings
        # onto it, so it has to exist before that runs.
        self.model = Model()
        super().__init__(outbox, objective, depth, budget)
        self.ignore_checksum = ignore_checksum
        # The player's "I am / am not in a fight", which only a panel
        # reading a SCREEN needs -- a client that is told the battle
        # has nothing to override.
        self._forced: Optional[bool] = None
        # When the last search was launched, for the failed-read retry,
        # and when `thinking` was last raised, so a flag that never
        # comes down cannot block every retry after it.
        self._last_try = 0.0
        self._thinking_since = 0.0
        self.turns = TurnCounter()

    # -- called from the UI thread --------------------------------------

    def set_forced(self, value: Optional[bool]) -> None:
        with self._lock:
            self._forced = value

    def forced(self) -> Optional[bool]:
        with self._lock:
            return self._forced

    def run(self) -> None:
        from . import advise as advise_mod
        from .gagpanel import find_panel
        from .watch import BattleWatcher
        from .window import game_rect

        watcher = BattleWatcher(battle_over=advise_mod._paid_out,
                                force_battle=self.forced)
        # Held so `name_cog` can reach it: the panel names a plate
        # the readers could not, and the watcher applies it per frame.
        self._watcher = watcher
        thinker = advise_mod.Thinker(self._on_advice, on_first_answer=self._on_first_answer)
        try:
            while not self._stop.is_set():
                cycle = time.time()
                events = watcher.poll()
                # THE FRAME THE WATCHER JUST GRADED, not a fresh one.
                # Grabbing again here meant `menu_visible` and
                # `read_panel` ran the same `find_panel` check on two
                # different captures taken milliseconds apart, and the
                # menu is mid-slide for several of those. The panel
                # reported "see: gag menu" and "no gag menu on screen"
                # together, which reads as the tool contradicting
                # itself. One frame, one answer -- and one screen grab
                # per poll instead of two.
                frame = watcher.last_frame
                if frame is None:               # nothing polled yet
                    frame = watcher.capture.grab()
                model = self.model
                model.window_found = game_rect() is not None
                model.plates = len(watcher.view.cogs)
                # RELEASE THE SUPPRESSION once the screen agrees. "Fight
                # is over" sets forced False so detection stops arguing
                # while the plates are still up; holding it there would
                # mean the next fight is never noticed.
                if self.forced() is False and not watcher.view.cogs:
                    self.set_forced(None)
                # From the watcher, which computed it this poll for its
                # own read gate. Calling `find_panel` again here doubled
                # the most expensive scan in the loop.
                model.menu_visible = watcher.menu_visible
                model.detected_battle = watcher.view.active
                model.forced = self.forced()
                model.cogs = [_describe_reading(r) for r in watcher.view.cogs]
                # Where the toon is, from the cached Local API session.
                # `advise._snapshot` is already polled for laff and gag
                # training and holds the answer for SNAPSHOT_TTL, so this
                # costs nothing -- and NEVER calls `discover()`, which
                # pops the game's consent dialog once per client built.
                snap = advise_mod._SESSION.get("snapshot")
                if snap is not None:
                    model.zone = getattr(snap, "zone", "") or ""
                    model.neighborhood = getattr(snap, "neighborhood", "") or ""
                    model.district = getattr(snap, "district", "") or ""
                    invasion = getattr(snap, "invasion", None)
                    # `invasion_text`, not `str()`: the field is a
                    # (cog, count, mega) tuple and `str()` put a raw
                    # Python repr on screen over a live battle.
                    model.invasion = getattr(
                        snap, "invasion_text", "") or ""
                model.rows = [_row(r) for r in watcher.view.cogs]
                turn = self.turns.observe(model.in_battle,
                                          model.menu_visible)
                if turn != model.turn:
                    # A NEW ROUND, so whatever was on screen for the last
                    # one has been played. Charged here rather than when
                    # the advice is produced, because the same move is
                    # re-scored several times while the player reads it.
                    if model.turn:
                        self.note_spent(self.displayed_action(),
                                        model.unite or None)
                    model.turn = turn
                if not model.in_battle:
                    self.reset_spending()
                model.fires_left = self.remaining("fires")
                model.unites_left = self.remaining("unites")
                model.sos_left = self.remaining("sos")
                asked = self._asked.is_set()
                if asked:
                    self._asked.clear()
                retry = self._should_retry(model, cycle)
                changed = any(e.kind in advise_mod.RECOMPUTE_ON
                              for e in events)
                if changed:
                    # A REJECTION IS ABOUT THIS POSITION. `reject_key` is
                    # (track, group), so "no, not that" turns down a whole
                    # kind of move -- which is the point, and is why it
                    # must not outlive the board it was said about.
                    # Kept across `asked`, because the player pressing
                    # Reconsider again means "still no", not "start over".
                    self._rejected.clear()
                if asked or retry or changed:
                    self._last_try = cycle
                    if not model.thinking:
                        self._thinking_since = cycle
                    model.thinking = True
                    thinker.submit(frame, list(watcher.view.cogs), None,
                                   self.objective, self.depth, self.budget,
                                   self.ignore_checksum,
                                   allies=max(0, self.toon_count - 1),
                                   fires=self.remaining("fires"),
                                   reject=self._rejected)
                self._post()
                time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))
        finally:
            watcher.close()

    def _should_retry(self, model, now: float) -> bool:
        """Ask again after a read that produced no state.

        A FAILED READ MUST NOT BE FINAL. Searches run on position
        CHANGES, and the frame grabbed at a round boundary is the
        likeliest one to be unreadable -- the gag menu is sliding, the
        plates are behind an attack animation. That read failed, posted
        its reasons, and then NOTHING ASKED AGAIN: the next `damage`
        event cannot arrive, because the player is sitting at the gag
        menu waiting for the advice that never came. The panel looked
        like it had given up mid-fight, and it had.

        Gated on `problems` rather than on the absence of advice,
        because the PREVIOUS round's advice is still on screen at that
        moment -- so "no answer yet" is not what the failure looks
        like. Success clears `problems`, so this stops on its own.

        `thinking` IS NOT TRUSTED INDEFINITELY. It is only ever cleared
        by a search reporting back, and a search that is superseded
        never reports -- so a flag stuck on would block every retry for
        the rest of the fight and freeze the panel on a stale problem
        while the readers were, by then, seeing the board perfectly
        well. Past the budget plus slack it is treated as gone.
        """
        stuck = (self._thinking_since
                 and now - self._thinking_since > self.budget + STUCK_SLACK)
        return bool(model.in_battle
                    and (not model.thinking or stuck)
                    and model.problems
                    and now - self._last_try >= RETRY_INTERVAL)

    def _on_first_answer(self, action, unite_str, state) -> None:
        from . import advise as advise_mod
        model = self.model
        if action is not None:
            text = advise_mod._render(action, state)
            track = advise_mod.track_of(action)
            level = action.level if (track and track not in ("fire", "sos")) else (7 if track in ("fire", "sos") else None)
            with self._lock:
                self._rl_action = action
                model.rl_gag = text
                model.rl_track = track or ""
                model.rl_gag_level = level or 0
                if unite_str:
                    model.unite = unite_str
                if model.preferred_engine == "rl" or not model.search_ready:
                    model.gag = text
                    model.gag_at = time.time()
                    model.track = track
                    model.gag_level = level
                    model.engine = "rl"
                # THE RL PATH EXPLAINS ITSELF TOO. This ran only in
                # `_on_advice` and so only ever described the SEARCH's
                # move, which the panel then printed under whichever
                # move was actually on screen.
                self._describe_into(model, state, action, "rl")
                self._sync_explanation(model)
                if model.preferred_engine == "rl":
                    model.thinking = False
            self._post()

    def _on_advice(self, lines, state, action=None, unite=None) -> None:
        from . import advise as advise_mod
        from .. import unites as unites_mod

        model = self.model
        with self._lock:
            model.thinking = False
            if state is None:
                model.problems = list(lines)
            else:
                model.problems = []
                if lines:
                    # EVERYTHING THAT CAN RAISE HAPPENS FIRST, before a
                    # single field is written. The label used to be
                    # assigned here and the reason eleven statements
                    # later, with the unite tables called in between --
                    # so anything raising in the middle left the new gag
                    # on screen under the OLD move's numbers. See
                    # `Worker._clear_engine`.
                    try:
                        text = lines[0]
                        track = advise_mod.track_of(action)
                        level = (action.level
                                 if (track and track not in ("fire", "sos"))
                                 else (7 if track in ("fire", "sos") else None))
                        # `unite` comes back FROM THE SEARCH rather than
                        # off a module global: `search_in_child` runs in
                        # another process, so the `LAST_UNITE` it set was
                        # set in that process and this one never saw it.
                        chosen = unite or getattr(advise_mod, "LAST_UNITE", None)
                        unite_text = ("" if chosen is None
                                      else unites_mod.describe(chosen))
                    except Exception:              # noqa: BLE001
                        # Half an answer is worse than none: drop the
                        # whole row rather than pair a fresh label with
                        # a stale explanation.
                        self._clear_engine(model, "search")
                        self._sync_explanation(model)
                        self._post()
                        return

                    self._search_action = action
                    model.search_gag = text
                    model.search_track = track or ""
                    model.search_gag_level = level or 0
                    model.search_ready = True
                    # CLEARED WHEN THERE IS NONE, not only set when
                    # there is. Assigning only on the `is not None` side
                    # left the previous round's unite on screen beside a
                    # move that does not use one.
                    model.unite = unite_text

                    # The reasons behind the move, read off the same
                    # functions the scorer used rather than re-derived.
                    self._describe_into(model, state, action, "search")

                    if model.preferred_engine == "search" or not model.rl_gag:
                        model.gag = text
                        model.gag_at = time.time()
                        model.track = track
                        model.gag_level = level
                        model.engine = "search"
                    self._sync_explanation(model)
        self._post()

    def mark_lured(self, index, lured) -> None:
        """The player says this cog is asleep on a Lure."""
        watcher = getattr(self, "_watcher", None)
        if watcher is not None:
            watcher.mark_lured(index, bool(lured))

    def mark_trapped(self, index, trapped) -> None:
        """The player says this cog is trapped with a Trap gag."""
        try:
            row = self.model.rows[int(index)]
            row.trapped = bool(trapped)
        except (TypeError, ValueError, IndexError):
            pass

    def name_cog(self, index, cog) -> None:
        """The player naming a plate, applied at once.

        PAINTED IMMEDIATELY rather than waiting for the watcher's next
        frame. Until it lands the row looks untouched, which is
        indistinguishable from the click having been lost -- and that
        ambiguity cost several rounds of debugging. Showing it now means
        a pick that arrives is visible instantly, so a pick that does not
        is a real bug rather than a guess.
        """
        from .. import data

        watcher = getattr(self, "_watcher", None)
        if watcher is not None:
            watcher.name_plate(index, cog or None)
        try:
            row = self.model.rows[int(index)]
        except (TypeError, ValueError, IndexError):
            return
        if cog:
            try:
                entry = data.cog(data.department_of(cog), cog)
            except (KeyError, ValueError):
                return
            row.name = entry.display
            row.identified = True
            row.art_key = f"{entry.department}-{entry.key}"
            for choice in row.choices:
                choice["current"] = choice["key"] == cog
        self._post()

    def end_fight(self) -> None:
        """The player says the fight is over. Wipe it and stop advising.

        `set_forced(None)` was not enough: None means "decide for
        yourself", and the readers still see plates on screen, so the
        battle re-asserted on the very next poll and the button did
        nothing. False actually suppresses -- see
        `BattleWatcher.in_battle`, where `forced is False` returns early.
        It is released automatically once the plates are gone, so the
        next fight is detected normally rather than staying suppressed.

        Everything derived from the old fight goes with it. A cog named
        by hand, an advice line, a refusal -- all describe a battle that
        has ended, and carrying any of it into the next one is how a name
        lands on the wrong cog.
        """
        self.set_forced(False)
        watcher = getattr(self, "_watcher", None)
        if watcher is not None:
            watcher._forget_names(-1)
        model = self.model
        # BOTH copies of the flag. `Worker._forced` is what the watcher
        # consults; `Model.forced` is what `Model.in_battle` reads. Setting
        # only the first left the panel still saying IN BATTLE.
        model.forced = False
        model.detected_battle = False
        model.plates = 0
        model.gag, model.gag_at, model.track = None, 0.0, None
        model.gag_level = None
        # BOTH ENGINES' ROWS TOO. Clearing only the displayed advice left
        # `rl_gag` / `search_gag` and their reasons behind, so the
        # runner-up row carried the last fight's move into the next one
        # -- the one place the panel shows a gag without the staleness
        # dimming that `problems` drives.
        for engine in ("rl", "search"):
            self._clear_engine(model, engine)
        model.unite = ""
        self._sync_explanation(model)
        model.incoming = model.survive = None
        self._rl_action = self._search_action = None
        model.problems, model.rows, model.cogs = [], [], []
        model.turn = 0
        model.thinking = False
        self._post()

    def _post(self) -> None:
        # A shallow copy per post: the UI must never read a Model that
        # the worker is halfway through updating.
        from copy import copy

        self.model.allow_level_7 = self.allow_level_7
        self.model.objective = self.objective_name
        self.model.budget = self.budget
        self.model.toon_count = self.toon_count
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
    # OFFERED ON EVERY ROW, not only unidentified ones. A confident
    # wrong answer is worse than no answer: the library holds six of
    # thirty-two heads, so a cog it has never seen can match the nearest
    # one it has -- a Number Cruncher read as a Bean Counter, both
    # Cashbots. With the dropdown hidden on identified rows there was no
    # way to say otherwise, and the solver planned the whole fight
    # against the wrong cog's attacks.
    choices = []
    if True:
        # EVERY COG, with the likely ones first. Narrowing to the pool the
        # plate allows is right for automatic matching and wrong for
        # asking a person: the department read can be wrong, and then the
        # cog actually on screen is the one option never offered. That is
        # the failure CLAUDE.md warns about -- "narrowing to the wrong
        # five cogs is worse than not narrowing at all" -- and it showed
        # up immediately: a plate misread as Cashbot could not be named
        # Head Hunter, which is a Bossbot.
        #
        # The player can see the cog. The reader's guess orders the list;
        # it does not limit it.
        from .catalogue import candidates

        likely = list(candidates(reading.department, reading.level))
        if reading.cog and reading.cog not in likely:
            likely.insert(0, reading.cog)
        rank = {key: i for i, key in enumerate(likely)}
        every = [c.key for dept in data.COG_DEPARTMENTS.values()
                 for c in dept.cogs]
        for key in sorted(every, key=lambda k: (rank.get(k, len(rank)), k)):
            try:
                entry = data.cog(data.department_of(key), key)
                choices.append({"key": key, "display": entry.display,
                                "likely": key in rank,
                                "current": key == reading.cog,
                                "department": entry.department})
            except (KeyError, ValueError):        # pragma: no cover
                continue
    # SNAPPED THE WAY THE SOLVER SNAPS IT. `session.FULL_HEALTH` treats
    # anything at or above the tolerance as untouched, because the bar
    # under-reads by a few percent and the shortfall scales with how
    # large the plate is. Showing the raw fraction meant the panel said
    # 91% while the solver was correctly using full HP, which reads as a
    # bug and prompted exactly that report.
    from .session import FULL_HEALTH

    shown = max(0.0, min(1.0, float(reading.health)))
    if shown >= FULL_HEALTH:
        shown = 1.0
    # Absolute HP, from the level and the snapped fraction. Only when
    # the level was read: `cog_max_hp` needs it, and an unread plate
    # gets None rather than a guessed maximum.
    hp = max_hp = None
    if reading.level is not None:
        try:
            max_hp = int(data.cog_max_hp(reading.level))
            hp = max(0, min(max_hp, int(round(shown * max_hp))))
        except (KeyError, ValueError, TypeError):
            hp = max_hp = None
    return CogRow(name=name, level=reading.level,
                  health=shown, hp=hp, max_hp=max_hp,
                  identified=identified, art_key=art_key,
                  department=reading.department,
                  index=getattr(reading, "index", None), choices=choices,
                  lured=bool(getattr(reading, "lured", False)))


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
