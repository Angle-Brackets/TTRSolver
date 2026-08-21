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

**The buildings cost was seed noise.** It read -3.3 (p=0.033) on the
first set, from a single outlying seed -- [63/72/72] against control's
[72/73/72]. Two explanations were open: real harm, or displacement,
since at `--boss-fraction 0.25` the boss arm also gets a quarter fewer
facility episodes (0.375 against 0.500 effective). A third arm at
`--facility-fraction 0.667` restores the exposure, and all three were
re-scored on 180 HELD-OUT sides a cell:

| set | mode | control | boss | bossmatched |
|---|---|---|---|---|
| buildings | climb | 66.3% | **69.6%** | 66.9% |
| buildings | plain | 61.7% | 60.6% | 59.6% |
| VP | climb | 99.4% | 99.4% | 99.3% |
| CEO 0 | climb | 78.7% | **88.9%** | 87.6% |
| CEO 0 | plain | 46.7% | **73.9%** | 79.6% |
| CEO 5 | climb | 32.4% | **43.1%** | 46.9% |
| CEO 5 | plain | 7.8% | **35.2%** | 30.6% |

The sign FLIPS: on seeds nobody tuned against, boss is 3.3 points ABOVE
control on buildings. So there was nothing to fix, and `bossmatched`
duly fixes nothing -- it lands between the other two with the widest
per-seed spread of the three, [71/63/66].

**The CEO win replicates, and it is the session's most robust result.**
+10.2 at CEO 0 on the climb, +10.7 at CEO 5, +27 on both plain cells,
with per-seed ranges that do not overlap at all: boss [67/76/79] against
control [37/57/47]. Everything else measured today shrank or vanished on
a larger sample. This did not.

**CEO 10 did not move**, from either side. Four sections of this
document have now failed to shift it.

Shipped `boss_s2`, **selected on the in-training facility eval** (+44.76
return, 84.5% win, 70.0% of floors finished -- the best of the three
boss seeds there) rather than on any set reported above. That
distinction is the point: an earlier policy in this repo was shipped
after choosing its seed on a set that was never reported, and the commit
title still says so.

## Refuted -- that the CEO is lost by not healing

It never heals on a boss board. Zero Toon-Ups in 1446 decisions across
40 CEO sides, including 99 rounds with the party under 35% laff, while
each toon carries eleven heals and a level 7 group Toon-Up restores 210
laff to the OTHER toon -- more than a full bar. In a losing trace the
party sits at 25 and 23 laff and throws Sound and Drop.

(A group Toon-Up is split evenly between its recipients, and the thrower
is not one of them. A two-toon party has a single recipient, so it does
receive the whole 210; a four-toon party gets three shares of 70. An
earlier draft of this section said "210 to everyone", which is wrong in
any party -- the thrower always heals nobody, including themselves.)

That looks like a glaring hole. It is correct play.

Two experiments, in the order they were run, because the first one
answered a different question than it was asked:

**Raising `QUICK_W["heal"]` does nothing.** From 2 to 40 -- twenty times
-- CEO clears 88.3% -> 89.2% at zero leftovers and 37.5% -> 39.2% at
five, and the agent still heals 0.1 times a side. It could not have
worked: **the climb can only reorder what the policy proposes**, its own
docstring says so, and Toon-Up gets essentially no probability on these
boards. The weight was never reached. Tuning a term that never fires
produces exactly this: a flat sweep that looks like evidence.

**`probe_tracks` reaches it, and then loses.** That flag offers each
seat the best action of every track it HOLDS, so a heal becomes a
candidate however the policy ranks it. It has been off since it was
measured and refuted -- but the recorded reason was that `_quick_score`
"plays one all-hit round, and a trap pays the round after, so it scores
near zero", and that scorer no longer exists. Re-run against the
expectation scorer, 120 sides a cell:

| set | probes off | probes on | Toon-Up/side | |
|---|---|---|---|---|
| buildings | 71.7% | 70.0% | 1.31 -> 1.82 | +4/-6, p=0.38 |
| VP | 100.0% | 98.3% | 0.00 -> 0.39 | +0/-2 |
| CEO 0 | **88.3%** | 80.8% | 0.00 -> 0.56 | +4/-13, p=0.025 |
| CEO 5 | **37.5%** | 30.8% | 0.01 -> 0.91 | +15/-23, p=0.13 |

