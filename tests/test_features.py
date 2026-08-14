"""Features for the fitted leaf evaluator.

These pin the distinctions the hand-written heuristic could not make.
Each one is a position pair it scored identically and that is worth
measurably different amounts.
"""
import unittest

from solver import data
from solver.search import features, fitted
from solver.search.expectimax import hand_written_value
from solver.state import BattleState, CogState, ToonState, Track


def toon(laff=50, gags=None):
    gags = gags if gags is not None else {(Track.THROW, 4): 2}
    return ToonState(laff, 50, {t: 6 for t, _l in gags}, dict(gags))


def cog(level=5, hp=None):
    full = data.cog_max_hp(level)
    return CogState("flunky", "bossbot", level, hp if hp is not None else full,
                    full)


def state(cogs, **kw):
    return BattleState(toon=toon(**kw), cogs=cogs)


class ShapeTest(unittest.TestCase):

    def test_vector_matches_the_declared_names(self):
        vec = features.extract(state([cog()]))
        self.assertEqual(len(vec), len(features.FEATURE_NAMES))

    def test_every_feature_is_finite(self):
        for st in (state([cog()]), state([cog(2, 1)]), state([], laff=1),
                   state([cog(), cog()], laff=1)):
            with self.subTest(state=st):
                for name, v in features.as_dict(st).items():
                    self.assertEqual(v, v, f"{name} is NaN")
                    self.assertLess(abs(v), 1e6, name)

    def test_no_cogs_does_not_divide_by_zero(self):
        features.extract(state([]))

    def test_dead_cogs_are_excluded(self):
        alive = state([cog(), cog()])
        one_dead = state([cog(), cog()])
        one_dead.cogs[1].status.is_dead = True
        self.assertGreater(features.as_dict(alive)["cogs_alive"],
                           features.as_dict(one_dead)["cogs_alive"])


class BlindSpotTest(unittest.TestCase):
    """Each of these was invisible to the hand-written heuristic.

    The comparisons are against `hand_written_value` deliberately, not
    against `heuristic_value` -- the latter now dispatches to the fitted
    model, which can see all of these, so asserting the blind spot
    through it would test nothing.
    """

    def test_gags_remaining_are_visible(self):
        many = state([cog(5, 20)], gags={(Track.THROW, 4): 6})
        few = state([cog(5, 20)], gags={(Track.THROW, 4): 1})
        self.assertEqual(hand_written_value(many), hand_written_value(few))
        self.assertNotEqual(features.as_dict(many)["gags_ratio"],
                            features.as_dict(few)["gags_ratio"])

    def test_kill_threshold_is_visible(self):
        """Total cog HP identical; what differs is whether a single gag
        can remove a cog."""
        killable = state([cog(5, 3), cog(5, 40)],
                         gags={(Track.THROW, 4): 2})
        spread = state([cog(5, 21), cog(5, 22)],
                       gags={(Track.THROW, 4): 2})
        self.assertAlmostEqual(hand_written_value(killable),
                               hand_written_value(spread), delta=1.0)
        self.assertNotEqual(features.as_dict(killable)["killable_ratio"],
                            features.as_dict(spread)["killable_ratio"])

    def test_lure_is_visible(self):
        awake = state([cog(5, 20)])
        lured = state([cog(5, 20)])
        lured.cogs[0].status.apply_lure(60, 3, level=3)
        self.assertEqual(hand_written_value(awake), hand_written_value(lured))
        self.assertNotEqual(features.as_dict(awake)["lured_ratio"],
                            features.as_dict(lured)["lured_ratio"])

    def test_a_trap_is_only_worth_something_with_lure_in_hand(self):
        """The conjunction. A trap does nothing until a cog is lured onto
        it, so these two states are not worth the same -- and they differ
        only in a gag count unrelated to the trap."""
        with_lure = state([cog(5, 20)], gags={(Track.TRAP, 3): 1,
                                              (Track.LURE, 3): 1})
        without = state([cog(5, 20)], gags={(Track.TRAP, 3): 1,
                                            (Track.THROW, 4): 1})
        for st in (with_lure, without):
            st.cogs[0].status.trapped = True
            st.cogs[0].status.trap_level = 3
            st.cogs[0].status.trap_track = Track.TRAP
        a, b = features.as_dict(with_lure), features.as_dict(without)
        self.assertEqual(a["trapped_with_lure"], 1.0)
        self.assertEqual(a["trapped_without_lure"], 0.0)
        self.assertEqual(b["trapped_with_lure"], 0.0)
        self.assertEqual(b["trapped_without_lure"], 1.0)

    def test_one_hit_from_death_is_a_step_not_a_slide(self):
        safe = state([cog(5, 20)], laff=48)
        doomed = state([cog(5, 20)], laff=2)
        self.assertEqual(features.as_dict(safe)["one_hit_from_death"], 0.0)
        self.assertEqual(features.as_dict(doomed)["one_hit_from_death"], 1.0)


