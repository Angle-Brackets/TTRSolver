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
# How long the feedback receipt stays up. Shorter than the advice
# it sits under: it is a confirmation of something already done,
# so it must not compete with the move you are about to make.
FEEDBACK_LINGER = 3.5


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
    # THE BOSS FIGHT, when there is one -- see `solver.live.boss`.
    # `boss_kind` is "vp", "cfo", "cj", "ceo" or "" for none;
    # `boss_manual` is what the player picked, "" for "use detection".
    # `cogs_left` is -1 where the fight's size is not confirmed: the
    # count still shows, the total is not invented.
    boss_kind: str = ""
    boss_manual: str = ""
    # Toons in the whole fight, both sides -- see `boss.BossTracker`.
    boss_players: int = 1
    cogs_defeated: int = 0
    cogs_left: int = -1
    # Which engine produced the advice on screen: "rl", "search", or ""
    # for neither. Shown as a badge rather than folded into the advice
    # text, because the advice is the thing being read at a glance and
    # provenance is a property OF it rather than part of it.
    engine: str = ""
    # BOTH ENGINES' ANSWERS, KEPT SIDE BY SIDE, so the badge is a toggle
    # rather than a label: the search takes fifteen seconds on any board
    # with two or more cogs (`advise.DEFAULT_DEPTH`), so it runs in the
    # background regardless of which answer is shown and swapping just
    # reads a value already here.
    #
    # `preferred_engine` is the player's choice and persists across
    # rounds; `engine` is whichever one actually PRODUCED the text on
    # screen right now, which lags the preference until that engine
    # answers.
    rl_gag: str = ""
    rl_track: str = ""
    rl_gag_level: int = 0
    search_gag: str = ""
    search_track: str = ""
    search_gag_level: int = 0
    search_ready: bool = False
    preferred_engine: str = "rl"
    # THE REASONS ARE PER ENGINE, like the gag: they describe a MOVE, and
    # the two engines routinely pick different ones, so a shared pair of
    # fields would show one engine's numbers under the other's advice --
    # seen live as an RL "Grand Piano, 95% acc, kills 2" where the 95 and
    # the 2 actually belonged to the search's unshown Wedding Cake.
    #
    # `incoming` and `survive` stay single: they describe the BOARD,
    # which both engines read identically.
    rl_accuracy: Optional[int] = None
    rl_reason: str = ""
    rl_organic: bool = False
    search_accuracy: Optional[int] = None
    search_reason: str = ""
    search_organic: bool = False
    # THE THIRD ANSWER: `search.playout`, the top moves played to the end
    # of the fight. Same shape as the other two. `playout_note` says why
    # a finished playout has no move ("solo only"), so its row can say
    # so instead of thinking forever.
    playout_gag: str = ""
    playout_track: str = ""
    playout_gag_level: int = 0
    playout_ready: bool = False
    playout_note: str = ""
    # The unite the playouts' move is planned on, as a phrase, or "".
    playout_unite: str = ""
    # ANYTIME: playouts per candidate behind the move shown, and whether
    # refining has stopped. The move can change while this climbs.
    playout_rollouts: int = 0
    playout_done: bool = False
    # Whether a playout is actually running. The row shows "Thinking"
    # only while one is: it used to spin whenever there was no answer,
    # including when the board could not be read and nothing was running.
    playout_pending: bool = False
    playout_accuracy: Optional[int] = None
    playout_reason: str = ""
    playout_organic: bool = False
    # Which answers this panel is computing at all, so a row for an
    # engine that is switched off is not drawn as "thinking".
    engines: List[str] = field(default_factory=lambda: ["rl", "search", "playout"])
    # Whether the DISPLAYED gag's track is organic, and which tracks are.
    # Both come from the Local API rather than the screen: it states
    # organic outright, so nothing has to recognise the sprout on the
    # gag button to know.
    organic: bool = False
    organic_tracks: List[str] = field(default_factory=list)
    # The most pink slips the solver may PLAN with, whatever the toon
    # actually holds; zero (the default) means never advise one. A cap
    # rather than a count, because the game's own `setPinkSlips` count is
    # always right but can't say how many the player is WILLING to
    # spend -- slips cost real money to replace. Needs no tracking
    # across rounds or floors: the game decrements `setPinkSlips` itself
    # and the panel re-reads it every cycle.
    max_fires: int = 0

    # The most UNITES and SOS CARDS to plan with, whatever the toon
    # holds. Zero for the same reason as `max_fires` -- both are farmed
    # from boss runs, so spending one is the player's call -- and zero
    # also happens to be what an unread pouch gives, so the safe default
    # and the unknown case agree.
    max_unites: int = 0
    max_sos: int = 0

    # -- the feedback strip ------------------------------------------
    # What the last round's label recorded, for the receipt under the
    # advice. Source-neutral on purpose: only one front end records
    # today, and the page must not learn which.
    #
    # `feedback_move` is what the player was SEEN to do (read off the
    # pouch, not asked for); `feedback_against` names the engine it
    # departed from; `feedback_problem` is shown INSTEAD when a round
    # wasn't readable. `feedback_fixable` is true only for the most
    # recent row, since the log is append-only and a correction on an
    # older one would silently edit the wrong record.
    feedback_move: str = ""
    feedback_against: str = ""
    feedback_problem: str = ""
    feedback_at: float = 0.0
    feedback_fixable: bool = False
    # Whether a target is MISSING from the row rather than merely
    # unknown to the page -- the one thing the pouch diff cannot see, so
    # the one thing worth asking about.
    feedback_needs_target: bool = False
    # Whether the row on screen was STATED by the player rather
    # than inferred from the pouch. The strip says which, because
    # trusting an inference as though it were a statement is the
    # mistake this whole split exists to prevent.
    feedback_stated: bool = False

    # WHAT THE TOON IS HOLDING, as {track, level, count}, so the page can
    # offer a move the player could actually make -- a full seven-by-
    # seven grid would invite naming a gag not in the pouch, which is a
    # wish rather than a preference, and wouldn't fit a strip this size.
    pouch: List[dict] = field(default_factory=list)
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
    # Reading a building's floors off Discord's pipe: "on", "blocked"
    # (Discord holds it -- the page offers a restart), "restarting", or ""
    # where there is no pipe to read. See `Worker.restart_discord`.
    discord_floors: str = ""
    # How the Playout row treats the pill's teammates: "pickup" (strangers,
    # guessed at) or "coordinated" (a party that plans together). Empty on
    # a panel that stands no teammates in, which hides the toggle.
    party_mode: str = ""
    turn: int = 0

    @property
    def in_battle(self) -> bool:
        if self.forced is not None:
            return self.forced
        return self.detected_battle

    @property
    def feedback_showing(self) -> bool:
        """Whether the receipt is still on screen.

        A DECISION, so it lives here rather than in the page -- the same
        rule `advice_text` follows. It also means the strip cannot
        outlive its row because a browser tab was left open.
        """
        if not (self.feedback_move or self.feedback_problem):
            return False
        return (time.time() - self.feedback_at) < FEEDBACK_LINGER

    @property
    def can_confirm(self) -> bool:
        """May the player assert a battle right now?

        ALWAYS, once the game window is there -- requiring plates or the
        menu first would gate the override on the very thing it exists
        to override, during the poll or two detection takes to settle.
        Not dangerous either way: it sets `forced`, and `build_state`
        still refuses to answer without real readings.
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

        The search otherwise runs only when the battle *changes*, which
        leaves no way to retry common failures -- the gag menu opening
        late, or a cog labelled mid-battle -- that would otherwise sit
        stale until something died. Withheld only while already running,
        or with no battle to search.
        """
        return self.in_battle and not self.thinking

    @property
    def status(self) -> str:
        if self.in_battle:
            where = "confirmed" if self.forced else "detected"
            turn = f", est. turn {self.turn}" if self.turn else ""
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

    # DECISION LOG (`feedback.FeedbackLog`), off unless a path is given:
    # each round, what every row advised beside what the player threw,
    # read off the pouch the menu shows. Source "ttr", so usable by TTR.
    feedback_to = None
    _feedback = None
    _fb_board = None        # the board the latest advice was for
    _fb_pending = None      # last round's board and advice, awaiting its result

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
        thinker = advise_mod.Thinker(self._on_advice,
                                     on_first_answer=self._on_first_answer,
                                     on_playout=self._on_playout)
        # THE MENU'S MEMORY. Counts cannot change while the menu is open,
        # so every poll while it is up votes on each cell, and the read a
        # search uses is resolved against the votes -- the cursor moves,
        # the digit under it does not. See `panel_memory`.
        from .panel_memory import PanelMemory

        memory = PanelMemory()
        thinker.panel_memory = memory
        self._start_relay()
        self._keep_api_fresh()
        try:
            while not self._stop.is_set():
                cycle = time.time()
                # The plates as they stood, for counting defeats below.
                before = list(watcher.view.cogs)
                events = watcher.poll()
                # THE FRAME THE WATCHER JUST GRADED, not a fresh one: a
                # second grab let `menu_visible` and `read_panel` check
                # two captures taken milliseconds apart, and while the
                # menu was mid-slide they'd disagree ("see: gag menu" and
                # "no gag menu" together). One frame, one answer.
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
                if watcher.menu_visible and watcher.view.active:
                    try:
                        snap_now = advise_mod._SESSION.get("snapshot")
                        memory.observe(
                            advise_mod._panel_with_training(frame, snap_now)
                            if snap_now is not None
                            else advise_mod._panel(frame))
                    except Exception:          # noqa: BLE001 -- a vote, not a read
                        pass
                else:
                    memory.reset()             # gags are spent while it is shut
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
                    self._observe_slips(getattr(snap, "pink_slips", None))
                    self._start_relay()
                    self.building = self._building(model.zone)
                    if self.building:
                        model.zone += (f", floor {self.building['floor']}"
                                       f" of {self.building['floors']}")
                model.rows = [_row(r) for r in watcher.view.cogs]
                self._track_boss(model, events, before,
                                 list(watcher.view.cogs))
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
                        self._feedback_round_over()
                    model.turn = turn
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
                                   allies=self.allies_in_battle(),
                                   fires=self.slips_to_plan(),
                                   reject=self._rejected,
                                   boss=self.boss_tracker().frozen(),
                                   unites=self.remaining("unites"),
                                   changed=bool(changed))
                self._post()
                time.sleep(max(0.0, POLL_INTERVAL - (time.time() - cycle)))
        finally:
            watcher.close()
            if self._relay is not None:
                self._relay.stop()

    def _track_boss(self, model, events, before, after) -> None:
        """Name the fight and count what died, from the screen.

        No cog ids here, so a death is a plate that vanished nearly
        empty -- `boss.died_plates` -- and only on a poll the watcher
        itself graded as a cog leaving. The player can correct the
        count; a misread plate cannot argue with them.

        The zone only names a fight once `boss.TTR_BOSS_ZONES` knows its
        string; a zone mid-transition (empty) keeps the current answer.
        """
        from . import boss as boss_mod

        tracker = self.boss_tracker()
        zone = getattr(model, "zone", "") or ""
        detected = boss_mod.boss_from_location(zone) if zone else None
        # THE CLIENT'S LOG names a boss room the API does not (`ttr_log`).
        place = self._place()
        if detected is None and place is not None:
            detected = boss_mod.boss_from_place(*place)
        if zone or place is not None:
            self._observe_boss(detected)
        if any(e.kind in ("cog_defeated", "battle_ended") for e in events):
            tracker.note_defeated(boss_mod.died_plates(before, after))
        # The pill is the whole fight's toon count (`allies_in_battle`).
        tracker.party_size = self.toon_count
        self._boss_into(model, on_field=len(after))

    _places = None
    _relay = None
    _relay_tried = 0.0
    building = None
    # Seconds between attempts on a pipe a running Discord holds.
    RELAY_RETRY = 3.0

    def _start_relay(self) -> None:
        """Sit on Discord's pipe when it is free, to read the building's
        floors the game publishes there (`discord_relay`).

        RETRIED, not tried once: a Discord already running holds the pipe,
        and the player frees it by quitting Discord -- the panel takes it
        in that gap, the game reconnects here within seconds (observed),
        and a Discord restarted after that is handed the game. Meanwhile a
        relay run separately writes the same record to a file, read below.
        """
        if self._relay is not None or time.time() - self._relay_tried < self.RELAY_RETRY:
            return
        self._relay_tried = time.time()
        try:
            from . import discord_relay
        except Exception:                      # noqa: BLE001
            return
        try:
            self._relay = discord_relay.Relay().start()
            self._floors_state("on")
        except discord_relay.PipeTaken:
            self._relay = None
            if self.model.discord_floors != "restarting":
                self._floors_state("blocked")
        except Exception:                      # noqa: BLE001 -- no pipes here
            self._relay = None

    def _keep_api_fresh(self) -> None:
        """Connect to the Local API the moment the panel opens, and keep
        the snapshot fresh from then on.

        It used to connect only when the panel first thought about a move,
        so until the first battle the location read "Local API
        Disconnected" and the slip count was unknown. One request per
        SNAPSHOT_TTL; discovery still runs at most once per
        REDISCOVER_AFTER and only while disconnected, so the consent prompt
        appears once and is not repeated (see `advise._snapshot`).
        """
        import threading
        from . import advise as advise_mod

        def run():
            while not self._stop.is_set():
                try:
                    advise_mod._snapshot()
                except Exception:              # noqa: BLE001 -- retried next tick
                    pass
                self._stop.wait(advise_mod.SNAPSHOT_TTL)
        threading.Thread(target=run, daemon=True).start()

    def _floors_state(self, state: str) -> None:
        """What the page says about reading floors: "on", "blocked" (Discord
        holds the pipe -- offer the restart), "restarting", or ""."""
        if getattr(self.model, "discord_floors", None) != state:
            self.model.discord_floors = state

    def restart_discord(self) -> None:
        """The player's button: put the relay in front of Discord.

        A Discord holding `discord-ipc-0` keeps every new connection, so it
        has to start after the relay. Close it, take the pipe the moment it
        is free (the game reconnects here within seconds -- observed), then
        start Discord again: it settles on `-1` and is handed the game, so
        the player's status comes back. Off the UI thread.
        """
        import threading

        def run():
            from . import discord_relay
            self._floors_state("restarting")
            self._post()
            how = discord_relay.quit_discord()
            deadline = time.time() + 15.0
            while self._relay is None and time.time() < deadline:
                self._relay_tried = 0.0
                self._start_relay()
                time.sleep(0.25)
            discord_relay.start_discord(how)
            self._floors_state("on" if self._relay is not None else "blocked")
            self._post()
        threading.Thread(target=run, daemon=True).start()

    def _building(self, zone: str):
        """{floor, floors, department} while the API says we are in a Cog
        building, from what the game told Discord; else None."""
        try:
            from . import discord_relay
            from .session import BUILDING_ZONES
            if zone not in BUILDING_ZONES:
                return None
            entry = (self._relay.latest() if self._relay is not None
                     else discord_relay.read_presence(max_age=3600))
            return discord_relay.building(entry)
        except Exception:                      # noqa: BLE001
            return None
    _slips_last = None
    observed = ()

    def _observe_slips(self, held) -> None:
        """Tick the slip box down by what REALLY left the toon.

        The Local API states the count (`/pinkslips.json`), so slips are
        observed rather than charged from the advice. A count that rises
        grants nothing.
        """
        if held is None:
            return
        self.observed = ("fires",)
        last, self._slips_last = self._slips_last, int(held)
        if last is not None and held < last:
            self.spend("fires", last - held)

    def slips_to_plan(self) -> int:
        """The box, and never more than the toon actually holds."""
        left = self.remaining("fires")
        if self._slips_last is not None:
            left = min(left, self._slips_last)
        return left

    def _place(self):
        """(where, hoodId) from the client's log, or None. Never raises."""
        try:
            if self._places is None:
                from .ttr_log import PlaceWatcher
                self._places = PlaceWatcher()
            return self._places.place()
        except Exception:                      # noqa: BLE001
            return None

    def _should_retry(self, model, now: float) -> bool:
        """Ask again after a read that produced no state.

        A FAILED READ MUST NOT BE FINAL. Searches run on position
        CHANGES, and the frame at a round boundary is the likeliest to
        be unreadable (gag menu sliding, plates mid-animation) -- with no
        retry, the next `damage` event can't arrive because the player is
        stuck at the gag menu waiting for advice that never comes.

        Gated on `problems` rather than on the absence of advice, since
        the PREVIOUS round's advice is still on screen at that moment.
        Success clears `problems`, so this stops on its own.

        `thinking` IS NOT TRUSTED INDEFINITELY: it's only cleared by a
        search reporting back, and a superseded search never reports, so
        past budget-plus-slack it's treated as stuck rather than blocking
        every retry for the rest of the fight.
        """
        stuck = (self._thinking_since
                 and now - self._thinking_since > self.budget + STUCK_SLACK)
        return bool(model.in_battle
                    and (not model.thinking or stuck)
                    and model.problems
                    and now - self._last_try >= RETRY_INTERVAL)

    def _on_playout(self, state, horizon, is_current) -> None:
        """The board is built: play the top moves out beside the search."""
        from . import advise as advise_mod

        def describe(action, st):
            track = advise_mod.track_of(action)
            level = (action.level if (track and track not in ("fire", "sos"))
                     else (7 if track in ("fire", "sos") else None))
            return advise_mod._render(action, st), track or "", level or 0

        self._start_playout(self._with_teammates(state), horizon, self.budget,
                            is_current, describe)

    # PICKUP unless the player says their party plans together. See
    # `party.assumed_teammates`.
    party_mode = "pickup"

    def _with_teammates(self, state):
        """The board the PLAYOUTS see: the pill's teammates as stand-in
        toons rather than a count, so the playouts know someone else is
        hitting the cogs too. Only the Playout row -- PPO and Search keep
        the count. A solo board is returned as it is."""
        from .. import party as party_mod

        board = party_mod.with_assumed_teammates(state)
        self.group_mode = self.party_mode if board is not state else None
        return board

    def set_party_mode(self, mode) -> None:
        """Strangers ("pickup") or a party that plans together
        ("coordinated")."""
        mode = str(mode or "").lower()
        if mode not in ("pickup", "coordinated"):
            return
        with self._lock:
            self.party_mode = mode
            self.model.party_mode = mode
        self._settings_changed()

    def _feedback_round_over(self) -> None:
        """The round just played: hold its board and advice for the diff."""
        if self.feedback_to and self._fb_board is not None:
            self._fb_pending = {
                "state": self._fb_board, "rl": self._rl_action,
                "search": self._search_action, "playout": self._playout_action,
                "engine": self.model.engine or "",
                "rejected": tuple(sorted(map(repr, self._rejected))),
                "objective": getattr(self, "objective_name", "")}

    def _feedback_observe(self, now_state) -> None:
        """Record last round once a board with a different pouch arrives.

        A board with the SAME pouch is a late answer about last round, not
        the next one, so it leaves the pending round waiting. Never raises.
        """
        pending = self._fb_pending
        if not pending or now_state is None:
            return
        try:
            from . import feedback as feedback_mod
            from .. import data
            from ..state import Action

            before = pending["state"]
            old = dict(getattr(before.toon, "gag_counts", {}) or {})
            new = dict(getattr(now_state.toon, "gag_counts", {}) or {})
            if old == new:
                return
            self._fb_pending = None
            key, why = feedback_mod.spent_gag(old, new)
            observed = None
            if key is not None:
                track, level = key
                try:
                    group = bool(data.gag(track, level).group)
                except Exception:              # noqa: BLE001
                    group = False
                observed = Action(track=track, level=level,
                                  target_index=feedback_mod.infer_target(
                                      before.cogs, now_state.cogs, group))
            if self._feedback is None:
                self._feedback = feedback_mod.FeedbackLog(self.feedback_to, source="ttr")
            self._feedback.append(feedback_mod.Decision(
                source="ttr", round_num=getattr(before, "round_num", 0),
                state=before, rl=pending["rl"], search=pending["search"],
                playout=pending["playout"], observed=observed, unreadable=why,
                engine_shown=pending["engine"], rejected=pending["rejected"],
                objective=pending["objective"]))
        except Exception:                      # noqa: BLE001 -- never cost the advice
            self._fb_pending = None

    def _on_first_answer(self, action, unite_str, state) -> None:
        from . import advise as advise_mod
        self._feedback_observe(state)
        if state is not None:
            self._fb_board = state
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
                    self._advise_unite(model, unite_str)
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
                    self._advise_unite(model, unite_text)

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

    def set_cog_level(self, index, level) -> None:
        """The player reading a plate's level for us, applied at once.

        The reader refuses a level it cannot tell apart from another --
        a clear "Level 6" behind a faint cog head scored 6 at 0.691 over
        8 at 0.679 -- and one refused level blocks the whole board. The
        player can see the plate. Their number overrides the reader for
        this fight (`BattleWatcher.set_level`); "Fight is over" clears it.
        """
        watcher = getattr(self, "_watcher", None)
        if watcher is not None:
            watcher.set_level(index, level)
        try:
            row = self.model.rows[int(index)]
            row.level = int(level) if level not in (None, "", 0) else None
        except (TypeError, ValueError, IndexError):
            pass
        self._post()

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

        `set_forced(None)` ("decide for yourself") isn't enough while the
        readers still see plates, since the battle just re-asserts next
        poll; `False` actually suppresses (`BattleWatcher.in_battle`) and
        releases itself once the plates are gone.

        Everything derived from the old fight goes with it -- a hand-
        named cog, an advice line, a refusal -- or a name lands on the
        wrong cog in the next one.
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
        for engine in ("rl", "search", "playout"):
            self._clear_engine(model, engine)
        model.unite = self._advised_unite = ""
        self._sync_explanation(model)
        model.incoming = model.survive = None
        self._rl_action = self._search_action = self._playout_action = None
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
        self.model.party_mode = self.party_mode
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
    # OFFERED ON EVERY ROW, not only unidentified ones: a confident wrong
    # answer is worse than no answer. The library holds six of
    # thirty-two heads, so an unseen cog can match the nearest one it
    # has (a Number Cruncher read as a Bean Counter, both Cashbots), and
    # hiding the dropdown on identified rows left no way to correct it.
    #
    # EVERY COG is offered, with the likely ones first -- narrowing to
    # the plate's own department is wrong for asking a person, because a
    # misread department hides the very cog on screen (CLAUDE.md:
    # "narrowing to the wrong five cogs is worse than not narrowing at
    # all"). The reader's guess only orders the list; the player decides.
    choices = []
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
    # SNAPPED THE WAY THE SOLVER SNAPS IT: `session.FULL_HEALTH` treats
    # anything at or above the tolerance as untouched, since the bar
    # under-reads by a few percent. Showing the raw fraction instead
    # read as a bug (91% on screen while the solver used full HP).
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
            # A word, not "~": at small sizes the tilde reads as a minus
            # and "turn ~1" was taken for "turn -1".
            text=f"est. turn {model.turn}" if model.turn else "")

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
