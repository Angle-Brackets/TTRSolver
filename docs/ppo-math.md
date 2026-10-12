# The mathematics of the PPO policy and the climb

This document states the decision process, the reward, the PPO loss and the
search that refines the policy's output at play time, each as the code
implements it. The sources are `solver/rl/env.py` (environment),
`tools/train_ppo.py` (trainer), `solver/search/party_search.py` (reward) and
`solver/search/hybrid.py` (the climb). It is current as of 2026-10-11; where
the code does something a textbook would not, that is said. The design
around these formulas is in [ml-design.md](ml-design.md).

## 1. The decision process

A battle is a Markov decision process whose state $s$ is a `BattleState`:
up to four toons (laff, gag counts, training, pink slips), up to four cogs
on the field (level, health, lure and trap status), the cogs still waiting,
and counters for the round and for the cogs in later floors or waves.

The action set is a fixed table of 250 entries (`env.ACTIONS`):

| entries | count |
|---|---|
| pass | 1 |
| (track, level, target) for 7 tracks, 7 levels, and 5 targets (the whole group, or one of four cog slots) | 245 |
| pink slip on one of four cog slots | 4 |

Most entries are illegal in any given state. Legality is a mask
$m(s) \in \{0,1\}^{250}$ derived from the simulator's own move generator,
and it is applied inside the distribution:

$$
\pi_\theta(a \mid s) = \operatorname{softmax}\big(z_\theta(s) + \log m(s)\big)_a
$$

An illegal action has logit $-\infty$ and probability zero. It is not
penalised through the reward. SOS cards and unites are not in the table;
section 6 says how they are handled.

**What a step is.** Two modes exist.

- *Pickup:* the agent chooses for one toon and the other toons' moves are
  sampled from a hand-written model. One step is one round.
- *Coordinated:* one shared policy chooses for every toon in turn. One step
  is one toon's decision. The observation tells the policy which toon is
  deciding and what the earlier toons have already chosen this round. The
  round resolves on the step of the last standing toon.

The shipped policy is coordinated. In that mode all steps but the last of a
round carry zero reward, and the discount $\gamma$ applies per step, so a
round with four toons standing is discounted by $\gamma^4$.

## 2. Reward

### 2.1 The round reward

On the step that resolves a round, the reward is
`party_search.round_reward`:

$$
r = -w_\ell\,\ell \;-\; \sum_{g \in G} \big(c(g) + \rho\,\mathbb{1}[\text{level}(g) = 7]\big) \;-\; w_k\,k \;-\; \tau \;+\; W\,\mathbb{1}[\text{won}] \;-\; L\,\mathbb{1}[\text{lost}]
$$

where $\ell$ is the laff the team lost this round, $G$ the gags spent, $k$
the number of toons whose laff reached zero, and $\tau$ a flat charge per
round. $\ell$ is the sum over toons of the net drop in laff across the
round, so a heal offsets damage to the same toon within the round, and a
toon that ends the round with more laff than it started contributes zero.

The price of a gag is

$$
c(g) = \Big(\kappa \cdot \text{level}(g) + \frac{\sigma_s}{\text{carry}(g)}\Big)\big(1 + \eta \cdot n_{\text{after}}\big)
$$

where $\text{carry}(g)$ is how many of that gag the toon who threw it can
carry at their training level, and $n_{\text{after}}$ is the number of cogs
in the floors or waves after the current one. A gag held one at a time is
therefore dearer than one held thirty at a time, and every gag is dearer
when more of the fight is still to come.

The weights are the `BALANCED` objective in `solver/search/objective.py`.
They are choices about what playing well means, not facts about the game.

| symbol | field | value |
|---|---|---|
| $w_\ell$ | `laff_weight` | 1.0 |
| $\kappa$ | `gag_cost` | 0.1 |
| $\sigma_s$ | `scarcity_cost` | 4.0 |
| $\rho$ | `rare_gag_premium` (level 7 only) | 6.0 |
| $\eta$ | `horizon_cost` | 0.15 |
| $w_k$ | `toon_lost_penalty` | 0.0 |
| $\tau$ | `turn_cost` | 1.0 |
| $W$, $L$ | `win_bonus`, `loss_penalty` | 100, 100 |

With these values and $n_{\text{after}} = 0$, $c(g)$ runs from about 0.23
for a level 1 gag carried thirty at a time to 4.70 for a level 7 gag.