class FittedTest(unittest.TestCase):

    def test_falls_back_to_the_hand_written_form_when_unfitted(self):
        """The solver must always have something to score with."""
        st = state([cog()])
        if not fitted.is_fitted():
            self.assertEqual(fitted.value(st), hand_written_value(st))

    def test_weight_count_matches_the_feature_count(self):
        if fitted.WEIGHTS is not None:
            self.assertEqual(len(fitted.WEIGHTS),
                             len(features.FEATURE_NAMES),
                             "WEIGHTS is positional; a mismatch is silent")

    def test_explain_is_empty_until_fitted(self):
        if not fitted.is_fitted():
            self.assertEqual(fitted.explain(state([cog()])), [])


if __name__ == "__main__":
    unittest.main()


class PartyFeaturesTest(unittest.TestCase):
    """Features read the team, not `toons[0]`.

    Two properties matter and they pull against each other. Solo vectors
    must be unchanged to the bit, because the shipped weights were
    fitted on solo positions and nothing has retrained them. Party
    vectors must describe the party, rather than silently describing the
    lead toon and calling it the team.

    Party values are DEFINED here, not validated: exact solve cannot
    reach a party position, so there are no labels to fit or check
    against. What this buys is a vector that means something sensible.
    """

    def toon(self, laff=50, counts=None):
        counts = counts or {(Track.THROW, 3): 2}
        return ToonState(laff, 50, {t: 6 for t, _l in counts}, dict(counts))

    def state(self, toons):
        hp = data.cog_max_hp(4)
        return BattleState(toons=toons,
                           cogs=[CogState("flunky", "bossbot", 4, hp, hp)])

    def named(self, state):
        return features.as_dict(state)

    def test_a_solo_state_is_unchanged_by_the_party_code(self):
        """Pinned numerically elsewhere over 300 sampled positions; this
        is the readable version."""
        solo = self.named(self.state([self.toon(laff=25)]))
        self.assertAlmostEqual(solo["laff_ratio"], 0.5)

    def test_laff_is_pooled_over_the_team(self):
        party = self.named(self.state([self.toon(laff=25),
                                       self.toon(laff=50)]))
        self.assertAlmostEqual(party["laff_ratio"], 75 / 100)

    def test_a_sad_toon_contributes_no_laff_and_no_gags(self):
        """They have left the battle; their pouch is not coming back."""
        party = self.named(self.state([
            self.toon(laff=50),
            self.toon(laff=0, counts={(Track.THROW, 5): 10})]))
        solo = self.named(self.state([self.toon(laff=50)]))
        self.assertAlmostEqual(party["laff_ratio"], solo["laff_ratio"])
        self.assertAlmostEqual(party["gags_ratio"], solo["gags_ratio"])

    def test_gags_are_pooled(self):
        one = self.named(self.state([self.toon()]))
        two = self.named(self.state([self.toon(), self.toon()]))
        self.assertGreater(two["gags_ratio"], one["gags_ratio"])

    def test_the_damage_budget_counts_everybodys_pouch(self):
        one = self.named(self.state([
            self.toon(counts={(Track.THROW, 3): 1})]))
        two = self.named(self.state([
            self.toon(counts={(Track.THROW, 3): 1}),
            self.toon(counts={(Track.THROW, 3): 1})]))
        self.assertGreater(two["damage_budget_ratio"],
                           one["damage_budget_ratio"])

    def test_a_trap_on_one_toon_pairs_with_a_lure_on_another(self):
        """The pair is what deals damage, and it does not have to be in
        one pouch -- the same rule `can_still_damage` follows."""
        split = self.named(self.state([
            self.toon(counts={(Track.TRAP, 3): 3}),
            self.toon(counts={(Track.LURE, 3): 3})]))
        trap_only = self.named(self.state([
            self.toon(counts={(Track.TRAP, 3): 3})]))
        self.assertGreater(split["damage_budget_ratio"], 0.0)
        self.assertEqual(trap_only["damage_budget_ratio"], 0.0)

    def test_best_damage_is_the_hardest_anyone_can_throw(self):
        party = self.named(self.state([
            self.toon(counts={(Track.THROW, 1): 5}),
            self.toon(counts={(Track.THROW, 5): 1})]))
        weak = self.named(self.state([self.toon(counts={(Track.THROW, 1): 5})]))
        self.assertGreater(party["best_gag_over_weakest_cog"],
                           weak["best_gag_over_weakest_cog"])

    def test_one_hit_from_death_is_about_the_weakest_toon(self):
        """A round that removes a toon is a step change, and averaging
        it over the party hides the thing the feature exists to see."""
        party = self.named(self.state([self.toon(laff=50),
                                       self.toon(laff=1)]))
        self.assertEqual(party["one_hit_from_death"], 1.0)
        healthy = self.named(self.state([self.toon(laff=50),
                                         self.toon(laff=50)]))
        self.assertEqual(healthy["one_hit_from_death"], 0.0)
