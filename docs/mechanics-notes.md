# Battle mechanics as implemented

This document describes the cog battle rules that TTRSolver simulates:
the order gags resolve in, how accuracy and damage are computed, how lure
and trap work, how cogs choose attacks and targets, what the gag pouch
holds, and what ends a battle. Each rule carries the tag of its source.
It describes the code as it stands on 2026-10-11, and it records where
the implementation deliberately differs from the Open Toontown source.

The tags (`[CONFIRMED]`, `[OWNER]`, `[OPEN TOONTOWN SOURCE]`,
`[ASSUMED]`, `[TODO]`) are defined in
[data-confidence.md](data-confidence.md). In short: `[CONFIRMED]` means
read from the Toontown Rewritten (TTR) wiki, `[OWNER]` means the
maintainer's judgement as an experienced player, and `[ASSUMED]` means a
labelled guess. In the tables below, "guide" in the source column means
the rule comes from the QED1224 strategy guide's account of the Toontown
Online code and the wiki has not been found to state it; some of those
are tagged `[CONFIRMED]` in older code comments, and this document does
not repeat that tag for them.

## Terms

| Term | Meaning |
| --- | --- |
| Toon | A player's character. |
| Cog | An enemy. Cogs have a level (1 to 12 on the street, higher in some boss fights), a department (Bossbot, Lawbot, Cashbot, Sellbot) and health set by level. |
| Laff | A toon's health. A toon at zero laff goes "sad" and leaves the battle. |
| Gag | An attack or support item a toon throws. Each toon picks one per round. |
| Track | One of the seven families of gags: Toon-Up, Trap, Lure, Sound, Throw, Squirt, Drop. Each has seven levels. |
| Lure | A gag that puts a cog to sleep for a number of rounds. A lured cog does not attack. |
| Trap | A gag placed in front of a cog. It does nothing until a Lure pulls the cog onto it. |
| Knockback | The 50% damage bonus a Throw or Squirt gets against a lured cog. |
| Organic | A gag track the toon has grown gag trees for. Organic gags deal more damage or heal more; organic Lure is more accurate. |
| Group gag | A gag that affects every cog (or, for Toon-Up, every other toon) instead of one target. |
| SOS toon, unite, pink slip | Consumable rewards from boss fights. See [sos-notes.md](sos-notes.md). |
| VP | The Vice President, the Sellbot boss fight. |
| Version 2.0 cog | A cog with two layers: an outer suit and a Skelecog underneath. |

## Where the rules live

| File | Role |
| --- | --- |
| `solver/mechanics.py` | Accuracy, damage, bonuses, cog attack and target selection. |
| `solver/state.py` | The battle state, the end conditions, the layered-health rule. |
| `solver/simulator.py` | Legal actions and the resolution of a round, solo (`step`) and party (`apply_party_round`). |
| `solver/party.py` | A full party round, including the cog phase with target selection. |
| `solver/outcomes.py` | The exact enumeration of a solo round's outcomes, used by the exact search. |
| `solver/data/` | The tables. |

A round is implemented three times: sampled for one toon
(`simulator.step`), sampled for a party (`party.step`), and enumerated
exactly for one toon (`outcomes`). They share `mechanics` and the data
tables, and the toon's own action is applied by one function,
`simulator.apply_toon_action`, in the solo and exact paths.
`tools/round_parity.py` holds the three against each other on random
positions; an expected outcome that differs beyond sampling error means
one path is missing a rule. `tests/test_round_parity.py` is the small
fixed-seed version.

## Gag tracks and order of resolution

Every toon chooses an action, then the round resolves in two phases: the
toons' gags, then the cogs' attacks.

Gags resolve by track, not by who chose first:

**Toon-Up → Trap → Lure → Sound → Throw → Squirt → Drop**

