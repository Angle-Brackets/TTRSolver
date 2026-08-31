# Scoring weights: what `QUICK_W["survive"]` is, and how 400 was picked

`_quick_score` is what `hybrid.climb` judges a plan with. Every term in
it is a DELTA across the round -- damage dealt, damage prevented, gags
spent -- because `_score_leaf` simulates the toon phase only and laff
does not move within it.

`survival_rounds` is the exception, and the only term that reads laff
LEVEL. It exists because without it a heal is worth exactly nothing:

* a unite scored 329.40 before restoring 80 laff and 329.40 after;
* Flippy, restoring 180 laff to a toon on 12 with a maximum of 137,
  scored exactly `-SOS_PRICE` -- the price and not one point else.

So lowering the price would not have helped. At price 0 the card reads
0.00 and still loses to any gag.

## The bug the sweep found first

The term was `survival_rounds(probe)`, reading the board AFTER the plan.
That makes it move with the plan, because killing or luring a cog lowers
`expected_incoming`. It therefore paid for damage prevention a SECOND
time, on top of `prevented`, and the extra payment lands on ordinary gag
choice where no heal is involved at all.

Measured, solo buildings at difficulty 8, no slips, nothing enabled,
200 runs a cell on two independent seed blocks:

| survive | block A | block B |
|---|---|---|
| 0 | 26.0% | 27.0% |
| 100 | 21.0% | 25.0% |
| 200 | 16.0% | — |
| 400 | 10.0% (p=0.000) | 16.5% (p=0.000) |
| 800 | 10.0% (p=0.000) | 14.5% (p=0.000) |

Sixteen points of ordinary play, to price something already priced.

## The fix, and why the gate is now structural

`survival_rounds(state, incoming=...)` takes an override, and
`_quick_score` always passes `expected_incoming(state)` -- the PRE-plan
figure. The term then varies only with laff.

Nothing in a plan changes laff. A Toon-Up gag looks like it should, but
healing comes back out-of-band from `party_mod.step` as `_healed` and
never reaches the probe's laff, so even that leaves the term alone.
Measured directly: on a party board with a toon down to 20, a Toon-Up
level 7 and a Throw level 7 both receive a survive contribution of
531.91, which is `800 x 0.6649`, which is `survival_rounds` of the
unplanned board.

**So the term is a constant across the entire action menu and cannot
reorder it.** The only thing it separates is "unite/SOS applied" from
"not", because those mutate laff on the state before the plan is judged.
`tests/test_survive_weight.py` pins that property; the refactor lock
agrees, with `pick` unchanged on all 120 sampled positions and `quick`
shifted by a per-state constant between 12.16 and 1600.00 (= 400 x
`SURVIVAL_CAP`).

The gate stops being an empirical result and becomes a structural one:
solo buildings read 26.0% and 27.0% at EVERY weight from 0 to 800, with
+0/-0 seeds moved and identical round counts.

## The sweep

Solo VP at 12 cogs a round, 5 slips, 200 runs a cell, same seeds across
every weight. **Not 20 cogs**: there every arm reads 0.0% -- with
unites, without, at every weight, and with truncation ruled out by
raising `max_rounds` to 40 -- and a cell where everything reads zero
cannot distinguish anything.

| survive | unite A | unite B | SOS A | SOS B | both A | both B |
|---|---|---|---|---|---|---|
| 0 | 35.0% | 31.5% | 27.0% | 24.5% | 35.0% | 31.5% |
| 100 | 73.5% | 66.0% | 27.0% | 24.5% | 73.5% | 66.0% |
| 200 | — | 91.5% | — | 33.5% | — | 92.0% |
| 400 | 95.0% | 92.5% | 52.5% | 49.0% | 96.0% | 93.0% |
| 600 | — | 91.0% | — | 53.0% | — | 92.5% |
| 800 | 92.5% | 91.0% | 57.5% | 52.0% | 95.0% | 94.0% |

Every lift above 200 is p<0.001 paired. The unite curve PLATEAUS from
200; SOS keeps climbing to about 600, because `SOS_PRICE` is 400 against
`UNITE_PRICE` 200 and needs more weight to clear its own price.

