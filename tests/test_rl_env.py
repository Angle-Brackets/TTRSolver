"""The RL view of a battle.

Standard library only -- the environment is the simulator wearing a
different interface, and torch never appears in `solver/`.
"""
import random
import unittest

from solver import simulator
from solver.rl import env
from solver.state import BattleState, CogState, ToonState, Track


class ActionTableTest(unittest.TestCase):

    def test_the_table_is_fixed_and_pass_is_index_zero(self):
        """The policy's output layer has a constant shape, and the pass
        is always present even when everything else is masked out."""
        self.assertEqual(env.PASS_INDEX, 0)
        self.assertTrue(env.action_at(0).is_pass)
        # 1 pass + 7 tracks x 7 levels x 5 targets + one fire per cog
        # slot. The fires are APPENDED so every gag index keeps the
        # meaning it had; a policy trained before them is refused by
        # check_export rather than read four slots out of step.
        self.assertEqual(len(env.ACTIONS), 1 + 7 * 7 * 5 + env.MAX_COGS)
        self.assertEqual(sum(1 for a in env.ACTIONS if a is not None
                             and a.fire), env.MAX_COGS)

    def test_pass_is_always_legal(self):
        """The search cannot say this -- widening its pass broke exact
        solve() -- and this environment can, because it memoises
        nothing. Conserving a scarce gag and declining to draw a cog's
        attack are both real moves."""
        rng = random.Random(0)
        for _ in range(50):
            state = env.default_position(rng)
            if state.is_terminal():
                continue
            self.assertTrue(env.legal_mask(state)[env.PASS_INDEX])


class MaskTest(unittest.TestCase):

    def setUp(self):
        self.rng = random.Random(7)

    def test_a_masked_action_is_never_unaffordable(self):
        for _ in range(40):
            state = env.default_position(self.rng)
            if state.is_terminal():
                continue
            toon = state.toons[0]
            for i, ok in enumerate(env.legal_mask(state)):
                if not ok or i == env.PASS_INDEX:
                    continue
                action = env.ACTIONS[i]
                self.assertGreater(
                    toon.gag_counts.get((action.track, action.level), 0), 0)
                self.assertGreater(toon.track_exp.get(action.track, 0), 0)

    def test_group_and_single_are_not_confused(self):
        from solver import simulator

        for _ in range(30):
            state = env.default_position(self.rng)
            for i, ok in enumerate(env.legal_mask(state)):
                if not ok or i == env.PASS_INDEX:
                    continue
                action = env.ACTIONS[i]
                group = simulator.is_group_action(action.track, action.level)
                self.assertEqual(group, action.target_index is None)

    def test_a_trapped_or_lured_cog_is_not_offered_a_trap(self):
        state = env.default_position(self.rng)
        for cog in state.cogs:
            cog.status.trapped = True
        for i, ok in enumerate(env.legal_mask(state)):
            if ok and i != env.PASS_INDEX:
                self.assertNotEqual(env.ACTIONS[i].track, Track.TRAP)


class EnvTest(unittest.TestCase):

    def test_observation_width_is_constant(self):
        e = env.BattleEnv(rng=random.Random(1))
        widths = set()
        for _ in range(20):
            obs, _mask = e.reset()
            widths.add(len(obs))
            for _step in range(3):
                obs, _m, _r, done, _i = e.step(env.PASS_INDEX)
                widths.add(len(obs))
                if done:
                    break
        self.assertEqual(widths, {env.OBS_DIM})

    def test_an_episode_ends(self):
        e = env.BattleEnv(rng=random.Random(2), max_rounds=20)
        for _ in range(10):
            _obs, mask = e.reset()
            for _step in range(25):
                choices = [i for i, ok in enumerate(mask) if ok]
                _obs, mask, _r, done, _info = e.step(
                    random.Random(_step).choice(choices))
                if done:
                    break
            else:
                self.fail("episode ran past its round cap")

    def test_reward_matches_the_search_objective(self):
        """The agent is scored by the same function the search is, so a
        comparison between them means something."""
        from solver.search import party_search as ps

        e = env.BattleEnv(rng=random.Random(3))
        e.reset()
        _o, _m, reward, _d, _i = e.step(env.PASS_INDEX)
        self.assertIsInstance(reward, float)
        self.assertLess(reward, 0.0)      # a pass costs a turn at minimum
        self.assertTrue(hasattr(ps, "round_reward"))


