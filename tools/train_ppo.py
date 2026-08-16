"""PPO on the party battle environment (proposal P2).

    python tools/train_ppo.py --steps 2000000

Torch, GPU if present. Training lives here and never in `solver/`; what
ships is a plain-float export, the same rule `fit_heuristic` follows.

WHY PPO RATHER THAN MORE DISTILLATION
-------------------------------------
The policy head distilled from search (P0) lost end to end, and the
reason was structural: it can only approach the teacher, and the teacher
is itself approximate for parties. PPO learns from outcomes, so it has
no teacher ceiling.

It also sidesteps the actual bottleneck. A depth-2 party search spends
**95% of its time in `plans()`** enumerating and ranking joint plans;
a policy samples instead of enumerating and never pays that.

TWO THINGS THAT WOULD MAKE THE NUMBERS LIE
------------------------------------------
* **Masking must be inside the distribution, not a penalty.** Illegal
  actions get `-inf` logits so they carry no probability at all. Penalty
  shaping would let the agent learn to want an illegal move and be
  taxed for it, which is a different (and worse) problem.
* **Truncation is not termination.** An episode cut off at the round cap
  still has value ahead of it and must be bootstrapped; treating it as a
  terminal zero teaches the agent that surviving to the cap is worthless.
  `info["truncated"]` distinguishes them.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.rl import env as env_mod                           # noqa: E402


def build(obs_dim, n_actions, hidden, device):
    """SEPARATE trunks for actor and critic.

    Sharing one was the first version and it trained backwards -- eval
    return fell from +47.9 to +22.5 while the win rate dropped 88% to
    78%. Returns here run to about +/-100, so the value loss is of order
    10,000 against a policy loss of order 0.1: the shared trunk followed
    the critic and the policy was noise riding on top of it. Separate
    towers, plus reward scaling, keep the two gradients comparable.
    """
    import torch.nn as nn

    trunk = nn.Sequential(nn.Linear(obs_dim, hidden), nn.Tanh(),
                          nn.Linear(hidden, hidden), nn.Tanh()).to(device)
    vtrunk = nn.Sequential(nn.Linear(obs_dim, hidden), nn.Tanh(),
                           nn.Linear(hidden, hidden), nn.Tanh()).to(device)
    actor = nn.Linear(hidden, n_actions).to(device)
    critic = nn.Linear(hidden, 1).to(device)
    return trunk, vtrunk, actor, critic


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=400_000)
    ap.add_argument("--envs", type=int, default=32)
    ap.add_argument("--rollout", type=int, default=128)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--minibatch", type=int, default=1024)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--entropy", type=float, default=0.01)
    ap.add_argument("--vf", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--export", default="solver/rl/ppo_policy.json")
    ap.add_argument("--eval-positions", type=int, default=200)
    ap.add_argument("--eval-every", type=int, default=10)
    ap.add_argument("--hard-fraction", type=float, default=0.0,
                    help="share of episodes drawn from hard_position -- "
                         "solo against a wall of level 10-12 cogs, where "
                         "Lure stops being optional")
    ap.add_argument("--coordinated", action="store_true",
                    help="one shared policy chooses for EVERY toon, a "
                         "round at a time, instead of playing beside "
                         "SensiblePrior teammates")
    ap.add_argument("--combo-fraction", type=float, default=0.0,
                    help="reverse curriculum: episodes starting with a "
                         "trap already armed and a lure in hand, where "
                         "the payoff is one move away")
    ap.add_argument("--strange-fraction", type=float, default=0.25,
                    help="mid-fight boards: already lured, armed traps, "
                         "picked-over pouches, someone nearly sad")
    ap.add_argument("--reward-scale", type=float, default=0.0,
                    help="fixed scale; 0 means normalise by a running "
                         "standard deviation instead, which preserves "
                         "relative magnitudes")
    args = ap.parse_args()

    import torch
    import torch.nn.functional as F

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)
    print(f"  device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    sampler = None
    if args.hard_fraction > 0 or args.combo_fraction > 0:
        frac = args.hard_fraction
        strange = args.strange_fraction
        combo = args.combo_fraction
        sampler = (lambda r, _f=frac, _s=strange, _c=combo:
                   env_mod.mixed_position(r, _f, _s, _c))
    envs = [env_mod.BattleEnv(rng=random.Random(args.seed * 1000 + i),
                              sampler=sampler,
                              coordinated=args.coordinated)
            for i in range(args.envs)]
    obs, masks = zip(*[e.reset() for e in envs])
    obs = list(obs)
    masks = list(masks)

    n_actions = len(env_mod.ACTIONS)
    trunk, vtrunk, actor, critic = build(env_mod.OBS_DIM, n_actions,
                                         args.hidden, device)
    params = (list(trunk.parameters()) + list(vtrunk.parameters())
              + list(actor.parameters()) + list(critic.parameters()))
    opt = torch.optim.Adam(params, lr=args.lr, eps=1e-5)

    def forward(obs_batch, mask_batch):
        logits = actor(trunk(obs_batch))
        # Masking INSIDE the distribution: an illegal action gets no
        # probability, rather than probability and a penalty.
        logits = logits.masked_fill(~mask_batch, float("-inf"))
        return logits, critic(vtrunk(obs_batch)).squeeze(-1)

    # A FIXED evaluation set, because the training win rate is not a
    # learning signal: every episode samples a different position, so it
    # measures how hard the draw was, not how well the agent played. The
    # same set every time, with the same seeds, is the only way to see
    # improvement.
    eval_seeds = list(range(10_000, 10_000 + args.eval_positions))

    def evaluate(greedy=True):
        total, won = [], []
        for seed in eval_seeds:
            e = env_mod.BattleEnv(rng=random.Random(seed),
                                  coordinated=args.coordinated)
            ob, mk = e.reset()
            ret, done, info = 0.0, False, {}
            while not done:
                with torch.no_grad():
                    logits, _v = forward(
                        torch.tensor([ob], dtype=torch.float32,
                                     device=device),
                        torch.tensor([mk], dtype=torch.bool, device=device))
                    if greedy:
                        act = int(logits.argmax(dim=1).item())
                    else:
                        act = int(torch.distributions.Categorical(
                            logits=logits).sample().item())
                ob, mk, reward, done, info = e.step(act)
                ret += reward
            total.append(ret)
            won.append(1.0 if info.get("win") else 0.0)
        return statistics.mean(total), statistics.mean(won)

    def baseline_random():
        total, won = [], []
        for seed in eval_seeds:
            e = env_mod.BattleEnv(rng=random.Random(seed),
                                  coordinated=args.coordinated)
            ob, mk = e.reset()
            rng = random.Random(seed)
            ret, done, info = 0.0, False, {}
            while not done:
                choices = [i for i, ok in enumerate(mk) if ok]
                ob, mk, reward, done, info = e.step(rng.choice(choices))
                ret += reward
            total.append(ret)
            won.append(1.0 if info.get("win") else 0.0)
        return statistics.mean(total), statistics.mean(won)

    base_ret, base_win = baseline_random()
    print(f"  baseline (uniform random over legal actions): "
          f"return {base_ret:+7.2f}  win {base_win * 100:5.1f}%")

    # RUNNING REWARD NORMALISATION.
    #
    # A flat 0.01 scale kept the value loss in range and destroyed the
    # signal it was meant to preserve: gag prices run 0.23 to 4.70
    # against a win bonus of 100, so after scaling the entire
    # gag-scarcity range is 2-5% of the win signal. Measured over 120
    # battles, PPO spent 4.49 of gag value against the search's 2.81 and
    # reached nearly a level higher, while WINNING LESS -- it was not
    # trading resources for wins, it simply could not hear the price.
    #
    # Dividing by a running standard deviation keeps the loss in range
    # without flattening the ratios: a Railroad still costs twenty times
    # a Cupcake afterwards, where a fixed scale made both indistinguish-
    # able from zero next to a win.
    class RunningScale:
        def __init__(self):
            self.n, self.mean, self.m2 = 0, 0.0, 0.0

        def update(self, values):
            for v in values:
                self.n += 1
                delta = v - self.mean
                self.mean += delta / self.n
                self.m2 += delta * (v - self.mean)

        @property
        def std(self):
            if self.n < 2:
                return 1.0
            return max(1e-3, (self.m2 / (self.n - 1)) ** 0.5)

    scaler = RunningScale()

    started = time.time()
    finished, wins, collected = [], [], 0
    updates = max(1, args.steps // (args.envs * args.rollout))

    for update in range(1, updates + 1):
        buf_obs, buf_mask, buf_act = [], [], []
        buf_logp, buf_val, buf_rew, buf_done = [], [], [], []

        for _ in range(args.rollout):
            ob_t = torch.tensor(obs, dtype=torch.float32, device=device)
            mk_t = torch.tensor(masks, dtype=torch.bool, device=device)
            with torch.no_grad():
                logits, value = forward(ob_t, mk_t)
                dist = torch.distributions.Categorical(logits=logits)
                action = dist.sample()
                logp = dist.log_prob(action)

            buf_obs.append(ob_t)
            buf_mask.append(mk_t)
            buf_act.append(action)
            buf_logp.append(logp)
            buf_val.append(value)

            rewards, dones = [], []
            acts = action.tolist()
            for i, e in enumerate(envs):
                nob, nmask, reward, done, info = e.step(acts[i])
                # Bootstrap through a truncation: the episode was cut
                # off, not lost, and its future is not worth zero.
                if done and info["truncated"]:
                    with torch.no_grad():
                        tail = forward(
                            torch.tensor([nob], dtype=torch.float32,
                                         device=device),
                            torch.tensor([nmask], dtype=torch.bool,
                                         device=device))[1].item()
                    reward += args.gamma * tail
                # Scaled for LEARNING only. Returns of +/-100 give a
                # value loss four orders of magnitude above the policy
                # loss; eval below reports real units.
                rewards.append(reward)
                dones.append(float(done))
                if done:
                    finished.append(info["rounds"])
                    wins.append(1.0 if info["win"] else 0.0)
                    nob, nmask = e.reset()
                obs[i], masks[i] = nob, nmask
                collected += 1

            # Normalise AFTER the truncation bootstrap, so the tail
            # value is scaled with everything else rather than added in
            # different units.
            if args.reward_scale > 0:
                rewards = [r * args.reward_scale for r in rewards]
            else:
                scaler.update(rewards)
                rewards = [r / scaler.std for r in rewards]
            buf_rew.append(torch.tensor(rewards, dtype=torch.float32,
                                        device=device))
            buf_done.append(torch.tensor(dones, dtype=torch.float32,
                                         device=device))

        with torch.no_grad():
            last_value = forward(
                torch.tensor(obs, dtype=torch.float32, device=device),
                torch.tensor(masks, dtype=torch.bool, device=device))[1]

        # GAE
        advantages = [None] * args.rollout
        gae = torch.zeros(args.envs, device=device)
        for t in reversed(range(args.rollout)):
            nxt = last_value if t == args.rollout - 1 else buf_val[t + 1]
            nonterminal = 1.0 - buf_done[t]
            delta = buf_rew[t] + args.gamma * nxt * nonterminal - buf_val[t]
            gae = delta + args.gamma * args.lam * nonterminal * gae
            advantages[t] = gae
        adv = torch.stack(advantages).reshape(-1)
        returns = adv + torch.stack(buf_val).reshape(-1)

        flat_obs = torch.cat(buf_obs)
        flat_mask = torch.cat(buf_mask)
        flat_act = torch.cat(buf_act)
        flat_logp = torch.cat(buf_logp)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)

        n = flat_obs.shape[0]
        index = torch.arange(n, device=device)
        for _epoch in range(args.epochs):
            index = index[torch.randperm(n, device=device)]
            for start in range(0, n, args.minibatch):
                sel = index[start:start + args.minibatch]
                logits, value = forward(flat_obs[sel], flat_mask[sel])
                dist = torch.distributions.Categorical(logits=logits)
                logp = dist.log_prob(flat_act[sel])
                ratio = (logp - flat_logp[sel]).exp()
                a = adv[sel]
                loss_pi = -torch.min(
                    ratio * a,
                    ratio.clamp(1 - args.clip, 1 + args.clip) * a).mean()
                loss_v = F.mse_loss(value, returns[sel])
                entropy = dist.entropy().mean()
                loss = loss_pi + args.vf * loss_v - args.entropy * entropy
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 0.5)
                opt.step()

        if update % args.eval_every == 0 or update == updates:
            ret, win = evaluate()
            rate = collected / (time.time() - started)
            print(f"    update {update:4d}/{updates}  steps {collected:8d}  "
                  f"EVAL return {ret:+7.2f}  win {win * 100:5.1f}%  "
                  f"({rate:5.0f} steps/s)", flush=True)

    payload = {
        "obs_dim": env_mod.OBS_DIM, "n_actions": n_actions,
        "hidden": args.hidden,
        "trunk": {k: v.detach().cpu().tolist()
                  for k, v in trunk.state_dict().items()},
        # The VALUE trunk too. The critic reads from its own tower since
        # the shared-trunk fix, so exporting `critic` without `vtrunk`
        # saved a head with nothing to feed it -- the policy's moves
        # reloaded fine and its grades were simply unrecoverable, which
        # is the sort of gap that hides until someone asks the model
        # what it thinks a position is worth.
        "vtrunk": {k: v.detach().cpu().tolist()
                   for k, v in vtrunk.state_dict().items()},
        "actor": {k: v.detach().cpu().tolist()
                  for k, v in actor.state_dict().items()},
        "critic": {k: v.detach().cpu().tolist()
                   for k, v in critic.state_dict().items()},
        "eval_return": evaluate()[0], "eval_baseline": base_ret,
        "coordinated": args.coordinated,
    }
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  exported to {args.export} "
          f"({Path(args.export).stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
