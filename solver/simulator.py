"""
The actual (state, action) -> (next_state, reward, done) transition,
i.e. what an expectimax / value-iteration / RL solver would call.

Round resolution order (solo toon, so this is simpler than the full
multi-toon initiative rules in mechanics.py's docstring):
  1. Toon acts (one Action).
  2. Any status effects that action triggers resolve (trap set, trap
     triggered by lure, cog death, cog lured).
  3. Each surviving cog attacks. A lured cog first has its lure timeout
     ticked and then rolls its wake-up check; if either ends the lure it
     attacks this same round, otherwise it skips.
  4. Reward is computed, round counter increments.

Step 3's ordering (timeout expiry before the wake-up roll) follows the
source: `__updateLureTimeouts()` runs once per round before the cog
attacks are picked, and the wake-up check is itself gated on the cog's
round counter still being > 0.
"""
from typing import List, Tuple

from . import data
from . import mechanics
from .state import BattleState, CogState, Action, Track


def is_group_action(track: Track, level: int) -> bool:
    if track == Track.SOUND:
        return True     # [CONFIRMED] every Sound gag hits all cogs
    if track == Track.TOON_UP:
        # [CONFIRMED] TTR wiki: Toon-Up has the same 2/4/6/7 zig-zag as
        # Lure -- Feather, Lipstick and Pixie Dust each affect one Toon.
        # (Moot while solo, but wrong is wrong.)
        return data.gag(Track.TOON_UP, level).group
    if track == Track.LURE:
        # [CONFIRMED] TTR wiki: Small Magnet (2), Big Magnet (4),
        # Hypno-goggles (6) and Presentation (7) all hit every cog. Only
        # the dollar-bill gags at 1/3/5 are single-target. This used to say
        # `level == 7`, which made three group gags single-target.
        return data.gag(Track.LURE, level).group
    if track in (Track.THROW, Track.SQUIRT, Track.DROP, Track.TRAP):
        return level == 7           # Wedding Cake / Geyser / Ocean Liner / Train Tracks
    return False


def legal_actions(state: BattleState) -> List[Action]:
    """Every action the toon may take this round, pass included.

    WHEN PASS IS OFFERED
    --------------------
    Only when a cog is lured *and* nothing productive can be done -- the
    situation where passing is the only move, not merely a legal one.
    Two separate reasons for a rule this narrow.

    The first is that a pass is not the free move it looks like at a
    search horizon. A lured cog does not attack, so passing while the
    battle is lured costs no laff and no gag: the leaf evaluator sees a
    round that cost nothing, and a shallow search will happily lure and
    then coast. The cost is real but it is off the horizon -- the lure
    lapses and no progress was made. Offered unconditionally, this
    swung a depth-2 search off a Cream Pie that killed a cog outright
    and onto a Lure. Exact play was never fooled; shallow play was, and
    shallow play is what ships.

    The second is termination. `solve()` terminates because every action
    spends a gag, so the gag count strictly decreases and the state
    graph is a DAG. A pass spends nothing, so an always-legal pass would
    let the search walk pass -> pass -> pass forever. Requiring a lured
    cog keeps a measure that still decreases: a lured cog's
    `lure_rounds_remaining` ticks down during the cog phase, and nothing
    but a fresh Lure gag puts rounds back. The measure is lexicographic,
    (gags remaining, total lure rounds remaining), and well-founded.

    The move this exists for: trap and lure left, cogs already lured. A
    trap cannot be placed on a lured cog, so the only gag action is to
    burn a Lure re-luring a cog that is already lured. Waiting for the
    lure to lapse, then trapping and re-luring, wins fights that
    otherwise run the pouch dry. tests/test_pass.py plays one out.
    """
    actions = []
    toon = state.toon
    active = state.active_cogs()
    if not active:
        return actions

    for (track, level), count in toon.gag_counts.items():
        if count <= 0:
            continue
        if toon.track_exp.get(track, 0) <= 0:
            continue  # toon doesn't own this track

        if is_group_action(track, level):
            actions.append(Action(track=track, level=level, target_index=None))
            continue

        for i, cog in enumerate(state.cogs):
            if cog.status.is_dead:
                continue
            if track == Track.TRAP:
                if cog.status.trapped or cog.status.lured:
                    continue  # can't trap an already-trapped or lured cog
            actions.append(Action(track=track, level=level, target_index=i))

    if (any(cog.status.lured for cog in active)
            and not any(is_productive(state, a) for a in actions)):
        actions.append(Action(track=None, level=0, target_index=None))

    return actions


