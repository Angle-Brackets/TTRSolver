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
OBS_DIM = MAX_COGS * 9 + MAX_TOONS * (3 + 49) + 3


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
            out += [0.0] * 9

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
                cap = data.gag(track, level).max_carry or 1
                counts[(track, level)] = rng.randint(1, min(cap, 5))

    # Sometimes empty the damage tracks. Note this is a spent POUCH and
    # not an untrained track -- a toon always owns Throw and Squirt, so
    # the only way to hold no attack gag is to have used them all, which
    # is a position real play reaches constantly.
    if rng.random() < 0.10:
        counts = {k: v for k, v in counts.items()
                  if k[0] in (Track.LURE, Track.TRAP, Track.TOON_UP)}

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
                     exp, counts, organic)


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


def mixed_position(rng, hard_fraction: float = 0.5,
                   strange_fraction: float = 0.25) -> BattleState:
    """Blend, so no single shape becomes the whole of what is learned."""
    roll = rng.random()
    if roll < strange_fraction:
        return strange_position(rng)
    if roll < strange_fraction + hard_fraction:
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