if __name__ == "__main__":
    unittest.main()


class StrangePositionTest(unittest.TestCase):
    """Mid-fight boards must be REACHABLE, not merely unusual.

    The first version set `trapped = True` without a `trap_level`, which
    no real battle can produce: the next Lure to spring it looks the
    trap's damage up by level and dies on `no gag at trap level None`.
    Training crashed 40 seconds in. A generator that can emit
    unreachable states is worse than one that is merely narrow -- it
    trains on a game that does not exist.
    """

    def test_every_trapped_cog_carries_a_trap_level(self):
        rng = random.Random(5)
        for _ in range(200):
            for cog in env.strange_position(rng).cogs:
                if cog.status.trapped:
                    self.assertIsNotNone(cog.status.trap_level)

    def test_every_lured_cog_can_be_ticked(self):
        """`_tick_lure` needs `lure_acc_before_bonus` to roll wake-up."""
        rng = random.Random(6)
        for _ in range(200):
            for cog in env.strange_position(rng).cogs:
                if cog.status.lured:
                    self.assertIsNotNone(cog.status.lure_acc_before_bonus)

    def test_positions_survive_being_played(self):
        from solver import party as party_mod

        rng = random.Random(7)
        for _ in range(150):
            state = env.strange_position(rng)
            for _round in range(4):
                if state.is_terminal():
                    break
                state, _h, _d = party_mod.step(
                    state, None, mode=party_mod.Mode.PICKUP, rng=rng)


class ToonShapeTest(unittest.TestCase):
    """Generated toons must be toons the game can produce."""

    def test_every_toon_owns_throw_and_squirt(self):
        """Both are starting tracks. A toon without them is not a hard
        puzzle, it is an impossible one."""
        rng = random.Random(9)
        for _ in range(300):
            exp = env.random_toon(rng).track_exp
            self.assertIn(Track.THROW, exp)
            self.assertIn(Track.SQUIRT, exp)

    def test_no_toon_owns_all_seven_tracks(self):
        rng = random.Random(10)
        for _ in range(300):
            self.assertLessEqual(len(env.random_toon(rng).track_exp), 6)

    def test_experience_is_in_range(self):
        rng = random.Random(11)
        for _ in range(300):
            for level in env.random_toon(rng).track_exp.values():
                self.assertTrue(1 <= level <= 7)


class ExportCompatibilityTest(unittest.TestCase):
    """A saved policy must refuse to load against a changed observation.

    Adding a feature to `encode` silently invalidates every trained
    policy: 247 floats read through weights expecting 243 shifts every
    input and returns confident nonsense, with no error anywhere. This
    is the `fitted.is_fitted` guard for the RL side.
    """

    def test_a_matching_export_is_accepted(self):
        self.assertIsNone(env.check_export(
            {"obs_dim": env.OBS_DIM, "n_actions": len(env.ACTIONS)}))

    def test_a_stale_observation_width_is_rejected(self):
        why = env.check_export(
            {"obs_dim": env.OBS_DIM - 4, "n_actions": len(env.ACTIONS)})
        self.assertIsNotNone(why)
        self.assertIn("retrain", why)

    def test_a_stale_action_table_is_rejected(self):
        why = env.check_export(
            {"obs_dim": env.OBS_DIM, "n_actions": len(env.ACTIONS) - 1})
        self.assertIsNotNone(why)


