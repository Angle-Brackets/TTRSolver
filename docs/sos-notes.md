# SOS Toons — what is known, and what has to be settled first

Scoping notes. Nothing is implemented yet.

## Why they matter

A solo VP at 20 cogs a round clears about 34% with unites and 0%
without. Every loss is laff running out, not gags: the losses die about
four cogs short of forty with roughly 37 usable gags in hand.

Two SOS cards dwarf anything else available for that problem. **Flippy**
heals 180 laff to a solo toon — more than three rounds of survival
against ~50 incoming a round, where an 80 Toon-Up unite buys about 1.6.
**Lil Oldman** lures every cog for six rounds.

## The shape of the problem

Roughly 28 cards, but only seven mechanical shapes, and six of them are
things the solver already does:

| shape | cards | reuses |
|---|---|---|
| heal all toons, scaled by how many are standing | 3 | `unites.apply_toon_up` |
| place a trap on every cog | 3 | `CogStatus.trapped` / `trap_level` |
| lure every cog for 4/5/6 rounds | 3 | `status.apply_lure`, already per-cog |
| damage every cog | 5 | existing group damage |
| damage every **unlured** cog | 3 | existing, plus Drop-misses-lured |
| restock 12 of one track, highest levels first | 7 | `unites.apply_gag_up`'s top-down fill |
| pink slip every cog | 1 | existing fire, applied to each target |

Plus two accuracy effects — Cogs Miss (−75% cog accuracy) and Toons Hit
(+75% gag accuracy) for a number of rounds — which are new but are
ordinary timed status effects, the same shape as a lure countdown.

## [CONFIRMED] TTR wiki (SOS Toon)

* Called at any time during a battle; 100 cards held per toon.
* Toon-Up: Madam Chuckle 60, Daffy Don 120, Flippy 180 laff to a lone
  toon, halving as more toons share it (60/30/20/15 for Chuckle).
* Lure: Stinky Ned 4 rounds, Nancy Gas 5, Lil Oldman 6 — all cogs.
* Sound: Barbara Seville 35, Sid Sonata 55, Moe Zart 75 — all cogs.
* Drop: Clumsy Ned 60, Franz Neckvein 100, Barnacle Bessie 170 — all
  **unlured** cogs.
* Restock: seven cards, one per track, "12 gags of the highest levels
  available for all Toons".
* Specials: Rocky 132 to all (Throw), Loopy Loopenloop 115 to all
  (Squirt), Lord Lowden Clear fires a pink slip at all cogs.
* **All SOS gags have perfect accuracy and cannot miss**, since the
  2.6.7 update of 12 December 2019. The sole exception is Drop against
  a lured cog. So no accuracy rolls to model for any of them.

## [OWNER, from play]

* **An SOS costs the toon's turn.** Unlike a unite, which is free, so
  an SOS is an ordinary action and belongs in the action table rather
  than in the wrapper `hybrid.climb` uses for unites.
* **The Trap cards PLACE TRAPS, they do not deal damage.** Clerk Will,
  Penny and Clara put Quicksand, Trapdoor and TNT in front of every
  cog; the damage arrives when something lures the cogs onto them. The
  wiki's "deals 60 damage to all lured Cogs" describes the outcome, not
  the mechanism.

  The numbers corroborate it. The cards are named after three real trap
  gags, which would be a strange coincidence for a direct attack:

  | | trap gag | SOS card |
  |---|---|---|
  | Quicksand | 50 | 60 |
  | Trapdoor | 85 | 120 |
  | TNT | 180 | 180 |

  So it places the named trap at SOS-tier damage — stronger than the
  real gag except TNT, which matches exactly. `CogStatus.trap_level`
  derives damage FROM the level, so modelling this needs an explicit
  trap damage instead, or three pseudo-levels.

## Unsettled — do not implement past these

1. **Does placing an SOS trap un-lure a lured cog?** The owner thinks
   so ("I think it will unlure cogs that are lured to place the SOS
   card"), reasoning that a trap cannot be laid under a sleeping cog.
   Marked uncertain because they said so. It decides whether the
   natural combo is *trap-SOS then lure* (two rounds, one action each)
   or whether the two can be stacked.
2. **Do Sound and Throw SOS wake the lured cogs they hit?**
   `mechanics.LURE_ENDS_ON_DAMAGE` says a landed attack ends a lure. If
   it applies, Moe Zart's 75 to all wakes the whole field, which is
   often a bad trade; if not, it is free damage. Same question that
   made `prevented` hard to get right.
3. **How does an SOS Toon's Toon-Up split across a party?** The table
   gives 60/30/20/15 for one to four toons, so it is not a simple
   division. Solo only needs the first column, which is all this
   project would use today.

## Rough cost

A `solver/sos.py` with a ~28-row table and seven effect functions, most
delegating to code that already exists, plus an explicit trap-damage
field and two timed accuracy effects. Comparable to the unites work:
about a day, plus measurement.
