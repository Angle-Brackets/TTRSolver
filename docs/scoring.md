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

## The harness bug that produced four false results

Every measurement script re-implemented the same action-to-index
mapping, and every one ended it the same way:

    i = env.PASS_INDEX
    if action is not None and not action.is_pass:
        for k, entry in enumerate(env.ACTIONS): ...
    env.step(i)

**That fallback is the bug.** `PASS_INDEX` is not "I could not express
this action", it is "hold this round". So an action the table cannot
name becomes a toon standing still, and the run reports a strategy
failure where the truth is a harness failure -- silently, plausibly,
and in a form that reads exactly like a finding.

It cost four separate measurements:

* a fire has `track=None`, so a script filtering on `track is not None`
  passed instead of firing;
* an SOS has no index at all, so it passed instead of calling;
* both together read **0% at difficulty 9 and on the VP**, against 60%
  and 94% from a harness that mapped them;
* separately, a solo toon given Toon-Up training spends part of an
  80-gag pouch on gags it can never throw (it cannot heal itself), and
  a pouch built at every gag's carry limit sums far past `pouch_capacity`
  -- both read 0% too;
* and `facility_position` returns `cogs=[]`, because `BattleEnv.reset`
  builds the board, so a state used before `reset` has nothing to fight.

`solver/rl/harness.py` is the single implementation. `play` RAISES
`UnplayableAction` rather than falling back to a pass, `solo_loadout`
builds a valid solo toon, and `check_position` refuses a board that
cannot measure anything. A measurement that stops is worth more than one
that quietly measures the wrong policy.

## SCARCITY_UNITS: swept, and left at 20

[OWNER] "It should be weighted by the fact you can carry 7 $10 bills and
only 3 hypnos." `_gag_units` already charges
`level + SCARCITY_UNITS / carry_limit`, so a Hypno-goggles (level 6,
carry 3) costs 12.67 against a Small Magnet's (level 2, carry 25) 2.80.

Swept at 0, 20, 60 and 150, 150 runs a cell, through the harness above:

| units | d5 win / scarce | d9 win / scarce | VP win / scarce |
|---|---|---|---|
| 0 | 100% 88% | 13% 69% | 41% 78% |
| 20 | 100% 88% | 10% 68% | 45% 78% |
| 60 | 100% 83% | 8% 64% | 47% 75% |
| 150 | 100% 80% | 8% 55% | 45% 69% |

"scarce" is the share of thrown gags whose carry limit is 5 or fewer.
Raising the weight does hoard them -- 69% to 55% at difficulty 9 -- but
no win-rate signal separates 0 from 150 at this sample size, the two
hard cells moving in opposite directions. **Left at 20**, because a
shipped constant should not move on a wash, and `solver/search/party_search.py`
already warns that these weights disagree across three scorers.

What the sweep does establish: Hypno-goggles is 61.5% of lures thrown at
difficulty 9 and 62.2% in the VP, and that is not the scarcity term
failing to bite -- it is the term being outweighed by a genuinely better
gag on a multi-cog board.

## Why there is no group-waste penalty

On a one-cog board a group gag and a single gag score IDENTICALLY --
`$1 Bill single` and `$1 Bill GROUP` both read 1785.26 on the reported
Ambulance Chaser position. The model has no concept of a group gag
wasting its breadth; the only things separating two lures are level and
carry limit, through `_gag_units`.

That has a visible consequence. Asked what happens when the pouch holds
nothing below Big Magnet, the panel advises **Big Magnet GROUP** on the
lone cog, because at `4 + 20/15 = 5.33` it is cheaper than a $10 Bill at
`5 + 20/7 = 7.86`. Which is arguably right -- a toon carries 15 Big
Magnets and 7 $10 Bills, so spending the magnet is the better resource
decision even though it is the "group" gag. From $10 Bill up it picks
the single bill; from Hypno up it abandons the lure and throws instead.

**Left alone, because it does not happen.** Group gags thrown onto a
single live cog, across 150 runs a cell:

| | group gags thrown | onto one cog |
|---|---|---|
| difficulty 5 | 659 | 0 |
| difficulty 9 | 1410 | 1 |
| VP, 12 cogs | 1476 | 1 |

Two in about three and a half thousand. A penalty for it would be tuning
a 0.06% case, and this file already records what happened the last time
a plausible-looking menu change went in unmeasured: difficulty 9 fell
60% to 42%.

## Every A/B in this file was run on a maxed toon

`trackExp` is `(training - 1) * 10`, so a maxed track adds **+60**
accuracy -- against a spread of only **35** points between the weakest
and strongest gag in a track (Lure runs 55 to 90). Maxed, the 95 cap
therefore flattens the entire line against low-level cogs and gag choice
stops depending on accuracy at all. It separates again from cog level 8
up, and at training 3 it separates everywhere.