| Rule | Source |
| --- | --- |
| The order above (`state.ATTACK_ORDER`) | The code cites the guide. The wiki's Gags page states the same order track by track ("Toon-Up gags are the first set of gags used during Cog battles", through "Drop gags are the seventh"). |
| Gags of one track resolve together, so same-track gags chosen independently can combine | Follows from the order; implemented in `simulator.apply_party_round`. |
| A pink slip resolves before any gag in a party round | `[ASSUMED]`. No source states when the cannon fires. |
| An SOS card resolves before any gag in a party round | `[ASSUMED]`. No source states it. |

The order has consequences the search relies on. A Trap placed this round
is already down when this round's Lure resolves. A Lure that lands before
a Throw makes the Throw a guaranteed hit with knockback. A Sound that
lands wakes a lured cog before a Drop reaches it.

Which gags are group gags (`simulator.is_group_action`, `[CONFIRMED]`):
every Sound gag; Lure and Toon-Up at levels 2, 4, 6 and 7; Trap, Throw,
Squirt and Drop at level 7 only.

## Accuracy

### The formula

`atkAcc = propAcc + trackExp + tgtDef + bonus`, floored at 5, capped at
95, then compared against a roll of 0 to 99. The gag hits if the roll is
below `atkAcc`.

| Term | Meaning | Source |
| --- | --- | --- |
| `propAcc` | The gag's base accuracy. Flat within a track except Lure (60/55/70/65/80/75/90 by level) and Toon-Up (70, and 95 at level 7). Throw 75, Squirt 95, Sound 95, Drop 50. Organic Lure is 10 higher. | `[CONFIRMED]` |
| `trackExp` | (highest gag level unlocked in the track − 1) × 10, so 0 to 60. Set by the toon's training, not by the gag thrown. Halved for Toon-Up. | `[CONFIRMED]` |
| `tgtDef` | A penalty from the cog's level, from −2 at level 1 to −55 at level 12. For a group gag, the highest-level target's value is used. | `[CONFIRMED]` for levels 1–12 and 20; `[ASSUMED]` for 13–19 |
| `bonus` | The stun bonus plus the luredRatio bonus, below. | `[CONFIRMED]` |
| Floor of 5 | Applied to everything except the forced outcomes below. | `[CONFIRMED]` |
| Cap of 95 | A hard cap in the solver. In TTR since 4.3.3 it is a soft cap that bonuses can "slightly" exceed; the wiki gives no number, so the solver does not model the excess. | `[CONFIRMED]` as a value; the soft part is not modelled |

A worked example: a toon with Throw fully trained throws at a level 12
cog. 75 + 60 − 55 = 80.

### `calc_tgt_def` — the rank-1 branch bug

`tgtDef` depends on the cog's rank as well as its level. The wiki's table
marks levels 4 and 5 with a second value used by rank-1 cogs (Flunky,
Bottom Feeder, Short Change, Cold Caller): −12 and −15, against −15 and
−20 for every other cog. Rank is the lowest level a cog type appears at.

The code once took the rank-1 value for every cog, which understated the
defence of every other cog at those two levels by 3 and 5 points. A
level 4 Micromanager was scored at −12 and should have been −15.
`mechanics.calc_tgt_def` now passes the rank to `data.tgt_def`.

### Outcomes that are stated, not computed

`mechanics.forced_accuracy` returns these directly. Nothing adjusts them
afterwards: not the stun bonus, not the floor, not the cap.

| Case | Result | Source |
| --- | --- | --- |
| Any Trap gag | Always hits | `[CONFIRMED]` |
| Throw or Squirt when every target is lured | Always hits | `[CONFIRMED]` |
| Drop when every target is lured | Always misses | `[CONFIRMED]` |
| A group gag over a mix of lured and unlured cogs | Rolled normally. A group Drop that hits still skips the lured cogs. | `[CONFIRMED]` |
| A pink slip or an SOS card | Cannot miss, no roll | Pink slip `[OWNER]`; SOS `[CONFIRMED]` |

The party round once kept its own copy of this decision and got it wrong
three ways: it added the stun bonus to the forced number and then capped
the sum, which gave an always-hit Trap a 5% miss, gave a guaranteed Throw
a 5% miss, and let a Drop land on a lured cog when something else had hit
earlier in the round. Solo play was right throughout. That is why the
decision is one function.

