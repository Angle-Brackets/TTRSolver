"""
The actual (state, action) -> (next_state, reward, done) transition,
i.e. what an expectimax / value-iteration / RL solver would call.

Round resolution order (solo toon, so this is simpler than the full
multi-toon initiative rules in mechanics.py's docstring):
  1. Toon acts (one Action).
  2. Any status effects that action triggers resolve (trap set, trap
     triggered by lure, cog death, cog lured).
  3. Each surviving, non-lured cog attacks (lured cogs roll a wake-up
     check first; if they wake, they attack this round too).
  4. Reward is computed, round counter increments.
"""
import copy
from typing import List, Tuple

from . import data
from . import mechanics
from .state import BattleState, CogState, Action, Track


def is_group_action(track: Track, level: int) -> bool:
    if track in (Track.TOON_UP, Track.SOUND):
        return True
    if track == Track.LURE:
        return level == 7           # Presentation hits all cogs
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
    return damage dealt."""
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


def _resolve_toon_action(state: BattleState, action: Action) -> Tuple[BattleState, int, int]:
    """Returns (state, laff_healed, damage_dealt_total) -- mutates state in place."""
    toon = state.toon
    targets = _targets_for(state, action)

    acc = mechanics.calc_toon_accuracy(action.track, action.level, toon, targets)
    hit = mechanics.roll_hit(acc)

    toon.gag_counts[(action.track, action.level)] -= 1

    healed = 0
    dealt = 0

    if not hit:
        return state, healed, dealt

    if action.track == Track.TOON_UP:
        # Heal table not yet transcribed -- see docs/data-confidence.md.
        raise NotImplementedError("Toon-Up heal amounts are TODO in data/")

    elif action.track == Track.TRAP:
        cog = targets[0]
        cog.status.trapped = True
        cog.status.trap_track = action.track
        cog.status.trap_level = action.level

    elif action.track == Track.LURE:
        for cog in targets:
            if cog.status.trapped:
                dmg = _apply_trap_trigger(cog)
                cog.hp -= dmg
                dealt += dmg
                if cog.hp <= 0:
                    cog.status.is_dead = True
                    continue
            cog.status.lured = True
            # wakeupChance uses the pre-bonus accuracy value; recomputed
            # per-round in the cog phase below via lure_wakeup_chance().

    else:  # SOUND, THROW, SQUIRT, DROP -- direct damage
        for cog in targets:
            dmg = mechanics.calc_toon_damage(action.track, action.level)
            cog.hp -= dmg
            dealt += dmg
            if cog.hp <= 0:
                cog.status.is_dead = True

    return state, healed, dealt


def _resolve_cog_phase(state: BattleState) -> int:
    """Returns total damage dealt to the toon this round."""
    total_dmg = 0
    for cog in state.active_cogs():
        if cog.status.lured:
            # Recompute the pre-bonus accuracy this cog's Lure was hit
            # with -- not separately stored yet, so this is a known gap;
            # see docs/roadmap.md item 2. For now, treat lured cogs as
            # skipping their attack unconditionally (wakeupChance unapplied).
            continue

        attack_name = mechanics.pick_cog_attack(cog)
        dmg, acc = mechanics.cog_attack_damage_and_accuracy(cog, attack_name)
        if mechanics.roll_hit(acc):
            total_dmg += dmg
    return total_dmg


def step(state: BattleState, action: Action, gag_cost_lambda: float = 0.1
          ) -> Tuple[BattleState, float, bool]:
    next_state = copy.deepcopy(state)

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
