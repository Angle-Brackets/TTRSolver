"""What the player actually did, recorded beside what was advised.

The panel proposes a move every round; when the player does something
else, that disagreement is a LABEL worth keeping rather than discarding.

The move is OBSERVED, never asked: `setInventory` is parsed every poll
already, and a thrown gag decrements exactly one cell by one (pink
slips, SOS cards and unites move the same way in their own dicts).
Asking would be slower, interrupt a fight, and be wrong whenever the
player misremembers -- this module's value is that its labels aren't
guesses.

A round it cannot read cleanly is recorded as unreadable, with the
reason, rather than guessed at: a wrong label is worse than a missing
one, and worse again here because these rows are training data nothing
downstream will re-derive. For the same reason, a target is left `None`
whenever the inventory diff doesn't pin it to a single cog.

**`source` is a QUARANTINE FLAG, not a label.** Realms is Toontown
Online lineage and nothing read from it may train a TTR policy, fit a
weight, or score one -- see the repo's CLAUDE.md. Stamped at write time
rather than inferred later, since a renamed or merged file is exactly
how that rule breaks irreversibly.

These are ONE PLAYER'S PREFERENCES, not measurement. Solo positions
already have exact labels from `expectimax.solve`; the rows worth
having are where the exact search can't reach -- party boards,
multi-round Lure, the facility horizon. `Decision.beats` reports the
comparison, not who is right.
"""
from __future__ import annotations

import os
import pickle
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = 1

# Why a round produced no observed action. Recorded verbatim so a gap in
# the data can be counted and explained rather than merely noticed.
UNREADABLE_RESTOCK = "a count went up: restocked mid-round, deltas are meaningless"
UNREADABLE_MULTIPLE = "more than one gag left the pouch"
UNREADABLE_JUMP = "a count fell by more than one"
UNREADABLE_NOTHING = "nothing left the pouch"
UNREADABLE_NO_BEFORE = "no previous inventory to compare against"


def spent_gag(before: Optional[Dict], after: Optional[Dict]
              ) -> Tuple[Optional[Tuple], Optional[str]]:
    """The one `(track, level)` that left the pouch, or a reason it is
    not readable.

    Returns `(key, None)` or `(None, reason)` -- never both, and never
    neither.

    A gag absent from a dict is a count of zero rather than missing
    data: `parse_inventory` omits empty cells, so the last one of a gag
    being thrown looks like a KEY disappearing rather than a value
    reaching 0.
    """
    if before is None or after is None:
        return None, UNREADABLE_NO_BEFORE

    down: List[Tuple] = []
    for key in set(before) | set(after):
        delta = int(after.get(key, 0)) - int(before.get(key, 0))
        if delta > 0:
            # A RESTOCK POISONS THE WHOLE ROUND, not just this cell: a
            # Gag-Up refills several at once and can mask a throw by
            # refilling the very gag that was spent. There is no reading
            # of the round left, so nothing is reported for it.
            return None, UNREADABLE_RESTOCK
        if delta == -1:
            down.append(key)
        elif delta < -1:
            return None, UNREADABLE_JUMP

    if not down:
        return None, UNREADABLE_NOTHING
    if len(down) > 1:
        return None, UNREADABLE_MULTIPLE
    return down[0], None


def spent_count(before: Optional[Dict], after: Optional[Dict],
                ) -> Tuple[Optional[str], Optional[int]]:
    """The one named thing that left a count-keyed holding (SOS cards),
    and how many. `(None, None)` when it does not read cleanly."""
    if before is None or after is None:
        return None, None
    down = []
    for key in set(before) | set(after):
        delta = int(after.get(key, 0)) - int(before.get(key, 0))
        if delta > 0:
            return None, None
        if delta < 0:
            down.append((key, -delta))
    if len(down) != 1:
        return None, None
    return down[0]


def infer_target(before_cogs, after_cogs, group: bool) -> Optional[int]:
    """Which cog was aimed at, or None when the board does not say.

    A group gag has no single target and returns None by definition, not
    by failure. For a single-target gag, exactly one cog losing hp pins
    it -- and nothing else does. A cog dying to a trap it was lured onto
    in the same round moves hp without being the target, which is
    precisely why "the only one that changed" is required rather than
    "the one that changed most".
    """
    if group or before_cogs is None or after_cogs is None:
        return None
    if len(before_cogs) != len(after_cogs):
        return None
    moved = [i for i, (b, a) in enumerate(zip(before_cogs, after_cogs))
             if _hp(b) != _hp(a)]
    return moved[0] if len(moved) == 1 else None


