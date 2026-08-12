"""
Battle state representation for the solo-toon-vs-cogs simulator.

Design note: status effects (trap, lure, etc.) are folded into explicit
state fields rather than tracked via history, so the transition function
in simulator.py stays a clean Markov step: (state, action) -> next_state.
See docs/data-confidence.md for why this matters and what it does/doesn't buy you.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, FrozenSet, Tuple, List


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


@dataclass(slots=True)
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

    # Tracks whose gags are organic. Organic is a property of the whole
    # track, not of an individual gag -- a toon earns an organic track
    # from a ToonTask and every gag in it is organic thereafter.
    #
    # Raises damage for every track, and accuracy for Lure specifically
    # (see Gag.prop_accuracy). Fixed for the battle, so `clone` shares it
    # rather than copying, exactly like track_exp.
    organic_tracks: FrozenSet[Track] = frozenset()

    def is_organic(self, track: Track) -> bool:
        return track in self.organic_tracks

    def has_gag(self, track: Track, level: int) -> bool:
        return self.gag_counts.get((track, level), 0) > 0


@dataclass(slots=True)
class CogStatus:
    lured: bool = False

    # Rounds of lure left on this cog -- the `currentlyLuredSuits[suitId][0]`
    # counter from the source pseudocode, which gates the wake-up check.
    # Counts cog phases this cog will skip; decremented every round the lure
    # holds, and the lure ends when it reaches 0. Set from
    # mechanics.lure_duration_rounds(), which is [CONFIRMED] against the
    # TTR wiki: 2/2/3/3/4/4/8 rounds by gag level.
    lure_rounds_remaining: int = 0

    # The PRE-BONUS accuracy (propAcc + trackExp + tgtDef, no bonus term)
    # that the Lure landing on this cog was rolled with. This is the input
    # to mechanics.lure_wakeup_chance(); the source stores it per-cog at the
    # moment the Lure resolves, because accuracy bonuses must not offset the
    # wake-up odds. None whenever the cog is not lured.
    lure_acc_before_bonus: Optional[int] = None

    # Level of the Lure gag that landed. Needed because whether a lure can
    # expire early is a property of that gag's base accuracy -- see
    # mechanics.lure_can_expire_early. None whenever the cog is not lured.
    lure_level: Optional[int] = None

    trapped: bool = False
    trap_track: Optional[Track] = None   # which gag laid the trap
    trap_level: Optional[int] = None
    # Whether the toon's Trap track was organic when this trap was laid.
    # Recorded here because the damage is dealt later, when a Lure drags
    # a cog onto it, by which time the action is long gone.
    trap_organic: bool = False

    is_dead: bool = False

    def apply_lure(self, acc_before_bonus: int, rounds: int,
                    level: Optional[int] = None) -> bool:
        """A Lure lands on this cog. Returns whether it did anything.

        **Re-luring an already-lured cog does NOT refresh its duration.**
        The existing counter runs down on its original schedule and the new
        gag is simply wasted on that cog. It doesn't stack either -- TTR
        3.0.0 "Removed the Lure Stacking Rounds mechanic that allowed the
        accumulation of Lure rounds ... if multiple Lure Gags are used
        simultaneously". Neither refresh nor stack: an already-lured cog is
        untouchable by Lure until its rounds run out.

        This is a no-op rather than an illegal action on purpose. A group
        Lure over a partly-lured battle has to be able to catch the
        un-lured cogs, so it can't be rejected wholesale -- it just leaves
        the already-lured ones alone.

        [UNVERIFIED] The no-refresh rule comes from play knowledge, not the
        wiki: the wiki documents the simultaneous-stacking removal above and
        says nothing about re-luring across rounds.
        """
        if self.lured:
            return False
        self.lured = True
        self.lure_rounds_remaining = rounds
        self.lure_acc_before_bonus = acc_before_bonus
        self.lure_level = level
        return True

    def clear_lure(self) -> None:
        """Cog stops being lured -- woke up early, or its rounds ran out."""
        self.lured = False
        self.lure_rounds_remaining = 0
        self.lure_acc_before_bonus = None
        self.lure_level = None

    def copy(self) -> "CogStatus":
        return CogStatus(
            lured=self.lured,
            lure_rounds_remaining=self.lure_rounds_remaining,
            lure_acc_before_bonus=self.lure_acc_before_bonus,
            lure_level=self.lure_level,
            trapped=self.trapped,
            trap_track=self.trap_track,
            trap_level=self.trap_level,
            trap_organic=self.trap_organic,
            is_dead=self.is_dead,
        )


@dataclass(slots=True)
class CogState:
    cog_type: str          # key into data/ cog tables, e.g. "flunky"
    department: str        # "bossbot" | "sellbot" | "cashbot" | "lawbot"
    level: int              # absolute level, e.g. 3
    hp: int
    max_hp: int
    status: CogStatus = field(default_factory=CogStatus)

    def copy(self) -> "CogState":
        return CogState(cog_type=self.cog_type, department=self.department,
                        level=self.level, hp=self.hp, max_hp=self.max_hp,
                        status=self.status.copy())


@dataclass(slots=True)
class BattleState:
    toon: ToonState
    cogs: List[CogState]
    round_num: int = 0

    def clone(self) -> "BattleState":
        """A deep-enough copy: every mutable field is fresh, and the shared
        leaves (Track enums, the (track, level) tuples used as gag keys) are
        immutable.

        Exists because `copy.deepcopy` dominated the solver's runtime -- it
        was 91% of a depth-2 search, since expectimax copies a state per
        outcome branch per node. This is ~20x faster for the same result.
        Extend it whenever you add a mutable field to any battle dataclass.
        """
        return BattleState(
            toon=ToonState(
                laff=self.toon.laff,
                max_laff=self.toon.max_laff,
                # Both dicts are SHARED, not copied. Cloning is the single
                # most expensive thing the search does -- 586,000 clones
                # for one three-cog depth-2 position -- and copying these
                # two was most of it.
                #
                # track_exp is the toon's training level per track. It is
                # fixed for the whole battle; nothing mutates it.
                #
                # gag_counts does change, but only in
                # simulator.apply_toon_action, which copies before
                # writing. Sharing here plus copying there costs one dict
                # copy per action instead of one per outcome branch.
                track_exp=self.toon.track_exp,
                gag_counts=self.toon.gag_counts,
                organic_tracks=self.toon.organic_tracks,
            ),
            cogs=[c.copy() for c in self.cogs],
            round_num=self.round_num,
        )

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