`facility_position` samples the real spread, and it is not maxed --
across 300 sampled parties:

| training | tracks | trackExp |
|---|---|---|
| 2 | 125 | +10 |
| 3 | 465 | +20 |
| 4 | 920 | +30 |
| 5 | 1458 | +40 |
| 6 | 547 | +50 |
| 7 | 537 | +60 |

**About 13% maxed.** Every sweep recorded above -- `survive`,
`FIRE_FLOOR`, `SOS_PRICE`, `SCARCITY_UNITS`, probe placement -- forced
training 7, so all of them describe the one regime where accuracy cannot
discriminate between gags. `harness.solo_loadout` now takes `training`
so a decision can be checked outside it.

Which conclusions are actually at risk:

* **`SCARCITY_UNITS` is not.** Only levels 6 and 7 have a carry limit of
  5 or fewer, and a toon trained to 5 holds no level 6 or 7 gags at all,
  so the knob is inert below training 6. Measuring it on maxed toons was
  accidentally the only place it does anything.
* **`FIRE_FLOOR` and `SOS_PRICE` are.** Both price a guaranteed effect
  against a gag that can miss, and at lower training gags miss more, so
  the alternative they are weighed against is weaker than it was in the
  sweep.
* **`QUICK_W["survive"]` mildly.** A heal is not accuracy-dependent, but
  the gag it displaces is.

Re-running those across the training spread needs care, because training
changes TWO things at once -- accuracy, and which gags the pouch can
hold -- so a naive sweep reads as a difficulty result. The d5 win rate
falls 100% to 22% between training 7 and 3 on that account alone.

### Both re-ran clean on realistic toons

`FIRE_FLOOR` and `SOS_PRICE` were the two flagged as at risk. Re-run on
the toons `facility_position` actually builds -- **mean training 4.65,
not 7**, parties of two to four, matched to their street -- 250 runs a
cell, paired on seeds:

| FIRE_FLOOR | win | slips | vs 20 |
|---|---|---|---|
| 20 | 89.2% | 17.33 | |
| 60 | 88.4% | 17.03 | +1/-3 p=0.625 |
| **120** | **88.8%** | **16.91** | +5/-6 p=1.000 |
| 200 | 85.6% | 16.58 | +3/-12 p=0.035 |

| SOS_PRICE | win | cards | vs 250 |
|---|---|---|---|
| **250** | **88.8%** | **0.74** | |
| 400 | 87.2% | 0.47 | +0/-4 p=0.125 |
| 150 | 89.6% | 1.03 | +3/-1 p=0.625 |

Both shipped values hold. 120 is indistinguishable from 20 (p=1.000)
while spending fewer slips, and 200 still overshoots. 250 beats the old
400 directionally on every seed that moved (+0/-4) and 150 is noise.

So the maxed-toon bias did not invalidate either number. It remains a
real limitation of the method, not of these two results.

Note this is the sampler's own distribution, so unlike the solo sweeps
above these are PARTY runs. Slips read about 17 a run because each of
two to four toons carries five, not because anything restocks --
`_next_floor` clones the state, so the pouch, laff and slips all carry
across floors.

## The panel's search budget was the single biggest defect

`climb`'s own default is 16. The panel passed **8**, below it, with
nothing in the code justifying the number. That is what starved the
targeted probes: they are appended after the track sweep, so at 8 they
are never evaluated, and `PROBE_CHEAPEST_KILL` was dead in live play --
recorded above as "a budget problem" and left there.

Measured on the sampler's own parties, 250 runs a cell, two seed blocks,
paired on seeds:

| budget | block A win | block B win | slips/run | warm latency |
|---|---|---|---|---|
| 8 | 88.8% | 85.2% | 18.4 | 1.9 ms |
| 16 | — | 95.6% (+27/-1) | 17.7 | 2.7 ms |
| 20 | 98.4% (+24/-0) | 98.4% (+33/-0) | 16.0 | 5.0 ms |
| **24** | — | **99.2% (+35/-0)** | **14.5** | **7 ms** |
| 30 | 98.4% | — | 13.0 | 8.6 ms |

Fourteen points of win rate, p<0.001 on both blocks, and it spends
FEWER slips -- 18.4 down to 14.5 -- because the cheap-kill probe finally
gets to offer the gag that does the job instead of a level 7 group gag.
The cost is five milliseconds against a poll interval measured in
hundreds.

`PANEL_BUDGET = 24`, mid-plateau: 20 through 30 all read 98-99%, and
both blocks are monotone up to it with a mechanism that explains why.

`tools/paired_confirm.py` and `tools/sweep_weight.py` passed 8 as well
and now pass 24, so a future sweep measures the configuration that
ships rather than one nobody runs. **Every number recorded above this
section was measured at budget 8** and is a lower bound on what the
panel now does; the weights were compared against each other at a fixed
budget, so their ORDERING stands, but the absolute win rates do not.

