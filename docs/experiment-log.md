# The experiment log

**What was tried, what it measured, and what lost.**

This file exists because the docs were shortened, and this is the part
that does not survive shortening. What the code does can be read off the
code; what was tried and abandoned cannot be, and without it the same
idea gets rebuilt a third time. Several entries below are the record of
a change that was built, measured and thrown away. Those are the
valuable ones.

Every section is VERBATIM from the docs as they stood before the
simplification pass, under its original heading and the file it came
from. Nothing is re-worded: a number that has been paraphrased is a
number nobody can check.

Figures are paired win rates on sampled sides unless a section says
otherwise, and "+a/-b" counts discordant seeds. A p-value with no stated
seed base is a SELECTION number, not a confirmation -- the discipline
this project settled on is to select on one base and confirm on another,
and the older entries predate it.

---

## From docs/scorer-audit.md

### 1 -- both plan scorers assumed every gag hits


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

### 4 -- pink slips were free, so the party never had one left


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

### Refuted -- pricing a slip at the use it gives up


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

### Retraining on boss sides -- and the first policy change to reach the climb


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

### Refuted -- that the CEO is lost by not healing


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

### Refuted -- widening the climb's candidate window


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

### The anomaly explained: trained solo, deployed as a proposer


`boss_s2` was trained under the BROKEN Lure rule and beat every
correctly-trained policy on the CEO -- 88.0% against a best of 63.3%
across nine of them, while matching on buildings and VP. It is not the
leftover range, not seed noise, and not the scorer weight.

The cause shows up the moment every policy is asked about the SAME
positions rather than about boards each built itself. 273 shared CEO
positions, argmax proposal per seat:

| policy | lure | trap | throw | squirt | group | fires |
|---|---|---|---|---|---|---|
| **boss_s2** | **83%** | 0% | 8% | 1% | **98%** | 218 |
| v2_s3 | 14% | 12% | 33% | 27% | 37% | 478 |
| v4_s18 | 0% | 0% | 55% | 30% | 30% | 471 |
| v3_s5 | 0% | 11% | 63% | 24% | 42% | 427 |

`boss_s2` proposes a group Lure four times in five. Every correctly
trained policy proposes single-target attacks and lures 0-14%.

It learned that where Lure was overpowered, and `prevent=9` -- validated,
worth +45 -- wants precisely that behaviour. Its wrong training happens
to produce what the climb is looking for.

**THE STRUCTURAL CAUSE, WHICH IS NOT A BUG IN EITHER HALF.** Training
scores the policy on ITS OWN argmax play. Deployment scores it as a
PROPOSER the climb then refines. Those two jobs reward different
behaviour.

To be exact, because "plays alone" is the wrong phrase for it: PPO is
trained on parties throughout -- 16% of positions are solo, 31% two
toons, 26% three, 28% four, and both boss sides are two. The policy is
`coordinated`, so one network chooses for every toon in turn while
seeing a 36-float `pending` block of what its teammates have already
committed this round. It coordinates with itself perfectly well. What it
never sees during training is THE CLIMB.

So a Lure it throws in training is a Lure followed by whatever its own
argmax picks next, which is usually another attack rather than the
attack that exploits it. Scored that way, Lure genuinely is weak and the
policy correctly learns to skip it. In deployment the climb can pair the
Lure with its follow-up, at which point Lure is the best move on the
board. The correctly trained policies are not worse: they are right
about the game they were scored in and wrong about the job they were
given.

It also explains why probes and pairs do not close the gap. They can
reach a Lure the policy ranks low, but the climb still STARTS from the
policy's argmax plan, and a sweep beginning on four single-target
attacks does not walk to a coordinated Lure line -- the same
starting-point argument that motivated joint moves.

**What would fix it**, none of it cheap: train with the climb in the
loop, so the policy is scored on the play it ENABLES rather than the
play it performs; or shape training toward what a searcher wants, which
means deciding that in advance rather than learning it; or generate boss
candidates without the policy at all.

Shipped: `v2_s3`, correctly trained, 63.5% on CEO 0. `boss_s2` is not
shipped and should not be -- an 88% resting on a rule the game does not
have is a number about our old bug.

### Refuted -- training more seeds and picking the best


Eight seeds at the better leftover range, scored on a SELECTION set, and
the winner re-measured on held-out seeds it was not chosen on.

The selection spread is the first thing to look at: CEO at zero
leftovers ran from **23.3% to 62.5%** across eight policies differing
only in their training seed, while buildings sat inside a two-point band
(73.3-75.0%). A thirty-nine point range on one fight.

`v4_s18` won the selection at 62.5%. On 200 held-out sides a cell it
lost:

| set | v2_s3 | v4_s18 | |
|---|---|---|---|
| buildings | **72.5%** | 66.0% | +5/-18, p=0.005 |
| VP | 99.5% | 99.0% | ns |
| CEO 0 | 63.5% | 67.5% | +37/-29, p=0.19 |
| CEO 2 | **53.0%** | 42.0% | +24/-46, p=0.006 |
| CEO 4 | 24.0% | 18.0% | +19/-31, p=0.06 |

**Taking the maximum of eight draws from a distribution that wide
selects the friendliest selection draw, not the better policy**, and the
advantage does not transfer -- it is worse on buildings and on CEO 2,
both significantly.

