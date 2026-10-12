# Learning the leaf evaluator for the exact search

The exact search (`solver/search/expectimax.py`) cannot reach the end of
most battles, so it stops at a depth limit and scores the position there
with a **leaf evaluator**. This document records how that evaluator went
from two hand-written terms to a linear model fitted on exactly solved
positions, the bug that made the first fit partly circular, and the later
attempts to replace the linear model with a network.

Status today: the fitted linear model is in use as the Search row's leaf.
Its weights were last changed on 2026-08-15 and have not been refitted
since, although rules have changed. The learned network that was built to
replace it is in the code and switched off, because it did not play better.
The Search row itself is no longer the engine the panel leads with; since
2026-10-11 that is the Playout engine, which judges moves by playing fights
out and uses a value network of its own to cut those playouts short.
[search-depth.md](search-depth.md) describes the search and
[scoring.md](scoring.md) lists the current features and weights.

Terms: a **toon** is the player's character, a **cog** an enemy, a **gag** a
consumable attack carried in a limited pouch, and **laff** hit points.
**Lure** puts a cog to sleep and **Trap** sets damage that a Lure springs.
Values are on the search's scale, where winning is +100, losing is −100 and
a point of laff is 1.

Figures of error and agreement below come from exact search on sampled
positions. Win counts come from simulated fights.

## Why the leaf mattered

Everything else in the solo solver is either transcribed game data or exact
arithmetic over it. The leaf evaluator was the one guessed component, and at
the depths the search could afford nearly every line ended at one.

The hand-written evaluator, still present as a fallback, is

$$v(s) = 100 \cdot \text{cog progress} - 100 \cdot (1 - \text{laff kept})$$

where cog progress is the share of the cogs' total health already removed
and laff kept is laff over maximum laff.

Compared with exactly solved values on 45 random positions:

| | |
|---|---|
| Mean of the evaluator | −6.5 (range −66 to 63) |
| Mean of the true value | 93.7 (range 67 to 100) |
| Bias | −100.2 |
| Mean absolute error | 100.2 |
| Correlation with the true value | 0.44 |
| Pairs of positions ordered correctly | 70% |

The bias is not noise. The evaluator scores a position relative to "full
laff, cogs untouched = 0", while the true value of a winnable position
includes the +100 the battle is on course to pay. Inside the search that
does damage: a line that reaches a win scores +100 and a line that runs out
of depth scores about −6, so finishing is flattered against anything that
merely looks good at the horizon.

It also scored positions identically that are not worth the same:

| Position | Hand-written | Exact |
|---|---|---|
| Damage focused, one cog nearly dead | −18.8 | 68.5 |
| Damage spread, same total cog health | −18.8 | 89.8 |
| Four gags against one cog | −35.4 | 99.0 |
| One gag against one cog | −35.4 | 92.0 |
| Cog lured for three rounds | −35.4 | 99.6 |
| Cog awake | −35.4 | 98.9 |

Summed cog health hides where the damage went, and what matters is how many
cogs the pouch can kill, which is a threshold. Gags remaining do not appear.
Lure and Trap do not appear.

### Cost was not the constraint

On a three-cog depth-2 search the evaluator was called 81,202 times and
accounted for 0.09 s of 4.67 s:

| Evaluator | Per call | Per search |
|---|---|---|
| Hand-written | 1.08 µs | 0.09 s |
| Linear over about 100 features | 1.05 µs | 0.09 s |
| Network 100-64-32-1, one position at a time | 6.7 µs | 0.5 s |
| Same network, 256 positions at a time | 0.44 µs | 0.04 s |

A linear model is free and a small network is affordable without batching.

## Labels

The advantage here over most learned evaluators is that the labels can be
exact. Gags are spent and never restocked, so a battle's state graph has no
cycles, and `expectimax.solve` plays a small position to the end without
consulting any evaluator. `tools/fit_heuristic.py` samples positions, solves
each one, and fits by ordinary least squares. Positions that exceed a time
budget are dropped, not approximated.

The catch is that exact solving is only tractable on small positions.
Training positions have one or two cogs and two or three kinds of gag;
the hold-out set is deliberately larger, up to three cogs and four kinds of
gag, because extrapolation to bigger fights is the failure this approach is
most exposed to. A model fitted on small positions still has to be used on
four cogs and a full pouch, and nothing here measures that directly.

### The first labels were not exact

