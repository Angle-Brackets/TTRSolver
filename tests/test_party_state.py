"""A battle with more than one toon in it.

Only the *rules* are party-aware so far. The search, the evaluator and
the live readers are all still solo, and these tests pin the boundary:
what a party state does correctly, and what refuses to answer rather
than answering wrongly.

The change that matters is the losing condition. It was a statement
about one toon and had to become a statement about the team, because
the two disagree in both directions -- a sad toon does not end the
fight, and a toon out of attacks has not lost if someone else can still
swing.
"""
import unittest

from solver import data, mechanics
from solver.state import BattleState, CogState, ToonState, Track


def cog_at(level=4, hp=None):
    mx = data.cog_max_hp(level)
    return CogState("flunky", "bossbot", level, hp if hp is not None else mx, mx)


def toon(laff=50, counts=None, exp=None):
    counts = {(Track.THROW, 3): 2} if counts is None else counts
    exp = exp or {t: 6 for t, _l in counts}
    return ToonState(laff, 50, exp, dict(counts))


class ConstructionTest(unittest.TestCase):

    def test_a_solo_battle_still_reads_as_one_toon(self):
        state = BattleState(toon=toon(), cogs=[cog_at()])
        self.assertEqual(len(state.toons), 1)
        self.assertIs(state.toon, state.toons[0])

    def test_exactly_one_of_toon_or_toons(self):
        """Accepting both invites them to disagree."""
        with self.assertRaises(ValueError):
            BattleState(cogs=[cog_at()])
        with self.assertRaises(ValueError):
            BattleState(cogs=[cog_at()], toon=toon(), toons=[toon()])

    def test_clone_gives_every_toon_its_own_laff(self):
        """Cloning is the single hottest thing the search does, and a
        shared toon would let one branch's damage appear in another."""
        state = BattleState(toons=[toon(), toon(30)], cogs=[cog_at()])
        copy = state.clone()
        copy.toons[1].laff = 0
        self.assertEqual(state.toons[1].laff, 30)
        self.assertEqual(copy.toons[1].laff, 0)


class TeamTerminalTest(unittest.TestCase):
    """The losing condition is about the team."""

    def test_one_toon_going_sad_does_not_end_the_battle(self):
        state = BattleState(toons=[toon(0), toon(40)], cogs=[cog_at()])
        self.assertFalse(state.is_terminal())
        self.assertEqual(len(state.active_toons()), 1)

    def test_every_toon_going_sad_does(self):
        state = BattleState(toons=[toon(0), toon(0)], cogs=[cog_at()])
        self.assertTrue(state.is_terminal())
        self.assertFalse(state.is_win())

    def test_a_win_needs_someone_left_standing(self):
        dead = cog_at()
        dead.status.is_dead = True
        self.assertTrue(
            BattleState(toons=[toon(0), toon(40)], cogs=[dead]).is_win())
        self.assertFalse(
            BattleState(toons=[toon(0), toon(0)], cogs=[dead]).is_win())


class PooledDamageTest(unittest.TestCase):
    """`can_still_damage` pools the party's gags.

    Asking it toon-by-toon would call a winnable fight lost the moment
    one member ran out of attacks, which is most of a long battle for a
    support toon.
    """

    def test_a_lure_only_toon_alone_is_lost(self):
        state = BattleState(toon=toon(counts={(Track.LURE, 3): 80}),
                            cogs=[cog_at()])
        self.assertTrue(state.is_terminal())

    def test_but_not_beside_someone_who_can_swing(self):
        """Eighty Lures and no attacks is a losing solo pouch and a
        perfectly good support one."""
        state = BattleState(
            toons=[toon(counts={(Track.LURE, 3): 80}),
                   toon(counts={(Track.THROW, 3): 2})],
            cogs=[cog_at()])
        self.assertFalse(state.is_terminal())

    def test_trap_and_lure_split_across_two_toons_still_works(self):
        """Neither pouch can win alone; together they can, and the rule
        has to see the pair rather than the halves."""
        state = BattleState(
            toons=[toon(counts={(Track.TRAP, 3): 3}),
                   toon(counts={(Track.LURE, 3): 3})],
            cogs=[cog_at()])
        self.assertFalse(state.is_terminal())

    def test_a_sad_toons_pouch_does_not_count(self):
        """They have left the battle and are not throwing anything."""
        state = BattleState(
            toons=[toon(counts={(Track.LURE, 3): 80}),
                   toon(laff=0, counts={(Track.THROW, 3): 2})],
            cogs=[cog_at()])
        self.assertTrue(state.is_terminal())

    def test_a_whole_party_out_of_attacks_is_lost(self):
        state = BattleState(
            toons=[toon(counts={(Track.TOON_UP, 3): 5}),
                   toon(counts={(Track.LURE, 3): 5})],
            cogs=[cog_at()])
        self.assertTrue(state.is_terminal())


