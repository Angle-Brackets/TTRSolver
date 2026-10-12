# Reward experiments for the PPO policy

This document records the changes tried to the reward the PPO policy is
trained on, what each one did, and the reward in use now. Most of them
changed how the policy plays without changing how often it wins, and one,
a charge for overkill, is part of the policy that ships. The formulas are in
[ppo-math.md](ppo-math.md) and the policy itself in
[ml-design.md](ml-design.md).

All results are from simulated fights. "Plain" means the policy playing its
own highest-probability move. "Climb" means the policy refined by the
one-round scorer, which is the form the panel's PPO row uses. Differences
are in percentage points of fights won.

## The reward in use

On the step that resolves a round the policy is paid

$$
r = -\ell \;-\; \sum_{g \in G} \big(c(g) + 6 \cdot \mathbb{1}[\text{level}(g) = 7]\big) \;-\; 1 \;+\; 100 \cdot \mathbb{1}[\text{won}] \;-\; 100 \cdot \mathbb{1}[\text{lost}]
$$

where $\ell$ is the laff the team lost, $G$ the gags spent, and $c(g)$ a
price that rises with the gag's level, with how few of it a toon can carry,
and with how many cogs are still to come after this battle. These are the
`BALANCED` weights of `solver/search/objective.py`.

The policy that ships (`solver/rl/ppo_facility.json`) was trained with one
further term, a charge for damage thrown past what a cog had left
(`--precision`). Its weight is not recorded: the file was exported before
the trainer began writing reward settings into the export. Every other
optional term described below is off by default.

Rewards are divided by a running standard deviation for learning. That is a
scaling, not a change to what is optimised, but it is listed first below
because it replaced something that was.

## Summary

| change | effect on behaviour | effect on wins | status |
|---|---|---|---|
| running-deviation normalisation in place of a fixed 0.01 scale | gag value spent per battle 4.49 → 4.17 | not the cause of the overspending it was aimed at | in use |
| horizon multiplier on gag price, with multi-floor episodes | none until episodes spanned floors | not measured in isolation | in use |
| potential shaping on incoming damage | Throw share 44.7% → 35.7% | none: 52.2% of buildings either way | off |
| potential shaping on toons standing, weight 25 | | climb −3.4, plain −1.2 | off |
| the same, weight 5 | | climb −3.9, plain −1.4 | off |
| penalty of 40 when a toon is lost | | climb −0.4, plain +2.6 | off |
| gag conservation terms set to zero | level 4 share 46% → about 34%, level 5 21% → about 31% | climb −0.7, plain +1.4 | not adopted |
| charge for overkill (precision) | first choice no longer always Drop; Lure 34% of first choices | solo VP 28.7% → 44.7%, buildings and CEO level | in use |
| charge per pink slip spent | slips no longer fill the whole shortlist | inside seed-to-seed variation | off, unjudged |

## Scaling and the horizon

**Normalisation.** The first trainer multiplied rewards by a fixed 0.01 to
keep the value loss in range. Gag prices run from 0.23 to 4.70 against a win
bonus of 100, so after scaling the whole range of gag prices was a few per
cent of the win signal. Over 120 battles the policy spent 4.49 of gag value
per battle against a search's 2.81 while winning less. Dividing by a running
standard deviation keeps the ratios between rewards intact. Spending fell to
4.17, against 2.60 for the search on the same ruler. It was a real defect
and it was not the mechanism behind the overspending.

**The horizon.** The price of a gag is multiplied by
$1 + 0.15 \cdot n_{\text{after}}$, where $n_{\text{after}}$ is the number of
cogs still to come after the current battle, and that count is in the
observation. Trained with this, the policy ignored it. Over 120 identical
battles it spent 4.17 at a horizon of 0 and 4.18 at a horizon of 30, and
moving the horizon from 0 to 30 at a fixed position changed its action in
4.3% of 394 positions.

The reason was structural. An episode ended when the battle ended, so a gag
saved was never spent later and conserving paid nothing. Under the reward
the agent was actually given, spending everything to win the current fight
was correct. The fix was to the environment, not the reward: a building or
a boss fight is now one episode across all its floors, with the same gags
and laff carried through, so a gag saved on one floor is spent on a later
one inside the same return.