This is the same shape as fitting a weight on the set you then report,
and it is worth naming separately because "train more seeds and keep the
best" is the obvious next move and it does not work here. What the
spread actually says is that a single CEO number cannot distinguish two
policies at this sample size. Distinguishing them needs either many more
evaluation sides or an evaluation that is not one high-variance fight.

`v2_s3` stays shipped.

---

## From docs/scoring.md

### The bug the sweep found first


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

### The fix, and why the gate is now structural


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

### SCARCITY_UNITS: swept, and left at 20


[OWNER] "It should be weighted by the fact you can carry 7 \$10 bills and
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

### Why there is no group-waste penalty


On a one-cog board a group gag and a single gag score IDENTICALLY --
`$1 Bill single` and `$1 Bill GROUP` both read 1785.26 on the reported
Ambulance Chaser position. The model has no concept of a group gag
wasting its breadth; the only things separating two lures are level and
carry limit, through `_gag_units`.

That has a visible consequence. Asked what happens when the pouch holds
nothing below Big Magnet, the panel advises **Big Magnet GROUP** on the
lone cog, because at `4 + 20/15 = 5.33` it is cheaper than a \$10 Bill at
`5 + 20/7 = 7.86`. Which is arguably right -- a toon carries 15 Big
Magnets and 7 \$10 Bills, so spending the magnet is the better resource
decision even though it is the "group" gag. From \$10 Bill up it picks
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

### How good a ranker is `_quick_score`? Good -- and I got this wrong first


It is what `hybrid.climb` judges with, what `tools/fit_scorer.py` tunes,
and what `train_heads.py` was fit against, so most of this file rests on
it ordering moves well. It had never been measured against outcomes.

**Method.** For each sampled position take the best candidate of each
track, so the candidate set is not chosen by the thing under test. Play
the candidate, finish the battle, repeat K=16 times on the SAME board
with INDEPENDENT dice, and score the candidate by how often it won. Then
compare that ordering with `_quick_score`'s.

| difficulty | positions | rho | picked the best | best | scorer | random | worst |
|---|---|---|---|---|---|---|---|
| 5 | 3 | +0.696 | 3/3 | 1.000 | 1.000 | 0.990 | 0.938 |
| 7 | 13 | +0.701 | 13/13 | 1.000 | 1.000 | 0.977 | 0.923 |
| 9 | 94 | +0.545 | 88/94 | 0.991 | 0.987 | 0.887 | 0.755 |

**It captures 96-100% of the gap between chance and best**, with rank
correlations of +0.55 to +0.70. On the largest sample it picks the best
candidate in 94% of positions and gives up 0.004 of win rate.

### `survive` re-run on realistic toons: 400 holds


The last of the three weights still resting on maxed-toon measurement.
Re-run the way `FIRE_FLOOR` and `SOS_PRICE` were -- on the toons
`facility_position` actually builds, mean training 4.65 and 4.71,
parties of two to four matched to their street, 250 runs a cell, paired
on seeds:

| survive | block A | block B |
|---|---|---|
| 0 | 77.6% | 74.4% |
| 100 | 81.6% (+12/-2, p=0.013) | — |
| 200 | 86.0% (+21/-0, p<0.001) | 84.4% (+25/-0, p<0.001) |
| **400** | **87.2% (+25/-1)** | **84.0% (+25/-1)** |
| 800 | 87.2% (+26/-2) | 84.8% (+26/-0) |

Monotone to 200 and flat after, on both blocks -- the same shape the
maxed-toon sweep found. 400 sits mid-plateau and stands.

All three weights flagged as maxed-toon-dependent have now been re-run
and all three held. The bias was real as a limitation of method and
changed none of the values.

### What the scorer gets wrong at difficulty 9, and why it stays wrong


The corrected ranker study left one lead: difficulty 9 is where the
stakes are real (worst candidate 0.755 against best 0.991) and where
`_quick_score` is least sharp (rho +0.545, wrong on 6 of 94).

**All six misses are the same mistake.** On a fresh board -- 3 or 4
cogs, none lured, none trapped -- it takes a long group Lure where the
outcomes prefer group Sound:

| seed | scorer picked | won | MC-best | won | score gap |
|---|---|---|---|---|---|
| 770015 | Presentation/all | 0.88 | Railroad/all | 0.94 | +1042.6 |
| 770032 | Presentation/all | 0.94 | Railroad/all | 1.00 | +918.8 |
| 770059 | Presentation/all | 0.94 | Railroad/all | 1.00 | +1049.1 |
| 770091 | Presentation/all | 0.94 | Railroad/all | 1.00 | +1072.6 |
| 770104 | Wedding Cake/all | 0.94 | Railroad/all | 1.00 | +706.1 |
| 770110 | Presentation/all | 0.94 | Railroad/all | 1.00 | +914.9 |

Decomposed on seed 770032 (four cogs, levels 10/9/11/10):

    Presentation/all   0 damage, 0 kills, prevented 144.7 x 9.0 = 1301.9
                       total 1898.5
    Railroad/all     360 damage, 0 kills, prevented   0.0        =    0.0
                       total 1003.7