The first fit rested on a claim that turned out to be false. `solve` did not
always play to the end of the battle. A line also stopped when the pouch
emptied with cogs still standing: there were no legal actions, and the
search returned the leaf evaluator's estimate at exactly the point it was
supposed to have stopped estimating. One such hopeless position scored
+47.6.

Re-solving 300 cached training positions under two different evaluators
changed 83% of the labels, by 3.7 points on average. Under exact labelling
none can move. The labelling tool used whichever evaluator was installed,
and by the time the 5,000-position set was built that was the fitted model.
So the model was partly being trained on its own output.

The problem surfaced as an impossibility: a regret figure computed its
reference with the fitted weights installed and its comparison without, and
came out negative.

What that did and did not invalidate:

- The **calibration** finding stood. A 100-point bias is far larger than 3.7
  points of label noise.
- The **features** stood. Kill thresholds, gags remaining and the trap and
  lure conjunction are real distinctions however the targets are computed.
- The **weights** did not, and were refitted.
- The **first agreement figures** did not. They were reported as move
  agreement with exact play rising from 86% to 92% over 120 fights, regret
  falling from 243.8 to 7.4, and search time falling from 10.6 s to 6.1 s.
  Those were measured against a reference that was not ground truth, and
  they were not re-measured afterwards.

### The fix: no way to damage a cog is a loss

The fix was a modelling decision. A toon with no remaining way to damage a
cog has lost as surely as one at zero laff, and
`BattleState.can_still_damage` now makes that a terminal state:

| Pouch | Verdict |
|---|---|
| Empty | Loss |
| Lure only, however many | Loss |
| Toon-Up and Trap only | Loss; nothing springs the trap |
| Trap and Lure | Not a loss; the pair works where neither half does |
| Lure only, with a cog already trapped | Not a loss |
| A gag in a track the toon has no training in | Loss |

Labels stopped depending on the evaluator, and the search got faster,
because a dead end became a cutoff instead of a subtree:

| Position | Before | After | Speedup |
|---|---|---|---|
| Toon-Up and Trap only, one cog | +87.8 | 0.0 | 400× |
| Toon-Up and Trap only, two cogs | +55.9 | 0.0 | 260× |
| Lure-heavy, no attacks | +99.4 | 0.0 | 2,200× |
| Throw runs out mid-line | +53.3 | −101.8 | 4× |
| Mixed pouch, no dead end in the horizon | +83.5 | +83.5 | 1.2× |

The zeros are terminal states whose −100 was already paid on the transition
into them. The fourth row is the one that matters for play: two Throws
cannot finish the cog, the rest of the pouch cannot damage it, and the old
evaluator called the position a win in progress.

The exception is the **pass**. With Trap and Lure in the pouch against a cog
that is already lured, there is nothing useful to throw, yet the fight is
won by waiting for the lure to lapse, then trapping and luring again. On
that fight exact search went from −100.6 to +94.3 by passing three times.
A pass is therefore a legal move. Today it is offered whenever a cog is
lured, and otherwise while a small budget of passes lasts, which keeps the
state graph free of cycles. The first version was narrower.

The fix was verified, not assumed. Re-solving 400 positions under three
evaluators (the fitted weights, the hand-written form, and one with a −500
intercept) moved 0% of labels, and the three runs took the same time, which
is the other sign that an exact solve never calls the evaluator.

Two more holes of the same shape turned up on the way. The label cache was
keyed on the rule files but listed neither the file that decides when a
battle ends nor the objective. And both evaluators recognised a terminal
state only by zero laff, so a dead-end position at full laff went to the
linear model, which is the worst case for extrapolation.

## The fit

Fitted on 5,000 exact labels and scored on 526 larger hold-out positions:

| Model | Bias | Mean absolute error | Correlation | Pairs ordered correctly |
|---|---|---|---|---|
| Hand-written | −51.0 | 95.9 | 0.07 | 52% |
| Linear, 15 features | +10.1 | 50.6 | 0.69 | 90% |
| Linear, plus two budget features | +0.9 | 25.6 | 0.86 | 91% |

The second row is the like-for-like refit. The third adds
`damage_budget_ratio` (damage the pouch can still deal over remaining cog
health) and `cannot_finish` (that ratio is below 1). They were prompted by
`gags_ratio` coming back with a weight of 244 on a scale where a win is 100:
one feature standing in for a question it could not answer. With the two
features that ask it directly, `gags_ratio` fell to 12.75 and the error
halved.

The model in the code today has 18 features. The comment beside its weights
records 5,000 training positions and 406 hold-out positions:

