"""The reward is a choice, so the choices have to be honest.

An objective decides what "playing well" means. These check the presets
actually differ, that the default reproduces the simulator's own reward
convention exactly, and that the scarcity term prices gags from data rather
than from an assumption about levels.

stdlib unittest only -- pytest is not installed.
"""
import unittest

from solver import data, outcomes, simulator
from solver.search import objective as obj
from solver.search import expectimax
from solver.state import (Action, BattleState, CogState, Track,
                          ToonState)
from solver.testing import two_flunky_fight


class TestDefaultMatchesTheSimulator(unittest.TestCase):
    def test_balanced_reproduces_step_rewards(self):
        """A sampled rollout and a searched line must optimise the same
        thing, or the benchmark measures one policy against another's
        scoring."""
        state = two_flunky_fight()
        action = Action(track=Track.THROW, level=3, target_index=0)
        for prob, nxt, reward in outcomes.action_outcomes(state, action):
            laff_lost = state.toon.laff - nxt.toon.laff
            expected = -float(laff_lost) - 0.1 * 3
            if nxt.is_win():
                expected += 100.0
            elif nxt.toon.laff <= 0:
                expected -= 100.0
            self.assertAlmostEqual(reward, expected, places=9)

    def test_a_bare_float_still_works(self):
        """Older callers passed a gag-cost lambda positionally."""
        state = two_flunky_fight()
        action = Action(track=Track.THROW, level=3, target_index=0)
        a = outcomes.action_outcomes(state, action, 0.1)
        b = outcomes.action_outcomes(state, action, obj.BALANCED)
        self.assertEqual([r for _p, _s, r in a], [r for _p, _s, r in b])


class TestPresets(unittest.TestCase):
    def test_every_preset_is_registered_and_described(self):
        for name, preset in obj.PRESETS.items():
            with self.subTest(name=name):
                self.assertEqual(preset.name, name)
                self.assertTrue(preset.description.strip())
                self.assertIs(obj.get(name), preset)

    def test_unknown_preset_names_the_alternatives(self):
        with self.assertRaises(KeyError) as caught:
            obj.get("nonsense")
        self.assertIn("balanced", str(caught.exception))

    def test_presets_actually_disagree(self):
        """A preset that never changes a decision is decoration.

        Needs a position where the trade-off is live: cogs the one Opera
        Singer cannot clear on its own, so whether to spend it now or set
        up first is a genuine question rather than a formality.

        The position was changed when the fitted evaluator landed. The
        previous one stopped discriminating -- every preset agreed --
        which is what a better leaf evaluator tends to do: it resolves
        more positions into having one clearly best move. That makes the
        test harder to write and is not itself a regression, so what
        matters is that *some* position still separates the presets.
        """
        # Found by sweeping random positions for maximum disagreement.
        # It separates them three ways: `survive` lures to stop the
        # incoming damage, `conserve` spends the cheapest gag that still
        # kills something, and the rest take the group Sound. A toon on
        # 17 laff against a healthy level-5 is the shape of position
        # where what you are optimising for actually shows.
        counts = {(Track.DROP, 3): 2, (Track.LURE, 2): 2,
                  (Track.TRAP, 3): 2, (Track.SOUND, 4): 3}
        toon = ToonState(laff=17, max_laff=50,
                         track_exp={t: 7 for t, _l in counts},
                         gag_counts=counts)
        cogs = [CogState(cog_type="flunky", department="bossbot", level=5,
                         hp=36, max_hp=data.cog_max_hp(5)),
                CogState(cog_type="flunky", department="bossbot", level=2,
                         hp=11, max_hp=data.cog_max_hp(2))]
        state = BattleState(toon=toon, cogs=cogs)

        moves = {name: str(expectimax.best_action(state, 2, objective=preset))
                 for name, preset in obj.PRESETS.items()}
        self.assertGreater(len(set(moves.values())), 1,
                           f"all presets chose the same move: {moves}")


class TestScarcityPricing(unittest.TestCase):
    def test_scarce_gags_cost_more(self):
        """Priced from Gag.max_carry, not from level: you can hold thirty
        Cupcakes and one Wedding Cake."""
        conserve = obj.CONSERVE
        cupcake = conserve.gag_price(Track.THROW, 1)
        wedding = conserve.gag_price(Track.THROW, 7)
        self.assertGreater(wedding, cupcake * 5)

    def test_scarcity_is_off_by_default(self):
        self.assertAlmostEqual(obj.BALANCED.gag_price(Track.THROW, 1), 0.1)
        self.assertAlmostEqual(obj.BALANCED.gag_price(Track.THROW, 7), 0.7)

    def test_sound_is_priced_higher_than_throw_at_the_same_level(self):
        """Sound's carry limits are lower across the board, so scarcity
        pricing should notice without being told about tracks."""
        conserve = obj.CONSERVE
        self.assertGreater(conserve.gag_price(Track.SOUND, 1),
                           conserve.gag_price(Track.THROW, 1))


class TestTurnCost(unittest.TestCase):
    def test_turn_cost_charges_every_round(self):
        speedy = obj.Objective(turn_cost=5.0, gag_cost=0.0)
        plain = obj.Objective(turn_cost=0.0, gag_cost=0.0)
        self.assertAlmostEqual(
            plain.step_reward(0, Track.THROW, 3, False, False)
            - speedy.step_reward(0, Track.THROW, 3, False, False), 5.0)

    def test_laff_weight_scales_damage(self):
        defensive = obj.Objective(laff_weight=3.0, gag_cost=0.0)
        self.assertAlmostEqual(
            defensive.step_reward(10, Track.THROW, 3, False, False), -30.0)


if __name__ == "__main__":
    unittest.main()