def is_productive(state: BattleState, action: Action) -> bool:
    """Does this action advance the battle at all?

    Only used to decide whether the toon is stuck and should be offered
    a pass, so "no" needs to mean *nothing whatsoever*, not "poor
    value". Choosing between productive moves is the search's job.
    """
    if action.is_pass:
        return False
    if action.track == Track.TOON_UP:
        return state.toon.laff < state.toon.max_laff
    targets = [c for c in _targets_for(state, action) if not c.status.is_dead]
    if action.track == Track.LURE:
        # Re-luring a cog that is already lured only refreshes a timer
        # the toon is trying to run down. A group Lure over a mixed
        # battle still counts -- it catches the ones that are loose.
        return any(not cog.status.lured for cog in targets)
    if action.track == Track.DROP:
        # Drop always misses a lured cog, so a Drop with no un-lured
        # target is a gag thrown away.
        return any(not cog.status.lured for cog in targets)
    # Trap arms something, and the damage tracks damage something.
    return bool(targets)


def _targets_for(state: BattleState, action: Action) -> List[CogState]:
    if action.target_index is not None:
        return [state.cogs[action.target_index]]
    return state.active_cogs()


def _apply_trap_trigger(cog: CogState) -> int:
    """Cog was lured onto its own trap: detonate it, clear trap status,
    return damage dealt.

    Ordering [CONFIRMED]: within a round, attacks resolve Toon-up -> Trap
    -> Lure -> Sound -> Throw -> Squirt -> Drop, so a Trap laid in the
    same round is already on the ground when the Lure resolves. A solo
    toon acts once per round, so the trap here is always from an earlier
    round; either way, detonating at Lure time matches the source order.

    A trapped cog that is DAMAGED rather than lured keeps its trap: the
    guide describes Trap as persisting on the cog until a Lure moves it
    onto the trap, and gives no rule for damage clearing a trap. (Nor is
    re-trapping possible -- legal_actions blocks trapping an already
    trapped or lured cog, which is [CONFIRMED].)"""
    # trained_fraction 1.0, matching mechanics.calc_toon_damage's default
    # and therefore every other track. This read 0.0 -- the MINIMUM of the
    # range -- which is a convention no other gag uses. TNT deals 90-180,
    # so a trap was being resolved at 90 while a Grand Piano of the same
    # level resolved at 170, and any comparison between Trap and another
    # track was measuring that discrepancy rather than the game.
    dmg = data.gag(Track.TRAP, cog.status.trap_level).damage_at(
        1.0, organic=cog.status.trap_organic)
    cog.status.trapped = False
    cog.status.trap_track = None
    cog.status.trap_level = None
    cog.status.trap_organic = False
    return dmg


def toon_action_accuracy(state: BattleState, action: Action) -> int:
    """The gag's hit chance, 0-100.

    Passes all_cogs (not just the targets) so the luredRatio half of `bonus`
    sees the whole battle -- its denominator is every cog in play.

    A pass always "hits": it has one outcome, so the search should not
    split a chance node over it.
    """
    if action.is_pass:
        return 100
    return mechanics.calc_toon_accuracy(
        action.track, action.level, state.toon,
        _targets_for(state, action), all_cogs=state.cogs,
        lure_tree_planted=state.toon.is_organic(action.track))


