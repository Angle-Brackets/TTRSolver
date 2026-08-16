"""
Exact outcome distributions: the enumerating twin of `simulator.step`.

`simulator.step` *samples* a single next state -- it calls `random` for the
toon's hit roll, each cog's attack choice, each cog's hit roll, and each
damage range. That's the right interface for MCTS or RL rollouts, but
expectimax and value iteration need the outcome *distribution*, not one
draw from it. This module provides it:

    action_outcomes(state, action) -> [(prob, next_state, reward), ...]

with probabilities summing to 1 and `reward` matching `simulator.step`'s
reward convention exactly, so a solver built on this optimizes the same
objective a sampling agent would.

WHY THE COG PHASE DOESN'T EXPLODE
---------------------------------
Naively the cog phase is a joint over (which attack x hit/miss) for every
cog: (5 attacks x 2)^4 = 10,000 branches for four cogs. Two things collapse
it. First, the toon is solo, so a cog's attack choice has no effect on the
next state beyond the damage number -- the joint convolves down to a
distribution over *total damage*, usually a few dozen values. Second, the
only per-cog state the phase can change is whether a lured cog woke up, so
the surviving joint is (woken-subset x total-damage), not the full product.
The visualizer's `convolve()` does the same collapse in JS.

WHERE THE RULES LIVE
--------------------
The toon phase is NOT reimplemented here -- this module calls
`simulator.apply_toon_action(state, action, hit)`, the same deterministic
function `simulator.step` uses once it has rolled the dice. So gag damage,
kbBonus, trap detonation, and lure application can only be written once.

The cog phase genuinely does exist twice: `simulator._resolve_cog_phase`
samples it, `cog_phase_outcomes` below enumerates it. Enumerating is not a
transformation of sampling, so some duplication is unavoidable there. Two
things keep the pair honest -- both go through `mechanics` and the same
data tables for every constant, and `tests/test_outcomes.py`'s
`test_matches_sampled_step` compares the enumerated distribution against
8,000 samples of `step`, state by state and reward by reward. If they ever
drift, that test fails.

(Having `step` sample *from* this enumeration would remove even that seam,
but it would make every sampled step pay for building the full
distribution -- far too slow for the rollout-heavy uses `step` exists for --
and it would make simulator and outcomes mutually recursive.)
"""
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from . import data
from . import mechanics
from . import simulator
from .state import BattleState, CogState, Action, Track

# (probability, next_state, reward)
Outcome = Tuple[float, BattleState, float]


# ---------------------------------------------------------------------
# Toon phase -- deterministic given whether the gag hit
# ---------------------------------------------------------------------

def _toon_hit_probability(state: BattleState, action: Action) -> float:
    """Probability the gag lands, straight from the simulator's own accuracy
    function so the luredRatio bonus and the 95 cap can't be forgotten here."""
    return simulator.toon_action_accuracy(state, action) / 100.0


# ---------------------------------------------------------------------
# Cog phase
# ---------------------------------------------------------------------

def cog_attack_outcomes(cog: CogState) -> List[Tuple[float, str, int, bool]]:
    """(probability, attack_name, damage, hit) for one cog's turn, assuming
    it attacks at all.

    Depends only on the cog's type and level -- not on its HP, lure or trap
    state -- so the real work is cached. A depth-2 search called this 11,111
    times for three distinct cogs.

    This is the unmerged form of `cog_damage_distribution` below. The search
    only ever needs the damage number, but anything showing a human what
    happened needs to say *which* attack -- "Pencil Pusher used Fountain Pen
    for 6" rather than "6 damage from somewhere".
    """
    return _attack_outcomes(cog.department, cog.cog_type, cog.level)