So it is `QUICK_W["prevent"] = 9.0`: a point of prevented damage is
worth nine of dealt damage, and an eight-round group Lure on four cogs
prevents a great deal.

### Observation v3 is unproven, and the training metric disagrees with play


`env.OBS_VERSION` is 3, so every policy trained today uses it. **Nothing
trained at 3 has ever shipped.** The shipped policy carries no
`obs_version` key at all -- it predates the field -- and
`hybrid._load` defaults it to 1, which matches its 302 dims, so it
works by default rather than by record.

v3 adds ABSOLUTE remaining laff to each toon block (four per-toon
scalars to five, 302 -> 306). Three training seeds at v3 against the
same three at v2, judged on the toons `facility_position` builds:

**With consumables, near the ceiling -- no signal:**

| seed | obs2 | obs3 | paired |
|---|---|---|---|
| 51 | 97.2% | 97.6% | +3/-2 |
| 52 | 97.2% | 97.6% | +4/-3 |
| 53 | 97.2% | 96.8% | +2/-3 |

**Without them, where the cell discriminates.** The first block read as
v3 losing every pair, and at three more blocks that does not hold:

| block | seed | obs2 | obs3 | paired |
|---|---|---|---|---|
| 770000 | 51 | 74.8% | 73.2% | +7/-11 |
| 770000 | 52 | 73.6% | 71.6% | +9/-14 |
| 770000 | 53 | 76.0% | 74.8% | +8/-11 |
| 660000 | 51 | 75.6% | 74.4% | +8/-11 |
| 660000 | 52 | 73.6% | 73.6% | +12/-12 |
| 660000 | 53 | 74.0% | 74.4% | +13/-12 |
| 880000 | 51 | 74.4% | 73.6% | +9/-11 |
| 880000 | 52 | 71.6% | 73.2% | +14/-10 |
| 880000 | 53 | 74.0% | 74.4% | +14/-13 |

Pooled over all nine: **+94/-105, p=0.478**, mean **-0.49 points**, and
v3 loses 5 of 9. **Indistinguishable.**

The first block alone read -1.60 and 3 losses from 3, which is what was
reported here before. That was one block of noise presented as a result,
and it is the same mistake this file warns about elsewhere: three paired
runs is not a sample.

**The training-time metric says the opposite.** `eval_return` at export:
obs2 averaged 35.90, obs3 averaged 40.51, and v3 won all three pairs.
The same disagreement that sank the learned plan-ranker -- an offline
number flattering a model that then loses in play.

**Left at 3**, now on better grounds than before. It is not worse; it is
the same, and the argument for it is one the measurement cannot see:
the two features it replaces are a RATIO and a CEILING, and what decides
a fight is their product — 0.5 of 137 survives a Legal Eagle, 0.5 of 40
does not. A linear layer cannot multiply, so handing it the product is
strictly more information for four more dimensions.

Same shape as `SCARCITY_USES_HELD_COUNT`: neutral on measurement, kept
on the argument, labelled as such.

The shipped policy still does not use it — it predates the field
entirely and carries no `obs_version` key — so anything trained from
here diverges from what ships until a v3 policy is trained and
promoted. That, not the observation, is the open item.

### `SLEEPERS_WAKE_IN_TURN`: the extrapolation is settled, and it was right


It shipped on a judgement call -- it helped at 12 cogs a round and HURT
at 8 -- and the note has said so ever since. Re-measured now that the
landscape has moved (budget 24, consumables on, `survive` at 400):

**Ordinary facility play: statistically neutral.** 250 runs a cell on
two seed blocks: 88.0% against 86.8% (+1/-4, p=0.375) and 84.4% against
84.8% (+1/-0, p=1.000). Only a handful of seeds move either way, which
is what you expect from a flag that changes the lure's MARGIN without
flipping the argmax -- it moves `prevented` from 110.54 to 174.87 and
the score by 550 points on a sampled board, and still decides almost
nothing outside the VP.

> An earlier version of this paragraph claimed +0/-0 across 500 games.
> That was a broken harness sweeping `SOS_PRICE` instead of this flag;
> see the note at the end of this file.

**Solo VP, where it was actually argued over, 200 runs a cell, paired:**

| cogs a round | reach ON | reach OFF | paired |
|---|---|---|---|
| 8 | 99.0% | 99.0% | +0/-0 |
| 12 | 100.0% | 99.5% | +1/-0 |
| 16 | 93.0% | 66.5% | +58/-5, p<0.001 |
| 16 (held out) | 85.0% | 67.5% | +47/-12, p<0.001 |
| 20 (held out) | 26.5% | 15.0% | +40/-17, p=0.003 |

**The old worry is gone and the flag is strongly justified.** At 8 cogs
it no longer hurts -- it is exactly neutral -- and at 16 and 20 it is
worth 17 to 27 points. The original reading was taken before the search
budget was raised, before consumables existed and with `survive` at
zero; the conditions it was extrapolating from are not the ones that
ship.

Four flags -- this one, `LURE_IS_SPENT_ON_SLEEPERS`,
`LURED_KILL_SILENCES_NOTHING` and `SURVIVAL_CAP` -- now carry a pointer
in `weights.py` to `party_search.prevented`, where their reasoning
actually lives. Moving the constants out separated them from the
docstring that argues them.