def apply_toon_action(state: BattleState, action: Action,
                       hit: bool) -> Tuple[int, int]:
    """Apply the toon's action given a known hit/miss, mutating `state`.
    Returns (laff_healed, damage_dealt_total).

    Deterministic on purpose: this is the single implementation of the
    toon-phase rules, shared by `_resolve_toon_action` (which rolls the
    dice) and `outcomes.action_outcomes` (which enumerates both branches).
    Anything added here reaches the solver automatically -- don't fork it.
    """
    toon = state.toon
    if action.is_pass:
        # Nothing spent, nothing dealt. The round still happens -- the
        # caller runs the cog phase, which is the entire point of
        # passing: it is how lure rounds get burned.
        return 0, 0
    targets = _targets_for(state, action)

    # Copy-on-write. `BattleState.clone` shares this dict rather than
    # copying it, because a clone happens once per outcome branch -- tens
    # of times per action -- while the counts change exactly once, here.
    # Copying at the point of change instead turns ~55 dict copies per
    # action into one. This is the ONLY place gag_counts is mutated; if
    # that ever stops being true, every sibling state silently shares the
    # edit. tests/test_state.py pins the invariant.
    counts = dict(toon.gag_counts)
    counts[(action.track, action.level)] -= 1
    toon.gag_counts = counts

    healed = 0
    dealt = 0

    if action.track == Track.TOON_UP:
        # [CONFIRMED] TTR wiki: "Toon-Up gags do not necessarily miss, but
        # rather, provide 20% of original values that are rounded up." So a
        # missed Toon-Up still heals -- it is the one track where a miss
        # isn't a no-op, which is why this sits above the `if not hit`.
        return mechanics.calc_toon_heal(action.level, hit), dealt

    if not hit:
        return healed, dealt

    if action.track == Track.TRAP:
        # Every target, not just the first. Railroad is a group gag -- it
        # lays a trap in front of all of them -- and arming only one cog
        # quietly turned the best trap in the game into a single-target one,
        # which made the Railroad+Lure combo look far weaker than it is.
        #
        # A lured cog is skipped: you cannot place a trap under a cog that
        # has already been pulled off its square, which is the same rule
        # legal_actions applies to single-target traps. An existing trap is
        # overwritten -- [CONFIRMED] TTR 3.0.0, "if there are active Trap
        # gags on Cogs, and a Railroad gag is placed in a subsequent round
        # by itself, it will override the previously placed Trap gags
        # rather than fizzling out".
        for cog in targets:
            if cog.status.lured:
                continue
            cog.status.trapped = True
            cog.status.trap_track = action.track
            cog.status.trap_level = action.level
            cog.status.trap_organic = toon.is_organic(action.track)

    elif action.track == Track.LURE:
        # Snapshot the accuracy this Lure landed with, BEFORE any bonus and
        # uncapped -- that is the value wakeupChance is computed from every
        # round the lure holds. One value per attack, stored on every cog
        # the attack lured (matching the source's single atkAccResult).
        acc_before_bonus = mechanics.lure_accuracy_before_bonus(
            action.track, action.level, toon, targets)
        # Looked up before any state is mutated so that the [TODO] raise
        # can't leave a half-applied lure behind.
        rounds = mechanics.lure_duration_rounds(action.level)
        for cog in targets:
            if cog.status.trapped:
                dmg = _apply_trap_trigger(cog)
                cog.hp -= dmg
                dealt += dmg
                if cog.hp <= 0:
                    cog.status.is_dead = True
                    continue
                # [TODO] Unconfirmed whether a cog that just detonated its
                # trap is then lured, or knocked out of the lure by the
                # trap damage (same open question as
                # mechanics.LURE_ENDS_ON_DAMAGE). Kept as "still lured",
                # the pre-existing behaviour. Not reachable today anyway:
                # lure_duration_rounds() above and per-level trap damage
                # in _apply_trap_trigger() are both [TODO] and raise.
            cog.status.apply_lure(acc_before_bonus, rounds, action.level)

    else:  # SOUND, THROW, SQUIRT, DROP -- direct damage
        for cog in targets:
            if action.track == Track.DROP and cog.status.lured:
                # [CONFIRMED] TTR wiki: "Drop gags always miss on lured
                # Cogs." Per-target, so a group Drop still hits the
                # un-lured members of a mixed battle.
                continue

            base = mechanics.calc_toon_damage(
                action.track, action.level,
                organic=toon.is_organic(action.track))
            # Damage instances in source order: gag damage, then hpBonus
            # (always 0 solo), then kbBonus (Throw/Squirt on a lured cog).
            total = (base
                     + mechanics.calc_hp_bonus(base)
                     + mechanics.calc_kb_bonus(action.track,
                                               cog.status.lured, base))
            # Source damage is float; HP here is an int, so floor. Only
            # bites when kbBonus lands on an odd base damage.
            dmg = int(total)
            cog.hp -= dmg
            dealt += dmg
            if cog.hp <= 0:
                cog.status.is_dead = True
                cog.status.clear_lure()
            elif action.track == Track.SOUND and cog.status.lured:
                # [CONFIRMED] TTR wiki: "Lured Cogs are awakened by Sound
                # gags without a damage bonus." Sound is the one track the
                # wiki names explicitly, which is why it's handled here and
                # not as a blanket damage-ends-lure rule -- see
                # mechanics.LURE_ENDS_ON_DAMAGE for the still-open question
                # of whether Throw/Squirt knock a cog out of lure too.
                cog.status.clear_lure()

    return healed, dealt


