# The PPO policy: design, training and standing

This document covers the policy network behind the panel's PPO row: why a
policy was learned at all, what it observes and outputs, how its training
environment draws positions, how it is trained, how it is used at play time,
and how it measures against the other two engines. The policy is in use
today in two roles. It gives the panel an answer within milliseconds, and it
supplies candidate moves to the Playout engine, which is the engine that
leads by default.

Related documents: [ppo-math.md](ppo-math.md) for the formulas,
[reward-experiments.md](reward-experiments.md) for the reward ablations,
[rollout-network.md](rollout-network.md) for the two networks inside the
Playout engine, and [playout.md](playout.md) for that engine.

Every result here comes from simulated fights. Nothing was measured in the
live game.

## Where the policy sits

The panel shows three engines side by side.

| row | what it is | code |
|---|---|---|
| PPO | the policy network described here, refined by a short local search called the climb | `solver/search/hybrid.py` |
| Search | expectimax over the battle tree, with a time budget | `solver/search/expectimax.py` |
| Playout | Monte Carlo playouts of each candidate move to the end of the fight | `solver/search/playout.py` |

The learned models, and where each stands:

| model | weights | role | status |
|---|---|---|---|
| PPO policy | `solver/rl/ppo_facility.json` | proposes moves for the climb; the climb's output is the PPO row and the first entry on the Playout engine's menu | in use |
| rollout network | `solver/rl/fast_player.json` | plays out the rest of each fight inside a playout | in use, see [rollout-network.md](rollout-network.md) |
| playout value net | `solver/rl/playout_value.json` | scores the rest of a playout that is cut short | in use, same document |
| party value head | `solver/search/party_policy.json` | optional leaf for the party search | in the tree, opt-in, not used by the panel |
| plan-ranking head | removed | ranked plans for the party search's shortlist | history, see [below](#earlier-supervised-attempts) |

A rule of the repository: nothing under `solver/` imports PyTorch. Training
is in `tools/` and exports plain floats as JSON. Inference is numpy, and
every caller falls back when numpy or the weights are missing.

## Why learn a policy

The project started with search. For one toon, expectimax can solve a small
battle exactly. For a party it cannot: a party round's outcomes are the
accuracy rolls, times each cog's choice of attack and target, times the
other toons' moves, so the party search samples, and before it can evaluate
anything it has to enumerate and shortlist joint plans.

That shortlist is where the cost was. A profile of a depth-2 party search
put 65.5 of 68.6 seconds, 95%, in the function that enumerates and ranks
candidate plans, and almost none in evaluating them. The cost per ply on one
party position, at fixed width:

| depth | time | value |
|---|---|---|
| 1 | 0.38 s | +91.32 |
| 2 | 17.91 s | +92.04 |
| 3 | 198.97 s | +91.96 |

Depth 3 cost eleven times depth 2 and scored no better. The shortlist was
also where correct answers kept being lost: several separate bugs each
dropped a known-good plan during a reduction step.

A policy avoids both problems. It scores every action in one forward pass
instead of enumerating plans, and it learns from outcomes, so it is not
capped by a teacher that is itself approximate.

