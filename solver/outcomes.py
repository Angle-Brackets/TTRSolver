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

    This is the unmerged form of `cog_damage_distribution` below. The search
    only ever needs the damage number, but anything showing a human what
    happened needs to say *which* attack -- "Pencil Pusher used Fountain Pen
    for 6" rather than "6 damage from somewhere".
    """
    table = data.COG_DEPARTMENTS[cog.department][cog.cog_type]
    if table.get("accuracy") is None:
        raise NotImplementedError(
            f"Accuracy table for '{cog.cog_type}' is marked TODO in "
            f"data/{cog.department}.py."
        )
    rel_level = cog.level - table["levels"][0]

    freqs = {name: rows[rel_level] for name, rows in table["freq"].items()}
    total_freq = sum(freqs.values())
    if total_freq != 100:
        # mechanics.pick_cog_attack samples cumulatively and falls through to
        # the first attack when the frequencies don't reach the roll, so any
        # shortfall lands on the first attack. Mirror that rather than
        # renormalizing, so this distribution matches the sampler exactly.
        first = next(iter(freqs))
        freqs[first] += 100 - total_freq

    results: List[Tuple[float, str, int, bool]] = []
    for name, freq in freqs.items():
        p_attack = freq / 100.0
        if p_attack <= 0:
            continue

        # Individual cells can be None even when the table as a whole is
        # populated. Catch that here so it reads as a data gap instead of
        # surfacing as a TypeError deep in the arithmetic.
        raw_acc = table["accuracy"][name][rel_level]
        entry = table["damage"][name][rel_level]
        if raw_acc is None or entry is None:
            missing = "accuracy" if raw_acc is None else "damage"
            raise NotImplementedError(
                f"{cog.cog_type}/{name} at level {cog.level}: {missing} is "
                f"marked TODO in data/{cog.department}.py."
            )
        p_hit = raw_acc / 100.0

        if isinstance(entry, int):
            damage_options = [(1.0, entry)]
        else:  # inclusive (min, max) range, sampled uniformly
            low, high = entry
            span = high - low + 1
            damage_options = [(1.0 / span, d) for d in range(low, high + 1)]

        for p_dmg, dmg in damage_options:
            if p_attack * p_hit * p_dmg > 0:
                results.append((p_attack * p_hit * p_dmg, name, dmg, True))
        if p_hit < 1.0:
            results.append((p_attack * (1.0 - p_hit), name, 0, False))

    return results


def cog_damage_distribution(cog: CogState) -> Dict[int, float]:
    """{damage: probability} for one cog's attack this round, assuming it
    attacks at all. Damage 0 covers every miss.

    The merged form of `cog_attack_outcomes` -- which attack landed doesn't
    affect the next state, only the number does, so the search collapses
    them."""
    dist: Dict[int, float] = {}
    for prob, _name, dmg, _hit in cog_attack_outcomes(cog):
        dist[dmg] = dist.get(dmg, 0.0) + prob
    return dist


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
                     gag_cost_lambda: float = 0.1) -> List[Outcome]:
    """Every (probability, next_state, reward) triple for taking `action`.

    Probabilities sum to 1. Rewards use simulator.step's convention:
    -laff_lost - gag_cost_lambda*level, +100 on a win, -100 on a loss.
    """
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
            _accumulate(results, p_toon, after_toon, 0, action, gag_cost_lambda)
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
                        action, gag_cost_lambda)

    return [(p, st, r) for p, st, r in results.values()]


def _accumulate(results, prob, state_after, laff_lost, action,
                 gag_cost_lambda) -> None:
    """Apply laff loss, advance the round, compute reward, and merge into
    `results` -- identical resulting states have their probabilities summed
    so the solver doesn't explore the same node twice."""
    state_after.toon.laff = max(0, min(state_after.toon.max_laff,
                                       state_after.toon.laff - laff_lost))
    state_after.round_num += 1

    reward = -float(laff_lost) - gag_cost_lambda * float(action.level)
    if state_after.is_win():
        reward += 100.0
    elif state_after.toon.laff <= 0:
        reward -= 100.0

    key = state_key(state_after)
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
            "cog": cog.cog_type.replace("_", " ").title(),
            "level": cog.level,
            "lured": cog.status.lured,
            "lure_rounds": cog.status.lure_rounds_remaining,
            "attacks": [],
        }

        # A lured cog only acts if its lure ends this round; fold that in so
        # the percentages shown are unconditional.
        p_acts = lure_end_probability(cog) if cog.status.lured else 1.0
        entry["p_acts"] = round(p_acts, 4)
        group_attacks = data.COG_DEPARTMENTS[cog.department][cog.cog_type][
            "group_attacks"]

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


def state_key(state: BattleState) -> Tuple:
    """Hashable identity for a state, for outcome merging and solver
    memoization. `round_num` is deliberately excluded -- nothing in the
    mechanics depends on it, so including it would split otherwise
    identical nodes."""
    return (
        state.toon.laff,
        tuple(sorted((t.value, lvl, n)
                     for (t, lvl), n in state.toon.gag_counts.items() if n > 0)),
        tuple((c.cog_type, c.department, c.level, c.hp, c.status.is_dead,
               c.status.lured, c.status.lure_rounds_remaining,
               c.status.lure_acc_before_bonus, c.status.lure_level,
               c.status.trapped, c.status.trap_level)
              for c in state.cogs),
    )
