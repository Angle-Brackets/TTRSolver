"""Legal-move rules found wrong in live play."""
import unittest

from solver import data
from solver import simulator
from solver.simulator import apply_toon_action, legal_actions
from solver.state import Action, BattleState, CogState, ToonState, Track


def _board(lured):
    toon = ToonState(70, 100, {Track.TRAP: 7, Track.THROW: 7},
                     {(Track.TRAP, 7): 1, (Track.THROW, 5): 4})
    hp = data.cog_max_hp(12)
    cogs = [CogState("mr_hollywood", "sellbot", 12, hp, hp) for _ in lured]
    for cog, is_lured in zip(cogs, lured):
        if is_lured:
            cog.status.apply_lure(80, 3, level=5)
    return BattleState(toons=[toon], cogs=cogs)


class RailroadTest(unittest.TestCase):
    """[CONFIRMED] by the owner: a Railroad needs ONE unlured cog; it then
    wakes the lured ones and arms every cog. With all lured it cannot be
    placed."""

    railroad = Action(Track.TRAP, 7, None)

    def test_not_offered_when_every_cog_is_lured(self):
        self.assertNotIn(self.railroad, legal_actions(_board([True])))
        self.assertNotIn(self.railroad, legal_actions(_board([True, True])))

    def test_one_unlured_cog_lets_it_wake_and_arm_the_row(self):
        board = _board([True, False])
        self.assertIn(self.railroad, legal_actions(board))
        apply_toon_action(board, self.railroad, hit=True)
        self.assertTrue(all(c.status.trapped and not c.status.lured for c in board.cogs))

    def test_a_single_trap_is_still_refused_on_a_lured_cog(self):
        board = _board([True])
        board.toons[0].gag_counts = {(Track.TRAP, 5): 2}
        self.assertNotIn(Action(Track.TRAP, 5, 0), legal_actions(board))



class OneRoundSosTest(unittest.TestCase):
    """[OWNER] Realms plays Toons Hit and Cogs Miss as Toontown Online
    did: certain, and for the ONE turn after the call only."""

    def _board(self, realms):
        board = _board([False])
        board.sos_one_round = realms
        board.toons[0].sos_cards = {"Soggy Bottom": 1, "Julius Wheezer": 1}
        return board

    def test_toons_hit_covers_only_the_next_turn_and_never_misses(self):
        from solver import simulator, sos
        board = self._board(realms=True)
        apply_toon_action(board, Action(track=None, sos="Soggy Bottom"), hit=True)
        throw = Action(Track.THROW, 5, 0)
        self.assertLess(simulator.toon_action_accuracy(board, throw), 100)   # this turn
        simulator.cogs_miss_factor(board)                             # round ends
        self.assertEqual(100, simulator.toon_action_accuracy(board, throw))  # next turn
        simulator.cogs_miss_factor(board)
        self.assertLess(simulator.toon_action_accuracy(board, throw), 100)   # gone
        self.assertFalse(sos.active(board, "toons_hit_rounds"))

    def test_a_party_round_never_caps_it_back_to_95(self):
        """Found by the three-way parity check: the party path re-capped
        Realms' certain hit at 95 after adding the stun bonus."""
        import random
        board = self._board(realms=True)
        board.toons_hit_rounds = 1
        hits = 0
        for seed in range(400):
            trial = board.clone()
            trial.cogs[0].hp = 1
            simulator.apply_party_round(trial, [Action(Track.THROW, 5, 0)],
                                        rng=random.Random(seed))
            hits += trial.cogs[0].status.is_dead
        self.assertEqual(400, hits)

    def test_cogs_miss_spares_this_turn_and_blanks_the_next(self):
        from solver import simulator
        board = self._board(realms=True)
        apply_toon_action(board, Action(track=None, sos="Julius Wheezer"), hit=True)
        self.assertEqual(1.0, simulator.cogs_miss_factor(board))
        self.assertEqual(0.0, simulator.cogs_miss_factor(board))
        self.assertEqual(1.0, simulator.cogs_miss_factor(board))

    def test_ttr_keeps_its_own_numbers(self):
        from solver import simulator
        board = self._board(realms=False)
        apply_toon_action(board, Action(track=None, sos="Julius Wheezer"), hit=True)
        factors = [simulator.cogs_miss_factor(board) for _ in range(6)]
        self.assertEqual([0.25] * 5 + [1.0], factors)

    def test_exact_search_sees_cogs_miss(self):
        """It never did: the timer was in the memo key and nowhere else."""
        from solver import outcomes
        plain = _board([False])
        wheezed = _board([False])
        wheezed.cogs_miss_rounds = 3
        pie = Action(Track.THROW, 5, 0)

        def lost(board):
            return sum(p * (board.toon.laff - st.toon.laff)
                       for p, st, _r in outcomes.action_outcomes(board, pie))
        self.assertLess(lost(wheezed), lost(plain) * 0.5)

    def test_a_party_honours_cogs_miss(self):
        """The party phase skipped it: Julius Wheezer did nothing in a
        group and Toons Hit never ran out."""
        import random
        from solver import party
        board = _board([False, False, False])
        board.toons.append(board.toons[0].clone() if hasattr(board.toons[0], "clone")
                           else _board([False]).toons[0])
        board.cogs_miss_rounds = 1      # the turn after a Realms call
        board.sos_one_round = True
        party._party_cog_phase(board, [0, 0], random.Random(1))
        self.assertEqual([70, 70], [t.laff for t in board.toons])
        self.assertEqual(0, board.cogs_miss_rounds)
        party._party_cog_phase(board, [0, 0], random.Random(1))
        self.assertLess(min(t.laff for t in board.toons), 70)



