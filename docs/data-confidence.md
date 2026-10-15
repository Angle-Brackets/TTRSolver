# Data confidence: what is solid and what is not

This document is the map of how far each number in TTRSolver can be
trusted. It defines the source tags used throughout the code and the other
docs, then goes through the data tables one at a time and says what is
confirmed, what is assumed, and what is unknown. It describes the code as
it stands on 2026-10-11; where a comment in the code is out of date, this
document follows what the code does.

Related documents: [mechanics-notes.md](mechanics-notes.md) covers the
battle rules built on these tables, [sos-notes.md](sos-notes.md) covers
SOS toons, unites and pink slips, and
[party-strategy.md](party-strategy.md) covers what has been measured about
multi-toon play.

## Sources, in order of authority

1. **The Toontown Rewritten wiki** (<https://toontownrewritten.wiki>) is
   the authority for game data.
2. **The maintainer's play knowledge** fills gaps the wiki leaves, and is
   tagged as such. It outranks the two sources below, because both
   describe a different game.
3. **Open Toontown** (<https://github.com/open-toontown>) is an
   open-source reimplementation of *Toontown Online*, the game TTR
   descends from. It is the algorithm itself, which makes it a better lead
   than a prose description, but it predates every TTR rebalancing pass.
   Anything taken from it is tagged `[OPEN TOONTOWN SOURCE]` and never
   `[CONFIRMED]`. Where that source is visibly buggy, the project
   implements what the code evidently means and records the discrepancy
   (see [mechanics-notes.md](mechanics-notes.md#pick_cog_target)).
4. **The QED1224 strategy guide**
   ([QED1224/Toontown-Resources](https://github.com/QED1224/Toontown-Resources)),
   which this project started from, also describes Toontown Online. It has
   been caught wrong on Lure durations, Lure accuracy, which Lure levels
   are group gags, and the luredRatio rule. It is a lead to verify and
   never a confirmation.

**Toontown Realms**, the other server the tool can read, is Toontown
Online lineage as well. Nothing read from Realms is used as a source for
TTR rules or copied into the tables in `solver/data/`.

The wiki returns HTTP 403 to ordinary page fetches but serves its
MediaWiki API:

```
curl "https://toontownrewritten.wiki/api.php?action=parse&page=Lure&prop=wikitext&format=json"
```

Category listings (used for the group cog attacks) come from
`action=query&list=categorymembers`.

## The tags

| Tag | Meaning | What the code does with it |
| --- | --- | --- |
| `[CONFIRMED]` | Read from the TTR wiki. | Used as data. |
| `[OWNER]` | The maintainer's judgement as an experienced TTR player. A report from play or a stated preference, not a sourced fact. | Used, and labelled so it can be challenged. |
| `[OPEN TOONTOWN SOURCE]` | Taken from Open Toontown's code. Same lineage as the guide, so weaker than `[CONFIRMED]`. Each use says what the wiki does and does not corroborate. | Used where the wiki gives only a direction. |
| `[ASSUMED]` | A value no source states, filled in knowingly and isolated so it can be changed in one place. Some were explicitly authorised by the maintainer; the list below says which. | Used. Any result that depends on it rests on a guess. |
| `[TODO]` | Unknown. Stored as `None`. | The accessor raises `NotImplementedError` (or `KeyError`) naming the cell. Nothing is substituted. |

Further labels appear inside the data tables:

| Label | Meaning |
| --- | --- |
| `[UNVERIFIED -- GUIDE-DERIVED]` | A value from the QED1224 guide that the wiki does not publish at all, so it cannot be checked there. Applies to cog attack frequency and accuracy. |
| `[FREQ STALE]` | A cog whose attack roster changed in TTR 4.0.0, so its guide-era frequencies were spread over the wrong set of attacks. |
| `[CONFLICT -- UNRESOLVED]` | Sources disagree and the conflict was left visible instead of being averaged. One case: The Mingler's Power Trip. |
| `[UNVERIFIED]` | A rule from play knowledge that the wiki is silent on. In this document those are listed as `[OWNER]`. |

Two notes on reading the code:

- Some comments say "`[CONFIRMED]` by the owner from play" ("the owner"
  is the code's word for the maintainer). Under the scheme above those
  are `[OWNER]`, and this document and
  [mechanics-notes.md](mechanics-notes.md) list them that way.
- The docstring of `solver/data/__init__.py` still defines `[CONFIRMED]`
  as "taken from the QED1224 guide and cross-checked against the wiki".
  That wording predates the wiki audit. The definition in the table above
  is the one the tables now follow.

## The no-guessing rule

- **A `[TODO]` is never filled with a plausible value.** If a number is
  not confirmed, the cell stays `None`, and the code raises when it is
  asked for.
- **Conflicting sources are not averaged.** The cell stays open with a
  comment describing what disagreed, or the more specific source is taken
  and the reason recorded.
- **A stand-in is deleted when its real data lands.**

The rule has deliberate, labelled exceptions: the `[ASSUMED]` values in
the next section. Each one was a choice between refusing to simulate a
fight at all and simulating it on a stated guess.

## Everything that is `[ASSUMED]`

`mechanics.MULTI_LURE_ACCURACY_BONUS` is the best-documented assumed
value in the project, and it is not the only one. The code carries about
two dozen `[ASSUMED]` tags. They fall into two groups that affect
different things, plus two tags that are now only history.

- **Assumptions in the battle rules and tables** decide whether a round
  is computed correctly. They can change the advice for a battle on
  screen.
- **Assumptions in the simulated world** decide what the simulated
  fights look like: how big a building floor is, what toons carry on
  which street. They shape training data and sweep results. They do not
  enter the calculation of a round.

"Authorised" below means the comment beside the value says the maintainer
approved filling it. Where the comment does not say so, the column says
"not stated".

### Assumed in the battle rules and tables

| What | Where | What the comment says it rests on | Authorised |
| --- | --- | --- | --- |
| Size of the multi-Lure accuracy bonus by level gap: 20 for a gap of 0, 15 for a gap of 1, 10 for 2 or more | `mechanics.MULTI_LURE_ACCURACY_BONUS`, `MULTI_LURE_ACCURACY_BONUS_DEFAULT` (also cited in `simulator.py` and `party_search.py`) | The TTR 4.0.0 notes give "(20/15/10)%" and say it depends on "gag level discrepancies", with the bonus "smaller if low-level Lure gags are used". Which gap selects which value is not stated. Mapped in order on the reasoning that the bonus is inversely proportional to the gap. That the bonus exists, and which pairs qualify, is `[CONFIRMED]`. | Yes |
| `tgtDef` (cog defence) for cog levels 13 to 19: −56, −58, −59, −60, −61, −63, −64 | `data.accuracy.TGT_DEF_RANK_1` | The wiki prints "Unknown" for these levels. Linear interpolation between the published level 12 (−55) and level 20 (−65), rounded. "A bet on the shape between two known points." | Yes |
| Accuracy and frequency of the twelve cog attacks TTR added in 4.0.0 | `data.cogs._fill_unmodeled` | The wiki publishes their damage and targeting and no accuracy or frequency. Open Toontown was checked and has only the older attacks. Each attack borrows the mean accuracy and mean frequency of the same cog's other attacks at that level, and the level's frequencies are rescaled to sum to 100. Described as "a preference for being roughly right over precisely silent, taken knowingly"; to be deleted, not tuned, if the wiki ever publishes the columns. | Not stated |
| Accuracy and frequency of Head Hunter, Corporate Raider and The Big Cheese above level 12 | `data.cogs._extend_high_levels`, `_carry` | Damage at those levels is `[CONFIRMED]`. The wiki publishes no accuracy or frequency above level 12 and Open Toontown stores none. The level-12 value is carried forward flat, on the reasoning that a flat carry "invents only 'no further change'". It errs toward weaker cogs. | Not stated |
| Accuracy of The Big Cheese's Glower Power, when opted in | `data.cogs.BORROW_BLANK_ACCURACY`, turned on by `ceo.enable_big_cheese` and by the live panels (`cogs.live_play_assumptions`, in each panel and each of its worker processes) | Off by default, so the cell is a `[TODO]` that raises. Without it every engine failed on any Big Cheese in a live fight. Turned on to simulate the CEO's second battle, it borrows the mean accuracy of the cog's other attacks, the same mechanism as the twelve attacks above. | Not stated |
| Pink slips resolve before any gag in a party round | `simulator.apply_party_round` | "No source states when in a round the cannon fires." Chosen because the alternative, slips last, would let a party damage a cog and then remove it for free. | Not stated |
| SOS cards resolve before any gag in a party round | `simulator.apply_party_round` | "No source states when an SOS lands in a round." Chosen to match pink slips, and because it makes plays such as a Lure card before a teammate's Throw readable. | Not stated |
| What a pink slip costs the exact search: 4.8 | `search.objective.Objective.fire_cost` | Derived, not measured: the scorer prices a slip's floor at 120 and an SOS call at 250, and a card costs the exact search 10. That the ratio carries from one scale to the other is the assumption. Before it, a slip was free and the Search row spent one on any cog. | Not stated |
| A cog read as lured on the TTR screen stays lured for one round, with a Lure accuracy of 80 | `live.session.cog_from_reading` | The marker above the plate says lured and not for how long. One round is the conservative end: it credits this round's forced accuracy and knockback and promises nothing after. The 80 is used only for the wake-up check. | Not stated |
| A waiting cog walks into a freed slot at once | `facility.reinforce` | The wiki confirms that cogs join a battle, not when. With four cogs on the field at most, they can only join as slots open, and a delay would only make the fight easier. Assumed "on timing only". | Not stated |
| Share of Version 2.0 cogs in the CEO's first battle: 0.20 | `ceo.V2_FRACTION` | The wiki says only "some of which are Version 2.0". Set from the maintainer's observed play. Open Toontown makes every cog there Version 2.0, and that disagreement is recorded. | From the maintainer's play |

What depends on each: the multi-Lure value affects any plan with two or
more Lures in one round. The `tgtDef` cells, the flat carry, the Big
Cheese borrow and `V2_FRACTION` all sit under the CEO fight, and a
comment in `solver/ceo.py` says every CEO number rests on them. The
twelve borrowed attacks affect damage taken from eight cogs on any
street. The two ordering rules affect party rounds that mix a slip or a
card with gags aimed at the same cog. The reinforcement timing affects
any fight with cogs waiting off the field.

### Assumed in the simulated world

These build the fights used for training and for the sweeps quoted in
the other docs. They are not game rules, and a battle read from the
screen does not pass through them.

| What | Where | What the comment says it rests on | Authorised |
| --- | --- | --- | --- |
| Cogs on each building floor (3–5 on floor 1, rising to 6–8) | `facility.floor_size` | The wiki confirms the direction, "Each floor contains progressively more Cogs", and gives no numbers. | Not stated |
| How often each street is the one being played (the last two playgrounds weighted 4 to 1) | `facility.LATE_PLAYGROUNDS`, `LATE_WEIGHT` | "Not a game rule": nothing published says where players spend their time. A choice about the training distribution. | Not stated |
| Laff ceilings of simulated toons per playground | `facility.PROGRESSION` | The laff floors and the pouch sizes are `[CONFIRMED]`. The ceilings are assumed; the maintainer puts a Dreamland toon around 100, which anchors the top, and the rest are interpolated. | Top anchor from the maintainer |
| Each gag-track choice a simulated toon makes is a coin flip | `facility.sample_tracks` | The order in which tracks are earned comes from the maintainer, who notes the real split is skewed. | Not stated |
| How many floors a simulated party takes on | `facility.floors_for` | The wiki supports that players can see the floor count before entering. The mapping from party laff to floors chosen is the assumption. | Not stated |
| Experience a simulated toon earns per playground | `rl.env.STAGE_EXP` | "The only invented number in the level model." The unlock thresholds it is read against are `[CONFIRMED]`. | Not stated |

### Tags that are now history

Two `[ASSUMED]` tags in `solver/vp.py` describe a value that has since
been replaced. The VP's round sizes were assumed at 12 cogs apiece until
the maintainer reported 20 a round from play. `vp.COG_ROUND` and
`vp.SKELECOG_ROUND` are now `[OWNER]` values, and the tags remain only in
the sentences that tell that story.

## Table by table

### Gags (`solver/data/gags.py`)

One `Gag` object per track and level, 49 in all.

| Field | Status | Source |
| --- | --- | --- |
| Damage ranges, all 35 damage gags | `[CONFIRMED]` | Each track's wiki page and each gag's own infobox. |
| Toon-Up heals, all 7 | `[CONFIRMED]` | Same. Lipstick is 25–30 from its own infobox; two summary tables on the wiki say 27–30 and were not followed. |
| Organic damage and heal values | `[CONFIRMED]` | Transcribed per gag. The percentage rule (`ORGANIC_BONUS_PCT`: 10% Trap, Sound, Throw; 15% Squirt, Drop; 20% Toon-Up, rounded up) is kept for reference only. Seltzer Bottle (18–21 becomes 22–25) is a known exception to it. |
| Trapdoor organic damage, 84–94 | `[CONFIRMED]`, with a recorded conflict | The wiki states it three ways (83–94, 84–94, 83–93). The Organic gags page and the Trapdoor infobox agree on 84–94 and that was taken. |
| Presentation organic accuracy, 100 | `[CONFIRMED]`, with a recorded conflict | The Organic gags page's prose implies 95; its own table and the Presentation infobox say 100. Moot in play at the 95 cap. |
| Base accuracy (`propAcc`) | `[CONFIRMED]` | Accuracy page and each track page. Only Lure and Toon-Up vary by level. |
| Group flag | `[CONFIRMED]` | Lure and Toon-Up are group at levels 2, 4, 6 and 7; every Sound gag is group; Trap, Throw, Squirt and Drop are group only at level 7. |
| Lure duration, 2 / 2 / 3 / 3 / 4 / 4 / 8 rounds | `[CONFIRMED]` | Lure page. |
| Carry limits at the two endpoints (`min_carry`, `max_carry`) | `[CONFIRMED]` | Each gag's infobox. |
| Carry limits in between (`carry_limit`) | `[OPEN TOONTOWN SOURCE]` | `ToontownBattleGlobals.CarryLimits`. The wiki corroborates it: each table's diagonal reproduces `min_carry` and its bottom row reproduces `max_carry`, for all six standard tracks (`tests/test_carry_limits.py`). Sound uses its own, lower table, following TTR 4.0.0. |
| Pouch capacities, 20 to 80 | `[CONFIRMED]` | Gag pouch page. |
| Level 7 gags do not count against the pouch | `[CONFIRMED]` and observed | See [mechanics-notes.md](mechanics-notes.md#the-gag-pouch). |
| Six trainable tracks out of seven | `[CONFIRMED]` | Gags page. |
| Skill points to unlock each gag (`GAG_UNLOCK_EXP`) | `[CONFIRMED]` | Skill points page. Transcribed and deliberately not used in the damage path (see below). |

There is no `[TODO]` cell left in the gag table. (The module docstring
still mentions "two cells explicitly left None"; both have since been
resolved as described above.)

**Known limitation: gag damage is not tied to experience.** In the game a
gag's damage climbs with skill points between its minimum and maximum.
The solver uses one global stand-in, `mechanics.DAMAGE_TRAINED_FRACTION`
(default 1.0, meaning every toon deals the maximum). The real formula is
transcribed (`mechanics.gag_damage_from_exp`) with its thresholds, but it
is not wired in, because the live readers know a toon's training level in
a track and not the points within it. The stand-in flatters an
under-trained toon most at level 6, where the ranges are widest (Birthday
Cake 48–100, Grand Piano 85–170).

### Toon accuracy components (`solver/data/accuracy.py`)

`atkAcc = propAcc + trackExp + tgtDef + bonus`

| Component | Status | Notes |
| --- | --- | --- |
| The formula | `[CONFIRMED]` | Accuracy page. |
| `propAcc` | `[CONFIRMED]` | Derived from the `Gag` objects. Trap is 0 in the table because Trap is handled by a special rule (always hits). |
| `trackExp`, 0 to 60 in steps of 10, halved for Toon-Up | `[CONFIRMED]` | Set by the highest gag unlocked in the track, not by the gag thrown. |
| `tgtDef`, cog levels 1–12 and 20 | `[CONFIRMED]` | Keyed on the cog's rank as well as its level: rank-1 cogs use −12 and −15 at levels 4 and 5, all others −15 and −20. |
| `tgtDef`, cog levels 13–19 | `[ASSUMED]` | Interpolated, see above. These levels used to raise instead. |
| 95 cap | `[CONFIRMED]` as a value | TTR 4.3.3 made it a soft cap that bonuses "can slightly push" past. The wiki gives no number for that, so the solver keeps a hard cap. Recorded by `ACCURACY_CAP_IS_SOFT_IN_GAME`, which nothing reads. |
| 5 floor | `[CONFIRMED]` | Applied in `mechanics.calc_toon_accuracy`. |
| Stun bonus (`PrevHits`), 25 per prior hit, 75 maximum | `[CONFIRMED]` | The guide's 20 and 60 are the Toontown Online values and were replaced. |
| Trap's Lure bonus, +10 for the first trap and +5 for each further one (group Lure only) | `[CONFIRMED]` | Persists across rounds while the trap is present. |
| +50 stun when a Lure activates a Trap | `[CONFIRMED]`, not modelled | `TRAP_ACTIVATION_PREV_HITS` is recorded and unused. |

### Cog health and rosters (`solver/data/cogs.py`)

| Field | Status | Notes |
| --- | --- | --- |
| Health by level, 1–20 | `[CONFIRMED]` | `(level+1)(level+2)` up to level 11, plus 14 from level 12. Matches all 20 rows the wiki publishes. |
| The 32 cogs, their departments and normal level ranges | `[CONFIRMED]` | Each cog's infobox. |
| Rank equals the lowest level a cog appears at | `[CONFIRMED]` | Used for `tgtDef`. |
| Version 2.0 cogs: two layers of normal health, no damage carried from the suit to the Skelecog | `[CONFIRMED]` | See [mechanics-notes.md](mechanics-notes.md#version-20-cogs). |
| Cogs three levels above their normal range | Not modelled | The wiki confirms every cog can appear up to three levels higher and publishes damage for those levels. Only the normal five levels are in the tables, except for the three Bossbot cogs extended for the CEO. |

### Cog attacks (`bossbot.py`, `sellbot.py`, `cashbot.py`, `lawbot.py`)

The four department tables hold 136 attack rows over 32 cogs and 68
distinct attack names. Each row has damage, accuracy and frequency per
cog level. The columns have very different standing.

| Column | Status | Notes |
| --- | --- | --- |
| Which attacks each cog has | `[CONFIRMED]` | Each cog's page, cross-checked against each attack's page. |
| Damage | `[CONFIRMED]` | Same. |
| Single-target or group | `[CONFIRMED]` | `data.GROUP_ATTACKS`, from the wiki's two categories, "Group Cog attacks" (14) and "Single Cog attacks" (54). Together they cover all 68 names with nothing left over. |
| Frequency (how often a cog picks each attack) | `[UNVERIFIED -- GUIDE-DERIVED]` | See below. |
| Accuracy (how often the attack hits) | `[UNVERIFIED -- GUIDE-DERIVED]` | See below. |

**Cog attack frequency and accuracy are the largest gap in the project.**
The wiki does not publish either number anywhere: its Cog attack page
defines both concepts and gives no values, and no cog page, attack page or
template carries them. Both are also known to have changed. TTR 4.0.0
rebalanced cog attacks and its notes say accuracy and frequency values
were tweaked. So these two columns are Toontown Online values for a game
that has since changed them, with no published replacement.

What is missing is the current TTR value of each cell. Two things would
settle it: the wiki publishing the two columns, or a measurement, meaning
enough recorded battles to estimate how often each cog uses each attack
and how often it hits. Neither exists today.

What is known about them:

- **They are faithful Toontown Online values.**
  `tools/verify_against_tto.py` compares the tables against Open
  Toontown's `SuitBattleGlobals.py`. When that check was written, 359 of
  366 rows matched exactly, all 7 differences were damage rows the wiki
  independently shows TTR rebalanced, and frequency and accuracy matched
  completely. That makes them a correct copy of the ancestor, which is
  not the same as being current.
- **Eight cogs are tagged `[FREQ STALE]`**: Micromanager, Corporate
  Raider, The Big Cheese, Penny Pincher, Money Bags, Robber Baron, Big
  Wig and Mr. Hollywood. TTR 4.0.0 gave each of them one or more new
  attacks, so the guide's frequencies covered the wrong set.
- **The twelve attacks added in 4.0.0 are fired on `[ASSUMED]` values.**
  They are Close the Loop (Micromanager), Hostile Takeover (Corporate
  Raider), Power Trip and Flood the Market (The Big Cheese), Beguile and
  Finger Wag (Mr. Hollywood), Nickel and Dime (Penny Pincher), Money
  Talks (Money Bags), Embezzle and Synergy (Robber Baron), and Quash and
  Throw Book (Big Wig). Their damage and targeting are `[CONFIRMED]`.
  Their accuracy and frequency are borrowed as described in the assumed
  table above. Before this fill they never fired, which understated the
  damage those eight cogs deal. The department modules' docstrings still
  describe that earlier state.
- **The Mingler's Power Trip is `[CONFLICT -- UNRESOLVED]`.** The wiki's
  roster for The Mingler has four attacks and does not include it. It is
  kept in the table because removing it would leave 15% of that cog's
  frequency with no source to say where it goes. Its numbers are
  guide-era values with no wiki counterpart.
- **The Big Cheese's Glower Power accuracy is `[TODO]`.** The wiki
  publishes no accuracy for it and the guide gave three values for one
  attack. The cell is `None` and the lookup raises, which is why the
  street cog pools leave The Big Cheese out. It is the one `[TODO]` cell
  left in the cog tables (`tests/test_data.py` pins that).

**Boss-only levels.** Head Hunter, Corporate Raider and The Big Cheese are
extended to levels 13, 14 and 15 for the CEO fight
(`data.cogs.HIGH_LEVEL_DAMAGE`). Damage is `[CONFIRMED]` from the wiki
(`tests/test_boss_levels.py` checks that the stored rows are a prefix of
the published ones). Accuracy and frequency above level 12 are
`[ASSUMED]`, carried flat.

### SOS cards, unites and pink slips

The values are `[CONFIRMED]` from the wiki; the rules for how they
interact with a battle are mostly `[OWNER]`. See
[sos-notes.md](sos-notes.md).

### Boss fight structure (`solver/vp.py`, `solver/ceo.py`, `solver/live/boss.py`)

| Fact | Status |
| --- | --- |
| VP: two turn-based rounds, cogs at levels 1–12 then Skelecogs at levels 8–12 | `[CONFIRMED]` |
| VP: 20 cogs a round in all, so 20 + 20 solo and 10 + 10 per side with company | `[OWNER]` |
| CEO: first battle cogs at levels 9–14; second battle opens with a level 14 Version 2.0 Big Cheese | `[CONFIRMED]` |
| CEO: 20 cogs per side in the first battle | `[OWNER]` |
| CEO: 40 in the first battle when solo | `[OWNER]`, stated by the maintainer as "I think" |
| CEO: share of Version 2.0 cogs in the first battle | `[ASSUMED]` |
| CEO: survivors of the banquet are all Version 2.0 | `[OPEN TOONTOWN SOURCE]`, agreed by the maintainer |
| CEO: size of the second battle | `[TODO]`. It depends on play. |
| CFO and CJ round sizes | `[TODO]` |

An unknown round size makes the remaining-cog count `None`. No horizon is
invented for it.

## Rules that rest on the maintainer's judgement

These are battle rules, not table cells, and each is tagged `[OWNER]`.
[mechanics-notes.md](mechanics-notes.md) gives the detail.

- Any landed attack from a damage track wakes a lured cog, not only
  Sound.
- Re-luring an already-lured cog neither refreshes nor extends its lure.
- A cog remembers who has damaged it for the whole fight.
- The same-track damage bonus applies per cog, not to every cog a group
  gag touched.
- Two single-target Traps thrown at one cog in the same round cancel.
- A Railroad needs one unlured cog to be placed, and wakes the lured ones
  it is laid under.
- A cog lured onto a trap takes the damage and is not left lured.
- Two Lures on one cog in the same round are a single effect.
- A group Toon-Up is divided among the toons being healed, not the whole
  party.
- Using a pink slip or an SOS card costs the toon's turn; using a unite
  does not.

## What the sensitivity analysis says

Because cog accuracy cannot be looked up, its effect was measured.
`python -m solver.search.sensitivity` shifts every cog accuracy cell by
an offset, re-runs the exact solo search and asks whether the recommended
move changes and whether the predicted outcome changes. It restores the
real tables on exit and leaves no value behind.

When the analysis was written, on the solo scenarios in
`solver/search/demo.py`:

- **The recommended move was the same across ±20 accuracy points** at
  every position the solver reached. The first difference appeared at
  −30, in one move out of five.
- **The predicted outcome moved gently.** On the `pressed` scenario the
  win rate stayed at 100% across ±20 points while mean laff remaining
  went from 35.0 to 30.1, about 0.12 laff per accuracy point.

The reading the project takes from this: the accuracy gap degrades the
forecast (win rates, expected laff) more than it degrades the advice
(which gag to throw).

Limits of that result, stated plainly:

- It was measured on small solo positions with the exact search. It has
  not been repeated for parties, for boss fights, or for the Playout
  engine.
- It perturbs accuracy only. Frequency, which decides how often a cog
  uses a group attack, was not swept.
- It predates the borrowed values for the twelve 4.0.0 attacks.

## How to read the tool's output in light of this

- Gag damage, gag accuracy, lure durations, cog health and cog attack
  damage come from the wiki. A calculation such as "this gag kills that
  cog" rests on confirmed numbers, with the caveat that damage assumes a
  fully trained toon.
- How much laff a toon loses in a round rests on cog attack frequency and
  accuracy, which are unverified for TTR. Treat any win rate or laff
  forecast as approximate.
- The maintainer reports one concrete mismatch with play: a single toon
  on one side of a two-player VP (10 + 10 cogs) is a hard fight in the
  simulator and an easy one in the game. That points at cog damage or
  attack rate being too high in the model. See
  [party-strategy.md](party-strategy.md#boss-fights).
- Anything involving two Lures thrown together, a cog above level 12, or
  one of the twelve 4.0.0 attacks rests on an `[ASSUMED]` value.