class CoordinatedTest(unittest.TestCase):
    """One shared policy choosing for every toon, a round at a time.

    Pickup mode fills the other seats from `SensiblePrior`, so teammates
    are noise to be survived rather than partners -- the policy can
    learn what is robust to strangers and never "I trap, you lure".
    Coordinated mode makes the joint plan the thing being learned.
    """

    def party(self, rng):
        state = env.default_position(rng)
        while len(state.toons) < 3:
            state = env.default_position(rng)
        return state

    def test_a_round_takes_one_step_per_standing_toon(self):
        e = env.BattleEnv(rng=random.Random(9), coordinated=True,
                          sampler=self.party)
        _ob, mask = e.reset()
        standing = sum(1 for t in e.state.toons if t.laff > 0)
        partial = 0
        for _ in range(standing):
            choices = [i for i, ok in enumerate(mask) if ok]
            _ob, mask, _r, _done, info = e.step(choices[0])
            partial += bool(info.get("partial"))
        self.assertEqual(partial, standing - 1)

    def test_intermediate_steps_pay_nothing(self):
        """Reward lands on the step that resolves the round; the critic
        carries the rest."""
        e = env.BattleEnv(rng=random.Random(11), coordinated=True,
                          sampler=self.party)
        _ob, mask = e.reset()
        choices = [i for i, ok in enumerate(mask) if ok]
        _ob, _mask, reward, _done, info = e.step(choices[0])
        if info.get("partial"):
            self.assertEqual(reward, 0.0)

    def test_pickup_always_acts_as_toon_zero(self):
        """`party.step` applies a pickup action to toons[0] whatever the
        actor says, so the mask must be built from that toon's pouch.
        Advancing past a sad toon here once produced a mask from someone
        else's pouch and a KeyError when the gag was spent."""
        e = env.BattleEnv(rng=random.Random(3), coordinated=False,
                          sampler=self.party)
        e.reset()
        e.state.toons[0].laff = 0
        e._begin_round()
        self.assertEqual(e.actor, 0)


class HorizonTest(unittest.TestCase):
    """`cogs_remaining` -- the fights after this one."""

    def test_default_is_the_old_behaviour(self):
        """A bare state is the last fight, so nothing already written
        changes meaning."""
        state = BattleState(toon=ToonState(50, 50, {Track.THROW: 5},
                                           {(Track.THROW, 1): 2}),
                            cogs=[CogState("cold_caller", "sellbot", 1,
                                           6, 6)])
        self.assertEqual(state.cogs_remaining, 0)

    def test_survives_a_clone(self):
        state = BattleState(toon=ToonState(50, 50, {Track.THROW: 5},
                                           {(Track.THROW, 1): 2}),
                            cogs=[CogState("cold_caller", "sellbot", 1,
                                           6, 6)],
                            cogs_remaining=17)
        self.assertEqual(state.clone().cogs_remaining, 17)

    def test_it_keys_the_memo(self):
        """Two positions identical but for the horizon are worth
        different amounts, so they must not share a memo entry -- the
        bug `free_passes` already had."""
        from solver import outcomes
        def make(remaining):
            return BattleState(toon=ToonState(50, 50, {Track.THROW: 5},
                                              {(Track.THROW, 1): 2}),
                               cogs=[CogState("cold_caller", "sellbot", 1,
                                              6, 6)],
                               cogs_remaining=remaining)
        self.assertNotEqual(outcomes.state_key(make(0)),
                            outcomes.state_key(make(9)))

    def test_a_gag_costs_more_when_more_is_coming(self):
        from solver.search import objective as om
        cheap = om.BALANCED.gag_price(Track.THROW, 6, 0)
        dear = om.BALANCED.gag_price(Track.THROW, 6, 30)
        self.assertGreater(dear, cheap)

    def test_the_sampler_spans_the_range(self):
        rng = random.Random(0)
        seen = [env.sample_horizon(rng) for _ in range(400)]
        self.assertEqual(min(seen), 0)
        self.assertGreater(max(seen), 20)
        self.assertGreater(seen.count(0), 100)   # half are the last fight
        self.assertLessEqual(max(seen), 30)

    def test_it_reaches_the_observation(self):
        """Encoded, and normalised into the same range as everything
        else."""
        def obs(remaining):
            state = env.default_position(random.Random(3))
            state.cogs_remaining = remaining
            return env.encode(state)
        near, far = obs(0), obs(30)
        self.assertNotEqual(near, far)
        self.assertEqual(len(near), env.OBS_DIM)
        self.assertTrue(all(-1.0 <= v <= 1.0 for v in far))