| Model | Bias | Mean absolute error | Correlation | Pairs ordered correctly |
|---|---|---|---|---|
| Hand-written | −51.2 | 94.3 | 0.07 | 53% |
| Fitted, 18 features | +4.5 | 24.3 | 0.78 | 89% |

The features and their weights are tabulated in
[scoring.md](scoring.md#the-leaf-evaluator). Inference is a dot product in
pure Python, so the solver core keeps its standard-library-only dependency
set; numpy is needed to fit, never to run.

### What a sharper evaluator cost the search

A model that can say "full laff, but this pouch cannot finish the fight"
returns values the hand-written form never could. The search's pruning
assumed a leaf could not fall below a floor set by laff alone. The fitted
model returned −98 at a node the bound put between 0 and 100, the search cut
branches it had no warrant to cut, and pruned and exhaustive search returned
different values (48.66 against 46.63).

Two things fixed it. The pruning floor now asks the installed evaluator for
its own minimum (`expectimax.heuristic_floor`). And the fitted value is
clamped to $[-100 - \text{max laff},\ +100]$; unclamped, it put 32% of
random positions outside the search's bounds, as high as 175.7.
`tests/test_search.py` pins pruned search equal to exhaustive search.
Pruning survives the looser bound: it cuts 2.0× with the fitted evaluator
against 1.3 to 1.4× with the hand-written one.

### Trap positions, and three wrong hypotheses

The evaluator's worst errors were on positions with an armed trap and a Lure
in hand, where the error ran to about 200 points. Three fixes were tried
before the cause was found:

| Attempt | Mean absolute error on 40 such positions | Worst error |
|---|---|---|
| An explicit trap-and-lure conjunction feature | 34.1 (worse) | |
| A small network in place of the line | 17.6 | 196.4 |
| A feature for the trap's size (`trap_damage_ratio`) | 22.7 to 22.0 | 203.5, unchanged |

The cause was a bug in a feature. A trap leaves the pouch when it is laid,
and the damage budget read only the pouch, so laying a trap dropped the
budget to zero and switched on `cannot_finish`, weight −99.95, in a winning
position. Counting armed traps took the error on those positions from 22.7
to 16.0. The two trap features that had been compensating for the bug
collapsed toward zero when refitted (from +90.6 and −32.6 to +0.04 and
−0.45), and the network stopped beating the line (17.6 against 16.7).

The worst case barely moved, 203.5 to 202.7. Those positions hinge on a
single accuracy roll, and a static feature vector cannot express a coin flip
with a large spread.

### A network instead of a line: not on this much data

Five models on the same 500 labels, scored on 97 larger hold-out positions:

| Model | Parameters | Training error | Hold-out error |
|---|---|---|---|
| Linear | 15 | 15.2 | 18.9 |
| Quadratic | 135 | 9.0 | 21.9 |
| Network, 16 hidden units | 273 | 9.4 | 19.3 |
| Network, 32 hidden units | 545 | 8.1 | 18.5 |
| Network, 64 hidden units | 1,089 | 7.2 | 22.3 |

Every nonlinear model fitted the training set better and none of it carried
to the hold-out. The best beat the line by 0.4 on 97 positions, which is
noise. That is too little data for the parameter counts, not evidence that
interactions are absent: the linear model sees the trap and lure interaction
only because the product was written out by hand. This comparison was run on
500 labels and was not repeated on the 5,000-label set.

## A learned network for the leaf (October 2026): three tries, none better in play

By October the search's move had been shown to stop changing by depth 4 on
single battles, so the remaining gain was expected to be in the leaf.
`solver/search/valuenet.py` holds a network that can stand in for the fitted
model. It is off (`valuenet.USE = False`). Each version was judged by
playing the Search row at 2 s a decision against the fitted leaf, on paired
simulated fights.

**1. Labels from deep search.** 27,667 boards from street battles, buildings
and solo Vice President (VP) boss fights, labelled by search at depth 5, 4,
4 and 3 for one to four cogs. Held-out error was 11.5 against the fitted
leaf's 36.6. In play:

| Fights | Fitted leaf | Network |
|---|---|---|
| 200 buildings, the maintainer's toon | 146 | 145 (+3/−4) |
| 200 solo buildings | 21 | 16 (+1/−6, p = 0.13) |
| 60 two-toon VP sides | 6 | 8 (+6/−4) |

A third of the error bought no better choices. Picking a move needs the
difference between sibling boards, often under a point, against a median
error of 3.7.

**2. Labels from whole fights.** 68,030 boards labelled with the reward
collected to the end of the fight under a fast rollout policy, six
continuations each. Worse in play: 4 against 7 on the VP sides, 138 against
146 on the first buildings set (+3/−11, p = 0.06). Fights ended sooner. In
the search's units a long fight's accumulated damage outweighs the −100 for
losing, so dying early scored better.

**3. The same with a lost fight worth −1000.** Still worse: 3 against 8 on
the VP sides (+0/−5, p = 0.06), 140 against 144 on buildings. The units were
not the whole story. The labels describe the rollout policy's own play,
which loses most VP fights alone, so most boards look alike, and six noisy
continuations cannot rank sibling moves.

The same experiment produced the more important finding. On those two-toon
VP sides the Search row never won more than 8 of 60 with any leaf, and the
Playout row won 33 of 60. The search sees only the cogs on the field, so labels from a
deeper search carry the same blind spot.

### What did work: a value network inside the playouts

The idea was then moved to where the horizon is not a problem. A network
trained in the playouts' own units (cogs defeated to the end of the fight
plus a laff term, under the rollout policy) scores the rest of a fight after
a playout has run for a fixed number of rounds, so that more playouts fit in
the same time.

