"""SOS Toons: the cards, and what each one does to a battle.

WHY THEY MATTER. A solo VP at 20 cogs a round clears about 34% with
unites and 0% without, and every loss is laff running out rather than
gags -- the losses die about four cogs short of forty holding roughly
37 usable gags. Flippy heals 180 laff to a lone toon, more than three
rounds of survival against ~50 incoming, where the best Toon-Up unite
buys about 1.6. Lil Oldman lures the whole field for six rounds.

WHAT THE WIKI GIVES, AND WHAT IT DOES NOT. Every damage figure,
duration, heal table and restock size below is [CONFIRMED] from the SOS
Toon page. What it does not state is how the cards interact with lure
and with the party's own accuracy rolls, and those are the rules that
decide whether a card is good. They come from the owner's play and are
tagged as such.

  * AN SOS COSTS THE TOON'S TURN. Unlike a unite, which is free, so an
    SOS is an ordinary action rather than something wrapped around one.
  * AN SOS CANNOT MISS. The only failures are situational: Drop against
    a lured cog, and a Trap nothing springs.
  * ITS ACCURACY IS INDEPENDENT OF THE PARTY'S. Call Moe Zart while
    another toon throws an Elephant Trunk and the Trunk may miss while
    Moe Zart does not, though both are Sound and both hit every cog.
    See `rolls_accuracy` -- this collides with `_roll_groups`.
  * EVERYTHING BUT LURE WAKES A SLEEPER. Trap wakes because a trap
    cannot be laid under a sleeping cog; Sound, Throw and Squirt wake
    because they are attacks, which is what `LURE_ENDS_ON_DAMAGE`
    already says of ordinary gags. Drop is exempt only because it never
    lands on a sleeper at all.
  * ONLY TRAP IS A SETUP. Every other card resolves the round it is
    played; Trap places something that pays out when a lure follows.

NOT MODELLED, DELIBERATELY. Rocky (Throw 132), Loopy Loopenloop (Squirt
115) and Lord Lowden Clear (a pink slip at every cog) come from
limited-time Operation ToonTasks and are [OWNER] not renewable the way
the VP cards are. A solver that plans around a reward the player cannot
farm is planning around something that runs out and never returns.

TRAP DAMAGE IS THE CARD'S, NOT THE GAG'S. The three Trap cards are
named after real trap gags and place them, but at SOS-tier damage:

    Quicksand   gag 50   card 60
    Trapdoor    gag 85   card 120
    TNT         gag 180  card 180

`CogStatus.trap_level` derives damage FROM the level, so these carry an
explicit damage instead. TNT matching exactly is a coincidence worth
not reading anything into.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .state import Track

# [CONFIRMED] wiki: "Toons can hold up to 100 cards of each SOS Toon."
CARRY_LIMIT = 100

# What a card does, as one of six shapes. Only TRAP is a setup; the
# rest resolve immediately.
HEAL = "heal"                 # laff to every standing toon, split
TRAP = "trap"                 # place a trap on every cog
LURE = "lure"                 # lure every cog for N rounds
DAMAGE_ALL = "damage_all"     # damage every cog, lured or not
DAMAGE_UNLURED = "damage_unlured"
RESTOCK = "restock"           # 12 of one track, or 45 across all
TOONS_HIT = "toons_hit"       # +75% gag accuracy for N rounds
COGS_MISS = "cogs_miss"       # -75% cog accuracy for N rounds


@dataclass(frozen=True)
class Card:
    """One SOS Toon. `amount` means whatever `kind` says it means."""

    name: str
    tier: int
    kind: str
    amount: int
    track: Optional[Track] = None   # RESTOCK: None means every track

    @property
    def is_setup(self) -> bool:
        """Does this pay out later rather than now? Trap alone."""
        return self.kind == TRAP

    @property
    def wakes_lured(self) -> bool:
        """Does playing this end a lure on the cogs it touches?

        Everything but Lure and Drop. Drop is exempt because it never
        lands on a sleeper, not because it is gentle.
        """
        return self.kind in (TRAP, DAMAGE_ALL)


# [CONFIRMED] TTR wiki (SOS Toon). Tier is the star rating.
CARDS: Tuple[Card, ...] = (
    Card("Madam Chuckle", 3, HEAL, 60),
    Card("Daffy Don", 4, HEAL, 120),
    Card("Flippy", 5, HEAL, 180),

    Card("Clerk Will", 3, TRAP, 60),
    Card("Clerk Penny", 4, TRAP, 120),
    Card("Clerk Clara", 5, TRAP, 180),

    Card("Stinky Ned", 3, LURE, 4),
    Card("Nancy Gas", 4, LURE, 5),
    Card("Lil Oldman", 5, LURE, 6),

    Card("Barbara Seville", 3, DAMAGE_ALL, 35),
    Card("Sid Sonata", 4, DAMAGE_ALL, 55),
    Card("Moe Zart", 5, DAMAGE_ALL, 75),

    Card("Clumsy Ned", 3, DAMAGE_UNLURED, 60),
    Card("Franz Neckvein", 4, DAMAGE_UNLURED, 100),
    Card("Barnacle Bessie", 5, DAMAGE_UNLURED, 170),

    Card("Professor Guffaw", 3, RESTOCK, 12, Track.TOON_UP),
    Card("Clerk Ray", 3, RESTOCK, 12, Track.TRAP),
    Card("Doctor Drift", 3, RESTOCK, 12, Track.LURE),
    Card("Melody Wavers", 3, RESTOCK, 12, Track.SOUND),
    Card("Baker Bridget", 3, RESTOCK, 12, Track.THROW),
    Card("Sofie Squirt", 3, RESTOCK, 12, Track.SQUIRT),
    Card("Shelly Seaweed", 3, RESTOCK, 12, Track.DROP),
    Card("Professor Pete", 5, RESTOCK, 45, None),

    Card("Soggy Bottom", 3, TOONS_HIT, 3),
    Card("Soggy Nell", 4, TOONS_HIT, 4),
    Card("Sticky Lou", 5, TOONS_HIT, 5),

    Card("Flim Flam", 3, COGS_MISS, 3),
    Card("Mr. Freeze", 4, COGS_MISS, 4),
    Card("Julius Wheezer", 5, COGS_MISS, 5),
)

BY_NAME: Dict[str, Card] = {c.name: c for c in CARDS}

# [CONFIRMED] wiki, and [OWNER] excluded: limited-time Operation
# rewards, not renewable. Named so that nobody adds them back without
# reading why they are absent.
NOT_MODELLED = ("Rocky", "Loopy Loopenloop", "Lord Lowden Clear")

# [CONFIRMED] wiki: since the 2.6.7 update of 12 December 2019 no SOS
# gag misses, the sole exception being Drop against a lured cog.
ACCURACY_UPDATE = "2.6.7, 12 December 2019"

# [CONFIRMED] wiki, both directions.
ACCURACY_SWING = 75


def rolls_accuracy(card: Card) -> bool:
    """Does this card resolve on an accuracy die? Never.

    Exists so `party_search._roll_groups` has something to ask. That
    function keys a SHARED die on (track, target), deliberately, so two
    toons throwing the same track at the same cog land or miss
    together. An SOS in the plan would be dragged into that group and
    would then "miss" whenever the party's gag did -- Moe Zart failing
    because someone else's Elephant Trunk failed.

    Fires and passes are already skipped there because they never roll.
    An SOS is the third such case.
    """
    return False


def heal_share(card: Card, recipients: int) -> int:
    """Laff each recipient gets. Plain division; only the divisor differs.

        Madam Chuckle   1:60   2:30   3:20   4:15    = 60 / X
        Daffy Don       1:120  2:60   3:40   4:30    = 120 / X
        Flippy          1:180  2:90   3:60   4:45    = 180 / X

    [OWNER] The difference from a player's Toon-Up is WHO COUNTS. A
    toon cannot heal itself, so a gag splits across the others -- up to
    three of a four-toon party. An SOS Toon is the thrower, so every
    standing toon is a recipient: up to four.

    Which is why Flippy is worth so much to a solo toon while a Toon-Up
    gag is worth nothing there. Solo, the gag has zero recipients and
    does nothing at all; the SOS has one, and divides by one.
    """
    if card.kind != HEAL:
        raise ValueError(f"{card.name} is not a Toon-Up card")
    if recipients <= 0:
        return 0
    return card.amount // recipients