### 2.2 Optional terms

The environment has four further terms. Each has weight zero by default.

**Precision** (`--precision`, weight $w_p$). A charge for damage thrown past
what the cogs had left:

$$
r \mathrel{-}= w_p \cdot \frac{D_{\text{waste}}}{D_{\text{waste}} + \sum_{c} \text{hp}(c)} \cdot \sum_{g \in G} \frac{1}{\text{carry}(g)}
$$

$D_{\text{waste}}$ is the plan's damage beyond its targets' remaining
health. A gag that hits every cog is charged once, against the toughest cog,
because its overkill on the weaker ones is not a choice. The last factor
makes waste of a scarce gag cost more. The policy in use was trained with
this term on; see [reward-experiments.md](reward-experiments.md).

**Pink-slip cost** (`--fire-cost`, weight $w_f$):
$r \mathrel{-}= w_f \cdot (\text{slips spent this round})$.

**Threat shaping** (`--shaping`, weight $w_t$). With $I(s)$ the laff the
cogs are expected to take off the team next round, and potential
$\Phi_t(s) = -w_t\,I(s)$:

$$
F_t = \gamma\,\Phi_t(s') - \Phi_t(s) = w_t\big(I(s) - \gamma\,I(s')\big), \qquad \Phi_t(s') = 0 \text{ when the episode ends}
$$

**Survival shaping** (`--survival-shaping`, weight $w_s$). With $n(s)$ the
number of toons standing and $\Phi_s(s) = w_s\,n(s)$:

$$
F_s = \gamma\,\Phi_s(s') - \Phi_s(s), \qquad \Phi_s(s') = 0 \text{ when the episode ends}
$$

Both shaping terms have the potential-based form of Ng, Harada and Russell
(1999), which leaves the optimal policy unchanged. Two details of the
implementation matter:

- The survival term is added on every step, including the intermediate
  steps of a coordinated round, where it equals $-(1-\gamma)\,\Phi_s(s)$.
  This is what makes the sum telescope when a step is one toon's decision.
- The threat term is added only on the step that resolves a round. In
  coordinated mode the intermediate steps get no threat term, so it does not
  telescope exactly per step.

## 3. Episodes

A street battle is one episode. A building, a VP or a CEO fight is one
episode across all of its floors or waves: when a floor is won and another
remains, the next floor's cogs are dealt and the episode continues with the
same laff and the same gags. This is what gives $n_{\text{after}}$ a
consequence. A gag saved on one floor can be spent on a later one inside the
same return.

The win bonus $W$ is paid each time a floor is won, not once per building,
because the reward is computed on the state before the next floor is dealt.

An episode is cut off when one floor runs longer than a cap (20 rounds; 60
for a VP floor) or the whole episode runs longer than six times that cap.
A cut-off episode is truncated, not lost, and is treated differently from a
terminal state in the next section.

## 4. The PPO objective

### 4.1 Collection

`envs` environments step in lockstep for `rollout` steps, giving a batch of
`envs` × `rollout` transitions per update (32 × 128 = 4,096 by default).
Actions are sampled from the masked distribution.

### 4.2 Reward normalisation

Rewards are divided by a running standard deviation before they are used
for learning. With $\hat\sigma$ the sample standard deviation of every
reward seen so far in the run:

$$
\tilde r_t = \frac{r_t}{\max(\hat\sigma,\,10^{-3})}
$$

The mean is not subtracted. A fixed scale was used first and replaced: gag
prices run from 0.23 to 4.70 against a win bonus of 100, and a fixed scale
small enough to keep the value loss in range left the whole range of gag
prices at a few per cent of the win signal. Evaluation reports returns in
the original units.

### 4.3 Truncation

When an episode is truncated, the critic's value of the cut-off state is
added to the last reward before normalisation:

$$
r_T \leftarrow r_T + \gamma\,V_\phi(s_{T+1})
$$

The step is then marked as an episode end. One property of the code as
written: $V_\phi$ is trained on normalised rewards, so it is in normalised
units, while $r_T$ at this point is in raw units and the sum is divided by
$\hat\sigma$ afterwards. The bootstrap term is therefore scaled down by a
factor of $\hat\sigma$ relative to an exact bootstrap.

### 4.4 Advantages

Generalised advantage estimation with $d_t = 1$ when step $t$ ended an
episode:

$$
\delta_t = \tilde r_t + \gamma\,(1 - d_t)\,V_\phi(s_{t+1}) - V_\phi(s_t)
$$

$$
\hat A_t = \delta_t + \gamma\lambda\,(1 - d_t)\,\hat A_{t+1}, \qquad \hat R_t = \hat A_t + V_\phi(s_t)
$$

Advantages are standardised over the whole batch (mean zero, unit standard
deviation) before the update.

### 4.5 Loss

With $\rho_t(\theta) = \pi_\theta(a_t \mid s_t) / \pi_{\theta_{\text{old}}}(a_t \mid s_t)$:

$$
\mathcal{L} = -\,\mathbb{E}_t\Big[\min\big(\rho_t \hat A_t,\; \operatorname{clip}(\rho_t,\, 1-\epsilon,\, 1+\epsilon)\,\hat A_t\big)\Big] \;+\; c_v\,\mathbb{E}_t\big[(V_\phi(s_t) - \hat R_t)^2\big] \;-\; \beta\,\mathbb{E}_t\big[H(\pi_\theta)\big] \;-\; \beta_{\text{tr}}\,\mathbb{E}_t\big[H_{\text{track}}(\pi_\theta)\big]
$$

The value loss is a plain squared error with no clipping. The actor and the
critic have separate trunks, so the value term's gradient does not reach the
actor's weights.

### 4.6 Entropy on the track marginal

The usual entropy bonus $H(\pi_\theta)$ is over all 250 actions. A policy
can satisfy it by spreading probability over which cog to hit while staying
committed to one track. Sweeping $\beta$ over 0.01, 0.04 and 0.10 left the
entropy of the gags actually thrown at 3.79 each time.

The second bonus is on the distribution over kinds of move. Group the
actions into nine classes $T$: the seven gag tracks, pass, and pink slip.

$$
p_{\text{track}}(T) = \sum_{a \in T} \pi_\theta(a \mid s), \qquad
H_{\text{track}} = -\sum_T p_{\text{track}}(T)\,\log\big(p_{\text{track}}(T) + 10^{-9}\big)
$$

$\beta_{\text{tr}}$ defaults to zero. The measured effect of 0.05 is in
[ml-design.md](ml-design.md#what-was-tried-on-the-policy).

### 4.7 Hyperparameters

Defaults of `tools/train_ppo.py`:

| quantity | symbol | default |
|---|---|---|
| parallel environments | | 32 |
| steps per environment per update | | 128 |
| epochs per update | | 4 |
| minibatch | | 1,024 |
| optimiser | | Adam, learning rate $3 \times 10^{-4}$, $\varepsilon = 10^{-5}$ |
| discount | $\gamma$ | 0.99 |
| GAE parameter | $\lambda$ | 0.95 |
| clip range | $\epsilon$ | 0.2 |
| value coefficient | $c_v$ | 0.5 |
| entropy coefficient | $\beta$ | 0.01 |
| track-entropy coefficient | $\beta_{\text{tr}}$ | 0.0 |
| gradient norm clip | | 0.5 |
| hidden width | | 256 |

## 5. The one-round scorer

The climb in the next section ranks plans with `_quick_score`, written
$Q(s, \mathbf{a})$ here. For a joint plan $\mathbf{a}$ (one action per
toon) it is an expectation over the accuracy rolls of the round:

$$
Q(s, \mathbf{a}) = \sum_{h} \Pr[h \mid s, \mathbf{a}]\; q(s, \mathbf{a}, h)
$$

where $h$ ranges over which rolls hit. Accuracy is rolled once per track
per target, so gags of the same track aimed at the same cog hit or miss
together, and $h$ has one component per such group. The leaf score $q$ is a
hand-weighted sum for the resulting board: cogs killed, incoming damage
prevented, laff healed, a credit for a trap laid, and charges for the gags,
pink slips and SOS cards spent. Its terms and weights are listed in
[scoring.md](scoring.md).

$Q$ is not the reward of section 2 and is not learned. It simulates the
toons' half of the round only; the cogs' reply enters through the expected
incoming damage $I(s)$, not through simulation.

## 6. The climb

At play time the policy's output is refined by `hybrid.climb`, a coordinate
ascent on $Q$ over joint plans.

**Start.** Each standing toon in turn takes the argmax of the masked logits,
with the earlier toons' picks visible to it. This gives $\mathbf{a}^{(0)}$.

**Sweep.** For each seat $i$, build a menu $\mathcal{M}_i$ and try each
entry in place of the seat's current action, keeping any strict improvement:

$$
\mathbf{a} \leftarrow \mathbf{a}[a_i \to a'] \quad \text{if} \quad Q(s, \mathbf{a}[a_i \to a']) > Q(s, \mathbf{a}), \qquad a' \in \mathcal{M}_i
$$

Sweeps repeat until one changes nothing or a budget of scorer calls is
spent. The defaults are a budget of 24 and a menu width of 16.

The menu $\mathcal{M}_i$ is, in order:

1. the seat's top 16 actions by logit, given the other seats' current
   choices;
2. if any cog has a trap armed, the cheapest lure of each scope (single
   target, group);
3. in a party, or when the top 16 are all one kind of move, the policy's
   best action of every (track, single or group) kind it has not already
   listed, and the pass;
4. the smallest gag that kills each cog outright, and the cheapest lures;
5. each SOS card the toon holds. These are judged without counting against
   the budget.

Items 2 to 5 exist because the scorer can only rank what it is shown. They
put in front of it moves the policy ranks too low to reach.

**Pair step.** Coordinate ascent cannot make a change that needs two seats
to move together. When a sweep changes nothing and budget remains, each pair
of seats is tried jointly over each seat's best action per kind (at most 7
per seat), again keeping any strict improvement.

