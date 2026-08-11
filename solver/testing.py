"""
SYNTHETIC STAND-IN DATA -- NOT GAME ACCURATE. FOR EXERCISING CODE PATHS ONLY.

Where a table is still [TODO], the mechanics deliberately raise rather than
guess (see docs/data-confidence.md). That's the right default, but it also
makes it impossible to run a fight end to end, and therefore impossible to
smoke-test the round loop. This module is the one sanctioned place to paper
over such a gap: each stand-in is a context manager that restores the real
value on exit, so a fake can never leak into a solver run by accident.

Nothing here is a source of truth. Delete a helper the moment its real
numbers land in data/ -- a stand-in that outlives its gap stops being
scaffolding and starts overwriting good data with bad, which is worse than
having no stand-in at all.

`synthetic_bossbot_accuracy()` was removed for exactly that reason once the
real Appendix C tables were transcribed. Lure duration is the only gap left
that blocks a full fight.
"""
from contextlib import contextmanager

from . import data
from . import mechanics
from .state import ToonState, CogState, BattleState, Track

# Flat 3 rounds for every Lure level -- deliberately uniform across levels
# so it can't be mistaken for a real table (real Lure duration certainly
# varies with gag level). The strategy guide never lists per-gag-level lure
# durations, so mechanics.lure_duration_rounds() raises without this patch;
# see the [TODO] on mechanics.LURE_ROUNDS_BY_LEVEL.
_FAKE_LURE_ROUNDS = 3


@contextmanager
def synthetic_lure_durations(rounds: int = _FAKE_LURE_ROUNDS):
    """Temporarily install a fake per-level Lure duration so fights that
    use Lure can run to completion. Restores the real ([TODO] = all None)
    table on exit."""
    previous = dict(mechanics.LURE_ROUNDS_BY_LEVEL)
    for level in mechanics.LURE_ROUNDS_BY_LEVEL:
        mechanics.LURE_ROUNDS_BY_LEVEL[level] = rounds
    try:
        yield
    finally:
        mechanics.LURE_ROUNDS_BY_LEVEL.clear()
        mechanics.LURE_ROUNDS_BY_LEVEL.update(previous)


@contextmanager
def synthetic_battle_data():
    """Every synthetic stand-in at once -- what a full fight currently
    needs. FAKE DATA; see the module docstring.

    Down to just lure durations now that real cog accuracy has landed. Kept
    as a named alias so callers don't have to track which gaps are still
    open; when the last one closes, this becomes a no-op and should go."""
    with synthetic_lure_durations():
        yield


def two_flunky_fight() -> BattleState:
    """A small, fixed scenario used by the smoke test and the demo script:
    one maxed Throw/Lure/Trap toon against a level-2 and a level-3 Flunky."""
    toon = ToonState(
        laff=50, max_laff=50,
        track_exp={Track.THROW: 7, Track.LURE: 7, Track.TRAP: 7},
        gag_counts={
            (Track.THROW, 3): 5,
            (Track.LURE, 2): 3,
            (Track.TRAP, 2): 3,
        },
    )
    cogs = [
        CogState(cog_type="flunky", department="bossbot", level=2,
                  hp=data.cog_max_hp(2), max_hp=data.cog_max_hp(2)),
        CogState(cog_type="flunky", department="bossbot", level=3,
                  hp=data.cog_max_hp(3), max_hp=data.cog_max_hp(3)),
    ]
    return BattleState(toon=toon, cogs=cogs)
