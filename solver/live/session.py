"""Turning what the screen and the Local API say into a BattleState.

Three sources, each authoritative for one thing and no substitute for
another:

    Local API   laff, and which gags are trained (which sets accuracy)
    gag menu    how many of each gag is carried
    cog plates  which cogs, at what level, and how hurt

REFUSING TO GUESS. `build_state` returns a state or the reasons it
cannot build one -- never fills a gap with something plausible. A cog
the head library hasn't learned is the common case: its level gives its
HP, but its attacks need knowing WHICH cog it is, and solving against
the wrong attack table gives confident advice for a fight that isn't
happening.

HP FROM THE HEALTH BAR. Cog HP is `max_hp * health_fraction`, rounded --
the one place a screen reading beats arithmetic, because joining a fight
already in progress leaves no damage history to reconstruct from. Once a
battle is followed from round one the solver's own tracking is exact and
this is only a cross-check -- see `vision.health_fraction`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .. import data
from ..state import BattleState, CogState, Track, ToonState

# A cog at full health does NOT read 1.0 -- the shortfall varies with
# plate size on screen. Readings of FULL bars, gathered live: 0.90, 0.91,
# 0.91, 0.95, 0.96, 0.99, 0.99, with no clean relation to plate size (a
# 65x44 plate read 0.99, a 70x47 read 0.90, in the same frame).
#
# The error is asymmetric, which decides which way to round: reading a
# full cog as damaged makes the solver underplan and leave the cog alive
# on a sliver, costing the fight; reading a lightly damaged cog as full
# just over-damages by a few hp, costing a gag at worst. 0.85 sits under
# the whole observed range, erring toward the cheap mistake.
FULL_HEALTH = 0.85


@dataclass(frozen=True)
class BuildResult:
    """Either a state, or why there isn't one."""

    state: Optional[BattleState]
    problems: List[str]

    def __bool__(self) -> bool:
        return self.state is not None


def cog_from_reading(reading) -> Tuple[Optional[CogState], List[str]]:
    """One CogState from one plate reading, or the reasons there isn't."""
    problems: List[str] = []
    if reading.level is None:
        problems.append(f"cog {reading.index + 1}: level unreadable")
    if reading.cog is None:
        if reading.department and reading.level is not None:
            # Points at the panel's dropdown rather than a CLI in
            # another window: the player is mid-battle looking at the
            # cog, and naming it there both unblocks this fight and
            # teaches the library.
            problems.append(
                f"cog {reading.index + 1}: a {reading.department} level "
                f"{reading.level}, but which one is not in the head "
                f"library yet -- pick it from the dropdown")
        else:
            problems.append(f"cog {reading.index + 1}: unidentified")
    if problems:
        return None, problems

    max_hp = data.cog_max_hp(reading.level)
    fraction = reading.health
    if fraction >= FULL_HEALTH:
        hp = max_hp
    else:
        # Round rather than truncate: a bar reading 0.5 on a 56hp cog is
        # 28, and floor() would quietly shave a point off every cog.
        hp = max(1, min(max_hp, round(max_hp * fraction)))

    cog = CogState(cog_type=reading.cog,
                   department=reading.department
                   or data.department_of(reading.cog),
                   level=reading.level, hp=hp, max_hp=max_hp)
    if getattr(reading, "lured", False):
        # Duration is unknown (nothing reads the indicator or rounds
        # left), so one round is assumed -- the conservative end, since
        # it credits this round's forced accuracy and knockback without
        # promising quiet the party may not get. The 80 is only the
        # lure's own accuracy for the wake-up check (mid-range of Lure
        # gags); it does not affect the forced accuracies that matter.
        cog.status.apply_lure(80, 1, None)
    level = getattr(reading, "trap_level", None)
    if getattr(reading, "trapped", False) and level:
        # A LEVEL IS REQUIRED, not just the flag. `CogStatus.trapped`
        # with `trap_level=None` raises the moment a Lure tries to
        # spring it -- `data.gag(TRAP, None)` has nothing to look up --
        # which is the crash the SOS trap cards hit first.
        cog.status.trapped = True
        cog.status.trap_level = int(level)
    return cog, []