@lru_cache(maxsize=None)
def _attack_outcomes(department: str, cog_type: str,
                      level: int) -> Tuple[Tuple[float, str, int, bool], ...]:
    spec = data.cog(department, cog_type)
    index = spec.rel_index(level)
    attacks = spec.modeled_attacks

    freqs = {a.name: spec.frequency_at(a.name, level) for a in attacks}
    total_freq = sum(freqs.values())
    if total_freq != 100:
        # mechanics.pick_cog_attack samples cumulatively and falls through to
        # the first attack when the frequencies don't reach the roll, so any
        # shortfall lands on the first attack. Mirror that rather than
        # renormalizing, so this distribution matches the sampler exactly.
        freqs[attacks[0].name] += 100 - total_freq

    results: List[Tuple[float, str, int, bool]] = []
    for attack in attacks:
        p_attack = freqs[attack.name] / 100.0
        if p_attack <= 0:
            continue

        # Individual cells can be a documented gap even when the rest of the
        # cog is filled in; these accessors raise naming the cell rather than
        # letting a None reach the arithmetic.
        p_hit = spec.accuracy_at(attack.name, level) / 100.0
        entry = spec.damage_at(attack.name, level)

        if isinstance(entry, int):
            damage_options = [(1.0, entry)]
        else:  # inclusive (min, max) range, sampled uniformly
            low, high = entry
            span = high - low + 1
            damage_options = [(1.0 / span, d) for d in range(low, high + 1)]

        for p_dmg, dmg in damage_options:
            if p_attack * p_hit * p_dmg > 0:
                results.append((p_attack * p_hit * p_dmg, attack.name, dmg, True))
        if p_hit < 1.0:
            results.append((p_attack * (1.0 - p_hit), attack.name, 0, False))

    return tuple(results)


def cog_damage_distribution(cog: CogState) -> Dict[int, float]:
    """{damage: probability} for one cog's attack this round, assuming it
    attacks at all. Damage 0 covers every miss.

    The merged form of `cog_attack_outcomes` -- which attack landed doesn't
    affect the next state, only the number does, so the search collapses
    them.

    DO NOT MUTATE the returned dict. It is shared, not rebuilt per call:
    the distribution depends only on the cog's department, type and level,
    and a three-cog depth-2 search asked for it 1.1 million times.
    """
    return _damage_distribution(cog.department, cog.cog_type, cog.level)


@lru_cache(maxsize=None)
def _damage_distribution(department: str, cog_type: str,
                          level: int) -> Dict[int, float]:
    dist: Dict[int, float] = {}
    for prob, _name, dmg, _hit in _attack_outcomes(department, cog_type,
                                                    level):
        dist[dmg] = dist.get(dmg, 0.0) + prob
    return dist


@lru_cache(maxsize=None)
def _worst_damage(department: str, cog_type: str, level: int) -> int:
    dist = _damage_distribution(department, cog_type, level)
    return max(dist) if dist else 0


def worst_case_damage(cog: CogState) -> int:
    """The most this cog could deal in one round, over all its attacks.

    Cached on the same key as the distribution: the search's value bounds
    ask for this once per node, which was 367,000 times on a three-cog
    depth-2 position.
    """
    return _worst_damage(cog.department, cog.cog_type, cog.level)


def clear_caches() -> None:
    """Drop every memo derived from the cog tables.

    Anything that edits `data.COG_DEPARTMENTS` underneath us -- the
    sensitivity analysis does exactly that -- has to call this, or the
    perturbed numbers are computed once and then ignored.
    """
    _attack_outcomes.cache_clear()
    _damage_distribution.cache_clear()
    _worst_damage.cache_clear()


def lure_end_probability(cog: CogState) -> float:
    """Probability a lured cog's lure ends this round, so it attacks.

    Mirrors simulator._tick_lure: the round counter running out ends the
    lure outright, and only if it hasn't does the wake-up roll apply.
    """
    if cog.status.lure_rounds_remaining <= 0:
        return 1.0
    if not mechanics.lure_can_expire_early(cog.status.lure_level):
        return 0.0     # TTR 3.3.0: no current Lure gag can expire early
    acc = cog.status.lure_acc_before_bonus
    if acc is None:
        raise ValueError(
            "Lured cog has no lure_acc_before_bonus -- wakeupChance can't be "
            "computed. Set it (via CogStatus.apply_lure) whenever you mark a "
            "cog lured."
        )
    return min(100, max(0, mechanics.lure_wakeup_chance(acc))) / 100.0