class StateKeyTest(unittest.TestCase):
    """The memo has to tell two parties apart."""

    def test_the_same_lead_toon_with_a_different_teammate_is_a_different_state(self):
        """Keying on toons[0] alone would let the transposition table
        answer about one party with another's value -- the quietest way
        for a memo to be wrong."""
        from solver import outcomes

        a = BattleState(toons=[toon(), toon(counts={(Track.THROW, 3): 2})],
                        cogs=[cog_at()])
        b = BattleState(toons=[toon(), toon(counts={(Track.SOUND, 4): 2})],
                        cogs=[cog_at()])
        self.assertNotEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_order_matters_because_toons_are_not_interchangeable(self):
        from solver import outcomes

        x = toon(counts={(Track.THROW, 3): 2})
        y = toon(counts={(Track.SOUND, 4): 2})
        self.assertNotEqual(
            outcomes.state_key(BattleState(toons=[x, y], cogs=[cog_at()])),
            outcomes.state_key(BattleState(toons=[y, x], cogs=[cog_at()])))

    def test_a_solo_key_is_unchanged(self):
        """Solo is every position the search actually visits today, so
        its key must not have grown a tuple around it."""
        from solver import outcomes

        key = outcomes.state_key(BattleState(toon=toon(), cogs=[cog_at()]))
        self.assertEqual(key[0], 50)          # laff, not a tuple of laffs

    def test_laff_alone_distinguishes_parties_for_merging(self):
        from solver import outcomes

        a = BattleState(toons=[toon(50), toon(40)], cogs=[cog_at()])
        b = BattleState(toons=[toon(50), toon(30)], cogs=[cog_at()])
        self.assertNotEqual(outcomes.merge_key(a), outcomes.merge_key(b))


class CogTargetSelectionTest(unittest.TestCase):
    """Which toon a cog hits back at.

    [OPEN TOONTOWN SOURCE], not [CONFIRMED]. The wiki says only that a
    single attack is "more likely" to target whoever dealt the most
    damage, and gives no numbers. The 75/25 split and the proportional
    weighting come from BattleCalculatorAI.__calcSuitTarget, which is
    Toontown Online code -- a better lead than a prose description,
    since it is the algorithm rather than an account of it, and the wiki
    corroborates its shape. Still not TTR.

    The two bugs in that function are deliberately not reproduced; see
    `mechanics.pick_cog_target` for what they are and why.
    """

    class Rolls:
        """A stand-in for `random` with a scripted sequence."""

        def __init__(self, rolls, choice=None):
            self.rolls = list(rolls)
            self._choice = choice

        def randint(self, _lo, _hi):
            return self.rolls.pop(0)

        def choice(self, seq):
            return self._choice if self._choice is not None else seq[0]

    def hurt_cog(self, damage=None):
        c = cog_at(4)
        for index, amount in (damage or {}).items():
            c.status.record_damage(index, amount)
        return c

    def test_one_toon_is_not_a_choice(self):
        self.assertEqual(mechanics.pick_cog_target(cog_at(), [toon()]), 0)

    def test_an_undamaged_cog_picks_at_random(self):
        """Nobody has hurt it, so there is nobody to hit back at."""
        rng = self.Rolls([0], choice=1)
        self.assertEqual(
            mechanics.pick_cog_target(self.hurt_cog(), [toon(), toon()], rng),
            1)

    def test_it_hits_back_at_its_only_attacker(self):
        rng = self.Rolls([0, 0])
        self.assertEqual(
            mechanics.pick_cog_target(self.hurt_cog({1: 50}),
                                      [toon(), toon()], rng), 1)

    def test_a_high_roll_goes_random_instead(self):
        """The quarter of the time that makes a cog unpredictable."""
        rng = self.Rolls([99], choice=0)
        self.assertEqual(
            mechanics.pick_cog_target(self.hurt_cog({1: 50}),
                                      [toon(), toon()], rng), 0)

    def test_damage_shares_decide_who_it_picks(self):
        """Toon 0 dealt a quarter and toon 1 three quarters, so a roll
        below 25 lands on the first and above it on the second."""
        for roll, want in ((0, 0), (24, 0), (25, 1), (99, 1)):
            rng = self.Rolls([0, roll])
            got = mechanics.pick_cog_target(
                self.hurt_cog({0: 25, 1: 75}), [toon(), toon()], rng)
            self.assertEqual(got, want, f"roll {roll}")

    def test_a_sad_toon_is_not_a_target(self):
        """They have left the battle, however much they hurt it first."""
        rng = self.Rolls([0, 0], choice=1)
        got = mechanics.pick_cog_target(
            self.hurt_cog({0: 100}), [toon(laff=0), toon()], rng)
        self.assertEqual(got, 1)


class DamageTrackingTest(unittest.TestCase):
    """What the selector reads, and what it costs when nobody needs it."""

    def test_damage_accumulates_per_toon(self):
        c = cog_at()
        c.status.record_damage(1, 10)
        c.status.record_damage(1, 15)
        c.status.record_damage(0, 5)
        self.assertEqual(c.status.damage_by_toon, {1: 25, 0: 5})

    def test_zero_damage_records_nothing(self):
        c = cog_at()
        c.status.record_damage(0, 0)
        self.assertIsNone(c.status.damage_by_toon)

    def test_nothing_is_allocated_while_solo(self):
        """The common case must not pay for the party case: `copy` is
        the hottest thing the search does."""
        self.assertIsNone(cog_at().status.damage_by_toon)
        self.assertIsNone(cog_at().status.copy().damage_by_toon)

    def test_recorded_damage_survives_a_copy_independently(self):
        c = cog_at()
        c.status.record_damage(0, 10)
        other = c.status.copy()
        other.record_damage(0, 5)
        self.assertEqual(c.status.damage_by_toon, {0: 10})
        self.assertEqual(other.damage_by_toon, {0: 15})


if __name__ == "__main__":
    unittest.main()
