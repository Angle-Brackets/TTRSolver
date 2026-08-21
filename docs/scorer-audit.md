# Auditing the scorer, after the policy work ran out

`reward-experiments.md` ends by concluding that further PPO work cannot
reach the live agent, and that the target is the scorer or the climb.
This is that work. It started from a different question -- *what is
actually making the toons fail?* -- asked before running another CEO
difficulty sweep, and the answer was four bugs rather than one.

**All four are in the party path only.** Solo play was right throughout,
which is most of why they survived so long.

| | before | after |
|---|---|---|
| CEO, 0 leftovers | 69.5% | **88.0%** |
| CEO, 5 leftovers | 38.0% | 41.5% |
| CEO, 10 leftovers | 0.0% | 4.0% |
| CEO, 15 / 20 leftovers | 0.0% | 0.0% |
| cog buildings | ~70% | 71.5% |

200 sides per row, common random numbers, `PPO + climb`.

## What the audit ruled out first

Four candidate causes were measured before any code changed. Three died:

- **Not gag exhaustion.** The party wipes holding **163 of 172 gags**.
  No loss at any difficulty came from an empty pouch. (This is the same
  phantom `reward-experiments.md` experiment 3 found the conservation
  terms defending.)
- **Not slip hoarding.** Losses spend 0.61 slips per round against wins'
  0.70 -- the same rate. The first pass reported "5 of 10 slips unused"
  as a finding; it was the fight ending sooner. A confound, not a cause.
- **Not the unpriced toon loss.** `toons_at_risk` has weight 0.0 and is
  dead code, which looked damning given that **100% of CEO losses are
  wipes**. Sweeping it 0 -> 240 moved nothing. A clean hypothesis, and
  wrong.
- **Not difficulty.** The opening draw does not predict the outcome:
  mean cog level 11.65 in clears against 11.73 in losses, party laff 219
  against 216. A four-round loss on `[12,11,10,9]` sits beside an
  eight-round survival on `[14,14,14,11]`.

Half the losses were over by round five. That pointed at the opening,
and the opening is where accuracy varies most.

## 1 -- both plan scorers assumed every gag hits

`_quick_score` and `_greedy_score` each played one ALL-HIT round, and
`_quick_score` is the climb's only judge.

The assumption is nearly true in a cog building: accuracy runs 70-95%
and hardly varies by track, so ranking by damage and ranking by expected
damage pick the same gag. Against level 13-14 cogs it spans 51% to 95%
and they stop agreeing -- the all-hit score prefers the biggest number
printed on the gag, which is reliably the least likely one to arrive.

Seed 99013 is the pathology in three rounds: two Grand Pianos into four
level-13 cogs on one shared 54% die, whiff; a Throw and a Lure, whiff;
dead, with no cog below full health.

Both now take the expectation over every way the dice can fall, through
one shared `_expected_over_rolls`. **Enumerated, not sampled** -- a party
is at most four toons and each rolls at most one die, so at most 16
branches, and exact means a ranking cannot wobble between two calls on
the same position. Branching over ROLL GROUPS rather than toons keeps
the correlated dice right for free, so a plan still cannot hedge by
stacking one track on one target.

**Accuracy is conditional, and the conditions are large.** The
probabilities are read from the simulator's own `record` per branch
rather than recomputed, because a table of per-gag accuracies would get
all of these wrong:

| | accuracy |
|---|---|
| Drop 7, nothing landed first | 54% |
| Drop 7, **Throw landed first** (stun) | **79%** |
| Lure 6 alone -> **two Lure 6s** (multi-lure) | 79% -> **95%** |
| Lure 6 into untrapped -> **trapped** target | 79% -> **95%** |

Worth 69.5% -> 75.0% on 200 CEO sides on its own (+24/-13, sign test
p=0.049). A 40-side sample said +12.5 points; 200 sides said +5.5. Quote
the larger sample -- this happened twice in one session.

