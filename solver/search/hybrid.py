"""PPO proposes, the search's scorer judges.

The policy costs a third of a millisecond a decision and the party
search costs a hundred, so there's room to check the policy's own
suggestions. This samples a few joint plans from the trained policy and
keeps whichever one `_quick_score` likes best.

Measured over 180 HELD-OUT buildings (seeds never tuned against -- the
tuned set flattered this badly):

    agent                floors  finished   plans/second
    plain PPO              2.44     61.7%           2266
    climb, budget 8        2.49     66.1%            656
    full search            2.48     67.8%              1

`climb` recovers about two thirds of the distance from policy to search
for roughly double the policy's cost, and is deterministic (walks the
policy's ranked logits rather than sampling). The search is still ahead
by 1.7 points -- on the tuned seeds this looked like a win (69.4% vs
65.0%) but that reverses on fresh buildings; always re-run a tuned
result elsewhere. Budget 16 ties budget 8 here despite beating it on the
tuned set: `_quick_score` is an approximation, so climbing it harder
optimises the proxy, not the game -- the scorer, not the search
strategy, is the ceiling.

WHERE THE REMAINING GAP IS
--------------------------
Usage over 80 held-out buildings, climb at budget 8 vs. the search:
climb holds 2.1% of decisions against the search's 11.0%, throws 13%
more gags (2159 vs 1918), and skews to level 4 (38.1% vs 27.9%) where
the search prefers 5-6. The common cause: `_quick_score` pays for damage
landed, so an action dealing none scores near zero whatever it saves --
on seed 31003 the search heals 3 times and holds the party at 48-55
laff, while climb heals twice and loses the building.

The obvious fix doesn't work: forcing hold-variants into the SEARCH's
shortlist made play worse (2.07 floors to 1.83) because they're ranked
by `_quick_score` too. The search's own 11% comes from sampled
rollouts, which can see a conserved gag spent later -- holding *as this
scorer judges it* is genuinely bad.

WHY IT WORKS
------------
PPO is a better PROPOSAL DISTRIBUTION than the search's enumeration.
`party_search.plans` builds joint plans combinatorially and truncates,
which is where a long line of bugs have lived (a stratified cut that
dropped every Sound plan, a shortlist that dropped Trap in 39 of 39
positions, a lexicographic prefix that dropped the best line outright).
The policy suggests a handful of plausible plans directly and the
scorer only ranks those.

THE JUDGE MUST NOT BE THE PROPOSER. Ranking the same samples with PPO's
own critic achieves nothing (57.8% at four plans, 58.3% at twelve, vs.
58.9% for plain argmax) -- it asks the network to catch its own
mistakes, and a network that could wouldn't be making them
(`docs/ml-design.md` records the same failure for a learned-leaf
evaluator). `_quick_score` is an independent opinion, which is the
point of it.

Needs numpy, and says so by returning False from `available()` rather
than raising -- the same contract `search/policy.py` follows. Torch
never appears here; what ships is the plain-float export.
"""
from __future__ import annotations

import functools
import itertools
import json
import math
import random
import threading
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from .. import data
from .. import mechanics
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
    # CACHED FOR ONE CLIMB, like `_judge`: a climb asks for the same
    # board and seat about three times, and the legal-move list behind
    # the mask was 10% of its time. Keyed on the board object, holding
    # it so the id cannot be reused; copied out, because the reject
    # masking below writes into the array.
    memo = getattr(_MEMO, "judged", None)
    key = ("logits", id(state), seat, tuple(map(repr, pending)),
           model.get("obs_version", 1), id(model))
    hit = memo.get(key) if memo is not None else None
    if hit is not None and hit[0] is state:
        out = hit[1].copy()
    else:
        x = np.array(env_mod.encode(state, seat, pending,
                                    obs_version=model.get("obs_version", 1)),
                     dtype=float)
        for weight, bias in model["trunk"]:
            x = np.tanh(x @ weight + bias)
        out = x @ model["aw"] + model["ab"]
        mask = env_mod.legal_mask(state, seat)
        out = np.where(np.array(mask), out, -np.inf)
        if memo is not None:
            memo[key] = (state, out.copy())
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


# REPEATED SCORES, CACHED FOR ONE CLIMB. Measured over 221 solo-VP climbs:
# 33.5 judge calls per climb but only 20.1 distinct (board, plan) pairs --
# the start plan is re-scored, sweeps revisit a seat's incumbent, and
# `best_with_unite` re-judges each inner climb's answer. Scoring is
# deterministic (it enumerates the dice, it does not sample), so a repeat
# is pure waste.
#
# Keyed on the board OBJECT, not its contents, and the entry holds the
# board: an id is only unique while its object lives, and holding it is
# what stops a freed Unite probe's id being reused by the next one.
# Thread-local, because the panels run searches on worker threads.
_MEMO = threading.local()