### The `bonus` term

**luredRatio** (`[CONFIRMED]`): `(lured cogs / all live cogs) × 100`,
added to the accuracy of every Sound gag and of level 7 Throw and Squirt.
It is read from the battle's current lure state, so a solo toon gets it.
The guide's rule was wider and wrong: it gave the bonus to every track
except Lure, Toon-Up and Drop. A ratio that is not a whole number is
truncated; no source says how it rounds, and the difference is at most
one point.

**The stun bonus, or PrevHits** (`[CONFIRMED]`): each attack that has
already landed this round adds 25 to a later attack's accuracy, up to 75.
The earlier attack must be a different track and not Trap, and either
attack must be a group gag or the two must share a target. A solo toon
acts once per round and never earns this. The guide's 20 and 60 are the
Toontown Online values.

**Trap's bonus to Lure** (`[CONFIRMED]`): while a trap is in front of any
live cog, a Lure gets +10. A group Lure gets a further +5 for each
additional trapped cog. This persists across rounds, so a solo toon who
traps one round and lures the next collects it. The solver once treated
the whole `bonus` term as zero for a solo toon and rolled that common
line 10 points short.

**Not modelled:** the wiki's +50 stun for attacks that land after a Lure
activates a Trap in the same round (`data.TRAP_ACTIVATION_PREV_HITS` is
recorded and unused).

**Toons Hit**, the SOS effect, multiplies accuracy by 1.75 before the
cap. See [sos-notes.md](sos-notes.md).

### Accuracy is rolled per track per target, not per gag

In a party round, gags of the same track aimed at the same cog share one
roll. They all land or all miss together. A group gag rolls once for the
whole battle, and all group gags of one track share that roll. The gag
with the best accuracy among those sharing a roll sets the number.

This matters for strategy. If each gag rolled separately, four Throws at
one cog would almost certainly land something, and a party could hedge by
stacking a track. That is not how the game resolves, and modelling it
that way badly overvalues stacking.

`simulator.apply_party_round` keys the roll on (track, target).
`mechanics.accuracy_roll` returns the number rolled instead of a verdict,
because the verdict can differ per gag while the die does not.

Sources: the code and the maintainer's notes state the shared roll as the
game's behaviour without a source tag. For Lure specifically, the rule
that the strongest gag sets the accuracy is `[CONFIRMED]` by the wiki's
4.0.0 notes: "High-level Lure gags override the base accuracy of
low-level Lure gags when used simultaneously."

SOS cards, pink slips and passes never roll and are outside this
grouping. An SOS card that deals Sound damage does not share a roll with
a teammate's Sound gag.

<a id="multi_lure_accuracy_bonus--the-one-assumed-value"></a>

### `MULTI_LURE_ACCURACY_BONUS` — the best-documented [ASSUMED] value