The multiplier of 0.15 was chosen by a sweep: at 0.033 it changed
nothing, and past 0.15 the gags saved cost more
battles than they were worth (over 40 coordinated battles at a horizon of
30, multipliers of 0.033, 0.15, 0.5 and 1.5 won 70.0%, 67.5%, 62.5% and
52.5%).

## Shaping

Potential-based shaping adds $F = \gamma\,\Phi(s') - \Phi(s)$ to the reward
for some function $\Phi$ of the state. By the result of Ng, Harada and
Russell (1999) this cannot change which policy is optimal. It can change how
quickly credit arrives.

### Incoming damage

*Problem.* The policy had collapsed onto Throw: 49% of its gags against a
search's 32%, with almost no healing, trapping or dropping. A heal or a
lure pays later, so its advantage early in training is negative and it is
never tried enough to learn otherwise.

*Tried.* $\Phi(s) = -w \cdot (\text{expected laff the cogs take next round})$,
which pays at once for a cog lured or killed.

*Result.* Over 180 buildings the Throw share fell from 44.7% to 35.7%,
close to the search's 32.0%, and the buildings finished stayed at 52.2%.
Making the mix of gags look like the search's bought nothing. The gap was
not which gags are thrown in aggregate but which gag in which situation.

A later check found this term had not been potential-based across a
building: the potential was reset at each floor, so the sum did not
telescope over the episode. That is fixed, and the result above was
measured with the defective term.

### Toons standing

*Problem.* A building is decided by the first toon lost. In 50 buildings
played by each of two agents, every one of the 60 runs that lost nobody was
won, and about 7% of the runs that lost anyone were. The reward says almost
nothing about this at the moment it happens: the step a toon is lost is
charged only the laff of the final hit, roughly 20, and the loss penalty
does not arrive until the whole team is down, ten to twenty steps later.

*Tried.* $\Phi(s) = w \cdot (\text{toons standing})$ with $w = 25$, then
$w = 5$ to rule out the objection that 25 made the potential as large as the
win bonus. Three seeds each, 6 million steps, paired on three held-out sets
of 120 buildings against the policy shipped at the time.

*Result.* Worse at both weights: −3.4 and −3.9 with the climb. Across six
training seeds and eighteen set comparisons, every one was negative with the
climb.

This does not contradict the theorem. The theorem is about the optimum, and
PPO does not reach it; shaping changes the path of optimisation, and here it
made the path worse. The likely mechanism is that the number of toons
standing is already in the observation. The shaping told the policy nothing
it could not see and only moved credit that the critic was already learning
to assign.

### A plain penalty for the same event

*Tried.* `toon_lost_penalty = 40`, charged on the step a toon is lost. This
is not potential-based and can change the optimum.

*Result.* Plain play improved by 2.6 points, positive in seven of nine set
comparisons. With the climb it did not move (−0.4). The risk that an
unguarded penalty would make the policy passive did not appear at this
size.

The contrast with the shaping result suggests a working rule: shape what the
agent cannot observe, and reprice what it can.

## Gag conservation

*Problem.* Two terms exist to stop the policy running out of gags: the
scarcity term in the gag price and the horizon multiplier. In the 60 runs
above that lost nobody, none ran out of gags.

*Tried.* Both set to zero. The premium on level 7 gags was left at 6.

| | baseline | conservation off |
|---|---|---|
| share of gags at level 4 | 46.0% | about 34% |
| share of gags at level 5 | 20.9% | about 31% |
| share of gags at level 7 | 3.5% | 3.4–3.5% |
| gags thrown | 3,433 | 3,484–3,776 |
| runs that ran out of gags | 0 | 0 |
| toons lost per building | 0.86 | 0.77–0.85 |

*Result.* Wins did not move (climb −0.7, plain +1.4, mixed signs). The
policy shifted from level 4 to level 5 gags and still never ran out. At the
pouch sizes tested, the conservation terms guard against a failure that does
not occur, and they cost nothing measurable either. Level 7 use did not
change, because it is governed by how rarely the policy proposes one, not by
price. The terms were kept.

## Overkill

*Problem.* The reward charged for laff and for gags spent, and nothing for
damage thrown past what a cog had left. The policy would spend a large gag
on a nearly dead cog as readily as on a full one. Its proposals had also
collapsed: the previous policy put Drop first on 100% of opening boards and
had Lure in its top three on 2%, while the climb, choosing from those
proposals and its own probes, played Drop 0% of the time and Lure 67%.

*Tried.* A charge proportional to the wasted share of the round's damage,
scaled by how scarce the wasted gags are, so a gag that is the only thing
that kills pays almost nothing. It was put in the reward and not in the
scorer, because a scorer weight only reorders what the policy already
proposes.

*Result.* The collapse broke. Lure became 34% of first choices and 18% of
the shortlist, and the top three spanned five tracks instead of three. On
300 held-out fights per cell, with the climb's per-track probes off so that
the proposals were what was being measured:

| fight | before | after | p |
|---|---|---|---|
| building | 232 / 300 | 229 / 300 | 0.82 |
| solo VP | 86 / 300 | 134 / 300 | < 0.001 |
| CEO | 14 / 300 | 12 / 300 | 0.82 |

With the probes on, the gain was invisible (p = 0.54 and 0.90): the climb
had already been routing around the bad shortlist. The climb now runs with
those probes off for a lone toon and on in a party, so the solo VP gain is
measured in the setting that is used. The VP here is an earlier and smaller
model of that fight than the one the project uses now.

Two alternatives were run for the same problem and failed. Retraining on the
corrected mix of positions alone left the collapse in place (Drop 97% of
first choices). Track entropy at 0.05 with damage shaping at 0.5 made it
worse (Throw 100%).

This policy is the one that ships.

## Pink slips

*Problem.* A pink slip removes a cog outright and uses the toon's turn. The
reward had never priced one, so the policy learned that a slip is a free
kill. On a solo VP (an earlier model of the fight, eight cogs a round) with
ten slips its four highest-ranked moves were all slips, and the win rate
fell from 49.5% with none to 0.0% with ten.

*Tried.* A charge per slip spent, at 8 and at 25, with the same seed and
mix as the shipped policy.

| slips held | 0 | 5 | 10 |
|---|---|---|---|
| shipped policy | 49.5% | 22.0% | 0.0% |
| charge of 8 | 31.5% | 1.5% | 0.0% |
| charge of 25 | 28.0% | 15.5% | 3.5% |

*Result.* The charge removed the collapse in the shortlist. It was first
read as costing twenty points with no slips held (31.5% and 28.0% against
49.5%). That reading was wrong. Ten other training runs put the same
measurement between 21.0% and 38.0%, mean 30.2%, standard deviation 5.0. The
runs with the charge sit inside that range. The shipped policy is the
outlier, 3.8 standard deviations above the mean of the rest, because it was
chosen for shipping on this very measurement.

The term is unjudged, not refuted, and stays at zero. The slip problem was
addressed at play time instead, by having the climb widen its menu whenever
the policy's shortlist is all one kind of move.

## What the experiments say together

**For a time, policy changes did not reach the climb.** Through the
experiments of mid-August the climb sat at 68 to 69% of buildings whatever
was done to the policy:

| change | plain | climb |
|---|---|---|
| retrain on corrected carry limits | +2.8 | +1.2 |
| penalty for a lost toon | +2.6 | −0.4 |
| conservation terms off | +1.4 | −0.7 |
| survival shaping | −1.4 | −3.9 |
| track entropy (a loss term, not a reward term) | −4.5 | +1.1 |

The scorer re-ranks whatever it is handed, and on positions it already
handles well the quality of its input stops mattering. The only change that
helped the climb made plain play worse, by giving the scorer more varied
candidates to choose from.

**That conclusion was later bounded.** It held for buildings. Adding boss
fights to the training positions moved the climb by 9 to 11 points on the
CEO, and the overkill charge moved the solo VP by 16. Where the policy's
proposals were badly wrong, improving them reached the agent.

**One training run cannot be compared with a shipped policy.** A shipped
policy was selected, usually as the best of several seeds on some
measurement, so on that measurement every fresh run looks like a regression.
The slip-charge result above is the worked example. A change to the reward
has to be judged between distributions of runs: several seeds with the
change and several without, differing in nothing else.

**The trainer's own evaluation does not predict any of this.** Across ten
seeds the return printed during training correlated with CEO win rate at
r = −0.43 (n = 10, not significant, and in any case not positive). It scores the policy on its own first choice over the training
mix, while play uses the policy as a source of candidates for the climb.