The mechanism works -- it heals now -- and it costs 7.5 points on the
CEO. So the scorer was right to decline: at laff [25,23] it prices the
attack at 851 against 227 for a double heal, and on a board where
incoming damage scales with the number of cogs still standing, killing
IS the prevention. A round spent healing is a round four cogs swing for
free.

`probe_tracks` stays off, now refuted twice for two different reasons.

**"It never heals" is CEO-specific.** On buildings the policy proposes
1.31 heals a side unprompted. It declines on boss boards particularly,
and that is a judgement rather than a blind spot.

What is left is duller than what was being looked for. The waiter battle
is a damage race with no slack -- twenty cogs at levels 9-14 against 217
laff -- and the two traced sides play structurally the same game with
the same nine or ten slips. One leaves for the Big Cheese on 139 laff
and one on 6. The loser is not making an identifiable mistake; it is on
the wrong side of the accuracy rolls, which is the same reason the
opening draw does not predict the outcome either.

## Refuted -- widening the climb's candidate window

The climb offers each seat only the policy's top `width` actions,
default 3, and it is fair to ask whether that is too narrow. On the
opening round of the CEO's second battle, enumerating ALL 2132 legal
joint plans:

    board  c0:14=254V c1:9=110V c2:10=132V c3:12=196V   laff 71/65

    585.6   lure/6->all   + trap/7->all     <- best legal plan
    559.6   squirt/7->all + drop/7->all
    525.0   toon_up/5->1  + drop/7->all
    472.7   squirt/7->all + drop/6->c0      <- played, rank 17 of 2132

So the best plan does open with a Lure, and the two-track setup it pairs
with -- a Trap behind it -- is exactly the kind a one-seat-at-a-time
sweep assembles badly. But the climb lands in the top 0.8%, which is
respectable rather than broken, and the gap is 113 points.

**A correction, because the first version of this section was wrong.**
It claimed the best plan was `lure/6->all + squirt/7->all` at 831.7, one
seat-move from the start and unreachable through a 3-wide window. Seat 1
holds no level 7 Squirt, so that plan is ILLEGAL and was never
available. `_quick_score` does not check playability -- `_playable` is a
separate function -- so a hand-built plan will happily score a gag the
toon does not own. The climb never had this problem: `_logits` masks
illegal actions to -inf and the sweep skips them, and across 3198
actions played on buildings, the VP and the CEO, zero were illegal.

The design is generate-legal-then-score, which is right: legality is
settled by `legal_actions` and `legal_mask` upstream, and re-deriving it
inside a function called thousands of times per decision would be pure
cost. What made it a trap was an INCONSISTENCY underneath. A pouch holds
explicit zeroes -- `{(SQUIRT, 7): 0}` is an ordinary entry for a toon
who has spent them all -- so spending a MISSING key raised KeyError,
which `_quick_score` catches into -inf, while spending a ZERO count went
quietly to -1 and dealt full damage:

    key absent      _quick_score  -inf    simulator KeyError
    key present, 0  _quick_score  72.8    count -> -1, damage dealt

Both are the same impossible plan and `_playable` refuses both; only one
of them said so. `simulator._spend_gag` now refuses both alike.

Two readings in that draft came from the same mistake. "squirt/7->all
ranks 49 for seat 1, unmoved by whether its partner lured" was not a
finding about the policy: seat 1 had 48 legal actions, so rank 49 meant
illegal, three times over.

**Coordination itself is live and correct**, which was the other thing
suspected. Every sweep recomputes each seat's logits with the current
joint plan visible and that seat blanked:

    pending = list(plan)
    pending[seat] = None
    values = _logits(model, state, seat, pending)

and the rankings do move in response -- committing seat 0 to a Lure
lifts `throw/5->3` to second for seat 1 and drops `drop/6->0` from
second to fifth. This is the class of bug that hit the DAgger run, where
seat k was labelled against the teacher's stale earlier moves, and it is
not present here.

**Widening does not pay.** Raw `width` is worse, because `budget` counts
scorer calls and a sweep costs about seats x width of them -- so width 8
at budget 8 buys candidates out of convergence and drops buildings to
65.8% (p=0.033) and CEO 0 to 75.0% (p=0.0019). At MATCHED sweeps it
looked like a win: CEO 5 37.5% -> 50.0% (p=0.022), CEO 0 +4.2,
buildings +1.6, nothing harmed.

