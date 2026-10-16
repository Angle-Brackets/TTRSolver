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
import random
from typing import Dict, List, Optional, Sequence, Tuple

from . import sos as sos_mod
from . import data
from . import facility
from . import mechanics
from . import state as state_mod
from .search import objective as objective_mod
from .state import (
    ATTACK_ORDER, BattleState, CogState, Action, Track,
)

# `facility` and `search.objective` are imported at module level rather
# than inside `step`: both depend only on `data` and `state`, so neither
# is a cycle, and a function-local `from . import x` re-imports on every
# call -- 11,670 import calls in a 6,000-step solo rollout. See
# `party.py` for the two imports that genuinely are cycles and must stay
# local.


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

    WHEN PASS IS OFFERED: always, while `state.free_passes` lasts.
    Passing is an ordinary choice -- conserve a scarce gag, or in a
    party decline to hit a cog because `mechanics.pick_cog_target`
    prefers whoever damaged it most, so attacking draws its next swing
    onto you.

    A LURED PASS COSTS NOTHING OFF THE BUDGET, because a lured cog does
    not attack, so the lure timer itself is the descending quantity. The
    move this exists for: trap and lure left, cogs already lured. Trap
    can't land on a lured cog, so the only gag action is to burn a Lure
    re-luring a cog that's already lured; waiting for the lure to lapse,
    then trapping and re-luring, wins fights that would otherwise run
    the pouch dry (tests/test_pass.py plays one out).

    AN UNLURED PASS DOES DRAW ON `state.free_passes`, a TERMINATION
    GUARD rather than a strategic limit (it starts at 3, where exact
    solve's cost stopped rising with it). It can't be unbounded: `solve()`
    terminates on the lexicographic measure (gags remaining, lure rounds
    remaining, free passes) strictly decreasing every round, and an
    unlured pass that missed everything would otherwise leave a state
    identical to its parent, making the search recurse forever.
    """
    actions = []
    toon = state.toon
    active = state.active_cogs()
    if not active:
        return actions
    if not state.can_still_damage():
        # No way left to hurt a cog, so the battle is already lost --
        # `state.is_terminal()` says so. Offering a pass here would let
        # a search "avoid" the loss by waiting forever in a position it
        # cannot win. Trap-plus-Lure is NOT this case: `can_still_damage`
        # knows a trap springs when a lure lands.
        return actions

    # PINK SLIPS, one per live cog. Offered before gags since they're
    # unconditional: no accuracy, no track, no interaction with lure or
    # trap. Finite and strictly decreasing, so they don't threaten the
    # termination argument above.
    for i, cog in enumerate(state.cogs):
        if toon.fires > 0 and not cog.status.is_dead:
            actions.append(Action(track=None, target_index=i, fire=True))

    # SOS TOONS, offered only when held. An SOS costs the turn, so it's
    # an ordinary action beside the gags, and finite and strictly
    # decreasing like a pink slip.
    for name in getattr(toon, "sos_cards", {}):
        held = toon.sos_held(name)
        # `name in BY_NAME` is not paranoia: the live readers build
        # `sos_cards` from what the game sends, and an unknown name would
        # otherwise be offered here and raise in `apply_toon_action` --
        # a crash in the search rather than a card politely not offered.
        # `hybrid._sos_probes` filters the same way; the two must agree.
        if held > 0 and name in sos_mod.BY_NAME:
            actions.append(Action(track=None, sos=name))

    for (track, level), count in toon.gag_counts.items():
        if count <= 0:
            continue
        if toon.track_exp.get(track, 0) <= 0:
            continue  # toon doesn't own this track
        # Read at call time so a caller can toggle it between runs.
        # `state.can_still_damage` applies the same rule; the two must
        # agree or a toon holding only 7s reads as able to fight and has
        # nothing legal to throw.
        if not state_mod.ALLOW_LEVEL_7 and level == state_mod.LEVEL_SEVEN:
            continue

        if is_group_action(track, level):
            if track == Track.TRAP and all(
                    c.status.lured for c in state.cogs if not c.status.is_dead):
                # [CONFIRMED] by the owner: a Railroad needs ONE unlured cog
                # to go down; with every cog lured it cannot be placed
                # (it was offered live over a lone lured cog).
                continue
            actions.append(Action(track=track, level=level, target_index=None))
            continue

        if track == Track.TOON_UP:
            # Toon-Up's target_index names a TOON, not a cog.
            #
            # [CONFIRMED] TTR wiki: a toon cannot heal themselves, so
            # the actor is excluded.
            for i, other in enumerate(state.toons):
                if i == 0 or other.laff <= 0:
                    continue
                if other.laff >= other.max_laff:
                    continue          # nothing to restore
                actions.append(Action(track=track, level=level,
                                      target_index=i))
            continue

        for i, cog in enumerate(state.cogs):
            if cog.status.is_dead:
                continue
            if track == Track.TRAP:
                if cog.status.trapped or cog.status.lured:
                    continue  # can't trap an already-trapped or lured cog
            actions.append(Action(track=track, level=level, target_index=i))

    # Drop moves that provably do nothing -- e.g. re-luring an
    # already-lured cog (refreshes a timer, buys nothing) or Drop on a
    # lured one (always misses). See `is_productive`.
    productive = [a for a in actions if is_productive(state, a)]
    if productive:
        actions = productive

    # PASS, offered whenever a cog is lured (that's how lure rounds get
    # burned, at no cost to the budget since the lure timer is already
    # descending) and otherwise while `free_passes` lasts.
    #
    # `solve()`'s depth budget must count `free_passes` as well as gags,
    # or a pass-including search truncates early and its leaves fall
    # through to `heuristic_value` -- checked over 93 random positions,
    # with the wider rule never scoring lower (more options cannot hurt)
    # and six positions scoring genuinely higher, one by 131 points.
    if any(cog.status.lured for cog in active) or state.free_passes > 0:
        actions.append(Action(track=None, level=0, target_index=None))

    return actions


def wasted_reach(state: BattleState, action: Action) -> float:
    """Share of the live cogs a group gag or SOS card cannot reach.

    [OWNER] "a waste": Barnacle Bessie with two of four cogs lured drops
    two pianos on nothing. Every engine already sees what the card DOES;
    this prices what it throws away, so a card that clears two cogs is
    not rated as if its other two pianos were free. A preference, the
    same kind as `Objective.sos_cost`, charged by all three engines.

        reaches nothing on   group Drop / Bessie-type cards: lured cogs
                             group Lure / lure cards: cogs already lured
                             group Trap / trap cards: cogs already trapped
        undoes a lure on     group Trap / trap cards: lured cogs, which
                             it wakes ([OWNER] "a penalty for unluring")

    Every hit-all, gag or card alike. Not Sound or Moe Zart waking a
    lured cog: they still land on it, which a Drop does not.

    A HEAL CARD wastes the laff it cannot restore: the share of its total
    that overflows the toons' max laff. Seen live on Realms: Flippy (180)
    called at 92/100 with every cog lured -- 172 of 180 wasted. The
    playouts charge nothing for a call, so a heal there was a free way to
    wait a round, the pass a lone toon's menu no longer offers.
    """
    live = [c for c in state.cogs if not c.status.is_dead]
    if not live or action is None:
        return 0.0
    if getattr(action, "sos", None):
        card = sos_mod.BY_NAME.get(action.sos)
        kind = getattr(card, "kind", None)
        if kind == sos_mod.HEAL:
            toons = [t for t in state.toons if t.laff > 0]
            share = sos_mod.heal_share(card, len(toons))
            overflow = sum(max(0, share - (int(t.max_laff) - int(t.laff)))
                           for t in toons)
            return min(1.0, overflow / float(card.amount)) if card.amount else 0.0
        if kind == sos_mod.RESTOCK:
            return _restock_waste(state, card)
        shape = {sos_mod.DAMAGE_UNLURED: Track.DROP, sos_mod.LURE: Track.LURE,
                 sos_mod.TRAP: Track.TRAP}.get(kind)
    elif (action.track is not None and action.target_index is None
          and not action.fire and is_group_action(action.track, action.level)):
        shape = action.track
    else:
        return 0.0
    if shape == Track.DROP:
        missed = sum(1 for c in live if c.status.lured)
    elif shape == Track.LURE:
        missed = sum(1 for c in live if c.status.lured)
    elif shape == Track.TRAP:
        missed = sum(1 for c in live if c.status.trapped or c.status.lured)
    else:
        return 0.0
    return missed / float(len(live))


def _restock_waste(state: BattleState, card) -> float:
    """Share of a restock card's gags that cannot fit in the pouches.

    [OWNER] "a bad play": Professor Pete (45 gags, every track) called at
    73/80 adds 7 and throws 38 away. Dry-run on COPIED pouches -- `clone`
    shares the gag dicts, and a restock writes into them.
    """
    toons = [t for t in state.toons if t.laff > 0]
    if not toons or not card.amount:
        return 0.0
    probe = state.clone()
    for toon in probe.toons:
        toon.gag_counts = dict(toon.gag_counts)
    try:
        added = sos_mod.apply(card, probe).get("restocked", 0)
    except Exception:                      # noqa: BLE001
        return 0.0
    capacity = card.amount * len(toons)
    return max(0.0, min(1.0, 1.0 - added / float(capacity)))


def is_productive(state: BattleState, action: Action) -> bool:
    """Does this action advance the battle at all?

    Only used to decide whether the toon is stuck and should be offered
    a pass, so "no" needs to mean *nothing whatsoever*, not "poor
    value". Choosing between productive moves is the search's job.
    """
    if action.is_pass:
        return False
    if action.track == Track.TOON_UP:
        # [CONFIRMED] TTR wiki (Toon-Up): "Toons cannot use Toon-Up gags
        # to restore their own laff." So a heal is productive only when
        # somebody ELSE is hurt -- and solo it is never productive at
        # all, because there is nobody else in the battle.
        return any(other.laff < other.max_laff and other.laff > 0
                   for i, other in enumerate(state.toons) if i != 0)
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
    if action.track == Track.TRAP:
        # A Trap goes down only in front of an unlured cog -- a Railroad
        # needs one to be placed at all.
        return any(not cog.status.lured for cog in targets)
    # The damage tracks damage something.
    return bool(targets)


def _targets_for(state: BattleState, action: Action) -> List[CogState]:
    if action.track == Track.TOON_UP:
        # A heal has no cog target. `target_index` names a TOON for this
        # track, so indexing `cogs` with it was wrong twice over: it read
        # the wrong list, and raised IndexError as soon as the party was
        # larger than the number of cogs. Who gets healed is decided in
        # `_apply_track_group`.
        return []
    if action.target_index is not None:
        return [state.cogs[action.target_index]]
    return state.active_cogs()


def _apply_trap_trigger(cog: CogState) -> int:
    """Cog was lured onto its own trap: detonate it, clear trap status,
    return damage dealt.

    Ordering [CONFIRMED]: within a round, attacks resolve Toon-up -> Trap
    -> Lure -> Sound -> Throw -> Squirt -> Drop, so a Trap laid in the
    same round is already on the ground when the Lure resolves.

    A trapped cog that is DAMAGED rather than lured keeps its trap: the
    guide describes Trap as persisting until a Lure moves the cog onto
    it, with no rule for damage clearing a trap. (Nor is re-trapping
    possible -- legal_actions blocks trapping an already trapped or
    lured cog, [CONFIRMED].)"""
    # trained_fraction 1.0, matching mechanics.calc_toon_damage's default
    # and every other track -- NOT the minimum of the range, which no
    # other gag uses as its resolution point.
    if cog.status.trap_damage is not None:
        # An SOS trap carries its OWN damage: `Clerk Will` and friends
        # place a named trap gag at SOS-tier numbers (60/120/180 against
        # the gags' own 50/85/180), which a level can't express. Checked
        # before the level so the card wins where both are somehow set.
        dmg = int(cog.status.trap_damage)
    else:
        dmg = data.gag(Track.TRAP, cog.status.trap_level).damage_at(
            1.0, organic=cog.status.trap_organic)
    cog.status.trapped = False
    cog.status.trap_damage = None
    cog.status.trap_track = None
    cog.status.trap_level = None
    cog.status.trap_organic = False
    return dmg


def toon_action_accuracy(state: BattleState, action: Action,
                         actor: int = 0) -> int:
    """The gag's hit chance, 0-100, for the toon THROWING it.

    Passes all_cogs (not just the targets) so the luredRatio half of `bonus`
    sees the whole battle -- its denominator is every cog in play.

    A pass always "hits": it has one outcome, so the search should not
    split a chance node over it.

    `actor` indexes `state.toons`, defaulting to 0 for solo play. A party
    round must pass it explicitly: accuracy reads the thrower's TRAINING
    and whether the track is organic to THEM, both of which are per toon
    -- reading `state.toon` unconditionally would score every gag in a
    party round with toon 0's training, invisible on a maxed team but
    wrong for any mixed party.
    """
    if action.sos is not None:
        # [CONFIRMED] wiki: no SOS gag misses, since 2.6.7. The
        # situational failures -- Drop on a lured cog, a trap nothing
        # springs -- are handled where the effect is applied, not here.
        return 100
    if action.is_pass or action.fire:
        # A PINK SLIP CANNOT MISS, and it needs its own arm here rather
        # than riding on the pass guard: a fire has `track=None` too,
        # but `is_pass` is False for it by definition, so it fell
        # through to `calc_toon_accuracy(None, 0, ...)` and raised
        # `KeyError: no gag at no track (a pass) level 0`.
        #
        # That was not a cosmetic gap. `outcomes.action_outcomes` asks
        # for this before it looks at what the action is, so EXACT
        # SEARCH RAISED on any position where the toon held a slip --
        # `legal_actions` offers one fire per live cog, so the very
        # first branch it expanded was a fire. Anyone carrying slips
        # into the panel's search engine hit it.
        return 100
    toon = state.toons[actor]
    return mechanics.calc_toon_accuracy(
        action.track, action.level, toon,
        _targets_for(state, action), all_cogs=state.cogs,
        lure_tree_planted=toon.is_organic(action.track, action.level),
        toons_hit=sos_mod.active(state, "toons_hit_rounds"),
        toons_always_hit=state.sos_one_round)


def apply_toon_action(state: BattleState, action: Action,
                       hit: bool, actor: int = 0) -> Tuple[int, int]:
    """Apply the toon's action given a known hit/miss, mutating `state`.
    Returns (laff_healed, damage_dealt_total).

    Deterministic on purpose: this is the single implementation of the
    toon-phase rules, shared by `_resolve_toon_action` (which rolls the
    dice) and `outcomes.action_outcomes` (which enumerates both branches).
    Anything added here reaches the solver automatically -- don't fork it.
    """
    # `actor` indexes state.toons. It defaults to 0, which is the whole
    # of solo play, but a party round has to name whose gag this is --
    # spending it from the wrong pouch is silent and wrong.
    toon = state.toons[actor]
    if action.is_pass:
        # Nothing spent, nothing dealt. The round still happens -- the
        # caller runs the cog phase, which is how passing while lured
        # burns lure rounds.
        #
        # An UNLURED pass spends a unit of `free_passes` instead, to
        # keep the termination measure descending (it ticks no lure and
        # costs no gag otherwise). A lured pass is free here because the
        # lure timer is already the quantity going down.
        if not any(cog.status.lured for cog in state.active_cogs()):
            state.free_passes = max(0, state.free_passes - 1)
        return 0, 0

    if action.sos is not None:
        # An SOS Toon answers the call: spends the card and the turn,
        # cannot miss, and resolves at once except for Trap, which
        # places something a later Lure collects.
        from . import sos as sos_mod

        held = toon.sos_held(action.sos)
        if held <= 0:
            raise KeyError(
                f"toon was told to call {action.sos} and holds none -- "
                f"the plan cannot be played")
        cards = dict(toon.sos_cards)
        cards[action.sos] = toon.sos_cards[action.sos] - 1
        toon.sos_cards = cards
        if toon.sos_calls is not None:
            toon.sos_calls -= 1
        did = sos_mod.apply(sos_mod.BY_NAME[action.sos], state)
        # Reported as (laff healed, 0 damage): every scorer reads this
        # tuple's second element as damage dealt by the TOON, and an SOS
        # that healed or lured dealt none. Laff healed DOES matter --
        # `_restored` weights a heal by the toon's headroom (17 into a
        # full toon, 125 into a dying one), so it must be reported, not
        # folded into "damage" or dropped.
        return int(did.get("healed", 0)), 0

    if action.fire:
        # A pink slip removes the cog from the battle. It cannot miss, so
        # `hit` is not consulted, and it spends the toon's action for the
        # round exactly as a gag would.
        #
        # Reported as 0 damage rather than the cog's remaining hp: every
        # scorer reads the return value as damage dealt, and crediting a
        # fire as damage would make it look like the biggest hit in the
        # game to an evaluator that already struggles to price a kill.
        index = action.target_index
        if index is None or not (0 <= index < len(state.cogs)):
            return 0, 0
        cog = state.cogs[index]
        if cog.status.is_dead:
            return 0, 0
        if toon.fires <= 0:
            raise ValueError("no pink slip to spend")
        toon.fires -= 1
        # [CONFIRMED] wiki: a pink slip eliminates BOTH layers of a
        # Version 2.0 -- the suit and the Skelecog form -- so a fired
        # v2.0 leaves nothing, and clearing `suited` here also keeps
        # dead cogs from splitting the memo key on a flag that no
        # longer matters.
        cog.hp = 0
        cog.status.is_dead = True
        cog.status.lured = False
        cog.status.trapped = False
        cog.status.suited = False
        return 0, 0

    targets = _targets_for(state, action)

    # Copy-on-write. `BattleState.clone` shares this dict rather than
    # copying it, because a clone happens once per outcome branch -- tens
    # of times per action -- while the counts change exactly once, here.
    # Copying at the point of change instead turns ~55 dict copies per
    # action into one. This is the ONLY place gag_counts is mutated; if
    # that ever stops being true, every sibling state silently shares the
    # edit. tests/test_state.py pins the invariant.
    _spend_gag(toon, action.track, action.level)

    healed = 0
    dealt = 0

    if action.track == Track.TOON_UP:
        # [CONFIRMED] TTR wiki: "Toon-Up gags do not necessarily miss, but
        # rather, provide 20% of original values that are rounded up." So
        # a missed Toon-Up still heals -- the one track where a miss
        # isn't a no-op, which is why this sits above `if not hit`.
        #
        # But it heals SOMEBODY ELSE: [CONFIRMED] wiki, "Toons cannot use
        # Toon-Up gags to restore their own laff". This path is solo,
        # where there's nobody else, so the gag is spent and heals
        # nothing.
        return 0, dealt

    if not hit:
        return healed, dealt

    if action.track == Track.TRAP:
        # Every target, not just the first: Railroad is a group gag that
        # lays a trap in front of all of them.
        #
        # An existing trap is overwritten -- [CONFIRMED] TTR 3.0.0, "if
        # there are active Trap gags on Cogs, and a Railroad gag is placed
        # in a subsequent round by itself, it will override the previously
        # placed Trap gags rather than fizzling out".
        #
        # THE RAILROAD WAKES THE FIELD TO LAY ITSELF. [CONFIRMED] by the
        # owner from play: a group Trap needs ONE unlured cog to go down,
        # and placing it un-lures every lured cog so the track is laid
        # under all of them. With every cog lured it cannot be placed --
        # `legal_actions` does not offer it. A single-target Trap cannot
        # do this and is refused on a lured cog.
        #
        # That is what makes Railroad-then-Lure work IN ONE ROUND: Trap
        # resolves before Lure, the Railroad wakes and arms the field,
        # and the Lure lands afterwards and springs it.
        group = data.gag(action.track, action.level).group
        if group and not all(c.status.lured for c in targets):
            for cog in targets:
                cog.status.clear_lure()
        for cog in targets:
            if cog.status.lured:
                continue          # single-target Trap, cog off its square
            cog.status.trapped = True
            cog.status.trap_track = action.track
            cog.status.trap_level = action.level
            cog.status.trap_organic = toon.is_organic(action.track, action.level)

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
                dealt += cog.take_damage(dmg)
                # THE TRAP KNOCKS IT OUT OF THE LURE. [CONFIRMED] by the
                # owner: "If you lure a cog onto a trap, the cog becomes
                # unlured after taking damage." Springing a trap SPENDS
                # the lure -- the trade is the trap's damage for the
                # rounds the cog would have spent asleep -- so pricing
                # Trap can't be just P(spring) x damage; the lure given
                # up is part of the cost.
                continue
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
                organic=toon.is_organic(action.track, action.level))
            # Damage instances in source order: gag damage, then hpBonus
            # (always 0 solo), then kbBonus (Throw/Squirt on a lured cog).
            total = (base
                     + mechanics.calc_hp_bonus(base)
                     + mechanics.calc_kb_bonus(action.track,
                                               cog.status.lured, base))
            # Source damage is float; HP here is an int, so floor. Only
            # bites when kbBonus lands on an odd base damage.
            dmg = int(total)
            dealt += cog.take_damage(dmg)
            # The knockback is already in `total` above, and the lure
            # ends here: [CONFIRMED] by the owner, any landed attack of a
            # damage track wakes the cog (mechanics.LURE_ENDS_ON_DAMAGE).
            # A Throw collects its +50% against the sleeping cog, and
            # only then does the cog wake and (if it survived) attack.
            if cog.status.is_dead or action.track in mechanics.DAMAGE_TRACKS:
                cog.status.clear_lure()

    return healed, dealt


def _resolve_toon_action(state: BattleState, action: Action) -> Tuple[BattleState, int, int]:
    """Roll the gag's hit and apply it. Returns (state, healed, dealt)."""
    hit = mechanics.roll_hit(toon_action_accuracy(state, action))
    healed, dealt = apply_toon_action(state, action, hit)
    return state, healed, dealt


def _tick_lure(cog: CogState, rng=random) -> bool:
    """Resolve one round of lure on a lured cog. Returns True if the lure
    ended (so the cog attacks this same round), False if it holds.

    Source order, both [CONFIRMED]:
      1. `__updateLureTimeouts()` -- the round counter runs out, lure ends.
      2. the wake-up roll, itself gated on that counter still being > 0:
         `__suitIsLured(...) and currentlyLuredSuits[suitId][0] > 0
          and random.randint(0, 99) < wakeupChance`

    lure_rounds_remaining counts cog phases the cog skips, so a lure of N
    rounds set this round makes the cog miss this round and the next N-1.

    THE OFF-BY-ONE IS SETTLED (`mechanics.lure_duration_rounds` is
    [CONFIRMED] against the wiki), measured two ways, agreeing: calling
    this function on a lured board skips exactly the table value of cog
    phases per gag (Big Magnet 3, Hypno-goggles 4, Presentation 8); and a
    recorded solo VP with Hypno-goggles on four cogs held laff flat for
    four consecutive rounds and dropped on the fifth, matching.

    **The in-game tooltip numbers are one higher and must not be
    copied** ("Rounds: 5" for Hypno-goggles, 4 for Big Magnet, 9 for
    Presentation) -- the tooltip counts the round the lure is thrown in,
    which the cog wouldn't have attacked in anyway; the in-battle badge
    does not count that round and matches this table.
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
            and mechanics.lure_wakes_up(status.lure_acc_before_bonus, rng)):
        status.clear_lure()
        return True
    status.lure_rounds_remaining -= 1
    return False


def cogs_miss_factor(state: BattleState) -> float:
    """This round's multiplier on cog accuracy, and tick the SOS timers.

    Call ONCE per round, at the cog phase -- solo and party both, which
    is why it is one function: the party phase once skipped it, so Cogs
    Miss did nothing in a group and Toons Hit never ran out.
    """
    # COGS MISS. [CONFIRMED] wiki: an SOS reduces cog attack accuracy by
    # 75% for 3-5 rounds. Applied as a multiplier on the roll rather
    # than a subtraction, since "by 75%" is a reduction OF the accuracy,
    # not 75 points off it -- a 90% attack becomes 22.5%, not 15%.
    miss_factor = (1.0 - sos_mod.ACCURACY_SWING / 100.0
                   if sos_mod.active(state, "cogs_miss_rounds") else 1.0)
    if state.sos_one_round and miss_factor < 1.0:
        miss_factor = 0.0     # Realms: every cog misses
    # The SOS effects run down with the round, like a lure. Ticked
    # here, once, alongside the lure timers -- the cog phase is the one
    # place every round passes through exactly once.
    if state.toons_hit_rounds > 0:
        state.toons_hit_rounds -= 1
    if state.cogs_miss_rounds > 0:
        state.cogs_miss_rounds -= 1
    return miss_factor


def _resolve_cog_phase(state: BattleState) -> int:
    """Returns total damage dealt to the toon this round."""
    total_dmg = 0
    miss_factor = cogs_miss_factor(state)

    for cog in state.active_cogs():
        if cog.status.lured and not _tick_lure(cog):
            continue    # lure held: cog skips its attack

        attack_name = mechanics.pick_cog_attack(cog)
        dmg, acc = mechanics.cog_attack_damage_and_accuracy(cog, attack_name)
        acc = int(round(acc * miss_factor))
        if not mechanics.roll_hit(acc):
            continue
        # Teammates give a single-target attack somewhere else to land.
        # A group attack hits everyone, so it is never diluted -- see
        # `outcomes._damage_distribution_shared`, which this has to
        # agree with or a sampled rollout stops being comparable with a
        # searched line.
        if state.allies_standing and not data.is_group_attack(attack_name):
            if random.random() >= state.your_target_share():
                continue
        total_dmg += dmg
    return total_dmg


def step(state: BattleState, action: Action, gag_cost_lambda=None,
         objective=None) -> Tuple[BattleState, float, bool]:
    """Sample one round, and score it exactly as the search would.

    The reward is delegated to the objective rather than recomputed here:
    this function and `outcomes.action_outcomes` must price a round
    identically so a sampled rollout can be compared with a searched
    line, and writing the same arithmetic twice let them drift the first
    time an objective changed.

    `gag_cost_lambda` is the old positional float and still works: it
    builds an objective with that gag cost and nothing else.
    """
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
        # Heal FIRST and cap it, THEN take the damage. Not one combined
        # clamp -- `min(max_laff, laff + healed - lost)` lets a heal on a
        # toon already at full laff absorb the round's damage, turning
        # Toon-Up into damage prevention it is not. Toon-Up is first in
        # ATTACK_ORDER, so it resolves in the toon phase and its excess
        # is gone before a cog swings.
        toon = next_state.toon
        toon.laff = min(toon.max_laff, toon.laff + healed)
        toon.laff = max(0, toon.laff - laff_lost)

    next_state.round_num += 1

    # The unite cooldown, for the same reason `party.step` ticks it --
    # see the note there. Nothing decremented it anywhere, so a toon got
    # one unite per battle however many it held.
    from . import unites as unites_mod

    for toon in next_state.toons:
        unites_mod.tick_cooldown(toon)

    # Same reinforcement rule as the party path; see the note in
    # `apply_party_round`.
    facility.reinforce(next_state)

    # One implementation of what a round is worth, shared with
    # outcomes._accumulate. A terminal state that is not a win is a
    # loss, which includes running out of ways to damage a cog and not
    # only running out of laff.
    reward = objective.step_reward(
        laff_lost, action.track, action.level,
        won=next_state.is_win(),
        lost=next_state.is_terminal() and not next_state.is_win())

    return next_state, reward, next_state.is_terminal()


# ---------------------------------------------------------------------
# Party rounds
# ---------------------------------------------------------------------

def _prev_hits_apply(prev_group: bool, prev_targets, this_group: bool,
                     this_targets) -> bool:
    """Whether an earlier hit this round feeds this attack's stun bonus.

    [CONFIRMED] TTR wiki (Accuracy#PrevHits). Both main conditions are
    the caller's (the previous attack hit, and was a different track);
    this is the sub-condition, of which any one suffices: the previous
    attack affected the group, the current one does, or the two share a
    target.
    """
    if prev_group or this_group:
        return True
    return bool(set(prev_targets) & set(this_targets))


def _spend_gag(toon, track, level) -> None:
    """Take one gag out of the pouch, raising if it isn't there.

    A pouch holds explicit zeroes -- `{(SQUIRT, 7): 0}` is ordinary for a
    toon who has used them all -- so this must check the count rather
    than decrementing blindly, or a zero count goes quietly to -1 and
    deals full damage.

    Nothing in normal play reaches the raise: `legal_actions` only offers
    a gag with a positive count. It's hand-built plans that get here, and
    KeyError is used (rather than a new type) because every caller that
    scores a speculative plan already catches it.
    """
    counts = dict(toon.gag_counts)
    if counts.get((track, level), 0) <= 0:
        raise KeyError((track, level))
    counts[(track, level)] -= 1
    toon.gag_counts = counts


def _check_pouches(state: BattleState,
                   actions: Sequence[Optional[Action]]) -> None:
    """Refuse a party plan that spends a gag somebody does not hold,
    BEFORE any of the round is applied.

    Every non-pass, non-fire action in a party round spends exactly one
    gag, so the plan can be priced against the pouches without
    simulating anything.

    Checked here rather than left to `_spend_gag`, which fires mid-round
    (tracks resolve one at a time in ATTACK_ORDER): by then earlier
    tracks have already mutated `state`, and the raise names a gag and
    level but not which seat or plan was at fault. Checking first makes
    the refusal atomic and able to name the seat.

    A plan that respects `legal_actions`/`rl.env.legal_mask` cannot reach
    this raise -- it exists for hand-built or buggy plans that bypass
    the mask (e.g. a driver that fed a nonexistent GROUP Toon-Up to every
    seat). KeyError, not a new exception type, for the reason
    `_spend_gag` gives.

    Counted per toon BY IDENTITY, so two seats holding the same
    `ToonState` object are charged one gag each rather than both reading
    the same pre-round count.
    """
    wanted: Dict[Tuple[int, Track, int], int] = {}
    for index, action in enumerate(actions):
        if action is None or action.is_pass or action.fire:
            continue
        if action.sos is not None:
            # Spends a CARD, not a gag. Without this it is read as a gag
            # with a null track that the toon holds none of, and the
            # round is refused before it starts.
            continue
        # Indexes `state.toons` exactly as the resolution below does, so
        # an over-long `actions` raises the same IndexError it always
        # did, only sooner.
        toon = state.toons[index]
        key = (id(toon), action.track, action.level)
        wanted[key] = wanted.get(key, 0) + 1
        held = toon.gag_counts.get((action.track, action.level), 0)
        if held < wanted[key]:
            raise KeyError(
                f"toon {index} was told to throw {action.track} level "
                f"{action.level} and holds {held} of them -- the plan "
                f"cannot be played"
            )


def apply_party_round(state: BattleState,
                      actions: Sequence[Optional[Action]],
                      hits: Optional[Sequence[bool]] = None,
                      rng=random,
                      record: Optional[List] = None) -> List[int]:
    """Resolve every toon's action for one round, in the game's order.

    `actions[i]` is `state.toons[i]`'s choice, or None to sit the round
    out. Returns the laff healed for each toon. Cog damage lands on the
    cogs in `state`.

    THIS IS WHERE A PARTY STOPS BEING FOUR SOLO TOONS. Three effects
    exist only here, each a reason the round can't be resolved by
    calling `apply_toon_action` four times:

    * Order. Gags resolve by track -- Toon-Up, Trap, Lure, Sound, Throw,
      Squirt, Drop -- not by who chose first. A Lure landing before a
      Throw is what makes the Throw a knockback.
    * Combos. Same-track gags on the same cog in the same round have
      their damage summed, THEN get `calc_hp_bonus` on the total -- four
      Throws at one cog are not four separately-bonused Throws.
    * Stun. A landed attack makes later attacks of a *different* track
      more accurate, via `calc_same_round_prev_hits`.

    Accuracy is rolled per attack at the moment it resolves, since the
    stun bonus depends on what already landed. Passing `hits` fixes the
    rolls instead, for an enumerating caller.

    `record`, if given, is appended with one `(track, key, accuracy)` per
    ROLL GROUP -- the shared die, not the gag -- carrying the accuracy
    actually resolved (stun and Lure bonus included), so a caller that
    fixes `hits` can know what that branch was worth without a second,
    possibly-drifting implementation of the same rule.
    """
    healed = [0 for _ in state.toons]

    # The whole plan is priced against the pouches before a single gag
    # lands -- see `_check_pouches` for why this is not left to the
    # per-track spends further down.
    _check_pouches(state, actions)

    # PINK SLIPS RESOLVE FIRST, before any gag: a fired cog is removed by
    # cannon, so it's gone before the round's gags land, wasting a
    # teammate's gag thrown at the same cog. [ASSUMED] ordering -- no
    # source states when in a round the cannon fires, but the
    # alternative (slips last) would let a party damage a cog and then
    # remove it for free.
    #
    # Also has to happen outside the sort below, which keys on
    # ATTACK_ORDER.index(track) -- a slip has no track.
    for i, action in enumerate(actions):
        if action is not None and action.fire:
            apply_toon_action(state, action, hit=True, actor=i)

    # SOS TOONS RESOLVE HERE TOO, for the same two reasons: no track
    # (same sort problem), and can't miss (no roll-group machinery
    # needed).
    #
    # BEFORE THE GAGS IS [ASSUMED] -- no source states when an SOS lands
    # in a round. Chosen to match slips, and it's the ordering that
    # makes the useful plays legible: a teammate's Lure SOS puts the
    # field to sleep before another toon's Throw collects the knockback.
    for i, action in enumerate(actions):
        if action is not None and getattr(action, "sos", None):
            # The return value is the point for a heal card: `_score_leaf`
            # reads the REPORT, not the state, so a discarded return
            # would make `QUICK_W["heal"]` blind to every SOS heal, and
            # hide the laff-relative weighting `_restored` applies (180
            # laff into a full toon is worth 17, into a dying one 125).
            gained, _damage = apply_toon_action(state, action,
                                                hit=True, actor=i)
            healed[i] += gained

    order = sorted(
        (i for i, a in enumerate(actions)
         if a is not None and not a.is_pass and not a.fire
         and a.sos is None),
        key=lambda i: ATTACK_ORDER.index(actions[i].track))

    # Hits so far this round, for the stun bonus: one entry per landed
    # attack, remembering what it was and whom it touched.
    landed: List[Tuple[Track, bool, List[int]]] = []

    index = 0
    while index < len(order):
        track = actions[order[index]].track
        same_track = [i for i in order[index:]
                      if actions[i].track == track]
        index += len(same_track)

        # Everything of one track resolves together, so a combo forms
        # from gags that were chosen independently.
        #
        # Index cogs by identity, not `list.index` -- CogState is a
        # dataclass, so two untouched cogs of the same type and level
        # compare equal, which would misattribute a Throw at cog 1 to
        # cog 0.
        where = {id(c): i for i, c in enumerate(state.cogs)}
        # ONE ROLL PER TRACK PER TARGET, NOT PER GAG. Gags of the same
        # track aimed at the same cog share a single accuracy roll, so
        # they all land or all miss together; a group gag rolls once for
        # the whole battle. Rolling each gag separately would let a
        # party hedge (four Throws almost surely landing *something*),
        # badly overvaluing stacking a track on one target.
        #
        # THE BEST GAG SHARING A ROLL SETS THE ACCURACY. Moot for every
        # track but Lure and Toon-Up, where propAcc is uniform within a
        # track. Lure's accuracies run 60/55/70/65/80/75/90 by level, so
        # a stronger Lure on a cog carries a weaker one thrown at the
        # same cog. [UNVERIFIED] for Lure -- play knowledge, not the
        # wiki, applied to every track since taking the max over equal
        # numbers changes nothing for the uniform ones.
        prepared = []
        for toon_index in same_track:
            action = actions[toon_index]
            target_cogs = _targets_for(state, action)
            targets = [where[id(c)] for c in target_cogs]
            group = action.target_index is None
            prior = sum(
                1 for prev_track, prev_group, prev_targets in landed
                if prev_track != track and prev_track != Track.TRAP
                and _prev_hits_apply(prev_group, prev_targets, group, targets))
            # A forced accuracy is an outcome the rules state, not a
            # total to adjust. Adding stun to it and capping the sum is
            # what gave an always-hit Trap a 5% miss and let a Drop land
            # on a lured cog -- see mechanics.forced_accuracy.
            forced = mechanics.forced_accuracy(action.track, target_cogs)
            if forced is None and state.sos_one_round and sos_mod.active(
                    state, "toons_hit_rounds"):
                # Realms' Toons Hit is a certainty too, and capping it
                # here at 95 undid it for every party round -- found by
                # holding this path against the solo and exact ones.
                forced = 100
            if forced is not None:
                accuracy = forced
            else:
                accuracy = min(
                    toon_action_accuracy(state, action, toon_index)
                    + mechanics.calc_same_round_prev_hits(prior),
                    data.ACCURACY_CAP)
            key = None if group else action.target_index
            prepared.append((toon_index, action, targets, group, key,
                             accuracy))

        best: Dict[Optional[int], int] = {}
        for _i, _a, _t, _g, key, accuracy in prepared:
            best[key] = max(best.get(key, 0), accuracy)

        # Lure Bonus: multiple Lures thrown together raise each other's
        # accuracy. [CONFIRMED] that it exists and which pairs qualify
        # (group with group, Bill with Bill, never one of each);
        # [ASSUMED] how big it is -- see
        # `mechanics.MULTI_LURE_ACCURACY_BONUS`.
        #
        # Applied to the shared roll rather than per gag, because the
        # gags in a roll group already resolve on one die and the
        # highest base accuracy already overrides -- which is the rule
        # the same patch notes state.
        if track == Track.LURE:
            for key in list(best):
                levels = [a.level for _i, a, _t, _g, k, _acc in prepared
                          if k == key]
                bonus = mechanics.multi_lure_bonus(levels)
                if bonus:
                    best[key] = min(best[key] + bonus, data.ACCURACY_CAP)

        if record is not None:
            for key, accuracy in best.items():
                record.append((track, key, accuracy))

        rolls: Dict[Optional[int], int] = {}
        resolved = []
        for toon_index, action, targets, group, key, _accuracy in prepared:
            if hits is not None:
                hit = bool(hits[toon_index])
            else:
                if key not in rolls:
                    rolls[key] = mechanics.accuracy_roll(rng)
                hit = rolls[key] < best[key]
            resolved.append((toon_index, action, targets, group, hit))
            if hit:
                landed.append((track, group, targets))

        _apply_track_group(state, track, resolved, healed)
    return healed


def _apply_track_group(state: BattleState, track: Track, resolved,
                       healed: List[int]) -> None:
    """Apply one track's worth of simultaneous gags, combos included."""
    if track == Track.TOON_UP:
        for toon_index, action, _t, _g, hit in resolved:
            toon = state.toons[toon_index]
            _spend_gag(toon, action.track, action.level)

            # [CONFIRMED] TTR wiki (Toon-Up): "Toons cannot use Toon-Up
            # gags to restore their own laff"; they "restore each
            # other's laff" -- the heal credits everyone but the thrower.
            # ORGANIC counts here as it does for every damage track. It was
            # left at the default, so a party's organic Toon-Up healed as
            # a plain one (Feather 10, not 12).
            amount = mechanics.calc_toon_heal(
                action.level, hit,
                organic=toon.is_organic(Track.TOON_UP, action.level))
            others = [i for i, other in enumerate(state.toons)
                      if i != toon_index and other.laff > 0]
            if not others:
                continue

            if data.gag(Track.TOON_UP, action.level).group:
                # [CONFIRMED] TTR wiki: "Group Toon-Up gags provide laff
                # evenly between Toons." [OWNER] from play: evenly among
                # the toons being HEALED, not the whole party -- the
                # thrower isn't a recipient, so one gag over a four-toon
                # party is three shares, not four.
                share = amount // len(others)
                for index in others:
                    healed[index] += share
            else:
                # `target_index` names a TOON for this track, not a cog.
                target = action.target_index
                if target is None or target not in others:
                    target = others[0]
                healed[target] += amount
        return

    if track == Track.TRAP:
        # TWO TRAPS ON ONE COG CANCEL. [CONFIRMED] by the owner: thrown in
        # the same round at the same cog, neither is placed and BOTH gags
        # are still spent. The Railroad is the exception -- it nils the
        # other trap and places anyway. (This is also how a fourth toon
        # can answer a badly-placed trap: throw a second one at the
        # same cog to stop the first from springing.)
        claims: Dict[int, List[Tuple[int, object]]] = {}
        for toon_index, action, targets, _g, hit in resolved:
            _spend_gag(state.toons[toon_index], action.track, action.level)
            if not hit:
                continue
            for cog_index in targets:
                claims.setdefault(cog_index, []).append((toon_index, action))

        for cog_index, bids in claims.items():
            cog = state.cogs[cog_index]
            if cog.status.is_dead:
                continue
            group = [(i, a) for i, a in bids
                     if data.gag(a.track, a.level).group]
            if len(bids) > 1 and not group:
                cog.status.clear_trap()       # both nilled, gags gone
                continue
            toon_index, action = group[0] if group else bids[0]
            # The group Trap wakes what it lays under; a single-target one
            # cannot be placed on a cog already off its square.
            if group:
                cog.status.clear_lure()
            elif cog.status.lured:
                continue
            cog.status.trapped = True
            cog.status.trap_track = action.track
            cog.status.trap_level = action.level
            cog.status.trap_organic = state.toons[toon_index].is_organic(
                action.track, action.level)
        return

    if track == Track.LURE:
        # SIMULTANEOUS, not sequential. [CONFIRMED] by the owner: two
        # Lures in one round are ONE effect on each cog -- if the cog was
        # trapped, the trap springs once and the cog stays awake; a
        # second Lure cannot then re-lure it, so a group Lure is not an
        # answer to a badly-placed Trap. What a second Lure DOES buy is
        # accuracy -- see `mechanics.multi_lure_bonus`, already applied
        # to the shared roll above.
        claims: Dict[int, Tuple[int, object]] = {}
        for toon_index, action, targets, _g, hit in resolved:
            _spend_gag(state.toons[toon_index], action.track, action.level)
            if not hit:
                continue
            for cog_index in targets:
                held = claims.get(cog_index)
                # The strongest Lure on a cog sets its duration, the same
                # rule by which the best gag sharing a roll sets accuracy.
                if held is None or action.level > held[1].level:
                    claims[cog_index] = (toon_index, action)

        for cog_index, (toon_index, action) in claims.items():
            cog = state.cogs[cog_index]
            if cog.status.is_dead:
                continue
            if cog.status.trapped:
                # Springing SPENDS the lure: the damage is the trade for
                # the rounds asleep, and no other Lure this round can buy
                # them back.
                cog.take_damage(_apply_trap_trigger(cog))
                continue
            toon = state.toons[toon_index]
            cog.status.apply_lure(
                mechanics.lure_accuracy_before_bonus(
                    action.track, action.level, toon, [cog]),
                mechanics.lure_duration_rounds(action.level),
                action.level)
        return

    # A damage track. Sum by target first, then bonus the total.
    per_target: Dict[int, List[Tuple[int, int]]] = {}
    for toon_index, action, targets, _g, hit in resolved:
        toon = state.toons[toon_index]
        # Spend the gag whether or not it landed.
        _spend_gag(toon, action.track, action.level)
        if not hit:
            continue
        for cog_index in targets:
            cog = state.cogs[cog_index]
            if cog.status.is_dead:
                continue
            if track == Track.DROP and cog.status.lured:
                continue          # Drop always misses a lured cog
            # Via `calc_toon_damage`, NOT `damage_at(1.0, ...)` directly
            # -- the latter hardcodes a fully-trained toon and bypasses
            # `mechanics.DAMAGE_TRAINED_FRACTION`.
            damage = mechanics.calc_toon_damage(
                track, action.level, organic=toon.is_organic(track, action.level))
            per_target.setdefault(cog_index, []).append((toon_index, damage))

    for cog_index, contributions in per_target.items():
        cog = state.cogs[cog_index]
        total = sum(d for _i, d in contributions)
        total += mechanics.calc_hp_bonus(total, len(contributions))
        if track in (Track.THROW, Track.SQUIRT) and cog.status.lured:
            total += int(mechanics.calc_kb_bonus(track, True, total))
        for toon_index, damage in contributions:
            cog.status.record_damage(toon_index, damage)
        cog.take_damage(int(total))
        # Same rule as the solo path, and for the same reason: the
        # knockback above is collected against the sleeping cog, then the
        # cog wakes. Only Sound used to do this.
        if cog.status.is_dead or track in mechanics.DAMAGE_TRACKS:
            cog.status.clear_lure()
