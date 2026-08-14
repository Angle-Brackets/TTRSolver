"""Cog attacks that hit the whole team.

[CONFIRMED] TTR wiki, which classifies every cog attack into one of two
categories -- "Group Cog attacks" (14) and "Single Cog attacks" (54).
Between them they cover all 68 attack names in the tables exactly, with
nothing unmatched on either side, so nothing here is guessed.

This was [TODO] for a long time and the reason is worth keeping: solo,
the lone toon is both the target and the group, so the distinction has
no observable effect and the tables never needed the flag. It only
became wrong when parties arrived, and then it was wrong in a direction
that flatters the toons -- a party took strictly less damage than the
game deals.
"""
import unittest

from solver import data, party
from solver.state import BattleState, CogState, ToonState, Track


def toon(laff=80):
    return ToonState(laff, laff, {Track.THROW: 7}, {(Track.THROW, 4): 3})


class ClassificationTest(unittest.TestCase):

    def test_every_attack_in_the_tables_is_classified(self):
        names = {a.name for c in data.all_cogs() for a in c.attacks}
        self.assertEqual(len(names), 68)
        # Group is the smaller set; everything else is single by
        # exclusion, so this asserts the split rather than restating it.
        self.assertTrue(data.GROUP_ATTACKS <= names,
                        "a group attack is not in any cog's table")
        self.assertEqual(len(data.GROUP_ATTACKS), 14)

    def test_a_known_group_attack(self):
        self.assertTrue(data.is_group_attack("quake"))
        self.assertTrue(data.is_group_attack("synergy"))

    def test_a_known_single_attack(self):
        self.assertFalse(data.is_group_attack("rubber_stamp"))
        self.assertFalse(data.is_group_attack("audit"))

    def test_an_unknown_name_is_not_group(self):
        self.assertFalse(data.is_group_attack("not_an_attack"))


class DamageTest(unittest.TestCase):
    """A group attack lands on everybody standing."""

    def phase(self, attack, n=4, laff=80):
        state = BattleState(toons=[toon(laff) for _ in range(n)],
                            cogs=[CogState("yesman", "bossbot", 3,
                                           100, 100)])
        healed = [0] * n
        import solver.mechanics as mechanics
        real_pick, real_hit = mechanics.pick_cog_attack, mechanics.roll_hit
        mechanics.pick_cog_attack = lambda cog, rng=None: attack
        mechanics.roll_hit = lambda acc, rng=None: True
        try:
            party._party_cog_phase(state, healed, __import__("random"))
        finally:
            mechanics.pick_cog_attack, mechanics.roll_hit = real_pick, real_hit
        return [t.laff for t in state.toons]

    def test_a_group_attack_hurts_every_toon(self):
        after = self.phase("synergy")
        self.assertTrue(all(l < 80 for l in after),
                        f"someone escaped a group attack: {after}")

    def test_a_single_attack_hurts_exactly_one(self):
        after = self.phase("rubber_stamp")
        self.assertEqual(sum(1 for l in after if l < 80), 1, after)

    def test_a_sad_toon_is_not_hit_again(self):
        """They have left the battle."""
        state = BattleState(toons=[toon(80), toon(80)],
                            cogs=[CogState("yesman", "bossbot", 3,
                                           100, 100)])
        state.toons[1].laff = 0
        import solver.mechanics as mechanics
        real_pick, real_hit = mechanics.pick_cog_attack, mechanics.roll_hit
        mechanics.pick_cog_attack = lambda cog, rng=None: "synergy"
        mechanics.roll_hit = lambda acc, rng=None: True
        try:
            party._party_cog_phase(state, [0, 0], __import__("random"))
        finally:
            mechanics.pick_cog_attack, mechanics.roll_hit = real_pick, real_hit
        self.assertEqual(state.toons[1].laff, 0)


if __name__ == "__main__":
    unittest.main()