### Should scarcity price the carry limit or what the toon holds?


[OWNER], looking at a pouch with nine Big Magnets: "shouldn't it be
scaled by 9 not 15, since that's how many magnets I actually have."

The two answer different questions. `carry_limit` prices how replaceable
the gag TYPE is and does not move as the pouch drains. The held count
prices what you would miss right now, and rises as you spend. Held is
never above the limit, so switching only ever makes gags dearer, and
dearest exactly when you are down to the last one.

**On that pouch it changes no ordering**, which is worth saying first:

| gag | carry | held | by carry limit | by held count |
|---|---|---|---|---|
| Big Magnet | 15 | 9 | 5.33 | 6.22 |
| \$10 Bill | 7 | 6 | 7.86 | 8.33 |
| Hypno-goggles | 3 | 3 | 12.67 | 12.67 |
| Presentation | 1 | 1 | 27.00 | 27.00 |

Implemented behind `SCARCITY_USES_HELD_COUNT` and measured, paired on
seeds. Solo VP at 12, 16 and 20 cogs, where pouches actually drain:
**+0/-0 every cell.** Facility play, 250 runs a cell on two blocks:
88.8% -> 88.0% (+1/-3) and 85.2% -> 84.4% (+1/-3), p=0.625 both.

**Directionally negative, and not significant.** Re-measured at four
times the sample -- four seed blocks, 1000 runs a cell:

| block | carry limit | held count | paired | gags spent |
|---|---|---|---|---|
| 440000 | 88.8% | 88.0% | +1/-3 | 14.2 -> 14.0 |
| 990000 | 85.2% | 84.4% | +1/-3 | 16.1 -> 15.5 |
| 660000 | 88.4% | 88.0% | +2/-3 | 15.1 -> 14.7 |
| 770000 | 87.6% | 88.0% | +2/-1 | 13.7 -> 13.5 |

Pooled **+6/-10, p=0.454**; mean **-0.40 points**; negative in 3 of 4
blocks. So it is not the +0/-0 first reported here (that came from a
broken harness, see the end of this file), and it is not significant
either — it is a small negative that a larger sample has not resolved
into anything.

**It does do its job**, which is the part worth keeping: 2.4% fewer gags
spent, consistently, in every block. That is conservation working as
designed and simply not converting into wins at this price weight —
consistent with everything else here, since the whole price term is
under 5% of the score.

Shipped, on the argument rather than the number. Recorded so nobody
later reads it as evidence-backed.

### Why it changes nothing, which is the real finding


**The entire price term is a median 4.79% of `_quick_score`** (mean
5.53%, max 13.24% across 120 boards). The scarcity half of it, at its
most extreme — a last Big Magnet going from 5.33 to 24.00 — moves
18.67 points on a score around 1500, or **1.24%**. Damage and prevention
dominate by two orders of magnitude, so no scarcity rule at this weight
can flip an argmax.

That also explains the earlier `SCARCITY_UNITS` sweep coming out a wash
from 0 to 150. It is not that the scarcity *rule* is wrong; it is that
the scarcity *lever* is far too short to steer with.

### `QUICK_W["price"]` swept — and it cannot be tuned on its own


Asked to sweep it after establishing that scarcity is too short a lever
to steer with. It stays at **1.0**, and the reason is structural.

**`QUICK_W["price"]` does not price gags. It prices everything.** The
`price` it multiplies is assembled from three sources in `_score_leaf`:

    price  = sum of _gag_units over the gags spent   (line ~930)
    price *= 1 + horizon_cost * cogs_remaining
    price += _fire_price(...) * fires spent          (line ~953)
    price += SOS_PRICE * sos calls                   (line ~965)
    ... - QUICK_W["price"] * price

So turning it down does not make the solver freer with gags; it makes
gags, pink slips and SOS cards free together, nullifying `FIRE_PRICE`,
`FIRE_FLOOR` and `SOS_PRICE` in one move.

That is exactly what the first sweep measured, and it looked like a win:

| price | win | gags | slips |
|---|---|---|---|
| 0.0 | 91.6% / 89.6% | 10.2 | 16.5 |
| **1.0** | 88.0% / 84.4% | 14.0 | 17.1 |
| 2.0 | 83.6% | 12.4 | 18.6 |
| 4.0 | 76.4% | 10.0 | 19.9 |
| 16.0 | 60.0% | 6.8 | 20.5 |

Zero beating one on both blocks (p=0.022, p=0.015) is not a finding
about gag conservation. It is unpriced consumables.

**Isolated** — same sweep with no slips, unites or cards, so the
multiplier only reaches gags:

| price | block A | block B | gags |
|---|---|---|---|
| 0.0 | 68.8% | 62.8% | 28.6 / 30.9 |
| **1.0** | **68.4%** | **62.0%** | **27.7 / 28.1** |
| 0.5 | 67.2% | 61.2% | 27.6 / 29.2 |
| 2.0 | 68.0% | 60.8% | 26.7 / 27.1 |
| 4.0 | 64.4% (p=0.052) | 54.8% (p<0.001) | 24.6 / 25.8 |

Anything from 0 to 2 is indistinguishable; 4 clearly hurts. Higher does
conserve — about 15% fewer gags at 4.0 — but buys nothing with it.

