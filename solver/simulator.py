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

from . import data
from . import mechanics
from . import state as state_mod
from .state import (
    ATTACK_ORDER, BattleState, CogState, Action, Track,
)


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
    Always, while `state.free_passes` lasts. Passing is an ordinary
    choice: conserve a scarce gag, or in a party decline to hit a cog
    because `mechanics.pick_cog_target` makes it prefer whoever damaged
    it most, so swinging really does pull its next attack onto you.

    It used to be offered only when a cog was lured and nothing
    productive could be done. That was too narrow -- it made both of the
    above unsayable -- but the reasons behind it are real and worth
    keeping in view.

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

    THE UNLURED PASS, AND WHY IT IS BUDGETED
    ----------------------------------------
    Passing with nothing lured is also a real move, and the rule above
    used to forbid it outright. Two cases it was wrong about:

      * conserving a scarce gag, when taking a hit is cheaper than
        spending the only Railroad in the pouch;
      * declining to hit a cog in a party, because
        `mechanics.pick_cog_target` makes a cog prefer whoever damaged
        it most -- so attacking really does draw its next swing onto
        you, and sometimes the right move is to let a healthier toon
        take the aggro.

    `state.free_passes` is a TERMINATION GUARD and not a strategic
    limit, which is why it starts at 12 -- high enough never to bind in
    a real battle.

    It cannot simply be unbounded. `solve()` terminates because a
    well-founded measure descends every round, and an unlured pass
    spends no gag and ticks no lure. In the outcome branch where every
    cog MISSES it also costs no laff, leaving a state identical to its
    parent -- so the graph stops being a DAG and the search recurses
    forever down pass -> pass -> pass. The measure is therefore
    (gags, lure rounds, free passes), and still descends.

    A lured pass does not draw on the budget: the lure timer is already
    the quantity going down, and the trap-and-wait line can need many
    rounds of it.
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

    # PINK SLIPS, one per live cog. Offered before gags because they are
    # unconditional: no accuracy, no track, no interaction with lure or
    # trap. Finite and strictly decreasing, so they do not threaten the
    # termination argument above -- the measure simply gains a component.
    for i, cog in enumerate(state.cogs):
        if toon.fires > 0 and not cog.status.is_dead:
            actions.append(Action(track=None, target_index=i, fire=True))

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
            actions.append(Action(track=track, level=level, target_index=None))
            continue

        if track == Track.TOON_UP:
            # Toon-Up names a TOON, and this enumerated cogs. With four
            # cogs and two toons it produced four heals aimed at cog
            # indices, and the heal quietly fell back to "first standing
            # teammate" -- so the search saw several identical actions
            # wearing different labels and printed nonsense like
            # `Feather -> cog 0`.
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

    # Drop the moves that provably do nothing. `is_productive` already
    # knew about them and was only ever consulted for the pass decision,
    # so the search was free to spend a round re-luring an
    # already-lured cog -- which refreshes a timer and buys nothing --
    # or dropping on a lured one, which always misses.
    productive = [a for a in actions if is_productive(state, a)]
    if productive:
        actions = productive

    # PASS, widened. Offered whenever a cog is lured -- that is how lure
    # rounds get burned, and it costs no budget because the lure timer
    # is already the quantity descending -- and otherwise while
    # `free_passes` lasts.
    #
    # This was reverted once, on the belief that it broke exact
    # `solve()`. It did not: `solve` computed its depth budget as
    # "gags + 1", on the assumption that every action spends a gag, and
    # a pass does not. The search truncated and its leaves fell through
    # to `heuristic_value`, which is what invented the value. Fixing the
    # budget to count `free_passes` too makes narrow and wide agree
    # exactly where they should -- checked over 93 random positions,
    # with no case of the wider rule scoring LOWER, which more options
    # cannot do -- and the six positions where it scores higher are
    # genuine, one of them by 131 points.
    if any(cog.status.lured for cog in active) or state.free_passes > 0:
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
    # Trap arms something, and the damage tracks damage something.
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