def _resolve_toon_action(state: BattleState, action: Action) -> Tuple[BattleState, int, int]:
    """Roll the gag's hit and apply it. Returns (state, healed, dealt)."""
    hit = mechanics.roll_hit(toon_action_accuracy(state, action))
    healed, dealt = apply_toon_action(state, action, hit)
    return state, healed, dealt


def _tick_lure(cog: CogState) -> bool:
    """Resolve one round of lure on a lured cog. Returns True if the lure
    ended (so the cog attacks this same round), False if it holds.

    Source order, both [CONFIRMED]:
      1. `__updateLureTimeouts()` -- the round counter runs out, lure ends.
      2. the wake-up roll, itself gated on that counter still being > 0:
         `__suitIsLured(...) and currentlyLuredSuits[suitId][0] > 0
          and random.randint(0, 99) < wakeupChance`

    lure_rounds_remaining counts cog phases the cog skips, so a lure of N
    rounds set this round makes the cog miss this round and the next N-1.
    The exact off-by-one against the source can't be pinned down while the
    per-level durations are [TODO] -- see mechanics.lure_duration_rounds.
    """
    status = cog.status
    if status.lure_rounds_remaining <= 0:
        status.clear_lure()
        return True
    if status.lure_acc_before_bonus is None:
        raise ValueError(
            "Lured cog has no lure_acc_before_bonus -- wakeupChance can't "
            "be computed. Set it (via CogStatus.apply_lure) whenever you "
            "mark a cog lured."
        )
    # [CONFIRMED] TTR 3.3.0: a Lure gag whose BASE accuracy is under 50%
    # is the only kind that can still expire early -- and no TTR gag is,
    # so in practice this roll never happens and a lure runs its full
    # duration. Kept as a rule rather than deleted; it's a balance knob.
    if (mechanics.lure_can_expire_early(status.lure_level)
            and mechanics.lure_wakes_up(status.lure_acc_before_bonus)):
        status.clear_lure()
        return True
    status.lure_rounds_remaining -= 1
    return False


def _resolve_cog_phase(state: BattleState) -> int:
    """Returns total damage dealt to the toon this round."""
    total_dmg = 0
    for cog in state.active_cogs():
        if cog.status.lured and not _tick_lure(cog):
            continue    # lure held: cog skips its attack

        attack_name = mechanics.pick_cog_attack(cog)
        dmg, acc = mechanics.cog_attack_damage_and_accuracy(cog, attack_name)
        if mechanics.roll_hit(acc):
            total_dmg += dmg
    return total_dmg


def step(state: BattleState, action: Action, gag_cost_lambda=None,
         objective=None) -> Tuple[BattleState, float, bool]:
    """Sample one round, and score it exactly as the search would.

    The reward is delegated to the objective rather than recomputed
    here, because it was recomputed here and the two drifted. This
    function and `outcomes.action_outcomes` are meant to price a round
    identically -- that is what lets a sampled rollout be compared with
    a searched line -- and keeping that true by writing the same
    arithmetic in two places lasted exactly as long as nobody changed
    an objective. Adding a scarcity term to the balanced preset broke
    it immediately.

    `gag_cost_lambda` is the old positional float and still works: it
    builds an objective with that gag cost and nothing else, which is
    what it always meant.
    """
    from .search import objective as objective_mod

    if objective is None:
        if gag_cost_lambda is None:
            objective = objective_mod.DEFAULT
        else:
            objective = objective_mod.Objective(
                gag_cost=float(gag_cost_lambda))
    next_state = state.clone()

    _, healed, dealt = _resolve_toon_action(next_state, action)

    laff_lost = 0
    if not next_state.is_terminal():
        laff_lost = _resolve_cog_phase(next_state)
        next_state.toon.laff = max(0, min(next_state.toon.max_laff,
                                            next_state.toon.laff + healed - laff_lost))

    next_state.round_num += 1

    # One implementation of what a round is worth, shared with
    # outcomes._accumulate. A terminal state that is not a win is a
    # loss, which includes running out of ways to damage a cog and not
    # only running out of laff.
    reward = objective.step_reward(
        laff_lost, action.track, action.level,
        won=next_state.is_win(),
        lost=next_state.is_terminal() and not next_state.is_win())

    return next_state, reward, next_state.is_terminal()