def cog_phase_outcomes(state: BattleState
                        ) -> List[Tuple[float, int, frozenset, frozenset]]:
    """[(probability, total_damage_to_toon, lures_ended, lures_held)].

    Convolves the per-cog distributions. `lures_ended` and `lures_held` are
    cog indices: a lure that ended has to be cleared, and one that held has
    to burn a round off its counter, so the caller can't just look at the
    damage number.

    A lured cog contributes a mixture -- it stays asleep and deals nothing,
    or its lure ends (timeout or wake-up) and it attacks this same round.
    """
    combined: Dict[Tuple[int, frozenset, frozenset], float] = {
        (0, frozenset(), frozenset()): 1.0
    }

    for idx, cog in enumerate(state.cogs):
        if cog.status.is_dead:
            continue

        # branches: (probability, damage, ended_lure, held_lure)
        if cog.status.lured:
            p_end = lure_end_probability(cog)
            branches = []
            if p_end < 1.0:
                branches.append((1.0 - p_end, 0, False, True))
            if p_end > 0:
                branches += [(p_end * p, d, True, False)
                             for d, p in cog_damage_distribution(cog).items()]
        else:
            branches = [(p, d, False, False)
                        for d, p in cog_damage_distribution(cog).items()]

        nxt: Dict[Tuple[int, frozenset, frozenset], float] = {}
        for (dmg_so_far, ended, held), p_so_far in combined.items():
            for p_branch, dmg, did_end, did_hold in branches:
                if p_branch <= 0:
                    continue
                key = (dmg_so_far + dmg,
                       ended | {idx} if did_end else ended,
                       held | {idx} if did_hold else held)
                nxt[key] = nxt.get(key, 0.0) + p_so_far * p_branch
        combined = nxt

    return [(p, dmg, ended, held)
            for (dmg, ended, held), p in combined.items()]


# ---------------------------------------------------------------------
# Full transition
# ---------------------------------------------------------------------

def action_outcomes(state: BattleState, action: Action,
                     objective=None) -> List[Outcome]:
    """Every (probability, next_state, reward) triple for taking `action`.

    Probabilities sum to 1. `objective` decides what the rewards mean --
    see solver/search/objective.py. It defaults to the balanced preset,
    which reproduces simulator.step's convention exactly, so a sampled
    rollout and a searched line optimise the same thing.

    A float is accepted for the old gag-cost-only calling convention.
    """
    from .search import objective as objective_mod
    if objective is None:
        objective = objective_mod.DEFAULT
    elif isinstance(objective, (int, float)):
        objective = objective_mod.Objective(gag_cost=float(objective))
    results: Dict[Tuple, List] = {}

    p_hit = _toon_hit_probability(state, action)
    hit_branches = []
    if p_hit > 0:
        hit_branches.append((p_hit, True))
    if p_hit < 1:
        hit_branches.append((1.0 - p_hit, False))

    for p_toon, hit in hit_branches:
        after_toon = state.clone()
        simulator.apply_toon_action(after_toon, action, hit)

        if after_toon.is_terminal():
            _accumulate(results, p_toon, after_toon, 0, action, objective)
            continue

        for p_cogs, laff_lost, ended, held in cog_phase_outcomes(after_toon):
            if p_cogs <= 0:
                continue
            final = after_toon.clone()
            for idx in ended:
                final.cogs[idx].status.clear_lure()
            for idx in held:
                final.cogs[idx].status.lure_rounds_remaining -= 1
            _accumulate(results, p_toon * p_cogs, final, laff_lost,
                        action, objective)

    return [(p, st, r) for p, st, r in results.values()]


def _accumulate(results, prob, state_after, laff_lost, action,
                 objective) -> None:
    """Apply laff loss, advance the round, compute reward, and merge into
    `results` -- identical resulting states have their probabilities summed
    so the solver doesn't explore the same node twice."""
    state_after.toon.laff = max(0, min(state_after.toon.max_laff,
                                       state_after.toon.laff - laff_lost))
    state_after.round_num += 1

    reward = objective.step_reward(
        laff_lost, action.track, action.level,
        won=state_after.is_win(),
        # Not just "laff hit zero". A toon that can no longer damage a cog
        # has lost the battle just as surely -- see
        # BattleState.can_still_damage -- and the search has to be told,
        # or it scores a hopeless position with the heuristic instead.
        lost=state_after.is_terminal() and not state_after.is_win())

    key = merge_key(state_after)
    existing = results.get(key)
    if existing is None:
        results[key] = [prob, state_after, reward]
    else:
        existing[0] += prob


