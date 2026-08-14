"""Toon-Up resolves before the cogs attack, and its excess is lost.

`ATTACK_ORDER` puts TOON_UP first, so a heal lands in the toon phase and
is capped at max laff there. Whatever it would have healed past the cap
is gone before a cog swings.

This was one combined clamp -- `min(max_laff, laff + healed - lost)` --
which quietly turned Toon-Up into damage prevention: a toon already on
full laff could throw a heal and have it soak up the round's damage. It
showed up as a healthy four-toon party being advised to heal itself.
"""
import unittest

from solver import data, party, simulator
from solver.state import Action, BattleState, CogState, ToonState, Track


def cog(level=6):
    mx = data.cog_max_hp(level)
    return CogState("yesman", "bossbot", level, mx, mx)


def healer(laff, max_laff):
    return ToonState(laff, max_laff, {Track.TOON_UP: 7, Track.THROW: 7},
                     {(Track.TOON_UP, 5): 3, (Track.THROW, 5): 3})


class HealOrderTest(unittest.TestCase):

    def test_a_heal_at_full_laff_does_not_absorb_damage(self):
        """The case that exposed it. Healing at the cap is a wasted gag,
        and must not quietly cancel the cogs' turn."""
        heal = Action(track=Track.TOON_UP, level=5, target_index=0)
        landed = []
        for _ in range(40):
            state = BattleState(toons=[healer(80, 80)], cogs=[cog()])
            nxt, _healed, _done = party.step(
                state, heal, mode=party.Mode.COORDINATED, joint=[heal])
            landed.append(nxt.toons[0].laff)
        # Some round out of forty must have left the toon below the cap.
        self.assertTrue(any(l < 80 for l in landed),
                        "a full-laff heal absorbed every cog attack")

    def test_a_heal_below_the_cap_still_heals(self):
        heal = Action(track=Track.TOON_UP, level=5, target_index=0)
        state = BattleState(toons=[healer(10, 80)], cogs=[cog()])
        nxt, healed, _done = party.step(
            state, heal, mode=party.Mode.COORDINATED, joint=[heal])
        self.assertGreater(healed[0], 0)
        self.assertGreater(nxt.toons[0].laff, 10 - 1)

    def test_a_heal_never_exceeds_max_laff(self):
        heal = Action(track=Track.TOON_UP, level=5, target_index=0)
        state = BattleState(toons=[healer(78, 80)], cogs=[cog()])
        nxt, _healed, _done = party.step(
            state, heal, mode=party.Mode.COORDINATED, joint=[heal])
        self.assertLessEqual(nxt.toons[0].laff, 80)

    def test_the_solo_path_agrees(self):
        """`simulator.step` had the identical combined clamp."""
        heal = Action(track=Track.TOON_UP, level=5, target_index=0)
        seen = []
        for _ in range(40):
            state = BattleState(toon=healer(80, 80), cogs=[cog()])
            nxt, _r, _d = simulator.step(state, heal)
            seen.append(nxt.toon.laff)
        self.assertTrue(any(l < 80 for l in seen))


if __name__ == "__main__":
    unittest.main()
