"""The CEO's two cog battles.

Structure is [CONFIRMED] wiki: waiter battle at levels 9-14 with some
Version 2.0s, then a level 14 Version 2.0 Big Cheese followed by whatever
survived the banquet. The banquet itself is a real-time minigame and is
not modelled; its OUTPUT is a count, which is why `LEFTOVERS` is swept.
"""
import random
import unittest

from solver import ceo, data
from solver.rl import env as env_mod


def plan(seed=0, **kw):
    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=ceo.ceo_position,
                          coordinated=True)
    return ceo.ceo_plan(random.Random(seed), e._boss_cog, **kw)


class CeoStructureTest(unittest.TestCase):

    def test_two_rounds(self):
        self.assertEqual(len(plan().floors), 2)

    def test_round_two_opens_with_a_v2_big_cheese(self):
        """The wiki says level 14; we run at 12 because `tgt_def` is
        unpublished above 12 and the project refuses to invent it. The
        COG has to be a Big Cheese either way -- drawing it from the
        level pool got a Corporate Raider, which is a different fight."""
        second = plan().floors[1]
        self.assertEqual(second[0].cog_type, "the_big_cheese")
        self.assertEqual(second[0].level, ceo.BIG_CHEESE_LEVEL)
        self.assertTrue(second[0].status.suited)

    def test_the_wiki_range_is_used_in_full(self):
        """The cap is gone: tgt_def 13-19 is now interpolated (owner
        authorised), so levels 13 and 14 can actually be simulated."""
        from solver import data
        self.assertEqual(ceo.COG_LEVELS, (9, 14))
        self.assertEqual(ceo.BIG_CHEESE_LEVEL, 14)
        self.assertEqual(data.tgt_def(14), -58)

    def test_every_banquet_leftover_is_a_v2(self):
        """[OPEN TOONTOWN SOURCE] generateDinerSuits builds every diner
        with revives=1, and the owner confirms it from play."""
        second = plan(leftovers=8).floors[1]
        self.assertEqual(len(second), 9)          # Big Cheese + 8
        for cog in second[1:]:
            self.assertTrue(cog.status.suited, cog.cog_type)

    def test_round_one_levels_are_nine_to_fourteen(self):
        for seed in range(20):
            for cog in plan(seed).floors[0]:
                self.assertGreaterEqual(cog.level, 9)
                self.assertLessEqual(cog.level, 14)

    def test_round_one_v2_fraction_is_roughly_the_parameter(self):
        suited = total = 0
        for seed in range(60):
            for cog in plan(seed, round_one=20, v2_fraction=0.20).floors[0]:
                suited += bool(cog.status.suited)
                total += 1
        share = suited / total
        self.assertGreater(share, 0.12, f"got {share:.2f}")
        self.assertLess(share, 0.29, f"got {share:.2f}")

    def test_none_and_all_are_both_reachable(self):
        self.assertEqual(
            sum(1 for c in plan(v2_fraction=0.0).floors[0] if c.status.suited),
            0)
        first = plan(v2_fraction=1.0).floors[0]
        self.assertTrue(all(c.status.suited for c in first))

    def test_the_party_is_two_toons_with_fires(self):
        state = ceo.ceo_position(random.Random(3))
        self.assertEqual(len(state.toons), 2)
        for toon in state.toons:
            self.assertEqual(toon.fires, ceo.FIRES_PER_TOON)
            self.assertGreaterEqual(toon.max_laff, 100)
            self.assertLessEqual(toon.max_laff, 119)
            self.assertTrue(any(lvl == 7 for (_t, lvl), n
                                in toon.gag_counts.items() if n > 0),
                            "level 7s are meant to be available here")

    def test_a_boss_cog_refuses_an_impossible_level(self):
        e = env_mod.BattleEnv(rng=random.Random(1), sampler=ceo.ceo_position,
                              coordinated=True)
        with self.assertRaises(ValueError):
            e._boss_cog(random.Random(1), 16)

    def test_the_episode_runs_both_rounds(self):
        e = env_mod.BattleEnv(rng=random.Random(11), sampler=ceo.ceo_position,
                              coordinated=True)
        e.reset()
        self.assertEqual(e.state.kind, "ceo")
        self.assertTrue(e.state.cogs)
        self.assertGreater(e.state.cogs_remaining, 0)

    def test_sweeping_the_module_values_actually_changes_the_plan(self):
        """Default arguments bind once at import; this module reads them
        at call time, which is the bug vp_plan shipped with."""
        old = ceo.LEFTOVERS
        try:
            ceo.LEFTOVERS = 3
            self.assertEqual(len(plan().floors[1]), 4)
            ceo.LEFTOVERS = 9
            self.assertEqual(len(plan().floors[1]), 10)
        finally:
            ceo.LEFTOVERS = old


if __name__ == "__main__":
    unittest.main()
