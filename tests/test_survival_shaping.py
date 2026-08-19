"""The survival potential must be potential-based, not a bonus.

The whole reason to prefer `survival_shaping` over simply raising
`toon_lost_penalty` is Ng et al.'s guarantee: a shaping term of the form
F = gamma*Phi(s') - Phi(s) leaves the optimal policy unchanged, so it can
only change how fast credit arrives, never what the agent is optimising.
A raw penalty has no such guarantee and can buy passivity.

That guarantee holds only if the terms telescope, which in turn needs
Phi(terminal) = 0. These tests pin both.
"""
import random
import unittest

from solver.rl import env as env_mod


GAMMA = 0.99


def _run(seed, survival, steps=400):
    """DISCOUNTED shaped minus unshaped reward over one episode.

    Discounted, because that is what the guarantee is about:

        sum_t gamma^t (gamma*Phi(s_{t+1}) - Phi(s_t)) = -Phi(s_0)

    The undiscounted sum does NOT telescope -- it picks up (1-gamma)*Phi
    every step, which is a real -0.2 a round here and looks exactly like
    a leak if you assert the wrong identity. It caught me out first.
    """
    shaped = env_mod.BattleEnv(rng=random.Random(seed),
                               sampler=env_mod.facility_position,
                               coordinated=True, survival_shaping=survival)
    plain = env_mod.BattleEnv(rng=random.Random(seed),
                              sampler=env_mod.facility_position,
                              coordinated=True)
    obs_a, mask_a = shaped.reset()
    obs_b, mask_b = plain.reset()
    total_a = total_b = 0.0
    start_alive = len(shaped.state.active_toons())
    rng = random.Random(seed)
    discount = 1.0
    for _ in range(steps):
        legal = [i for i, ok in enumerate(mask_a) if ok]
        pick = rng.choice(legal) if legal else env_mod.PASS_INDEX
        obs_a, mask_a, r_a, done_a, _ = shaped.step(pick)
        obs_b, mask_b, r_b, done_b, _ = plain.step(pick)
        total_a += discount * r_a
        total_b += discount * r_b
        discount *= GAMMA
        if done_a or done_b:
            break
    return total_a, total_b, start_alive


class SurvivalShapingTest(unittest.TestCase):

    def test_off_by_default(self):
        e = env_mod.BattleEnv(rng=random.Random(1))
        self.assertEqual(e.survival_shaping, 0.0)

    def test_zero_weight_changes_nothing(self):
        a, b, _ = _run(41, 0.0)
        self.assertAlmostEqual(a, b, places=6)

    def test_the_episode_sum_telescopes_to_a_constant(self):
        """Sum of F over an episode is -Phi(s_0), which depends only on
        how many toons STARTED. If it depended on the trajectory the
        optimality guarantee would be gone."""
        w = 5.0
        for seed in (11, 12, 13, 14, 15, 16):
            shaped, plain, start_alive = _run(seed, w)
            self.assertAlmostEqual(
                shaped - plain, -w * start_alive, places=4,
                msg=f"seed {seed}: shaping summed to {shaped - plain:.3f}, "
                    f"expected {-w * start_alive:.3f} -- it is not "
                    f"telescoping, so it is not potential-based")

    def test_the_charge_lands_when_the_toon_does(self):
        """A step that loses a toon must carry the negative itself."""
        w = 5.0
        e = env_mod.BattleEnv(rng=random.Random(7),
                              sampler=env_mod.facility_position,
                              coordinated=True, survival_shaping=w)
        plain = env_mod.BattleEnv(rng=random.Random(7),
                                  sampler=env_mod.facility_position,
                                  coordinated=True)
        obs, mask = e.reset()
        plain.reset()
        rng = random.Random(7)
        seen = False
        for _ in range(400):
            before = len(e.state.active_toons())
            legal = [i for i, ok in enumerate(mask) if ok]
            pick = rng.choice(legal) if legal else env_mod.PASS_INDEX
            obs, mask, r_shaped, done, _ = e.step(pick)
            _o, _m, r_plain, done_b, _i = plain.step(pick)
            after = len(e.state.active_toons())
            if after < before and not done:
                self.assertLess(r_shaped, r_plain,
                                "losing a toon must cost more with the "
                                "potential on than without it")
                seen = True
                break
            if done or done_b:
                break
        if not seen:
            self.skipTest("no toon was lost in this rollout")


if __name__ == "__main__":
    unittest.main()
