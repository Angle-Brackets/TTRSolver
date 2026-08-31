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

25 renewable cards, but only six mechanical shapes, and five of them
are things the solver already does:

| shape | cards | reuses |
|---|---|---|
| heal all toons, scaled by how many are standing | 3 | `unites.apply_toon_up` |
| place a trap on every cog | 3 | `CogStatus.trapped` / `trap_level` |
| lure every cog for 4/5/6 rounds | 3 | `status.apply_lure`, already per-cog |
| damage every cog | 3 | existing group damage |
| damage every **unlured** cog | 3 | existing, plus Drop-misses-lured |
| restock 12 of one track, highest levels first | 7 | `unites.apply_gag_up`'s top-down fill |
| pink slip every cog | — | excluded, see below |

Plus two accuracy effects — Cogs Miss (−75% cog accuracy) and Toons Hit
(+75% gag accuracy) for a number of rounds.

**Model these as timed status effects, which is [OWNER] how TTR itself
does it** — the same shape as a lure countdown, and the wiki lists them
beside Lured and Trapped on the Status effects page rather than as
special cases. So the right home is `CogStatus` / a toon-side
equivalent with a round counter, not a bag of special rules in the
scorer.

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
* **Only the Trap cards are delayed. Everything else hits at once.**
  Sound, Throw, Squirt and Drop deal their damage immediately when the
  card is played; Trap places something that pays out later. So the
  seven shapes split into "an attack" and "a setup", and only the
  setup needs a second round to be worth anything.
* **Drop SOS always misses a lured cog**, and hits every unlured one
  immediately. That is the wiki's sole stated exception to SOS gags
  never missing, and the owner confirms it from play, so the wake
  question above simply does not arise for Drop: it never touches a
  sleeping cog.
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

## Everything wakes a sleeper [OWNER, from play]

Both questions that were open here are settled, and they settle the
same way:

* **Placing an SOS trap un-lures the cogs it is placed on.** A trap
  cannot be laid under a sleeping cog. So Clerk Clara into a lured
  field wakes it and leaves TNT on the floor, and the combo is
  necessarily *trap first, lure second* -- two rounds, one action each.
  It cannot be stacked onto an existing lure.
* **Sound, Throw and Squirt SOS un-lure too, because they are
  attacks.** Exactly what `mechanics.LURE_ENDS_ON_DAMAGE` already says
  about ordinary gags, so no new rule is needed -- Moe Zart's 75 to all
  wakes the whole field, and that is usually a bad trade rather than
  free damage.
* Drop is the one that cannot, since it never lands on a sleeper.

So the only SOS that leaves a lure intact is another Lure, and the only
SOS that is a setup rather than an attack is Trap.

## Not modelled: the three specials

Rocky (Throw 132), Loopy Loopenloop (Squirt 115) and Lord Lowden Clear
(pink slip to all) are **[OWNER] excluded on purpose**. They come from
limited-time ToonTasks during Operation: Storm Sellbot and the other
Operations, and are not renewable the way the VP cards are. Modelling a
reward the player cannot farm would let the solver plan around
something that runs out and never comes back.

That leaves 25 cards, all earned by rescuing SOS Toons after a VP.

## The Toon-Up split, settled — and it reuses what exists

It IS a simple division; the table only looked irregular because the
divisor differs from a gag's.

    Madam Chuckle   1:60   2:30   3:20   4:15     = 60 / X
    Daffy Don       1:120  2:60   3:40   4:30     = 120 / X
    Flippy          1:180  2:90   3:60   4:45     = 180 / X

[OWNER] The difference from a player's Toon-Up is WHO COUNTS. A toon
cannot heal itself, so a gag splits across `len(others)` -- up to three
in a four-toon party. An SOS Toon is the one throwing, so every
standing toon is a recipient: up to four.

`simulator` already does this, in the group Toon-Up branch:

    others = [i for i, other in enumerate(state.toons)
              if i != toon_index and other.laff > 0]
    share = amount // len(others)

An SOS heal is the same line with the recipient list built to INCLUDE
the caller. Nothing else changes.

It also explains why Flippy is worth so much to a solo toon while a
Toon-Up gag is worth nothing there. Solo, the gag has zero recipients
and does nothing at all; the SOS has one recipient and so divides by
one -- the full 180.

Nothing in this file is unsettled now.

## Rough cost

A `solver/sos.py` with a ~28-row table and seven effect functions, most
delegating to code that already exists, plus an explicit trap-damage
field and two timed accuracy effects. Comparable to the unites work:
about a day, plus measurement.
