"""PPO proposes, the search's scorer judges.

The policy costs a third of a millisecond a decision and the party
search costs a hundred, so there is room to spend a little of that gap
checking the policy's own suggestions. This samples a few joint plans
from the trained policy and keeps whichever one `_quick_score` likes
best.

Measured over 180 HELD-OUT buildings -- seeds never tuned against,
which matters because the tuned set flattered this badly:

    agent                floors  finished   plans/second
    plain PPO              2.44     61.7%           2266
    climb, budget 8        2.49     66.1%            656
    climb, budget 16       2.48     66.1%            467
    best-of-16 sampling       -         -            106
    full search            2.48     67.8%              1

`climb` recovers about two thirds of the distance from the policy to
the search for roughly double the policy's cost, and it is
deterministic -- it walks the policy's ranked logits rather than
sampling, so it returns the same plan every time.

THE SEARCH IS STILL AHEAD, by 1.7 points. On the tuned seeds this
scored 69.4% against the search's 65.0% and looked like a win; on fresh
buildings it is 66.1% against 67.8%. Same code, same budget. Anything
measured on the set it was chosen on is worth re-running elsewhere.

BUDGET 8 BEATS BUDGET 16 on the tuned set (69.4% against 66.7%) and
ties it here. `_quick_score` is an approximation, so climbing it harder
optimises the proxy rather than the game -- more budget is not
automatically better, which is the tell that the scorer, not the
search strategy, is now the ceiling.

WHERE THE REMAINING GAP IS
--------------------------
Usage over 80 held-out buildings, climb at budget 8 against the search:

    holds      2.1%   11.0%      <- the big one
    throw     44.4%   35.1%
    squirt    20.3%   23.4%
    sound     11.4%   14.1%
    drop      10.0%    8.2%
    lure       7.8%    9.5%
    toon_up    4.8%    6.7%
    trap       1.3%    2.9%

CLIMB ALWAYS SWINGS. It declines to act on 2.1% of decisions against
the search's 11.0%, throws 13% more gags over the same buildings (2159
against 1918), and skews to level 4 (38.1% against 27.9%) where the
search prefers 5 and 6. More gags, each weaker, and almost never a
hold.

Every one of those differences is the same thing: `_quick_score` pays
for damage landed, so an action that deals none scores near zero
whatever it saves. Healing is the visible case -- on seed 31003 the
search heals three times in seven rounds and holds the party at 48-55
laff, while the climb heals twice, the second time at [2, 17, 2], and
loses the building with two toons carrying Toon-Up 7.

A caution about the obvious fix, learnt the hard way: hold-variants
were forced into the SEARCH's shortlist once and play got worse, 2.07
floors to 1.83, and that was written down as "the overkill is not a
bug". It was ranked by `_quick_score` too. What that experiment
actually showed is that holding *as this scorer judges it* is bad --
the search's own 11% comes from sampled rollouts, which can see a
conserved gag spent later.

WHY IT WORKS
------------
PPO is a better PROPOSAL DISTRIBUTION than the search's enumeration.
`party_search.plans` builds joint plans combinatorially and then
truncates, and that truncation is where a long line of this project's
bugs have lived -- a stratified cut that dropped every Sound plan, a
shortlist that dropped Trap in 39 of 39 positions, a lexicographic
prefix that dropped the best line outright. The policy suggests a
handful of plausible plans directly and the scorer only has to rank
those.

THE JUDGE MUST NOT BE THE PROPOSER
----------------------------------
Ranking the same samples with PPO's own critic achieves nothing: 57.8%
at four plans and 58.3% at twelve, against 58.9% for plain argmax. It
asks the network to catch its own mistakes, and a network that could
would not be making them. `docs/ml-design.md` records the learned-leaf
evaluator losing in place for the same reason. `_quick_score` is an
independent opinion and that is the whole point of it.

Needs numpy, and says so by returning False from `available()` rather
than raising -- the same contract `search/policy.py` follows. Torch
never appears here; what ships is the plain-float export.
"""
from __future__ import annotations

import itertools
import json
import math
import random
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from .. import data
from .. import mechanics
from .. import party as party_mod
from .. import sos as sos_mod
from .. import unites as unites_mod
from ..rl import env as env_mod
from ..state import Action, BattleState, Track
from . import objective as objective_mod
from . import party_search

# How much of the follow-up round counts when `judge="deep"`. Less than
# one because the second round is played by a greedy stand-in rather
# than by whatever will really happen.
LOOKAHEAD_DISCOUNT = 0.7

# Per-round discount for `rollout_judge`. Near one because a building is
# long and a gag saved on floor one is spent on floor four; the reward
# function already prices the horizon through `cogs_remaining`.
ROLLOUT_DISCOUNT = 0.95

_EXPORT = Path(__file__).resolve().parents[1] / "rl" / "ppo_facility.json"
_MODEL: Optional[dict] = None
_TRIED = False
# Why the last load attempt failed, for `unavailable_reason`.
_REASON: Optional[str] = None