def _hp(cog) -> int:
    try:
        return int(getattr(cog, "hp", 0))
    except (TypeError, ValueError):
        return 0


@dataclass
class Decision:
    """One round: what was advised, what was done, what followed."""

    source: str                         # "realms" | "ttr" -- see module docs
    schema: int = SCHEMA
    at: float = field(default_factory=time.time)
    session: str = ""
    round_num: int = 0
    rid: str = ""                       # this row's id, within the session

    # A CORRECTION IS A NEW ROW, not an edit. The log is append-only and
    # is deliberately opened per write, so rewriting the tail would mean
    # holding a handle and losing the session's end whenever the window
    # is killed. Appending keeps the original too, which is the honest
    # record: "the reader said X and the player said no" is itself worth
    # knowing when judging how often the reader is right.
    corrects: str = ""                  # rid this row amends
    discard: bool = False               # the amended row was wrong outright

    state: Any = None                   # the BattleState, pickled whole
    rl: Any = None                      # the policy's Action
    search: Any = None                  # the search's Action
    playout: Any = None                 # the playouts' Action (newer rows only)
    observed: Any = None                # what the player actually spent
    unreadable: Optional[str] = None    # why `observed` is None

    # WHAT THE PLAYER SAYS THEY WOULD USE -- NOT the same fact as what
    # they were seen to do, and must never collapse into it. Covers cases
    # where the observed move is a poor label (a misclick, an unreadable
    # round) and reaches moves that were never thrown at all. Stated, so
    # it outranks the inferred one in `beats`.
    preferred: Any = None

    engine_shown: str = ""
    rejected: Tuple = ()                # Reconsider keys pressed this board
    objective: str = ""
    policy_id: str = ""
    outcome: Optional[Dict] = None      # filled in once the round resolves

    def beats(self) -> Dict[str, Optional[bool]]:
        """Whether the player's move differed from each engine's.

        None where the comparison cannot be made -- an engine that did
        not answer, or a round whose action was not readable. A missing
        comparison and a tie are different facts and must not collapse.
        """
        out: Dict[str, Optional[bool]] = {}
        mine = self.player_move()
        for name in ("rl", "search"):
            proposed = getattr(self, name)
            if mine is None or proposed is None:
                out[name] = None
            else:
                out[name] = not _same_move(mine, proposed)
        return out

    def player_move(self):
        """The player's move, stated if they stated one.

        An explicit "I'd use this" outranks the pouch diff on purpose:
        the diff reports what happened, which is only evidence of what
        they wanted. Where both exist they are both kept -- whether a
        player does what they say is itself worth being able to count.
        """
        return self.preferred if self.preferred is not None else self.observed

    def stated(self) -> bool:
        """Whether a human said this, rather than it being inferred."""
        return self.preferred is not None

    def informative(self) -> bool:
        """Whether this row carries a preference at all.

        A round where both engines proposed what the player then did is
        agreement, which is worth recording but is not a comparison.
        """
        return any(v for v in self.beats().values())


def _same_move(a, b) -> bool:
    """Same gag, ignoring the target.

    The target is compared only when BOTH are known: `observed` usually
    has none (see `infer_target`), and treating unknown-versus-cog-2 as
    a disagreement would label every readable round a disagreement.
    """
    for attr in ("track", "level", "fire", "sos"):
        if getattr(a, attr, None) != getattr(b, attr, None):
            return False
    at, bt = getattr(a, "target_index", None), getattr(b, "target_index", None)
    if at is not None and bt is not None and at != bt:
        return False
    return True


# -- watching, as opposed to being told -----------------------------
#
# A DEMONSTRATION, not a preference. The feedback log above answers
# "which of these was better"; this answers "what does this player
# actually do", over a whole fight, whether or not anything was
# advised. Different question, different shape -- a trajectory with
# episode boundaries rather than independent rows -- but the SAME
# reading machinery, because two implementations of "what left the
# pouch" would drift and one of them would be wrong silently.
#
# The terminal round is the point of recording episodes at all: whether
# a VP run was won or lost is carried entirely by its last transition,
# and per-round rows throw exactly that away.