class WastedReachTest(unittest.TestCase):
    """[OWNER] Bessie with two of four cogs lured drops two pianos on
    nothing -- and any hit-all is charged the same way."""

    def test_bessie_and_a_group_drop_waste_the_lured_share(self):
        from solver.simulator import wasted_reach
        board = _board([True, True, False, False])
        self.assertEqual(0.5, wasted_reach(board, Action(track=None, sos="Barnacle Bessie")))
        self.assertEqual(0.5, wasted_reach(board, Action(Track.DROP, 7, None)))
        self.assertEqual(0.0, wasted_reach(board, Action(track=None, sos="Moe Zart")))
        self.assertEqual(0.0, wasted_reach(board, Action(Track.DROP, 5, 2)))

    def test_a_trap_is_charged_for_the_lures_it_undoes(self):
        from solver.simulator import wasted_reach
        board = _board([True, False, False, False])
        self.assertEqual(0.25, wasted_reach(board, RailroadTest.railroad))

    def test_nothing_is_wasted_on_a_clean_board(self):
        from solver.simulator import wasted_reach
        board = _board([False, False])
        for action in (Action(track=None, sos="Barnacle Bessie"),
                       Action(Track.DROP, 7, None), RailroadTest.railroad):
            self.assertEqual(0.0, wasted_reach(board, action))

    def test_the_playouts_charge_it_and_every_call(self):
        from solver.search import playout
        board = _board([True, True, False, False])
        board.toons[0].sos_cards = {"Barnacle Bessie": 2}
        after = board.clone()
        bessie = Action(track=None, sos="Barnacle Bessie")
        apply_toon_action(after, bessie, hit=True)
        self.assertAlmostEqual(playout.SOS_CALL_PRICE + 0.5 * playout.SOS_REACH_PRICE,
                               playout.spend_charge(board, after, [bessie]))
        self.assertEqual(0.0, playout.spend_charge(board, board.clone(), [None]))


if __name__ == "__main__":
    unittest.main()


class HealCardWasteTest(unittest.TestCase):
    """Seen live on Realms: Flippy (180 laff) called at 92/100 with every
    cog lured. The overflow is waste, like a hit-all's unreachable cogs."""

    def _state(self, laff):
        from solver import data
        from solver.state import BattleState, CogState, ToonState, Track
        toon = ToonState(laff, 100, {Track.THROW: 7}, {(Track.THROW, 5): 3})
        hp = data.cog_max_hp(6)
        return BattleState(toons=[toon], cogs=[CogState("name_dropper", "sellbot", 6, hp, hp)])

    def test_flippy_at_92_of_100_is_almost_all_waste(self):
        from solver import simulator
        from solver.state import Action
        waste = simulator.wasted_reach(self._state(92), Action(track=None, sos="Flippy"))
        self.assertAlmostEqual(172 / 180, waste, places=6)

    def test_a_heal_that_fits_wastes_nothing(self):
        from solver import simulator
        from solver.state import Action
        self.assertEqual(0.0, simulator.wasted_reach(self._state(30),
                                                    Action(track=None, sos="Madam Chuckle")))

    def test_a_smaller_card_wastes_less_for_the_same_heal(self):
        """At 10/100 Flippy and Daffy Don both restore 90; the premium
        card throws away more, so it is charged more."""
        from solver import simulator
        from solver.state import Action
        state = self._state(10)
        self.assertGreater(simulator.wasted_reach(state, Action(track=None, sos="Flippy")),
                           simulator.wasted_reach(state, Action(track=None, sos="Daffy Don")))
