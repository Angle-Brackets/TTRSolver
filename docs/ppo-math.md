# The maths, as implemented

Written against the code, not against a textbook: every symbol here has
a line number behind it. Where this project departs from standard PPO —
and it does, in three places that matter — the departure is marked.

## 1. The decision problem

A battle is a Markov game the solver treats as an MDP over the party's
*joint* action. State $s$ is a `BattleState`: each toon's laff, pouch,
training and organic tracks; each cog's level, department, HP and status
(lured with a countdown, trapped with a damage or level, a v2.0's outer
suit); plus `round_num` and `cogs_remaining`.

The action set is a fixed table of $|\mathcal{A}| = 250$ entries
(`env.ACTIONS`) — every (track, level, target) triple, four pink-slip
targets, and a pass. Legality is a mask $m(s) \in \{0,1\}^{250}$, and it
is enforced by construction rather than by penalty:

$$
\pi_\theta(a \mid s) = \operatorname{softmax}\big(z_\theta(s) + \log m(s)\big)_a
$$

so illegal actions receive $-\infty$ logits and exactly zero
probability. **Two things live outside this table** and cannot be
expressed as an $a$: unites, because they cost no turn, and SOS cards,
because adding them would change $|\mathcal{A}|$ and invalidate every
trained policy. Both are handled in §5.

## 2. What a round is worth

`party_search.round_reward`. With $\ell$ laff lost by the team, $G$ the
multiset of gags spent, $k$ toons knocked out:

$$
r = -w_\ell \cdot \ell \;-\; \sum_{g \in G} c(g) \;-\; w_k k \;-\; \tau \;+\; W\mathbb{1}[\text{won}] \;-\; L\mathbb{1}[\text{lost}]
$$

with $\tau$ a flat per-round cost (`turn_cost`, so dithering is priced)
and $W = L = 100$. The gag price carries the horizon:

$$
c(g) = \Big(\text{gag\_cost} \cdot \text{level}(g) + \frac{\text{scarcity\_cost}}{\text{carry}(g)}\Big)\big(1 + \eta \cdot \text{cogs\_remaining}\big)
$$

$\eta = 0.15$. **This is why a Railroad spent on floor one costs more
than the same Railroad spent on the last cog of the day** — the same
gag, priced by how much fighting is still to come.

## 3. Learning: PPO, with one non-standard term

Trajectories come from 32 environments stepped in lockstep, 128 steps
per update. Advantages by GAE($\lambda$), $\gamma = 0.99$,
$\lambda = 0.95$:

$$
\delta_t = r_t + \gamma V_\phi(s_{t+1})(1 - d_t) - V_\phi(s_t), \qquad
\hat{A}_t = \sum_{l \ge 0} (\gamma\lambda)^l\,\delta_{t+l}(1 - d_{t+l})
$$

The clipped surrogate, with $\rho_t(\theta) = \exp(\log \pi_\theta(a_t|s_t) - \log \pi_{\theta_{\text{old}}}(a_t|s_t))$:

$$
\mathcal{L}^{\text{PPO}} = -\,\mathbb{E}_t\Big[\min\big(\rho_t \hat{A}_t,\; \operatorname{clip}(\rho_t, 1-\epsilon, 1+\epsilon)\hat{A}_t\big)\Big] + c_v\,\mathbb{E}_t\big[(V_\phi(s_t) - \hat{R}_t)^2\big] - \beta\,\mathbb{E}_t[H(\pi_\theta)] - \beta_{\text{tr}}\,\mathbb{E}_t[H_{\text{track}}(\pi_\theta)]
$$

$\epsilon = 0.2$, $c_v = 0.5$, $\beta = 0.01$, gradients clipped to
norm $0.5$.

**$H_{\text{track}}$ is the non-standard term, and it exists because a
measurement said it had to.** Entropy over 250 actions is not entropy
over the seven tracks: the policy satisfies a flat bonus by spreading
mass across *levels and targets within one track*. Sweeping $\beta$ over
$\{0.01, 0.04, 0.10\}$ moved gag entropy not at all — 3.79 at every
setting. So the bonus is also available on the track marginal:

$$
p_{\text{track}}(T) = \sum_{a \in T} \pi_\theta(a \mid s), \qquad
H_{\text{track}} = -\sum_T p_{\text{track}}(T) \log p_{\text{track}}(T)
$$

which is the quantity that decides whether the agent ever tries Lure,
Toon-Up, or holding.

## 4. The policy is a proposer, not the agent

$\pi_\theta$ never plays directly. `hybrid.climb` does coordinate ascent
on the joint plan $\mathbf{a} = (a_1, \dots, a_n)$, judged by
$Q(s, \mathbf{a}) \equiv$ `_quick_score`:

$$
\mathbf{a}^{(k+1)} = \arg\max_{\mathbf{a} \in \mathcal{N}(\mathbf{a}^{(k)})} Q(s, \mathbf{a}), \qquad
\mathcal{N}(\mathbf{a}) = \bigcup_{i} \big\{ \mathbf{a}[a_i \!\to\! a'] : a' \in \mathcal{M}_i \big\}
$$

Seat $i$'s menu $\mathcal{M}_i$ is the policy's top-$k$ by logit, *plus*
targeted probes the policy ranks nowhere — the cheapest killing gag per
cog, the cheapest lure of each scope on a trapped board, and the pass.
Ascent runs to a fixed point or until the evaluation budget (24) is
spent, then tries pairwise joint moves.

The division of labour is the point: **$\pi_\theta$ proposes, $Q$
disposes.** A policy that ranks a good move nowhere loses it — which is
what the probes exist to prevent, and why raising the budget from 8 to
24 was worth 14 points.

## 5. The two things outside the action table

**A unite costs no turn**, so a round is *two* decisions. Rather than
multiply the action space, the state is transformed and re-planned:

$$
V^{+}(s) = \max\Big(\;\max_{u \in U(s)} \big[\,Q\big(s \oplus u,\, \text{climb}(s \oplus u)\big) - P_u\,\big],\;\; Q\big(s, \text{climb}(s)\big)\Big)
$$

so a unite must beat the no-unite plan *by more than its price* $P_u$.
Both engines share this (`unites.best_with_unite`).

**An SOS is the move**, so its turn cost is already paid — the plan
holds no gag for that toon and the damage terms fall out on their own.
Its price therefore carries only scarcity, which is why $P_{\text{SOS}}$
is 250 and not 400.

## 6. The exact solo search

Solo, the tree is finite: every action spends a gag and the pouch only
shrinks, so `expectimax.solve` returns a true value with no heuristic.

$$
V(s) = \max_{a \in \mathcal{A}(s)} \sum_{o} \Pr[o \mid s, a]\; \big(r(s, a, o) + V(s')\big)
$$

Chance nodes are the accuracy rolls times each cog's attack times its
target choice. Two things make it tractable: a transposition memo on
`outcomes.state_key`, and star1/star2 pruning, which bounds a chance
node's value from the children evaluated so far —

$$
V_{\text{chance}} \le \sum_{i < j} p_i v_i + p_j U + \Big(1 - \sum_{i \le j} p_i\Big) U
$$

for an upper bound $U$ on any child — and cuts the branch when that
bound cannot beat the incumbent.

**Accuracy is rolled per (track, target), not per gag.** Gags of the
same track at the same cog share one die, so they land or miss together.
Rolling independently would let a party hedge — four Throws at one cog
would almost certainly land *something* — which is not the game and
badly overvalues stacking.

## 7. Where the maths stops being honest

- **Party values are estimates.** `party_search` samples; its numbers
  are not comparable with `solve()`'s.
- $Q$ is a one-round scorer with a single exception: it looks one step
  past the round for a trap, because a trap deals nothing until a lure
  arrives and would otherwise score zero.
- $Q$ cannot see laff *level*, only deltas — `_score_leaf` simulates
  the toon phase, where laff does not move. `survival_rounds` is the one
  term that reads the level, which is why a heal is worth exactly zero
  without it.
