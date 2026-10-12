# Audit of the party scorer (August 2026)

This is the record of an audit of how the solver scores a round when more
than one toon is in the battle. It found five defects, all of which were
fixed and remain fixed in the current code, and it refuted five plausible
improvements. It is kept as a record: the defects explain why several
constants have the values they do, and the refutations are the experiments
most likely to be repeated by someone who has not read them.

Status today: the scorer audited here, `_quick_score`, still judges the PPO
row's plans (`hybrid.climb`), and every fix below is in use. The numbers are
from August 2026 and several settings have changed since (the menu width,
the search budget, the shipped policy); those changes are noted where they
matter. Since 2026-10-11 the panel leads with the Playout engine, which does
not use this scorer to compare moves. [scoring.md](scoring.md) describes the
scorer as it stands.

All results are from simulated fights. Unless stated otherwise they are
paired on identical seeds, on seeds not used for tuning, at 200 sides a
cell; "+a/−b" counts the seeds that flipped each way and p-values are sign
tests.

## Terms

A **toon** is a player character and a **cog** an enemy. A **gag** is a
consumable attack; **laff** is hit points. **Lure** puts cogs to sleep,
**Trap** sets damage that a Lure springs, **Toon-Up** heals. A **pink slip**
removes a cog outright. A **Version 2.0** cog has a second health bar.

Three kinds of fight are measured. A **cog building** is several floors of
ordinary battles. The **Vice President (VP)** and the **Chief Executive
Officer (CEO)** are boss fights in which the toons split into two sides,
each fighting its own battle; a **side** is one of them. The CEO has a first
battle against twenty cogs per side, an unmodelled banquet phase, and a
second battle against a level 14 boss cog plus whatever cogs survived the
banquet. Those survivors are the **leftovers**, and their count is swept
because the banquet cannot be modelled.

The **PPO row** is a trained policy that proposes joint plans plus a
coordinate ascent, `climb`, that changes one toon's action at a time and
keeps what `_quick_score` prefers. "Plain" means the policy's own first
choice with no climb.

## Summary

The audit began by asking what was making parties lose the CEO, before
running another sweep. The answer was four bugs in the party path. A fifth,
found shortly afterwards, dwarfed them and meant every number first
published was inflated.

| Fight | First published | Corrected rule, all fixes |
|---|---|---|
| Cog buildings | 71.5% | **73.5%** |
| VP | 99.4% | **99.5%** |
| CEO, no leftovers | 88.9% | **88.5%** |
| CEO, 2 leftovers | | 73.5% |
| CEO, 4 leftovers | | 45.0% |
| CEO, 5 leftovers | 43.1% | 32.5% |
| CEO, 10 leftovers | 2.0% | 3.0% |

The CEO rows are one side of two. A four-toon fight needs both, so 88.5% a
side is 78.3% for the fight.

The headline looks unchanged, and that is the point of the table. The first
88.9% rested on a rule the game does not have. With the rule corrected the
same configuration no longer reached it, and the figure was earned back by
three further corrections, described under defect 5.

Solo play was correct throughout. That is most of why these bugs survived:
the tests and most earlier measurements were solo.

## What was ruled out first

Four candidate causes were measured before any code changed.

- **Not gag exhaustion.** Losing parties were wiped holding 163 of 172 gags.
- **Not hoarding pink slips.** Losses spent 0.61 slips a round against 0.70
  in wins. An earlier reading of "5 of 10 slips unused" was the fight ending
  sooner.
- **Not an unpriced toon loss.** All CEO losses were wipes, and the scorer's
  term for a toon in danger had weight zero. Sweeping that weight from 0 to
  240 moved nothing. (The term was later found to return zero on every
  position because of a bug, was fixed, and still changed no outcome; see
  [scoring.md](scoring.md).)
- **Not difficulty.** Mean cog level was 11.65 in wins and 11.73 in losses;
  party laff was 219 against 216.

Half the losses were over by round five, which pointed at the opening, where
accuracy varies most.

## Defects found and fixed

### 1. Both plan scorers assumed every gag hits

