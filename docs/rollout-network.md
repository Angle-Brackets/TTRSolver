# The rollout network and the playout value net

This document covers the two small networks behind the Playout engine: the
rollout network (`solver/search/fastplayer.py`), which plays out the rest of
a fight inside each playout, and the playout value net
(`solver/search/valuenet.py`), which scores the remainder of a playout that
is cut short. Both are in use today, loaded from `solver/rl/fast_player.json`
and `solver/rl/playout_value.json`. How the engine uses them (the candidate
menu, successive halving, scoring) is in [playout.md](playout.md); the policy
network behind the PPO row is in [ml-design.md](ml-design.md).

Every result below comes from simulated fights. No number here was measured
in the live game.

## Where the two networks sit

The Playout engine judges a candidate move by playing the fight on from it
many times and averaging the outcomes. A playout is a sequence of rounds, so
something has to choose the toon's move in every later round. Originally that
was `hybrid.climb` (the PPO policy plus a one-round scorer, described in
[ml-design.md](ml-design.md)). Profiling put 91% of a playout's time in
`climb` choosing those later rounds, at about 2.3 ms a decision.

The rollout network replaces `climb` for that job. It is a fast imitation of
a slower and stronger player, used where the number of playouts matters more
than the quality of any single one. This is the role the rollout policy has
in AlphaGo.

The value net shortens each playout further. After the candidate move and
eight more rounds played by the rollout network, the playout stops and the
value net estimates what the rest would have scored.

| model | file | used by | status |
|---|---|---|---|
| rollout network | `solver/rl/fast_player.json` | solo playouts (every round after the first); its unite head also chooses unites for teammates and for group playouts | in use |
| playout value net | `solver/rl/playout_value.json` | solo playouts, to score the rest after the cut | in use |
| search-leaf value net | no weights in the repository | the Search row's leaf, behind `valuenet.USE` | off; three attempts lost in play |

Both shipped networks need numpy at play time and nothing else. Training
uses PyTorch and lives in `tools/`; what is exported is plain floats in JSON.
If numpy or a weight file is missing, the engine falls back: `climb` plays
the playouts, and playouts run to the end of the fight.

The rollout network knows one seat. In a group, the rest of a playout is
played by `climb`, which plans every seat jointly.

## The rollout network

### Inputs

The input is a vector of 352 floats for the toon being advised.

