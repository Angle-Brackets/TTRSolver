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

# A cog at full health does NOT read 1.0, and the shortfall varies with
# how large the plate is on screen. Measured on live frames at 1900px
# wide: a single full cog read 0.91 and 0.96 on different frames, and two
# full cogs read 0.99 each. `health_fraction` counts saturated columns
# across the health region, and the region is a little wider than the bar
# it contains, so the ends never light.
#
# 0.97 was too tight and turned a full cog into a 91% one. The error runs
# the DANGEROUS way: the solver plans 91% of the damage the cog actually
# needs, throws it, and the cog survives on a sliver.
#
# Readings of a FULL bar, gathered live: 0.90, 0.91, 0.91, 0.95, 0.96,
# 0.99, 0.99. Seven observations spanning nine points, with no clean
# relationship to plate size -- a 65x44 plate read 0.99 and a 70x47 read
# 0.90 in the same frame.
#
# 0.90 sat exactly on the lowest observation, which is no tolerance at
# all: the next full bar to read 0.89 would be planned against as a
# damaged cog. 0.85 puts a margin under the whole observed range.
#
# The error is asymmetric, which is what decides the direction to round.
# Reading a full cog as damaged makes the solver plan 90% of the damage
# the cog needs, throw it, and leave the cog alive on a sliver -- the
# failure costs the fight. Reading a lightly damaged cog as full makes it
# over-damage by a few hit points, which costs a gag at worst. So the
# threshold is set to be wrong in the second direction.
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
        # Duration is unknown -- nothing reads the indicator, let alone
        # how many rounds are left on it -- so one round is assumed. That
        # is the conservative end: it credits the forced accuracy and the
        # knockback that apply THIS round, which is what the advice turns
        # on, without promising quiet the party may not get.
        # The accuracy recorded here is the lure's own, used for the
        # wake-up check; 80 is the mid-range of the Lure gags. It does
        # not affect the forced accuracies that make this matter.
        cog.status.apply_lure(80, 1, None)
    return cog, []


def build_state(snapshot=None, panel=None, readings: Sequence = (),
                round_num: int = 0,
                ignore_checksum: bool = False,
                allies: int = 0, fires: int = 0,
                unites: int = 0) -> BuildResult:
    """Assemble a BattleState from whatever the readers have produced.

    `snapshot` is a `ttr_local.Snapshot`, `panel` a `gagpanel.GagPanel`,
    `readings` the `watch.CogReading`s for the cogs on screen.

    `allies` is how many OTHER toons are in the fight, 0-3. It is set by
    the player rather than read: nothing on screen has been shown to
    count toons reliably, and this module's rule is a state or the
    reasons there isn't one, never a guess. Zero is therefore the
    default and solo is what you get if nobody says otherwise -- which
    is also the safe direction, because it is the one that assumes
    every cog attack is coming at you.

    `fires` and `unites` are SET BY THE PLAYER, on the same footing as
    `allies` and for the same reason: nothing TTR exposes counts them.
    The Local API reports laff, tracks, organic, location and invasion
    and no inventory; the screen shows the gag menu and not the slip or
    unite pouch. A player typing "I have three" is an assertion, not a
    guess -- which is the distinction this module actually cares about.

    Both default to 0, so an unanswered box advises neither, and that is
    the safe direction.

    SOS CARDS ARE DELIBERATELY ABSENT. A slip is a slip and a unite is a
    unite, so a count is the whole story; there are 29 distinct cards
    and a count says nothing about WHICH. Accepting a number here would
    let the solver advise a card the player may not hold, which is the
    invented state this module exists to refuse. Naming them needs a
    picker or a reader, not another integer.

    `ignore_checksum` builds a state from gag counts that do not match
    the menu's own total. It exists to exercise the rest of the pipeline
    while a known digit misread is outstanding, and it is a deliberate
    violation of this module's whole premise -- the caller is expected
    to say so out loud. Never set it by default.
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
        # The menu prints its own total and the cells have to sum to it.
        # A misread count is the quietest way to be wrong here: it does
        # not look like an error downstream, it looks like a toon
        # carrying one fewer gag, and the solver plans confidently
        # around it. Blocking is the right response for the same reason
        # an unknown cog blocks -- see this module's docstring.
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
                     fires=max(0, int(fires)),
                     unites_held=max(0, int(unites)))
    return BuildResult(BattleState(toon=toon, cogs=cogs,
                                   round_num=round_num,
                                   allies_standing=max(0, min(3, int(allies)))),
                       [])


def describe(state: BattleState) -> str:
    lines = [f"toon {state.toon.laff}/{state.toon.max_laff} laff, "
             f"{sum(state.toon.gag_counts.values())} gags"]
    for cog in state.cogs:
        entry = data.cog(cog.department, cog.cog_type)
        lines.append(f"  {entry.display} (level {cog.level}) "
                     f"{cog.hp}/{cog.max_hp} hp")
    return "\n".join(lines)