def cog_phase_summary(state: BattleState) -> List[Dict]:
    """What each cog is about to do, per cog, as marginal probabilities.

    The obvious thing for a UI would be the *joint* -- every combination of
    what all the cogs do -- but that is combinatorial: three cogs produce
    ~430 distinct lines, so even the twelve most likely cover under a tenth
    of the probability, and showing them would badly misrepresent the round.
    The marginals are compact, exact, and answer the actual question ("what
    can this cog do to me, and how likely is each?"). The joint over total
    damage is still available, merged, from `cog_phase_outcomes`.
    """
    summary = []
    for index, cog in enumerate(state.cogs):
        if cog.status.is_dead:
            continue

        entry = {
            "index": index,
            "cog": data.cog(cog.department, cog.cog_type).display,
            "level": cog.level,
            "lured": cog.status.lured,
            "lure_rounds": cog.status.lure_rounds_remaining,
            "attacks": [],
        }

        # A lured cog only acts if its lure ends this round; fold that in so
        # the percentages shown are unconditional.
        p_acts = lure_end_probability(cog) if cog.status.lured else 1.0
        entry["p_acts"] = round(p_acts, 4)
        spec = data.cog(cog.department, cog.cog_type)
        group_attacks = {a.name for a in spec.attacks if a.group}

        if p_acts > 0:
            merged: Dict[str, Dict] = {}
            for prob, name, dmg, hit in cog_attack_outcomes(cog):
                slot = merged.setdefault(name, {
                    "attack": name.replace("_", " ").title(),
                    "prob": 0.0, "hit_prob": 0.0, "damage": 0,
                    "group": name in group_attacks,
                })
                slot["prob"] += prob * p_acts
                if hit:
                    slot["hit_prob"] += prob * p_acts
                    slot["damage"] = max(slot["damage"], dmg)
            entry["attacks"] = sorted(
                ({**v, "prob": round(v["prob"], 4),
                  "hit_prob": round(v["hit_prob"], 4)} for v in merged.values()),
                key=lambda a: a["prob"], reverse=True)

        entry["expected_damage"] = round(
            sum(a["hit_prob"] * a["damage"] for a in entry["attacks"]), 2)
        summary.append(entry)
    return summary


def collapse_damage(branches: List[Outcome]) -> List[Outcome]:
    """Merge outcomes that differ only in how much damage the cogs dealt.

    A ply costs `actions x chance outcomes`, and the second factor is
    what keeps the search shallow -- 20 to 70 branches per action, almost
    all of them the same events with a different damage total. Unlike the
    toon's own hit roll, that number carries no decision: the cogs cannot
    kill each other, cannot change what gags remain, and cannot alter
    anything the next choice depends on except the laff figure.

    So branches sharing a cog configuration collapse into one carrying
    the probability-weighted mean laff. Outcomes per action drop to a
    handful, which is worth one to two extra plies.

    Two things are deliberately NOT merged. Branches whose cog states
    differ at all -- a gag hit rather than missed, a lure held rather
    than ended -- stay separate, because those do change the next
    decision. And a branch where the toon died stays separate from one
    where it survived: averaging a death into a survival is exactly the
    distortion that would make the search cheerfully walk into a loss.

    This is an approximation, and the only one here that touches the
    shape of the tree rather than its tails. It makes the search
    risk-*neutral* about damage, which is wrong near zero laff and wrong
    for an objective that weights laff heavily, so callers should keep
    the plies nearest the root exact -- see `evaluate`'s `exact_plies`.
    """
    if len(branches) <= 1:
        return branches

    groups: Dict[Tuple, list] = {}
    for prob, nxt, reward in branches:
        key = (_cog_key(nxt), nxt.is_terminal())
        slot = groups.get(key)
        if slot is None:
            groups[key] = [prob, prob * nxt.toon.laff, prob * reward, nxt]
        else:
            slot[0] += prob
            slot[1] += prob * nxt.toon.laff
            slot[2] += prob * reward
    if len(groups) == len(branches):
        return branches

    merged: List[Outcome] = []
    for total, laff_sum, reward_sum, sample in groups.values():
        state = sample.clone()
        state.toon.laff = max(0, min(state.toon.max_laff,
                                     int(round(laff_sum / total))))
        merged.append((total, state, reward_sum / total))
    return merged