| block | width | contents |
|---|---|---|
| board | 318 | `env.encode` at its current layout: four cog slots, four toon slots (laff, pink slips, the count of every gag), round and fight context. See [ml-design.md](ml-design.md#observation). |
| SOS cards | 29 | one input per card in `sos.BY_NAME`, in alphabetical order: copies held, capped at 3 and divided by 3 |
| unites | 2 | unites held (capped at 5, divided by 5) and the unite cooldown (divided by 3) |
| horizon | 3 | what is still to come, described below |

An SOS card is a one-use call for help that takes the toon's turn. A unite
is a consumable that restores laff or gags and does not take a turn.

The three horizon inputs are the ones the board does not show:

| input | meaning | scaling |
|---|---|---|
| cogs waiting | cogs still to walk into the current wave or floor as slots free up | capped at 40, divided by 20 |
| cogs after | cogs in the later waves or floors of the fight | capped at 80, divided by 40 |
| SOS calls left | calls the toon may still make this fight | capped at 10, divided by 5 |

A playout plays on a view of the board with the waiting cogs stripped, which
is what a player sees. The count of waiting cogs is passed in separately, so
the network knows how many are coming without seeing which.

The loader accepts older weights. A first layer three inputs narrower is
treated as a network without horizon inputs, and one two narrower again is
padded with zero rows for the unite inputs.

### Outputs

There are two heads on one trunk.

| head | width | contents |
|---|---|---|
| move | 279 | the 250 entries of the environment's action table (pass, every gag at every target, four pink-slip targets) plus one per SOS card |
| unite | 14 | none; five Toon-Up unites by ordinal; Gag-Up for all tracks; Gag-Up for each of the seven tracks |

Both heads are masked. The move head is restricted to legal moves and to SOS
cards the toon holds. The unite head is restricted to what
`unites.candidates` offers: held, off cooldown, and not obviously wasted.

The unite is chosen first, as in the game. The unite head reads the board as
it is; if it picks a unite, the unite is applied to a copy of the board and
the move head reads that copy.

### Architecture

Taken from `fastplayer.py` and the shapes in `fast_player.json`:

| layer | shape | activation |
|---|---|---|
| trunk 1 | 352 → 512 | tanh |
| trunk 2 | 512 → 512 | tanh |
| move head | 512 → 279 | masked argmax at play time |
| unite head | 512 → 14 | masked argmax at play time |

That is about 0.59 million parameters. Play is greedy: the network takes the
highest-scoring legal output and does not sample.

### Training

`tools/train_fast_player.py` minimises cross-entropy between the masked
move-head output and a target distribution, over the legal moves only.

For a row labelled with a single move the target is one-hot. For a row that
carries the Playout engine's mean score $m_i$ for every move $i$ it tried,
the target is a softmax over those moves:

$$
p_i = \frac{\exp(m_i / T)}{\sum_j \exp(m_j / T)}
$$

with temperature $T$ (`--temp`, default 0.02, in units of cogs defeated).
This is the same idea as AlphaZero training on its search's visit counts
instead of only its chosen move.

The unite head is trained with ordinary cross-entropy on its own rows, added
to the same loss. The optimiser is Adam with learning rate $10^{-3}$, cosine
annealing over the epochs, and batches of 1,024. Five per cent of each data
file is held out before any reweighting, so copies of one decision cannot
sit on both sides of the split.

### Training data

All training data is generated by the simulator. `tools/gen_fast_player_data.py`
plays solo fights and records one row per decision: the input vector, the
legal mask, and the teacher's move. A hard rule of the project applies here:
data from Toontown Realms (a different game on the same engine, whose live
battles the project can also read) never trains anything used for Toontown
Rewritten. The six data sets recorded in the shipped weight file are all
simulator output.

The fights are drawn from a mix set by `--kinds`. The default is 60% solo
VP (the Sellbot boss fight, 20 cogs then 20 more), 20% buildings and 20%
street battles, each cut to one toon. Solo CEO fights can be added with
`ceo:1`. Toons hold between one and five unites in 70% of fights. In
building and street fights the toon is given a random set of SOS cards with
probability one half and, independently, up to three pink slips with
probability one half.

Two choices decide what the data teaches:

| option | values | effect |
|---|---|---|
| `--teacher` | `climb` (default) or `playout` | who labels each decision |
| `--player` | none (default) or a weight file | who plays the fight forward. With a weight file the network plays and the teacher only labels, so the data covers the positions the network itself reaches. This is DAgger. |

### History

The network has had four versions. The comparisons below are paired: both
arms play the same seeds, so the fights and dice match, and the p-values are
sign tests on the seeds where the arms disagree.

**1. Imitating climb, with DAgger (2026-10-01).** The first network was
trained on `climb`'s decisions over solo VPs, buildings and street fights,
then on two DAgger rounds. The DAgger rounds took held-out agreement with
`climb` from 68% to 79%, and its wins playing solo VPs entirely on its own
from 7 of 300 to 16 of 300. Used inside playouts, on 200 paired solo VPs:

| rollout player | rollouts per stage | wins of 200 | time per move |
|---|---|---|---|
| climb | 2 / 4 / 8 | 71 | 3.37 s |
| network | 2 / 4 / 8 | 63 (p = 0.42) | 0.78 s |
| network | 8 / 16 / 32 | 111 (+60 / −20, p < 0.001) | 3.06 s |

Per rollout the network is slightly worse than `climb`. At equal time it
gets four times as many rollouts, and that wins.

These fights, and every VP figure dated before 2026-10-06, were played with
unites unusable because of a bug in how simulated fights applied them. The
absolute win rates are therefore low; the comparison between arms stands.

**2. A first attempt at expert iteration (not shipped).** Expert iteration
means using a stronger player built on the network (here the Playout engine)
as the teacher, so that the network learns the search's moves and the search
then plays on with a better network. 1,000 solo fights labelled by the
Playout engine gave 27,449 decisions, mixed at three times weight into the
345,693 existing `climb` rows, with 384 hidden units. On 300 paired solo VPs
the candidate won 190 and the shipped network 175 (+74 / −59, p = 0.22). A
five-point lead that 300 paired fights cannot separate from chance was not
shipped.

**3. Unite inputs and a unite head (shipped 2026-10-07).** Until then no
playout ever spent a unite, so the playouts valued any unite held past the
current round at nothing. The new network agreed with `climb` on 82.8% of
held-out moves and on 96% of unite decisions (about 80% of which are "none").

| setting | old network | unite-aware network |
|---|---|---|
| solo VP, in playouts, 100 fights | 94 | 93 (+6 / −7, p = 1.00) |
| two-player VP side, in playouts, 60 fights | 55 | 49 (+2 / −8, p = 0.11) |
| two-player VP side, in playouts, 200 fresh fights | 167 | 163 (+18 / −22, p = 0.64) |
| solo VP, network alone, 100 fights | 6 | 22 |
| two-player VP side, network alone, 60 fights | 9 | 24 |

Alone it was much stronger, because it heals itself. As a rollout player it
was no better and about 55% slower per decision (1.88 s against 1.21 s). It
was shipped anyway on the maintainer's judgement that a playout which can
never spend a unite misprices them `[OWNER]`.

**4. Expert iteration with horizon inputs and soft targets (shipped
2026-10-11).** This is the network in the repository. Three things changed
from the first attempt.

- The student can see what the teacher sees. The Playout engine knows how
  many cogs are still to come; a student blind to that cannot copy it. The
  three horizon inputs were added for this reason.
- Soft targets. In a dry run the student matched `climb`'s held-out moves
  56% of the time and the Playout engine's only 31% (25% when trained on
  them alone). The engine's picks are full of near-ties, such as one gag
  over another by 0.0004 cogs, so the winning move alone is close to a coin
  flip to copy. Training toward the scores of every move tried uses the
  information the engine actually has.
