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

import random
from typing import List, Optional, Tuple

from .. import data, party as party_mod, simulator
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

PASS_INDEX = 0
OBS_DIM = MAX_COGS * 8 + MAX_TOONS * (3 + 49) + 3


def action_at(index: int) -> Optional[Action]:
    """The action for a policy index. `None` is the pass."""
    if index == PASS_INDEX:
        return Action(track=None, level=0, target_index=None)
    return ACTIONS[index]


def encode(state: BattleState) -> List[float]:
    """Fixed-width observation.

    Cogs and toons are padded to four with an `alive` flag rather than
    pooled, because neither is interchangeable: targets are indexed, and
    `outcomes.state_key` keys on every toon in order for the same
    reason.
    """
    out: List[float] = []
    for i in range(MAX_COGS):
        if i < len(state.cogs) and not state.cogs[i].status.is_dead:
            cog = state.cogs[i]
            out += [1.0,
                    cog.level / 12.0,
                    cog.hp / max(1, cog.max_hp),
                    cog.max_hp / 200.0,
                    1.0 if cog.status.lured else 0.0,
                    1.0 if cog.status.trapped else 0.0,
                    min(cog.status.lure_rounds_remaining, 8) / 8.0,
                    1.0 if cog.status.is_dead else 0.0]
        else:
            out += [0.0] * 8

    for i in range(MAX_TOONS):
        if i < len(state.toons) and state.toons[i].laff > 0:
            toon = state.toons[i]
            out += [1.0,
                    toon.laff / max(1, toon.max_laff),
                    toon.max_laff / 137.0]
            for track in TRACKS:
                for level in range(1, 8):
                    out.append(min(toon.gag_counts.get((track, level), 0),
                                   8) / 8.0)
        else:
            out += [0.0] * (3 + 49)

    out += [min(state.round_num, 12) / 12.0,
            len(state.active_cogs()) / MAX_COGS,
            len(state.active_toons()) / MAX_TOONS]
    return out


def legal_mask(state: BattleState) -> List[bool]:
    """Which indices the agent may pick this round.

    The pass is always legal here. The search cannot say that -- see the
    module docstring -- and this environment can, because it memoises
    nothing.
    """
    mask = [False] * len(ACTIONS)
    mask[PASS_INDEX] = True
    if not state.active_toons():
        return mask
    toon = state.toons[0]
    live = [i for i, c in enumerate(state.cogs) if not c.status.is_dead]
    for index in range(1, len(ACTIONS)):
        action = ACTIONS[index]
        if toon.gag_counts.get((action.track, action.level), 0) <= 0:
            continue
        if toon.track_exp.get(action.track, 0) <= 0:
            continue
        group = simulator.is_group_action(action.track, action.level)
        if group != (action.target_index is None):
            continue          # a group gag has no single target, and vice versa
        if action.target_index is not None:
            if action.target_index not in live:
                continue
            if action.track == Track.TRAP:
                status = state.cogs[action.target_index].status
                if status.trapped or status.lured:
                    continue
        mask[index] = True
    return mask


class BattleEnv:
    """One battle. `reset()` starts a new one, `step()` plays a round."""

    def __init__(self, objective=None, rng=None, max_rounds: int = 20,
                 sampler=None):
        self.objective = objective or objective_mod.BALANCED
        self.rng = rng or random.Random()
        self.max_rounds = max_rounds
        self.sampler = sampler or default_position
        self.state: Optional[BattleState] = None
        self.rounds = 0

    def reset(self) -> Tuple[List[float], List[bool]]:
        while True:
            self.state = self.sampler(self.rng)
            if not self.state.is_terminal():
                break
        self.rounds = 0
        return encode(self.state), legal_mask(self.state)

    def step(self, index: int):
        """-> (observation, mask, reward, done, info)."""
        before = self.state
        action = action_at(index)
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
            toons_lost=went_sad)

        self.state = nxt
        self.rounds += 1
        done = nxt.is_terminal() or self.rounds >= self.max_rounds
        info = {"win": bool(nxt.is_win()), "rounds": self.rounds,
                "truncated": self.rounds >= self.max_rounds
                and not nxt.is_terminal()}
        return encode(nxt), legal_mask(nxt), reward, done, info


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


def random_toon(rng) -> ToonState:
    tracks = rng.sample(TRACKS, rng.randint(3, 5))
    counts, exp = {}, {}
    for track in tracks:
        trained = rng.randint(4, 7)
        exp[track] = trained
        for level in range(max(1, trained - 3), trained + 1):
            if (track, level) in USABLE and rng.random() < 0.8:
                cap = data.gag(track, level).max_carry or 1
                counts[(track, level)] = rng.randint(1, min(cap, 4))
    if not counts:
        counts, exp = {(Track.THROW, 4): 2}, {Track.THROW: 5}
    max_laff = rng.choice([50, 65, 80, 95, 110, 125, 137])
    return ToonState(max(1, int(max_laff * rng.uniform(0.2, 1.0))), max_laff,
                     exp, counts,
                     frozenset([rng.choice(tracks)]) if rng.random() < 0.4
                     else frozenset())


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


def mixed_position(rng, hard_fraction: float = 0.5) -> BattleState:
    """Blend, so the easy case is not forgotten while the hard one is
    learned."""
    if rng.random() < hard_fraction:
        return hard_position(rng)
    return default_position(rng)


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