`_quick_score` and `_greedy_score` each scored a round in which every gag
landed. In a cog building that is nearly harmless, because accuracy runs 70
to 95% and barely varies by track. Against level 13 and 14 cogs it runs from
51% to 95%, and an all-hit score prefers the largest damage number, which is
reliably the least likely to land.

**Fix.** Both scorers now take the expectation over every way the dice can
fall, through one shared function, `_expected_over_rolls`. It enumerates
instead of sampling: accuracy is rolled once per (track, target), a party
has at most four toons, so there are at most 16 branches, and an exact
expectation cannot rank the same position differently on two calls. The
probabilities are read from the simulator's own record for each branch,
because accuracy is conditional:

| Situation | Accuracy |
|---|---|
| Level 7 Drop, nothing landed first | 54% |
| Level 7 Drop after a Throw landed | 79% |
| One level 6 Lure, then two together | 79%, then 95% |
| Level 6 Lure into an untrapped, then a trapped cog | 79%, then 95% |

**Effect.** On 200 CEO sides with no leftovers: 69.5% to 75.0% (+24/−13,
p = 0.049). A 40-side sample had read +12.5 points. The climb's cost went
from 1.7 to 3.3 ms a decision. In the sampling party search the same change
measured 73.3% to 73.3% at 794 to 1,245 ms a decision; it was kept there as
a correctness fix.

### 2. Forced accuracies did not survive a party round

Three accuracies are stated by the rules instead of computed: Trap always
hits, Throw and Squirt always hit a lured cog, and Drop always misses one.
The party round treated each as an ordinary total, added the bonus for an
earlier hit in the same round, and applied the 95% cap.

| Gag | Rule | Resolved at |
|---|---|---|
| Trap, after a heal landed | 100% | 95% |
| Throw into a lured cog, after a heal landed | 100% | 95% |
| Drop into a lured cog, after a Throw landed | 0% | 25% |

All three misfired only when something else had hit earlier in the round,
which is why 878 tests passed over them.

**Fix.** `mechanics.forced_accuracy` is the single place that decision is
made. The defect was found by printing the accuracies the simulator actually
used, which is what the `record` argument of `simulator.apply_party_round`
is for.

### 3. Every gag in a party round used the first toon's training

`simulator.toon_action_accuracy` read the first toon's track experience and
organic gags for whoever was throwing.

**Fix.** It takes the acting toon as an argument. No measured number moved,
because the boss samples used identically trained teams, where reading the
wrong toon gives the right answer. It was wrong for any mixed party.

### 4. Pink slips were free

The shortlisting scorer charged nothing for a slip. Measured, a side spent
all ten on the CEO's first battle and reached the second holding 0.3, which
was the whole reason ten leftovers sat at exactly 0%. The second battle on
its own, from full resources, cleared 93% at ten leftovers. On 40 sides
each:

| Entering the second battle | 10 slips | 0 slips |
|---|---|---|
| Full laff | 92.5% | 50.0% |
| 65% laff | 82.5% | 17.5% |

**Fix.** `FIRE_PRICE` charges 20 per cog still to come. The shape matters
more than the number. A flat price helped at five leftovers (38.0% to
49.5%, p = 0.008) and hurt at none (88.5% to 82.0%, p = 0.021), because it
also held slips back in the last battle, where an unspent slip is worth
nothing. A price proportional to what is still coming falls to zero at the
end.

**Effect.** Directionally supported, not proven: neutral at zero leftovers
(88.5% to 88.0%, p = 0.50), positive but not significant at five (38.0% to
41.5%, p = 0.22). It moves ten leftovers off 0% at every non-zero price
tried. A constant floor, `FIRE_FLOOR`, was added later for a different
reason; see [scoring.md](scoring.md).

### 5. A lured cog stayed asleep when hit

In the game a landed attack wakes a lured cog. The rule's cell in
`solver/mechanics.py`, `LURE_ENDS_ON_DAMAGE`, was unfilled, and the model
let a party dismantle a lured field without waking it. It is now `True`.

Correcting it broke more than the rule, because the scorer's prevention term
had been built on the old behaviour and its weight fitted against that. The
recovery took three steps, each recorded with its measurement in the code:

1. **The term.** `prevented` was rewritten to credit a Lure only for the
   quiet it actually buys: until the party gets round to hitting each
   sleeper.
