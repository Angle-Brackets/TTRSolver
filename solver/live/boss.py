"""Which boss fight this is, how many cogs are down, and what is left.

THE PROBLEM IT SOLVES. Neither live state builder set `kind`,
`cogs_remaining` or `holdout`, so every wave of a VP reached the solver
as a standalone street battle with nothing after it. With no horizon, a
level 7 costs the least it ever can, and a solo VP spent its power gags
on the easy cog round and met the skelecog round empty-handed. Measured
in simulation, the same solo VP played with that blindness cleared 5/100
against 13/100 when the solver knew the structure (+12/-4, p = 0.077).

WHAT IT IS ALLOWED TO KNOW. The owner signed off on the published round
structure of the four boss fights -- that a VP's cog round is followed
by a harder skelecog round, say -- and on counting cogs defeated against
it. That is information a player has. It does NOT extend to cog
buildings or facilities, whose next floor a player cannot see; this
module only ever names a boss.

ROUND SIZES are evidence, tagged like everything else in `solver/data`.
Where a size is not confirmed it is None, and an unknown size makes
`remaining` None rather than a guess -- the counter still runs, the
state is still marked as the right fight, but no horizon is invented.

Source-neutral on purpose: the TTR panel and the other front end both
feed it, through `note_defeated` and `set_kind`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Set, Tuple

# Cogs per round, in order. None where unknown.
BOSS_ROUNDS = {
    # [OWNER, from play] twenty a round for a SOLO VP -- see `vp.COG_ROUND`.
    # A party VP's count has not been reported, which `remaining` honours
    # through PARTY_COUNTS_KNOWN below.
    "vp": (20, 20),
    # [OWNER, verified in game] twenty in battle one, PER SIDE -- see
    # `ceo.ROUND_ONE`. Battle two is whoever survived the banquet plus
    # the Big Cheese: it varies by play, so it is unknown until seen.
    "ceo": (20, None),
    # [TODO] neither published source gives a count and none has been
    # observed. Left unknown rather than filled with something plausible.
    "cfo": None,
    "cj": None,
}

BOSS_KINDS = tuple(BOSS_ROUNDS)

# Fights whose counts were reported for a party as well as solo. Empty:
# the VP's twenty-and-twenty is a solo observation, and applying it to a
# party would be the guess the no-guessing rule forbids.
PARTY_COUNTS_KNOWN: Set[str] = set()

# WHERE TTR'S LOCAL API PUTS YOU IN A BOSS ROOM. [TODO] Empty on purpose:
# `location.zone` inside the four boss rooms has never been observed, and
# the strings outside them ("Sellbot HQ" covers a factory too) do not
# identify a fight. The panel shows the zone it reads, so the first time
# a player stands in one the string can be copied in here. Until then
# the player names the fight with the panel's picker.
TTR_BOSS_ZONES: Dict[str, str] = {}


def boss_from_location(zone: Optional[str]) -> Optional[str]:
    """The boss fight a TTR zone string names, or None."""
    return TTR_BOSS_ZONES.get((zone or "").strip())


# A plate that vanishes this close to empty died; one that vanishes
# healthier than this was hidden behind an animation and will be back.
# Only the screen-reading front end needs it -- the other has cog ids.
DEATH_HEALTH = 0.25


@dataclass
class BossTracker:
    """One boss fight's running count."""

    kind: Optional[str] = None
    defeated: int = 0
    party_size: int = 1
    _dead_ids: Set[int] = field(default_factory=set)

    # -- what the fight is ------------------------------------------------

    def set_kind(self, kind: Optional[str]) -> None:
        """Name the fight, or clear it with None. Changing it restarts
        the count, because a count against the wrong structure is
        worse than none."""
        kind = kind or None
        if kind is not None and kind not in BOSS_ROUNDS:
            raise ValueError("not a boss fight: %r (one of %s)"
                             % (kind, ", ".join(BOSS_KINDS)))
        if kind != self.kind:
            self.kind = kind
            self.reset()

    def reset(self) -> None:
        self.defeated = 0
        self._dead_ids = set()

    def frozen(self) -> "BossTracker":
        """A copy to hand to another thread, which must not see this
        one's count move under it."""
        return BossTracker(kind=self.kind, defeated=self.defeated,
                           party_size=self.party_size,
                           _dead_ids=set(self._dead_ids))

    # -- counting ---------------------------------------------------------

    def note_defeated(self, count: int = 1) -> None:
        """Add plain defeats -- the screen reader's path, no ids."""
        if self.kind is not None and count > 0:
            self.defeated += int(count)

    def note_dead_ids(self, ids: Iterable[int]) -> None:
        """Add defeats by object id, each counted once however often it
        is reported -- the exact path, for a client that names cogs."""
        if self.kind is None:
            return
        for cog_id in ids:
            if cog_id not in self._dead_ids:
                self._dead_ids.add(cog_id)
                self.defeated += 1

    def correct(self, defeated: int) -> None:
        """The player setting the count by hand. They can see the fight;
        a misread plate cannot argue with them."""
        self.defeated = max(0, int(defeated))

    # -- what is left -----------------------------------------------------

    def rounds(self) -> Optional[Tuple]:
        rounds = BOSS_ROUNDS.get(self.kind) if self.kind else None
        if rounds is None:
            return None
        if self.party_size > 1 and self.kind not in PARTY_COUNTS_KNOWN:
            return None
        return rounds

    def round_index(self) -> Optional[int]:
        """Which round the count says we are in, 0-based, or None."""
        rounds = self.rounds()
        if not rounds:
            return None
        seen = 0
        for index, size in enumerate(rounds):
            if size is None:
                return index
            seen += size
            if self.defeated < seen:
                return index
        return len(rounds) - 1

    def later_rounds(self) -> Optional[int]:
        """Cogs in the rounds AFTER this one -- the quantity the solver's
        `cogs_remaining` means, matching `FacilityPlan.remaining` in the
        simulator. None when any later round's size is unknown."""
        rounds, index = self.rounds(), self.round_index()
        if rounds is None or index is None:
            return None
        later = rounds[index + 1:]
        if any(size is None for size in later):
            return None
        return sum(later)

    def left_in_fight(self, on_field: int = 0) -> Optional[int]:
        """Every cog still to beat, for the panel. None if unknown."""
        rounds = self.rounds()
        if rounds is None or any(size is None for size in rounds):
            return None
        return max(0, sum(rounds) - self.defeated - max(0, on_field))

    # -- feeding the solver -----------------------------------------------

    def apply(self, state) -> None:
        """Mark `state` as this fight and give it the horizon.

        Leaves `holdout` alone: that holds the actual cogs waiting to walk
        in, and nobody can see which cogs those are, only how many. An
        invented holdout would be exactly the guessed state this project
        refuses to build.
        """
        if self.kind is None or state is None:
            return
        state.kind = self.kind
        later = self.later_rounds()
        if later is not None:
            state.cogs_remaining = later


def died_plates(before, after) -> int:
    """How many plates in `before` died rather than hid, given `after`.

    The screen reader has no cog ids, and plates also vanish while an
    attack animation covers them. So only a plate that was nearly empty
    counts, and never more than the plate count actually fell by.
    """
    dropped = len(before) - len(after)
    if dropped <= 0:
        return 0
    nearly_dead = sum(1 for reading in before
                      if getattr(reading, "health", 1.0) <= DEATH_HEALTH)
    return min(dropped, nearly_dead)