- More playout labels, and a wider network: 1,350 simulated fights (VP,
  building, street and solo CEO) gave about 47,000 decisions labelled by the
  Playout engine, half of them with soft targets. About 77,000 `climb`
  labels were kept for the basics. The hidden width went to 512.

The weight file records 193,834 training rows after per-file repeats and
57,121 unite rows, and these held-out agreement rates:

| held-out data | agreement with the label |
|---|---|
| climb labels, VP / building / street | 63.4% |
| climb labels, solo CEO | 61.3% |
| playout labels, first set | 37.0% |
| playout labels, soft-target set | 36.2% |
| playout labels, solo CEO (two sets) | 48.8%, 50.0% |
| all held-out move rows | 53.4% |
| unite head | 89.1% |

### Results for the shipped network

Each row compares playouts using the new network against playouts using the
network it replaced, on seeds never used in training.

| regime | new | old | paired |
|---|---|---|---|
| solo VP, 100 fights | 65 wins | 44 wins | +31 / −10, p = 0.001 |
| solo VP, 100 fresh seeds | 68 wins | 37 wins | +35 / −4, p < 0.001 |
| solo CEO | 9.8 cogs defeated | 8.9 cogs defeated | a lone toon never wins this fight in the model |
| solo building, 1,000 fights | 121 wins | 128 wins | +15 / −22, p = 0.32 |

Decisions take about 15% longer. The network is better in the long
multi-wave fights it was aimed at and level in buildings.

### Later rounds that did not replace it

Three further networks were trained on 2026-10-11 and none beat the
shipped one clearly, so it stayed. Each row is a paired sweep of the
Playout engine using the shipped network against the same engine using
the candidate, on simulated fights; "+a / −b" counts fights won only by
the candidate and only by the shipped network.