class MoveGeneratorAgreementTest(unittest.TestCase):
    """The mask and `simulator.legal_actions` must offer the same moves.

    They are now the same code -- `legal_mask` translates rather than
    decides -- but the translation still has three chances to be wrong:
    the (track, level, target) lookup, the actor rotation, and mapping a
    Toon-Up target (which names a TOON) back to this state's numbering.

    Two generators drifted before. The mask never applied the
    productivity rules, so the agent healed a party already on full
    laff, 4.0% of every gag it threw; and it validated Toon-Up targets
    against live COG indices, which the simulator had already found and
    fixed on its own side.
    """

    def key(self, action):
        if action is None or action.is_pass:
            return ("PASS",)
        return (action.track.name, action.level, action.target_index)

    def from_mask(self, state, actor=0):
        return {self.key(env.ACTIONS[i])
                for i, ok in enumerate(env.legal_mask(state, actor)) if ok}

    def from_search(self, state):
        return {self.key(a) for a in simulator.legal_actions(state)}

    def test_they_agree_across_every_sampler(self):
        rng = random.Random(7)
        samplers = [env.default_position, env.hard_position,
                    env.strange_position, env.combo_position,
                    env.facility_position]
        checked = 0
        for i in range(250):
            state = samplers[i % len(samplers)](rng)
            if state.is_terminal():
                continue
            checked += 1
            self.assertEqual(self.from_mask(state),
                             self.from_search(state),
                             f"move generators disagree on {state.kind}")
        self.assertGreater(checked, 100)

    def test_they_agree_with_the_pass_budget_spent(self):
        """`legal_actions` withdraws the pass when free_passes runs out
        and no cog is lured. The mask used to offer it unconditionally,
        which diverged on 333 of 386 positions."""
        rng = random.Random(11)
        for _ in range(120):
            state = env.mixed_position(rng, 0.3, 0.25, 0.2)
            if state.is_terminal():
                continue
            state.free_passes = 0
            self.assertEqual(self.from_mask(state), self.from_search(state))

    def test_a_toon_up_target_names_a_toon(self):
        """The bug that diverged in BOTH directions: a heal aimed at
        toon 2 was accepted or rejected on whether COG 2 was alive."""
        toon_a = ToonState(50, 50, {Track.TOON_UP: 5},
                           {(Track.TOON_UP, 1): 2})
        hurt = ToonState(10, 50, {Track.THROW: 5}, {(Track.THROW, 1): 2})
        state = BattleState(toons=[toon_a, hurt],
                            cogs=[CogState("cold_caller", "sellbot", 1,
                                           6, 6)])
        offered = self.from_mask(state)
        self.assertIn(("TOON_UP", 1, 1), offered)

    def test_no_heal_when_nobody_is_hurt(self):
        full = ToonState(50, 50, {Track.TOON_UP: 5},
                         {(Track.TOON_UP, 1): 2})
        other = ToonState(50, 50, {Track.THROW: 5}, {(Track.THROW, 1): 2})
        state = BattleState(toons=[full, other],
                            cogs=[CogState("cold_caller", "sellbot", 1,
                                           6, 6)])
        self.assertEqual(
            [k for k in self.from_mask(state) if k[0] == "TOON_UP"], [])

    def test_the_agent_always_has_a_move(self):
        """An all-False mask leaves nothing to pick."""
        rng = random.Random(5)
        for _ in range(200):
            state = env.mixed_position(rng, 0.3, 0.25, 0.2)
            state.free_passes = 0
            for actor in range(len(state.toons)):
                self.assertTrue(any(env.legal_mask(state, actor)))


