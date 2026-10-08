"""
Shared battle fixtures for tests and demos.

A synthetic stand-in for [TODO] data is deleted the moment the real data
lands -- leaving one in place stops being scaffolding and starts
overwriting good data with bad. If you need one, use this shape: a
context manager that restores the real value on exit, an obviously-fake
value nobody could mistake for transcribed data, and a test asserting it
doesn't leak.
"""
from . import data
from .state import ToonState, CogState, BattleState, Track

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