**Unites.** A unite restores laff or gags and costs no turn, so it is
handled as a transformation of the state wrapped around the climb. Write
$s \oplus u$ for the state after unite $u$ and $\text{climb}(s)$ for the
plan the steps above return. With $P_u = 200$ (`unites.UNITE_PRICE`):

$$
u^\ast = \arg\max_{u \in U(s) \cup \{\varnothing\}} \Big[\, Q\big(s \oplus u,\ \text{climb}(s \oplus u)\big) - P_u\,\mathbb{1}[u \neq \varnothing] \,\Big]
$$

A unite is used only when the plan it enables beats the plan without it by
more than the price.

**SOS cards.** A card takes the toon's turn, so it competes inside the plan
as an ordinary candidate (item 5). The scorer charges 250 per call
(`sos.SOS_PRICE`).

The climb is deterministic. It walks ranked logits and enumerates the
accuracy rolls; nothing is sampled.

## 7. What the exact search computes

Results in these documents compare the policy with the Search row, so its
objective is stated here for reference. `solver/search/expectimax.py`
evaluates a solo position by

$$
V(s) = \max_{a \in \mathcal{A}(s)} \sum_{o} \Pr[o \mid s, a]\,\big(r(s, a, o) + V(s')\big)
$$

with exact outcome probabilities, down to a depth limit where a heuristic
value is used, or to the end of the battle when no limit is given. The
reward is built on `Objective.step_reward`, the solo counterpart of section
2.1, which has no horizon multiplier and no level 7 premium.

Chance nodes are pruned with \*-minimax (star1 and star2). Each outcome $i$
has a known probability $p_i$, a known reward $r_i$, and bounds
$f_i \le V(s'_i) \le c_i$ on the value still to be searched. The node's
value lies in

$$
\Big[\ \sum_i p_i\,(r_i + f_i),\ \ \sum_i p_i\,(r_i + c_i)\ \Big]
$$

and the node is cut when that interval leaves the window $(\alpha, \beta)$.
Star2 first tightens each $f_i$ by searching one action of the child, which
is a true lower bound on a maximising node. The pruned search returns the
same value and move as the exhaustive one.

## 8. Approximations to keep in mind

1. **The policy is trained on one reward and refined by another.** PPO
   optimises the return of section 2. The climb then maximises $Q$, a
   one-round score with different terms. Nothing forces the two to agree.
2. **$Q$ looks one round ahead.** The only exception is a credit for a trap
   laid this round, which pays off when a later lure lands.
3. **The policy ignores the playstyle preset.** The panel's presets change
   the weights of section 2.1 for the Search row. The policy was trained
   under `BALANCED` only, and $Q$ takes no objective.
4. **Values from different engines are not comparable.** $Q$, the PPO
   return, the exact search's $V$ and the Playout engine's score (cogs
   defeated) are four different scales. Engines are compared by the fights
   they win on the same seeds.