**1.0 stands.** And the real finding is the coupling: conservation
cannot be tuned without unpricing consumables, so if gag thrift is ever
wanted, the fix is to split the multiplier rather than to move it.

### The price multiplier is split: `price` for gags, `spend` for consumables


They shared one, which made `QUICK_W["price"]` a trapdoor rather than a
knob: lowering it to loosen gag thrift also zeroed `FIRE_PRICE`,
`FIRE_FLOOR` and `SOS_PRICE`. `_score_leaf` now builds `gag_price` and
`spend_price` separately and scales each by its own weight. The horizon
still multiplies the pouch only, which is what it always did.

**1.0 and 1.0 reproduce the old arithmetic exactly** — the refactor lock
is clean across all eleven pinned values, which is the point of doing it
this way.

The split immediately corrects a false reading. With consumables on:

| price | win | gags | before the split |
|---|---|---|---|
| 0.0 | 86.8% (+6/-9, ns) | 15.5 | 91.6% (+11/-2, p=0.022) |
| **1.0** | **88.0%** | **14.0** | 88.0% |
| 2.0 | 87.2% (+5/-7, ns) | 11.9 | 83.6% |
| 4.0 | 82.0% (+4/-19, p=0.003) | 10.4 | 76.4% |

`price=0` looked like a win and was unpriced consumables. It is now
indistinguishable from 1.0, which is the truth, and matches what the
consumables-off isolation already said.

**A usable conservation knob appears.** `price=2.0` spends 11.9 gags
against 14.0 at no significant win cost — about 15% of the pouch, for
0.8 points that do not survive a sign test. That trade was invisible
before, because raising `price` also made the solver hoard slips and
cards it should have been spending.

### `spend`: kept at 1.0, and NOT to be swept for win rate


| spend | win | gags |
|---|---|---|
| 0.0 | 92.4% (+12/-1, p=0.003) | 10.1 |
| **1.0** | **88.0%** | **14.0** |
| 2.0 | 83.2% (+2/-14, p=0.004) | 15.4 |
| 4.0 | 80.4% (+2/-21, p<0.001) | 15.9 |

Free consumables win by four points, significantly. **That is the
expected answer and not a reason to change anything**, for the reason
`solver/sos.py` already states: cheaper cards always clear more, and the
search would be right about the number while spending a currency farmed
from whole boss runs. [OWNER] slips are for bosses; cards are a last
resort. The price encodes reluctance, not win-maximisation.

What the split buys is that this preference is now expressible on its
own axis, instead of riding on the knob that also governs the pouch.

### Six fresh policies: nothing to promote, and v3 buys nothing


Three training seeds at observation v3 and the same three at v1, 6M
steps each, paired by seed. The question was whether a v3 policy should
be trained and promoted, since `env.OBS_VERSION` is 3 and the shipped
policy predates the field entirely.

**Training-time `eval_return` favours v1, 3 of 3:**

| seed | v3 | v1 | v1 − v3 |
|---|---|---|---|
| 71 | 35.47 | 44.58 | +9.11 |
| 72 | 41.05 | 43.46 | +2.41 |
| 73 | 37.24 | 41.35 | +4.11 |
| mean | 37.92 | **43.13** | **+5.21** |

**Held-out play says they are the same.** 250 runs a cell, paired:

| cell | v3 | v1 | paired |
|---|---|---|---|
| with consumables | 96.4% | 96.4% | +10/-10, p=1.000 |
| without (discriminating) | 70.1% | 71.2% | +26/-34, p=0.366 |

That is the THIRD time `eval_return` and play have disagreed in this
project, and the second time in opposite directions — it preferred v3 in
the earlier comparison and v1 here, while play called both even.
**Stop reading `eval_return` as a ranking.** It is a training-progress
signal.

### Nothing is promoted


Every fresh policy beats the shipped one in the discriminating cell, by
1.2 to 4.0 points — and not one of them significantly:

| policy | win | vs shipped |
|---|---|---|
| SHIPPED | 68.8% | — |
| fresh obs3_s71 | 70.4% | +12/-8, p=0.503 |
| fresh obs3_s72 | 70.0% | +12/-9, p=0.664 |
| fresh obs3_s73 | 70.0% | +10/-7, p=0.629 |
| fresh obs1_s71 | 70.4% | +12/-8, p=0.503 |
| fresh obs1_s72 | 70.4% | +13/-9, p=0.523 |
| fresh obs1_s73 | **72.8%** | +18/-8, **p=0.076** |

All six landing above shipped is suggestive, but they share eval seeds
and conditions, so a sign test across policies is not valid — the paired
tests are, and the best reads p=0.076.

**Promoting that one would be exactly the selection that produced the
outlier we already have.** Best-of-six at p=0.076 is a lottery ticket,
not a result. The shipped policy stays.

What this does settle: the shipped policy is **not** the 3.8 sd monster
it is described as, at least in this cell, where it is the worst of
seven. That reputation came from a different measurement and should not
be carried into new comparisons unexamined.

`OBS_VERSION` stays at 3 — there is no evidence to move it either way,
and this file's own rule is that a shipped value does not move on a
wash. But there is now no positive case for v3 beyond the argument that
a linear layer cannot multiply a ratio by a ceiling.

---