| candidate | solo building, 1,000 | solo VP, 100 | solo CEO, cogs defeated |
|---|---|---|---|
| A second round of playout labels, soft targets | 106 against 104 (+8 / −6, p = 0.79) | 58 against 67 (+10 / −19, p = 0.14) | 9.6 against 9.4 |
| The same, fine-tuned from the shipped weights (`--init`) | 106 against 103 (+11 / −8, p = 0.65) | 71 against 70 (+26 / −25, p = 1.0) | 9.2 against 8.7 |
| Playout labels only, without the `climb` labels | 113 against 103 (+17 / −7, p = 0.064) | 66 against 70 (+20 / −24, p = 0.65) | 8.9 against 8.7 |

The first row and the other two used different seeds, which is why the
shipped network's own figures differ between them. The playout-labels-only
network also took 3.00 s a decision on the VP against 2.36 s. Its building
result is the one lead here that a larger sample might confirm; it was not
followed up. These candidate weights were not kept in the repository.

### Why agreement with climb fell on purpose

The shipped network agrees with `climb` on 63% of held-out moves. Its
predecessor agreed on 83%. That drop is the intended result, not a
regression.

`climb` judges one round at a time. A network that copies it faithfully
plays the rest of every playout with one-round judgement, which is the
weakness the Playout engine exists to get past. The playout labels pull the
network toward moves chosen with the whole fight in view, and those moves
differ from `climb`'s.

The low agreement on playout labels (36% to 50%) has a different cause. The
teacher's first choice is often separated from its second by less than the
noise in its own estimate, so exact agreement is a poor measure of how well
the student has learned. Whether the student is good enough is decided by
paired sweeps of the playouts that use it, as above.

### It is a rollout player, not an engine

Played alone, one forward pass per decision with no playouts, the shipped
network won 108 of 2,000 solo buildings. The comparison arm in the same
record won 155; the record does not name that arm, and the other figures
beside it compare against the previous network. The cause is known: the
teacher charges for the gags it spends, and a student that has absorbed
those prices without the playouts' look-ahead hoards.

Earlier versions were no more usable alone: 6 and 5 wins of 100 solo VPs for
the first two, and 22 of 100 for the unite-aware one.

Two other uses of the network were tried and are not in the panel:

- An open-loop Monte Carlo tree search (`solver/search/mcts.py`) that uses
  the network's top four moves as priors below the root. It did not beat the
  flat playouts at any exploration constant, and unlike the flat playouts it
  did not improve with two or four times the budget (49, 51 and 49 wins of
  100 two-player VP sides, against 52, 63 and 60).
- A teammate model that plays other toons from the network at their seat
  (`party.NetTeammate`). Over 200 party buildings, what the engine assumed
  about teammates made no measurable difference (93 to 101 wins across the
  four combinations), so the simpler hand-written prior stays the default.

### What is not recorded

- The exact commands for the shipped run: the episode count per data file
  and the repeat weight given to each. The weight file records the file
  names, the row totals and the settings (512 hidden units, 15 epochs).
- The data and weights of the later rounds above. Their sweep results are
  in the table; the networks themselves and the commands that produced
  them were not kept.

## The playout value net

### What it scores

A playout's score is cogs defeated plus a small term for laff left. The
value net predicts, for a board partway through a fight, the part of that
score still to come:

$$
y = (\text{cogs defeated from this board to the end of the fight}) + 0.5 \cdot \frac{\text{laff left}}{\text{max laff}}
$$

under the rollout network's play. The 0.5 is `playout.LAFF_WEIGHT`. A
shortened playout returns the cogs it has already defeated plus this
prediction.

The match between label and use is the point. The playouts already finish
every fight with the rollout network, so a net trained on how fights end
under that network, in the playouts' own units, predicts what the rest of
that same playout would have scored.

### What it sees

The input is 351 floats: the rollout network's board, SOS and unite inputs
(349, without the three horizon inputs) plus two counts of its own.