Cost on the climb: 1.7 -> 3.3 ms per decision, not the 16x the branch
count suggests, because a probe is cheap. On the classical search the
same change measured **73.3% -> 73.3%, +2/-2, at 794 -> 1245 ms per
decision** -- no measurable gain for 1.6x cost. Kept as a correctness
fix, since `rollout_value` IS `greedy_plan` played forward and an
all-hit rollout values every position as though the party never misses.

## 2 -- forced accuracies did not survive a party round

Three accuracies are stated by the rules rather than computed: Trap
always hits, Throw and Squirt are guaranteed against fully lured cogs,
Drop always misses them. `calc_toon_accuracy` returns them verbatim and
says so.

`apply_party_round` then treated the forced number as an ordinary total,
added the same-round stun bonus and capped the sum:

| | rule | party round resolved it at |
|---|---|---|
| Trap, after a heal landed | 100% | 95% |
| Throw into lured, after a heal landed | 100% | 95% |
| Drop into lured, after a Throw landed | **0%** | **25%** |

So an always-hit Trap had a 5% miss, and a Drop that "always misses on
lured Cogs" could land. All three misfire only when something else hit
earlier in the round, which is why 878 tests passed over them.

`mechanics.forced_accuracy` is now the single home for the decision.
Found by printing the numbers the simulator actually used rather than
the numbers a separate calculation said it should have used -- which is
what `apply_party_round`'s new `record` parameter exists for.

## 3 -- every gag in a party round used toon 0's training

`toon_action_accuracy` read `state.toon` for whoever was throwing, so a
four-toon round scored all four gags with `toons[0]`'s track experience
and organic tracks. It takes an `actor` now.

Nothing measured moves: the VP and CEO field maxed teams, and when every
toon has the same training, reading the wrong one gives the right
answer. It is wrong for any mixed party, which is what a real pickup
group is.

## 4 -- pink slips were free, so the party never had one left

`_cheap_score` charged nothing for a fire and said so outright: *"A
search using this will therefore fire freely. That is close to right for
the CEO, where slips are the reward for the fight."*

Measured, it is not close to right. The party spent all ten slips on the
waiter battle and reached the Big Cheese holding **0.3 of 10** -- the
whole of why ten banquet leftovers sat at exactly 0%.

Battle two in isolation, from full resources, clears 93% at ten
leftovers, so the fight was never the problem. Which resource decides
it, on 40 sides each:

| | 10 slips | 0 slips |
|---|---|---|
| full laff | 92.5% | 50.0% |
| 65% laff | **82.5%** | 17.5% |

The slips are worth 42 points of clear rate, the laff 10.

**The shape matters more than the number.** A flat price was tried
first: it helped at five leftovers (38.0% -> 49.5%, p=0.008) and HURT at
zero (88.5% -> 82.0%, p=0.021), because it also suppressed slips in the
last battle -- and a slip carried out of the fight unspent is worth
nothing. Scaling by `cogs_remaining` sends the price to zero when there
is nothing left to save for: hoard while cogs are still coming, spend
freely at the end.