It did not replicate. On 240 fresh sides a set, seeds never used to find
it:

| set | w3 b8 | w5 b14 | flips |
|---|---|---|---|
| buildings | 69.2% | 70.0% | +12/-10 |
| VP | 98.8% | 100.0% | +3/-0 |
| CEO 0 | 90.4% | 91.2% | +12/-10 |
| CEO 5 | 48.8% | 48.8% | **+50/-50** |

Exactly zero on the cell that motivated it. The baseline itself moved
37.5% -> 48.8% between the two seed sets, so the discovery set was a
hard draw and `w5` was fitting it.

**Budget alone buys nothing** -- +0/-0 on CEO 0, +1/-1 on CEO 5, at
three times the budget. That is a real result rather than a null one: it
says the climb converges long before budget 8, so the wall was never how
long it looks. Combined with the width result, the wall is not obviously
the window either.

A pattern is now visible across three attempts. Everything that widens
what the climb CONSIDERS -- `probe_tracks`, raw width, matched width --
either loses or does nothing, while the one thing that improved it this
session was making the scorer more accurate about the plans it already
saw. The suggestion is that `_quick_score` ranks a few plausible plans
well and a wide field badly, which would make widening the window a way
of feeding it exactly the comparisons it is worst at. That is a
hypothesis and has not been tested.

**A prediction I got wrong, recorded because it was specific.** I
expected a wider window to lure MORE, having traced a lure being
abandoned. Lures per side went DOWN wherever the window widened -- 6.65
-> 6.11 on CEO 5, 4.44 -> 4.11 on CEO 0 -- while the win rate rose on
the discovery set. So it was never "the lure gets rescued"; wider
windows find better PAIRINGS, and one well-supported lure replaces two
poorly-supported ones. The r11 case is a true instance of the mechanism
and a misleading guide to its effect.

## What training can and cannot teach about pink slips

Lookahead into the next floor is ruled out on realism grounds -- a
player cannot see it, so neither may the solver, and a clear rate earned
by peeking would not transfer. That leaves training, and training got
exactly half of it.

Measured on the policy alone (plain argmax, so the scorer's `FIRE_PRICE`
is not what is being read), over CEO sides at 0, 5 and 10 leftovers:

| board | P(fire) |
|---|---|
| a Version 2.0 present | **62.2%** (n=779) |
| no 2.0s | 47.0% (n=790) |

**Target choice is learned.** It fires 15 points more readily at a cog
with two health bars, which is right -- a slip removes both. And it is
newly learnABLE: before the observation widened, a v2.0 and an ordinary
cog encoded identically, so this could not have been picked up at any
amount of training.

**Timing is not.** Discipline would fire less while cogs are still to
come and more in the last battle. It reads 51/55/58% with a fight ahead
against 33/53/0% at the end -- flat to backwards, and the right-hand
column has small n and should not be leaned on.

The split is the shape credit assignment predicts. `suited` is a fact
about the board in front of the agent, one step from its reward. "Hold
this slip for a battle eight rounds and a floor boundary away" is the
opposite, and it is where PPO at gamma=0.99 is weakest.

So the 42 points that slip conservation is worth are, for now,
unreachable from either direction: the lookahead route is closed by
realism and the training route reaches the target and not the timing.

## Two notes on method

**Small samples overstated an effect three times in one session.** A
40-seed run claimed +12.5 for the expectation scorer (+5.5 real) and
+7.5 for the slip price (+3.5, not significant); a 120-side run claimed
+12.5 for a wider climb window, which came back at EXACTLY zero on 240
fresh sides. The third one was on its way to being shipped. Nothing goes
in without a held-out set now.

**The original note, kept because it understated the problem:** a
40-seed sample overstated the effect twice, by roughly 2x, in the
same session -- once for the expected-value scorer (+12.5 claimed,
+5.5 real) and once for the slip price (+7.5 claimed, +3.5 real, not
significant). Paired 200-side runs with common random numbers and a sign
test are the minimum for anything that gets quoted.

**Watch for `sum(1 for r, _ in res)` without the `if r`.** It counts
every row regardless of the win flag and can only ever print 100%. It
was written twice during this audit, and the first time nearly got a
dead-flat sweep reported as a finding.
