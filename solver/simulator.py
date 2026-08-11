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
        return level in data.GAG_GROUP_LEVELS[Track.TOON_UP]
    if track == Track.LURE:
        # [CONFIRMED] TTR wiki: Small Magnet (2), Big Magnet (4),
        # Hypno-goggles (6) and Presentation (7) all hit every cog. Only
        # the dollar-bill gags at 1/3/5 are single-target. This used to say
        # `level == 7`, which made three group gags single-target.
        return level in data.LURE_GROUP_LEVELS
    if track in (Track.THROW, Track.SQUIRT, Track.DROP, Track.TRAP):
        return level == 7           # Wedding Cake / Geyser / Ocean Liner / Train Tracks
    return False


def legal_actions(state: BattleState) -> List[Action]:
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

    return actions


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
    entry = data.GAG_DAMAGE_MINMAX[Track.TRAP].get(cog.status.trap_level)
    if entry is None:
        raise NotImplementedError(
            f"Trap damage for level {cog.status.trap_level} is TODO in data/gags.py"
        )
    dmg = entry[0]  # trap damage is a fixed value once populated
    cog.status.trapped = False
    cog.status.trap_track = None
    cog.status.trap_level = None
    return dmg


def toon_action_accuracy(state: BattleState, action: Action) -> int:
    """The gag's hit chance, 0-100.

    Passes all_cogs (not just the targets) so the luredRatio half of `bonus`
    sees the whole battle -- its denominator is every cog in play.
    """
    return mechanics.calc_toon_accuracy(
        action.track, action.level, state.toon,
        _targets_for(state, action), all_cogs=state.cogs)


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
    targets = _targets_for(state, action)

    toon.gag_counts[(action.track, action.level)] -= 1

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
        cog = targets[0]
        cog.status.trapped = True
        cog.status.trap_track = action.track
        cog.status.trap_level = action.level

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

            base = mechanics.calc_toon_damage(action.track, action.level)
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


def step(state: BattleState, action: Action, gag_cost_lambda: float = 0.1
          ) -> Tuple[BattleState, float, bool]:
    next_state = state.clone()

    _, healed, dealt = _resolve_toon_action(next_state, action)

    laff_lost = 0
    if not next_state.is_terminal():
        laff_lost = _resolve_cog_phase(next_state)
        next_state.toon.laff = max(0, min(next_state.toon.max_laff,
                                            next_state.toon.laff + healed - laff_lost))

    next_state.round_num += 1

    reward = -float(laff_lost) - gag_cost_lambda * float(action.level)
    if next_state.is_win():
        reward += 100.0
    elif next_state.toon.laff <= 0:
        reward -= 100.0

    return next_state, reward, next_state.is_terminal()