Three supervised components were built before the policy. None earned a
place in play; they are summarised under
[earlier supervised attempts](#earlier-supervised-attempts).

## Observation

The observation is a fixed-width vector from the point of view of the toon
deciding. Cogs and toons are padded to four slots each and kept in order.
They are not pooled, because neither is interchangeable: a target is a slot
index, and each toon has its own gags.

The layout has a version number, because a change of scale in one slot
would otherwise let an old policy load and misread its input. The policy in
use is version 1. The encoder reproduces each older version exactly, so an
old policy keeps working.

| block | contents | width at version 1 | width at version 4 |
|---|---|---|---|
| cogs, 4 slots | present; level / 20; health fraction; max health / 476; is a Version 2.0 cog; work left on it, counting the second layer; lured; trapped; lure rounds left / 8; dead flag; armed trap's damage as a fraction of remaining health | 4 × 11 | 4 × 11 |
| toons, 4 slots | present; laff fraction; max laff / 137; pink slips; from version 3, laff / 137; then the count of each of 49 gags (7 tracks × 7 levels), capped at 8 and divided by 8 | 4 × 53 | 4 × 54 |
| fight | round / 12; cogs on the field / 4; toons standing / 4; cogs in later floors or waves / 30; whether this is a multi-floor facility; cogs waiting to walk in / 4 | 6 | 6 |
| kind of fight | one-hot over 12 kinds: street, building, a generic facility, the four headquarters facilities, the field office and the four bosses. The simulator produces four of them today; the rest are reserved. | none | 12 |
| who is deciding | one-hot over the 4 toon slots | 4 | 4 |
| plan so far | for each toon, what it has already chosen this round: track one-hot, a group-target flag, and a not-yet-chosen flag | 4 × 9 | 4 × 9 |
| total | | 302 | 318 |

Several features are products handed over directly because a linear layer
cannot multiply: the work left on a two-layer cog, a trap's damage relative
to its target's health, and absolute laff.

The last two blocks are what make one shared policy able to plan for a
team. Without the plan so far, four toons sharing a policy would see the
same observation and choose the same move.

The observation does not contain a toon's training level in each track or
which track is organic, although both affect accuracy and damage in the
simulator. A wider observation that added them, along with each cog's
expected damage, was tried and reverted (see the table of experiments
below).

Version history:

| version | change | width |
|---|---|---|
| 1 | pink slips as min(slips, 10) / 10 | 302 |
| 2 | pink slips as a fraction of the toon's slip capacity | 302 |
| 3 | absolute laff added to each toon | 306 |
| 4 | kind-of-fight one-hot appended | 318 |

Versions 3 and 4 were each measured against a matched control and neither
showed a gain. Version 3 over nine paired runs of 250 games: +94 / −105,
p = 0.48. Version 4 over 150 paired sides a cell: street 52.0% against
52.7%, buildings 45.3% against 44.0% (p = 0.83). Both are kept as the
trainer's default on the argument that they add information at no cost, and
neither is in the policy that ships.

## Actions

The output is a fixed table of 250 actions: the pass, every (track, level,
target) for 7 tracks, 7 levels and 5 targets (the group, or one of four cog
slots), and a pink slip on each of four cog slots.

Illegal entries are masked, not removed, so indices stay stable. The mask is
derived from the simulator's own move generator. An earlier mask was written
separately and drifted from it: compared over 1,178 positions, it allowed
204 Toon-Up moves the simulator did not and disallowed 147 it did.

Two kinds of move are outside the table because adding them would change
its size and invalidate every trained policy. SOS cards (a one-use call for
help that takes the turn) are offered to the climb as extra candidates.
Unites (consumables that restore laff or gags and take no turn) are handled
as a transformation of the state around the climb. Both are described in
[ppo-math.md](ppo-math.md#6-the-climb).

## The training environment

`solver/rl/env.py` wraps the same simulator the engines use. Nothing is
re-implemented for training, so the policy and the search are scored by the
same rules and the same reward.

**Modes.** In pickup mode the agent controls one toon and the others are
sampled from a hand-written model of what a stranger tends to throw. That
model is a guess about people and is labelled as one. In coordinated mode
one shared policy chooses for every toon in turn, one decision per step, and
the round resolves when the last toon has chosen. The policy in use is
coordinated. A coordinated policy can learn plans that need two toons, such
as one laying a trap for another's lure, which a pickup policy cannot,
because there the other toon's move is noise.

**Episodes.** A street battle is one episode. A building, a VP or a CEO
fight is one episode across all its floors or waves, with laff and gags
carried through and nothing restocked. This matters: when an episode ended
with the battle, the policy ignored the count of cogs still to come, because
a gag saved was never spent. See
[reward-experiments.md](reward-experiments.md#scaling-and-the-horizon).

**Reward.** The search's own round reward: laff lost, a price for each gag
spent, a charge per round, and ±100 for winning or losing. The policy in
use was also charged for overkill. Formulas are in
[ppo-math.md](ppo-math.md#2-reward).

### How positions are sampled

The distribution of starting positions is the curriculum, and most of the
gains in this project came from changing it. Each sampler exists because
its absence showed up as a specific failure.

| sampler | what it draws | why it exists |
|---|---|---|
| default | 1 to 4 toons against 1 to 4 cogs at a quarter to full health | the base case |
| hard | one toon against 3 or 4 cogs of level 10 to 12 | with several toons and mixed cogs the team can out-damage the board, so Lure is never forced and never learned |
| mid-fight | a default or hard position with cogs already lured or trapped, damaged cogs, toons near zero laff, and gags already spent | advice is asked for mid-fight, and fresh battles teach only round-one habits |
| combo | a trap already armed and a lure in hand | a reverse curriculum: only 4.6% of ordinary positions had that state, so its payoff was almost never experienced |
| building | 2 to 4 toons built to fit a street, then a multi-floor building from the same street | multi-floor play, where conserving gags pays |
| boss | one side of a VP or a CEO fight | the only positions with two-layer cogs, cogs above level 12, and pink slips as standard |

Toons are deliberately uneven: random tracks beyond the two every toon has,
random training per track, a pouch capacity drawn from the game's table, and
laff from 15 to 137. A first version gave every toon high training in every
track, and every position had the same late-game texture.

For buildings the street is drawn first and the toons are built to match
it: laff and pouch size at or above what a toon would have on reaching that
street, tracks limited to those earned by then, and a pouch filled from the
top level down as a player stocks one. Before this order was fixed, half of
the building episodes put starting toons into late-game buildings and no
agent could clear a floor.

Only cogs and gags whose data tables are complete are sampled, so a missing
value cannot raise mid-episode and bias the sample. One exception is opted
into explicitly when boss positions are trained: one CEO cog has an attack
with no published accuracy, and the trainer accepts a borrowed value for it
(the mean of that cog's other attacks) and says so on start-up. That value
is `[ASSUMED]`.

Position samplers must not emit states the game cannot reach. One early
version set a cog as trapped without a trap level, a state the simulator
never produces, and training on it means training on a game that does not
exist.

The trainer's defaults put a quarter of episodes on boss sides (half VP,
half CEO), cut a quarter of boss and building episodes down to one toon, and
make a quarter of the remaining street positions mid-fight ones. The shares
of hard, combo and building episodes are set by flags and default to zero.

### Where training data comes from

All of it is generated by this simulator, whose rules are sourced from the
Toontown Rewritten wiki. A hard rule of the project applies to every model
here: data from Toontown Realms (a different game on the same engine, whose
live battles the project can also read) never trains or scores anything used
for Toontown Rewritten. Its cog health and gag tables differ.

## Training

`tools/train_ppo.py` is a single-file PPO with a masked categorical policy.
The loss and its terms are in [ppo-math.md](ppo-math.md#4-the-ppo-objective).

| component | shape |
|---|---|
| actor trunk | observation → 256 → 256, tanh |
| actor head | 256 → 250 logits, masked |
| critic trunk | observation → 256 → 256, tanh (separate from the actor's) |
| critic head | 256 → 1 |

The actor and critic do not share a trunk. With a shared trunk the first
trainer learned backwards (evaluation return fell from +47.9 to +22.5):
returns run to about ±100, the value loss was four orders of magnitude above
the policy loss, and the shared weights followed the critic. Separate trunks
and reward normalisation fixed it.

Defaults: 32 environments, 128 steps each per update, 4 epochs, minibatches
of 1,024, Adam at $3 \times 10^{-4}$, $\gamma = 0.99$, $\lambda = 0.95$,
clip 0.2, entropy coefficient 0.01, gradient clip 0.5.

An episode cut off at the round cap is truncated, not terminated: its last
reward is topped up with the critic's value, so that surviving to the cap is
not learned as worthless.

The export is JSON: layer weights, the observation version, the action
count, and, in recent exports, the reward settings and step count of the
run. `env.check_export` refuses a file whose observation width
or action count does not match what its version implies. Before that check
existed, a policy trained on one layout was loaded against another and
returned confident nonsense.

The experiment that first put boss sides into training, from which the
shipped lineage descends, used the flags below for 6 million steps. With
today's trainer they produce a version 4 policy:

```
python tools/train_ppo.py --steps 6000000 --coordinated --facility-fraction 0.5 --fire-fraction 0.25 --boss-fraction 0.25 --export candidate.json
python tools/ship_gate.py solver/rl/ppo_facility.json candidate.json
```

`ship_gate.py` measures a candidate against the incumbent on buildings, the
VP and the CEO. It exists because a policy was once shipped on a
buildings-only comparison and cost 16.5 points on the CEO. The trainer's
default `--export` path is `solver/rl/ppo_policy.json`, which is not the
file the engine loads.

### The policy that ships

`solver/rl/ppo_facility.json` was committed on 2026-08-28. From the file:
observation 302 wide (version 1), 250 actions, hidden width 256,
coordinated. It was trained with boss sides in the mix and with the overkill
charge; the commit records the held-out results (in
[reward-experiments.md](reward-experiments.md#overkill)) but not the exact
command, and the file predates the reward and step-count fields. Policies
earlier in the same lineage were trained for 6 million steps.

What is known about how it was selected matters as much as how it was
trained. It was chosen for shipping because it scored well on the solo VP,
so on that measurement it is the best of several runs. Ten other training
runs scored between 21.0% and 38.0% on the same measurement (mean 30.2%,
standard deviation 5.0) where the shipped policy scores 49.5%, and two
replications of the shipped policy's own flags on fresh seeds scored 33.0%
and 31.5%. Any single new run compared against it will look like a
regression.

`solver/rl/` used to hold seven weight files from earlier experiments that
no code loaded. They were removed on 2026-10-12 to keep the repository
small, and remain in the git history (last present at commit `432c4dd`):

| file | what it was |
|---|---|
| `ppo_policy.json` | the first pickup policy and its early retrains (247 inputs, 246 actions). It is still the trainer's default `--export` path, so a training run with no `--export` writes a new file there. |
| `ppo_pickup.json`, `ppo_coord.json` | a pickup and a coordinated policy from 2026-08-15, before buildings were modelled |
| `ppo_expert.json`, `ppo_expert_w.json` | behaviour clones of the party search, without and with class weights |
| `ppo_v4.json`, `ppo_v4_nokind.json` | the matched pair for the kind-of-fight feature: 2 million steps each, same seed, differing only in whether those inputs are live |

All but the last pair used a 246-action table and would have been refused
by the loader.

## At play time: the climb

The policy alone is not what the PPO row shows. `hybrid.climb` treats the
policy as a source of proposals and a separate one-round scorer,
`_quick_score`, as the judge.

1. Each toon in turn takes the policy's top move, with the earlier toons'
   picks visible. This is the starting plan.
2. For each toon, a menu is built: the policy's top 16 moves, plus a few
   targeted probes (the smallest gag that kills each cog, the cheapest lure,
   and, in a party or when the menu is all one kind of move, the policy's
   best move of every kind and the pass).
3. Each menu entry is tried in place of the toon's current move. Any plan
   the scorer strictly prefers is kept.
4. This repeats until a sweep changes nothing or 24 scorer calls are spent.
   Then pairs of toons are tried jointly, since some improvements need two
   toons to change at once.
5. Unites are tried around the whole procedure, and SOS cards inside it.

The scorer takes the expectation over the round's accuracy rolls of a
hand-weighted score: cogs killed, damage prevented, laff healed, less the
price of what was spent. It is described in [scoring.md](scoring.md). The
procedure is deterministic and takes a few milliseconds to a few hundred.

Findings from building it that generalise:

**The judge must be independent of the proposer.** Ranking the policy's
samples with the policy's own critic achieved nothing (57.8 to 58.3% of
buildings against 58.9% for the policy's top move). Playing each candidate
forward with the policy for two or four rounds was worse than the one-round
scorer (61.1% and 60.6% against 64.4%). The one-round scorer shares none of
the policy's blind spots, and it took the same policy from 58.9% to 64.4%.

**More reach is not always better.** A wider menu gives the search more
good options and also more chances to act on the scorer's own errors. On a
solo VP, widening the menu from 3 to 16 moves took held-out wins from 48% to
75% (+15 / −4, p = 0.019), because below 16 the right move was often never
shown to the scorer. But offering every toon its best move of every kind
cost 9.2 points on the solo VP while gaining 17.6 on a two-toon CEO side.
That probe is therefore on in a party and off for a lone toon, unless the
policy's menu is all one kind of move.

**Tuned seeds flatter.** The climb first appeared to beat the full search
(69.4% against 65.0%) on the seeds it had been tuned on. On buildings it had
never seen it was behind (66.1% against 67.8%). Every result reported below
is on seeds not used for tuning.

## Measured standing

### Against the party search

The first policy, pickup mode, on 200 held-out single battles drawn from
its own training sampler:

| agent | mean return | wins | time for the set |
|---|---|---|---|
| PPO policy | +60.31 | 93.0% | 0.41 s |
| search, 8 samples, 12 plans | +57.98 | 92.0% | 24.09 s |
| search, 32 samples, 30 plans | +61.87 | 94.0% | 101.51 s |
| uniform random | +23.10 | 80.0% | |

On harder positions (one toon against a wall of cogs, and mid-fight boards)
the cheaper search was ahead by four points of return, with the policy 71
times faster.

On multi-floor buildings, three sets of 180, with the coordinated policy:

| agent | buildings cleared | time per decision |
|---|---|---|
| PPO with the climb | 65.9% (69.4 / 63.3 / 65.0) | 0.6 ms |
| party search | 65.0% (65.6 / 65.0 / 64.4) | 124 ms |
| PPO alone | 57.6% (57.2 / 53.9 / 61.7) | 0.28 ms |

The top two are tied; the order between them is noise. The gap between the
climb and the policy alone is not. A harder building regime, with
under-levelled parties, lowered both agents by ten points and left them
level (50.0% each over 120 buildings).

### Against the Playout engine

The Playout engine takes the climb's move as one candidate among about ten
and plays each to the end of the fight. Paired, same seeds:

| fight | PPO with the climb | Playout engine | paired |
|---|---|---|---|
| solo VP, 500 sides | 36 (7.2%) | 106 (21.2%), an early version: three candidates, 8 playouts each | +90 / −20, p < 0.0001 |
| solo VP, 200 fresh sides | 10 | 54, same early version | +50 / −6, p < 0.0001 |
| one toon on a two-player VP side, 60 | 6 | 33 | |
| party buildings, 600, you choosing and teammates modelled | 268 | 288 | +34 / −14, p = 0.006 |
| two-toon CEO side, 200 | 43 | 48 | +16 / −11, p = 0.44 |

The Playout engine improved a good deal after the first two rows were
measured; its own figures are in [playout.md](playout.md). The policy alone,
with no climb, won 0 of 400 solo VPs.

The reason for the gap is the horizon. The climb's scorer sees one round. A
VP is forty cogs arriving in waves, and only an engine that plays the fight
forward sees the waves after the one on the field. The same blindness
applies to the Search row, which won 6 of 60 on the two-player VP side.

### Standing today

- The Playout row leads in every fight unless the player picks an engine.
  The PPO row's answer is shown at once and stays until the playouts post
  their first.
- The policy is still load-bearing. The climb's move, with and without its
  unite, and the policy's top two moves are entries on the Playout engine's
  menu, and in a group the climb plays out the rest of each playout.
- The PPO row ignores the panel's playstyle preset. The policy was trained
  under one set of reward weights and its scorer takes none.

## What was tried on the policy

Each row was measured on held-out simulated fights. "Plain" is the policy's
own top move; "climb" is the policy with the climb. Differences are in
percentage points.

| change | result | kept |
|---|---|---|
| more training steps | 800 thousand → 6 million: +8.3 on buildings (48.9% → 57.2%, plain). 6 million → 16 million: +1.1, inside noise. | later runs use 6 million |
| entropy coefficient 0.01 / 0.04 / 0.10 | entropy of gags thrown 3.79 at every setting; the bonus is satisfied by spreading over targets | 0.01 |
| entropy on the track marginal, 0.05 | holds 2.0% → 11.9%, Throw 44.4% → 33.8%, matching the search's profile. Climb +1.1 (positive on three sets), plain −4.5. At 0.15 the policy passes 39% of the time. | shipped at the time; whether the current policy's run used it is not recorded |
| hidden width 512 | climb −0.2, mixed signs | no |
| wider observation: per-cog threat, training levels, organic flags | behaviour moved as predicted; climb 64.4 / 66.1 / 63.3% over three seeds against 66.7% | reverted |
| observation versions 3 and 4 | no measurable difference against matched controls | as trainer default only |
| hiding level 7 counts when level 7 gags are disallowed | 35 up, 42 down over 800 sides, p = 0.49 | off |
| hard and mid-fight positions in the mix | Lure use more than doubled, to 19.5% of moves (the search: 9.4%) | yes |
| building positions built street-first | made building play learnable at all | yes |
| boss sides in the mix, 25% | CEO side with the climb +8.9 and +11.4 (p < 0.001), replicated on held-out seeds; buildings unchanged | yes |
| reward changes | see [reward-experiments.md](reward-experiments.md) | overkill charge |
| behaviour cloning of the party search | 12,445 decisions; the clone cleared 7.5% of buildings against the search's 51.2% and PPO's 35.0% | no |
| DAgger with the climb as teacher | 6 iterations, 15,393 states: plain −2.0, climb −0.9. Agreement with the teacher never rose (44.3% to 45.8%) while the loss fell. | no |

Two of these deserve a sentence more.

*Why DAgger onto the climb has no fixed point.* The climb is defined as a
perturbation of the student's own proposal. As the student changes, the
teacher changes with it, so there is nothing to converge onto. A search
whose behaviour does not depend on the student, like the Playout engine, is
a different case, and expert iteration with that teacher worked for the
rollout network ([rollout-network.md](rollout-network.md)).

*Seed variance decides more than most changes.* Eight policies differing
only in training seed spanned 23.3% to 62.5% on one CEO measurement while
their building results sat inside a two-point band. Picking the
best seed on the measurement being reported has been tried and failed: the
winner lost on fresh seeds. A change to training has to be judged across
several seeds per arm against a matched control.

## Earlier supervised attempts

Three learned components were built before PPO. They are recorded because
the reasons they failed shaped what came after.

**A small network as the solo evaluator.** Solo positions that are small
enough can be solved exactly, so labels exist. A network of one hidden layer
of 16 units, heavily regularised, cut held-out error against the fitted
linear evaluator from 27.1 to 19.0 and left move ordering unchanged at 91%.
A larger network overfitted (4.4 on training data, 32.0 held out). Since a
search needs ordering, not calibration, it was not adopted, and its script
is no longer in the tree.

**A plan-ranking head for the party search** (referred to in code comments
as P0 and as section 2b of this document). The idea was to learn which joint
plans deserve to be on the shortlist, from a search run deliberately wider
than the shipped one. The teacher has to be wider than the student:
labels come from search, a search ranks only what its shortlist admitted,
and training on the shipped shortlist would teach the student its blind
spots. `tools/gen_party_data.py` still generates data this way.

Offline the head looked strong: the value lost by keeping only its top six
plans was 3.22, against 9.93 for the hand-written ranking and 12.09 for
random choice. In play, over four seeds on one party position, it lost at
every shortlist width, in both value and time:

| shortlist width | hand-written ranking | learned ranking |
|---|---|---|
| 8 | +88.06 in 0.9 s | +86.79 in 1.2 s |
| 16 | +89.34 in 1.3 s | +86.79 in 1.6 s |
| 30 | +89.34 in 2.2 s | +87.79 in 2.6 s |
| 60 | +89.72 in 3.9 s | +89.23 in 4.3 s |

The cause was the labels. The teacher estimated each plan from 16 samples,
for a standard error of about 7.8, while the median gap between the best
plan and the sixth was 3.54. The labels were noisier than the distinctions
they were meant to teach, and the offline metric was scored against the same
noisy values, so it rewarded avoiding bad plans and could not see failure to
pick the best one. The table shows the better of two label sets, relabelled
at 128 samples per plan; that narrowed the deficit at width 60 from 1.43 to
0.49 and did not close it. The head was removed.

The lesson carried forward: an offline metric computed against noisy labels
cannot validate a component whose job is to discriminate within that noise.
Only the end-to-end comparison counts.

**A value head for the party search's leaf** (P1). It replaces a sampled
playout at the leaf with one forward pass. The leaf became 65 times faster
(66,474 evaluations a second against 1,030) and the search 1% faster, at the
same quality, because the leaf was never where the time went. It remains in
the tree, loaded from `solver/search/party_policy.json` and used only when a
caller asks for `leaf="learned"`.

## Limits

- **The policy has learned the simulator, errors included.** A search
  exposes a wrong rule because a person reads its output and sees a move
  nobody would play. A policy hides one. Several rule errors were found and
  fixed during this work, and shipped policies were retrained after each.
  The other engines stay in the panel partly as a cross-check.
- **One rule value is an assumption.** The accuracy bonus for several toons
  luring at once is tagged `[ASSUMED]` in the simulator, and Lure play
  depends on it.
- **Party results rest on a model of teammates.** In pickup-mode
  measurements the other toons play from a hand-written prior. That is a
  guess about people that nothing in the game's rules can confirm.
- **Boss measurements from August used earlier models of those fights.**
  The VP in particular was smaller than the 20 + 20 cogs used now and was
  often fought by two toons, which is why win rates near 99% appear in the
  older records and 7% in the newer.
- **The in-training evaluation is not a selection criterion.** It plays
  street battles with the policy's top move, and it did not predict results
  with the climb or on bosses.