def toon_action_accuracy(state: BattleState, action: Action,
                         actor: int = 0) -> int:
    """The gag's hit chance, 0-100, for the toon THROWING it.

    Passes all_cogs (not just the targets) so the luredRatio half of `bonus`
    sees the whole battle -- its denominator is every cog in play.

    A pass always "hits": it has one outcome, so the search should not
    split a chance node over it.

    `actor` indexes `state.toons`, and defaults to 0 because solo play is
    the whole of every other caller. A party round must pass it: accuracy
    reads the thrower's TRAINING and whether the track is organic to
    them, and both are per toon. This read `state.toon` unconditionally,
    so every gag in a party round was scored with toon 0's training --
    invisible on a maxed team, which is every boss position modelled so
    far, and wrong for any mixed party.
    """
    if action.is_pass:
        return 100
    toon = state.toons[actor]
    return mechanics.calc_toon_accuracy(
        action.track, action.level, toon,
        _targets_for(state, action), all_cogs=state.cogs,
        lure_tree_planted=toon.is_organic(action.track))


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
        # Nothing spent from the pouch, nothing dealt. The round still
        # happens -- the caller runs the cog phase, which is the entire
        # point of passing while lured: it is how lure rounds get
        # burned.
        #
        # An UNLURED pass does spend something: a unit of
        # `free_passes`. That is what keeps the termination measure
        # descending, since such a pass ticks no lure and costs no gag.
        # A lured pass is free here because the lure timer is already
        # the quantity going down.
        if not any(cog.status.lured for cog in state.active_cogs()):
            state.free_passes = max(0, state.free_passes - 1)
        return 0, 0

    if action.fire:
        # A pink slip removes the cog from the battle. It cannot miss, so
        # `hit` is not consulted, and it spends the toon's action for the
        # round exactly as a gag would.
        #
        # Reported as 0 damage rather than the cog's remaining hp: the
        # cog is fired out of the fight, not damaged, and every scorer in
        # the project reads the return value as damage dealt. Crediting
        # it as damage would make a fire look like the biggest hit in the
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
        # Kills BOTH layers of a Version 2.0 -- [CONFIRMED] wiki. Nothing
        # here needs to know about the second layer because a fire never
        # leaves one behind.
        cog.hp = 0
        cog.status.is_dead = True
        cog.status.lured = False
        cog.status.trapped = False
        # Both layers go. [CONFIRMED] wiki: a pink slip eliminates the
        # suit AND the Skelecog form, so a fired v2.0 leaves nothing --
        # clearing this also keeps dead cogs from splitting the memo key
        # on a flag that can no longer matter.
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
        # rather, provide 20% of original values that are rounded up." So a
        # missed Toon-Up still heals -- it is the one track where a miss
        # isn't a no-op, which is why this sits above the `if not hit`.
        #
        # But it heals SOMEBODY ELSE. [CONFIRMED] TTR wiki (Toon-Up):
        # "Toons cannot use Toon-Up gags to restore their own laff" --
        # they "restore each other's laff". This path is the solo one,
        # where there is nobody else, so the gag is spent and heals
        # nothing. It used to return the full value to the thrower,
        # which made a solo Toon-Up a self-heal the game does not offer.
        return 0, dealt

    if not hit:
        return healed, dealt

    if action.track == Track.TRAP:
        # Every target, not just the first. Railroad is a group gag -- it
        # lays a trap in front of all of them -- and arming only one cog
        # quietly turned the best trap in the game into a single-target one,
        # which made the Railroad+Lure combo look far weaker than it is.
        #
        # An existing trap is overwritten -- [CONFIRMED] TTR 3.0.0, "if
        # there are active Trap gags on Cogs, and a Railroad gag is placed
        # in a subsequent round by itself, it will override the previously
        # placed Trap gags rather than fizzling out".
        #
        # THE RAILROAD WAKES THE FIELD TO LAY ITSELF. [CONFIRMED] by the
        # owner from play: a group Trap needs only ONE unlured cog to go
        # down, and placing it un-lures every lured cog so the track can
        # be laid under all of them. A single-target Trap cannot do this
        # and is still refused on a lured cog.
        #
        # That is what makes Railroad-then-Lure work IN ONE ROUND: Trap
        # resolves before Lure, the Railroad wakes the field and arms it,
        # and the Lure lands afterwards and springs it. Skipping lured
        # cogs -- which this used to do -- made the strongest combination
        # in the game unplayable whenever anything was already asleep.
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
                dealt += cog.take_damage(dmg)
                # THE TRAP KNOCKS IT OUT OF THE LURE. [CONFIRMED] by the
                # owner: "If you lure a cog onto a trap, the cog becomes
                # unlured after taking damage."
                #
                # This was a [TODO] that guessed the other way and kept
                # the cog lured, which made Trap+Lure strictly better
                # than it is -- the cog took the trap damage AND stayed
                # asleep for the full lure duration, so the combo bought
                # damage and several rounds of prevention at once.
                #
                # It does not. Springing a trap SPENDS the lure: you
                # trade the rounds the cog would have spent asleep for
                # the trap's damage. That is the real trade-off behind
                # the combo and any evaluation of Trap has to price it,
                # which is why the discount cannot just be
                # P(spring) x damage -- the lure given up is part of the
                # cost.
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
            dealt += cog.take_damage(dmg)
            # THE KNOCKBACK IS ALREADY IN `total` ABOVE, AND THE LURE
            # ENDS HERE. A landed attack of any damage track wakes the
            # cog -- [CONFIRMED] by the owner, see
            # mechanics.LURE_ENDS_ON_DAMAGE. So a Throw collects its +50%
            # against the sleeping cog and then the cog is awake, and if
            # it survived it attacks this round.
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
            and mechanics.lure_wakes_up(status.lure_acc_before_bonus, rng)):
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

    # Same reinforcement rule as the party path; see the note in
    # `apply_party_round`.
    from . import facility
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
    """Take one gag out of the pouch, refusing to take one that is not
    there.

    A pouch holds explicit zeroes -- `{(SQUIRT, 7): 0}` is an ordinary
    entry for a toon who has used them all -- so a bare `-= 1` on a
    missing key raised KeyError while the same spend on a ZERO count
    went quietly to -1 and dealt full damage. Two spellings of the same
    mistake, one loud and one silent.

    Nothing in normal play reaches this: `legal_actions` only offers a
    gag with a positive count, and `legal_mask` derives from it. It is
    hand-built plans that get here, and they are exactly the ones with
    nobody to check them -- a scorer handed an impossible plan returned
    a plausible number, which cost an afternoon and a wrong commit.

    KeyError rather than a new exception type because every caller that
    scores a speculative plan already catches it, and this is the same
    fact those catches are for: the plan cannot be played.
    """
    counts = dict(toon.gag_counts)
    if counts.get((track, level), 0) <= 0:
        raise KeyError((track, level))
    counts[(track, level)] -= 1
    toon.gag_counts = counts


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
    exist only here, and each is why the round cannot be resolved by
    calling `apply_toon_action` four times:

    * Order. Gags resolve by track -- Toon-Up, Trap, Lure, Sound, Throw,
      Squirt, Drop -- not by who chose first. A Lure that lands before a
      Throw is what makes the Throw a knockback.
    * Combos. Same-track gags on the same cog in the same round have
      their damage summed and then get `calc_hp_bonus` on the total.
      Summed *then* bonused: four Throws at one cog are not four
      separately-bonused Throws.
    * Stun. A landed attack makes later attacks of a *different* track
      more accurate, via `calc_same_round_prev_hits`.

    Accuracy is rolled per attack at the moment it resolves, because the
    stun bonus depends on what has already landed. Passing `hits` fixes
    the rolls instead, which is what an enumerating caller wants.

    `record`, if given, is appended with one `(track, key, accuracy)` per
    ROLL GROUP -- the shared die, not the gag -- carrying the accuracy
    this round actually resolved it against, stun bonus and Lure bonus
    included. A caller that fixes `hits` and wants to know what that
    branch was worth needs the accuracy the simulator used, and deriving
    it a second time outside this function would be a second
    implementation of the same rule, free to disagree with this one
    while both looked right. `(track, key)` is unique per round: tracks
    resolve in ATTACK_ORDER, so one track is prepared exactly once.
    """
    healed = [0 for _ in state.toons]

    # PINK SLIPS RESOLVE FIRST, before any gag. A fired cog is removed
    # from the battle by cannon, so it is gone before the round's gags
    # land -- which means a teammate who threw at the same cog has wasted
    # the gag. That ordering is [ASSUMED]: no source states where in a
    # round the cannon fires, and the alternative (slips last) would let
    # a party damage a cog and then remove it for free.
    #
    # It also has to happen outside the sort below, which keys on
    # ATTACK_ORDER.index(track) -- a slip has no track and that raised
    # "None is not in list" the moment fires reached a party round.
    for i, action in enumerate(actions):
        if action is not None and action.fire:
            apply_toon_action(state, action, hit=True, actor=i)

    order = sorted(
        (i for i, a in enumerate(actions)
         if a is not None and not a.is_pass and not a.fire),
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
        # Index cogs by identity. `list.index` compares by value and
        # CogState is a dataclass, so two untouched cogs of the same type
        # and level are equal -- which made a Throw aimed at cog 1 report
        # itself as hitting cog 0, and then combo with the gag that
        # really did. Found by a test asserting two cogs do not combo.
        where = {id(c): i for i, c in enumerate(state.cogs)}
        # ONE ROLL PER TRACK PER TARGET, NOT PER GAG. Gags of the same
        # track aimed at the same cog share a single accuracy roll, so
        # they all land or all miss together; a group gag rolls once for
        # the whole battle. Rolling each gag separately let a party
        # hedge -- four Throws at one cog would almost surely land
        # *something* -- which is not the game and badly overvalues
        # stacking a track on one target.
        #
        # THE BEST GAG SHARING A ROLL SETS THE ACCURACY. For every track
        # but Lure and Toon-Up this is moot, because propAcc is uniform
        # within a track -- a Cupcake and a Birthday Cake are both 75, so
        # it makes no difference which is read. Lure is where it bites:
        # its accuracies run 60/55/70/65/80/75/90 by level, and a
        # stronger Lure on a cog carries a weaker one thrown at the same
        # cog rather than being dragged down by it.
        #
        # [UNVERIFIED] for Lure -- play knowledge, not the wiki, which
        # documents the per-gag accuracies and says nothing about two
        # Lures on one cog. Applied to every track because taking the
        # maximum over equal numbers changes nothing, so the uniform
        # tracks are unaffected either way. Toon-Up (70 up to level 6,
        # 95 at 7) follows the same rule by analogy and nothing more.
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
            # Spend it. This returned without spending, which made
            # healing free -- and a free action is one a search will
            # take for no reason. A joint search filled three of four
            # slots with Feathers thrown at toons already on full laff,
            # purely because they cost nothing.
            toon = state.toons[toon_index]
            _spend_gag(toon, action.track, action.level)

            # [CONFIRMED] TTR wiki (Toon-Up): "Toons cannot use Toon-Up
            # gags to restore their own laff"; they "restore each
            # other's laff". This credited the heal to the THROWER,
            # which is the rule backwards -- and it is why a party at
            # full laff kept being advised to heal itself.
            amount = mechanics.calc_toon_heal(action.level, hit)
            others = [i for i, other in enumerate(state.toons)
                      if i != toon_index and other.laff > 0]
            if not others:
                continue

            if data.gag(Track.TOON_UP, action.level).group:
                # [CONFIRMED] TTR wiki: "Group Toon-Up gags provide laff
                # evenly between Toons."
                #
                # EVENLY BETWEEN THE RECIPIENTS, not the party. The wiki
                # never says among whom, which stood as a [TODO] here;
                # [CONFIRMED] by the owner from play: it is split across
                # the toons being healed, and the thrower is not one of
                # them. So one gag over a four-toon party is three
                # shares, not four -- nothing is lost to the thrower.
                #
                # A two-toon party therefore hands its single recipient
                # the full value: a level 7 is 210 to the other toon.
                # That is not a special case, it is one recipient.
                share = amount // len(others)
                for index in others:
                    healed[index] += share
            else:
                # `target_index` names a TOON for this track. It used to
                # be read as a cog index, which meant a heal aimed at
                # teammate 1 indexed cogs[1] and raised IndexError once
                # there were more toons than cogs.
                target = action.target_index
                if target is None or target not in others:
                    target = others[0]
                healed[target] += amount
        return

    if track == Track.TRAP:
        # TWO TRAPS ON ONE COG CANCEL. [CONFIRMED] by the owner: thrown in
        # the same round at the same cog, neither is placed and BOTH gags
        # are still spent. The Railroad is the exception -- it nils the
        # other trap and places anyway.
        #
        # This cannot be delegated to `apply_toon_action` one toon at a
        # time, which is what it used to do: each call sees only its own
        # trap, so the second silently overwrote the first and a cog that
        # should have ended the round bare ended it armed. It is also the
        # only reason a fourth toon can answer a badly-placed trap at all
        # -- throwing a second trap at the same cog is how you stop the
        # first from springing.
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
                action.track)
        return

    if track == Track.LURE:
        # SIMULTANEOUS, which is not the same as sequential. Two Lures in
        # one round are ONE effect on each cog, and this used to call
        # `apply_toon_action` per toon: the first Lure sprang the trap
        # and left the cog awake, and the second then saw an untrapped
        # cog and lured it. [CONFIRMED] by the owner that this is wrong
        # -- the Lures fire together, the trap springs once, and the cog
        # stays awake.
        #
        # It mattered: a teammate trapping a cog about to be lured
        # throws the lure away, and sequential resolution let a second
        # Lure quietly undo that. It also made a group Lure look like an
        # answer to a badly-placed Trap, which it is not.
        #
        # What a second Lure DOES buy is accuracy -- see
        # `mechanics.multi_lure_bonus`, already applied to the shared
        # roll above.
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
            # Via `calc_toon_damage`, NOT `damage_at(1.0, ...)`. Going
            # straight to the table hardcoded a fully-trained toon and
            # bypassed `mechanics.DAMAGE_TRAINED_FRACTION`, so a search
            # run against a pessimistic damage assumption silently kept
            # dealing maxed damage here -- and the mismatch between what
            # the knob said and what the round dealt looked exactly like
            # the round inventing damage out of nowhere.
            damage = mechanics.calc_toon_damage(
                track, action.level, organic=toon.is_organic(track))
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
