"""The measurement harness, and the silent failure it exists to stop.

Every script re-implemented the action-to-index mapping and ended it
with `i = PASS_INDEX`. That fallback turns "I cannot express this
action" into "the toon holds this round", which is silent, plausible,
and reads as a strategy result. It cost four separate measurements
before it was caught.
"""
import random
import unittest

from solver import sos as sos_mod
from solver.rl import env as env_mod, harness
from solver.state import Action, Track


def _board(seed=7, **kw):
    def sampler(rng):
        state = env_mod.facility_position(rng)
        state.toons = [harness.solo_loadout(rng, **kw)]
        return state

    e = env_mod.BattleEnv(rng=random.Random(seed), sampler=sampler,
                          coordinated=True, max_rounds=40)
    e.reset()
    return e


class IndexTest(unittest.TestCase):

    def test_a_gag_has_one(self):
        entry = next(a for a in env_mod.ACTIONS
                     if a is not None and not a.fire)
        self.assertIsNotNone(harness.action_index(entry))

    def test_a_pass_maps_to_pass(self):
        self.assertEqual(harness.action_index(None), env_mod.PASS_INDEX)
        self.assertEqual(harness.action_index(Action(track=None)),
                         env_mod.PASS_INDEX)

    def test_a_fire_maps_to_its_target(self):
        self.assertEqual(
            harness.action_index(Action(track=None, fire=True,
                                        target_index=0)),
            env_mod._FIRE_INDEX.get(0))

    def test_an_sos_has_no_index(self):
        """None means "not in the table", not "failed" -- `play`
        handles it by passing the raw action."""
        self.assertIsNone(
            harness.action_index(Action(track=None, sos="Flippy")))


class PlayTest(unittest.TestCase):

    def test_a_gag_is_actually_thrown(self):
        e = _board()
        before = sum(c.hp for c in e.state.cogs)
        from solver import simulator
        gag = next(a for a in simulator.legal_actions(e.state)
                   if a.track is Track.THROW)
        harness.play(e, gag)
        self.assertLessEqual(sum(c.hp for c in e.state.cogs), before)

    def test_a_fire_spends_a_slip(self):
        e = _board(fires=3)
        harness.play(e, Action(track=None, fire=True, target_index=0))
        self.assertEqual(e.state.toons[0].fires, 2)

    def test_an_sos_spends_a_card(self):
        e = _board(sos_cards={"Lil Oldman": 1})
        harness.play(e, Action(track=None, sos="Lil Oldman"))
        self.assertEqual(e.state.toons[0].sos_cards.get("Lil Oldman", 0), 0)

    def test_an_unplayable_action_raises_rather_than_passing(self):
        """THE POINT OF THE MODULE. A silent pass reads as a strategy
        failure; a raise reads as the harness bug it is."""
        e = _board()
        bogus = Action(track=None, fire=True, target_index=99)
        with self.assertRaises(harness.UnplayableAction):
            harness.play(e, bogus)


class LoadoutTest(unittest.TestCase):

    def test_a_solo_toon_gets_no_toon_up(self):
        """It cannot heal itself, so the training spends part of an
        80-gag pouch on gags that can never be thrown."""
        toon = harness.solo_loadout(random.Random(1))
        self.assertNotIn(Track.TOON_UP, toon.track_exp)
        self.assertFalse(any(k[0] is Track.TOON_UP
                             for k in toon.gag_counts))

    def test_the_pouch_respects_capacity(self):
        """Level 7s are exempt, so count what the pouch actually holds.
        Filling every gag to its carry limit sums far past 80 and makes
        the position degenerate."""
        from solver.data import gags as gags_mod
        toon = harness.solo_loadout(random.Random(1))
        counted = sum(n for (_t, level), n in toon.gag_counts.items()
                      if level < gags_mod.POUCH_EXEMPT_LEVEL)
        self.assertLessEqual(counted, toon.pouch_capacity)
        self.assertGreater(counted, 0)

    def test_consumables_default_to_none(self):
        toon = harness.solo_loadout(random.Random(1))
        self.assertEqual(toon.fires, 0)
        self.assertEqual(toon.unites_held, 0)
        self.assertEqual(dict(toon.sos_cards), {})


class CheckPositionTest(unittest.TestCase):

    def test_a_board_before_reset_is_refused(self):
        """`facility_position` builds the party and `reset` builds the
        board, so a state used before `reset` has nothing to fight."""
        state = env_mod.facility_position(random.Random(3))
        with self.assertRaises(harness.UnplayableAction):
            harness.check_position(state)

    def test_a_real_board_passes(self):
        harness.check_position(_board().state)

    def test_a_toon_that_cannot_damage_is_refused(self):
        e = _board()
        e.state.toons[0].gag_counts = {}
        with self.assertRaises(harness.UnplayableAction):
            harness.check_position(e.state)


if __name__ == "__main__":
    unittest.main()


class TrainingTest(unittest.TestCase):
    """`training` is not a detail.

    `trackExp` is `(training - 1) * 10`, so a maxed track adds +60
    accuracy against a spread of only 35 points between the weakest and
    strongest gag in a track. Maxed, the 95 cap flattens the whole line
    against low-level cogs and gag choice stops depending on accuracy;
    at 3 or 4 it does not.

    `facility_position` samples the real spread and only about 13% of
    its tracks are maxed, while every A/B measurement in this project
    forced 7.
    """

    def test_it_defaults_to_maxed(self):
        from solver import mechanics
        toon = harness.solo_loadout(random.Random(1))
        self.assertEqual(mechanics.calc_track_exp(toon, Track.LURE), 60)

    def test_lower_training_lowers_the_bonus(self):
        from solver import mechanics
        for level, expect in ((7, 60), (5, 40), (3, 20), (1, 0)):
            toon = harness.solo_loadout(random.Random(1), training=level)
            self.assertEqual(mechanics.calc_track_exp(toon, Track.LURE),
                             expect)

    def test_maxed_flattens_the_lure_line_and_lower_does_not(self):
        """The finding this parameter exists for."""
        from solver import data, mechanics
        from solver.state import CogState
        hp = data.cog_max_hp(5)
        cogs = [CogState(department="lawbot", cog_type="ambulance_chaser",
                         level=5, hp=hp, max_hp=hp)]
        maxed = harness.solo_loadout(random.Random(1), training=7)
        part = harness.solo_loadout(random.Random(1), training=3)
        at_max = {mechanics.calc_toon_accuracy(Track.LURE, lv, maxed, cogs,
                                               all_cogs=cogs)
                  for lv in range(1, 8)}
        at_part = {mechanics.calc_toon_accuracy(Track.LURE, lv, part, cogs,
                                                all_cogs=cogs)
                   for lv in range(1, 8)}
        self.assertEqual(at_max, {95}, "maxed should sit on the cap")
        self.assertGreater(len(at_part), 1, "undertrained should separate")

    def test_scarce_gags_only_exist_when_trained_for(self):
        """Levels 6 and 7 are the only gags with a carry limit of 5 or
        fewer, so `SCARCITY_UNITS` is inert below training 6 -- which is
        why measuring it on maxed toons was the right place."""
        for level in (3, 5):
            toon = harness.solo_loadout(random.Random(2), training=level)
            self.assertFalse([k for k in toon.gag_counts if k[1] > level])