`FIRE_PRICE = 20` is **directionally supported, not proven**. Over 200
sides it is neutral at zero leftovers (88.5% -> 88.0%, p=0.50 -- the
flat price's harm is gone) and positive but not significant at five
(38.0% -> 41.5%, p=0.22). What it clearly does is unstick ten leftovers
from 0%, at every non-zero price tried.

## Refuted -- pricing a slip at the use it gives up

The obvious objection to a count is that a count cannot tell a level 10
waiter from a level 14 Version 2.0, and only one of those is worth a
slip. So the price should be the **opportunity cost**: rank every cog
you could fire instead -- those standing and those in the `holdout` --
and, holding F slips, charge the F-th best, because that is the use you
are settling away. No tuned constant at all, just a comparison.

It was built and it lost, decisively, on 200 sides per row:

| | count price (20/cog) | opportunity cost |
|---|---|---|
| 0 leftovers | **88.0%** | 76.0% (+11/-35, p=0.0003) |
| 5 leftovers | **41.5%** | 28.5% (+20/-46, p=0.0009) |
| 10 leftovers | **4.0%** | 2.0% |

Not a broken implementation -- it did exactly what it was designed to.
On the opening waiter board, firing a cog is worth 241.3 against an
opportunity cost of 333.9, so it declines. And it barely hoards: 9.00
slips fired against 9.85, two left at the end against 0.25. It loses six
sides in forty by declining 0.85 slips.

**Which slips, not how many.** The ones it declines are the EARLY ones,
and a slip spent early stops that cog attacking for the whole rest of
the battle. The comparison prices what a slip buys in *removal* and
ignores what it saves in *laff over time*, which in a twenty-cog battle
is most of what it is for. `_fire_value` already carries `_cog_threat`
-- one round of the cog's damage -- but one round is not the horizon a
slip actually buys.

The idea is not dead, but a working version has to price the damage a
slip prevents between now and the end of the battle, not the cog it
deletes. Reverted rather than left behind a `SLIP_OPPORTUNITY = 0.0`
knob, because that is how `toons_at_risk` became dead code.

## What is still open

**Ten leftovers is 4%, not solved.** Holding slips costs laff in battle
one and battle two wants both. At `FIRE_PRICE = 80` the party arrives
armed with 6.2 slips but at 42.8% laff, and only 19 of 40 sides reach
battle two at all. The isolated measurements suggest the ideal line --
clear the waiters without slips (53.8%), then battle two armed (82.5%)
-- is worth about 42%, so roughly 38 points are being left on the table
by a scorer that cannot see across a floor boundary.

**Fifteen and twenty leftovers are 0% at every price tried.** Probably a
difficulty statement, but it has not been proven the way ten was.

**The scorer cannot see the next battle.** `BattleState` exposes
`cogs_remaining` as a count and `holdout` as the current battle's
reinforcements; the facility plan lives in the env. So "save exactly as
many slips as the last battle needs" is not expressible from a state,
which is why the price has to be a smooth function of a count instead.

## What the policy could not see

Asked whether the training mix should be enriched with CEO and VP
positions, the prerequisite turned out to be missing. Measured on the
290-wide observation:

- **A Version 2.0 and an ordinary cog encoded identically** -- 0
  differing floats. The suit is the single thing that defines the CEO's
  banquet round.
- **Holding 0 pink slips and holding 5 encoded identically.** The action
  table has offered fire actions since they were modelled; nothing ever
  told the policy whether it had any. It duly proposed 10.07 of its 10
  slips per CEO side, firing everything, with the legality mask as the
  only thing that ever said no.
- **Level 14-15 cogs fell outside the normalisation.** `level / 12.0`
  and `max_hp / 200.0` are the top of a cog BUILDING; a level 15 Big
  Cheese read 1.25 and 1.43.

So enriching the training mix first would have taught the policy to
guess: the positions differ in what it cannot perceive. The observation
is now 302 wide -- a `suited` flag and the remaining-work ratio per cog,
a slip count per toon, and scales of 20 and 476, which is where the
tables actually end.

The ratio is given rather than implied because remaining health is
`hp + max_hp if suited`, a PRODUCT of two inputs, and a linear layer
cannot form one. Same reasoning as `trap_damage / hp`.

**This invalidates every exported policy**, exactly as the 246 -> 250
action change did, so it forces the retrain rather than merely enabling
it. `check_export` refuses the mismatch, and the reason -- which used to
be computed and thrown away, leaving the tools to report "numpy or the
policy is missing" -- now reaches the user: *observation is 302 wide,
policy was trained on 290 -- retrain*.

Two measurements to set expectations for that retrain. The climb is
**saturated** on CEO boards: budget 8, 16, 32 and 64 all give 88/88/88/88
at zero leftovers and 38/37/37/37 at five, converging well before budget
8. And plain argmax scores 55% and 10% where the climb scores 88% and
38%. So the policy is far worse than the agent, and the agent does not
depend on it much -- which is `reward-experiments.md`'s finding again,
now with a fourth piece of evidence. Expect a better policy to show up
on plain and not on the climb. The exception worth testing is slip
discipline, where the proposal really does drive behaviour: the climb
trims 10.07 proposed slips only to 9.42.

## Retraining on boss sides -- and the first policy change to reach the climb

Six runs, 6M steps each, three seeds an arm. The control arm exists
because the observation widened at the same time: without it, "boss
positions helped" and "the wider observation helped" are one number.
Both arms `--coordinated --facility-fraction 0.5 --fire-fraction 0.25
--hidden 256`; the treatment adds `--boss-fraction 0.25`.

120 sides a cell, common random numbers, per-seed figures in brackets.

| set | mode | control | boss |
|---|---|---|---|
| buildings | plain | 63.3% [64/63/62] | 60.3% [56/64/61] |
| buildings | climb | 72.5% [72/73/72] | 69.2% [63/72/72] |
| VP | plain | 95.0% | 96.4% |
| VP | climb | 98.1% | **99.7%** |
| CEO 0 | plain | 43.3% [34/56/40] | **76.4%** [68/78/83] |
| CEO 0 | climb | 79.2% | **88.1%** [88/88/88] |
| CEO 5 | plain | 10.0% [5/10/15] | **31.9%** [19/37/40] |
| CEO 5 | climb | 28.6% | **40.0%** |
| CEO 10 | either | ~0.5% | ~1.2% |

Paired over sides, boss against control: CEO 0 plain **+33.1**
(+140/-21, p<0.0001), CEO 0 climb **+8.9** (+45/-13, p<0.0001), CEO 5
plain **+21.9** (p<0.0001), CEO 5 climb **+11.4** (+90/-49, p=0.0003),
VP climb +1.7 (p=0.035), buildings climb **-3.3** (p=0.033).

**This is the first policy-side change that has ever moved the climb**,
and it refutes a prediction made in this document three sections ago.
The reasoning there was that the climb is saturated on CEO boards --
budget 8, 16, 32 and 64 all score identically -- so a better proposal
would show up on plain and not on the agent. Budget saturation turns out
to say only that more ITERATIONS do not help. It says nothing about
where the climb starts, and coordinate ascent from a different starting
plan reaches a different local optimum. +8.9 and +11.4 on the climb is
that difference.

`reward-experiments.md`'s finding still stands for everything tried
there -- five changes that moved plain and not the climb -- but it is
now bounded: it held because those changes were all on positions the
climb already handled well. On the CEO it does not hold.

**The buildings cost is one seed, not a trend.** Boss climb reads
[63/72/72] against control's [72/73/72]: two of three seeds match the
control exactly and seed 1 is an outlier. Worth more seeds before
calling it a real regression -- and it has a confound either way, since
at `--boss-fraction 0.25` the treatment arm gets a quarter fewer
facility episodes (0.375 against 0.500 effective). Holding building
exposure constant would need `--facility-fraction 0.667` in the boss
arm, which has not been run.

**CEO 10 did not move**, from either side. Four sections of this
document have now failed to shift it.

Shipped `boss_s2`, **selected on the in-training facility eval** (+44.76
return, 84.5% win, 70.0% of floors finished -- the best of the three
boss seeds there) rather than on any set reported above. That
distinction is the point: an earlier policy in this repo was shipped
after choosing its seed on a set that was never reported, and the commit
title still says so.

## Two notes on method

**A 40-seed sample overstated the effect twice, by roughly 2x, in the
same session** -- once for the expected-value scorer (+12.5 claimed,
+5.5 real) and once for the slip price (+7.5 claimed, +3.5 real, not
significant). Paired 200-side runs with common random numbers and a sign
test are the minimum for anything that gets quoted.

**Watch for `sum(1 for r, _ in res)` without the `if r`.** It counts
every row regardless of the win flag and can only ever print 100%. It
was written twice during this audit, and the first time nearly got a
dead-flat sweep reported as a finding.