def _memoised(fn):
    """Give `fn` -- `climb` -- one judge cache per top-level call."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        if getattr(_MEMO, "judged", None) is not None:
            return fn(*args, **kwargs)            # a nested climb shares it
        _MEMO.judged = {}
        try:
            return fn(*args, **kwargs)
        finally:
            _MEMO.judged = None
    return run


def _judge(state: BattleState, plan, deep: bool) -> float:
    memo = getattr(_MEMO, "judged", None)
    if memo is None:
        return _judge_uncached(state, plan, deep)
    key = (id(state), bool(deep), tuple(map(repr, plan)))
    hit = memo.get(key)
    if hit is not None and hit[0] is state:
        return hit[1]
    value = _judge_uncached(state, plan, deep)
    memo[key] = (state, value)
    return value


def _judge_uncached(state: BattleState, plan, deep: bool) -> float:
    """Rank a plan. One round, or two.

    `_quick_score` scores a single round, so a trap scores near zero and
    climbing it harder stops paying -- it can't see next round. It takes
    the expectation over accuracy rolls, not the all-hit score this used
    to compute (that preferred the biggest printed number, reliably the
    least likely to land, and fixing it moved the CEO 69.5% -> 75.0%).

    `deep` plays the plan, lets `greedy_plan` answer for the round after,
    and counts that at LOOKAHEAD_DISCOUNT -- the cheapest imitation of
    `party_search`'s multi-round `rollout_value`.

    OFF, measured: over 180 held-out buildings, 1-ply/budget 8 finishes
    66.7% in 0.61ms vs. 2-ply/budget 8's 63.9% in 1.82ms -- nearly three
    points worse at three times the cost, because the lookahead's second
    round is itself only `greedy_plan`'s myopic guess. Third judge
    improvement to fail (after trap credit +0.6 noise and track probes
    -2.8); plain one-ply `_quick_score` at budget 8 beats all of them.
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
"""Whether `climb` may open a round by using a unite.

A ROUND IS TWO DECISIONS when a unite is available -- use one, then
throw -- since a unite costs no action and applies immediately in
planning. [OWNER, from play; see solver/unites.py.]

Modelled as a state TRANSFORMATION wrapped around the ordinary choice,
not an action-table entry: 246 actions times up to thirteen unite
options is unusable, while wrapping costs one extra evaluation per
candidate, only when one is off cooldown and not obviously wasted.

Each candidate is scored on the transformed state and charged
`unites.UNITE_PRICE` (ten times a pink slip) -- a PREFERENCE, not a
tunable, so this flag is about whether the option exists, not how
eagerly it's taken.

Was off until measured: a solo VP at 16-20 cogs/round read 0.0% for
every policy, weight and observation version tried, though the owner
beats that fight. Unites were the unmodelled difference.
"""

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

PROBE_CHEAPEST_KILL = True
"""Offer the SMALLEST gag that kills each cog, alongside the policy's.

The scorer already prefers the cheap kill but never gets the chance to
say so: on a lone level-1 Cold Caller (6hp) it rates a Cupcake at 129.5
over a Storm Cloud's 118.5, but `climb` only judges what the policy
proposes, and the policy's top three were all big gags. `_track_key`
probing doesn't cover this either -- it offers each TRACK's biggest by
the policy's ranking, not the smallest that finishes the job; the gap
is size, not track.

One entry per live cog (bounded by the board, not the pouch), only when
something in the pouch kills it outright.

MEASURED, paired, 250 runs/cell then 300 held out: vp+5slips 81.2% ->
82.0% (+1/-0, p=1.00), vp+0slips 48.8% -> 54.4% (+24/-3, p=0.0002),
buildings 16.0% -> 21.6% (+30/-9, p=0.0008). Seven points on both
no-slip cells, and it replicates. Doesn't save gags (11.2 vs 11.4/run)
-- it wins more rounds outright, since the smallest kill leaves the
bigger gag for the cog that needs it. Pays most with no slip to fall
back on, the opposite of the board that found it (five slips; the real
fix there was `FIRE_PRICE`'s floor).
"""

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