2. **The weight.** `QUICK_W["prevent"]` was re-swept and moved from 2.0 to
   9.0. On the CEO with no leftovers that took 9.0% to 54.0% (p < 0.0001),
   with buildings at 66.0% to 67.0% and the VP unchanged.
3. **The reach.** Offering each toon the best action of every track it holds
   (`probe_tracks`) had been refuted twice under the old scorer. With the
   term and weight fixed it paid: buildings 65.0% to 73.5% (p = 0.0002), CEO
   with no leftovers 54.0% to 88.5%, with two 18.5% to 73.5%, with four 7.0%
   to 45.0% (all p < 0.0001).

Before step 3, Trap sat at a median rank of 25 in the policy's ordering and
was never inside the three-wide menu in 521 seats examined; Toon-Up sat at
rank 10 and was reachable 1% of the time. No weight could have fixed that,
which is why an earlier sweep of the heal weight read flat at twenty times
its value.

The order is the lesson: fix the model, then the weights, then the reach.
Done in reverse, each stage measures the previous stage's errors and refutes
a correct idea for the wrong reason.

`probe_tracks` is now on whenever more than one toon is standing and off
solo, where it measured worse.

## What the policy could not see

A question about adding boss positions to training turned out to have a
missing prerequisite. On the 290-number observation the policy was given:

- A Version 2.0 cog and an ordinary one encoded identically.
- Holding no pink slips and holding five encoded identically. The policy
  proposed 10.07 of its 10 slips per CEO side, with the legality mask the
  only thing that ever refused.
- Level 14 and 15 cogs fell outside the normalisation, which stopped at
  level 12 and 200 health.

The observation was widened to 302 numbers: a flag and a remaining-health
ratio per cog, a slip count per toon, and scales of level 20 and 476
health. This invalidated every exported policy and forced a retrain. The
policy the PPO row loads today (`solver/rl/ppo_facility.json`) still uses
the 302-number layout; the training environment has since moved on to a
wider one (`OBS_VERSION` 4, 318 numbers).

### Retraining on boss sides

Three seeds were trained with a quarter of episodes on boss sides and three
without, 6 million steps each, and scored on 180 held-out sides a cell:

| Fight | Mode | Control | Boss-trained |
|---|---|---|---|
| Buildings | climb | 66.3% | 69.6% |
| Buildings | plain | 61.7% | 60.6% |
| VP | climb | 99.4% | 99.4% |
| CEO, no leftovers | climb | 78.7% | 88.9% |
| CEO, no leftovers | plain | 46.7% | 73.9% |
| CEO, 5 leftovers | climb | 32.4% | 43.1% |
| CEO, 5 leftovers | plain | 7.8% | 35.2% |

This was the first change to the policy that moved the climb's results. An
earlier prediction in the audit had been that it would not: the climb gave
the same result at budgets of 8, 16, 32 and 64, so it looked saturated. That
only shows that more iterations do not help. Coordinate ascent from a
different starting plan reaches a different local optimum.

A buildings loss of 3.3 points on the first evaluation set (p = 0.033) came
from one outlying seed and reversed sign on the held-out set above.

### Why the boss-trained policy was withdrawn

The policy chosen from that batch, `boss_s2`, had been trained before defect
5 was fixed. It then beat every correctly trained policy on the CEO: 88.0%
against a best of 63.3%. Asked about the same 273 CEO positions, it proposed
a group Lure 83% of the time, where correctly trained policies proposed
Lure 0 to 14% of the time. It had learned Lure in a game where Lure was
overpowered, and the corrected scorer happened to want exactly that
proposal.

The structural cause is not a bug in either half. Training scores the
policy on its own first choices. Deployment uses it as a proposer whose
plans the climb then refines. A Lure followed by the policy's own next move
is weak, so a correctly trained policy learns to skip it; a Lure followed by
the climb's choice of follow-up is often the best move on the board.

It was withdrawn anyway, on the reasoning that a policy fitted to a rule the
game does not have is a liability whose failures cannot be predicted. A
second policy trained under a subtler wrong Lure rule was measured on 150
boards where that rule could matter: it proposed Lure 38% of the time
against 16 to 33% (mean 26%) for eleven correct-rule policies. That is one
policy, so it is a consistent pattern and not a demonstrated cause.

