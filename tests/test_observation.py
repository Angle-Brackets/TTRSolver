"""What the policy can and cannot see.

Two features were missing for as long as the things they describe have
been modelled, and both were invisible in the worst way -- not wrong,
absent. A Version 2.0 and an ordinary cog encoded to byte-identical
observations, and so did a toon holding five pink slips and one holding
none. Training on CEO or VP positions could not have taught the policy
either, because the positions differ only in what it could not perceive.

Measured before the fix: 0 differing floats out of 290 for both.
"""
import unittest

from solver.rl import env as env_mod
from solver.search import hybrid
from solver.state import BattleState, CogState, ToonState, Track


def toon(fires=0):
    return ToonState(laff=110, max_laff=110,
                     track_exp={t: 7 for t in Track},
                     gag_counts={(t, l): 3 for t in Track
                                 for l in range(1, 8)},
                     organic_tracks=frozenset(), fires=fires)


def state(v2=False, fires=0, level=12, hp=None):
    from solver import data
    full = data.cog_max_hp(level) if hp is None else hp
    cog = CogState("corporate_raider", "bossbot", level, full, full)
    cog.status.suited = v2
    return BattleState(toons=[toon(fires), toon(fires)], cogs=[cog])


def differing(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


class TheObservationHasTheRightWidth(unittest.TestCase):
    def test_encode_matches_obs_dim(self):
        """`OBS_DIM` is declared separately from the loop that fills the
        vector, and `check_export` gates every trained policy on it. If
        they drift, a policy reads every feature shifted."""
        self.assertEqual(len(env_mod.encode(state())), env_mod.OBS_DIM)

    def test_a_dead_cog_pads_to_the_same_width(self):
        alive = env_mod.encode(state())
        empty = env_mod.encode(BattleState(toons=[toon()], cogs=[]))
        self.assertEqual(len(alive), len(empty))


class AVersionTwoIsVisible(unittest.TestCase):
    def test_the_suit_changes_the_observation(self):
        self.assertGreater(differing(env_mod.encode(state(v2=False)),
                                     env_mod.encode(state(v2=True))), 0,
                           "a v2.0 encoded identically to an ordinary cog")

    def test_the_work_remaining_is_handed_over_not_implied(self):
        """Remaining health is `hp + max_hp if suited` -- a PRODUCT of
        two inputs, which a linear layer cannot form. A bare flag would
        leave the network to multiply, so the ratio is given directly."""
        plain = env_mod.encode(state(v2=False))
        suited = env_mod.encode(state(v2=True))
        self.assertEqual(differing(plain, suited), 2,
                         "expected the flag AND the remaining-work ratio")

    def test_a_damaged_v2_still_reads_above_a_full_ordinary_cog(self):
        """The point of the ratio: a v2.0 at half its visible health has
        more left to lose than an untouched ordinary cog."""
        hurt = state(v2=True)
        hurt.cogs[0].hp = hurt.cogs[0].max_hp // 2
        whole = state(v2=False)
        # The remaining-work entry is the 6th float of the cog block.
        self.assertGreater(env_mod.encode(hurt)[5],
                           env_mod.encode(whole)[5])


class PinkSlipsAreVisible(unittest.TestCase):
    def test_holding_slips_changes_the_observation(self):
        self.assertGreater(differing(env_mod.encode(state(fires=0)),
                                     env_mod.encode(state(fires=5))), 0,
                           "the action table offers fires; the observation "
                           "never said whether the toon had any")

    def test_more_slips_reads_higher(self):
        few = env_mod.encode(state(fires=1))
        many = env_mod.encode(state(fires=8))
        index = next(i for i, (x, y) in enumerate(zip(few, many)) if x != y)
        self.assertLess(few[index], many[index])


class HighLevelCogsStayInRange(unittest.TestCase):
    """Level and max hp were scaled by 12 and 200 -- the top of a cog
    BUILDING. A level 15 Big Cheese read 1.25 and 1.43, outside the range
    every other feature lives in, on exactly the fights the scaling had
    never been checked against."""

    def test_every_modelled_level_normalises_inside_the_unit_range(self):
        for level in (1, 8, 12, 14, 15, 20):
            obs = env_mod.encode(state(level=level))
            self.assertLessEqual(obs[1], 1.0, f"level {level}")
            self.assertLessEqual(obs[3], 1.0, f"max_hp at level {level}")

    def test_levels_are_still_ordered(self):
        self.assertLess(env_mod.encode(state(level=8))[1],
                        env_mod.encode(state(level=15))[1])


class AMismatchedPolicySaysWhy(unittest.TestCase):
    def test_check_export_names_the_width(self):
        message = env_mod.check_export(
            {"obs_dim": env_mod.OBS_DIM - 12,
             "obs_version": env_mod.OBS_VERSION,
             "n_actions": len(env_mod.ACTIONS)})
        self.assertIsNotNone(message)
        self.assertIn(str(env_mod.OBS_DIM), message)

    def test_an_accepted_payload_returns_none(self):
        self.assertIsNone(env_mod.check_export(
            {"obs_dim": env_mod.OBS_DIM,
             "obs_version": env_mod.OBS_VERSION,
             "n_actions": len(env_mod.ACTIONS)}))

    def test_a_width_is_only_meaningful_with_its_version(self):
        """An export declaring today's WIDTH at an old VERSION is
        contradictory and must be refused. Widths moved when version 3
        added absolute laff, so 306 is right at 3 and wrong at 1."""
        why = env_mod.check_export(
            {"obs_dim": env_mod.OBS_DIM, "obs_version": 1,
             "n_actions": len(env_mod.ACTIONS)})
        self.assertIsNotNone(why)

    def test_an_older_policy_is_still_accepted_at_its_own_width(self):
        """The whole point of versioning it: a version 1 export is 302
        wide and correct, and `encode` still speaks version 1."""
        self.assertIsNone(env_mod.check_export(
            {"obs_dim": env_mod.obs_dim_for(1), "obs_version": 1,
             "n_actions": len(env_mod.ACTIONS)}))

    def test_unavailable_reason_is_never_silent(self):
        """The reason used to be computed and discarded, so a policy
        invalidated by an observation change was reported as "numpy or
        the policy is missing" -- which sends you looking in entirely
        the wrong place."""
        if hybrid.available():
            self.assertIsNone(hybrid.unavailable_reason())
        else:
            reason = hybrid.unavailable_reason()
            self.assertTrue(reason and reason.strip())


if __name__ == "__main__":
    unittest.main()


class LureSafetyTest(unittest.TestCase):
    """The lure input designed for the next retrain (OBS_VERSION 5): the
    reasoning is beside `env_mod.LURE_SAFETY_BASE`."""

    def test_the_curve(self):
        got = [round(env_mod.lure_safety(r), 2) for r in (0, 1, 2, 4, 8, 14)]
        self.assertEqual([0.0, 0.25, 0.44, 0.68, 0.9, 0.98], got)

    def test_a_long_lure_reads_safer_than_a_short_one(self):
        """The reason a per-gag fraction was rejected: a fresh $1 Bill and
        a fresh Presentation must not read the same."""
        self.assertLess(env_mod.lure_safety(2), env_mod.lure_safety(14))

    def _lured(self, rounds):
        board = state(level=6)
        board.cogs[0].status.apply_lure(90, rounds, level=6)
        return board

    def test_the_shipped_networks_still_get_their_encoding(self):
        """Version 4 is what every shipped network was trained on; the new
        curve must not leak into it."""
        self.assertEqual(env_mod.encode(self._lured(4)),
                         env_mod.encode(self._lured(4), obs_version=4))
        self.assertEqual(4, env_mod.OBS_VERSION)

    def test_version_5_tells_14_rounds_from_8(self):
        v4 = (env_mod.encode(self._lured(8), obs_version=4),
              env_mod.encode(self._lured(14), obs_version=4))
        v5 = (env_mod.encode(self._lured(8), obs_version=5),
              env_mod.encode(self._lured(14), obs_version=5))
        self.assertEqual(v4[0], v4[1])
        self.assertNotEqual(v5[0], v5[1])


class EncodingVersionPlumbingTest(unittest.TestCase):
    """Each network reads the encoding it was trained on; data tools can
    write rows at a new one; old data converts exactly."""

    def _lured(self, rounds):
        board = state(level=6)
        board.cogs[0].status.apply_lure(90, rounds, level=6)
        return board

    def test_features_follow_the_version_asked_for(self):
        try:
            from solver.search import fastplayer
        except Exception:                    # pragma: no cover
            self.skipTest("fastplayer unavailable")
        board = self._lured(3)
        x5 = fastplayer.features(board, obs_version=5)[0][:env_mod.OBS_DIM]
        self.assertEqual(list(env_mod.encode(board, 0, [None] * len(board.toons),
                                             obs_version=5)), x5)

    def test_old_rows_convert_exactly(self):
        import pathlib
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
        import reencode_lure
        for rounds in (1, 4, 8):
            board = self._lured(rounds)
            v4 = list(env_mod.encode(board, obs_version=4))
            v5 = list(env_mod.encode(board, obs_version=5))
            self.assertEqual(v5, reencode_lure.convert_row({"x": v4})["x"])
            self.assertEqual(v5, reencode_lure.convert_row(("gag", v4, [], 0))[1])