# Whether an SOS card costs a judge call out of `budget`. It used to,
# and that is the bug: the cards sit at the END of the queue, so on any
# board big enough to fill the sweep the loop broke before reaching one.
# A four-cog VP wave with seven cards held is past the default 24 well
# before the first card, so `_quick_score` ranked a card first of
# seventy actions and `climb` never asked it.
#
# False is the shipped behaviour. True restores the old one, and exists
# so the two can be measured against each other on identical seeds
# rather than by checking out an old revision.
#
# MEASURED, because the judge preferring a card is not proof the card
# wins. 100 paired VP sides, two maxed toons, seven cards and three
# slips held, budget 24, common random numbers:
#
#     charged (old)  88/100   cards called 225   17.7 rounds/side
#     free    (new)  97/100   cards called 370   14.8 rounds/side
#
# +10 sides won only when free against 1 only when charged; sign test
# on the 11 discordant pairs p = 0.0117. Nine points and three rounds
# a side, from moves that were already being ranked and thrown away.
#
# The regime matters and cost an afternoon: a two-toon party is the only
# one that discriminates here. Solo never clears this harness (0/8 with
# or without unites) and there is nothing to compare; and an early n=8
# probe came back 7 against 6 the WRONG way, which is what a single
# discordant pair looks like. Do not read this flag on a small sample.
SOS_CHARGED_TO_BUDGET = False

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
    toon = state.toons[seat]
    held = getattr(toon, "sos_cards", None)
    if not held:
        return []
    return [Action(track=None, sos=name)
            for name in held
            if toon.sos_held(name) > 0 and name in sos_mod.BY_NAME]


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
                    organic=toon.is_organic(entry.track, entry.level))
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

Decided per SEAT (unlike `probe_tracks`, decided per CALL and defaulting
to party-only): did the policy hand the judge a menu with no choice on
it? When every top-k entry shares a `_track_key`, the judge can only
order variants of one move, however badly it scores.

TEN PINK SLIPS DO EXACTLY THAT: a fire keys as (None, False), so ten of
them collapse to one entry and the top-3 is three fires. The policy then
fires every round, which costs a ROUND (~15 laff with cogs awake) for no
gag -- solo VP at 8 cogs/round went from 49.5% with an empty slip pocket
to 0.0% with ten in it.

Solo VP, 8 cogs/round, 300 runs/cell selection then 500 held out:
probes-off/-always/degenerate-only win rates are 56.3%/66.0%/66.7-68.6%
with ten slips, 47.0%/37.3%/47.3-47.4% with none. Neither fixed setting
wins both rows -- probing always costs ten points empty-handed (p=0.006),
probing never costs ten points loaded. Held out: +138/-65 (p<0.0001)
with slips, +2/-1 without -- all the gain, none of the cost.

THE NET'S OWN RANKING IS THE ROOT CAUSE, which the probe works around
rather than fixes: on a live VP board the four fires take ranks 1-4 at
logits 20.4-21.1 against the best gag's 14.8 (a ~500x probability gap),
and the ranking is backwards on its own terms -- a 20hp Cold Caller
outranks both Hollywoods, and luring the whole board (when firing is
free) makes every fire logit fall, not rise. It reads as a reflex on
holding slips, uninformed by the board; only a retrain can fix the
ranking itself.

CANNOT REGRESS ANYTHING ALREADY PROBED: the condition short-circuits on
`probe_tracks or _menu_is_degenerate`, so every party position (where
`probe_tracks` defaults on) is unaffected -- only solo changes, and
solo buildings without slips read neutral (17.3% vs 16.7%, p=0.80).

REPLACES a hand-written rule withholding slips unless the whole board
was lured. That rule worked (54.0% vs 47.4% held out) but could only
ever fix pink slips (missing the same failure elsewhere) and suppressed
a GOOD move to prevent a bad one without ever comparing them: with
alternatives on the menu the policy actually fires MORE (5.2 slips/run
vs 3.0) and wins more often. Turning the old rule back on atop this
measured 57.3% vs 66.0% -- nine points lost once the judge can see.
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