Giving up `boss_s2` first cost 25 points on the CEO. It turned out not to be
a trade. Later correct-rule seeds ranged from 26.5% to 68.0% on the CEO with
no leftovers, and the best held at 72.5% on seeds it was not chosen on. The
commit history shows the exported policy was last replaced on 2026-08-28,
with a policy trained with a penalty on overkill.

## Refuted ideas

### Pricing a pink slip at the use it gives up

A count cannot tell a level 10 cog from a level 14 Version 2.0, so the price
was rebuilt as an opportunity cost: holding $F$ slips, charge the value of
the $F$-th best cog you could fire instead. It needed no tuned constant. It
lost:

| CEO leftovers | Price per cog to come | Opportunity cost |
|---|---|---|
| 0 | 88.0% | 76.0% (+11/−35, p = 0.0003) |
| 5 | 41.5% | 28.5% (+20/−46, p = 0.0009) |
| 10 | 4.0% | 2.0% |

It behaved as designed and barely hoarded (9.00 slips fired against 9.85).
The slips it declined were the early ones, and a slip spent early stops that
cog attacking for the rest of the battle. The comparison priced what a slip
removes and ignored the laff it saves over time. A working version would
have to price the damage prevented from now to the end of the battle. The
code was reverted instead of being left behind a zero weight.

### That the CEO is lost by not healing

The agent threw no Toon-Up in 1,446 decisions across 40 CEO sides, including
99 rounds with the party under 35% laff. That is correct play.

Raising the heal weight from 2 to 40 did nothing (88.3% to 89.2% with no
leftovers), because at that time the climb could only reorder what the
policy proposed and the policy did not propose heals. Forcing heals onto the
menu did make it heal, and lost:

| Fight | Without | With | Toon-Ups per side | |
|---|---|---|---|---|
| Buildings | 71.7% | 70.0% | 1.31 to 1.82 | +4/−6, p = 0.38 |
| VP | 100.0% | 98.3% | 0.00 to 0.39 | +0/−2 |
| CEO, no leftovers | 88.3% | 80.8% | 0.00 to 0.56 | +4/−13, p = 0.025 |
| CEO, 5 leftovers | 37.5% | 30.8% | 0.01 to 0.91 | +15/−23, p = 0.13 |

The CEO's first battle is a damage race. With incoming damage proportional
to the cogs still standing, killing is the prevention, and a round spent
healing is a round the cogs attack for free. This measurement predates the
fix in defect 5; the same menu change later paid for other reasons, as
described there.

### Widening the climb's menu

Each toon was offered the policy's top three actions. Enumerating all 2,132
legal joint plans on one CEO opening showed the climb's choice ranked 17th,
within the top 0.8%.

Widening to five at a matched number of sweeps looked like a win on the
seeds that suggested it (CEO with 5 leftovers 37.5% to 50.0%, p = 0.022). On
240 fresh sides a cell it was not:

| Fight | Width 3, budget 8 | Width 5, budget 14 | Flips |
|---|---|---|---|
| Buildings | 69.2% | 70.0% | +12/−10 |
| VP | 98.8% | 100.0% | +3/−0 |
| CEO, no leftovers | 90.4% | 91.2% | +12/−10 |
| CEO, 5 leftovers | 48.8% | 48.8% | +50/−50 |

The baseline itself moved from 37.5% to 48.8% between the two seed sets, so
the first set was a hard draw. Raising the budget alone changed nothing.

This refutation is about parties in August and has since been overtaken for
one case. In September the default width was raised to 16 together with a
budget of 24, on a solo VP measurement (48% to 75% on 40 held-out runs,
p = 0.019) in which the exact search's preferred move had never been on the
three-wide menu. Buildings were unchanged by it.

The section also corrected itself. Its first draft named a best plan that
was illegal: the scorer does not check that a toon holds the gag, and a gag
with a count of zero was spent to a count of −1 with full damage. The
simulator now refuses a zero count the same way it refuses a missing one.

### Training more seeds and keeping the best