## The learned plan-ranker, removed from `plans`

`USE_POLICY` gated a second ranker inside `party_search.plans`: a
trained model scored candidate plans alongside `_cheap_score`, the two
top-Ns were unioned into each stratum, and the stratum was then ordered
by alternating the two rankings. It was False, so none of it ran, and
the code is now deleted. **The measurements are kept here because they
are the reason, and they cost real work.**

It lost at every shortlist width tried, after the wiring bug was fixed:

| width | policy OFF | policy ON |
|---|---|---|
| 8 | +88.06 | +87.29 |
| 16 | +89.34 | +87.29 |
| 30 | +89.34 | +87.29 |
| 60 | +89.72 | +88.29 |

**The cause is the LABELS, not the plumbing or the network.** The
teacher estimated each plan from 16 samples of a per-round spread of
about 31, a standard error near 7.8 -- while the median value gap
between the best plan and the sixth is 3.54. The labels are noisier than
the distinctions they are meant to teach, so the teacher's ordering
among good plans is mostly noise, and the policy learned it faithfully.

That also explains why the offline metric looked good. `regret@6` scored
the policy against those same noisy values: when the top twenty plans
sit within noise of each other, almost any six score a low regret. It
measured "avoids obviously bad plans", which the policy does better than
`_quick_score`, and could not see "picks the actually best plan", which
is what the search needs.

Two design findings worth keeping if it is ever rebuilt:

* **Ranking by the policy ALONE deletes correct plans.** On the maxed
  board it dropped 2 Foghorn + 2 Aoogah, the known-best line, off the
  shortlist entirely. Per-family stratification did not save it, because
  the loss happened *within* the Sound family.
* **Interleaving the two rankings is worse than unioning them.**
  Interleaving halves each ranker's depth, so the arithmetic lost the
  slot that had been keeping that same plan and it vanished again --
  the same deletion, caused by the fix for it. A union costs a larger
  bucket and guarantees the property the arrangement is for: a plan has
  to be missed by BOTH rankers to be lost.

**The prerequisite for trying again is more samples per plan in the
teacher -- 16 to 128 or more, at eight times the generation cost.** Not
a bigger network.

`policy` and `search.features` are still imported by `party_search`:
`evaluate`'s `leaf="learned"` path uses them, and that is unaffected.

## How good a ranker is `_quick_score`? Barely better than chance

It is what `hybrid.climb` judges with, what `tools/fit_scorer.py` tunes,
and what `train_heads.py` was fit against -- so most of this file rests
on it ordering moves well. It was never measured against outcomes.

**Method.** For each sampled position take the best candidate of each
track, so the candidate set is not chosen by the thing under test.
Evaluate each by Monte Carlo -- play it, finish the battle with `climb`,
16 times on paired seeds -- and compare that ordering with
`_quick_score`'s.

Solo, difficulty 7, 60 positions:

| | win rate |
|---|---|
| best candidate | 1.000 |
| **`_quick_score`'s pick** | **0.625** |
| uniformly at random | 0.507 |
| worst candidate | 0.000 |

**It captures 24% of the gap between chance and best**, and the mean
Spearman rho between its scores and the outcomes is **+0.013** -- no
ordering signal at all. It picks the best candidate 62% of the time, and
when it is wrong the move it takes wins essentially never.

### Two things that soften it, and one that does not

* **Most positions are flat.** Only 24 of 60 at difficulty 7 had any
  spread between candidates; at difficulty 5 it was 7 of 100, and at
  difficulty 9, 0 of 100 (a solo toon loses regardless). Where the first
  move cannot change the outcome, a bad ranker costs nothing -- which is
  why this does not show up as a large win-rate deficit in aggregate.
* **The sample is small.** 24 and 7 discriminating positions. This is a
  signal to act on, not a settled number.
* **The continuation policy is `climb`, which uses `_quick_score`.** So
  "best" means best under how we actually play, not ground truth. That
  is the right question for improving play, but it is not a claim about
  the game.

### What it explains

**The flat sweeps may be flat because the ranker cannot discriminate,
not because the weights do not matter.** `QUICK_W["risk"]`,
`["waste"]` and `["kill_threat"]` all swept to zero on evidence;
`SCARCITY_UNITS` came out a wash. A ranker with rho +0.013 on the
positions that matter would produce exactly that pattern whatever the
weights were worth.

It also explains the null result recorded above: giving solo the track
probe cut "the scorer's argmax was missed" from 61% to 7% and moved win
rate not at all. Agreeing more closely with a ranker that carries little
signal buys nothing.

**This does not mean the weights are wrong.** It means the evidence for
them is weaker than the tables above suggest, and that a better ranker
is worth more than better weights for the current one.
