"""The three Bossbot cogs that go above level 12.

The CEO's first cog battle draws levels 9-14 and its second opens with a
level 14 Version 2.0 Big Cheese, so without these the fight cannot be
built at all. Our main tables stop at 12 because that is the STREET
range; the wiki publishes eight levels per attack and the Big Cheese's
infobox says outright that it "can have three additional levels, up to
level 15".

WHAT IS CONFIRMED AND WHAT IS NOT. Damage comes from each cog's
CogAttackTable and is [CONFIRMED]. Accuracy and frequency are [ASSUMED]:
the wiki publishes neither at any level, and Open Toontown's
SuitBattleGlobals stores five levels per cog exactly as we do, so the
Toontown Online lineage has nothing above 12 either -- checked, not
assumed. The last published value is carried forward flat, which errs
toward weaker cogs, so a CEO clear rate is an upper bound.
"""
import unittest

from solver import data
from solver.data import cogs as cogs_mod


HIGH = (("head_hunter", 13), ("corporate_raider", 14), ("the_big_cheese", 15))


class BossLevelTest(unittest.TestCase):

    def test_each_cog_reaches_its_published_ceiling(self):
        for key, top in HIGH:
            self.assertEqual(data.cog("bossbot", key).levels[-1], top, key)

    def test_stored_damage_is_a_prefix_of_the_published_table(self):
        """The check that makes the extension safe rather than hopeful.
        If the wiki table and ours disagreed on the levels we already
        had, appending to it would corrupt the ones we trust."""
        for (dept, key), table in cogs_mod.HIGH_LEVEL_DAMAGE.items():
            spec = data.cog(dept, key)
            for attack in spec.attacks:
                published = table.get(attack.name)
                if published is None:
                    continue          # borrowed by _fill_unmodeled
                self.assertEqual(tuple(attack.damage), published,
                                 f"{key}.{attack.name}")

    def test_every_column_is_as_long_as_the_level_list(self):
        """A short column would index out of range mid-battle."""
        for key, _top in HIGH:
            spec = data.cog("bossbot", key)
            n = len(spec.levels)
            for attack in spec.attacks:
                self.assertEqual(len(attack.damage), n, f"{key}.{attack.name}")
                self.assertEqual(len(attack.accuracy), n, f"{key}.{attack.name}")
                self.assertEqual(len(attack.frequency), n, f"{key}.{attack.name}")

    def test_a_mismatched_prefix_raises_rather_than_appending(self):
        import dataclasses
        spec = data.cog("bossbot", "the_big_cheese")
        broken = dataclasses.replace(
            spec,
            levels=(8, 9, 10, 11, 12),
            attacks=tuple(dataclasses.replace(a, damage=(1, 2, 3, 4, 5))
                          for a in spec.attacks))
        with self.assertRaises(ValueError):
            cogs_mod._extend_high_levels(broken)

    def test_the_carry_never_invents_a_number(self):
        self.assertEqual(cogs_mod._carry((70, 80), 2), (70, 80, 80, 80))
        self.assertEqual(cogs_mod._carry((), 2), (None, None))
        self.assertEqual(cogs_mod._carry((None,), 1), (None, None))

    def test_a_level_14_big_cheese_can_actually_be_built(self):
        """The point of the whole exercise."""
        spec = data.cog("bossbot", "the_big_cheese")
        self.assertIn(14, spec.levels)
        i = spec.levels.index(14)
        for attack in spec.attacks:
            self.assertIsNotNone(attack.damage[i], attack.name)
        self.assertEqual(data.cog_max_hp(14), 254)


if __name__ == "__main__":
    unittest.main()