**400** sits mid-plateau for unites and near peak for SOS. It is not a
peak-picked value: both curves are plateaus rather than spikes, the two
seed blocks agree, and the gate is invariant at every weight, so there
is no cost side to trade against.

## What these numbers do NOT establish

* **The unite arm assumes a full stock.** `unites.available` checks only
  the cooldown; nothing tracks how many a toon holds. The wiki confirms
  a carry limit of 100 per type, and a 23-round fight with a 3-round
  cooldown can fit about 8, so "unlimited" and "a full stock" are the
  same thing inside one battle -- but a player carrying two unites will
  not see 92%. The SOS arm is bounded (one of each of the 29 cards) and
  is the more conservative signal.
* **The weight is inert until a flag is turned on.** `OFFER_UNITES` and
  `OFFER_SOS` are both False. With neither, nothing changes laff
  mid-plan and the term contributes the same constant everywhere --
  which is exactly what the invariant gate shows.
* **A Toon-Up GAG is still invisible to it**, for the out-of-band reason
  above. That is unchanged from weight 0, not a new gap, but it means
  the term values a unite's heal and not a teammate's.
* **Nothing here is a party result.** Every cell is one toon, except the
  heal gate, which is three and sat at 89.2% identically across weights.

## Turning the flags on, and the unite stock that had to come first

`OFFER_UNITES` and `OFFER_SOS` are both on.

Enabling them exposed that **a unite had no stock at all**.
`unites.available` checked only the cooldown, so every toon held an
unlimited supply. Solo buildings at difficulty 8 went 26.0% -> 100.0%
and 27.0% -> 99.0%, spending about four unites a building. That is not
the game and it is not something a price can fix, because the resource
was free.

`ToonState.unites_held` now holds the count, defaults to **0**, is
carried through `clone` (anything spent must be, or a sweep reports
usage that never happened -- the standing note on `fires`), and is
decremented wherever the cooldown is set. `available` requires both.

The default of zero is the safety property for live advice. Neither
consumable is visible to the readers -- the Local API reports no unite
pouch and nothing reads SOS cards off the screen -- so
`session.build_state` sets neither field. Both therefore read as "holds
none", nothing is offered, and **turning the flags on changes nothing on
screen today**. `tests/test_survive_weight.py` pins that.

### It reserves them for hard content on its own

The worry was that consumables would trivialise ordinary play. Measured
at survive=400, 5 unites held and a full 29-card book, 120 runs a cell:

| difficulty | win | unites/run | cards/run |
|---|---|---|---|
| 3 | 100% | 0.00 | 0.00 |
| 5 | 100% | 0.15 | 0.00 |
| 7 | 100% | 2.54 | 0.00 |
| 9 | 42% | 4.88 | 1.16 |
| VP, 12 cogs | 93% | 3.48 | 0.17 |

Ordinary street play spends nothing. The owner's rule -- standard play
should not need consumables -- falls out of the prices rather than
needing a hard-coded exemption for buildings.

**The earlier "it trivialises buildings" reading was an artifact of
testing at difficulty 8**, which is near the top of a 1-9 scale and
wins only 26% solo WITHOUT consumables. A toon losing three fights in
four is not standard play, and spending a heal there is correct.

`SURVIVAL_CAP` was swept as a candidate fix for that non-problem and is
left at 4.0. Lowering it reduces consumable use everywhere in
proportion (at 2.0: buildings 90.8% on 2.64 unites, VP 85.8% on 2.38) --
it does not separate easy content from hard, because the thing that
separates them is how much danger the toon is actually in, which the
term already reads.

### Still missing

The overlay cannot offer either until it knows what the player holds.
The honest options are a UI input for unite and card counts, or reading
them off the screen; neither exists yet. Until one does, these flags are
live-inert and matter only to offline search and measurement.

## The SOS price, and the turn it was charged for twice

[OWNER] "An SOS card is slightly less valuable than a unite because a
unite can be used AND you can do something in your turn, whereas an SOS
card eats your turn."

Correct, and the model already knew it. An SOS occupies the toon's
action slot, so the plan holds no gag for that toon and the damage terms
fall out on their own, with nothing priced. Measured with BOTH prices
zeroed over 90 positions:

| comparison | median | mean |
|---|---|---|
| best gag alone − card alone | 203 | 273 |
| unite + that gag − card alone | 841 | 892 |

The old prices were `UNITE_PRICE` 200 and `SOS_PRICE` 400, a gap of 200
— within three points of the turn cost the mechanics were already
charging. An SOS therefore had to clear roughly double its true
handicap.

`SOS_PRICE` is now **250**. The 50 that remains is scarcity, which is a
preference rather than a measurement: cards are farmed from whole boss
runs.

**This was not swept for win rate**, and `solver/sos.py` says why — that
sweep's answer is known and wrong, because cheaper cards always clear
more. Win rates were used only to check the change harms nothing:

| SOS price | d3 cards/run | d5 cards/run | d9 win | VP win |
|---|---|---|---|---|
| 150 | 0.00 | 0.00 | 48% | 93% |
| 250 | 0.00 | 0.00 | 43% / 55% | 94% / 97% |
| 400 | 0.00 | 0.00 | 42% / 47% | 93% / 97% |

Two seed blocks where two are shown. Ordinary play spends no cards at
any price from 150 to 400, so the price is not what protects it — the
mechanics are. Only hard content moves at all.

## Do the consumables get spammed? And does any of this need a retrain?

**No retrain.** Three facts settle it:

* `env.ACTIONS` holds **no SOS entry and no unite entry** — 0 of 250.
  The policy cannot emit either; SOS arrives through `hybrid._sos_probes`
  and a unite through the wrapper around `climb`. Only fires are in the
  table, 4 of them.
* The observation contains neither `unites_held` nor `sos_cards`. The
  policy is blind to consumables.
* Training optimises `round_reward`; `climb` judges with `QUICK_W`.
  Everything changed here was `QUICK_W` and the prices — inference, not
  the training signal.

So consumable use is decided entirely by the scorer, and retraining
would not move it.

### What it actually spends

150 runs a cell, then 200 held out, with 5 slips, 5 unites and all 29
cards available in EVERY cell including the easy ones:

| | win | slips | unites | cards |
|---|---|---|---|---|
| d3 | 100% | 0.63 | 0.01 | 0.00 |
| d5 | 100% | 1.16 | 0.32 | 0.00 |
| d7 | 99% | 3.22 | 2.22 | 0.07 |
| d9 | 63% | 4.73 | 4.66 | 1.05 |
| VP | 95% | 4.89 | 3.56 | 0.19 |

Unites and cards behave: nothing on easy content, heavy use only where
the fight is otherwise lost (d9 goes 3% -> 63%, the VP 31% -> 95%).

**Slips did not.** 0.63 a battle at difficulty 3, in a fight lasting 3.7
rounds and won every time — the one resource the owner said should be
for bosses. Unchanged at survive 0 and 400, so it predated this work.

### FIRE_FLOOR 20 -> 120

`FIRE_FLOOR` exists for exactly this and had already been swept — but
that sweep ran when a solo VP read about 86%. With consumables it reads
94%, and the headroom that opened was enough to raise the floor for free:

| floor | d3 slips | d5 slips | d9 win | VP win | VP slips |
|---|---|---|---|---|---|
| 20 | .63 / .58 | 1.16 / 1.12 | 63 / 66% | 95 / 95% | 4.89 / 4.88 |
| 60 | .00 / .00 | .12 / .15 | 65 / 70% | 94 / 94% | 4.69 / 4.66 |
| 120 | .00 / .00 | .03 / .05 | 65 / 67% | 95 / 94% | 3.96 / 4.03 |
| 200 | .00 | .03 | 53% | 85% | 2.93 |

120 zeroes the slip spent on easy content and spends nearly a whole slip
LESS per VP at the same win rate. 200 is too far. d9 is within noise
between 60 and 120; the economy separates them.

The refactor lock caught the change and was read before re-recording:
**9 picks moved, 8 of them `fire` to a gag**, one a gag-to-gag cascade
from the hill-climb settling differently. All 53 shifted scores are
positions whose scored action is itself a fire, so the floor reaches
fire-bearing plans only, as designed.
