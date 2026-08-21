# Four experiments on the reward function

All three seeds each, 6M steps, paired on the same three held-out sets
(31000 / 33000 / 39000, 120 buildings apiece). Baseline throughout is
`ppo_carry_s2`, the shipped policy. **Nothing here was shipped** -- no
configuration beat the baseline on the climb, which is the live agent.

| experiment | climb | plain |
|---|---|---|
| 1. survival shaping, `w=25` | **-3.4** | -1.2 |
| 1b. survival shaping, `w=5` | **-3.9** | -1.4 |
| 2. `toon_lost_penalty = 40` | -0.4 | **+2.6** |
| 3. `horizon_cost = scarcity_cost = 0` | -0.7 | +1.4 |

## What prompted them

A building is decided by the first toon loss and almost nothing else:
an intact party clears 100% of the time (60 for 60) and a party that has
lost anyone clears about 7%. The reward barely mentions this.
`toon_lost_penalty` is 0.0, so the step a toon goes sad is charged only
the laff of the final hit -- roughly -20, against a swing in win
probability nearer -186 -- and the terminal `-loss_penalty` does not
arrive until the wipe, ten to twenty steps later.

Experiments 1 and 2 are two ways to close that gap. Experiment 3 attacks
the opposite problem: `horizon_cost` and `scarcity_cost` defend against
gag exhaustion, and gag exhaustion never happens.

## 1 and 1b -- shaping is refuted, and the reason generalises

Phi(s) = w * (toons standing), applied as F = gamma*Phi(s') - Phi(s), so
by Ng, Harada & Russell (1999) it cannot change the optimal policy.

It cost 3-4 points at BOTH magnitudes: six training seeds, eighteen
set-comparisons, **every one negative on the climb**. The first run at
w=25 was open to the objection that Phi reached 100 -- the size of
`win_bonus` -- so w=5 was run specifically to rule the magnitude out. It
did not help; it was slightly worse.

This does not contradict the theorem. The theorem fixes the OPTIMUM, and
PPO never reaches the optimum; shaping changes the optimisation path, and
here it made it worse.

**The likely mechanism, and the transferable lesson: `toons alive` is
already in the observation.** It is one of the six globals. So the
shaping told the policy nothing it could not already see -- it only
perturbed the reward with a term reallocating credit the critic was
already learning to assign. Contrast experiment 2, which reprices the
same event and HELPED the policy by +2.6.

    Shape what the agent cannot observe. Reprice what it can.

## 2 -- the raw penalty helps the policy and not the agent

`toon_lost_penalty = 40` gives plain argmax +2.6, seven of nine
set-comparisons positive. The climb does not move: -0.4.

The passivity risk of an un-guaranteed penalty did not materialise at 40.
Seed 3 opened badly (-24.55 return, 7.5% of floors at 40k steps) and
recovered fully.

## 3 -- the conservation terms defend a phantom, and cost nothing either way

Zeroing both moved the outcome nowhere (climb -0.7, plain +1.4, mixed
signs both) but moved BEHAVIOUR a long way:

| | baseline | conservation off |
|---|---|---|
| level 4 | 46.0% | ~34% |
| level 5 | 20.9% | ~31% |
| level 7 | 3.5% | 3.4-3.5% |
| gags thrown | 3433 | 3484-3776 |
| pouch-outs | 0 | **0** |
| toons lost | 0.86 | 0.77-0.85 |

Two things settled. **Removing the sprinklers did not start a fire**:
pouch-outs stay at zero, so the conservation machinery really is
defending a failure mode that does not occur at these pouch sizes. And
**level-7 use does not move** (3.5% -> 3.5%), because `rare_gag_premium`
was left at 6.0 and, as the earlier `QUICK_W["price"]` sweep found,
level-7 use is governed by the policy's reluctance to propose one rather
than by price.

So the terms are neither earning their keep nor doing harm. They shift
which levels get thrown -- scarcity made high levels dearer, and without
it the agent moves off level 4 onto level 5 -- without changing what
happens.

## The finding that outlasts all four

**The climb is the binding constraint, not the policy.** It has sat at
68-69% across every policy-side change tried:

| change | plain | climb |
|---|---|---|
| carry-limit retrain | +2.8 | +1.2 |
| `toon_lost_penalty` | +2.6 | -0.4 |
| conservation off | +1.4 | -0.7 |
| survival shaping | -1.4 | -3.9 |
| track-entropy (earlier) | -4.5 | +1.1 |

Three separate changes have now cleared the policy's bar and failed to
reach the shipped agent's. `_quick_score` re-ranks whatever it is handed,
so the quality of its input has stopped mattering -- and the only change
that ever moved the climb made the policy WORSE.

Further PPO work cannot reach the live agent. The target is the scorer
or the climb procedure.

That target was taken up in [`scorer-audit.md`](scorer-audit.md): four
bugs in the party path, worth 69.5% -> 88.0% on the CEO at zero banquet
leftovers, and none of them reachable from the policy side.