## From solver/search/hybrid.py (code removed 2026-10-05)

Both of these were switched off for measured reasons and their code was
removed in the consolidation pass. The text below is what the code
said, verbatim.

### `rollout_judge` -- PPO rollouts as climb's judge

```
Play the plan, then let PPO play on, and total the real reward.

The horizon `_quick_score` does not have. It scores ONE round --
expected over the accuracy rolls, not all-hit; this said all-hit
long after that changed -- with a hand-weighted sum whose weights turn out not to
matter -- four random weight vectors finish 62.5-65.0% of the same
buildings, and zeroing every term costs five points. So the terms
matter and their sizes do not, which is what a flat proxy looks
like.

This scores the future with `round_reward` instead: the objective
the environment actually pays, over several rounds of PPO's own
play. It is Bertsekas's rollout with the learned policy as the base,
which is what makes the guarantee interesting -- a rollout policy is
no worse than its base when the evaluation is sound.

NOT the two-ply judge that failed earlier. That one let
`greedy_plan` answer for the next round, and greedy is a myopic
proxy, so it added a guess about the future to a real reading of the
present and weighted the guess at 0.7. It cost nearly three points.
PPO is a considerably better base policy than greedy, and it is fast
enough to run several rounds.

COMMON RANDOM NUMBERS. Every candidate plan is rolled out from the
same `seed`, so the accuracy rolls and cog attacks are identical
across candidates and the comparison is paired. Without that the
climb would reliably pick whichever plan drew the luckiest dice,
which with eight candidates is most of them.

IT IS OFF, AND THE REASON IS THE USEFUL PART. Over 180 held-out
buildings, climb at budget 8:

    `_quick_score`, one round      64.4%   0.76 ms
    PPO rollout, two rounds        61.1%   2.50 ms
    PPO rollout, four rounds       60.6%   3.23 ms

Deeper is monotonically worse, and cost is not the issue at three
milliseconds. The judge is: scoring a plan by what happens when PPO
PLAYS ON measures how well PPO exploits the resulting position, not
how good the position is. A strong plan leading somewhere PPO
handles badly is marked down. It is circular.

Third time that has been established here. PPO's own critic ranking
PPO's samples: 57.8-58.3% against 58.9% for plain argmax. A two-ply
lookahead played by `greedy_plan`: nearly three points worse. This:
three to four points worse. The only judge that has ever helped is
`_quick_score`, which shares none of the proposer's blind spots and
is worth 58.9% to 64.4%.

It is also why the SEARCH works: `rollout_value` plays forward with
`greedy_plan`, a different policy from the plans it grades.

The horizon idea is not refuted, only this way of getting one --
Toon-Up use does rise 4.1% to 5.3% with rollouts on, so the longer
view pushes where it should. What is refuted is asking the policy to
grade itself.

```

Superseded by `solver/search/playout.py`, which fixes the three things
that sank this one: it plays to the end of the fight rather than 2-4
rounds, scores cogs defeated rather than a reward with no credit for
damage, and averages 8-32 rollouts with common random numbers rather
than one seed. Solo VP 7% -> 55-70% (see `playout.py`).

### `RESTOCK_LOOKAHEAD` -- crediting a restock SOS with next round

```
A RESTOCK IS JUDGED ON WHAT IT ENABLES NEXT ROUND -- the one exception
to scoring a single round, and a narrow one on purpose.

`_quick_score` sees a round. A restock SOS call deals nothing and
prevents nothing in the round it is played, so it scored exactly
`SOS_PRICE` below a pass, and on a solo VP that had spent its power
gags "wait for the lure to lapse, re-lure, wait" beat climbing out of
the hole forever. Measured on that board: pass 672.7, Restock All 422.7.

NOT the general two-round judge, which is off for a measured reason:
it adds a guess about next round to EVERY plan and cost buildings three
points. This touches only plans that call a restock, and credits only
the DIFFERENCE between next round with the restock and next round
without it (the same plan with the call replaced by a pass). With a
full pouch that difference is near zero, so a restock stays the bad
move it is; with an empty one it is large.

SWEPT, AND NULL. Solo VP, realistic loadout, 100 paired sides with
common random numbers: 13/100 off, 14/100 on, +4/-3, sign test
p = 1.00. It did make restocks happen (0.00 -> 0.63 a side) and cards
get spent a little more, but clears did not move. Kept, off, so the
next attempt starts from a measured baseline rather than from zero --
and because that sweep ran blind to the boss structure, which by
itself cost 13 -> 5. Worth re-sweeping once live boss state exists.
```

### The gag menu's hover card as a third check -- tried, not shipped (2026-10-05)

Hovering a gag replaces "Total gags N / M" with that gag's card, whose
"N / M" line states the hovered gag's count exactly. The idea was to use
it as a check on the cell under the cursor, the one most likely misread.

Reading the card's count worked on the recorded building run ("7 / 7",
"4 / 10", "0 / 20"), once ink was taken by brightness, fragments joined
by column, and the line split clear of the gag's picture. Identifying
WHICH cell the card describes did not: matching the card's picture
against every cell's picture, backgrounds painted out, won by margins of
0.002-0.11 and named the wrong cell on most frames (the Safe as Throw 5,
a Throw 1 the toon did not carry). The card's capacity alone is
ambiguous whenever two gags share a carry limit.

