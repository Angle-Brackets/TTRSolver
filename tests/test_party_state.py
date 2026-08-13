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


def cog(level=4, hp=None):
    mx = data.cog_max_hp(level)
    return CogState("flunky", "bossbot", level, hp if hp is not None else mx, mx)


def toon(laff=50, counts=None, exp=None):
    counts = {(Track.THROW, 3): 2} if counts is None else counts
    exp = exp or {t: 6 for t, _l in counts}
    return ToonState(laff, 50, exp, dict(counts))


class ConstructionTest(unittest.TestCase):

    def test_a_solo_battle_still_reads_as_one_toon(self):
        state = BattleState(toon=toon(), cogs=[cog()])
        self.assertEqual(len(state.toons), 1)
        self.assertIs(state.toon, state.toons[0])

    def test_exactly_one_of_toon_or_toons(self):
        """Accepting both invites them to disagree."""
        with self.assertRaises(ValueError):
            BattleState(cogs=[cog()])
        with self.assertRaises(ValueError):
            BattleState(cogs=[cog()], toon=toon(), toons=[toon()])

    def test_clone_gives_every_toon_its_own_laff(self):
        """Cloning is the single hottest thing the search does, and a
        shared toon would let one branch's damage appear in another."""
        state = BattleState(toons=[toon(), toon(30)], cogs=[cog()])
        copy = state.clone()
        copy.toons[1].laff = 0
        self.assertEqual(state.toons[1].laff, 30)
        self.assertEqual(copy.toons[1].laff, 0)


class TeamTerminalTest(unittest.TestCase):
    """The losing condition is about the team."""

    def test_one_toon_going_sad_does_not_end_the_battle(self):
        state = BattleState(toons=[toon(0), toon(40)], cogs=[cog()])
        self.assertFalse(state.is_terminal())
        self.assertEqual(len(state.active_toons()), 1)

    def test_every_toon_going_sad_does(self):
        state = BattleState(toons=[toon(0), toon(0)], cogs=[cog()])
        self.assertTrue(state.is_terminal())
        self.assertFalse(state.is_win())

    def test_a_win_needs_someone_left_standing(self):
        dead = cog()
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
                            cogs=[cog()])
        self.assertTrue(state.is_terminal())

    def test_but_not_beside_someone_who_can_swing(self):
        """Eighty Lures and no attacks is a losing solo pouch and a
        perfectly good support one."""
        state = BattleState(
            toons=[toon(counts={(Track.LURE, 3): 80}),
                   toon(counts={(Track.THROW, 3): 2})],
            cogs=[cog()])
        self.assertFalse(state.is_terminal())

    def test_trap_and_lure_split_across_two_toons_still_works(self):
        """Neither pouch can win alone; together they can, and the rule
        has to see the pair rather than the halves."""
        state = BattleState(
            toons=[toon(counts={(Track.TRAP, 3): 3}),
                   toon(counts={(Track.LURE, 3): 3})],
            cogs=[cog()])
        self.assertFalse(state.is_terminal())

    def test_a_sad_toons_pouch_does_not_count(self):
        """They have left the battle and are not throwing anything."""
        state = BattleState(
            toons=[toon(counts={(Track.LURE, 3): 80}),
                   toon(laff=0, counts={(Track.THROW, 3): 2})],
            cogs=[cog()])
        self.assertTrue(state.is_terminal())

    def test_a_whole_party_out_of_attacks_is_lost(self):
        state = BattleState(
            toons=[toon(counts={(Track.TOON_UP, 3): 5}),
                   toon(counts={(Track.LURE, 3): 5})],
            cogs=[cog()])
        self.assertTrue(state.is_terminal())


class StateKeyTest(unittest.TestCase):
    """The memo has to tell two parties apart."""

    def test_the_same_lead_toon_with_a_different_teammate_is_a_different_state(self):
        """Keying on toons[0] alone would let the transposition table
        answer about one party with another's value -- the quietest way
        for a memo to be wrong."""
        from solver import outcomes

        a = BattleState(toons=[toon(), toon(counts={(Track.THROW, 3): 2})],
                        cogs=[cog()])
        b = BattleState(toons=[toon(), toon(counts={(Track.SOUND, 4): 2})],
                        cogs=[cog()])
        self.assertNotEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_order_matters_because_toons_are_not_interchangeable(self):
        from solver import outcomes

        x = toon(counts={(Track.THROW, 3): 2})
        y = toon(counts={(Track.SOUND, 4): 2})
        self.assertNotEqual(
            outcomes.state_key(BattleState(toons=[x, y], cogs=[cog()])),
            outcomes.state_key(BattleState(toons=[y, x], cogs=[cog()])))

    def test_a_solo_key_is_unchanged(self):
        """Solo is every position the search actually visits today, so
        its key must not have grown a tuple around it."""
        from solver import outcomes

        key = outcomes.state_key(BattleState(toon=toon(), cogs=[cog()]))
        self.assertEqual(key[0], 50)          # laff, not a tuple of laffs

    def test_laff_alone_distinguishes_parties_for_merging(self):
        from solver import outcomes

        a = BattleState(toons=[toon(50), toon(40)], cogs=[cog()])
        b = BattleState(toons=[toon(50), toon(30)], cogs=[cog()])
        self.assertNotEqual(outcomes.merge_key(a), outcomes.merge_key(b))


class CogTargetTest(unittest.TestCase):

    def test_one_toon_is_not_a_choice(self):
        self.assertEqual(mechanics.pick_cog_target(cog(), [toon()]), 0)

    def test_a_party_refuses_rather_than_guessing(self):
        """Returning 0 would mean every cog attacks the lead toon
        forever: a party that never spreads damage and whose support
        toons are invulnerable. Worse than no answer."""
        with self.assertRaises(NotImplementedError):
            mechanics.pick_cog_target(cog(), [toon(), toon()])


if __name__ == "__main__":
    unittest.main()