@dataclass
class Step:
    """One round of a watched fight."""

    round_num: int = 0
    state: Any = None                   # the board BEFORE the action
    action: Any = None                  # what the player spent, or None
    unreadable: Optional[str] = None    # why `action` is None
    laff: Tuple = ()                    # each toon's laff, before
    hp: Tuple = ()                      # each cog's hp, before
    at: float = field(default_factory=time.time)


@dataclass
class Episode:
    """One fight, start to finish."""

    source: str
    session: str = ""
    schema: int = SCHEMA
    kind: str = "street"                # street / building / vp / ...
    started: float = field(default_factory=time.time)
    ended: float = 0.0
    outcome: str = "unknown"            # won / lost / unknown
    steps: List[Step] = field(default_factory=list)
    final: Any = None                   # the last board seen

    def rounds(self) -> int:
        return len(self.steps)

    def readable(self) -> int:
        return sum(1 for s in self.steps if s.action is not None)


# An episode that ended without the board ever resolving -- the window
# was closed, the client dropped, the player walked away mid-fight.
# Recorded as its own outcome rather than folded into "lost", because a
# fight nobody finished is not a fight that was lost and training on it
# as one teaches the wrong lesson about the position.
ABANDONED = "unknown"


def outcome_of(state) -> str:
    """Won, lost, or not yet decided, from the last board seen.

    Deliberately narrow. `is_win` and `is_terminal` are the state's own
    predicates and are not re-implemented here -- the panel has been
    burnt before by a second opinion about a rule.
    """
    if state is None:
        return ABANDONED
    try:
        if state.is_win():
            return "won"
        if not state.active_toons():
            return "lost"
    except Exception:                          # noqa: BLE001
        return ABANDONED
    return ABANDONED


class WatchLog:
    """Append-only pickle stream of `Episode`s, one per fight.

    Written when a fight ENDS rather than per round, because an episode
    is only worth anything whole: a trajectory missing its last
    transition cannot say whether the run was won.

    The cost of that choice is a fight lost if the window dies mid-run,
    which is the right trade here -- a VP is twenty minutes and a
    half-recorded one teaches less than nothing.
    """

    def __init__(self, path: str, source: str, session: str = "") -> None:
        if not source:
            raise ValueError("a watch record needs a source; see module docs")
        self.path = path
        self.source = source
        self.session = session or ("%x" % int(time.time() * 1000))
        self.written = 0
        self.skipped = 0

    def append(self, episode: Episode) -> bool:
        """Write one finished fight. False if it was not worth keeping."""
        if not episode.steps:
            self.skipped += 1
            return False
        episode.source = self.source
        episode.session = self.session
        if not episode.ended:
            episode.ended = time.time()
        try:
            with open(self.path, "ab") as handle:
                pickle.dump(episode, handle, protocol=4)
        except OSError:
            return False
        self.written += 1
        return True


def read_episodes(path: str) -> List[Episode]:
    """Every finished fight in a watch log, oldest first."""
    out: List[Episode] = []
    if not os.path.exists(path):
        return out
    with open(path, "rb") as handle:
        while True:
            try:
                out.append(pickle.load(handle))
            except EOFError:
                break
    return out


def summarise_episodes(episodes: List[Episode]) -> Dict[str, Any]:
    """What a watch log holds, for deciding whether it is worth fitting.

    `readable` against `rounds` is the number to watch: a run whose
    rounds mostly could not be read is a collection problem, and it
    should look like one rather than like thin data.
    """
    rounds = sum(e.rounds() for e in episodes)
    readable = sum(e.readable() for e in episodes)
    outcomes: Dict[str, int] = {}
    kinds: Dict[str, int] = {}
    for ep in episodes:
        outcomes[ep.outcome] = outcomes.get(ep.outcome, 0) + 1
        kinds[ep.kind] = kinds.get(ep.kind, 0) + 1
    return {"episodes": len(episodes), "rounds": rounds,
            "readable": readable,
            "sources": sorted({e.source for e in episodes}),
            "outcomes": outcomes, "kinds": kinds}


