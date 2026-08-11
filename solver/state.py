"""
Battle state representation for the solo-toon-vs-cogs simulator.

Design note: status effects (trap, lure, etc.) are folded into explicit
state fields rather than tracked via history, so the transition function
in simulator.py stays a clean Markov step: (state, action) -> next_state.
See docs/data-confidence.md for why this matters and what it does/doesn't buy you.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Tuple, List


class Track(str, Enum):
    TOON_UP = "toon_up"
    TRAP = "trap"
    LURE = "lure"
    SOUND = "sound"
    THROW = "throw"
    SQUIRT = "squirt"
    DROP = "drop"


# Fixed initiative order used to resolve a round.
# [CONFIRMED] via Toontown-Resources README ("misc-2" section).
ATTACK_ORDER: List[Track] = [
    Track.TOON_UP, Track.TRAP, Track.LURE,
    Track.SOUND, Track.THROW, Track.SQUIRT, Track.DROP,
]

GROUP_TRACKS = {Track.TOON_UP, Track.SOUND, Track.LURE}  # can hit all cogs
# Throw/Squirt only go multi-target at level 7 (Wedding Cake / Geyser).


@dataclass
class ToonState:
    laff: int
    max_laff: int

    # track_exp[track] = toon's TRAINING level in that track (0-7).
    # This is a fixed skill stat, NOT the level of the gag about to be
    # thrown -- a toon maxed in Throw gets the same trackExp accuracy
    # bonus whether they throw a Cupcake or a Whole Cream Pie.
    # Assume 7 (maxed) for owned tracks unless modeling gag training.
    track_exp: Dict[Track, int] = field(default_factory=dict)

    # gag_counts[(track, level)] = number of that gag left in the pouch
    gag_counts: Dict[Tuple[Track, int], int] = field(default_factory=dict)

    def has_gag(self, track: Track, level: int) -> bool:
        return self.gag_counts.get((track, level), 0) > 0


@dataclass
class CogStatus:
    lured: bool = False
    lure_rounds_remaining: int = 0

    trapped: bool = False
    trap_track: Optional[Track] = None   # which gag laid the trap
    trap_level: Optional[int] = None

    is_dead: bool = False


@dataclass
class CogState:
    cog_type: str          # key into data/ cog tables, e.g. "flunky"
    department: str        # "bossbot" | "sellbot" | "cashbot" | "lawbot"
    level: int              # absolute level, e.g. 3
    hp: int
    max_hp: int
    status: CogStatus = field(default_factory=CogStatus)


@dataclass
class BattleState:
    toon: ToonState
    cogs: List[CogState]
    round_num: int = 0

    def active_cogs(self) -> List[CogState]:
        return [c for c in self.cogs if not c.status.is_dead]

    def is_terminal(self) -> bool:
        return self.toon.laff <= 0 or len(self.active_cogs()) == 0

    def is_win(self) -> bool:
        return self.toon.laff > 0 and len(self.active_cogs()) == 0


@dataclass
class Action:
    """A solo toon's choice for one round."""
    track: Track
    level: int
    # target_index: index into state.cogs, or None for a track that hits
    # all active cogs (Toon-Up, Sound, Lure, or level-7 Throw/Squirt/Drop/Trap)
    target_index: Optional[int] = None