Code comments link to this section under its older title, "the one
assumed value". It is no longer the only one; the full list is in
[data-confidence.md](data-confidence.md#everything-that-is-assumed).

Several Lure gags thrown in the same round raise each other's accuracy.

| Part of the rule | Status |
| --- | --- |
| The bonus exists. Wiki, Lure page: "Using multiple Lure gags simultaneously increases the accuracy." | `[CONFIRMED]` |
| Its values are 20, 15 and 10, "depending on the gag level discrepancies of the additional Lure gags, with the bonus being smaller if low-level Lure gags are used" (TTR 4.0.0 notes). | `[CONFIRMED]` |
| Which pairs qualify: two group Lures, or two single-target Lures (the Dollar Bills). One of each earns nothing. `mechanics.multi_lure_eligible`. | `[CONFIRMED]` |
| Which level gap selects which value: gap 0 gives 20, gap 1 gives 15, gap 2 or more gives 10. | `[ASSUMED]` |

The assumed part is the bucket boundaries. The patch notes say the gap
indexes the bonus and that low-level Lures earn less; a wide gap is the
low-level case, so the three values were mapped onto gaps in order, with
the maintainer's authorisation after reading the notes. No source states
the boundaries.

The gap is measured between the highest Lure and the next highest. The
bonus is added to the shared roll and the total is capped at 95. With the
table as it stands, two fully trained level 6 Lures against a level 12
cog go from 80 to 95.

What would settle it: throwing two group Lures at known levels and
recording hit rates over enough trials to separate 20 from 15 from 10. If
a measurement contradicts the table, the table changes and nothing else
does.

Sources already checked, so nobody repeats the search: the wiki's
Accuracy page names a "Lure bonus" and gives no formula; the two
rebalancing documents the wiki cites are images, not text; and Open
Toontown cannot help, because this bonus was added in TTR 4.0.0 and
postdates Toontown Online.

History: the party search once refused any plan with two Lures, by
analogy with the two-Traps rule. That made a real TTR play unreachable
and was removed. For a time a comment also claimed the bonus was not
modelled at all, and [party-strategy.md](party-strategy.md) used that
claim to explain away a measurement. The bonus is modelled; only its size
is assumed.

## Damage

### Base damage

Each gag has a damage range from the wiki. Where a toon sits in the range
depends, in the game, on skill points earned in the track.

The solver does not track skill points. It uses one global setting,
`mechanics.DAMAGE_TRAINED_FRACTION`, which defaults to 1.0: every toon
deals the top of the range. That makes gag damage deterministic. All the
variance in the toons' half of a round is accuracy.

The setting exists as a knob so a search can be re-run at a pessimistic
value to ask how much a recommendation depends on everyone being fully
trained. [party-strategy.md](party-strategy.md#the-safety-margin) uses it
that way. The real formula (`mechanics.gag_damage_from_exp`) and its
thresholds are transcribed and deliberately not wired in.

A trap's damage, when it is sprung, is always the top of the trap gag's
range and does not follow the knob.

### Bonuses

| Bonus | Rule | Source |
| --- | --- | --- |
| Organic | The gag's own organic value from the table. Organic status can be per level: trees are planted in level order, so levels 1 to N of a track are organic. | `[CONFIRMED]` |
| Same-track bonus (`calc_hp_bonus`) | When two or more gags of the same track land on one cog in one round, their damage is summed and 20% of the sum is added. Lure, Trap and Toon-Up are excluded. | `[CONFIRMED]` for the bonus |
| The same-track bonus is per cog | It counts the gags of one track landing on that cog. A group Geyser (105) plus a single Storm Cloud (80) on one cog gives that cog 185 plus 20%; the other cogs the Geyser hit take 105 with no bonus. | `[OWNER]` |
| Rounding of the same-track bonus | Rounded up. The wiki does not say how it rounds; rounding up is the guide's convention. | Guide |
| Knockback (`calc_kb_bonus`) | A Throw or Squirt that lands on a lured cog deals 50% more. | `[CONFIRMED]` |

Order and rounding, as implemented. In a party round the track's damage
on a cog is summed, the same-track bonus is added to the sum, and
knockback is 50% of that combined figure, rounded down. In the solo path
there is one gag, so the total is the gag's damage plus 50% for
knockback, rounded down.

The per-cog reading is what makes coordinating a party worth anything.
Before parties were modelled, the same-track bonus returned zero
unconditionally, and a search could not tell four toons stacking Throw on
one cog from four toons hitting four different cogs.

### Toon-Up

| Rule | Source |
| --- | --- |
| A toon cannot heal itself. A Toon-Up heals other toons only. Solo, the gag is spent and heals nothing. | `[CONFIRMED]` |
| A Toon-Up that "misses" still heals 20% of its value, rounded up. | `[CONFIRMED]` |
| A group Toon-Up is divided evenly among the toons being healed. The thrower is not a recipient, so in a four-toon party it is three shares. | Even division `[CONFIRMED]`; who counts `[OWNER]` |
| Healing is applied and capped at maximum laff before the cogs' damage is taken off. | Follows from the order of resolution |

A known gap: the party path computes the heal without the organic flag,
so an organic Toon-Up heals its base value there.

### Version 2.0 cogs

A Version 2.0 cog is an outer suit and a Skelecog, each with the health
of a normal cog of that level (`[CONFIRMED]`). A hit that destroys the
suit does not carry its excess into the Skelecog: TTR removed carryover
damage in 3.0.0 (`[CONFIRMED]`). A 180-damage gag into a 90-health suit
wastes 90. A pink slip removes both layers (`[CONFIRMED]`).

`CogState.take_damage` reports the full amount thrown, not the part that
fitted, because every scorer reads its return value as damage dealt.
Charging for overkill is left to the scorers.

## Lure

| Rule | Source |
| --- | --- |
| Duration by gag level: 2, 2, 3, 3, 4, 4, 8 rounds. A lured cog skips that many of its own attack phases, counting the round the Lure is thrown. | `[CONFIRMED]` |
| A cog whose lure runs out attacks in that same round. | Guide |
| Re-luring a lured cog does nothing. It neither extends the lure nor restarts it. | No stacking is `[CONFIRMED]` (TTR 3.0.0 removed it). No refresh across rounds is `[OWNER]`; the wiki is silent. |
| A lure does not expire early. TTR 3.3.0 limited early expiry to Lure gags with base accuracy under 50%, and the lowest in the game is 55. | `[CONFIRMED]` |
| Any attack from a damage track (Sound, Throw, Squirt, Drop) that lands on a lured cog wakes it. Knockback is applied first, then the lure ends. If the cog survives, it attacks that round. | Sound waking a cog without a bonus is `[CONFIRMED]`. The same for Throw and Squirt is `[OWNER]` (`mechanics.LURE_ENDS_ON_DAMAGE`). |
| Drop never wakes a lured cog, because it never lands on one. | `[CONFIRMED]` |
| Two Lures on one cog in the same round are one effect. The stronger gag sets the duration. | `[OWNER]` |

**The in-game tooltip shows one more round than the table.** The tooltip
for Hypno-goggles says 5 rounds, Big Magnet 4, Presentation 9. It counts
the round the Lure is thrown in. The badge shown during battle does not,
and matches the table. The solver's count was checked two ways: the
simulator skips exactly the table's number of attack phases, and a
recorded solo VP with Hypno-goggles on four cogs held laff flat for four
rounds and dropped on the fifth.

**The wake-up roll is kept and unreachable.** The Toontown Online rule,
from the guide, is that each round a lured cog may wake with chance
`100 − 2 × accuracy`, where the accuracy is the Lure's value before any
bonus and before the cap. The code stores that value on the cog
(`CogStatus.lure_acc_before_bonus`) and keeps the roll behind
`mechanics.lure_can_expire_early`, because the 50% threshold is a
balance setting a future patch could move. Today the roll never happens.

**Why "any attack wakes a cog" mattered.** For a time only Sound cleared
a lure in the model, on the reading that the wiki names Sound explicitly.
The wiki naming one track is not the wiki excluding the others. With the
gap open, a lure was credited for rounds it would not deliver once
anyone hit the cog, and lure-then-grind lines looked much stronger than
they play.

## Trap

| Rule | Source |
| --- | --- |
| A trap sits in front of a cog until a Lure lands on that cog. It then deals its damage. | The basic rule; the code attaches no tag to it. The wiki's Trap page is the source for the trap values. |
| The cog that springs a trap takes the damage and is not left lured. Springing the trap spends the lure. | `[OWNER]` |
| A trap is not removed when its cog is damaged by something else. | Guide |
| A single-target Trap cannot be placed on a cog that is already trapped or lured. | Stated in the code without a wiki citation; the lured case is repeated in an `[OWNER]` note. |
| Two single-target Traps thrown at one cog in the same round cancel. Neither is placed and both gags are spent. | `[OWNER]` |
| A Railroad (level 7, group) overrides traps already placed. | `[CONFIRMED]` (TTR 3.0.0) |
| A Railroad needs one unlured cog to be placed. Placing it wakes every lured cog and lays the trap under all of them. With every cog lured it cannot be thrown. | `[OWNER]` |

Because Trap resolves before Lure, a Railroad and a Lure work in one
round: the Railroad wakes and arms the field, and the Lure springs it.

Trap damage is not just "chance of springing × damage" for the search.
The lure given up when the trap goes off is part of the cost.

## The cog phase

After the gags, every live cog that is not held by a lure attacks once.

### Which attack

`mechanics.pick_cog_attack` samples one of the cog's attacks by its
frequency at that level. The attack then hits with its accuracy at that
level. Damage is a fixed number per attack and level.

Attack damage and the roster are `[CONFIRMED]`. Frequency and accuracy
are the least certain numbers in the project: unverified Toontown Online
values for most attacks, and `[ASSUMED]` for the twelve attacks TTR added
in 4.0.0. See
[data-confidence.md](data-confidence.md#cog-attacks-bossbotpy-sellbotpy-cashbotpy-lawbotpy).

A missing cell raises `NotImplementedError` naming the cog, attack and
level. One remains: The Big Cheese's Glower Power accuracy.

### `pick_cog_target`

This is the project's worked example of how a rule is built when the
wiki gives a direction and no numbers.

**What the wiki says** (`[CONFIRMED]`, direction only): "It is more
likely that a Cog's single attack may target a Toon whose gags dealt the
most damage to them, though this may not always be the case."

**What Open Toontown supplies** (`[OPEN TOONTOWN SOURCE]`):
`BattleCalculatorAI.__calcSuitTarget` rolls 0 to 99; below 75, and if
anyone has damaged this cog, it picks among those toons in proportion to
the damage each dealt; otherwise it picks uniformly among the toons
still standing. The solver implements that
(`mechanics.REVENGE_CHANCE = 75`). The wiki corroborates the shape and
none of the numbers. It is Toontown Online code, so it is a lead, not
TTR.

**Three things in that source that are not copied.** What is implemented
is what the code evidently means.

1. *A dictionary replaced by a list.* `__rememberToonAttack` records
   damage per toon in a dictionary. When a toon's later hit is at least
   as large as their earlier one, it assigns
   `self.SuitAttackers[suitId] = [toonId, damage]`, replacing the
   dictionary with a two-element list, which the selector then cannot
   read as a dictionary. The solver accumulates each toon's damage
   instead.
2. *The weights.* Each toon's weight is
   `damage / totalDamage * 100`. In the original Python 2 code, with
   whole-number damage, that division rounds down to zero for anyone who
   did not deal all of the damage, and selection would fall through to a
   uniform pick. The current Open Toontown branch runs on Python 3, where
   the same line divides normally. The operand types in the original were
   inferred from the arithmetic, not traced, so this is a probable bug
   and not an established one. The solver does the division in floating
   point.
3. *The memory window.* Open Toontown sets `CLEAR_SUIT_ATTACKERS = 1`
   and empties the damage record at the start of every round, so a cog
   there forgets who hurt it when the round ends. `[OWNER]`: that is a
   Toontown Online bug, not a rule; a cog remembers who has been hitting
   it for the whole fight. `CogStatus.damage_by_toon` accumulates and is
   never reset. The wiki names no memory window, so it settles nothing
   either way, and between an `[OPEN TOONTOWN SOURCE]` reading and the
   maintainer's play knowledge, the maintainer's wins.

If the solver's targeting is ever compared with observed play and
disagrees, these three points are where to start. Anyone diffing the
solver against the source will see the third as a missing reset. It is
deliberate.

**A related belief, checked.** The question that led to the third point
was whether passing repeatedly in front of cogs lowers their accuracy.
Nothing in the Open Toontown source does that. It counts how often each
toon has been attacked (`suitAtkStats`), and that count is read only by
a debug logger. What is real is the damage-weighted targeting above.

### Group cog attacks

Some cog attacks hit every toon in the battle. `data.GROUP_ATTACKS` lists
the 14 that do, `[CONFIRMED]` from the wiki's "Group Cog attacks"
category. The companion category, "Single Cog attacks", has 54. Together
they cover all 68 attack names in the tables with nothing left over, so
no attack's targeting is guessed.

Being a group attack is a property of the attack, not of the cog using
it. In a party round a group attack makes one accuracy roll and, if it
hits, damages every standing toon (`party._party_cog_phase`). A
single-target attack goes through `pick_cog_target`.

Solo, the distinction changes nothing: the one toon is both the target
and the group.

### Teammates the solver cannot see

On a live TTR battle the solver knows how many teammates are present but
not what they hold, so they are a count (`BattleState.allies_standing`),
not entries in the list of toons. The count does one thing: a
single-target cog attack lands on the advised toon with probability
`1 / (1 + allies)` (`BattleState.your_target_share`). Group attacks are
not diluted.

That share is uniform, where `pick_cog_target` is not. Uniform is what
the weighted rule comes to when everyone deals damage at similar rates.
It is optimistic in one known case: if the advised toon alone has
damaged a cog, that cog's attacks concentrate on them, and the real
share is nearer 0.75 than 0.25. The model cannot see that, because
nothing reports each teammate's damage.

### Cogs waiting to join

At most four cogs are on the field. Where a fight holds more, the rest
wait (`BattleState.holdout`) and walk into freed slots at the end of the
round (`facility.reinforce`). That cogs join is `[CONFIRMED]`; that a
freed slot is filled at once is `[ASSUMED]`.

## The gag pouch

| Rule | Source |
| --- | --- |
| A toon trains at most six of the seven tracks. | `[CONFIRMED]` |
| The pouch holds 20 to 80 gags in total, by upgrade. | `[CONFIRMED]` |
| Each gag has its own carry limit, which rises as later gags in the track are unlocked. | Endpoints `[CONFIRMED]`; the steps in between `[OPEN TOONTOWN SOURCE]` |
| Level 7 gags do not count against the pouch (`POUCH_EXEMPT_LEVEL`). A toon carries one of each. | `[CONFIRMED]`, and observed |
| Nothing restocks the pouch during a fight except a Gag-Up unite or a restock SOS card. | See [sos-notes.md](sos-notes.md) |

The level 7 exemption was confirmed three ways: the wiki gives level 7
gags their own limit, a live gag menu holding 75 gags displayed "Total
gags 70 / 70" with five level 7s making up the difference, and the
maintainer confirmed it. Counting them had been rejecting legal
loadouts.

The exemption gives the screen reader a free checksum: the gag menu's
"Total gags" label counts levels 1 to 6 only, so it can be compared with
the counts read off the individual cells. The live-reading docs cover
how that is used.

`state.ALLOW_LEVEL_7` can be set to `False` to forbid level 7 gags
entirely. Both `simulator.legal_actions` and
`BattleState.can_still_damage` read it, and they must agree, or a toon
holding only level 7 gags would be judged able to fight while having
nothing legal to throw.

## What ends a battle

Three things end a battle (`BattleState.is_terminal`).

1. **Every toon is sad.** A sad toon leaves the battle; the fight
   continues without them. In a party, the battle is lost only when all
   toons are at zero laff.
2. **Every cog is defeated**, with none waiting to join. This is the win.
3. **No toon has any remaining way to damage a cog**
   (`BattleState.can_still_damage`). This is a loss, as final as the
   first.

The third is easy to overlook. Its cases:

| Position | Verdict |
| --- | --- |
| Lure gags only, however many | Lost. Nothing can deal damage. |
| Toon-Up and Trap only | Lost. The trap can never be sprung. |
| A gag in a track the toon has no training in | Does not count. |
| Trap and Lure | Not lost, even if every cog is currently lured and the Trap cannot be placed this round. |
| Lure only, with a cog already trapped | Not lost. The Lure springs the trap. |
| No attack gags, but a pink slip in hand | Not lost. |
| No attack gags, but a damage or restock SOS card, or a Gag-Up unite for an attack track | Not lost. A Trap card counts only if someone holds a Lure. |
| Only heals, Lure or Toon-Up restocks, Cogs Miss or Toons Hit in hand | Lost. None of them can take health off a cog. |

In a party the test pools the gags of every standing toon. Eighty Lures
and no attacks loses solo and is a workable support pouch in a party. A
sad toon's gags do not count.

Before this condition existed, a hopeless position fell through to the
search's heuristic and scored +47.6. Because the evaluator's training
labels came from the exact search, it was partly fitted to that mistake.
Any new way for a position to have no useful moves needs a value here.

### The pass

A toon may pass (`Action(track=None)`). It is offered:

- whenever any cog is lured, at no cost, because the lure's remaining
  rounds are already counting down; and
- otherwise while `BattleState.free_passes` lasts. The default is 3, and
  an unlured pass spends one.

The budget is a termination guard for the exact search, not a rule of
the game. The exact search needs every round to reduce some measure
(gags left, lure rounds left, passes left), or it could pass forever.

The pass keeps the third end condition honest: with Trap and Lure in
hand and every cog already lured, there is nothing useful to throw, and
the winning line is to wait for the lure to lapse, then trap and lure
again. `tests/test_pass.py` plays that out.

When any other action does something, `legal_actions` first drops the
moves that provably do nothing (a Lure with no unlured target, a Drop or
a Trap with no unlured target, a Toon-Up with nobody to heal). A lone
toon's Playout menu offers the pass only when nothing else is productive.
In a party, passing is how one toon conserves gags while a teammate
covers (`[OWNER]`).

Two comments in the code are out of date on this: one in `state.py` says
the pass budget is unused, and the `legal_actions` docstring says it
starts at 12.

## Differences from the Open Toontown source and the guide

| Topic | Open Toontown or guide | What the solver does | Basis |
| --- | --- | --- | --- |
| Cog target memory | Cleared every round | Kept for the whole fight | `[OWNER]` |
| Damage record | Dictionary overwritten by a list | Accumulates per toon | Implements the evident intent |
| Target weights | Probably integer division in the Python 2 original | Floating point | Implements the evident intent |
| Same-track damage bonus | Applied to every cog a group gag touched when two same-track gags were used in the round (as the code comment describes Toontown Online) | Per cog | `[OWNER]` |
| Knockback bonus indexing | The guide documents a long-standing bug that applies the bonus to the cog at the wrong index | Not reproduced | It is a bug, and TTR may have fixed it |
| Stun bonus size | 20 per hit, 60 maximum | 25 and 75 | `[CONFIRMED]` |
| luredRatio | Every track except Lure, Toon-Up and Drop | Sound and level 7 Throw and Squirt only | `[CONFIRMED]` |
| Lure durations, accuracy, group levels | Toontown Online values | TTR values | `[CONFIRMED]` |
| Early lure expiry | Rolled every round | Unreachable since TTR 3.3.0 | `[CONFIRMED]` |
| Carry limits | `CarryLimits` table | Used, with Sound on its own lower table | `[OPEN TOONTOWN SOURCE]`, wiki corroborates the endpoints |
| CEO first battle | Every cog is Version 2.0 | 20% are | `[ASSUMED]` from the maintainer's play |
| CEO second battle | Opens with two level 12 Big Cheeses | One at level 14 | `[CONFIRMED]` |

## Known gaps

- Cog attack frequency and accuracy are unverified for TTR.
- Gag damage assumes full training.
- The 95 cap is modelled as hard.
- The +50 stun after a Lure activates a Trap is not modelled.
- Cogs above their normal level range are not modelled, except three
  Bossbot cogs for the CEO fight.
- Organic Toon-Up is not applied in the party path.
- The party search, the evaluator's party features and the pickup
  teammate model are untested against real play. See
  [party-strategy.md](party-strategy.md).
