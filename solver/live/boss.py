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
from typing import Dict, Iterable, NamedTuple, Optional, Set, Tuple

BOSS_KINDS = ("vp", "ceo", "cfo", "cj")

# Fights whose toons split across TWO battles. [OWNER] a VP's toons "get
# split evenly across both sides", and the CEO's round one is 20 a side.
# The CFO and CJ are [TODO], so they keep everyone in one battle.
TWO_SIDED = ("vp", "ceo")


def toons_in_battle(kind: Optional[str], players: int) -> int:
    """Toons in YOUR battle, counting you, of `players` in the whole fight.

    Evenly split in a two-sided fight; an odd count is rounded up, so
    three toons put you with one teammate rather than none -- the side
    that overstates help rather than danger is the less surprising one.
    """
    players = max(1, int(players))
    if kind in TWO_SIDED:
        return (players + 1) // 2
    return players


def rounds_for(kind: Optional[str], players: int) -> Optional[Tuple]:
    """Each round's cogs ON ONE SIDE, in order, for a fight of `players`
    toons in all. None where the fight's sizes are unknown, and None for
    a round whose size is. The sizes come from the fights' own modules,
    so the simulator and the tracker cannot disagree.
    """
    if kind == "vp":
        # [OWNER, from play] twenty a round in all. Alone you face all of
        # it; with company the toons split across the two sides and each
        # side faces ten -- see `vp.side_rounds`.
        from .. import vp as vp_mod
        return vp_mod.side_rounds(players)
    if kind == "ceo":
        # [OWNER, verified in game] twenty in battle one PER SIDE, so
        # alone you face forty (the solo figure is the owner's "I think",
        # not a count). Battle two is the banquet's survivors plus the Big
        # Cheese: it varies by play, so it is unknown until seen.
        from .. import ceo as ceo_mod
        return (ceo_mod.round_one_for(players), None)
    # cfo, cj: [TODO] neither published source gives a count and none has
    # been observed. Left unknown rather than filled with something
    # plausible.
    return None


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


# WHERE THE TTR CLIENT'S LOG PUTS YOU IN A BOSS ROOM, as (where, hoodId)
# from its `enter(requestStatus=...)` line -- see `ttr_log`. OBSERVED: a
# VP on 2026-10-10 logged ('CogHQBossBattle', 11000), hood 11000 being
# Sellbot HQ. The CFO, CJ and CEO are [TODO] until a player stands in
# one: the same 'where' with another hood is the obvious guess, and a
# guessed key would quietly name the wrong fight if it were wrong.
TTR_BOSS_PLACES: Dict[Tuple[str, int], str] = {
    ("CogHQBossBattle", 11000): "vp",
}


def boss_from_place(where: Optional[str], hood: Optional[int]) -> Optional[str]:
    """The boss fight a client-log place names, or None."""
    if where is None or hood is None:
        return None
    return TTR_BOSS_PLACES.get((where, int(hood)))


# WHO THE UNSEEN COGS ARE, as far as a player knows: the department and
# each round's level band, both from the fight's own module so there is
# one source for them. A round with no band is unknown and ends the
# horizon there -- no partial guess past it.
DEPARTMENT = {"vp": "sellbot", "ceo": "bossbot"}


def _round_bands(kind: str):
    if kind == "vp":
        from .. import vp as vp_mod
        return (vp_mod.COG_LEVELS, vp_mod.SKELECOG_LEVELS)
    if kind == "ceo":
        from .. import ceo as ceo_mod
        # Battle two is the banquet's survivors plus the Big Cheese:
        # neither its size nor its make-up is known until seen.
        return (ceo_mod.COG_LEVELS, None)
    return None


class Horizon(NamedTuple):
    """What a player knows is still coming, and nothing about WHICH cogs.

    `holdout` cogs are still to walk into this round, drawn from `band`;
    each later round is (count, band). A playout fills these in by
    drawing from the band -- see `solver.search.playout`.
    """
    holdout: int
    band: Tuple[int, int]
    later: Tuple[Tuple[int, Tuple[int, int]], ...]
    department: str


# A plate that vanishes this close to empty died; one that vanishes
# healthier than this was hidden behind an animation and will be back.
# Only the screen-reading front end needs it -- the other has cog ids.
DEATH_HEALTH = 0.25


@dataclass
class BossTracker:
    """One boss fight's running count."""

    kind: Optional[str] = None
    defeated: int = 0
    # Toons in the WHOLE fight, both sides -- not the toons in your
    # battle. One toon on screen is a solo VP or one side of a two-player
    # one, and those meet twenty a round and ten.
    party_size: int = 1
    _dead_ids: Set[int] = field(default_factory=set)

    # -- what the fight is ------------------------------------------------

    def set_kind(self, kind: Optional[str]) -> None:
        """Name the fight, or clear it with None. Changing it restarts
        the count, because a count against the wrong structure is
        worse than none."""
        kind = kind or None
        if kind is not None and kind not in BOSS_KINDS:
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
        return rounds_for(self.kind, self.party_size)

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

    def horizon(self, on_field: int = 0) -> Optional[Horizon]:
        """Counts and level bands of everything still to come, or None
        where the current round's size or band is not known."""
        rounds, index = self.rounds(), self.round_index()
        bands = _round_bands(self.kind) if self.kind else None
        if rounds is None or index is None or bands is None:
            return None
        size, band = rounds[index], bands[index]
        if size is None or band is None:
            return None
        before = sum(rounds[:index])
        holdout = max(0, size - (self.defeated - before) - max(0, on_field))
        later = []
        for count, later_band in zip(rounds[index + 1:], bands[index + 1:]):
            if count is None or later_band is None:
                break
            later.append((count, later_band))
        return Horizon(holdout, band, tuple(later), DEPARTMENT[self.kind])

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