def build_state(snapshot=None, panel=None, readings: Sequence = (),
                round_num: int = 0,
                ignore_checksum: bool = False,
                allies: int = 0, fires: int = 0) -> BuildResult:
    """Assemble a BattleState from whatever the readers have produced.

    `snapshot` is a `ttr_local.Snapshot`, `panel` a `gagpanel.GagPanel`,
    `readings` the `watch.CogReading`s for the cogs on screen.

    `allies` (0-3, other toons in the fight) and `fires` (pink slips
    carried) are both SET BY THE PLAYER, not read: nothing on screen or
    in the Local API counts either reliably, and this module's rule is a
    state or the reasons there isn't one, never a guess. Both default to
    0 -- solo and "no fire" are the safe assumptions, since they plan for
    every attack landing on you and spend nothing you don't have. A pink
    slip is the one consumable a plain count can fully describe: slips
    are fungible, so a number is the whole story.

    Unites and SOS cards are absent for a stronger reason than "unread":
    a count would not be enough even if read, since a unite is one of
    five Toon-Up values (or eight Gag-Up variants) and a card one of 29.
    Leaving `unite_stock` as a bare count would read as "unknown, permit
    everything", and the solver could offer a Gag-Up Lure to a toon
    holding only Toon-Ups. Naming them needs a picker or a reader, not
    another integer.

    `ignore_checksum` builds a state from gag counts that don't match the
    menu's own total, to exercise the rest of the pipeline while a known
    digit misread is outstanding. It violates this module's whole
    premise -- the caller is expected to say so out loud, and it is
    never set by default.
    """
    problems: List[str] = []

    if snapshot is None:
        problems.append(
            "no Local API snapshot: laff and gag training are unknown "
            "(is the game running with the Local API enabled?)")
    if not readings:
        problems.append("no cog plates on screen")

    if panel is None:
        problems.append(
            "no gag menu on screen: carrying nothing until it is read "
            "(press the gag key so the menu is visible)")
    else:
        # The menu's own total must match the summed cells. A misread
        # count looks like a toon carrying one fewer gag, not an error,
        # and the solver plans confidently around it -- block for the
        # same reason an unknown cog blocks.
        bad = panel.checksum_problem()
        if bad and not ignore_checksum:
            problems.append(bad)

    cogs: List[CogState] = []
    for reading in readings:
        cog, why = cog_from_reading(reading)
        problems.extend(why)
        if cog is not None:
            cogs.append(cog)

    # Every reason at once. Collecting them and returning here, rather
    # than bailing at the first, is the difference between "fix this,
    # run again, fix the next one" and being told what is wrong.
    if snapshot is None or problems:
        return BuildResult(None, problems)

    track_exp = snapshot.track_exp()
    # The panel sees training too, but the API states it; only take
    # counts from the screen.
    gag_counts: Dict[Tuple[Track, int], int] = panel.counts()

    toon = ToonState(laff=snapshot.laff, max_laff=snapshot.max_laff,
                     track_exp=track_exp, gag_counts=gag_counts,
                     organic_tracks=frozenset(snapshot.organic_tracks()),
                     fires=max(0, int(fires)))
    zone = (getattr(snapshot, "zone", "") or "").strip()
    return BuildResult(BattleState(toon=toon, cogs=cogs,
                                   round_num=round_num,
                                   allies_standing=max(0, min(3, int(allies))),
                                   kind=fight_kind(zone)),
                       [])


# Zone strings that mean "this battle is one floor of several". OBSERVED
# from the Local API inside a building on 2026-10-05 ("Cog Building,
# Daisy Gardens [Blam Canyon]"). Only what has been seen is listed: a
# facility's or a Field Office's string is unknown until someone stands
# in one, and a guessed string would just never match.
BUILDING_ZONES = frozenset({"Cog Building"})


def fight_kind(zone: str) -> str:
    """"facility" inside a building (more unknown floors may follow, so
    the playouts keep a value on the pouch), else "street"."""
    return "facility" if zone in BUILDING_ZONES else "street"


def describe(state: BattleState) -> str:
    lines = [f"toon {state.toon.laff}/{state.toon.max_laff} laff, "
             f"{sum(state.toon.gag_counts.values())} gags"]
    for cog in state.cogs:
        entry = data.cog(cog.department, cog.cog_type)
        lines.append(f"  {entry.display} (level {cog.level}) "
                     f"{cog.hp}/{cog.max_hp} hp")
    return "\n".join(lines)
