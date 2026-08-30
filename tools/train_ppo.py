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
    ap.add_argument("--obs-version", type=int, default=None,
                    help="train against an OLDER observation layout, as "
                         "a matched control. Defaults to the current "
                         "version. Only useful for comparing a new "
                         "feature against its own absence: comparing a "
                         "new run to the shipped policy cannot settle "
                         "anything, because that baseline was selected "
                         "and sits 3.8 sd above a fresh run.")
    ap.add_argument("--hidden", type=int, default=256,
                    help="trunk width; 512 is the capacity test")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--entropy", type=float, default=0.01)
    ap.add_argument("--track-entropy", type=float, default=0.0,
                    help="entropy bonus on the TRACK marginal rather than "
                         "the flat 246-way action distribution, which a "
                         "sweep showed cannot be moved by --entropy")
    ap.add_argument("--shaping", type=float, default=0.0,
                    help="potential-based shaping on incoming damage; "
                         "pays now for a cog lured or killed, which is "
                         "what the collapse onto Throw needs")
    ap.add_argument("--survival-shaping", type=float, default=0.0,
                    help="weight on a potential over toons still "
                         "standing; potential-based, so it cannot "
                         "change the optimum, only how fast the "
                         "credit for losing a toon arrives")
    ap.add_argument("--fire-fraction", type=float, default=0.0,
                    help="fraction of training positions that hand the party "
                         "pink slips. They are unmissable instant kills, so a "
                         "policy that never sees one leaves its fire logits "
                         "untrained and will not use slips it is holding")
    ap.add_argument("--fire-max", type=int, default=5,
                    help="most slips a toon gets in those positions")
    ap.add_argument("--objective", default="",
                    help="comma-separated overrides on the reward "
                         "objective, e.g. "
                         "toon_lost_penalty=40,horizon_cost=0")
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
    ap.add_argument("--facility-fraction", type=float, default=0.0,
                    help="share of episodes that are multi-floor "
                         "facilities, where a gag saved on one floor is "
                         "spent on the next and conserving finally pays")
    ap.add_argument("--boss-fraction", type=float, default=0.25,
                    help="share of episodes that are one side of a boss "
                         "-- the Sellbot VP or the CEO. These are the "
                         "only positions with Version 2.0 cogs, pink "
                         "slips as standard and cogs above level 12, so "
                         "without them the policy never sees any of it. "
                         "DEFAULTS ON: it was 0.0, which meant the "
                         "obvious training command produced a policy "
                         "blind to all three, and every shipped policy "
                         "since e835148 has passed 0.25 by hand anyway. "
                         "Pass 0.0 to train facilities only")
    ap.add_argument("--fire-cost", type=float, default=0.0,
                    help="charge the REWARD per pink slip spent. A slip "
                         "is an unmissable kill and the reward has never "
                         "priced one, so the fire logits learn it is free "
                         "-- a solo VP with ten slips drops from 49.5% "
                         "to 0.0%, with the policy's entire top four "
                         "being fires. The real cost is the round's "
                         "action: a fire removes one cog where a group "
                         "Lure neutralises four")
    ap.add_argument("--precision", type=float, default=0.0,
                    help="charge the REWARD for damage thrown past a "
                         "cog's remaining hit points. `waste` appeared "
                         "nowhere in env.py, so no shipped policy has "
                         "ever been told overkill is a thing -- it will "
                         "spend a Birthday Cake on a 20hp cog as "
                         "readily as on a 196hp one. Scaled by scarcity, "
                         "so a gag that is the only thing that kills "
                         "pays almost nothing. 0 reproduces the reward "
                         "every shipped policy was trained against")
    ap.add_argument("--solo-fraction", type=float, default=0.25,
                    help="share of boss and facility episodes cut down to "
                         "ONE toon. Both samplers build parties -- the VP "
                         "two, the CEO two, a facility two to four -- so "
                         "the policy never saw a boss or a facility solo, "
                         "which is exactly how the panel is used. The solo "
                         "toon gets a maxed pouch and 100-137 laff")
    ap.add_argument("--ceo-share", type=float, default=0.5,
                    help="of the boss episodes, the share that are CEO "
                         "rather than VP")
    ap.add_argument("--ceo-leftovers", default="0,10",
                    help="lo,hi range of banquet survivors drawn per CEO "
                         "episode. Fixing it at the shipped default of "
                         "10 would train almost entirely on a position "
                         "the agent clears 4%% of the time, which is "
                         "nearly no gradient at all")
    ap.add_argument("--strange-fraction", type=float, default=0.25,
                    help="mid-fight boards: already lured, armed traps, "
                         "picked-over pouches, someone nearly sad")
    ap.add_argument("--reward-scale", type=float, default=0.0,
                    help="fixed scale; 0 means normalise by a running "
                         "standard deviation instead, which preserves "
                         "relative magnitudes")
    args = ap.parse_args()

    # BEFORE ANY ENVIRONMENT EXISTS. `encode` reads the module global at
    # call time, so this has to be set before the first observation is
    # produced -- set it just before `build` instead and the net comes
    # out 302 wide while the envs are still emitting 306, which fails
    # as `mat1 and mat2 shapes cannot be multiplied`.
    if args.obs_version is not None:
        env_mod.OBS_VERSION = int(args.obs_version)
        env_mod.OBS_DIM = env_mod.obs_dim_for(env_mod.OBS_VERSION)

    import torch
    import torch.nn.functional as F

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)
    print(f"  device: {device}"
          + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    boss = args.boss_fraction
    if boss > 0:
        # The Big Cheese has a [TODO] accuracy, and `enable_big_cheese`
        # is the explicit opt-in that accepts a borrowed one. It is
        # ONE-WAY -- half a process holding borrowed accuracy and half
        # not is worse than either -- so it is called here, once, and
        # announced.
        from solver import ceo as ceo_mod
        from solver import vp as vp_mod
        ceo_mod.enable_big_cheese()
        lo_left, _, hi_left = args.ceo_leftovers.partition(",")
        lo_left, hi_left = int(lo_left), int(hi_left)
        ceo_share = args.ceo_share
        print(f"  boss positions: {boss:.0%} of episodes, "
              f"{ceo_share:.0%} of those CEO "
              f"({lo_left}-{hi_left} banquet leftovers), rest VP")

    sampler = None
    if (args.hard_fraction > 0 or args.combo_fraction > 0
            or args.facility_fraction > 0 or boss > 0):
        frac = args.hard_fraction
        strange = args.strange_fraction
        combo = args.combo_fraction
        fac = args.facility_fraction

        fire_fraction = args.fire_fraction
        fire_max = args.fire_max

        solo_fraction = args.solo_fraction

        def _make_solo(state, r):
            """Cut a party position down to one maxed toon.

            The boss and facility samplers all build parties, so a
            policy trained on them has never seen either fought alone --
            and alone is how the live panel is used. Keeps the toon that
            is already there, so its tracks stay a genuine draw rather
            than a fixed six.
            """
            from solver.state import Track

            toon = state.toons[0]
            toon.laff = toon.max_laff = r.randint(100, 137)
            toon.gag_counts = {}
            env_mod.restock(toon, r)
            state.toons = [toon]
            del Track
            return state

        def sampler(r, _f=frac, _s=strange, _c=combo, _fa=fac, _b=boss):
            # A boss side is a two-floor facility with Version 2.0 cogs,
            # pink slips as standard and cogs above level 12 -- none of
            # which appears anywhere else in the mix. `BattleEnv.reset`
            # reads `kind` and builds the right plan.
            if _b and r.random() < _b:
                if r.random() < ceo_share:
                    # Drawn per episode. `ceo_plan` reads the module
                    # global when `reset` builds the floors, immediately
                    # after this returns, so setting it here is what
                    # that episode gets.
                    ceo_mod.LEFTOVERS = r.randint(lo_left, hi_left)
                    state = ceo_mod.ceo_position(r)
                else:
                    state = vp_mod.vp_position(r)
                if solo_fraction and r.random() < solo_fraction:
                    state = _make_solo(state, r)
                # SLIPS BELONG TO BOSSES. The CEO already issued its own
                # five a toon, which is the real number and must not be
                # overwritten; the VP got none at all, which is why the
                # slip collapse was measured on the one fight the policy
                # had never held a slip in. See `env.grant_slips`.
                if state.kind == "vp":
                    env_mod.grant_slips(state, r, fire_fraction, fire_max)
                return state

            # A facility position becomes a multi-floor episode in
            # `BattleEnv.reset`, which is the only place a saved gag can
            # actually be spent later.
            if r.random() < _fa:
                state = env_mod.facility_position(r)
                if solo_fraction and r.random() < solo_fraction:
                    state = _make_solo(state, r)
            else:
                state = env_mod.mixed_position(r, _f, _s, _c)
                state.cogs_remaining = 0
                state.kind = "street"

            # NO SLIPS ON A STREET OR IN A BUILDING. They used to be
            # handed out HERE and nowhere else, which inverted the game:
            # the owner states that slips are for bosses and standard
            # play does not need them, buildings included.
            #
            # The reason it matters is not tidiness. A street battle is
            # one to four cogs, so firing one is most of the work and
            # "hold slips -> fire" is a fair habit there; it is the same
            # habit that loses fifty points at an eight-cog VP wave. The
            # policy learned slips in the one context where the lesson
            # does not transfer. See `env.grant_slips`.
            return state
    objective = None
    if args.objective:
        import dataclasses
        from solver.search import objective as objective_mod
        fields = {f.name for f in dataclasses.fields(objective_mod.Objective)}
        edits = {}
        for pair in args.objective.split(","):
            key, _, value = pair.partition("=")
            key = key.strip()
            if key not in fields:
                raise SystemExit(f"  no such objective field: {key!r}")
            edits[key] = float(value)
        objective = dataclasses.replace(objective_mod.DEFAULT, **edits)
        print(f"  objective overrides: {edits}")

    envs = [env_mod.BattleEnv(rng=random.Random(args.seed * 1000 + i),
                              sampler=sampler,
                              coordinated=args.coordinated,
                              shaping=args.shaping, gamma=args.gamma,
                              survival_shaping=args.survival_shaping,
                              precision=args.precision,
                              fire_cost=args.fire_cost,
                              objective=objective)
            for i in range(args.envs)]
    obs, masks = zip(*[e.reset() for e in envs])
    obs = list(obs)
    masks = list(masks)

    n_actions = len(env_mod.ACTIONS)

    # WHICH TRACK EACH ACTION BELONGS TO, so the entropy bonus can be put
    # on the track marginal instead of the flat 246-way distribution.
    #
    # The measured problem: sweeping the flat entropy coefficient 0.01 /
    # 0.04 / 0.10 moved gag entropy not at all -- 3.79 at every setting.
    # An action is (track, level, target) and there are five targets per
    # gag, so the policy satisfies a flat entropy bonus by spreading
    # probability over WHICH COG to hit while staying committed to
    # Throw. Entropy over actions is not entropy over tracks.
    #
    # The pass gets its own slot at the end, so "hold" is something the
    # track-entropy term can encourage too.
    # Pass gets a slot, and so does FIRE -- a pink slip has no track and
    # is not a hold, so it belongs in neither bucket. Without its own
    # slot this raised "None is not in list" the moment fires entered the
    # action table, which is the right failure: the mapping has to say
    # what every action is.
    track_of = torch.zeros(n_actions, dtype=torch.long, device=device)
    for _i, _a in enumerate(env_mod.ACTIONS):
        if _a is not None and _a.fire:
            track_of[_i] = len(env_mod.TRACKS) + 1
        elif _a is None or _a.is_pass:
            track_of[_i] = len(env_mod.TRACKS)
        else:
            track_of[_i] = env_mod.TRACKS.index(_a.track)
    n_tracks = len(env_mod.TRACKS) + 2
    track_onehot = torch.nn.functional.one_hot(
        track_of, num_classes=n_tracks).float()
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

    def evaluate_facility():
        """Buildings finished and floors cleared, on a FIXED set.

        The eval above draws street positions, so every learning curve
        this trainer has ever printed measured single battles -- while
        the thing actually being optimised is multi-floor play. A policy
        could have plateaued on facilities at 200k steps and the curve
        would still have looked healthy.

        Shaping is deliberately off here: this measures the real
        objective, not the one training is accelerated with.
        """
        floors, finished = [], []
        for seed in range(20_000, 20_000 + 40):
            e = env_mod.BattleEnv(rng=random.Random(seed),
                                  sampler=env_mod.facility_position,
                                  coordinated=args.coordinated)
            ob, mk = e.reset()
            done, info, guard = False, {}, 0
            while not done and guard < 300:
                guard += 1
                with torch.no_grad():
                    logits, _v = forward(
                        torch.tensor([ob], dtype=torch.float32,
                                     device=device),
                        torch.tensor([mk], dtype=torch.bool, device=device))
                    act = int(logits.argmax(dim=1).item())
                ob, mk, _r, done, info = e.step(act)
            cleared = info.get("floor", 1) - (0 if info.get("win") else 1)
            floors.append(max(0, cleared))
            finished.append(1.0 if info.get("win") else 0.0)
        return statistics.mean(floors), statistics.mean(finished)

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

                # Entropy on the TRACK MARGINAL: sum the action
                # probabilities within each track, then take the entropy
                # of that. This is the quantity a flat bonus could not
                # move, and the one that decides whether the agent ever
                # tries Lure, Toon-Up or holding.
                probs = dist.probs
                track_probs = probs @ track_onehot
                track_entropy = -(track_probs
                                  * (track_probs + 1e-9).log()).sum(-1).mean()

                loss = (loss_pi + args.vf * loss_v
                        - args.entropy * entropy
                        - args.track_entropy * track_entropy)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 0.5)
                opt.step()

        if update % args.eval_every == 0 or update == updates:
            ret, win = evaluate()
            rate = collected / (time.time() - started)
            fl, fin = evaluate_facility()
            print(f"    update {update:4d}/{updates}  steps {collected:8d}  "
                  f"EVAL return {ret:+7.2f}  win {win * 100:5.1f}%  "
                  f"| FACILITY floors {fl:4.2f} finished {fin * 100:5.1f}%  "
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
        # What `encode` meant when these weights were fitted. A reader
        # that ignores it loads a stale policy without complaint and
        # misreads its input, because OBS_DIM does not move when a
        # slot's scale does. See `env.OBS_VERSION`.
        "obs_version": env_mod.OBS_VERSION,
    }
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  exported to {args.export} "
          f"({Path(args.export).stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