The first version lost, and lost more the earlier the cut: on 60 solo VP
fights, stopping after 4 rounds won 19 against 37 for full playouts
(+1/−19). The network saw the board as the panel does, without the count of
cogs still to walk in, which in a VP swings between 16 and 0. With that
count and the later-wave count as inputs, held-out error barely moved (1.34
against 1.37 cogs) and play did: stopping after 8 rounds won 175 against 163
of 260 solo VP fights (+56/−44, p = 0.27) in 28% less time a decision.

That network is in use (`playout.ROLLOUT_DEPTH = 8`,
`solver/rl/playout_value.json`). It is not a leaf for the exact search, and
the win difference was not statistically established; the case for it is the
time saved.

## Parties

`features.extract` pools over the toons still standing, so the fitted model
returns a number for a party position. With one toon the feature vector is
bit-identical to the solo one, checked over 300 sampled positions, which
keeps the fitted weights valid. With more than one toon the values are
defined, not validated: exact solving cannot reach a party position, so
there are no labels to check against.

On a maxed team the evaluator is saturated. Over the successors of three
plans on a maxed four-toon position it read 98.03, 98.96 and 96.73, while
the plans finished the fight 87%, 98% and 95% of the time. The party search
(`solver/search/party_search.py`) therefore values a position by playing it
out. A separate network, the value head in `solver/search/policy.py`
(trained by `tools/train_heads.py` on values found by that search), can
replace the rollout when a caller asks for `leaf="learned"`; the default is
the rollout.

## What is in use now

| Component | Where | State |
|---|---|---|
| Fitted linear leaf, 18 features | `solver/search/fitted.py` | In use by the Search row |
| Hand-written leaf | `expectimax.hand_written_value` | Fallback if the weights are missing or mismatched |
| Learned network leaf | `solver/search/valuenet.py` | Built, off; three versions did not play better |
| Value network for shortened playouts | `solver/rl/playout_value.json` | In use by the Playout row |
| Party value head | `solver/search/policy.py` | Optional leaf for the party search; not the default |

## Known limits

- **The weights are stale.** The fitted weights date from 2026-08-15. The
  comment beside them says to refit whenever a rule change alters what an
  exact label means. Rules have changed since, including a landed attack
  waking a lured cog (2026-08-21), and the file's history shows no refit.
- **Small positions only.** Labels exist for one to three cogs and a handful
  of gags from nine mid-level kinds. Live positions are larger.
- **One objective.** Labels are solved under the default objective. The
  evaluator is used unchanged under presets that weight laff or gags
  differently.
- **Collinear features.** Several features fire together, and least squares
  splits them arbitrarily. Individual weights should not be read as effects.
- **Formulas fitted to playout outcomes failed.** Two later attempts to fit
  a one-round scoring formula to labels produced by playouts took a solo VP
  win rate from 7% to 3.6% and to 0.4% in simulated play. That work was on
  the one-round scorer, not this evaluator, but the lesson is the same as
  the network's: a label for one decision holds only while the player that
  produced it plays the rest of the fight.

## Reproducing

```
python tools/fit_heuristic.py --positions 400
```

The tool prints a block of floats to paste into `solver/search/fitted.py`.
The order must match `features.FEATURE_NAMES`; the weights are positional.
The full record of the October network experiments is in
[experiment-log.md](experiment-log.md).
