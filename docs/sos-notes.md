# SOS toons, unites and pink slips

This document covers the three consumables a toon can bring into a cog
battle: what is known about each, what TTRSolver models today, what it
does not, and what differs on Toontown Realms. All three are implemented
in the simulator and can be advised by the engines, but on Toontown
Rewritten (TTR) the live readers see only part of what a toon holds, so
SOS cards in particular cannot be advised on a live TTR battle yet. It
describes the code as it stands on 2026-10-11.

The source tags used below are defined in
[data-confidence.md](data-confidence.md). The battle rules these
consumables interact with (lure, trap, accuracy rolls) are in
[mechanics-notes.md](mechanics-notes.md).

## What they are

| Consumable | What it is | Where it comes from |
| --- | --- | --- |
| SOS toon (or SOS card) | A card that calls a non-player toon into the battle for one powerful effect: a heal, a lure, damage to every cog, a restock. | Rescuing toons after defeating the VP (the Vice President, the Sellbot boss). |
| Unite | A SpeedChat phrase that restores laff (a toon's health) or restocks gags. | Defeating the CFO, the Cashbot boss. `[CONFIRMED]` |
| Pink slip | Fires one cog out of the battle with a cannon. | The CEO, the Bossbot boss. |

All three are scarce: each comes from a whole boss run. The solver treats
spending one as the player's decision. Every budget defaults to zero, so
nothing is advised until the player says how many they are willing to
spend.

## Why they matter

In the simulator, a solo VP is decided by laff, not by gags. Losing runs
end with most of the gag pouch unthrown. An early measurement with the
one-round engine, recorded in `solver/vp.py` (solo VP at 20 cogs a round,
12 runs per cell):

| Carrying | Cleared | Laff left | Gags left |
| --- | --- | --- | --- |
| Nothing | 0.0% | 0.0 | 64.0 |
| Unites | 8.3% | 5.2 | 64.2 |
| SOS cards | 33.3% | 37.1 | 60.8 |

The later Playout engine, given the maintainer's pouch and five unites,
won 94 of 100 simulated solo VPs and 55 of 60 two-player VP sides. These
are simulation results. They show that the consumables decide the fight
in the model; they are not a claim about win rates in the game.

## SOS toons

### What is known

| Fact | Source |
| --- | --- |
| A toon holds up to 100 of each card. | `[CONFIRMED]` |
| Every value in the table below: heals, damage, durations, restock sizes, star tier. | `[CONFIRMED]` (wiki, SOS Toon page) |
| No SOS gag can miss, since TTR 2.6.7 (12 December 2019). The one exception is Drop against a lured cog. | `[CONFIRMED]` |
| Toons Hit raises gag accuracy by 75% and Cogs Miss lowers cog accuracy by 75%, for 3, 4 or 5 rounds by tier. | `[CONFIRMED]` |
| Calling an SOS costs the toon's turn. | `[OWNER]` |
| An SOS does not share an accuracy roll with the party's gags. If Moe Zart is called while a teammate throws an Elephant Trunk, the Trunk can miss and Moe Zart cannot. | `[OWNER]` |
| Everything except Trap resolves at once. A Trap card places traps that pay out when a later Lure lands. | `[OWNER]` |
| A Trap card places the named trap; it does not deal damage directly. Placing it wakes any lured cog, because a trap cannot be laid under a sleeping cog. | `[OWNER]` |
| Sound, Throw and Squirt cards wake lured cogs, as ordinary attacks do. | `[OWNER]` |
| A heal card is divided among every standing toon, the caller included. | Values `[CONFIRMED]`; who counts `[OWNER]` |
| A restock card fills the highest gag levels first, and a restock of all tracks is spread evenly across tracks. | `[OWNER]` |

### The cards (`solver/sos.py`)

Twenty-nine cards, in eight kinds.

| Kind | Cards (3, 4 and 5 stars) | Effect as modelled |
| --- | --- | --- |
| Heal | Madam Chuckle 60, Daffy Don 120, Flippy 180 | The amount divided by the number of standing toons, to each, capped at maximum laff. Solo: the full amount. |
| Trap | Clerk Will 60, Clerk Penny 120, Clerk Clara 180 | A trap of that damage in front of every live cog. Lured cogs are woken. |
| Lure | Stinky Ned 4, Nancy Gas 5, Lil Oldman 6 | Every live cog lured for that many rounds. |
| Damage to all | Barbara Seville 35, Sid Sonata 55, Moe Zart 75 | That damage to every live cog. Lured cogs are woken, with no knockback bonus. |
| Damage to unlured | Clumsy Ned 60, Franz Neckvein 100, Barnacle Bessie 170 | That damage to every cog that is not lured. Lured cogs are untouched and stay lured. |
| Restock, one track | Professor Guffaw (Toon-Up), Clerk Ray (Trap), Doctor Drift (Lure), Melody Wavers (Sound), Baker Bridget (Throw), Sofie Squirt (Squirt), Shelly Seaweed (Drop); all 3 stars | Up to 12 gags of that track to every standing toon. |
| Restock, all tracks | Professor Pete (5 stars) | Up to 45 gags across every track the toon has, to every standing toon. |
| Toons Hit | Soggy Bottom 3, Soggy Nell 4, Sticky Lou 5 | Gag accuracy × 1.75 for that many rounds, applied before the 95 cap. |
| Cogs Miss | Flim Flam 3, Mr. Freeze 4, Julius Wheezer 5 | Cog attack accuracy × 0.25 for that many rounds. |

Details of the model:

- **An SOS is an ordinary action.** `Action(sos=name)` takes the toon's
  turn in place of a gag. `simulator.legal_actions` offers one action per
  card held and known.
- **Trap cards carry their own damage.** The three are named after trap
  gags but hit harder than two of them: Quicksand is 50 as a gag and 60
  as a card, Trapdoor 85 and 120, TNT 180 and 180. The damage is stored
  on the cog (`CogStatus.trap_damage`) because a gag level cannot express
  it. The combination with a lure is therefore trap first, lure second,
  over two rounds.
- **A Lure card follows the ordinary lure rules.** It does nothing to a
  cog that is already lured, and it cannot expire early.
- **Restocks are bounded four ways**: the card's budget, each gag's own
  carry limit, what the pouch can still hold, and level 6 at most. Level
  7 gags are never restocked. `unites.restock_pouch` is the one
  implementation, shared with the Gag-Up unite.
- **Toons Hit and Cogs Miss are timed effects on the battle**
  (`BattleState.toons_hit_rounds`, `cogs_miss_rounds`), counted down once
  a round at the cog phase, the same shape as a lure countdown
  (`[OWNER]`: that is how TTR presents them). The wiki's "75%" is applied
  as a multiplier, so a 90% cog attack becomes 22.5%, not 15%. That
  reading is the code's; the wiki's wording does not settle it.
- **In a party round, an SOS resolves before any gag.** `[ASSUMED]`: no
  source states when in a round an SOS lands. The order was chosen to
  match pink slips.
- **Against a Version 2.0 cog**, a damage card removes the outer suit and
  the excess is not carried into the Skelecog, as with gags.

### One pool of calls

A budget such as "five SOS this fight" is one pool across every card
(`ToonState.sos_calls`), read through `ToonState.sos_held`. An earlier
version handed the solver five of each card held, and the Playout engine
then called an SOS on 13 of 28 boards of a Realms VP.

### How the engines price a call

Each engine charges for a card in its own units. These are preferences,
not measurements of the game.

| Engine | Charge | Notes |
| --- | --- | --- |
| PPO row (`hybrid.climb`) | `sos.SOS_PRICE` = 250 per call | `[OWNER]`: a card is a last resort, slightly less valuable than a unite because it uses the turn. Cards are supplied to the scorer directly (`hybrid._sos_probes`), since the trained policy has no action index for them. `hybrid.OFFER_SOS` is on. |
| Search row (expectimax) | `Objective.sos_cost` = 10 | Chosen, not derived. It was 0, and the search called a restock card beside a cog one hit from defeat. |
| Playout row | `playout.SOS_CALL_PRICE` = 0 | Measured: charging per call only delayed the calls and lost fights (43, 38 and 30 wins of 100 simulated Realms VPs at 0, 0.5 and 1 cog per call). |

All three also charge for wasted reach (`simulator.wasted_reach`,
`[OWNER]` preference): a card or group gag is charged for the share of
live cogs it cannot affect, for example a Drop card when half the cogs
are lured. It cost no wins in simulation (43 of 100 Realms VPs with it
and 43 without).

A heal is only worth something to a scorer that values laff. The PPO
row's scorer has a survival term (`weights.QUICK_W["survive"]`, 400) for
that reason; with it at zero, a 180-laff heal scored nothing.

### Not modelled

- **Rocky, Loopy Loopenloop and Lord Lowden Clear** are excluded on
  purpose (`sos.NOT_MODELLED`). `[OWNER]`: they come from limited-time
  events and cannot be earned again, and a solver should not plan around
  a reward that never comes back.
- **Damage from a card is not recorded for cog targeting.** A cog's
  memory of who damaged it does not include SOS damage.
- **Reading a TTR toon's cards.** See "What the live readers see" below.

## Unites

### What is known

| Fact | Source |
| --- | --- |
| A toon holds up to 100 unites of each type. | `[CONFIRMED]` |
| Toon-Up unites restore 20, 35, 50, 65 or 80 laff. | `[CONFIRMED]` |
| A Gag-Up unite restocks at most 7 gags for a single track, or at most 30 across all tracks. | `[CONFIRMED]` |
| A three-round cooldown applies inside a battle. | `[CONFIRMED]` |
| One unite at a time, affecting toons within a short radius of the user. | `[CONFIRMED]` |
| The values were higher before the 3.0.0 rebalancing of December 2021, so older guides and Toontown Online sources disagree. | `[CONFIRMED]` |
| A unite does not cost the toon's turn. The toon uses one and still throws a gag that round. | `[OWNER]` |
| A unite is something to use only as a last resort, valued above a pink slip. | `[OWNER]` preference |

### What is modelled (`solver/unites.py`)

- **A unite is not an action.** It is applied in the planning phase,
  before the gag is chosen, and takes effect at once. The engines treat
  it as a change to the state the gag is chosen from: use a unite, then
  plan the round on the result. In the game a unite can also be used at
  other moments; the model offers it only while planning. That is a
  deliberate narrowing.
- **Toon-Up** restores the unite's value, capped at the toon's missing
  laff.
- **Gag-Up** restocks highest levels first, bounded by the unite's budget
  (7 or 30), each gag's carry limit and the room left in the pouch. Level
  7 gags are not restocked; the wiki does not say they are, and the
  solver does not assume it.
- **Cooldown.** Using a unite sets a three-round cooldown
  (`ToonState.unite_cooldown`) that counts down at the end of each round.
- **Holding.** `ToonState.unites_held` is how many the toon may use, and
  it defaults to 0. `ToonState.unite_stock` says which kinds are held,
  where a reader knows. An empty stock beside a nonzero count means "this
  many, kind unknown", and every kind is then offered.
- **Which unites are offered** (`unites.candidates`): none during the
  cooldown; a Toon-Up only if the toon is missing nearly its full value
  (within 5 laff); a single-track Gag-Up only if that track has room for
  the full 7.
- **Price.** `unites.UNITE_PRICE` = 200 in the PPO row's scorer units,
  against 20 per remaining cog plus 120 for a pink slip. A plan with a
  unite must beat the plan without one by more than that. `[OWNER]`
  preference. The code warns against tuning this for win rate: a cheaper
  unite always wins more simulated fights, which says nothing about
  whether spending it was right.

Where the engines use them: the PPO row (`hybrid.OFFER_UNITES`, on), the
Search row (`unites.OFFER_UNITES_IN_SEARCH`, on), and the Playout row,
where the unite is carried on the plan (`playout.Plan`) so that a played
round actually spends it. In group playouts, each simulated teammate who
is recorded as holding a unite may use one, chosen by the rollout
network; the live readers record unites for nobody but the player.

### Why the default is zero

With the cooldown as the only limit, the supply was effectively
unlimited: simulated solo buildings went from 26% cleared to 100% on one
block of seeds, spending about four unites a building, on a holding the
solver had no evidence for. A toon whose unites nobody has read is
therefore offered none.

### Not modelled

- **The effect on nearby toons.** The wiki describes a unite as affecting
  toons near the user. The model applies it to the toon who uses it only.
- **Use outside the planning phase.**
- **Restocking level 7 gags**, which is left out, not guessed.
- **Reading a TTR toon's unites.** See below.

## Pink slips

### What is known

| Fact | Source |
| --- | --- |
| A pink slip fires the targeted cog out of the battle with a cannon. | `[CONFIRMED]` |
| It removes both layers of a Version 2.0 cog. | `[CONFIRMED]` |
| A toon holds up to 200, reduced from 255 in the December 2021 update. | `[CONFIRMED]` |
| Using one costs the toon's turn, and it cannot miss. | `[OWNER]` |

A comment in `solver/state.py` also says they come from the CEO, two to
six a run. It carries no source tag.

### What is modelled

- `Action(fire=True, target_index=i)` removes cog `i`. One action per
  live cog is offered while `ToonState.fires` is above zero.
- A fired cog is reported as zero damage dealt, so that scorers do not
  read a slip as the largest hit in the game.
- A slip counts as a way to damage a cog for the end-of-battle test, so a
  toon with only Lure gags and a slip has not lost.
- In a party round, slips resolve before any gag. `[ASSUMED]`: no source
  states when the cannon fires. The alternative, slips last, would let a
  party damage a cog and then remove it for free.
- Price in the PPO row's scorer: `weights.FIRE_PRICE` (20) times the cogs
  still to come, plus `weights.FIRE_FLOOR` (120). The floor exists
  because a live board often cannot say what is still to come, and a
  price of zero once spent a slip on a level 1 cog with 6 health.

`ToonState.fires` defaults to 0.

## What the live readers see

| | TTR | Realms |
| --- | --- | --- |
| Pink slips | Read. The game's Local API reports the count (`/pinkslips.json`). | Read from the toon's own data. |
| Unites | Not read. The player enters how many the panel may plan with; the kinds are unknown, so every kind is offered. | Read, by kind. |
| SOS cards | Not read. The Local API has `/sos.json`, but it has not been parsed, because no toon holding battle cards has been read and the card names it reports are unseen. | Read by name. |

On both servers the panel has a box for each consumable: the most the
solver may plan with. The count read from the game says what is held;
the box says what the player is willing to spend. Neither grants
anything alone, and all three boxes default to 0. A box is a budget for
the session (`[OWNER]`), counted down by what actually leaves the toon.

The consequence for TTR today: pink slips can be advised, unites can be
advised once the player enters a count, and SOS cards cannot be advised.

## What differs on Toontown Realms

Realms is a different server with Toontown Online lineage. Its rules are
handled where they differ and are never copied into the TTR tables.

| Topic | TTR | Realms | Source for the Realms side |
| --- | --- | --- | --- |
| Toons Hit and Cogs Miss | ±75% for 3 to 5 rounds | Every gag hits, or every cog misses, for the one round after the call (`BattleState.sos_one_round`) | `[OWNER]` |
| Toon-Up unite values | 20, 35, 50, 65, 80 | 10, 20, 40, 80 and a full heal (`ToonState.toon_up_values`) | `[OWNER]`, from the in-game menu |
| Other unite categories | Not modelled | Jellybeans (recorded, unused) and Toon-Down (a Realms addition, deliberately not implemented) | `[OWNER]` |
| Holdings | Partly read, see above | Slips, unites by kind and cards by name are all read | Observed on a running client |

The Realms values are set on the battle state by the Realms reader.
`unites.TOON_UP_VALUES` and the accuracy rules in `solver/sos.py` stay
TTR's.

## Open points

- Whether "75%" for Toons Hit and Cogs Miss is a multiplier or a number
  of points. The model uses a multiplier.
- When in a round a pink slip or an SOS resolves relative to gags. The
  model resolves both first.
- What `/sos.json` and `/unites.json` report for a TTR toon that holds
  cards and unites.
- Whether a Gag-Up unite or a restock card can restock a level 7 gag.
