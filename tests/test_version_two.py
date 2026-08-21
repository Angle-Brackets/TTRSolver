"""Version 2.0 Cogs: two layers, and no carryover between them.

[CONFIRMED] TTR wiki (Version 2.0 Cogs): a v2.0 is its suit plus its
Skelecog form, each with the health of a normal cog of that level, and it
is only defeated once both are gone. The published totals are exactly
twice the normal table on all twelve levels.

[CONFIRMED] same page: "A mechanic known as 'carryover damage' for gags
when used against Version 2.0 Cogs was removed as a result of rebalancing
changes made during the 3.0.0 update." So overkill on the suit is
discarded rather than spilling into the Skelecog.

REINFORCED PLATING NEEDS NO CODE. The wiki calls it a status effect, but
what it describes is the ABSENCE of TTO's rule: in TTO a Skelecog's turn
was skipped on the round its suit broke, and TTR removed that skip. To
break the plating you must hit the cog; hitting a lured cog wakes it; an
awake cog attacks. That is ordinary lure mechanics and the simulator
already does it -- there is no override to implement, and inventing one
would be wrong.
"""
import unittest

from solver import data, simulator
from solver.state import Action, BattleState, CogState, Track, ToonState


def v2(level=8):
    hp = data.cog_max_hp(level)
    cog = CogState(cog_type="Flunky", department="bossbot",
                   level=level, hp=hp, max_hp=hp)
    cog.status.suited = True
    return cog


def _state(cog, gags=None, fires=0):
    toon = ToonState(laff=137, max_laff=137,
                     track_exp={t: 7 for t in Track},
                     gag_counts=dict(gags or {}), fires=fires)
    return BattleState(cogs=[cog], toons=[toon])


class VersionTwoTest(unittest.TestCase):

    def test_the_wiki_total_is_twice_the_normal_table(self):
        published = {1: 12, 2: 24, 3: 40, 4: 60, 5: 84, 6: 112, 7: 144,
                     8: 180, 9: 220, 10: 264, 11: 312, 12: 392}
        for level, total in published.items():
            self.assertEqual(data.cog_max_hp(level) * 2, total,
                             f"level {level}")

    def test_breaking_the_suit_does_not_kill(self):
        cog = v2(8)                      # 90 suit + 90 skelecog
        cog.take_damage(90)
        self.assertFalse(cog.status.is_dead)
        self.assertFalse(cog.status.suited)
        self.assertEqual(cog.hp, 90, "the Skelecog steps out at full health")

    def test_overkill_on_the_suit_is_discarded(self):
        """The 3.0.0 rule. A Toontanic into a 90 hp suit wastes 90."""
        cog = v2(8)
        cog.take_damage(180)
        self.assertFalse(cog.status.is_dead)
        self.assertEqual(cog.hp, 90,
                         "carryover was removed in 3.0.0 -- the Skelecog "
                         "must be untouched")

    def test_both_layers_must_be_destroyed(self):
        cog = v2(8)
        cog.take_damage(90)
        cog.take_damage(90)
        self.assertTrue(cog.status.is_dead)

    def test_a_normal_cog_is_unaffected(self):
        cog = CogState(cog_type="Flunky", department="bossbot",
                       level=8, hp=90, max_hp=90)
        cog.take_damage(90)
        self.assertTrue(cog.status.is_dead)

    def test_damage_reported_is_what_was_thrown(self):
        """Scorers read this as damage dealt; overkill is their problem,
        not the simulator's."""
        cog = v2(8)
        self.assertEqual(cog.take_damage(180), 180)

    def test_a_fire_removes_both_layers_at_once(self):
        """[CONFIRMED] wiki: a pink slip eliminates the suit AND the
        Skelecog form."""
        cog = v2(12)
        st = _state(cog, fires=1)
        simulator.apply_toon_action(
            st, Action(track=None, target_index=0, fire=True), hit=True)
        self.assertTrue(cog.status.is_dead)
        self.assertFalse(cog.status.suited)

    def test_the_suit_survives_a_copy(self):
        """It did not, and that quietly un-2.0'd every Version 2.0 after
        ONE round: the flag lived until the first `copy`, so a CEO's
        second battle -- which is entirely 2.0s -- was fought against
        ordinary cogs with half the health. The tell was a trace marker
        that appeared on round one of each floor and never again."""
        cog = v2(12)
        self.assertTrue(cog.copy().status.suited)
        st = _state(cog)
        self.assertTrue(st.clone().cogs[0].status.suited)

    def test_a_suited_cog_keys_differently(self):
        """A suited cog at 90 hp has 180 left to give; a bare one has 90.
        Collapsing them would let the memo answer a v2.0 with a
        Skelecog's value -- the `free_passes` lesson again."""
        from solver import outcomes
        bare = _state(CogState(cog_type="Flunky", department="bossbot",
                               level=8, hp=90, max_hp=90))
        suited = _state(v2(8))
        self.assertNotEqual(outcomes.state_key(bare),
                            outcomes.state_key(suited))

    def test_a_hit_too_small_leaves_the_suit_on(self):
        """Drop 5 deals 60-70 into a 90 hp suit, so the suit holds. The
        first version of this test asserted the suit came off, which was
        simply wrong about the numbers."""
        cog = v2(8)
        st = _state(cog, gags={(Track.DROP, 5): 2})
        simulator.apply_toon_action(st, Action(Track.DROP, 5, 0), hit=True)
        self.assertFalse(cog.status.is_dead)
        self.assertTrue(cog.status.suited)
        self.assertLess(cog.hp, 90)

    def test_two_rounds_take_the_suit_then_the_skelecog(self):
        cog = v2(8)
        st = _state(cog, gags={(Track.DROP, 6): 4})
        simulator.apply_toon_action(st, Action(Track.DROP, 6, 0), hit=True)
        self.assertFalse(cog.status.suited, "170 breaks a 90 hp suit")
        self.assertEqual(cog.hp, 90, "and the overkill is discarded")
        simulator.apply_toon_action(st, Action(Track.DROP, 6, 0), hit=True)
        self.assertTrue(cog.status.is_dead)


if __name__ == "__main__":
    unittest.main()