Not shipped: a reader that names the wrong cell would overwrite a good
count with another gag's. `panel_memory` already resolves the cursor
case on 42 of 45 recorded menu frames; the rest are a menu's first frame,
which the panel's retry covers. A future attempt needs a better way to
name the gag -- reading the card's title text, or the cursor's position.


## Expert iteration, round 2: the fast network learns the playouts' moves

1,000 solo fights (VP, building, street) labelled by the Playout engine
itself -- 27,449 decisions -- mixed at 3x weight into the shipped
network's 345,693 climb rows, same architecture (384 hidden, 20 epochs).
Held-out agreement 70.4%, not comparable with the shipped 79%: the
held-out rows now include playout labels, which are harder to copy.

Paired solo VPs, playouts played on by each network:

    seeds 100000-100099   shipped 52   candidate 61   +28/-19
    seeds 100100-100299   shipped 123  candidate 129  +46/-40
    all 300               shipped 175  candidate 190  +74/-59  p = 0.22

On its own, as an instant answer, neither network is usable (6/100 and
5/100). Not shipped: a 5-point lead that 300 paired fights cannot
separate from chance. If tried again, the labels are the lever -- 27k
playout decisions against 346k climb ones may simply be too few to move
the network off climb.

## Unites were never spent in simulation -- and they decide VPs

`climb` applies its chosen unite to the board it is handed, and every
playout, sweep and data tool handed it a copy, so the unite was dropped
and the round played without it (fixed in 9f634a2, 598bfd9). Every VP
figure before this was measured with unites unusable -- including the
"solo VP 55-70%" that the playout engine was tuned against.

Paired, playouts, the owner's VP pouch (`vp.OWNER_VP_POUCH`):

    duo VP side, 60 fights    no unites 33   5 unites 55 (92%)   +22/-0
    solo VP, 100 fights       no unites 57   5 unites 94 (94%)   +38/-1

Five unites is the owner's own solo test budget. The solo regime also
carries three slips and a ten-card SOS deck. This is the first figure
back above 90% since the old 12-cog, two-toon, full-information VP, and
the owner's "a duo VP is trivial" now matches the model.