class FeedbackLog:
    """Append-only pickle stream of `Decision`s.

    Pickle rather than JSON for the same reason `_record_position` gives:
    a summary records what someone thought to write down, and that
    assumption is the one that keeps turning out wrong. The state goes in
    whole and replayable; `export` flattens it when something downstream
    wants columns.

    Opened per append rather than held: the panel is killed with the
    window and a held handle loses the tail of every session.
    """

    def __init__(self, path: str, source: str, session: str = "") -> None:
        if not source:
            raise ValueError("a feedback record needs a source; see module docs")
        self.path = path
        self.source = source
        self.session = session or ("%x" % int(time.time() * 1000))
        self.written = 0
        self.skipped = 0

    def append(self, decision: Decision) -> bool:
        """Write one row. False if it was not worth keeping.

        A round with nothing observed AND no rejection is not a label,
        it is a round that happened -- and a store that fills with those
        makes the real rows harder to find rather than easier.
        """
        if (decision.observed is None and decision.preferred is None
                and not decision.rejected):
            self.skipped += 1
            return False
        decision.source = self.source
        decision.session = self.session
        if not decision.rid:
            decision.rid = "%s:%d" % (self.session, self.written)
        try:
            with open(self.path, "ab") as handle:
                pickle.dump(decision, handle, protocol=4)
        except OSError:
            # Recording must never cost the advice it records.
            return False
        self.written += 1
        return True


    def correct(self, rid: str, target_index: Optional[int] = None,
                discard: bool = False) -> bool:
        """Amend a row the player says is wrong, by appending.

        Only the target can be fixed, because it is the only field the
        pouch diff guesses at -- everything else was read exactly. A row
        that is wrong in some other way is discarded whole rather than
        patched into something plausible.
        """
        if not rid:
            return False
        try:
            with open(self.path, "ab") as handle:
                pickle.dump(Decision(source=self.source, session=self.session,
                                     rid="%s:c%d" % (self.session, self.written),
                                     corrects=rid, discard=bool(discard),
                                     observed=None if discard else target_index),
                            handle, protocol=4)
        except OSError:
            return False
        self.written += 1
        return True


def read(path: str, raw: bool = False) -> List[Decision]:
    """Every record in a log, oldest first, with corrections applied.

    `raw=True` returns the stream as written, corrections included, for
    auditing how often the reader was overruled.
    """
    out: List[Decision] = []
    if not os.path.exists(path):
        return out
    with open(path, "rb") as handle:
        while True:
            try:
                out.append(pickle.load(handle))
            except EOFError:
                break
    if raw:
        return out
    return _apply_corrections(out)


def _apply_corrections(rows: List[Decision]) -> List[Decision]:
    """Fold amendments into the rows they amend.

    A correction with no matching row is DROPPED rather than kept as a
    row of its own: it describes something that is not there, and a
    label with no position is not a label.
    """
    by_id = {r.rid: r for r in rows if not r.corrects}
    dropped = set()
    for row in rows:
        if not row.corrects:
            continue
        target = by_id.get(row.corrects)
        if target is None:
            continue
        if row.discard:
            dropped.add(row.corrects)
        elif target.observed is not None and row.observed is not None:
            target.observed.target_index = row.observed
    return [r for r in rows
            if not r.corrects and r.rid not in dropped]


def summarise(records: List[Decision]) -> Dict[str, Any]:
    """What a log holds, for deciding whether it is worth fitting on."""
    agree = {"rl": 0, "search": 0}
    differ = {"rl": 0, "search": 0}
    unreadable: Dict[str, int] = {}
    sources = set()
    for rec in records:
        sources.add(rec.source)
        if rec.unreadable:
            unreadable[rec.unreadable] = unreadable.get(rec.unreadable, 0) + 1
        for name, beat in rec.beats().items():
            if beat is True:
                differ[name] += 1
            elif beat is False:
                agree[name] += 1
    stated = sum(1 for r in records if r.stated())
    # How often a player did what they said they would. Only countable
    # where BOTH exist, and worth watching: a wide gap means the stated
    # preferences describe an intention rather than a policy.
    both = [r for r in records
            if r.preferred is not None and r.observed is not None]
    kept = sum(1 for r in both if _same_move(r.preferred, r.observed))
    return {"records": len(records), "sources": sorted(sources),
            "agreed": agree, "differed": differ,
            "unreadable": unreadable,
            "stated": stated, "inferred": len(records) - stated,
            "said_and_did": (kept, len(both)),
            "rejections": sum(1 for r in records if r.rejected)}