@_memoised
def climb(state: BattleState, rng=random,
          # Raised together with `width`: `budget` counts judge calls
          # and a default of 16 against width 16 starves the probes
          # appended after the policy's own entries. On a trapped
          # ambulance chaser: budget 12 picks Storm Cloud, 16 picks
          # Small Magnet, 20/24 pick the $1 Bill that springs the trap.
          # Panels already pass 24; this keeps a caller on the default
          # from silently getting the truncated answer.
          budget: int = 24,
          # 16, measured. [OWNER] reported the policy spending a dearer
          # gag than the exact search wanted on the same board; spying
          # on every plan `_judge` scores showed why -- at width 3 the
          # search's pick is offered 0/4 times, at 8 it's 2/4, at 16
          # it's 4/4 (RL agrees with it 3/4). Below 16 the scorer never
          # sees the move at all, so no weight could ever reach it.
          #
          # Solo VP, 20/round, everything carried, paired: width 3 vs 16
          # read 60% vs 76% on selection seeds and 48% vs 75% held out
          # (+15/-4, p=0.019) -- not noise. Buildings are untouched (82%
          # at both widths, +0/-0): width pays where the POUCH binds (a
          # solo VP is ~4255 cog HP against a ~2730-damage pouch), and a
          # two-floor building shared by three toons never gets there.
          # Costs 20ms -> 26ms a decision.
          #
          # Coupled with `budget` -- see the docstring below before
          # raising either alone.
          width: int = 16, probe_tracks: Optional[bool] = None,
          deep: bool = False,
          fixed: Optional[Mapping[int, Optional[Action]]] = None,
          pairs: bool = True, pair_width: int = 7, reject=None,
          allow_unites: bool = True
          ) -> Optional[Sequence[Optional[Action]]]:
    """Coordinate ascent on the joint plan, instead of independent draws.

    `best_plan` re-rolls every seat on every sample, spending its budget
    re-deciding seats that were already right. A joint plan is one action
    per toon, so the natural move is to fix the others and vary one seat
    at a time.

    Starts from the policy's argmax plan, sweeps the seats offering each
    the policy's top `width` alternatives, keeps any `_quick_score`
    prefers, and repeats until a full sweep changes nothing or `budget`
    (`_quick_score` calls, so this is comparable with `best_plan` at
    equal cost) runs out.

    `pairs` lets two seats change TOGETHER once single-seat sweeps settle
    -- the one move coordinate ascent structurally cannot make. On a
    no-level-7 board, both toons on lure/6 scores 366.4 (where the sweep
    stops), changing either ONE to sound/6 scores 177.8, changing BOTH
    scores 672.1 -- Sound wakes what Lure put to sleep, so every
    single-seat edit looks downhill even though the joint edit nearly
    doubles the score. Over 43 sampled rounds the best plan needed both
    seats to move 72% of the time; the climb captured 68.4% of the
    reachable score.

    OFF, measured on 240 held-out sides: buildings 68.3% -> 70.4%, VP
    98.8% -> 99.6%, CEO-0 92.5% -> 90.4%, CEO-5 44.2% -> 35.4% (p=0.020),
    CEO-0-no-7s 21.7% -> 27.5% (p=0.041). Works where predicted, loses
    where the agent is already good -- both significant, opposite
    directions.

    THE GENERAL LESSON, which `probe_tracks` and wider `width` share: a
    joint move or wider menu gives the search more reach to act on
    `_quick_score`'s own errors, not just more good options. Where the
    policy is undertrained (a no-level-7 board) that reach rescues bad
    proposals; where it's well-trained, the same reach mostly finds the
    scorer's mistakes instead. The narrow window is a REGULARISER
    holding an imperfect scorer near a well-trained policy, not a
    limitation to remove -- widen it only for positions outside the
    policy's training distribution.

    `probe_tracks` offers each seat the best action of every track held,
    not just the top `width`. ON in a party, OFF solo -- measured on
    v7_precision, 250 runs/cell, OFF minus ON: building solo +0.4%,
    building party -1.2%, VP solo +9.2%, VP party -1.2%, CEO party
    -17.6%. In a party the joint plan space is large enough that a
    per-seat top-k misses combination moves (`sound/6->all` sat 22nd and
    16th for two seats on one board); solo there's no combination to
    miss, so the reach only helps an approximate scorer act on its
    errors. `None` decides from party size; pass a bool to override.

    `probe_tracks` WAS REFUTED TWICE before the scorer caught up (66.1%
    vs 63.3% with probes on 180 buildings, -7.5 on the CEO) for the same
    reason above. WHAT CHANGED WAS THE SCORER, NOT THE PROBE: once a
    landed attack wakes a lured cog (`mechanics.LURE_ENDS_ON_DAMAGE`),
    `prevented` counts what a Lure actually buys, and
    `QUICK_W["prevent"]` moved 2 -> 9, the same flag paid on 200 held-out
    sides: buildings 65.0% -> 73.5% (p=0.0002), CEO-0 54.0% -> 88.5%
    (p<0.0001), CEO-2 18.5% -> 73.5% (p<0.0001), CEO-4 7.0% -> 45.0%
    (p<0.0001). Trap and Toon-Up had been structurally invisible before
    this -- Trap at median rank 25, never in a 3-wide window in 521
    seats; Toon-Up rank 10, reachable 1% of the time -- no weight could
    have fixed that, which is why the earlier heal sweep read flat at
    twenty times the weight. THE LESSON, WHICH GENERALISES: fix the
    model, then the weights, then the reach, in that order -- reversed,
    each stage measures the previous one's errors and refutes the right
    idea for the wrong reason.

    GROUP AND SINGLE-TARGET ARE DIFFERENT MOVES, and probing by track
    alone hid one of them: the per-track menu offered `Birthday Cake ->
    c2` (342 by `_quick_score`) over `Wedding Cake -> all` (1103), never
    putting the group gag in front of the judge. `_track_key` now keys
    on (track, group); `GROUP_GAGS_PROBED_SEPARATELY` turns it off. ON,
    paired on identical positions: facilities -0.2/+1.3 (budget 24/36),
    CEO-0 -1.7/+4.5, CEO-2 +8.8, CEO-4 +9.0. The GAIN scales with cogs
    alive (what a group gag is for); the COST is fixed (~4 extra menu
    entries/seat). Starving the budget gets you the cost without the
    gain: at budget 24 CEO-0 is 88 up/98 down (p=0.51); at 36 it's 100
    up/73 down (p=0.048). Facilities are untouched at every budget (46
    discordant games in 1800) -- unlike the three earlier "widen the
    menu" refutations, this one is neutral where it can't help rather
    than costly everywhere.

    WIDTH AND BUDGET ARE COUPLED (`budget` counts judge calls and the
    loop breaks on `spent >= budget`, so a menu wider than the budget
    never reaches the probes appended after it -- `_cheapest_kills`,
    `_cheapest_lures`, the SOS list). On a trapped ambulance chaser:
    width 16/budget 8 -> Foghorn (wastes the armed trap), width
    16/budget 24 -> $1 Bill (springs it, the panel's setting), width
    32/budget 24 -> Small Magnet (starved again), width 32/budget 48 ->
    $1 Bill. So width 32 scoring worse than width 3 on the VP (+3/-7)
    was budget starvation, not the approximate-scorer effect above --
    16 fits inside the panel's budget of 24; wider needs the budget
    raised with it.

    Boss analysis wants budget 36+ (a PARTY result, measured, that does
    not carry to solo). Solo VP, 8 cogs/round, ten slips, paired on
    identical seeds: budget 3/4/6/8/16/24/36 -> 0.0%/11.3%/71.3% (held
    out 71.0%, p=0.46)/63.3% (held out 68.3%, the panel's setting)/
    47.3%/47.3% (held out 55.3%, p=0.0001)/47.3%. Raising it hurts solo
    by thirteen points held out, for the same reach-vs-errors reason;
    16/24/36 are identical because solo has one seat, so once the
    single-seat menu is exhausted (budget 8 stops partway through it,
    and stopping helps) there's nothing left to spend on without the
    pair loop. Below 6 it collapses (11.3% at 4, 0.0% at 3) because the
    climb can't afford even the first few candidates and falls back
    toward the policy's raw argmax -- what `PROBE_WHEN_DEGENERATE`
    exists to rescue. 6 looked like a free +8 on the selection set and
    came back +2.7, p=0.46 held out, so the panel keeps 8.
    (`advise.DEFAULT_BUDGET` is a different, still-unmeasured quantity:
    seconds for the expectimax path.)
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
    judge = (lambda st, pl: _judge(st, pl, deep))

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
                          pairs=pairs,
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
                # Appended, not merged (no index, no logit to sort by)
                # and NOT CHARGED TO THE BUDGET: they used to sit at the
                # end of the queue and never got reached on a board big
                # enough to fill the sweep -- a four-cog VP with seven
                # cards held is past the default 24 before the first
                # card, so the judge ranked a card FIRST and `climb`
                # never asked it (budget 24 picks Presentation, 40 picks
                # the card the judge preferred all along). Moving them
                # earlier instead just starves the other sweep
                # (`TARGETED_PROBES_FIRST`: difficulty 9 fell 60% to
                # 42%), so the sweep keeps its place and the handful of
                # cards are simply always judged.
                queue += [(action, False)
                          for action in _sos_probes(state, seat)]
            for action, charge in queue:
                if SOS_CHARGED_TO_BUDGET:
                    charge = True        # the pre-fix behaviour, for A/B
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
