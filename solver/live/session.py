"""Turning what the screen and the Local API say into a BattleState.

Three sources, each authoritative for a different thing:

    Local API   laff, and which gags are trained (which sets accuracy)
    gag menu    how many of each gag is carried
    cog plates  which cogs, at what level, and how hurt

None of them covers the whole fight, and none is a good substitute for
another. The API knows entitlements exactly and the battle not at all;
the screen knows the battle and cannot be asked about anything off it.

REFUSING TO GUESS
-----------------
`build_state` returns a state or a list of reasons it cannot build one.
It never fills a gap with something plausible. A cog whose identity the
head library has not learned is the common case: its level gives its HP,
but its attacks come from knowing *which* cog it is, and a solver run
against the wrong attack table gives confident advice for a fight that
is not happening. Saying "I do not know this cog yet" is the useful
answer, because it also says what to do about it.

HP FROM THE HEALTH BAR
----------------------
Cog HP is `max_hp * health_fraction`, rounded. That is the one place a
screen reading is preferred to arithmetic, and only because there is no
arithmetic available: on joining a fight already in progress there is no
history to reconstruct the damage from. Once a battle is being followed
from its first round the solver's own tracking is exact and this is only
a cross-check -- see `vision.health_fraction`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .. import data
from ..state import BattleState, CogState, Track, ToonState

# A cog at full health should read 1.0; allow for the bar's own noise
# before rounding down to a number of hit points.
FULL_HEALTH = 0.97


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
            problems.append(
                f"cog {reading.index + 1}: a {reading.department} level "
                f"{reading.level}, but which one is not in the head "
                f"library yet -- run "
                f"`python -m solver.live.read_battle --label`")
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

    return CogState(cog_type=reading.cog,
                    department=reading.department
                    or data.department_of(reading.cog),
                    level=reading.level, hp=hp, max_hp=max_hp), []


def build_state(snapshot=None, panel=None, readings: Sequence = (),
                round_num: int = 0) -> BuildResult:
    """Assemble a BattleState from whatever the readers have produced.

    `snapshot` is a `ttr_local.Snapshot`, `panel` a `gagpanel.GagPanel`,
    `readings` the `watch.CogReading`s for the cogs on screen.
    """
    problems: List[str] = []

    if snapshot is None:
        problems.append(
            "no Local API snapshot: laff and gag training are unknown "
            "(is the game running with the Local API enabled?)")
    if not readings:
        problems.append("no cog plates on screen")

    cogs: List[CogState] = []
    for reading in readings:
        cog, why = cog_from_reading(reading)
        problems.extend(why)
        if cog is not None:
            cogs.append(cog)

    if snapshot is None or problems:
        return BuildResult(None, problems)

    track_exp = snapshot.track_exp()
    if panel is not None:
        # The panel sees training too, but the API states it; only take
        # counts from the screen.
        gag_counts: Dict[Tuple[Track, int], int] = panel.counts()
    else:
        gag_counts = {}
        problems.append(
            "no gag menu on screen: carrying nothing until it is read "
            "(press the gag key so the menu is visible)")
        return BuildResult(None, problems)

    toon = ToonState(laff=snapshot.laff, max_laff=snapshot.max_laff,
                     track_exp=track_exp, gag_counts=gag_counts,
                     organic_tracks=frozenset(snapshot.organic_tracks()))
    return BuildResult(BattleState(toon=toon, cogs=cogs,
                                   round_num=round_num), [])


def describe(state: BattleState) -> str:
    lines = [f"toon {state.toon.laff}/{state.toon.max_laff} laff, "
             f"{sum(state.toon.gag_counts.values())} gags"]
    for cog in state.cogs:
        entry = data.cog(cog.department, cog.cog_type)
        lines.append(f"  {entry.display} (level {cog.level}) "
                     f"{cog.hp}/{cog.max_hp} hp")
    return "\n".join(lines)