Eight policies differing only in training seed ranged from 23.3% to 62.5%
on the CEO with no leftovers, while their buildings results sat between
73.3% and 75.0%. The best of the eight on the selection set was then worse
on held-out seeds than the policy it was meant to replace: buildings 66.0%
against 72.5% (p = 0.005), CEO with two leftovers 42.0% against 53.0%
(p = 0.006). Taking the maximum of eight draws from a distribution that wide
selects a lucky evaluation, not a better policy.

### Refitting all the scorer's weights at once

`tools/fit_scorer.py` runs an evolution strategy over seven `QUICK_W`
weights against fights won. Over 45 generations on buildings, the VP and the
CEO with two leftovers, it took its fitting set from 73.3% to 79.2% and its
validation set from 70.4% to 70.8%. On a third set every cell was inside
noise. Its fitting set was 180 sides, against a CEO clear rate that swings
39 points between identically trained policies, so the optimiser was below
the noise floor of its own objective. The single-weight sweep of `prevent`
worked where this did not because it had a mechanism behind it, 120 to 200
sides a point, and an effect far above that floor.

For the record, it proposed `kill` 120 to 79.5, `prevent` 9 to 7.4 and
`risk` 0 to 3.06. None of it validated.

## What ends a losing CEO side

Measured again after the fixes, on 80 held-out sides at each leftover count:

| | 5 leftovers | 10 leftovers |
|---|---|---|
| Party wiped | 40 of 40 losses | 71 of 79 |
| No way left to damage a cog | 0 | 0 |
| Ran out of rounds | 0 | 8 |
| Gags left at the end | 150 of 172 | 140 of 172 |

Running out of gags is unreachable in practice: two toons throw two gags a
round, so a twenty-round fight spends about forty of 172. The heavy gags do
run low, but that does not separate wins from losses:

| Carried into the second battle | Level 6 and 7 attack gags | Laff |
|---|---|---|
| Sides that cleared | 20.6 | 172 |
| Sides that lost | 19.3 | 116 |

The whole separation is how much laff survives the first battle. A traced
win and a traced loss played the same plan with the same nine or ten slips;
one left the first battle on 139 laff and the other on 6. What differed was
the accuracy rolls, which fits the earlier finding that the opening draw
does not predict the outcome.

## What remains open

- **Ten leftovers is not solved.** Holding slips for the second battle costs
  laff in the first. At a slip price of 80 the party arrived with 6.2 slips
  but 42.8% laff, and 19 of 40 sides reached the second battle at all. The
  isolated measurements suggest the ideal line is worth about 42%.
  Fifteen and twenty leftovers read 0% at every price tried.
- **The scorer cannot see the next battle.** A state carries a count of cogs
  still to come and nothing else about them, so "save as many slips as the
  last battle needs" cannot be expressed. Looking ahead into a building's
  next floor is ruled out on principle: a player cannot see it, so the
  solver may not.
- **Training learned which cog to fire and not when.** The policy alone
  fired 62.2% of the time with a Version 2.0 present against 47.0% without.
  Its timing did not improve with a fight still ahead.
- **The scorer is one round deep.** Several entries here are that limit seen
  from different sides. The Playout engine, built in October, addresses it
  by playing fights out. On a benchmark labelled by those playouts, four
  random entries from the climb's menu beat the scorer's own top four.

## Notes on method

- **Small samples overstated effects three times in one session.** A
  40-seed run claimed +12.5 points for defect 1 (+5.5 at 200 sides) and
  +7.5 for the slip price (+3.5, not significant). A 120-side run claimed
  +12.5 for a wider menu, which was exactly zero on 240 fresh sides. Nothing
  is accepted without a held-out set.
- **A harness must raise, not substitute.** A measurement script that turns
  an action it cannot express into a pass reports a harness failure as a
  strategy failure.
- **A clean 0% or 100% everywhere is a reason to check the harness.** One
  counting expression without its condition could only print 100%. A probe
  built from positions with no cogs on the board reported zero for both arms
  of a comparison, which read exactly like agreement.

The full text of each section as originally written, including traces and
per-seed figures, is in [experiment-log.md](experiment-log.md).