def _cog_key(state: BattleState) -> Tuple:
    return tuple((c.cog_type, c.department, c.level, c.hp, c.status.is_dead,
                  c.status.lured, c.status.lure_rounds_remaining,
                  c.status.lure_acc_before_bonus, c.status.lure_level,
                  c.status.trapped, c.status.trap_level,
                  c.status.trap_organic)
                 for c in state.cogs)


def merge_key(state: BattleState) -> Tuple:
    """Identity of a state *within one action's outcome set*.

    Deliberately omits the gag counts, which `state_key` includes. Every
    outcome of a single action spent the same gag from the same pouch, so
    the counts are identical across all of them and hashing a
    twenty-element frozenset of them per outcome is pure overhead --
    measured at 11.8 million generator steps on a three-cog depth-2
    search, for a value that never varies within the comparison.

    Only for merging siblings. Use `state_key` for the transposition
    table, where states genuinely differ in what has been spent.

    The fast path is one toon, because that is every searched position
    today; the tuple form is only built for a party. Laff is per toon
    and ORDER MATTERS -- toons are not interchangeable, they hold
    different pouches, so this must not be a frozenset.
    """
    if len(state.toons) == 1:
        return (state.toon.laff, _cog_key(state))
    return (tuple(t.laff for t in state.toons), _cog_key(state))


def state_key(state: BattleState) -> Tuple:
    """Hashable identity for a state, for outcome merging and solver
    memoization. `round_num` is deliberately excluded -- nothing in the
    mechanics depends on it, so including it would split otherwise
    identical nodes.

    This is the hottest function in the search -- a depth-2 two-cog
    position calls it 319,000 times -- so two things here are deliberate
    and worth keeping.

    The track is used as-is rather than as `t.value`. `Track` subclasses
    `str`, so the member is already a perfectly good key, and `.value`
    goes through `DynamicClassAttribute` on every access: it accounted
    for 6.2 million enum lookups and a fifth of the whole search.

    The gag counts are a frozenset rather than a sorted tuple. Both are
    canonical, but a frozenset needs no comparisons, and this key is only
    ever hashed -- never ordered, never serialised.

    A party keys on every toon, in order. Keying on `toons[0]` alone
    would let the memo answer a question about one party with the value
    of a different one -- same lead toon, different teammates -- which
    is the quietest possible way for a transposition table to be wrong.

    `free_passes` is in the key for that same reason, and was left out
    when the field was added. It changes `legal_actions`, so two states
    differing only in it are genuinely different nodes -- and with them
    collapsed, the memo answered a position holding three passes with
    the value of one holding none. The symptom was a search that liked
    passing MORE as its laff dropped, which is backwards, and it was
    visible only because someone asked why it would not throw.

    Contrast `round_num`, which stays out: nothing in the mechanics
    reads it, so including it would split identical nodes for nothing.
    The test is whether a field can change what happens next, not
    whether it changes.
    """
    if len(state.toons) == 1:
        toon = state.toon
        return (
            toon.laff,
            frozenset((t, lvl, n)
                      for (t, lvl), n in toon.gag_counts.items() if n > 0),
            _cog_key(state),
            state.free_passes,
            state.cogs_remaining,
        )
    return (
        tuple((t.laff,
               frozenset((tr, lvl, n)
                         for (tr, lvl), n in t.gag_counts.items() if n > 0))
              for t in state.toons),
        _cog_key(state),
        state.free_passes,
        state.cogs_remaining,
    )
