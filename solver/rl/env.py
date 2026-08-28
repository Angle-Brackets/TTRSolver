"""A party battle as a reinforcement-learning environment.

`reset()` / `step(action_index)` over `party.step`, so the agent plays
the same simulator the search does and is scored by the same
`round_reward`. Nothing is re-implemented here; if the two ever disagree
the comparison between agent and search stops meaning anything.

WHY THIS EXISTS ALONGSIDE THE SEARCH
------------------------------------
Profiling a depth-2 party search put **95% of its runtime in `plans()`**
-- enumerating and ranking candidate joint plans -- and essentially none
in evaluating them. That is a combinatorial cost, and a policy does not
pay it: it samples an action instead of enumerating thousands.

It also has no transposition table and makes no exactness claim, which
matters for one action in particular. Widening the pass broke exact
`solve()` (see `state.free_passes`), so the search cannot currently
offer it outside a lured position -- but passing to conserve a scarce
gag, or to avoid drawing a cog's attack via
`mechanics.pick_cog_target`, is real play. **Here the pass is simply
available**, because nothing in this file memoises anything.

MODE
----
Pickup: the agent controls `toons[0]` and teammates are sampled from
`party.SensiblePrior`. That is the live-advice case, and it is honest
about its limits -- a policy trained here has learned to play alongside
a *model* of strangers, not alongside strangers.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

from .. import data, facility, party as party_mod, simulator
from .. import state as state_mod

# Zero a level-7 count the rules forbid, so the pouch looks naturally
# empty rather than full of unusable gags. OFF: the reasoning was sound
# and the measurement said no.
#
# The mismatch is real. With `state.ALLOW_LEVEL_7` off -- the panel's
# "hold my 7s for the boss" toggle -- `legal_mask` drops level 7 while
# the observation still reports the count, so the policy sees resources
# it cannot spend. That combination never occurs in training: when a
# training pouch has no 7s the count is genuinely 0, which is 52% of
# sampled loadouts. Zeroing it should have put the observation back in
# distribution.
#
# It changed nothing worth having, paired over 800 no-7 sides:
#
#     cell        shown   zeroed
#     buildings   62.0%    61.5%
#     buildings   61.0%    60.0%
#     CEO 0       24.0%    22.0%
#     CEO 2        6.5%     6.5%
#     pooled      35 up / 42 down, p=0.49
#
# All four cells lean the wrong way, so it stays off. Kept as a flag
# because the argument survives the result -- a policy retrained with
# no-7 play as an explicit arm might use those inputs differently, and
# this is the knob that would test it.
MASK_SEVENS_IN_OBS = False
from ..data import gags as gags_mod
from ..search import objective as objective_mod
from ..state import Action, BattleState, CogState, ToonState, Track

MAX_COGS = 4
MAX_TOONS = 4
TRACKS = [Track.TOON_UP, Track.TRAP, Track.LURE, Track.SOUND,
          Track.THROW, Track.SQUIRT, Track.DROP]

# A fixed action table, so the policy's output layer has a constant
# shape. Illegal entries are masked per step rather than removed --
# masking keeps the indices stable, and a policy that never sees an
# index cannot learn a spurious preference for it.
#
# target None means "group"; 0..3 name a cog. The pass is index 0 so it
# is always present even when the table is otherwise fully masked.
ACTIONS: List[Optional[Action]] = [None]
for _track in TRACKS:
    for _level in range(1, 8):
        for _target in [None] + list(range(MAX_COGS)):
            ACTIONS.append(Action(track=_track, level=_level,
                                  target_index=_target))

# PINK SLIPS, one per cog slot, appended AFTER the gags so every existing
# index keeps its meaning. Without these the agent could not fire at all:
# `simulator.legal_actions` offers them, but nothing here could name one,
# so `legal_mask` dropped them and a party holding twenty slips played as
# though it held none.
#
# This takes the table from 246 to 250 and therefore INVALIDATES every
# policy trained before it -- `check_export` refuses them rather than
# reading the weights shifted by four, which is the failure this project
# has already had once.
FIRE_TARGETS = list(range(MAX_COGS))
for _target in FIRE_TARGETS:
    ACTIONS.append(Action(track=None, level=0, target_index=_target,
                          fire=True))

PASS_INDEX = 0
# Coordinated play adds two blocks: which toon is deciding, and what
# each toon has already chosen THIS round. Without the second, four
# toons sharing one policy see identical observations and pick identical
# actions -- four Lures on the same board. Coordination needs the
# pending plan to be visible.
PENDING_DIM = MAX_TOONS * (len(TRACKS) + 2)      # track one-hot, group, none
OBS_DIM = (MAX_COGS * 11 + MAX_TOONS * (4 + 49) + 6
           + MAX_TOONS + PENDING_DIM)

# Cog level and max hp were scaled by 12 and 200, which is the top of a
# cog BUILDING and nowhere near the top of the game. A level 15 Big
# Cheese read 1.25 and 1.43 -- outside the range every other feature
# lives in, on exactly the fights the scaling was never checked against.
# 20 and 476 are the highest the tables go.
LEVEL_SCALE = 20.0
MAX_HP_SCALE = 476.0


def check_export(payload) -> Optional[str]:
    """Why a saved policy cannot be used here, or None if it can.

    Nothing else validates this, and the failure is silent: a policy
    trained on a 243-wide observation fed 247 floats reads every feature
    shifted by four and returns confident nonsense. That happened --
    adding `trap_damage_ratio` to the observation invalidated a trained
    policy, and only a manual check caught it before a comparison was
    run against it.

    Same shape as `fitted.is_fitted`, which exists so a weight vector
    that no longer matches the feature list refuses to be used instead
    of quietly misreading it.
    """
    if payload.get("obs_dim") != OBS_DIM:
        return (f"observation is {OBS_DIM} wide, policy was trained on "
                f"{payload.get('obs_dim')} -- retrain")
    if payload.get("n_actions") != len(ACTIONS):
        return (f"action table is {len(ACTIONS)}, policy was trained on "
                f"{payload.get('n_actions')} -- retrain")
    return None


def action_at(index: int) -> Optional[Action]:
    """The action for a policy index. `None` is the pass."""
    if index == PASS_INDEX:
        return Action(track=None, level=0, target_index=None)
    return ACTIONS[index]


def _trap_damage(cog) -> float:
    """Damage the armed trap will deal when sprung, 0 if none."""
    if not cog.status.trapped or cog.status.trap_level is None:
        return 0.0
    try:
        return float(data.gag(Track.TRAP, cog.status.trap_level)
                     .damage_at(1.0, organic=False))
    except (NotImplementedError, ValueError, KeyError):
        return 0.0


def encode(state: BattleState, actor: int = 0,
           pending=None) -> List[float]:
    """Fixed-width observation, from `actor`'s point of view.

    `pending` is the joint plan so far this round -- one entry per toon,
    None where they have not chosen. Coordinated play needs it; solo and
    pickup pass nothing and the block reads as all-unchosen.

    Cogs and toons are padded to four with an `alive` flag rather than
    pooled, because neither is interchangeable: targets are indexed, and
    `outcomes.state_key` keys on every toon in order for the same
    reason.
    """
    out: List[float] = []
    for i in range(MAX_COGS):
        if i < len(state.cogs) and not state.cogs[i].status.is_dead:
            cog = state.cogs[i]
            # A Version 2.0 has this much health AGAIN behind what is
            # shown. Without these two entries a v2.0 and an ordinary
            # cog encoded IDENTICALLY -- 0 differing floats out of 290
            # -- so the policy could not see the single thing that
            # defines the CEO's banquet round, and no amount of training
            # on those positions could have taught it.
            #
            # The flag alone would not do it. Remaining health is
            # `hp + max_hp if suited`, a PRODUCT of two inputs, and a
            # linear layer cannot multiply. So the work still to do on
            # this cog is handed over directly, the same reasoning as
            # `trap_damage / hp` below.
            suited = 1.0 if cog.status.suited else 0.0
            remaining = cog.hp + (cog.max_hp if cog.status.suited else 0)
            out += [1.0,
                    cog.level / LEVEL_SCALE,
                    cog.hp / max(1, cog.max_hp),
                    cog.max_hp / MAX_HP_SCALE,
                    suited,
                    remaining / max(1, 2 * cog.max_hp),
                    1.0 if cog.status.lured else 0.0,
                    1.0 if cog.status.trapped else 0.0,
                    min(cog.status.lure_rounds_remaining, 8) / 8.0,
                    1.0 if cog.status.is_dead else 0.0,
                    # HOW BIG the armed trap is, as a fraction of what
                    # the cog has left. A bare `trapped` flag makes a
                    # Banana Peel (10 damage) and a Railroad (200) look
                    # identical, and trap damage spans that whole range
                    # -- which is roughly the size of the errors the
                    # linear evaluator makes on these positions.
                    #
                    # An armed trap is stored damage: the cog WILL lose
                    # this much the moment a lure lands. Reading it as a
                    # fraction of remaining hp answers the question that
                    # actually matters, which is whether it kills.
                    _trap_damage(cog) / max(1, cog.hp)]
        else:
            out += [0.0] * 11

    for i in range(MAX_TOONS):
        if i < len(state.toons) and state.toons[i].laff > 0:
            toon = state.toons[i]
            # Pink slips. The action table has offered fire actions
            # since they were modelled, but the observation never said
            # whether the toon HELD any -- 0 slips and 5 encoded
            # identically. The policy proposed 10.07 of its 10 slips per
            # CEO side, firing everything, because the legality mask was
            # the only thing that ever told it no.
            out += [1.0,
                    toon.laff / max(1, toon.max_laff),
                    toon.max_laff / 137.0,
                    min(toon.fires, 10) / 10.0]
            for track in TRACKS:
                for level in range(1, 8):
                    held = toon.gag_counts.get((track, level), 0)
                    # A GAG THE RULES FORBID IS NOT A GAG YOU HAVE. With
                    # `state.ALLOW_LEVEL_7` off -- the live panel's "hold
                    # my 7s for the boss" toggle -- the mask makes level
                    # 7 illegal while the pouch still contains them, and
                    # showing the count anyway puts the policy in a
                    # position it never trained on: resources visible and
                    # unusable. Zeroing it reproduces the natural empty
                    # pouch instead, which is 52% of sampled training
                    # loadouts, so the observation stays in
                    # distribution.
                    if (MASK_SEVENS_IN_OBS
                            and level == state_mod.LEVEL_SEVEN
                            and not state_mod.ALLOW_LEVEL_7):
                        held = 0
                    out.append(min(held, 8) / 8.0)
        else:
            out += [0.0] * (4 + 49)

    out += [min(state.round_num, 12) / 12.0,
            len(state.active_cogs()) / MAX_COGS,
            len(state.active_toons()) / MAX_TOONS,
            # What is still coming after this fight. Without it the
            # agent cannot tell floor one of a building from the last
            # cog of the day, and every gag looks equally spendable.
            min(state.cogs_remaining, 30) / 30.0,
            # Is anything coming after this fight at all. Distinct from
            # the horizon count: a street battle and the last floor of a
            # building both have 0 remaining, but only one of them let
            # the toon walk away from a fight going badly.
            1.0 if state.kind == "facility" else 0.0,
            # Cogs waiting to walk in to THIS fight as slots free.
            min(len(state.holdout), MAX_COGS) / MAX_COGS]

    # Whose decision this is. Solo play always sets index 0, so the
    # block is constant there and costs nothing.
    for i in range(MAX_TOONS):
        out.append(1.0 if i == actor else 0.0)

    # What each toon has already committed to this round. This is the
    # whole of coordination: it is how the second toon knows a trap is
    # already going down and can lure instead of trapping again.
    pending = pending or [None] * MAX_TOONS
    for i in range(MAX_TOONS):
        block = [0.0] * (len(TRACKS) + 2)
        action = pending[i] if i < len(pending) else None
        if action is None:
            block[-1] = 1.0                       # not chosen yet, or holding
        else:
            if action.track in TRACKS:
                block[TRACKS.index(action.track)] = 1.0
            if action.target_index is None:
                block[len(TRACKS)] = 1.0
        out.extend(block)
    return out


# (track, level, target_index) -> index into ACTIONS. Built once so the
# mask can be derived from the search's own move generator rather than
# reimplementing it.
_ACTION_INDEX = {
    (action.track, action.level, action.target_index): index
    for index, action in enumerate(ACTIONS)
    if action is not None and not action.is_pass and not action.fire
}

# Fires key on the target alone -- they have no track and no level, and
# keying them into the table above would collide with the pass.
_FIRE_INDEX = {
    action.target_index: index
    for index, action in enumerate(ACTIONS)
    if action is not None and action.fire
}


def legal_mask(state: BattleState, actor: int = 0) -> List[bool]:
    """Which indices the agent may pick this round.

    DERIVED FROM `simulator.legal_actions`, deliberately, rather than
    reimplementing its rules. There used to be two move generators and
    they drifted, as two of anything will: the mask never applied the
    productivity rules, so the agent healed parties already on full
    laff -- 4.0% of every gag it threw -- and it validated Toon-Up
    targets against live COG indices, a bug the simulator had already
    found and fixed on its own side without the second copy being
    corrected with it. Diffed over 1,178 positions that was 204
    Toon-Ups the mask allowed and the search did not, and 147 the other
    way.

    Nothing here decides legality. It translates.

    Two things this function still owns, because they are about the
    agent rather than the rules:

    * The actor. `legal_actions` always speaks for `toons[0]`, so the
      state is rotated and Toon-Up targets -- which name a TOON -- are
      mapped back to this state's numbering.
    * The guarantee of a move. An all-False mask leaves the agent with
      nothing to pick, so the pass is restored if nothing else survives.
      `legal_actions` cannot reach that state; the mask is called on
      states the search would never be asked about.
    """
    mask = [False] * len(ACTIONS)
    if (not state.active_toons() or actor >= len(state.toons)
            or state.toons[actor].laff <= 0):
        mask[PASS_INDEX] = True
        return mask

    rotated = party_mod._as_actor(state, actor)
    # `_as_actor` orders the toons [actor, everyone else], so a target
    # `t` in that frame is `order[t]` here.
    order = [actor] + [i for i in range(len(state.toons)) if i != actor]

    for action in simulator.legal_actions(rotated):
        if action.is_pass:
            mask[PASS_INDEX] = True
            continue
        if action.fire:
            index = _FIRE_INDEX.get(action.target_index)
            if index is not None:
                mask[index] = True
            continue
        target = action.target_index
        if action.track == Track.TOON_UP and target is not None:
            target = order[target]
        index = _ACTION_INDEX.get((action.track, action.level, target))
        if index is not None:
            mask[index] = True

    if not any(mask):
        mask[PASS_INDEX] = True
    return mask


class BattleEnv:
    """One battle. `reset()` starts a new one, `step()` plays a round."""

    def __init__(self, objective=None, rng=None, max_rounds: int = 20,
                 precision: float = 0.0, fire_cost: float = 0.0,
                 shaping: float = 0.0, gamma: float = 0.99,
                 sampler=None, coordinated: bool = False,
                 survival_shaping: float = 0.0):
        """`coordinated` makes a round TOON-MAJOR: one env step is one
        toon's decision, and the round resolves when everybody standing
        has chosen.

        In pickup mode the teammates come from `SensiblePrior`, so they
        are noise the policy has to survive -- it can learn what is
        robust to strangers and never "I trap, you lure", because the
        other toon's choice is not a choice. Coordinated play makes the
        whole team's plan the thing being learned.

        The cost is that reward arrives only on the step that completes
        a round; the intermediate decisions get zero and are carried by
        the critic. That is why the pending plan is in the observation.
        """
        self.objective = objective or objective_mod.BALANCED
        self.rng = rng or random.Random()
        self.max_rounds = max_rounds
        # Weight on the potential-based shaping term; 0 disables it.
        # `gamma` must match the trainer's discount or the shaping stops
        # being potential-based and starts changing the objective.
        self.shaping = shaping
        # Weight on a SECOND potential, over toons still standing.
        #
        # The measured fact it exists for: a building is decided by the
        # first toon loss and almost nothing else. An intact party clears
        # 100% of the time (60 for 60) and a party that has lost anyone
        # clears about 7%. The reward says almost nothing about that --
        # `toon_lost_penalty` is 0.0, so the step a toon goes sad is
        # charged only the laff of the final hit, roughly -20, while the
        # true swing in win probability is on the order of -186. The
        # terminal -loss_penalty does not arrive until the wipe, ten to
        # twenty steps later, by which point discounting and noise have
        # buried it.
        #
        # Phi(s) = survival_shaping * (toons standing), so
        # F = gamma*Phi(s') - Phi(s) delivers the charge on the exact
        # step the toon is lost. Potential-based in the Ng et al. sense,
        # so unlike a raw penalty it CANNOT change the optimal policy --
        # only how fast the credit arrives. That guarantee is why this is
        # tried before `toon_lost_penalty`, which can.
        self.survival_shaping = survival_shaping
        # Weight on damage thrown past a cog's remaining hit points. 0
        # keeps the reward exactly what every shipped policy was trained
        # against.
        self.precision = float(precision)
        # Charged per pink slip spent. 0 keeps the reward every shipped
        # policy was trained against.
        self.fire_cost = float(fire_cost)
        self.gamma = gamma
        self.sampler = sampler or default_position
        self.coordinated = coordinated
        self.state: Optional[BattleState] = None
        self.rounds = 0
        self.actor = 0
        self.pending: List[Optional[Action]] = []

    def _standing(self):
        return [i for i, t in enumerate(self.state.toons) if t.laff > 0]

    def _begin_round(self):
        self.pending = [None] * len(self.state.toons)
        if not self.coordinated:
            # PICKUP always acts as toons[0] -- `party.step` applies the
            # action there regardless. Advancing the actor past a sad
            # toon here built the legal mask from a DIFFERENT toon's
            # pouch than the one that would throw, so the agent picked a
            # gag its own toon did not hold and the spend raised
            # KeyError deep in `apply_toon_action`.
            self.actor = 0
            return
        order = self._standing()
        self.actor = order[0] if order else 0

    def _sellbot_cog(self, rng, level):
        """A SELLBOT of a given level, for the VP.

        The VP is Sellbot HQ and every cog in it is a Sellbot. The VP
        plan was being built with `_facility_cog`, which draws from the
        street pools across all four departments, so the policy was
        trained on VP rounds full of Lawbots and Cashbots -- a fight
        that does not exist.

        It matters beyond flavour: departments differ in their attacks,
        so the incoming damage distribution the policy learned for a VP
        was wrong, not merely mislabelled.

        The eight Sellbots span levels 1-12 between them, exactly the
        VP's own band, so nothing has to be substituted and this
        refuses rather than guessing -- the same rule `_facility_cog`
        and `_boss_cog` follow.
        """
        from .. import data

        candidates = [spec.key for spec in data.all_cogs()
                      if spec.department == "sellbot"
                      and level in spec.levels]
        if not candidates:
            raise ValueError(f"no Sellbot at level {level}")
        full = data.cog_max_hp(level)
        return CogState(rng.choice(candidates), "sellbot", level, full, full)

    def _boss_cog(self, rng, level):
        """A cog of a given level, allowed to reach 13-15.

        `_facility_cog` draws from the street pools, which stop at 12.
        The CEO needs the three Bossbot Clubhouse cogs, so this picks
        from whichever of them actually covers the level rather than
        substituting -- the same refusal-to-guess `_facility_cog` makes.
        """
        from .. import data

        candidates = [key for key in ("head_hunter", "corporate_raider",
                                      "the_big_cheese")
                      if level in data.cog("bossbot", key).levels]
        if not candidates:
            raise ValueError(f"no Bossbot Clubhouse cog at level {level}")
        key = rng.choice(candidates)
        full = data.cog_max_hp(level)
        return CogState(key, "bossbot", level, full, full)

    def _facility_cog(self, rng, level):
        """A cog of a given level, from the tables known to be complete.

        RAISES rather than substituting when no cog covers the level.
        This used to fall back to the whole pool -- `rng.choice(pool or
        SAFE_COGS)` -- which quietly produced a Number Cruncher at level
        2, a cog that does not exist at level 2, and the training run
        died several minutes in with a ValueError from deep inside the
        data layer.

        A silent stand-in is worse than the crash it prevents: it would
        have trained the policy against cogs the game does not have.
        """
        # BRUTAL_COGS reaches level 12, which a difficulty 9 building's
        # boss needs and neither other pool provides.
        pool = [c for c in SAFE_COGS + LOW_COGS if c[2] <= level <= c[3]]
        pool += [(k, d, lv, lv) for k, d, lv in BRUTAL_COGS if lv == level]
        if not pool:
            raise ValueError(
                f"no cog with a complete table appears at level {level}")
        key, dept, _lo, _hi = rng.choice(pool)
        full = data.cog_max_hp(level)
        return CogState(key, dept, level, full, full)

    def _next_floor(self, state):
        """Move a won facility battle on to the next floor.

        The pouch and the laff carry over exactly as they stand: nothing
        restocks between floors and nobody heals, which is the whole
        reason a gag spent early is a gag missing later. Cog status --
        lured, trapped, soaked -- does not, because these are different
        cogs in a different room.
        """
        cogs, holdout = self.plan.take_floor()
        nxt = state.clone()
        nxt.cogs = cogs
        nxt.holdout = holdout
        nxt.round_num = 0
        nxt.cogs_remaining = self.plan.remaining()
        self.floor += 1
        return nxt

    def reset(self) -> Tuple[List[float], List[bool]]:
        while True:
            self.state = self.sampler(self.rng)
            self.plan = None
            self.floor = 1
            if self.state.kind == "ceo":
                # The CEO is not on a street either. Its cog levels reach
                # 14, which only the Bossbot Clubhouse cogs cover, so it
                # uses its own factory rather than `_facility_cog`.
                from .. import ceo as ceo_mod
                self.plan = ceo_mod.ceo_plan(self.rng, self._boss_cog)
                first, holdout = self.plan.take_floor()
                self.state.cogs = first
                self.state.holdout = holdout
                self.state.cogs_remaining = self.plan.remaining()
            elif self.state.kind == "vp":
                # The VP is not on a street and has no difficulty row, so
                # its plan is built from the wiki's two level bands
                # instead. Everything downstream -- holdout,
                # cogs_remaining, one pouch across both rounds -- is the
                # ordinary facility machinery.
                from .. import vp as vp_mod
                self.plan = vp_mod.vp_plan(self.rng, self._sellbot_cog)
                first, holdout = self.plan.take_floor()
                self.state.cogs = first
                self.state.holdout = holdout
                self.state.cogs_remaining = self.plan.remaining()
            elif self.state.kind == "facility":
                # The building is built from the party's OWN street.
                # Rolling a second street here would undo the whole
                # point of generating the party for one: a Dreamland
                # party could end up in a Toontown Central building.
                street = (facility.street_named(self.state.street)
                          or facility.sample_street(self.rng))
                difficulty = facility.difficulty_for(
                    self.state, self.rng, street=street)
                self.plan = facility.plan_facility(
                    self.rng, difficulty, self._facility_cog,
                    floors=facility.floors_for(self.state, difficulty,
                                               self.rng))
                first, holdout = self.plan.take_floor()
                self.state.cogs = first
                self.state.holdout = holdout
                self.state.cogs_remaining = self.plan.remaining()
            # Checked AFTER the floor is dealt: a facility position
            # arrives with no cogs and would otherwise read as terminal
            # and spin here forever.
            if not self.state.is_terminal():
                break
        self.rounds = 0
        # Truncation is per FLOOR, not per episode. `max_rounds` exists
        # to cut a fight that has stalled, and a five-floor building
        # legitimately runs past 20 rounds -- capping the episode there
        # would end it around floor two, so the pouch pressure that the
        # whole facility model exists to create would never arrive.
        self.floor_rounds = 0
        self._begin_round()
        return (encode(self.state, self.actor, self.pending),
                legal_mask(self.state, self.actor))

    def _survival_term(self, before, after, done: bool) -> float:
        """gamma*Phi(s') - Phi(s) for Phi = w * (toons standing).

        Applied on EVERY step, including the intermediate seat decisions
        that resolve no round. Those leave Phi unchanged, so the correct
        term is -(1-gamma)*Phi rather than zero -- and skipping them was
        worth about 1.7 of a 20-point telescoping check, a real drift
        that quietly favoured whatever the agent happened to be doing
        while toons were alive. In PPO's MDP a step is one seat's
        decision, so the identity has to hold per step, not per round.
        """
        if not self.survival_shaping:
            return 0.0
        phi_before = float(len(before.active_toons()))
        phi_after = 0.0 if done else float(len(after.active_toons()))
        return self.survival_shaping * (self.gamma * phi_after - phi_before)

    def step(self, index: int):
        """-> (observation, mask, reward, done, info)."""
        before = self.state
        action = action_at(index)

        if self.coordinated:
            self.pending[self.actor] = None if action.is_pass else action
            order = self._standing()
            position = order.index(self.actor) if self.actor in order else -1
            if position + 1 < len(order):
                # Still collecting the joint plan: no round resolves, so
                # no reward. The critic carries these steps.
                self.actor = order[position + 1]
                return (encode(self.state, self.actor, self.pending),
                        legal_mask(self.state, self.actor),
                        self._survival_term(self.state, self.state, False),
                        False,
                        {"win": False, "rounds": self.rounds,
                         "floor": self.floor, "truncated": False,
                         "partial": True})
            nxt, _healed, _done = party_mod.step(
                before, self.pending[0], mode=party_mod.Mode.COORDINATED,
                joint=list(self.pending), rng=self.rng)
        else:
            nxt, _healed, _done = party_mod.step(
                before, action, mode=party_mod.Mode.PICKUP, rng=self.rng)

        laff_lost = sum(max(0, b.laff - a.laff)
                        for b, a in zip(before.toons, nxt.toons))
        went_sad = sum(1 for b, a in zip(before.toons, nxt.toons)
                       if b.laff > 0 and a.laff <= 0)
        from ..search import party_search as ps

        reward = ps.round_reward(
            self.objective, laff_lost, ps._spent(before, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win(),
            toons_lost=went_sad,
            cogs_remaining=before.cogs_remaining)

        # PRECISION. `round_reward` charges for laff and for gags spent,
        # and nothing at all for damage thrown past what a cog had left,
        # so the policy has never been told that overkill is a thing --
        # `waste` appeared nowhere in this file. It shows: on a board
        # with four cogs asleep the policy's whole shortlist was
        # Birthday Cake, and it will spend one on a 20hp Name Dropper as
        # readily as on a 196hp Mr. Hollywood, because both pay the same.
        #
        # Charged here, in the REWARD, rather than in the ranker. A
        # scorer weight only re-orders candidates the policy already
        # proposes; teaching it in training changes what gets proposed,
        # which is the half that was actually broken.
        #
        # `waste_penalty` scales by scarcity, so a gag that is the only
        # thing that kills pays almost nothing and the same gag into a
        # nearly-dead cog pays nearly in full.
        # A PINK SLIP COSTS THE ROUND'S ACTION, and the reward has never
        # said so. `round_reward` charges laff and gags; fires are
        # priced only in `_quick_score`, via FIRE_PRICE, which the
        # policy never sees. So the fire logits learn that a slip is an
        # unmissable kill and nothing teaches restraint.
        #
        # It shows badly: a solo VP with ten slips falls from 49.5% to
        # 0.0%, dying three rounds sooner, with the policy's whole top
        # FOUR being fires -- so no scorer weight can reach a gag,
        # because none is on the shortlist.
        #
        # The cost is real and simple. Firing removes ONE cog while a
        # group Lure neutralises four, for the same action. Charging it
        # here teaches WHEN a guaranteed kill is worth more than the
        # round, which is the thing `--fire-fraction` was reaching for
        # and overshot.
        #
        # MEASURED, AND IT DOES NOT WORK. Two runs at 8 and 25, same
        # seed and mix as the shipped policy, solo VP at 8 cogs a round:
        #
        #     slips              0      5     10
        #     shipped        49.5%  22.0%   0.0%
        #     fire_cost 8    31.5%   1.5%   0.0%
        #     fire_cost 25   28.0%  15.5%   3.5%
        #
        # It removes the collapse -- fires fall from 100% of the
        # shortlist to 0% and 31% -- and takes about twenty points off
        # the base rate with it, measured with NO slips in hand, so the
        # damage is to general play rather than to slip discipline.
        # Worse, it does not fix the presenting problem either: fc25
        # still slides 28.0 -> 15.5 -> 3.5 as slips are added.
        #
        # The likelier story is that slip-carrying boards are simply
        # UNDER-TRAINED -- `--fire-fraction` is 0.15, so a board with
        # ten of them is a thin slice of the distribution and the policy
        # is unfamiliar rather than wrongly incentivised. Pricing cannot
        # fix unfamiliarity; exposure might. Left here at 0.0.
        if self.fire_cost:
            spent = ps._fires_spent(before, nxt)
            if spent:
                reward -= self.fire_cost * float(spent)

        if self.precision:
            # The joint plan in coordinated mode, this seat's single
            # action otherwise -- `_waste_fraction` takes a plan either
            # way, one entry per toon.
            plan = (list(self.pending) if self.coordinated
                    else [None if action.is_pass else action])
            try:
                reward -= self.precision * ps._waste_fraction(before, plan)
            except Exception:           # pragma: no cover - defensive
                pass

        # POTENTIAL-BASED SHAPING on incoming damage.
        #
        # The problem it addresses, measured: the policy collapses onto
        # Throw -- 49% of its gags against the search's 32% -- and
        # essentially never heals (1.1% vs 8.5%), traps (0.0% vs 3.8%)
        # or drops (2.1% vs 9.5%). Throw is universally held, always
        # legal and always pays immediately; a heal spends a gag and a
        # turn to prevent damage that would have arrived later, so its
        # advantage is negative early and it is never explored enough to
        # learn otherwise.
        #
        # Raising the entropy coefficient does not touch this. Swept
        # 0.01 / 0.04 / 0.10, the gag entropy came back 3.79 every time,
        # because the bonus is over 246 ACTIONS and the policy satisfies
        # it by spreading across targets while still choosing Throw.
        #
        # Shaping with the potential Phi(s) = -shaping * expected
        # incoming damage pays the agent NOW for a cog it put to sleep
        # or killed. Potential-based, in the Ng et al. sense --
        # F = gamma*Phi(s') - Phi(s) -- so it leaves the optimal policy
        # unchanged and only changes how quickly the credit arrives.
        # That guarantee is the whole reason to prefer it over simply
        # handing out a bonus for luring, which would distort what the
        # agent is optimising.
        self.rounds += 1
        self.floor_rounds += 1

        # THE FLOOR IS NOT THE EPISODE. Winning a facility battle with
        # floors left moves to the next one instead of ending, which is
        # what makes a conserved gag worth conserving: it gets spent
        # later in the same return. Without this the horizon was a price
        # with no payoff and PPO correctly ignored it.
        if (nxt.is_win() and nxt.kind in ("facility", "vp", "ceo")
                and self.plan is not None and not self.plan.exhausted):
            nxt = self._next_floor(nxt)
            self.floor_rounds = 0

        self.state = nxt
        stalled = self.floor_rounds >= self.max_rounds
        # A hard episode ceiling as well, so a pathological facility
        # cannot run forever: generous enough that a five-floor building
        # finishes well inside it.
        overrun = self.rounds >= self.max_rounds * 6
        done = nxt.is_terminal() or stalled or overrun

        # SHAPING IS APPLIED HERE, AFTER THE FLOOR ADVANCE, and keyed on
        # `done` rather than on `nxt.is_terminal()`. It used to sit above
        # both, and a floor win makes `is_terminal()` true while the
        # EPISODE continues -- so the potential was zeroed and then
        # restarted at the next floor, and the episode sum picked up a
        # fresh -Phi(s_0) every floor instead of once.
        #
        # That breaks the telescoping the Ng et al. guarantee rests on,
        # which means the old threat shaping was not potential-based
        # across a building at all: it was changing the objective, not
        # only the speed of credit. Worth knowing, because that shaping
        # was measured as "moved behaviour substantially, moved outcomes
        # not at all" -- a result now taken with a defective term.
        # tests/test_survival_shaping.py pins the telescoping.
        if self.shaping:
            before_threat = ps.expected_incoming(before)
            after_threat = 0.0 if done else ps.expected_incoming(nxt)
            reward += self.shaping * (before_threat
                                      - self.gamma * after_threat)

        reward += self._survival_term(before, nxt, done)
        info = {"win": bool(nxt.is_win()), "rounds": self.rounds,
                "floor": self.floor,
                "truncated": (stalled or overrun) and not nxt.is_terminal(),
                "partial": False}
        if not done:
            self._begin_round()
        return (encode(nxt, self.actor, self.pending),
                legal_mask(nxt, self.actor), reward, done, info)


# ---------------------------------------------------------------------
# Position sampling. Shared with tools/gen_party_data.py's intent: only
# gags and cogs whose tables are complete, so a [TODO] cell cannot raise
# mid-episode and bias the sample toward whatever happens to be filled.

SAFE_COGS = [("bean_counter", "cashbot", 4, 8),
             ("number_cruncher", "cashbot", 5, 9),
             ("loan_shark", "cashbot", 7, 11),
             ("double_talker", "lawbot", 3, 7),
             ("ambulance_chaser", "lawbot", 4, 8),
             ("backstabber", "lawbot", 5, 9),
             ("spin_doctor", "lawbot", 6, 10),
             ("legal_eagle", "lawbot", 7, 11),
             ("head_hunter", "bossbot", 6, 10),
             ("two_face", "sellbot", 6, 10),
             ("the_mingler", "sellbot", 7, 11)]

# Levels 1-2, which SAFE_COGS does not reach -- its lowest is 3. A
# difficulty 1 building is level 1-3 cogs, so without these the low
# difficulties could not be built at all.
#
# Kept SEPARATE from SAFE_COGS rather than merged into it, so street
# positions and the fixed evaluation set are byte-identical to previous
# runs and their returns stay comparable. Only facilities draw from
# both pools.
#
# Every level listed here was checked by running a cog phase 40 times at
# each one; all eight are complete over their whole published range.
LOW_COGS = [("flunky", "bossbot", 1, 5),
            ("cold_caller", "sellbot", 1, 5),
            ("short_change", "cashbot", 1, 5),
            ("bottom_feeder", "lawbot", 1, 5),
            ("pencil_pusher", "bossbot", 2, 6),
            ("telemarketer", "sellbot", 2, 6),
            ("penny_pincher", "cashbot", 2, 6),
            ("bloodsucker", "lawbot", 2, 6)]


def _usable(track: Track, level: int) -> bool:
    try:
        gag = data.gag(track, level)
        if track == Track.TOON_UP:
            gag.heal_at(1.0, False)
        elif track != Track.LURE:
            gag.damage_at(1.0, False)
        gag.prop_accuracy(organic=False)
        return True
    except (NotImplementedError, ValueError, KeyError):
        return False


USABLE = {(t, l) for t in TRACKS for l in range(1, 8) if _usable(t, l)}


def _trim_to_pouch(counts, capacity, rng):
    """Drop gags until the loadout fits the pouch.

    Level 7s are exempt and never trimmed -- [CONFIRMED], they are
    carried outside the pouch.

    Trims from the lowest levels first: a toon short on room drops
    Cupcakes before Wedding Cakes, which is what a player does.
    """
    counts = dict(counts)
    while gags_mod.pouch_total(counts) > capacity:
        inside = [k for k, v in counts.items()
                  if v > 0 and k[1] < gags_mod.POUCH_EXEMPT_LEVEL]
        if not inside:
            break
        lowest = min(k[1] for k in inside)
        key = rng.choice([k for k in inside if k[1] == lowest])
        counts[key] -= 1
        if counts[key] <= 0:
            del counts[key]
    return counts


def random_toon(rng) -> ToonState:
    """A toon, deliberately not always a maxed one.

    The first version trained every track to 4-7 and handed out the top
    gags of each, so every toon was late-game and every puzzle had the
    same texture. Real pouches are lopsided: a track at experience 2
    while another is maxed, a pouch of nothing but level 1-3, one track
    only, or no attack gags at all -- which forces Lure, Trap or a pass
    and is exactly the position worth being able to solve.

    Training experience matters beyond which gags are owned: it feeds
    `calc_track_exp`, so an unmaxed track is genuinely less accurate,
    not merely smaller.
    """
    # THROW AND SQUIRT ALWAYS. Every toon starts with both, so a
    # one-track toon is not a hard puzzle, it is an impossible one --
    # the same error as a trapped cog with no trap level, generating a
    # game that does not exist.
    #
    # And never all seven: a toon picks six at most, so the extras come
    # from the other five tracks and stop at four.
    tracks = [Track.THROW, Track.SQUIRT]
    others = [t for t in TRACKS if t not in tracks]
    tracks += rng.sample(others, rng.randint(0, 4))

    counts, exp = {}, {}
    for track in tracks:
        trained = rng.randint(1, 7)                  # UNMAXED tracks
        exp[track] = trained
        low = 1 if rng.random() < 0.35 else max(1, trained - 3)
        for level in range(low, trained + 1):
            if (track, level) in USABLE and rng.random() < 0.75:
                # Capped by what `trained` allows, not by a maxed track.
                cap = gags_mod.carry_limit(track, level, trained) or 1
                counts[(track, level)] = rng.randint(1, min(cap, 5))

    # Sometimes empty the damage tracks. Note this is a spent POUCH and
    # not an untrained track -- a toon always owns Throw and Squirt, so
    # the only way to hold no attack gag is to have used them all, which
    # is a position real play reaches constantly.
    if rng.random() < 0.10:
        counts = {k: v for k, v in counts.items()
                  if k[0] in (Track.LURE, Track.TRAP, Track.TOON_UP)}

    # POUCH CAPACITY, chosen per toon rather than per street. 62% of
    # generated toons would not have fit a starting 20-gag pouch and 49%
    # not a Medium, so every toon implicitly carried a late-game bag
    # whatever else was sampled about them.
    #
    # Uniform over the confirmed table. Correlating it with training
    # would be more realistic -- pouch upgrades and gag training both
    # come from progression, so a maxed toon with a 20-gag pouch is not
    # a real toon -- and is a refinement deliberately not taken here.
    capacity = rng.choice(sorted(data.POUCH_CAPACITIES.values()))
    counts = _trim_to_pouch(counts, capacity, rng)

    if not counts:
        # The empty-roll fallback. It used to reset to Throw alone,
        # which quietly rebuilt the impossible one-track toon this
        # function exists to avoid -- 17 of 400 draws came out that way
        # even after the sampling above was fixed. A fallback that
        # violates the invariant is worse than no fallback.
        counts = {(Track.THROW, 4): 2, (Track.SQUIRT, 4): 2}
        exp = {Track.THROW: 5, Track.SQUIRT: 5}
    max_laff = rng.choice([15, 25, 40, 50, 65, 80, 95, 110, 125, 137])
    organic = frozenset()
    if rng.random() < 0.4:
        organic = frozenset([rng.choice(list(exp))])
    return ToonState(max(1, int(max_laff * rng.uniform(0.15, 1.0))), max_laff,
                     exp, counts, organic, pouch_capacity=capacity)


# The hardest cogs that are actually playable, level 12 included.
#
# Mr Hollywood and Robber Baron work at 12 (196 hp). Their Beguile,
# Finger Wag, Embezzle and Synergy carry no accuracy or frequency and
# that is DELIBERATE, not a gap: they are `modeled=False` signature
# attacks that do not occur in regular cog battles, and
# `pick_cog_attack` iterates `modeled_attacks`. The remaining attacks
# already sum to 100% frequency at every level, which is the check that
# proves nothing is missing.
#
# The Big Cheese is the one genuine hole and is excluded: its Glower
# Power fires 50% of the time and has [TODO] accuracy. It cannot be
# derived from the same attack on other cogs -- accuracy is per-cog, and
# shared attacks disagree at the same level 149 times against 19
# agreements, with Glower Power itself running 50->90 across Head
# Hunter's levels and a flat 95 on Tightwad.
BRUTAL_COGS = [("mr_hollywood", "sellbot", 12),
               ("robber_baron", "cashbot", 12),
               ("the_mingler", "sellbot", 11),
               ("loan_shark", "cashbot", 11),
               ("legal_eagle", "lawbot", 11),
               ("head_hunter", "bossbot", 10)]


def hard_position(rng) -> BattleState:
    """One toon against a wall of cogs.

    The position distribution IS the curriculum, and the default sampler
    never forces Lure: with several toons and mixed cogs you can usually
    out-damage the board, so "kill the biggest thing" is a winning habit
    and the agent learns it. Trained only on that, the policy under-uses
    Lure -- caught on a real position where it threw for a kill while
    the search re-lured, and the search was right.

    Alone against three or four cogs of 132-156 hp there is no
    out-damaging anything. Every round they all swing, so the only way
    to survive long enough to spend a pouch is to stop them swinging.
    Lure stops being one option among many and becomes the game.
    """
    cogs = []
    for _ in range(rng.randint(3, MAX_COGS)):
        key, dept, level = rng.choice(BRUTAL_COGS)
        full = data.cog_max_hp(level)
        cogs.append(CogState(key, dept, level,
                             rng.randint(full // 2, full), full))
    toon = random_toon(rng)
    # A pouch worth defending: a starved one just loses, and teaches
    # nothing but that the position was hopeless.
    toon.laff = max(40, toon.max_laff // 2)
    return BattleState(toons=[toon], cogs=cogs)


def strange_position(rng) -> BattleState:
    """Positions a fresh battle never produces.

    Training only on round-one boards teaches round-one habits. Real
    advice is asked for mid-fight, where a cog is already lured with two
    rounds left, a trap is sitting armed, someone is one hit from sad,
    or the pouch has been picked over and the cheap gags are gone.

    These are reachable states, not invented ones -- every modifier here
    is something the simulator itself produces a few rounds in.
    """
    state = default_position(rng) if rng.random() < 0.5 else hard_position(rng)

    for cog in state.cogs:
        roll = rng.random()
        if roll < 0.25:
            cog.status.apply_lure(rng.choice([50, 60, 70, 80]),
                                  rng.randint(1, 4), rng.randint(2, 4))
        elif roll < 0.40:
            # `trap_level` too, not just the flag. Setting `trapped`
            # alone builds a state the simulator cannot reach: the first
            # Lure to spring it looks the trap's damage up by level and
            # dies on `no gag at trap level None`. A position generator
            # that can emit unreachable states is worse than one that is
            # merely narrow -- it trains on a game that does not exist.
            cog.status.trapped = True
            cog.status.trap_level = rng.randint(1, 6)
        if rng.random() < 0.3:
            cog.hp = max(1, int(cog.hp * rng.uniform(0.1, 0.6)))

    for toon in state.toons:
        if rng.random() < 0.35:
            toon.laff = max(1, int(toon.max_laff * rng.uniform(0.05, 0.25)))
        if rng.random() < 0.4 and toon.gag_counts:
            # A picked-over pouch: the cheap gags go first in real play.
            counts = dict(toon.gag_counts)
            for key in sorted(counts, key=lambda k: k[1])[:rng.randint(1, 3)]:
                counts[key] = 0
            toon.gag_counts = {k: v for k, v in counts.items() if v > 0}
    if not any(t.gag_counts for t in state.toons):
        return default_position(rng)
    state.round_num = rng.randint(0, 5)
    return state


def combo_position(rng) -> BattleState:
    """A battle where the Trap+Lure payoff is ONE move away.

    A REVERSE CURRICULUM, and it is not reward shaping: no reward is
    invented and no strategy is encoded, only the distribution of
    starting states moves closer to the payoff. The agent still has to
    find the move and still gets paid only what the simulator pays.

    The problem it solves is exploratory rather than temporal. PPO's
    critic already sees far -- GAE at lambda 0.95 averages over roughly
    seventeen rounds, far longer than a battle -- but it estimates value
    under its OWN policy, so a line the policy never plays never enters
    the data. Measured on the shipped sampler, only 4.6% of positions
    have an armed trap AND a lure in hand, which is the state where
    springing pays immediately. With 246 actions to choose between, that
    reward is essentially never experienced.

    Start there instead, and the agent can learn "lure when a trap is
    armed" from direct reward. Learning to LAY the trap is then one step
    further back, which is the standard way round a sparse sequence.
    """
    key, dept, lo, hi = rng.choice(SAFE_COGS)
    level = rng.randint(lo, hi)
    full = data.cog_max_hp(level)
    cogs = [CogState(key, dept, level, rng.randint(full // 2, full), full)]
    for _ in range(rng.randint(0, 2)):
        k2, d2, l2, h2 = rng.choice(SAFE_COGS)
        lv2 = rng.randint(l2, h2)
        f2 = data.cog_max_hp(lv2)
        cogs.append(CogState(k2, d2, lv2, rng.randint(f2 // 3, f2), f2))

    # The trap is already down on the first cog, and a Lure is in hand.
    trap_level = rng.randint(3, 6)
    cogs[0].status.trapped = True
    cogs[0].status.trap_level = trap_level

    counts = {(Track.LURE, rng.choice([3, 4, 5, 6])): rng.randint(1, 2)}
    for track in rng.sample([Track.THROW, Track.SQUIRT], rng.randint(1, 2)):
        counts[(track, rng.choice([4, 5, 6]))] = rng.randint(1, 3)
    exp = {t: rng.randint(4, 7) for t, _l in counts}
    max_laff = rng.choice([50, 65, 80, 95, 110])
    toon = ToonState(max(10, int(max_laff * rng.uniform(0.25, 0.9))),
                     max_laff, exp, counts)
    toons = [toon] + [random_toon(rng) for _ in range(rng.randint(0, 2))]
    return BattleState(toons=toons, cogs=cogs)


def mixed_position(rng, hard_fraction: float = 0.5,
                   strange_fraction: float = 0.25,
                   combo_fraction: float = 0.0) -> BattleState:
    """Blend, so no single shape becomes the whole of what is learned."""
    roll = rng.random()
    if roll < combo_fraction:
        state = combo_position(rng)
    else:
        roll -= combo_fraction
        if roll < strange_fraction:
            state = strange_position(rng)
        elif roll < strange_fraction + hard_fraction:
            state = hard_position(rng)
        else:
            state = default_position(rng)
    state.cogs_remaining = sample_horizon(rng)
    state.kind = "facility" if state.cogs_remaining else "street"
    return state


def sample_horizon(rng) -> int:
    """How many cogs are still coming after this fight.

    Assigned here rather than inside each sampler so every position shape
    is seen at every horizon -- a feature that only ever varies with, say,
    cog level teaches the agent the wrong thing to condition on.

    Half of all positions are the last fight, which is the street battle
    the solver has always modelled and the case the horizon must not
    disturb. The rest are building-shaped: floors of four to five cogs,
    up to a five-floor building and its boss.
    """
    if rng.random() < 0.5:
        return 0
    return rng.randint(1, 30)


# Experience a well-played track earns per playground of ownership.
# [ASSUMED], and the only invented number in the level model -- the
# SHAPE comes from `GAG_UNLOCK_EXP`, which is [CONFIRMED].
#
# That shape is what makes this worth doing rather than picking levels
# by hand. Levels 2-4 cost 400-800 experience in total and levels 5, 6
# and 7 cost 2000, 6000 and 10000, so a freshly earned track rockets to
# 4 and then stalls. A linear model of "newer track means lower level"
# had a Dreamland toon holding level 1-2 Drop as the ordinary case,
# which is not what a played toon looks like.
# Experience a well-played track earns during each PLAYGROUND, indexed
# by `facility.PROGRESSION[...]["stage"]`.
#
# Rising rather than flat, because a stage in Toontown Central and a
# stage in Dreamland are not the same amount of experience: gag
# experience comes from the cogs you beat, and those run level 1-3 on
# the first streets and 6-9 on the last. A flat rate handed Toontown
# Central toons level 7 gags, which is not a toon that exists.
STAGE_EXP = {1: 60, 2: 200, 3: 500, 4: 900, 5: 1800, 6: 3500}


def track_level(track, available_from: int, stage: int,
                grind: float, usage: float) -> int:
    """Training level from experience, read off the confirmed table."""
    earned = sum(STAGE_EXP[s] for s in range(available_from, stage + 1))
    earned *= grind * usage
    thresholds = gags_mod.GAG_UNLOCK_EXP[track]
    level = 1
    for i, need in enumerate(thresholds):
        if earned >= need:
            level = i + 1
    return max(1, min(7, level))


def toon_for_street(rng, street, hardship: float = 0.0) -> ToonState:
    """A toon who could plausibly be fighting on this street.

    `hardship` in [0, 1] squeezes the toon toward the bottom of what the
    street allows: laff to the floor of the band, and grind down, which
    is what actually lowers gag levels. It is a SYNTHETIC DIFFICULTY
    KNOB, not a claim about the game -- no wiki page says how many
    underlevelled toons attempt a Dreamland building. See
    `scrappy_position` for why it exists.

    The correction that made facility training data worth having. The
    sampler used to build a party and then pick a street, which put
    15-laff toons carrying 20-gag starting pouches into Dreamland
    buildings -- toons that have never left Toontown Central. Half the
    facility episodes were that, and neither the search nor the policy
    could clear a floor.

    Now the street comes first and the toon is built to match: laff and
    pouch at or above what the previous playground's ToonTasks award,
    and tracks limited to those earned by then.
    """
    _name, playground, _levels = street
    profile = facility.PROGRESSION[playground]
    stage = profile["stage"]

    low, high = profile["laff"]
    if hardship > 0.0:
        # Squeeze the band toward its floor rather than going below it:
        # the floor is what the previous playground's ToonTasks award, so
        # dropping under it would build a toon who could not have reached
        # this street at all -- the exact incoherence `facility_position`
        # was written to stop.
        high = max(low, low + int(round((high - low) * (1.0 - hardship))))
    max_laff = rng.randint(low, high)
    reach = (max_laff - low) / float(high - low) if high > low else 0.5

    # GRIND -- how hard this toon has played, tied to where their laff
    # sits in the band, because both come from playing. Deliberately
    # noisy rather than a function of laff: the wiki's own laff table
    # awards +17 for fishing, gardening, racing and golf, none of which
    # grants a single point of gag experience. So a toon can fish their
    # way to the top of the band with mediocre gags, and a cog grinder
    # can sit mid-band holding level 7s. Both are real, and a tight
    # coupling would erase them.
    grind = (0.35 + 1.75 * reach) * math.exp(rng.gauss(0.0, 0.35))
    # Grind is what sets gag levels, so this is the half of `hardship`
    # that produces "mediocre gags" -- laff alone would just make a
    # well-equipped toon fragile.
    grind *= (1.0 - 0.65 * hardship)

    have = facility.sample_tracks(rng)
    exp = {}
    for track, available_from in have.items():
        if available_from > stage:
            continue                     # not earned yet at this street
        # USAGE -- which tracks this toon actually trained. The spread
        # is the point: it is what separates the earnest trainer from
        # someone who has left a track sitting where they found it.
        usage = math.exp(rng.gauss(0.0, 0.55))
        exp[track] = track_level(track, available_from, stage, grind,
                                 usage)

    # Pouch: at least what the previous playground awarded, sometimes
    # more for a toon who pushed further before coming back.
    sizes = sorted(data.POUCH_CAPACITIES.values())
    allowed = [c for c in sizes if c >= profile["pouch"]] or [sizes[-1]]
    capacity = allowed[0] if rng.random() < 0.6 else rng.choice(allowed)

    toon = ToonState(max_laff, max_laff, exp, {}, frozenset(),
                     pouch_capacity=capacity)
    restock(toon, rng)
    return toon


def restock(toon, rng, capacity=None) -> None:
    """Fill a pouch the way a toon entering a building has one.

    `random_toon` models a pouch part-way through a street battle: one
    to five of each gag, with a quarter of the trained levels empty.
    Right for a single fight, wrong for the start of a building, where
    you have just restocked at the playground. Facility parties were
    averaging 40 gags against 17 cogs of level 6-9 -- about two gags per
    cog, where two rarely kills one -- so the run died of an empty pouch
    on floor one and cleared 0.4 floors.

    RESPECTS THE POUCH CAP, which the first version did not. Filling
    every gag to its own `max_carry` produced parties holding 378 gags;
    `POUCH_CAPACITIES` is [CONFIRMED] as a cap on the TOTAL across all
    tracks, 80 at the very most, and `validate_loadout` would have
    rejected every one of those loadouts. The data was already in the
    repo and the first attempt simply did not consult it.

    TRAINING IS NOT TOUCHED, only quantity: which tracks a toon has and
    how far each is trained stays as sampled, so the lopsided, unmaxed
    pouches `random_toon` exists to produce survive. A toon with
    mediocre gags still has mediocre gags -- just a full bag of them.
    """
    owned = []
    for track, trained in toon.track_exp.items():
        for level in range(1, trained + 1):
            if (track, level) in USABLE:
                owned.append((track, level))
    if not owned:
        return
    if capacity is None:
        capacity = toon.pouch_capacity

    counts = {}
    # Level 7s sit outside the pouch entirely, one each.
    for key in owned:
        if key[1] >= gags_mod.POUCH_EXEMPT_LEVEL:
            counts[key] = 1

    # TOP DOWN, which is how the owner describes a facility loadout:
    # concentrate at the top, then fill in downward until the pouch is
    # full. A weighted random draw spread the bag thinly across every
    # level instead, which is not what anyone walks into a building
    # with. `_trim_to_pouch` drops the lowest first, so the two are
    # exact inverses.
    inside = sorted((k for k in owned
                     if k[1] < gags_mod.POUCH_EXEMPT_LEVEL),
                    key=lambda k: -k[1])
    for key in inside:
        if gags_mod.pouch_total(counts) >= capacity:
            break
        room = capacity - gags_mod.pouch_total(counts)
        # The limit the toon's OWN training allows, not the fully
        # upgraded one. Reading `max_carry` here handed every toon a
        # maxed allowance of every gag whatever their progression, which
        # over-supplied precisely the under-trained parties
        # `scrappy_position` exists to model: it lowered laff and gag
        # LEVELS and then gave out maxed COUNTS of what was left.
        want = min(gags_mod.carry_limit(key[0], key[1],
                                        toon.track_exp.get(key[0], 0)),
                   room)
        if want > 0:
            counts[key] = want
    toon.gag_counts = {k: v for k, v in counts.items() if v > 0}


def facility_position(rng) -> BattleState:
    """A facility floor, built street first.

    The order is the whole point. Building a party and then choosing a
    street put 15-laff toons with 20-gag starting pouches into Dreamland
    buildings -- toons that have never left Toontown Central -- and half
    the facility episodes were that. Neither the search nor the policy
    could clear a floor, and no comparison between them meant anything.

    `BattleEnv.reset` reads `state.street` and builds the building from
    the same street, so the matchup stays coherent.
    """
    street = facility.sample_street(rng)
    # Buildings are group content. The 1-4 spread came from
    # `mixed_position`, which models a street battle, and made 57% of
    # facility episodes solo.
    party = [toon_for_street(rng, street)
             for _ in range(rng.randint(2, 4))]
    state = BattleState(toons=party, cogs=[], kind="facility",
                        street=street[0])
    return state


SCRAPPY_HARDSHIP = 0.8


def scrappy_position(rng) -> BattleState:
    """A facility floor for a party that has no business being there.

    WHY THIS EXISTS. On the standard facility sampler the two agents are
    tied -- 65.9% against 65.0% over three sets, inside the noise -- and
    every lever tried against that tie has come back null. The tie may be
    a property of the TASK rather than of the agents: with a maxed pouch
    there is usually a gag that simply removes the problem, so most
    positions have many good answers and it does not matter much which
    one you pick. That is exactly what the CRN experiment measured -- the
    agents disagree on 95% of rounds and three quarters of the
    disagreements are worth under a point.

    Take the shortcuts away and the support tracks have to carry the
    fight. With low laff you cannot trade hits, and with mediocre gags
    you cannot one-shot a cog or lean on Sound to clear a floor, so
    Toon-Up and Lure stop being optional. Those are precisely the two
    tracks every scorer here prices worst: `_quick_score` pays for damage
    landed, a heal is capped at the target's missing laff, and
    `prevented` is worth 2.0 a point against a kill's flat 120.

    So this is a task where the evaluator's known weaknesses should
    finally cost something measurable, and where a difference between the
    agents has room to appear.

    SYNTHETIC, and labelled as such. The wiki says nothing about how
    underlevelled a party attempting a building typically is;
    `SCRAPPY_HARDSHIP` is a dial, not a datum. It never goes below the
    laff floor the previous playground awards, so every toon it builds
    could really have reached the street it is on.

    THE PARTY IS CONSTRAINED TO HOLD THE SUPPORT TRACKS, and the first
    version was not. Hardship lowers `grind`, and grind decides how many
    tracks a toon ever trained, so squeezing it stripped exactly the
    tracks this regime is meant to lean on: Lure fell 34% -> 23% and
    Toon-Up 43% -> 32%. A party that has no Lure cannot be made to
    demonstrate anything about Lure. So the pooled party must hold both,
    and the sampler redraws until it does.

    That is a bias, stated rather than hidden: these are underlevelled
    parties that DID train support, not a random sample of underlevelled
    parties.

    WHAT IT SHOWED, AND IT WAS NOT WHAT IT WAS BUILT FOR. Over 120
    buildings, both agents:

        standard   climb 60.8%   search 60.0%   toons lost 1.02 / 0.99
        scrappy    climb 50.0%   search 50.0%   toons lost 1.52 / 1.47

    The task got 10 points harder in the intended way -- Sound 15.7% ->
    11.1%, Toon-Up 5.4% -> 7.9% -- and the agents stayed exactly level.
    So the tie is NOT an artifact of an easy task, which is what this
    regime was written to test. That is a stronger result than the
    original tie: two agents that track each other as the ground moves
    are equal in a way two agents that merely score the same are not.

    The oddity worth chasing: LURE USE DOES NOT MOVE, 11.9% -> 12.0%,
    although the party pools Lure far more often here (59% -> 77%) and
    the regime exists because you cannot trade hits. Both agents answer a
    harder fight by healing more rather than by preventing more, and
    both share `_quick_score`'s `prevented` term. That points at the
    shared evaluator rather than at either agent.
    """
    street = facility.sample_street(rng)
    for _ in range(40):
        party = [toon_for_street(rng, street, hardship=SCRAPPY_HARDSHIP)
                 for _ in range(rng.randint(2, 4))]
        pooled = {track for toon in party
                  for (track, _level), n in toon.gag_counts.items()
                  if n > 0 and toon.track_exp.get(track, 0) > 0}
        if {Track.LURE, Track.TOON_UP} <= pooled:
            break
    return BattleState(toons=party, cogs=[], kind="facility",
                       street=street[0])


def default_position(rng) -> BattleState:
    cogs = []
    for _ in range(rng.randint(1, MAX_COGS)):
        key, dept, lo, hi = rng.choice(SAFE_COGS)
        level = rng.randint(lo, hi)
        full = data.cog_max_hp(level)
        cogs.append(CogState(key, dept, level,
                             rng.randint(max(1, full // 4), full), full))
    return BattleState(toons=[random_toon(rng)
                              for _ in range(rng.randint(1, MAX_TOONS))],
                       cogs=cogs)