class SlipEncodingTest(unittest.TestCase):
    """Slips are normalised by what a toon can CARRY, not by a literal.

    [CONFIRMED] wiki: the cap is 200, reduced from 255 on 31 May 2022.
    `ToonState.fire_capacity` holds it and `_fire_feature` divides by it.

    The literal 10 this replaced was doing two jobs and both badly. It
    was the scale, and `min(fires, 10)` also made it a saturation point,
    so ten slips and twenty were the same number going in -- which is
    why the slip curve came back identical at 10 and 20 to the decimal.
    Training never went above five either (`--fire-max` defaults to 5),
    so the live range was 0.1 to 0.5 and every measurement taken at ten
    slips was off the end of it.
    """

    def _toon(self, fires):
        from solver.state import ToonState, Track
        t = ToonState(100, 100, {Track.THROW: 7}, {}, frozenset())
        t.fires = fires
        return t

    def test_the_capacity_is_the_divisor(self):
        from solver.rl import env as env_mod
        toon = self._toon(50)
        self.assertAlmostEqual(env_mod._fire_feature(toon),
                               50 / toon.fire_capacity)

    def test_a_full_pocket_is_one(self):
        from solver.rl import env as env_mod
        toon = self._toon(0)
        toon.fires = toon.fire_capacity
        self.assertAlmostEqual(env_mod._fire_feature(toon), 1.0)

    def test_ten_and_twenty_are_no_longer_the_same_input(self):
        """The saturation that hid half the slip curve."""
        from solver.rl import env as env_mod
        self.assertNotAlmostEqual(env_mod._fire_feature(self._toon(10)),
                                  env_mod._fire_feature(self._toon(20)))

    def test_a_custom_capacity_is_honoured(self):
        from solver.rl import env as env_mod
        toon = self._toon(5)
        toon.fire_capacity = 10
        self.assertAlmostEqual(env_mod._fire_feature(toon), 0.5)

    def test_over_capacity_still_clamps(self):
        from solver.rl import env as env_mod
        self.assertAlmostEqual(env_mod._fire_feature(self._toon(10_000)),
                               1.0)

    def test_version_one_is_reproduced_exactly(self):
        """The shipped policy was FITTED to `min(fires, 10) / 10`. It has
        to keep advising while its replacement trains, so the old
        meaning stays reachable rather than the old policy being
        refused."""
        from solver.rl import env as env_mod
        for fires, expected in ((0, 0.0), (5, 0.5), (10, 1.0), (20, 1.0)):
            self.assertAlmostEqual(
                env_mod._fire_feature(self._toon(fires), obs_version=1),
                expected, msg=f"{fires} slips under version 1")

    def test_encode_threads_the_version_through(self):
        from solver.rl import env as env_mod
        from solver.state import BattleState, CogState
        from solver import data
        hp = data.cog_max_hp(2)
        cog = CogState(department="sellbot", cog_type="cold_caller",
                       level=2, hp=hp, max_hp=hp)
        state = BattleState(toon=self._toon(10), cogs=[cog])
        old = env_mod.encode(state, 0, None, obs_version=1)
        new = env_mod.encode(state, 0, None, obs_version=2)
        self.assertEqual(len(old), len(new))
        self.assertNotEqual(old, new,
                            "ten slips must not encode the same under "
                            "both versions, or the version is a no-op")

    def test_the_shipped_policy_declares_no_version_and_means_one(self):
        """`hybrid` reads `model.get("obs_version", 1)`. If an export
        ever starts defaulting differently, the shipped weights get
        misread in silence -- so pin the default here."""
        import json
        from pathlib import Path
        shipped = (Path(__file__).resolve().parents[1]
                   / "solver" / "rl" / "ppo_facility.json")
        if not shipped.exists():
            self.skipTest("no shipped policy in this checkout")
        payload = json.loads(shipped.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("obs_version", 1), 1)

    def test_no_capacity_literal_survives_in_the_encoder(self):
        """A toon with an unusual cap must encode against ITS cap.

        The first version of this used `getattr(toon, "fire_capacity",
        200)`, which is the same magic number in a new hiding place and
        would silently absorb a ToonState built without the field.
        """
        from solver.rl import env as env_mod
        toon = self._toon(3)
        toon.fire_capacity = 6
        self.assertAlmostEqual(env_mod._fire_feature(toon), 0.5)

    def test_a_missing_capacity_is_an_error_not_a_default(self):
        from solver.rl import env as env_mod

        class Bare:
            fires = 4
        with self.assertRaises(AttributeError):
            env_mod._fire_feature(Bare())

    def test_a_nonsense_capacity_raises(self):
        from solver.rl import env as env_mod
        toon = self._toon(3)
        toon.fire_capacity = 0
        with self.assertRaises(ValueError):
            env_mod._fire_feature(toon)