| input | scaling |
|---|---|
| cogs waiting to walk into this wave | divided by 20 |
| cogs in the waves or floors after it | divided by 40 |

### Architecture and training

| layer | shape | activation |
|---|---|---|
| 1 | 351 → 256 | tanh |
| 2 | 256 → 256 | tanh |
| 3 | 256 → 1 | none |

That is about 0.16 million parameters. `tools/train_value_net.py` regresses
on the label divided by 100, with a smooth L1 loss, AdamW (learning rate
$10^{-3}$, weight decay $10^{-4}$), cosine annealing, 60 epochs and batches
of 256. Ten per cent of the boards are held out, and the epoch with the
lowest held-out error is the one exported.

Labels come from `tools/gen_value_outcomes.py --units playout --extras`. It
plays simulated fights with the rollout network across five regimes in
rotation (two-player VP side, solo VP, the maintainer's own building toon,
generic solo buildings, street battles). Each round's board is taken with
probability 0.3, up to eight per fight, and labelled with the mean of
several independent continuations from it. The shipped file was trained on
68,030 boards with six continuations each. Its held-out error is 1.34 cogs.
As with the rollout network, all of this is simulator output, and no
Toontown Realms data is involved.

### Measurements for shortened playouts

`k` is the number of rounds the rollout network plays before the cut. Time
is per decision. All fights are simulated and paired.

**Without the two counts.** The first version read the board as the panel
shows it, with no count of cogs still to arrive. It lost, and lost more the
earlier the cut:

| regime | full playouts | k = 8 | k = 4 |
|---|---|---|---|
| two-player VP side, 60 fights | 33 | 28 | 31 |
| solo VP, 60 fights | 37 | 30 | 19 (+1 / −19) |

In a VP the number of cogs waiting swings between 16 and none, and a net
that cannot see it cannot tell those boards apart. This is a bias, and more
playouts do not average a bias away.

**With the two counts.** Held-out error barely moved (1.37 to 1.34 cogs).
Play did:

| regime | full playouts | k = 8 | k = 4 |
|---|---|---|---|
| solo VP, 60 fights | 37 (2.54 s) | 41 (1.94 s; +15 / −11, p = 0.56) | 30 (1.13 s) |
| solo VP, 200 fresh fights | 126 (2.61 s) | 134 (1.88 s; +41 / −33, p = 0.42) | |
| solo VP, all 260 | 163 | 175 (+56 / −44, p = 0.27) | |
| two-player VP side, 100 fights | 52 (1.37 s) | 57 (1.72 s) | |

The offline error could not have told the two versions apart; only play
did.

The gain in wins is not statistically established. The case for shipping
was time: the same or better advice in 28% less time per decision on a solo
VP. With playouts this cheap, the rollout schedule was doubled from 8, 16
and 32 rollouts per stage to 16, 32 and 64. With full-length playouts the
same doubling had not paid (146 against 139 wins of 200 solo VPs, p = 0.46,
at twice the time). On the two-player VP side the shortened setting is
slower, because short fights save less than the extra playouts cost.

Shortened playouts apply to solo playouts only, with `k = 8`
(`playout.ROLLOUT_DEPTH`).

### A caveat on freshness

The value net's weights were committed on 2026-10-09. The rollout network
was replaced two days later, so the value net's labels describe fights
finished by the previous rollout network. It has not been retrained under
the current one, and the effect of doing so has not been measured.

## The search-leaf value net (not in use)

`valuenet.py` can also serve as the leaf evaluator for the Search row,
replacing a fitted linear model at the depth cutoff of the expectimax
search. It is off (`valuenet.USE = False`) and no weights for it are in the
repository. Three versions were trained and judged in play at two seconds a
decision. None beat the fitted leaf.

| labels | held-out error | result in play |
|---|---|---|
| a deeper search's value (27,667 boards) | 11.5 against the fitted leaf's 36.6 | level: 145 against 146 of 200 buildings; 8 against 6 of 60 two-player VP sides |
| reward collected to the end of the fight under the rollout network (68,030 boards) | | worse: 138 against 146 of 200 buildings (p = 0.06); fights ended sooner |
| the same, with a lost fight scored at −1000 | | still worse: 3 against 8 of 60 two-player VP sides (p = 0.06) |

