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

    def test_a_heal_below_the_cap_still_heals_the_TEAMMATE(self):
        """Toon-Up heals someone else -- see test_party_round."""
        heal = Action(track=Track.TOON_UP, level=5, target_index=1)
        state = BattleState(toons=[healer(80, 80), healer(10, 80)],
                            cogs=[cog()])
        nxt, healed, _done = party.step(
            state, heal, mode=party.Mode.COORDINATED, joint=[heal, None])
        self.assertEqual(healed[0], 0)
        self.assertGreater(healed[1], 0)

    def test_a_heal_never_exceeds_max_laff(self):
        heal = Action(track=Track.TOON_UP, level=5, target_index=1)
        state = BattleState(toons=[healer(80, 80), healer(78, 80)],
                            cogs=[cog()])
        nxt, _healed, _done = party.step(
            state, heal, mode=party.Mode.COORDINATED, joint=[heal, None])
        self.assertLessEqual(nxt.toons[1].laff, 80)

    def test_the_solo_path_agrees(self):
        """`simulator.step` had the identical combined clamp -- and solo
        the heal is zero anyway, since there is nobody else to heal."""
        heal = Action(track=Track.TOON_UP, level=5, target_index=0)
        seen = []
        for _ in range(40):
            state = BattleState(toon=healer(80, 80), cogs=[cog()])
            nxt, _r, _d = simulator.step(state, heal)
            seen.append(nxt.toon.laff)
        self.assertTrue(any(l < 80 for l in seen))


if __name__ == "__main__":
    unittest.main()


class GroupToonUpSplitsBetweenToons(unittest.TestCase):
    """A group Toon-Up divides its laff; it does not hand each toon the
    full amount.

    The wiki says "Group Toon-Up gags provide laff evenly between Toons"
    and never says evenly among WHOM, which stood as a [TODO] on this
    branch. [CONFIRMED] by the owner from play: evenly between the
    RECIPIENTS, and the thrower is not one of them -- they cannot heal
    themselves, which the wiki does state. So one gag over a four-toon
    party is three shares and the full value is delivered.

    A two-toon party hands its single recipient the whole 210. That is
    not a special case; it is one recipient.
    """

    def party(self, n):
        return BattleState(
            toons=[ToonState(laff=20, max_laff=140,
                             track_exp={t: 7 for t in Track},
                             gag_counts={(t, l): 5 for t in Track
                                         for l in range(1, 8)},
                             organic_tracks=frozenset())
                   for _ in range(n)],
            cogs=[CogState("head_hunter", "bossbot", 10, 132, 132)])

    def heal(self, n, hit=True, level=7):
        state = self.party(n)
        return simulator.apply_party_round(
            state, [Action(Track.TOON_UP, level, None)] + [None] * (n - 1),
            hits=[hit] + [True] * (n - 1))

    def test_the_denominator_is_the_recipients(self):
        self.assertEqual(self.heal(2), [0, 210], "one recipient, all of it")
        self.assertEqual(self.heal(3), [0, 105, 105], "210 over two")
        self.assertEqual(self.heal(4), [0, 70, 70, 70], "210 over three")

    def test_nothing_is_lost_to_the_thrower(self):
        """Dividing by the party instead would waste the thrower's
        share; dividing by the recipients delivers the whole gag."""
        for n in (2, 3, 4):
            self.assertEqual(sum(self.heal(n)), 210)

    def test_the_thrower_heals_nobody_including_themselves(self):
        for n in (2, 3, 4):
            self.assertEqual(self.heal(n)[0], 0,
                             "Toons cannot use Toon-Up on themselves")

    def test_a_miss_is_split_the_same_way(self):
        """A Toon-Up that misses still heals 20%, and that is divided
        too -- the split is a property of the gag, not of landing it."""
        self.assertEqual(self.heal(4, hit=False), [0, 14, 14, 14])
        self.assertEqual(self.heal(2, hit=False), [0, 42])

    def test_more_toons_means_less_each(self):
        self.assertGreater(self.heal(2)[1], self.heal(3)[1])
        self.assertGreater(self.heal(3)[1], self.heal(4)[1])

    def test_a_single_target_heal_is_not_split(self):
        """Only GROUP Toon-Up divides. A targeted one gives its whole
        value to the toon it names."""
        state = self.party(4)
        healed = simulator.apply_party_round(
            state, [Action(Track.TOON_UP, 5, 2)] + [None] * 3,
            hits=[True, True, True, True])
        self.assertEqual(healed[0], 0)
        self.assertEqual(healed[1], 0)
        self.assertGreater(healed[2], 0)
        self.assertEqual(healed[3], 0)