def _load():
    """The exported policy, or None if it is missing or unusable."""
    global _MODEL, _TRIED, _REASON
    if _TRIED:
        return _MODEL
    _TRIED = True
    try:
        import numpy as np                                   # noqa: F401
    except ImportError:
        _REASON = "numpy is not installed"
        return None
    if not _EXPORT.exists():
        _REASON = f"no exported policy at {_EXPORT}"
        return None
    try:
        payload = json.loads(_EXPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _REASON = f"{_EXPORT.name} could not be read: {exc}"
        return None

    mismatch = env_mod.check_export(payload)
    if mismatch:
        # Trained against a different observation or action table. A
        # silent mismatch reads 302 floats through weights expecting
        # 290 and returns confident nonsense.
        #
        # The REASON is kept rather than discarded. It used to be
        # thrown away, so a policy invalidated by an observation change
        # was reported to the user as "numpy or the policy is missing"
        # -- which is not what happened and sends them looking in the
        # wrong place entirely.
        _REASON = mismatch
        return None

    import numpy as np
    layers, i = [], 0
    while f"{i}.weight" in payload["trunk"]:
        layers.append((np.array(payload["trunk"][f"{i}.weight"]).T,
                       np.array(payload["trunk"][f"{i}.bias"])))
        i += 2
    _MODEL = {
        "trunk": layers,
        "aw": np.array(payload["actor"]["weight"]).T,
        "ab": np.array(payload["actor"]["bias"]),
        # CARRIED, not dropped. `_logits` feeds this back to `encode` so
        # a policy is read with the layout it was fitted to. Rebuilding
        # the model dict from selected keys silently lost it, and every
        # version 2 policy was then read through the version 1 encoder
        # -- the exact silent misread the version exists to prevent, and
        # invisible because the shipped policy IS version 1 and so was
        # right by accident.
        "obs_version": int(payload.get("obs_version", 1)),
    }
    return _MODEL


def available() -> bool:
    """Is a usable policy loadable? False means fall back, not fail."""
    return _load() is not None


def unavailable_reason() -> Optional[str]:
    """Why `available()` is False, in words, or None if it is True.

    Every caller that reports the failure should print this rather than
    guessing at the cause.
    """
    if _load() is not None:
        return None
    return _REASON or "the policy could not be loaded"


def _logits(model, state: BattleState, seat: int, pending,
            reject=None):
    import numpy as np


    # A policy exported before the slip feature changed scale must be
    # fed the layout it was fitted to. Absent key means version 1, the
    # `min(fires, 10) / 10` encoding; see `env.OBS_VERSION`.
    x = np.array(env_mod.encode(state, seat, pending,
                                obs_version=model.get("obs_version", 1)),
                 dtype=float)
    for weight, bias in model["trunk"]:
        x = np.tanh(x @ weight + bias)
    out = x @ model["aw"] + model["ab"]
    mask = env_mod.legal_mask(state, seat)
    out = np.where(np.array(mask), out, -np.inf)
    if reject:
        # Masked here rather than filtered afterwards, so a rejected
        # move is invisible to the hill-climb instead of being proposed
        # and discarded -- otherwise `climb` spends its budget
        # rediscovering the answer that was just turned down.
        for index, entry in enumerate(env_mod.ACTIONS):
            # ANY granularity the entry answers to -- gag, kind, or
            # track. Testing one key would make the set's meaning depend
            # on which control produced it.
            if index < len(out) and not reject.isdisjoint(reject_keys(entry)):
                out[index] = -np.inf
    return out


def _choose(values, rng, sample: bool) -> int:
    import numpy as np

    if not sample:
        return int(np.argmax(values))
    finite = np.isfinite(values)
    if not finite.any():
        return 0
    shifted = np.where(finite, values - values[finite].max(), -np.inf)
    weights = np.where(finite, np.exp(shifted), 0.0)
    total = float(weights.sum())
    if total <= 0:
        return int(np.argmax(values))
    roll = rng.random() * total
    for index, weight in enumerate(weights):
        roll -= float(weight)
        if roll <= 0:
            return index
    return int(np.argmax(values))


def propose(state: BattleState, rng, sample: bool = True,
            fixed: Optional[Mapping[int, Optional[Action]]] = None,
            reject=None) -> List[Optional[Action]]:
    """One joint plan, every standing toon choosing in turn.

    Later toons see the earlier ones' picks through `pending`, which is
    what makes this a joint plan rather than four independent ones.

    `fixed` pins seats that have ALREADY COMMITTED, which matters when
    the caller is midway through a round rather than starting one. It is
    a mapping rather than a list because `None` already means "pass" in
    a plan, and a pinned pass and an open seat are not the same thing.
    """

    model = _load()
    if model is None:
        raise RuntimeError("no usable policy; check hybrid.available()")

    fixed = dict(fixed or {})
    pending: List[Optional[Action]] = [None] * len(state.toons)
    for seat, action in fixed.items():
        pending[seat] = action
    for seat, toon in enumerate(state.toons):
        if seat in fixed or toon.laff <= 0:
            continue
        index = _choose(_logits(model, state, seat, pending, reject),
                        rng, sample)
        action = env_mod.action_at(index)
        pending[seat] = None if action.is_pass else action
    return pending


def rollout_judge(state: BattleState, plan, seed: int, depth: int = 3,
                  objective=None) -> float:
    """Play the plan, then let PPO play on, and total the real reward.

    The horizon `_quick_score` does not have. It scores ONE round --
    expected over the accuracy rolls, not all-hit; this said all-hit
    long after that changed -- with a hand-weighted sum whose weights turn out not to
    matter -- four random weight vectors finish 62.5-65.0% of the same
    buildings, and zeroing every term costs five points. So the terms
    matter and their sizes do not, which is what a flat proxy looks
    like.

    This scores the future with `round_reward` instead: the objective
    the environment actually pays, over several rounds of PPO's own
    play. It is Bertsekas's rollout with the learned policy as the base,
    which is what makes the guarantee interesting -- a rollout policy is
    no worse than its base when the evaluation is sound.

    NOT the two-ply judge that failed earlier. That one let
    `greedy_plan` answer for the next round, and greedy is a myopic
    proxy, so it added a guess about the future to a real reading of the
    present and weighted the guess at 0.7. It cost nearly three points.
    PPO is a considerably better base policy than greedy, and it is fast
    enough to run several rounds.

    COMMON RANDOM NUMBERS. Every candidate plan is rolled out from the
    same `seed`, so the accuracy rolls and cog attacks are identical
    across candidates and the comparison is paired. Without that the
    climb would reliably pick whichever plan drew the luckiest dice,
    which with eight candidates is most of them.

    IT IS OFF, AND THE REASON IS THE USEFUL PART. Over 180 held-out
    buildings, climb at budget 8:

        `_quick_score`, one round      64.4%   0.76 ms
        PPO rollout, two rounds        61.1%   2.50 ms
        PPO rollout, four rounds       60.6%   3.23 ms

    Deeper is monotonically worse, and cost is not the issue at three
    milliseconds. The judge is: scoring a plan by what happens when PPO
    PLAYS ON measures how well PPO exploits the resulting position, not
    how good the position is. A strong plan leading somewhere PPO
    handles badly is marked down. It is circular.

    Third time that has been established here. PPO's own critic ranking
    PPO's samples: 57.8-58.3% against 58.9% for plain argmax. A two-ply
    lookahead played by `greedy_plan`: nearly three points worse. This:
    three to four points worse. The only judge that has ever helped is
    `_quick_score`, which shares none of the proposer's blind spots and
    is worth 58.9% to 64.4%.

    It is also why the SEARCH works: `rollout_value` plays forward with
    `greedy_plan`, a different policy from the plans it grades.

    The horizon idea is not refuted, only this way of getting one --
    Toon-Up use does rise 4.1% to 5.3% with rollouts on, so the longer
    view pushes where it should. What is refuted is asking the policy to
    grade itself.
    """
    from . import party_search as ps

    objective = objective or objective_mod.BALANCED
    rng = random.Random(seed)
    total, current, live = 0.0, state, list(plan)
    for step in range(max(1, depth)):
        if current.is_terminal():
            break
        try:
            nxt, _healed, _done = party_mod.step(
                current, live[0], mode=party_mod.Mode.COORDINATED,
                joint=live, rng=rng)
        except (NotImplementedError, ValueError, KeyError):
            break
        laff_lost = sum(max(0, b.laff - a.laff)
                        for b, a in zip(current.toons, nxt.toons))
        went_sad = sum(1 for b, a in zip(current.toons, nxt.toons)
                       if b.laff > 0 and a.laff <= 0)
        total += (ROLLOUT_DISCOUNT ** step) * ps.round_reward(
            objective, laff_lost, ps._spent(current, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win(),
            toons_lost=went_sad,
            cogs_remaining=current.cogs_remaining)
        current = nxt
        if current.is_terminal():
            break
        live = propose(current, rng, sample=False)
    return total


def _judge(state: BattleState, plan, deep: bool) -> float:
    """Rank a plan. One round, or two.

    `_quick_score` scores a single round, which is why a trap scores
    near zero and why climbing it harder stops paying: it cannot see
    anything that arrives next round.

    NOT "all-hit", which this said for a long time after it stopped
    being true. It takes the expectation over the accuracy rolls, and
    that change is why the CEO went 69.5% -> 75.0%: an all-hit score
    prefers the biggest number printed on a gag, which is reliably the
    least likely one to land. The horizon is what is missing here, not
    the dice. `deep` plays the plan, then
    lets `greedy_plan` answer for the round after, and counts that at
    LOOKAHEAD_DISCOUNT.

    This is what the search has and the climb did not. `party_search`
    scores its plans with `rollout_value`, several rounds of play; this
    is the cheapest possible imitation of it.

    IT IS OFF, having been measured. Over 180 held-out buildings:

        1-ply, budget 8      66.7% finished   0.61 ms
        1-ply, budget 12     65.0%            0.73 ms
        2-ply, budget 8      63.9%            1.82 ms
        2-ply, budget 12     63.9%            2.38 ms

    Nearly three points worse at three times the cost. The second round
    is played by `greedy_plan`, which is a myopic proxy itself, so this
    adds a GUESS about the next round to a real evaluation of this one
    and weights the guess at 0.7. A lookahead is only as good as the
    policy that plays it forward.

    Third judge improvement to fail: trap credit was worth +0.6 (noise),
    track probes -2.8, this -2.8. Plain one-ply `_quick_score` at budget
    8 has beaten all of them.
    """
    from . import party_search as ps

    first = ps._quick_score(state, plan)
    if not deep:
        return first
    probe = state.clone()
    try:
        ps.simulator.apply_party_round(
            probe, list(plan), hits=[a is not None and not a.is_pass
                                     for a in plan])
    except (NotImplementedError, ValueError, KeyError):
        return first
    if probe.is_terminal():
        return first
    try:
        follow = ps.greedy_plan(probe, objective_mod.BALANCED)
        return first + LOOKAHEAD_DISCOUNT * ps._quick_score(probe, follow)
    except (NotImplementedError, ValueError, KeyError):
        return first


# Whether a probe menu distinguishes a group gag from a single-target
# one of the same track. Toggleable because the effect is still being
# measured and the honest state of it is "unproven": see the A/B in
# `_track_key`.
GROUP_GAGS_PROBED_SEPARATELY = True

# MEASURED NEUTRAL, kept as a correctness rule rather than a win. Paired
# over four cells: 33 up / 31 down, p=0.90. Blocking the move without
# giving the seat anywhere better to go just changes which gag is spent.
#
# Reject a plan that throws a Drop at cogs its OWN Lure puts to sleep.
# Drop resolves after Lure and always misses a lured cog, so such a gag
# only lands in the branch where the plan's own Lure missed. The scorer
# prices that correctly -- on a real board a Grand Piano behind a 70%
# Lure was worth +90, because in the 30% branch it lands and may kill --
# and it is still a bad trade: a level 6 Drop is scarce and the fight is
# long. This is a judgement about gag economy that a one-round scorer
# cannot make, so it is a rule rather than a weight.
NO_DROP_INTO_OWN_LURE = True

# MEASURED NEUTRAL: 57 up / 54 down, p=0.85 over six cells. Kept because
# the move was UNREACHABLE rather than rejected, which is a different
# defect from being unwanted -- the same one that hid Trap at rank 25 and
# the group gags. With both this and the Drop rule on, the pair read 53
# up / 68 down (p=0.20), which neither component supports; three
# underpowered tests, and the honest summary is that none of them moves
# the win rate.
#
# Note `simulator.legal_actions` predicts the ceiling here: a lured cog
# does not attack, so on a fully-lured board a pass costs no laff and no
# gag, and `_quick_score` plays ONE round -- the cost of coasting while
# the lure lapses is off its horizon. Making the move reachable cannot
# help until the judge can see that.
#
# Always put "hold" in front of the judge. Without it the pass entry is
# unreachable: it lives in `ACTIONS` as None so the track probes skip it,
# and the policy ranks it near last on exactly the boards where it is
# right. Legality was never the constraint.
ALWAYS_PROBE_PASS = True

LAST_UNITE = None
"""The unite `climb` chose on its last call, or None.

A module global rather than a second return value, because `climb`'s
return shape is what every evaluation harness and the live panel
unpack, and widening it to a tuple would touch all of them for a field
almost always None. The panel reads this to name the unite it is
advising; nothing else should depend on it.
"""

# On. Swept: see docs/scoring.md. A unite now needs `unites_held > 0`,
# which the live readers never set, so this changes nothing on screen
# until something tells the overlay what the player is carrying -- and
# offline it reserves itself for hard content on its own. Measured at
# survive=400 with 5 held and a full card book, 120 runs a cell:
# difficulty 3 spends 0.00 unites and 0.00 cards at a 100% clear, d5
# spends 0.15, d7 2.54, d9 4.88 at 42%, the VP 3.48 at 93%. The owner's
# rule -- standard play should not need consumables -- falls out of the
# prices rather than needing a rule about buildings.
OFFER_UNITES = True

# An SOS card cannot be PROPOSED, only played. The whole `climb` menu is
# indices into `env.ACTIONS`, and no SOS has an index -- adding one would
# change `n_actions` and invalidate every trained policy. So the policy
# is silent about them and the probe below supplies them directly, the
# way `_cheapest_kills` supplies a move the logits rank nowhere.
#
# Unites escaped this by being free: they are a wrapper around the whole
# climb, applied before it. An SOS COSTS THE TURN, so it has to compete
# inside the plan against the gag it displaces, and the only thing that
# can weigh that is `judge`.
#
# Off until measured. `party_search` prices a call at `SOS_PRICE`, which
# is deliberately steep enough that one wins only where it dominates.
OFFER_SOS = True
"""Whether `climb` may open a round by using a unite.

A ROUND IS TWO DECISIONS when a unite is available -- use one, then
throw -- because a unite costs no action and applies immediately in the
planning phase. [OWNER, from play; see solver/unites.py.]

Modelled as a state TRANSFORMATION wrapped around the ordinary choice,
never as an entry in the action table. The table has 246 actions and
there are up to thirteen unite options; multiplying them is unusable,
while wrapping costs one extra evaluation per candidate and only when
one is off cooldown and not obviously wasted.

Each candidate is scored on the transformed state and charged
`unites.UNITE_PRICE`, which is ten times a pink slip. That price is a
PREFERENCE, not a tunable -- see the note on it -- so this flag is
about whether the option exists at all, not about how eagerly it is
taken.

OFF by default until measured. The question it exists to answer: a solo
VP at 16 and 20 cogs a round reads 0.0% for every policy, weight and
observation version tried, while the owner beats that fight. Unites are
the difference nobody has modelled.
"""

PROBE_CHEAPEST_KILL = True

# The same idea for LURE, which `_cheapest_kills` deliberately skips
# because a lure deals no damage and "kills it" does not apply.
#
# `_track_key` is (track, group), so the menu carries the policy's
# favourite single lure and its favourite group lure -- and the LEVEL
# inside each is the policy's alone, with nothing comparing one level
# against another. Reported from live play and reproduced: a lone
# trapped level 5 Ambulance Chaser with a Trapdoor in front, where the
# panel advised a GROUP Small Magnet. The scorer ranks $1 Bill 1785.26
# against Small Magnet's 1784.12 and would have chosen it -- it was
# never offered, because the policy's favourite single lure was $10
# Bill at 1779.07.
#
# What a lure's level buys is duration and accuracy, and against a
# trapped cog the duration is often worth nothing, since the trap
# resolves at once. That is a judgement the scorer can make and the
# policy cannot, so the cheapest of each scope is put in front of it.
PROBE_CHEAPEST_LURE = True

# WHERE the targeted probes sit, which matters more than whether they
# exist -- and the answer is NOT "early", which was measured and lost.
#
# At the panel's budget of 8 the probes queued behind the track sweep
# are never reached, so moving them ahead of it looked like a fix. It
# reverses which sweep gets starved, and the track sweep is worth far
# more: 200 runs a cell, everything available, difficulty 9 fell 60% to
# 42% and the VP 94% to 81%, with rounds nearly doubling on easy content
# (d3 3.7 -> 6.4) as cheap gags dragged fights out.
#
# So the ordering stands and `PROBE_CHEAPEST_KILL` really is mostly
# unreached live. That is a budget problem, not an ordering one, and it
# is left recorded rather than papered over.
TARGETED_PROBES_FIRST = False

# The one narrow exception, and it is narrow on purpose: a LURE aimed at
# a TRAPPED cog. There the lure's level buys nothing -- the trap
# resolves at once, so duration is worthless -- and every lure lands at
# the same 95% cap anyway, which makes the cheapest strictly correct.
# At most two entries, only on boards holding a trapped cog, so it costs
# the track sweep almost nothing.
#
# Reported from live play: a lone trapped level 5 Ambulance Chaser with
# a Trapdoor, advised a GROUP Small Magnet.
PROBE_LURE_ON_TRAP = True
"""Offer the SMALLEST gag that kills each cog, alongside the policy's.

The scorer already prefers the cheap kill and never gets the chance to
say so. On a lone level 1 Cold Caller with 6 hp it rates a Cupcake at
129.5 and a Storm Cloud at 118.5 -- it knows -- but `climb` only ever
judges what the policy proposes, and the policy's top three were all
big gags. That is the same shape as the pink slip collapse: a menu with
no cheap option on it, and a judge blamed for a proposal it never saw.

`_track_key` probing does not cover this. It offers the best of each
TRACK by the policy's own ranking, which on a 6 hp cog is the biggest
Throw and the biggest Squirt, not the smallest one that finishes the
job. The distinction the menu is missing is not track, it is size.

One entry per live cog, so the cost is bounded by the board rather than
the pouch, and only when something in the pouch actually kills it
outright.

MEASURED, paired on identical seeds, 250 runs a cell then 300 held out:

    cell             off     on    held out      paired (held out)
    vp + 5 slips   81.2%  82.0%   84.3 -> 84.7   +1/-0    p=1.00
    vp + 0 slips   48.8%  54.4%   46.7 -> 53.7   +24/-3   p=0.0002
    buildings      16.0%  21.6%   17.3 -> 24.3   +30/-9   p=0.0008

Seven points on both no-slip cells, and it replicates. Note it does NOT
save gags -- 11.2 against 11.4 a run, 17.4 against 17.8 -- so this is
not conservation. It wins more rounds outright, because spending the
smallest thing that kills leaves the bigger gag for the cog that needs
it, and the run lasts long enough to throw more of them.

It pays most where there is no slip to fall back on, which is the
opposite of where it was found: the board that prompted it had five
slips and the fix that mattered there was `FIRE_PRICE`'s floor.
"""


def _sos_probes(state, seat: int):
    """The SOS cards this toon holds, as actions to try.

    One per distinct card rather than per copy -- calling the same card
    twice in a round is the same move, and the count only decides
    whether it is available at all.

    Deliberately unranked. There is no policy signal to sort these by,
    so they go to `judge` in table order and the score decides; with
    `SOS_PRICE` charged per call, a card that is not clearly better than
    the gag it displaces loses on its own.
    """
    held = getattr(state.toons[seat], "sos_cards", None)
    if not held:
        return []
    return [Action(track=None, sos=name)
            for name, count in held.items()
            if count > 0 and name in sos_mod.BY_NAME]


def _cheapest_lures(state, seat: int, legal=None):
    """Indices of the LOWEST-level lure this toon holds, per scope.

    One single-target and one group, so the scorer can weigh a cheap
    inaccurate lure against the expensive accurate one the policy
    prefers. It decides; this only makes sure it is asked.

    Skipped when every live cog is already lured -- there is nothing to
    put to sleep, and `legal_actions` has its own view on that.
    """

    live = [c for c in state.cogs if not c.status.is_dead]
    if not live or all(c.status.lured for c in live):
        return []
    best = {}
    for index, entry in enumerate(env_mod.ACTIONS):
        if entry is None or entry.fire or entry.track is not Track.LURE:
            continue
        if legal is not None and not legal[index]:
            continue
        scope = entry.target_index is None
        current = best.get(scope)
        if current is None or entry.level < current[0]:
            best[scope] = (entry.level, index)
    return [index for _level, index in best.values()]


def _cheapest_kills(state, seat: int, legal=None):
    """Indices of the smallest single-target gag that kills each cog.

    Cheapest by DAMAGE, not by level: a level 4 Throw can out-damage a
    level 5 Squirt, and what is being avoided is spilled damage rather
    than spent training. Ties break to the lower level, which is the
    cheaper gag to replace.

    Lure, Trap and Toon-Up are skipped -- they do not damage, so "kills
    it" does not apply -- and so is a lured target, where knockback
    changes the arithmetic this is deliberately not trying to model.
    """

    if not PROBE_CHEAPEST_KILL or seat >= len(state.toons):
        return []
    if legal is None:
        legal = env_mod.legal_mask(state, seat)
    toon = state.toons[seat]
    out = []
    for index, cog in enumerate(state.cogs):
        if cog.status.is_dead or cog.status.lured:
            continue
        best = None
        for action_index, entry in enumerate(env_mod.ACTIONS):
            if (entry is None or entry.fire or entry.target_index != index
                    or entry.track in (Track.LURE, Track.TRAP,
                                       Track.TOON_UP)):
                continue
            # LEGALITY, and leaving it out made this whole probe a
            # no-op. The cheapest killer of a 6hp cog is a single-target
            # SOUND, and Sound is group-only -- so the one candidate
            # offered was always illegal, the caller's isfinite check
            # dropped it, and the menu was never widened at all. Checked
            # here so the search falls through to the next cheapest
            # LEGAL gag instead of offering nothing.
            if action_index < len(legal) and not legal[action_index]:
                continue
            if toon.gag_counts.get((entry.track, entry.level), 0) <= 0:
                continue
            try:
                dmg = mechanics.calc_toon_damage(
                    entry.track, entry.level,
                    organic=toon.is_organic(entry.track))
            except Exception:           # noqa: BLE001 - unpriced gag
                continue
            if dmg < cog.hp:
                continue
            if best is None or (dmg, entry.level) < best[0]:
                best = ((dmg, entry.level), action_index)
        if best is not None:
            out.append(best[1])
    return out


def _wastes_a_drop(state, plan) -> bool:
    """Does this plan throw a Drop at cogs that will all be asleep?

    Drop resolves last and always misses a lured cog, so a Drop whose
    every target is asleep cannot land at all -- there is not even a
    hedge, because the cogs were already lured before the round or are
    lured by this plan. On a real CEO board `lure/5 + GrandPiano->c0`
    scored -29.8 against -11.4 for the same Lure alone: the scorer
    already ranks it worse and plays it anyway, because `legal_actions`
    offers a pass only in narrow circumstances and the seat must throw
    something.

    A WOKEN COG IS DIFFERENT, and this is the whole subtlety. Gags
    resolve Toon-Up, Trap, Lure, Sound, Throw, Squirt, Drop, and a
    landed attack ends the lure (`mechanics.LURE_ENDS_ON_DAMAGE`). So a
    Sound, Throw or Squirt aimed at a sleeping cog wakes it before the
    Drop arrives, and Drop-behind-Lure is then a real play rather than a
    wasted Piano. Only Drops with no such partner are rejected.
    """

    live = {i for i, c in enumerate(state.cogs) if not c.status.is_dead}
    if not live:
        return False

    asleep = {i for i in live if state.cogs[i].status.lured}
    woken = set()
    for a in plan or ():
        if a is None or a.is_pass or getattr(a, "fire", False):
            continue
        targets = ((live if a.target_index is None else {a.target_index})
                   & live)
        if a.track is Track.LURE:
            asleep |= targets
        elif a.track in (Track.SOUND, Track.THROW, Track.SQUIRT):
            # Resolves before Drop and ends the lure on landing.
            woken |= targets

    for a in plan or ():
        if a is None or a.is_pass or getattr(a, "fire", False):
            continue
        if a.track is not Track.DROP:
            continue
        targets = ((live if a.target_index is None else {a.target_index})
                   & live)
        if targets and targets <= (asleep - woken):
            return True
    return False


def reject_key(entry) -> object:
    """What "no, not that" rejects, for the panel's Reconsider control.

    `_track_key` already collapses EVERY fire into one key, because a
    fire has no track and no level, so rejecting one rejects all of
    them. That is the behaviour wanted rather than a side effect: a
    player who dismisses "pink slip on cog 2" means "do not spend a
    slip", not "spend it on cog 3", and offering the same move against
    a different target four times over is the obvious way to make a
    Reconsider button useless.

    The same reasoning gives "no, not Drop" in one click.

    The pass has no entry in `ACTIONS` -- it is a None -- so it gets its
    own constant rather than being unrejectable.
    """
    if entry is None:
        return "pass"
    return _track_key(entry)


def gag_reject_key(entry) -> object:
    """Just this gag: "not the Grand Piano", Safe still on offer.

    Narrower than `reject_key`, which turns down a whole kind of move.
    Both exist because the player means different things by them and
    only they know which: dismissing a Piano because it is overkill on a
    56 hp cog is not the same as dismissing Drop because the cog is
    lured.
    """
    return ("gag", entry.track, entry.level)


def track_reject_key(entry) -> object:
    """The whole track: "no Drop at all, at any level"."""
    return ("track", entry.track)


def reject_keys(entry) -> tuple:
    """Every key `entry` answers to, for the mask to test against.

    The mask checks membership of ANY of these rather than of one, so
    the three granularities can be mixed in a single rejection set and a
    caller that only ever stores `reject_key` values keeps working
    unchanged -- which `realms_panel` does.
    """
    if entry is None:
        return ("pass",)
    return (reject_key(entry), gag_reject_key(entry), track_reject_key(entry))


def _track_key(entry):
    """What counts as a distinct kind of move for probing purposes.

    TRACK ALONE IS NOT ENOUGH, and this was measured. Probing one action
    per track offers the policy's favourite within that track, and on a
    CEO board that was `Birthday Cake -> c2` for Throw and `TNT -> c2`
    for Trap -- scoring 342 apiece, while `Wedding Cake -> all` scored
    1103 and `Railroad -> all` 1159 and neither was ever offered. A group
    gag hits four cogs and a single-target one hits one; they are not
    two orderings of the same move, and collapsing them hides whichever
    the policy happens to rank lower.

    So the key is (track, group). At most fourteen entries instead of
    seven, and in practice far fewer, because a toon holding no group
    gag in a track contributes one entry for it as before.
    """

    if not GROUP_GAGS_PROBED_SEPARATELY:
        return entry.track

    try:
        group = bool(data.gag(entry.track, entry.level).group)
    except (KeyError, ValueError, NotImplementedError):
        group = entry.target_index is None
    return (entry.track, group)


PROBE_WHEN_DEGENERATE = True
"""Probe the tracks when the whole top-k is ONE kind of move.

`probe_tracks` is decided per CALL and defaults to party-only, because
in solo the extra reach mostly gives an approximate scorer more room to
act on its errors. This is decided per SEAT and asks a narrower
question: did the policy just hand the judge a menu with no choice on
it?

When every entry in the top-k shares a `_track_key`, the judge is
choosing between orderings of one move and cannot see an alternative,
however badly the one on offer scores.

TEN PINK SLIPS DO EXACTLY THAT. A fire keys as (None, False), so all
of them collapse to one entry and the top-3 is three fires. The policy
then fires every round, and since a slip costs no gag but does cost a
ROUND -- about fifteen laff with the cogs awake -- it met the back half
of the VP with no laff left. Solo VP at 8 cogs a round went from 49.5%
with an empty slip pocket to 0.0% with ten in it.

Solo VP, 8 cogs a round, 300 runs a cell on selection seeds and 500 on
held out:

    slips   probes off   probes always   degenerate-only
       10       56.3%          66.0%         66.7% / 68.6%
        0       47.0%          37.3%         47.3% / 47.4%

Neither FIXED setting wins both rows. Probing always costs ten points
with an empty pocket (p=0.006, reproducing the +9.2% for probes-off
already recorded on `climb`); probing never costs ten with slips in it.
The rows disagree because the menu only collapses in one of them, which
is the thing this flag tests for. Held out it is +138/-65 (p<0.0001)
with slips and +2/-1 without -- all of the gain, none of the cost.

WHY THE NET RANKS FIRES THERE AT ALL, since a probe works around
that rather than fixing it. On a live VP board -- L12 196hp, L11 156hp,
L8 90hp, L3 20hp, all awake, 49.9 laff of incoming, ten slips -- the
four fires take ranks 1 to 4 at logits 20.4 to 21.1 with the best gag
at 14.8. A gap of 6.2 logits is about 500x in probability, so a 3-wide
menu can contain nothing else. With the slips removed the same net
ranks Geyser, Wedding Cake, Toontanic, Hypno-goggles -- sensibly.

It is not evaluating the board, and two readings show it rather than
suggest it. The spread across the four targets is 0.647 logits, and
the ORDER is wrong: the 20 hp Cold Caller outranks both Hollywoods, so
whatever it has learned, it is not "remove the biggest threat". And
lure the whole board -- incoming 49.9 -> 0.0, which is precisely when
a slip is free -- and every fire logit falls by 5.6 to 6.6. It rates
firing WORST exactly where firing is cheapest, which is backwards.

So the prior is close to a reflex on holding slips, and uninformed by
the rest of the position. That is what `--fire-fraction 0.15` predicts:
a slip-carrying board is a thin slice of training, and a slip-carrying
board that is ALSO lured is thinner still. The probe forces a
comparison the net never learned to make; only a retrain that shows it
those positions can fix the ranking itself.

WHERE IT CANNOT REGRESS, and it is worth knowing why rather than
measuring it: the condition is `probe_tracks or _menu_is_degenerate`,
which short-circuits, so on any position where probes are already on --
every party position, since `probe_tracks` defaults to party-only -- the
new code is not even called and behaviour is bit-identical. Only solo
can change. Solo buildings at difficulty 8 with no slips read 17.3%
against 16.7%, +9/-7, p=0.80: neutral, on the surface where the
Drop-argmax collapse lived and where a degenerate menu was therefore
most plausible without slips in the pouch.

WHAT THIS REPLACES, and why it is better than what it replaces. The
first fix was a hand-written rule that withheld slips unless every live
cog was lured, on the reasoning that a lured board does not swing so
the round is free. It worked -- 54.0% held out against 47.4% for
withholding them entirely -- and it was still wrong, in two ways this
one is not.

It was a rule about pink slips, so it could only ever fix pink slips;
the Drop-argmax collapse is the same failure and it would have missed
it. And it was aimed at the ranking when the fault was in the REACH:
with the alternatives on the menu the policy fires MORE, not less --
5.2 slips a run against 3.0 -- and wins ten points more often. The
lure rule was suppressing a good move to prevent a bad one, because
nothing had put the two side by side. Turning it back on on top of
degenerate probing measured 57.3% against 66.0%: it costs nine points
once the judge can see.

The order the project keeps -- model, then weights, then reach -- says
to suspect the proposal before the ranking. This is the reach, and it
is the third time on this function that a menu the judge never saw was
mistaken for a judgement it got wrong.
"""


def _menu_is_degenerate(order, values) -> bool:
    """Is every candidate in the top-k the same kind of move?"""
    import numpy as np


    if not PROBE_WHEN_DEGENERATE:
        return False
    keys = set()
    for index in order:
        index = int(index)
        if not np.isfinite(values[index]):
            continue
        entry = env_mod.ACTIONS[index]
        if entry is None:
            continue                  # the pass; ACTIONS has gaps
        keys.add(_track_key(entry))
        if len(keys) > 1:
            return False
    return len(keys) == 1


def climb(state: BattleState, rng=random,
          # RAISED WITH `width`, and it has to be. `budget` counts judge
          # calls and the scoring loop breaks on `spent >= budget`, so a
          # default budget of 16 against a default width of 16 starves
          # the probes appended after the policy's own entries. Measured
          # on the trapped ambulance chaser: budget 12 picks Storm
          # Cloud, 16 picks Small Magnet, 20 and 24 pick the $1 Bill
          # that springs the trap. The shipped panels already pass 24;
          # this stops a caller relying on the default from silently
          # getting the truncated answer.
          budget: int = 24,
          # WIDTH IS WHY THE TWO ENGINES DISAGREE, and 16 is worth it.
          # [OWNER] reported the policy spending a dearer gag than the
          # exact search wanted on the same board. Spying on every plan
          # `_judge` is asked to score says why:
          #
          #   width   search's pick offered   RL agrees with it
          #       3            0 of 4                0 of 4
          #       8            2 of 4                2 of 4
          #      16            4 of 4                3 of 4
          #
          # At 3 the scorer NEVER SEES the move, so no weight on `price`
          # or `waste` could reach it -- those sweeps were measuring a
          # menu, not a scorer.
          #
          # A FIRST PASS AT 10 RUNS A CELL SAID IT BOUGHT NOTHING AND
          # THAT WAS TOO SMALL A SAMPLE. Solo VP, 20 a round, everything
          # carried, paired on identical seeds:
          #
          #   runs   seeds        width 3   width 16   paired
          #     25   selection        60%        76%   +6/-2
          #     40   HELD OUT         48%        75%   +15/-4, p=0.019
          #
          # BUILDINGS ARE UNTOUCHED, and that was re-run properly: the
          # first check reported one floor a run, which barely exercises
          # the pouch. On real multi-floor buildings, 2.6-toon parties,
          # 40 paired runs: 82% finished at both widths, +0/-0.
          #
          # The split is the point. Width pays where the POUCH binds --
          # a solo VP is 40 cogs over two long floors, and my own
          # arithmetic puts 4255 cog HP against a pouch worth ~2730
          # single-target. A two-floor building shared by three toons
          # never gets near that, so a better menu has nothing to buy.
          #
          # Cost is 20ms -> 26ms a decision.
          #
          # WIDTH AND BUDGET ARE COUPLED, and this is the thing to know
          # before changing either. `budget` counts JUDGE CALLS and the
          # scoring loop breaks on `spent >= budget`, so a menu wider
          # than the budget never reaches the probes appended after the
          # policy's own entries -- `_cheapest_kills`, `_cheapest_lures`
          # and the SOS list, which exist precisely because the policy
          # ranks them nowhere.
          #
          # On the trapped ambulance chaser the owner reported:
          #
          #   width 16, budget  8 -> Foghorn, wasting the armed trap
          #   width 16, budget 24 -> $1 Bill, springing it   (the panel)
          #   width 32, budget 24 -> Small Magnet, starved again
          #   width 32, budget 48 -> $1 Bill
          #
          # So width 32 measuring worse than 3 on the VP (+3/-7) was
          # BUDGET STARVATION, not the approximate-scorer effect the
          # module docstring records for budget. 16 fits inside the
          # panel's 24; anything wider needs the budget raised with it.
          width: int = 16, probe_tracks: Optional[bool] = None,
          deep: bool = False, rollout: int = 0,
          fixed: Optional[Mapping[int, Optional[Action]]] = None,
          pairs: bool = True, pair_width: int = 7, reject=None,
          allow_unites: bool = True
          ) -> Optional[Sequence[Optional[Action]]]:
    """Coordinate ascent on the joint plan, instead of independent draws.

    `best_plan` re-rolls every seat on every sample, which spends its
    budget re-deciding the seats that were already right. A joint plan
    is one action per toon, so the natural move is to fix the others and
    vary one seat at a time -- the same structure the search exploits
    when it enumerates per toon.

    Starts from the policy's argmax plan, then sweeps the seats,
    offering each the policy's top `width` alternatives and keeping any
    that `_quick_score` prefers. Repeats until a full sweep changes
    nothing or the budget of scorer calls runs out.

    Budget is counted in `_quick_score` calls so this can be compared
    with `best_plan` at equal cost, which is the only fair comparison
    between two search strategies.

    `pairs` lets two seats change TOGETHER once the single-seat sweeps
    settle, which is the one move coordinate ascent structurally cannot
    make. Measured on a real no-level-7 board:

        366.4   both toons lure/6 -- where the sweep stops
        177.8   change either ONE to sound/6
        672.1   change BOTH to sound/6

    Sound resolves after Lure and wakes what Lure put to sleep, so the
    mixed plan is far worse than either pure one. Every single-seat edit
    is downhill and the joint edit nearly doubles the score, so the
    sweep sits at 366 and stops. Over 43 sampled no-7 rounds the best
    plan needed BOTH seats to move 72% of the time, and the climb
    captured 68.4% of the reachable score.

    This is why widening what each seat is OFFERED never helped --
    `probe_tracks` and larger `width` were both refuted twice. They add
    candidates to a menu whose problem is that the two choices have to
    be made at the same time. Note the pair menu is built BY TRACK for
    the same reason: `sound/6->all` sits 22nd and 16th for the two seats
    on the board above, so no top-k reaches it. Each fix alone is
    blocked by the other wall, which is why both were refuted
    separately.

    OFF, having been measured on 240 held-out sides a set:

        set              shipped   +pairs
        buildings          68.3%    70.4%   (= budget control)
        VP                 98.8%    99.6%
        CEO 0              92.5%    90.4%
        CEO 5              44.2%    35.4%   p=0.020
        CEO 0, no lvl 7s   21.7%    27.5%   p=0.041

    It works exactly where predicted and loses where the agent is
    already good. Both significant, opposite directions.

    WHY, AND IT IS THE GENERAL LESSON. A joint move lets the search
    reach plans `_quick_score` rates highly, and `_quick_score` is an
    approximation -- so more reach means more scope to act on its own
    errors. On a no-level-7 board the policy has never trained on, its
    proposals are bad and the extra reach rescues them. Everywhere else
    the proposals are good and the reach mostly finds the scorer's
    mistakes.

    So the narrow window is not a limitation to be removed, it is a
    REGULARISER holding an imperfect scorer near a well-trained policy's
    suggestions. `probe_tracks`, wider `width` and this are the same
    move, and all three fail in-distribution for the same reason.

    The prerequisite for any of them is an evaluator worth widening --
    and `prevented` documents why that cannot be done one term at a
    time. Turn this on only for positions outside the policy's training
    distribution, where there is nothing good to stay near.

    `probe_tracks` offers each seat the best action of every track it
    holds, not just the policy's top `width`. It is ON IN A PARTY AND
    OFF SOLO, and the story of how it got there is the most useful thing
    in this file.

    THE SPLIT IS MEASURED. On v7_precision, 250 runs a cell, same seeds,
    OFF minus ON:

        building solo    +0.4%
        building party   -1.2%
        VP solo          +9.2%
        VP party         -1.2%
        CEO party       -17.6%

    Solo is the only place turning it off wins, and the CEO is where it
    earns its keep -- 20.0% with it against 2.4% without. Flipping it
    globally, which the solo VP number alone argued for, would have cost
    the CEO almost everything.

    The reason fits the regulariser argument below. In a party the joint
    plan space is far larger and a per-seat top-k is far more likely to
    miss the move that only works in combination -- `sound/6->all` sat
    22nd and 16th for two seats on the board in that note. Solo there is
    no combination to miss, so the extra reach only gives an approximate
    scorer more room to act on its errors.

    `None` means decide from the party size. Pass a bool to override.

    IT WAS REFUTED TWICE. The reason was always the same: more reach for
    an approximate scorer is more scope to act on its errors. On 180
    buildings it read 66.1% against 63.3% with probes, and on the CEO it
    lost 7.5 points.

    WHAT CHANGED IS THE SCORER, NOT THE PROBE. A landed attack now wakes
    a lured cog (`mechanics.LURE_ENDS_ON_DAMAGE`), `prevented` counts
    what a Lure actually buys instead of multiplying by a duration it
    never delivers, and `QUICK_W["prevent"]` moved 2 -> 9 for +45 points
    on the CEO. With the scorer worth widening, the same flag pays, on
    200 held-out sides a set:

        set          plain   +probes+pairs
        buildings    65.0%       73.5%      p=0.0002
        VP           99.0%       99.5%      ns
        CEO 0        54.0%       88.5%      p<0.0001
        CEO 2        18.5%       73.5%      p<0.0001
        CEO 4         7.0%       45.0%      p<0.0001

    WHY IT MATTERS SO MUCH: three tracks were structurally invisible.
    Trap sat at median rank 25 in the policy's ranking and entered the
    3-wide window 0 times in 521 seats; Toon-Up at rank 10, 1% of the
    time. The scorer wanted both -- `Railroad + group Lure` was the
    highest-scoring plan on the board where it was measured, and heal
    use goes 0% -> 15% once reachable. No weight could ever have fixed
    that, which is why the earlier heal sweep read flat at twenty times
    the weight.

    THE LESSON, WHICH GENERALISES: do not widen a search to compensate
    for a scorer you have not checked. Fix the model, then the weights,
    then the reach -- in that order. Reversed, each stage measures the
    previous stage's errors and refutes the right idea for the wrong
    reason.

    Budget is counted in `_quick_score` calls so this can be compared
    with `best_plan` at equal cost, which is the only fair comparison
    between two search strategies.

    GROUP AND SINGLE-TARGET ARE DIFFERENT MOVES, and probing by track
    alone hid one of them. The menu took the policy's favourite action
    per TRACK, so on a CEO board seat 1 was offered `Birthday Cake -> c2`
    for Throw and `TNT -> c2` for Trap -- 342 apiece by `_quick_score`,
    while `Wedding Cake -> all` scored 1103 and `Railroad -> all` 1159
    and neither was ever put in front of the judge. A gag that hits four
    cogs is not a reordering of one that hits one. `_track_key` now keys
    on (track, group); `GROUP_GAGS_PROBED_SEPARATELY` turns it off.

    It is ON, on this evidence, paired on identical positions:

        board            budget 24   budget 36
        facilities          -0.2        +1.3
        CEO 0               -1.7        +4.5
        CEO 2               +8.8         --
        CEO 4               +9.0         --

    Two effects pulling opposite ways, and they separate cleanly. The
    GAIN scales with cogs alive, because that is what a group gag is
    for -- CEO 4 pays at budget 24 where CEO 0 needs 36. The COST is
    fixed, about four extra menu entries a seat, spent whether they help
    or not. Starve the search and the cost is all you get: at budget 24
    the wider menu is 88 up / 98 down on CEO 0 (p=0.51), and at 36 it is
    100 up / 73 down (p=0.048). The trace that showed why is worth
    keeping -- on side 92008 the starved arm picked `Geyser -> all` over
    `Toontanic -> all`, left three cogs alive on 5 hp, and took 75 laff
    for it.

    Facilities are untouched at every budget: 46 discordant games in
    1800. Few cogs and often no group gag in the track, so the extra key
    usually adds no candidate at all. That is the difference from the
    three earlier refutations of "widen the menu" -- this one is neutral
    where it cannot help rather than costly everywhere.

    Boss analysis wants budget 36 or better. That is a PARTY result and
    it does not carry to solo -- measured now, where it used to say the
    panel's setting was unmeasured.

    Solo VP, 8 cogs a round, ten slips, shipped policy on every arm,
    paired on identical seeds:

        budget    150 sel.    300 held out
             3       0.0%
             4      11.3%
             6      71.3%           71.0%   +49/-41  p=0.46
             8      63.3%           68.3%   (the panel's setting)
            16      47.3%
            24      47.3%           55.3%   +26/-65  p=0.0001
            36      47.3%

    RAISING IT HURTS, by thirteen points held out. The reason is the one
    already written three times above: more reach for an approximate
    scorer is more scope to act on its errors. In a party the joint plan
    space is large enough that the extra reach finds moves worth having;
    solo there is no combination to miss.

    16, 24 and 36 are IDENTICAL on the selection set, which is the tell
    for what the budget does here. Solo has one seat, so once the
    single-seat menu is exhausted there is nothing left to spend on --
    the pair loop below needs two seats. Budget 8 stops partway through
    that menu, and stopping helps.

    Below 6 it collapses instead -- 11.3% at 4, 0.0% at 3 -- because the
    climb cannot afford even the first few candidates and returns close
    to the policy's raw argmax, which is what `PROBE_WHEN_DEGENERATE`
    exists to rescue.

    6 looked like a free +8 on the selection set and came back +2.7 and
    p=0.46 held out, so the panel's 8 stays. `advise.DEFAULT_BUDGET` is
    a different quantity -- seconds for the expectimax path -- and is
    still unmeasured.
    """
    if probe_tracks is None:
        # Party only. See the measurements above: solo is the one place
        # it costs, and the CEO is where it pays 20.0% against 2.4%.
        probe_tracks = len(state.active_toons()) > 1

    import numpy as np

    from . import party_search as ps

    if not available():
        return None
    model = _load()

    # One seed for every candidate this call compares, so the rollouts
    # are paired rather than a lottery.
    seed = rng.randrange(1 << 30)
    judge = ((lambda st, pl: rollout_judge(st, pl, seed, rollout))
             if rollout else (lambda st, pl: _judge(st, pl, deep)))

    fixed = dict(fixed or {})

    # UNITE FIRST, THEN THROW. Evaluated by transforming the state and
    # re-planning on it, so the gag is chosen against the laff and gags
    # the unite just restored -- which is what the game does in the
    # planning phase. The unite is charged for separately, so a plan
    # that uses one has to beat the plan that does not BY MORE than the
    # price, not merely beat it.
    if OFFER_UNITES and allow_unites and not fixed and state.toons:
    
        def _value_of(st):
            inner = climb(st, rng, budget=budget, width=width,
                          probe_tracks=probe_tracks, deep=deep,
                          rollout=rollout, pairs=pairs,
                          pair_width=pair_width, reject=reject,
                          allow_unites=False)
            if inner is None:
                return None, float("-inf")
            try:
                return inner, _judge(st, inner, deep)
            except (NotImplementedError, ValueError, KeyError):
                return inner, float("-inf")

        # `unites.best_with_unite` is the shared implementation, taking
        # the engine as a callable. The exact search needs the identical
        # comparison and had no way to reach this one, which is why TTR
        # -- which runs that search -- could not use a unite at all.
        best_choice, best_plan = unites_mod.best_with_unite(state, _value_of)

        global LAST_UNITE
        LAST_UNITE = best_choice
        if best_choice is not None:
            # In place, because the caller's state is what the round is
            # played from and the effect lands before the gag.
            unites_mod.apply(state.toons[0], best_choice)
        return best_plan

    plan = list(propose(state, rng, sample=False, fixed=fixed,
                        reject=reject))
    try:
        best_score = judge(state, plan)
    except (NotImplementedError, ValueError, KeyError):
        return plan
    spent = 1

    improved = True
    while improved and spent < budget:
        improved = False
        for seat, toon in enumerate(state.toons):
            if seat in fixed or toon.laff <= 0 or spent >= budget:
                continue
            pending = list(plan)
            pending[seat] = None
            values = _logits(model, state, seat, pending, reject)
            mask_for_seat = np.isfinite(values)
            order = list(np.argsort(values)[::-1][:width])
            # THE TARGETED PROBES GO IN BEFORE THE BROAD ONE, and the
            # order is load-bearing at the budget the panel actually
            # uses. `budget` is 8 live; the track probe appends up to
            # fourteen entries, so anything queued behind it is never
            # evaluated. Measured on the reported board -- a lone
            # trapped Ambulance Chaser -- the cheap-lure probe changed
            # nothing at budget 8 or 12 and only bit at 20. That made
            # `PROBE_CHEAPEST_KILL` largely dead in live play too, which
            # is not what its own measurement assumed.
            #
            # These are one or two entries each and are aimed at a
            # specific known blind spot, so they earn a place ahead of a
            # sweep of every track.
            def _add_targeted():
                for index in _cheapest_kills(state, seat, mask_for_seat):
                    if index not in order and np.isfinite(values[index]):
                        order.append(index)
                if PROBE_CHEAPEST_LURE:
                    for index in _cheapest_lures(state, seat, mask_for_seat):
                        if index not in order and np.isfinite(values[index]):
                            order.append(index)

            if TARGETED_PROBES_FIRST:
                _add_targeted()
            elif PROBE_LURE_ON_TRAP and PROBE_CHEAPEST_LURE and any(
                    c.status.trapped and not c.status.is_dead
                    for c in state.cogs):
                for index in _cheapest_lures(state, seat, mask_for_seat):
                    if index not in order and np.isfinite(values[index]):
                        order.append(index)
            if probe_tracks or _menu_is_degenerate(order, values):
                # The best of every track this toon can actually play,
                # in the policy's own within-track order.
                seen_tracks = set()
                for i in order:
                    entry = env_mod.ACTIONS[int(i)]
                    if entry is not None and np.isfinite(values[int(i)]):
                        seen_tracks.add(_track_key(entry))
                for index in np.argsort(values)[::-1]:
                    index = int(index)
                    if not np.isfinite(values[index]):
                        break
                    entry = env_mod.ACTIONS[index]
                    if entry is None:
                        continue          # ACTIONS has gaps
                    key = _track_key(entry)
                    if key in seen_tracks:
                        continue
                    seen_tracks.add(key)
                    order.append(index)
                # HOLDING IS A MOVE AND HAD NO SLOT. The probe menu is
                # built from `ACTIONS`, where the pass entry is None, so
                # the loop above skips it -- and the policy ranks it 31st
                # of 33 on a board where every cog is already lured, far
                # outside the 3-wide window. The seat was therefore
                # forced to throw something, which is how a Grand Piano
                # gets spent into a sleeping cog for a guaranteed miss.
                # Legality is not the constraint: `free_passes` was 3.
                if (ALWAYS_PROBE_PASS
                        and np.isfinite(values[env_mod.PASS_INDEX])
                        and env_mod.PASS_INDEX not in order):
                    order.append(env_mod.PASS_INDEX)
            if not TARGETED_PROBES_FIRST:
                _add_targeted()
            queue = [(env_mod.action_at(int(index)), True) for index in order
                     if np.isfinite(values[index])]
            if OFFER_SOS:
                # Appended, not merged: these have no index and no
                # logit, so they cannot be ordered against the rest.
                #
                # AND NOT CHARGED TO THE BUDGET. They used to be, and
                # sat at the very end of the queue, so on any board big
                # enough to fill the sweep they were never reached: the
                # loop broke on `spent >= budget` first. A four-cog VP
                # board with seven cards held is past the default 24
                # before the first card, which is why the panel "never
                # suggests SOS" -- the judge ranked a card FIRST and
                # `climb` never asked it. Measured on a recorded run:
                # at budget 24 the plan is Presentation, at 40 it is the
                # card the judge preferred all along.
                #
                # Not fixed by moving them earlier: `TARGETED_PROBES_FIRST`
                # records that reversing which sweep gets starved cost
                # difficulty 9 sixty percent to forty-two. So the sweep
                # keeps its place and its budget, and the cards -- of
                # which there are at most a handful, one per distinct
                # card held -- are simply always judged.
                queue += [(action, False)
                          for action in _sos_probes(state, seat)]
            for action, charge in queue:
                if charge and spent >= budget:
                    continue          # sweep truncated; cards still judged
                trial = list(plan)
                trial[seat] = None if action.is_pass else action
                if trial == plan:
                    continue
                if NO_DROP_INTO_OWN_LURE and _wastes_a_drop(state, trial):
                    continue
                try:
                    score = judge(state, trial)
                except (NotImplementedError, ValueError, KeyError):
                    continue
                if charge:
                    spent += 1
                if score > best_score:
                    plan, best_score, improved = trial, score, True

        # A joint move, once no single seat can improve alone. Narrower
        # than the single-seat menu on purpose: this is width^2 per
        # pair, and it is a tie-break on an already-settled plan rather
        # than the main search.
        if pairs and not improved and spent < budget:
            seats = [i for i, t in enumerate(state.toons)
                     if i not in fixed and t.laff > 0]
            # BY TRACK, not by logit rank. The move a joint step needs
            # is often one the policy ranks nowhere: on the board in the
            # docstring, `sound/6->all` sits 22nd and 16th for the two
            # seats, so no top-k menu reaches it at any k worth paying
            # for. Taking each seat's best action per track guarantees
            # every track it HOLDS is represented in at most seven
            # entries.
            #
            # This is `probe_tracks`' menu, and pairing is what makes it
            # useful. On its own it offers Sound to ONE seat while the
            # other keeps luring, which is the mixed plan at 177.8 --
            # correctly rejected. Each fix alone is blocked by the other
            # wall, which is why both were refuted separately.
            menu = {}
            for seat in seats:
                pending = list(plan)
                pending[seat] = None
                values = _logits(model, state, seat, pending, reject)
                best_of_track, seen_tracks = [], set()
                for index in np.argsort(values)[::-1]:
                    index = int(index)
                    if not np.isfinite(values[index]):
                        break
                    entry = env_mod.ACTIONS[index]
                    if entry is None:
                        continue          # ACTIONS has gaps
                    key = _track_key(entry)
                    if key in seen_tracks:
                        continue
                    seen_tracks.add(key)
                    best_of_track.append(index)
                    if len(best_of_track) >= pair_width:
                        break
                menu[seat] = best_of_track
            for first, second in itertools.combinations(seats, 2):
                for i in menu[first]:
                    for j in menu[second]:
                        if spent >= budget:
                            break
                        trial = list(plan)
                        trial[first] = env_mod.action_at(i)
                        trial[second] = env_mod.action_at(j)
                        trial = [None if a is not None and a.is_pass else a
                                 for a in trial]
                        if trial == plan:
                            continue
                        if NO_DROP_INTO_OWN_LURE and _wastes_a_drop(state,
                                                                    trial):
                            continue
                        try:
                            score = judge(state, trial)
                        except (NotImplementedError, ValueError, KeyError):
                            continue
                        spent += 1
                        if score > best_score:
                            plan, best_score, improved = trial, score, True
    return plan


def best_plan(state: BattleState, rng=random, samples: int = 16
              ) -> Optional[Sequence[Optional[Action]]]:
    """Sample `samples` plans from the policy; keep the best.

    The first is the policy's argmax, so this can never be worse than
    plain greedy play except through the scorer's own error.
    """
    from . import party_search as ps

    if not available():
        return None
    seen, best, best_score = set(), None, -math.inf
    for i in range(max(1, samples)):
        plan = propose(state, rng, sample=(i > 0))
        key = tuple((a.track, a.level, a.target_index) if a is not None
                    else None for a in plan)
        if key in seen:
            continue
        seen.add(key)
        try:
            score = ps._quick_score(state, plan)
        except (NotImplementedError, ValueError, KeyError):
            continue
        if score > best_score:
            best, best_score = plan, score
    return best