Two lessons carried over. Lower absolute error did not buy better choices,
because choosing a move depends on the differences between sibling boards,
which are often under a point, against a median error of 3.7. And labels
from a depth-limited search carry that search's blind spot: it sees only the
cogs on the field, and on two-player VP sides the Search row won 6 of 60
where the Playout row won 33. That gap is why the value net was pointed at
the playouts instead.

## Regenerating the networks

Generation and training are long-running. The data tools use ten worker
processes by default (`--workers`). Training needs PyTorch and uses a GPU if
one is present.

### Rollout network

Label fights with `climb`, including the horizon inputs:

```
python tools/gen_fast_player_data.py --episodes 6000 --horizon --out climb_h.pkl
python tools/gen_fast_player_data.py --episodes 1000 --kinds ceo:1 --horizon --out climb_ceo.pkl
```

Label fights with the Playout engine. Rows from this teacher carry the soft
targets automatically:

```
python tools/gen_fast_player_data.py --teacher playout --horizon --episodes 1000 --out playout_soft.pkl
python tools/gen_fast_player_data.py --teacher playout --horizon --kinds ceo:1 --episodes 200 --out playout_ceo.pkl
```

Train. A `*k` suffix repeats a file's rows `k` times, which is how scarce
playout labels are weighted against plentiful `climb` labels:

```
python tools/train_fast_player.py --data climb_h.pkl climb_ceo.pkl "playout_soft.pkl*3" "playout_ceo.pkl*3" --hidden 512 --export solver/rl/fast_player.json
```

The episode counts and the `*3` above are illustrations. The counts and
weights of the shipped run are not recorded. Every file in one training run
must have been generated with the same `--horizon` setting, because the
input width differs by three.

A DAgger round lets the current network play while the teacher labels, then
fine-tunes from the current weights:

```
python tools/gen_fast_player_data.py --player solver/rl/fast_player.json --horizon --episodes 4000 --out dagger1.pkl
python tools/train_fast_player.py --data climb_h.pkl dagger1.pkl --hidden 512 --init solver/rl/fast_player.json --export candidate.json
```

Other flags: `--kinds vp:6,building:2,street:2` sets the fight mix,
`--unites N` the most unites a toon carries (0 for none), `--base` the first
seed, and `--temp` the soft-target temperature.

### Playout value net

```
python tools/gen_value_outcomes.py --units playout --extras --rollouts 6 --episodes 20000 --out playout_value.pkl
python tools/train_value_net.py --data playout_value.pkl --export solver/rl/playout_value.json
```

`--units playout` selects the label defined above, and `--extras` adds the
two counts to the inputs. Without `--extras` the net cannot see the waiting
cogs, which is the version that lost. The experiment log records 20,000
episodes yielding 68,030 boards for this tool; `--rollouts 6` matches the
six continuations of the shipped run (the default is 3).

One thing to check before regenerating: this tool calls the rollout network
without passing it the count of waiting cogs, so the current network, which
has that input, plays these label fights seeing zero waiting. The tool
predates the horizon inputs.

### Judging a candidate

Agreement rates and held-out error do not decide anything. A candidate is
judged by a paired sweep of the playouts that use it:

```
python tools/sweep.py --regime solo-vp --n 100 --arms playout playout:net=candidate.json
python tools/sweep.py --regime solo-vp --n 100 --arms playout playout:trunc=0
python tools/sweep.py --regime solo-building --n 1000 --arms net net:net=candidate.json
```

`net=` names the rollout network's weights, `trunc=` the cut (0 plays in
full), `vnet=` the value net's weights, and the `net` arm plays the network
alone. Use seeds that no training file used. `gen_fast_player_data.py` and
`sweep.py` both default to `--base 100000`, so pass a different `--base` to
one of them; the value tool defaults to `--base 800000`.