What the earlier hunt ruled out on the way: the loadout (owner's pouch
vs the level-first fill, +5 solo, p 0.51) and Lure accuracy (70-95%
against level 8-12 skelecogs, from the wiki's formula). Laff was always
the binding constraint -- losses ended with 65-78 gags unthrown -- and
unites are the laff.

## A unite-aware fast network: stronger alone, no better in the playouts

2731e4e gave the rollout network unite inputs and a unite head. Trained
on 354k new climb-labelled decisions with unites in hand (one DAgger
round) plus the old 345k rows padded with "no unites": gag agreement
with climb 82.8% (shipped 79%), unite agreement 96% (about 80% is "none").

Paired, the owner's pouch and five unites:

                            shipped net    unite-aware net
    solo VP, playouts       94/100         93/100   +6/-7   p 1.00
    duo VP side, playouts   55/60          49/60    +2/-8   p 0.11
    solo VP, net alone       6/100         22/100
    duo VP side, net alone   9/60          24/60

Alone it is far stronger -- it heals itself -- but as the playouts'
rollout player it is no better and 40% slower (the unite head, and a
board clone whenever it uses one). Not shipped. A guess at why: the
playouts' job is to RANK first moves, and a continuation that spends
unites on every candidate's behalf narrows the differences the ranking
reads. The code stays: weights without a unite head never use one.

## Groups with unites, and the shipped network re-checked

Every toon holding five unites; in the fight teammates always use what
they hold, and the arms differ only in whether the ENGINE assumes so.

    CEO side, coordinated, 40       engine ignores mates' unites 37   models them 37   +3/-3
    party building, pickup, 100     ignores 64                       models them 68   +5/-1  p 0.22

The CEO side was 11/30 for the playouts before unites could be spent at
all; with them it is 37/40 either way. Modelling the teammates' unites
changes the engine's choices little -- it is the unites themselves that
decide group fights, as they did solo.

The unite-aware network (shipped in d3c18f4 on realism, against a
non-significant dip) on 200 fresh duo VP sides:

    old network 167/200   unite-aware 163/200   +18/-22  p 0.64
    with the first 60:  old 222/260  new 212/260  +20/-30  p 0.20

Still within noise, still slightly behind, and 55% slower a decision
(1.88 s vs 1.21 s). Kept, on the owner's reasoning; if a later sweep
makes the gap significant, the old weights are in git (2731e4e^).

## The panel's preset in the playouts (bfc7fe2)

Each preset scales the playouts' laff weight, pouch weight and a per-round
charge by its own numbers relative to Balanced. Paired:

    my-building, 200     balanced 149   conserve 147   survive 142
                         speedrun 141   glass cannon 140  (p 0.08 at worst)
    solo VP, 60, owner pouch + 5 unites
                         balanced 57 (46.5 rounds)   conserve 57   glass 56
                         survive 55   speedrun 53 (38.4 rounds)

Speedrun does what it says -- 17% fewer rounds in a VP for 4 losses in 60.
Conserve is identical to Balanced in a VP, as it must be: the pouch is
only valued where a fight continues past the playout (buildings). No
preset beats Balanced on wins, which is expected -- Balanced is the
measured setting and the others trade wins for what they ask for.

## Open-loop MCTS over your own decisions: not better than flat playouts

`search/mcts.py`: the tree holds sequences of your plans; each iteration
draws its own future, descends by PUCT (root menu = `wide_candidates`,
uniform priors; deeper menus = the fast network's top 4 with its
probabilities), expands one node and lets the network play on. Same
budget as `pick_wide` (168 playouts); on a sample VP board it grew 12
decisions deep and took 2.8 s against 2.3 s. Paired, owner pouch, no
unites:

                    flat    c=0.7   c=1.5   c=3    c=6
    duo VP, 100      52      38      49      42     46
    solo VP, 100     61      51      56      --     --

No setting beats flat; c=0.7 is significantly worse (p 0.04). A tree
splits the same playouts across many nodes, so the root's estimates get
noisier, and the deeper nodes add little because the network's prior is
peaked (82% on one move is common) -- below the root the tree mostly
re-plays the network's own choice. Open-loop averaging over divergent
futures also blurs the deeper decisions. Kept as a module and a sweep arm
(`mcts`), not wired into the panel. Revisit with a value network
(truncated rollouts buy more iterations) or a much larger budget.

## A network teammate model (`party.NetTeammate`)

Pickup teammates from the fast network, from their own seat, spread over
its top 4 moves. The sweep separates how teammates play in the fight
(`truth`) from what the engine assumes (`assume`). 200 party buildings:

                         assume prior   assume net
    truth = prior             96            93
    truth = net              101           101

What the engine assumes makes no measurable difference; network
teammates simply play a little better. `SensiblePrior` stays the default
(it is also ~45% faster a decision); `NetTeammate` is available.

### MCTS with more budget: budget is not what it lacks

Same 100 duo VP sides, owner pouch, no unites, each method given 1x, 2x
and 4x the playouts (flat: stages 8/16/32, 16/32/64, 32/64/128 =
168/336/672; MCTS: iters to match):

                1x     2x     4x
    flat        52     63     60
    MCTS        49     51     49    (vs flat 2x: p 0.05 and 0.02)

MCTS stays near 50 whatever its budget while flat improves, so the tree
is not underfed. The likely cause is structural: below the root, PUCT
picks among the network's top 4 by design, so the in-tree follow-up is
deliberately worse than the network's own play, and the open-loop tree
blends divergent dice into one node. A retry needs chance nodes and
the network's argmax below the root until a node is well visited.

The other finding: flat playouts gained 11 wins from 2x budget on duo
VPs, so cheaper playouts are strength -- which is what a value network
that truncates rollouts would buy.

## Squeezing depth out of the exact search

`tools/search_bench.py` (depth / agree / fight). Positions: maxed toon,
owner pouch partly spent, 30-137 laff, 1-4 cogs of level 6-12 at random
health, street battles. Fully exact, time per decision:

    cogs   d1      d2      d3      d4
    1      0.01s   0.24s   6s      >60s
    2      0.02s   2.8s    >60s
    3      0.07s   22s     >60s
    4      0.11s   42s     >60s

What changed and what it bought:

  * Profiled hot spots, exact: `can_still_damage` (a third of a search)
    checks the common case first; `features` caches its pouch-only
    answers per toon. 60/60 answers identical, 1.5x.
  * A memo kept across a fight's rounds (`best_action_iterative(memo=)`):
    exact, but barely helps -- median 6.5s -> 4.7s, mean unchanged --
    because the new board's NEXT level was never searched before; only
    the cheap shallow work is reused.
  * Cog-order symmetry: not done -- permuted boards only collide when
    the cogs are identical, which the key already merges.
  * `expectimax.BEAM`: below the root, only the top k moves by a one-
    round look-ahead. Against fully exact search at depth 3:
        1 cog,  k=6: 100% same move, |dv| 0.003, 1.75x
        1 cog,  k=4:  93%,                       1.9x
        2 cogs, k=4 and k=6: 100%, |dv| 0.000, 2x
  * The cog-damage collapse the panel already uses (`exact_plies=0`)
    plus k=6, against fully exact at depth 3:
        1 cog:  100% same move, |dv| 0.004, 86s -> 4.6s
        2 cogs: 100% same move, |dv| 0.005, 534s -> 6.4s
    Keeping the first ply exact was no more accurate and 4-13x slower.

Depth reached (mean of 3 positions, 60s cap):

                     collapse only            collapse + k=6
    cogs   d3     d4      d5            d3     d4      d5
    1      0.3s   1.9s    9.6s          0.2s   0.8s    3.0s
    2      1.0s   5.5s    27s           1.0s   4.0s    13s
    3      2.9s   14s     >60s          2.9s   10s     30s
    4      6.7s   35s     >60s          7.1s   23s     ~55s

The panel already collapses (depth 4 cap, 15s budget), so live it reaches
depth 4 at two cogs and 3 at three or four. k=6 would put three cogs at
depth 4 and two at depth 5 inside the same budget. Not switched on yet:
agreement is measured, play is not, and the older note in advise.py
(extra depth changed nothing over 42 three-cog battles) says depth alone
may not show up as wins -- which is what the value network is for.
