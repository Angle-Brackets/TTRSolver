"""What the TRAINING REWARD pays for a pink slip.

These exist because the policy plays slips badly and the obvious
conclusion -- that the reward must be telling it to -- is wrong. The
reward already prices a fire correctly, through the laff the round
costs and the potential-based shaping on expected incoming damage.
Charging fires a second time (`--fire-cost`) took twenty points off the
base win rate and fixed nothing.

Pinning the reward's behaviour here means a retrain aimed at the
EXPOSURE (`--fire-fraction`) cannot quietly change what is being taught
while changing how often it is taught.

Measured over 400 paired VP boards, one step each:

    board AWAKE (incoming 31.6)     board ASLEEP (incoming 0.0)
      Hypno-goggles -> all  -9.56     FIRE -> c0            -1.00
      FIRE -> c0           -25.29     Foghorn -> all       -32.42
      Foghorn -> all       -33.54

A NOTE FOR ANYONE WRITING MORE OF THESE. Setting `state.kind` to "vp",
"ceo" or "facility" makes `BattleEnv.reset` deal a fresh floor and
DISCARD the sampler's cogs, so a hand-built board never reaches the
step -- the first version of this measurement compared two boards that
were both random and identical. Leave `kind` alone to keep your board.
"""
import random
import unittest

from solver.data import gags as G
from solver.rl import env as env_mod
from solver.state import BattleState, CogState, ToonState, Track

SEEDS = 24


def _board(lured):
    """A fixed battle. `kind` is left alone so the cogs survive reset."""
    from solver import data

    tracks = [t for t in Track if t is not Track.TOON_UP]
    toon = ToonState(100, 100, {t: 7 for t in tracks}, {},
                     frozenset({Track.THROW}), pouch_capacity=80)
    env_mod.restock(toon, random.Random(4))
    toon.fires = 10
    gag = G.gag(Track.LURE, 6)
    cogs = []
    for key, level in (("mr_hollywood", 12), ("mr_hollywood", 11),
                       ("glad_hander", 8), ("cold_caller", 3)):
        hp = data.cog_max_hp(level)
        cog = CogState(department="sellbot", cog_type=key, level=level,
                       hp=hp, max_hp=hp)
        if lured:
            cog.status.apply_lure(gag.prop_accuracy(organic=False), 3,
                                  level=6)
        cogs.append(cog)
    return BattleState(toon=toon, cogs=cogs)


def _index(match):
    for i, a in enumerate(env_mod.ACTIONS):
        if a is not None and match(a):
            return i
    raise AssertionError("no such action in ACTIONS")


FIRE = _index(lambda a: a.fire and a.target_index == 0)
GROUP_LURE = _index(lambda a: (not a.fire and a.track is Track.LURE
                               and a.level == 6 and a.target_index is None))


def _mean_reward(index, lured):
    """Average one-step reward, same seeds for every candidate."""
    total = 0.0
    for seed in range(SEEDS):
        e = env_mod.BattleEnv(rng=random.Random(seed),
                              sampler=lambda rng, l=lured: _board(l),
                              coordinated=False)
        e.reset()
        assert e.state.cogs[0].status.lured is bool(lured), (
            "reset replaced the board; see the note in the module "
            "docstring about state.kind")
        _obs, _mask, reward, _done, _info = e.step(index)
        total += reward
    return total / SEEDS


class FireRewardTest(unittest.TestCase):

    def test_luring_beats_firing_while_the_cogs_are_awake(self):
        """The lesson the policy failed to learn is already in here.

        A fire removes one cog; a group Lure stops all four swinging,
        for the same round.
        """
        fire = _mean_reward(FIRE, lured=False)
        lure = _mean_reward(GROUP_LURE, lured=False)
        self.assertGreater(
            lure, fire,
            f"the reward prefers a fire to a group Lure on an awake "
            f"board: fire {fire:+.2f}, lure {lure:+.2f}")

    def test_firing_a_sleeping_board_is_far_cheaper(self):
        """A lured cog does not swing, so the round is free and the
        slip costs almost nothing. This is the gradient that should
        teach `lure first, then fire`."""
        awake = _mean_reward(FIRE, lured=False)
        asleep = _mean_reward(FIRE, lured=True)
        self.assertGreater(
            asleep, awake + 10.0,
            f"firing an asleep board should be much cheaper than firing "
            f"an awake one: awake {awake:+.2f}, asleep {asleep:+.2f}")

    def test_the_reward_does_not_double_charge_a_slip(self):
        """`fire_cost` is off, and must stay off unless something new
        is measured. It re-charges a cost the laff term and the shaping
        already carry; at 8 and 25 it cost twenty points of base win
        rate and did not fix the collapse. See `env` for the numbers."""
        e = env_mod.BattleEnv(rng=random.Random(0),
                              sampler=lambda rng: _board(False))
        self.assertFalse(e.fire_cost)

    def test_a_slip_is_spent_and_only_one(self):
        """Guards the measurement above: if the step silently declined
        to fire, every reward here would be a pass and the ordering
        tests would compare nothing."""
        e = env_mod.BattleEnv(rng=random.Random(0),
                              sampler=lambda rng: _board(False),
                              coordinated=False)
        e.reset()
        before = e.state.toons[0].fires
        e.step(FIRE)
        self.assertEqual(e.state.toons[0].fires, before - 1)
