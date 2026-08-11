"""
SYNTHETIC STAND-IN DATA -- NOT GAME ACCURATE. FOR EXERCISING CODE PATHS ONLY.

Bossbot cog accuracy is still TODO (see docs/data-confidence.md), and
mechanics.cog_attack_damage_and_accuracy deliberately raises rather than
guess. That makes it impossible to run a fight end to end, which in turn
makes it impossible to smoke-test the round loop.

This module is the one sanctioned place to paper over that gap: it patches
in an obviously-fake accuracy table inside a context manager that restores
the real (None) value on exit, so the fake can never leak into a solver run
by accident. Nothing here is a source of truth -- delete the relevant helper
the moment the real numbers land in data/.
"""
from contextlib import contextmanager

from . import data
from .state import ToonState, CogState, BattleState, Track

# Flat 75% for every Flunky attack at every level. Chosen to be visibly
# uniform so nobody mistakes it for transcribed data.
_FAKE_FLUNKY_ACCURACY = {
    "pound_key":   [75, 75, 75, 75, 75],
    "shred":       [75, 75, 75, 75, 75],
    "clip_on_tie": [75, 75, 75, 75, 75],
}


@contextmanager
def synthetic_bossbot_accuracy():
    """Temporarily install fake Flunky accuracy so a fight can run to
    completion. Restores the previous value (normally None) on exit."""
    flunky = data.BOSSBOT_COGS["flunky"]
    previous = flunky["accuracy"]
    flunky["accuracy"] = _FAKE_FLUNKY_ACCURACY
    try:
        yield
    finally:
        flunky["accuracy"] = previous


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
