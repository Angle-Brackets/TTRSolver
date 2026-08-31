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
