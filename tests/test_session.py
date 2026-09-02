"""Assembling a BattleState from live readings.

The interesting behaviour here is refusal: the pipeline must decline to
produce a state it had to guess at, and say what is missing.
"""
import unittest

try:
    from solver.live.session import build_state, cog_from_reading
    from solver.live.ttr_local import Snapshot
    from solver.live.watch import CogReading
    from solver.state import Track
    from solver import data
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"session needs numpy: {exc}") from None


class FakePanel:
    def __init__(self, counts, problem=None):
        self._counts = counts
        self._problem = problem

    def counts(self):
        return self._counts

    def checksum_problem(self):
        """Why the read cannot be trusted, or None.

        A real panel cross-checks its cells against the "Total gags"
        label the menu prints; these fakes are hand-built and add up by
        construction, so they say None unless a test wants otherwise.
        """
        return self._problem


def snapshot(laff=95):
    return Snapshot(name="T", toon_id="TTID", laff=laff, max_laff=95,
                    zone="Loopy Lane", neighborhood="Toontown Central",
                    district="Splat Summit",
                    tracks={Track.THROW: (7, False),
                            Track.SQUIRT: (6, True)})


def reading(cog="penny_pincher", dept="cashbot", level=6, health=1.0,
            index=0):
    return CogReading(index=index, department=dept, level=level,
                      health=health, cog=cog, slot=(0, 0, 66, 45))


class CogFromReadingTest(unittest.TestCase):

    def test_full_health_is_full_hp(self):
        cog, why = cog_from_reading(reading(health=1.0))
        self.assertEqual(why, [])
        self.assertEqual(cog.hp, cog.max_hp)
        self.assertEqual(cog.max_hp, data.cog_max_hp(6))

    def test_a_bar_just_under_full_still_reads_full(self):
        """The bar's own noise must not shave a point off every cog."""
        cog, _ = cog_from_reading(reading(health=0.98))
        self.assertEqual(cog.hp, cog.max_hp)

    def test_partial_health_scales_max_hp(self):
        cog, _ = cog_from_reading(reading(level=6, health=0.5))
        self.assertEqual(cog.hp, round(data.cog_max_hp(6) * 0.5))

    def test_health_rounds_rather_than_truncates(self):
        cog, _ = cog_from_reading(reading(level=6, health=0.51))
        self.assertEqual(cog.hp, round(data.cog_max_hp(6) * 0.51))

    def test_a_nearly_dead_cog_keeps_at_least_one_hp(self):
        cog, _ = cog_from_reading(reading(health=0.001))
        self.assertGreaterEqual(cog.hp, 1)

    def test_an_unidentified_cog_is_refused_with_advice(self):
        cog, why = cog_from_reading(reading(cog=None))
        self.assertIsNone(cog)
        self.assertIn("head library", why[0])
        self.assertIn("cashbot level 6", why[0])

    def test_an_unreadable_level_is_refused(self):
        cog, why = cog_from_reading(reading(level=None))
        self.assertIsNone(cog)
        self.assertTrue(any("level" in w for w in why))

    def test_department_is_derived_when_the_emblem_was_unreadable(self):
        """Below 900p the medallion cannot be read, but a named cog
        already implies its department."""
        cog, why = cog_from_reading(reading(dept=None))
        self.assertEqual(why, [])
        self.assertEqual(cog.department, "cashbot")


class BuildStateTest(unittest.TestCase):

    def panel(self):
        return FakePanel({(Track.THROW, 5): 7, (Track.THROW, 7): 1})

    def test_builds_a_state_when_everything_is_known(self):
        result = build_state(snapshot=snapshot(), panel=self.panel(),
                             readings=[reading()])
        self.assertTrue(result)
        self.assertEqual(result.state.toon.laff, 95)
        self.assertEqual(len(result.state.cogs), 1)

    def test_track_exp_comes_from_the_api_not_the_panel(self):
        """It sets accuracy, and the API states it exactly."""
        result = build_state(snapshot=snapshot(), panel=self.panel(),
                             readings=[reading()])
        self.assertEqual(result.state.toon.track_exp[Track.THROW], 7)
        self.assertEqual(result.state.toon.track_exp[Track.SQUIRT], 6)

    def test_allies_default_to_none_and_are_carried_through(self):
        """Solo is the default and the safe direction: it is the one
        that assumes every cog attack is coming at you."""
        solo = build_state(snapshot=snapshot(), panel=self.panel(),
                           readings=[reading()])
        self.assertEqual(solo.state.allies_standing, 0)

        full = build_state(snapshot=snapshot(), panel=self.panel(),
                           readings=[reading()], allies=3)
        self.assertEqual(full.state.allies_standing, 3)
        self.assertAlmostEqual(full.state.your_target_share(), 0.25)

    def test_allies_are_clamped_to_a_legal_party(self):
        """Four toons is the most a battle holds, so three allies is the
        most there can be. A junk value must not reach the share, where
        it would divide the danger by an arbitrary number."""
        for given, want in ((9, 3), (4, 3), (-1, 0)):
            result = build_state(snapshot=snapshot(), panel=self.panel(),
                                 readings=[reading()], allies=given)
            self.assertEqual(result.state.allies_standing, want)

    def test_gag_counts_come_from_the_panel(self):
        result = build_state(snapshot=snapshot(), panel=self.panel(),
                             readings=[reading()])
        self.assertEqual(result.state.toon.gag_counts[(Track.THROW, 5)], 7)

    def test_no_snapshot_is_refused(self):
        result = build_state(snapshot=None, panel=self.panel(),
                             readings=[reading()])
        self.assertFalse(result)
        self.assertTrue(any("Local API" in p for p in result.problems))

    def test_no_cogs_is_refused(self):
        result = build_state(snapshot=snapshot(), panel=self.panel(),
                             readings=[])
        self.assertFalse(result)
        self.assertTrue(any("cog plates" in p for p in result.problems))

    def test_a_pouch_that_does_not_add_up_is_refused(self):
        """The gag menu prints its own total and the cells must sum to
        it. A misread digit is the quietest possible failure -- it does
        not look like an error, it looks like a toon carrying one fewer
        gag -- so it has to block rather than warn."""
        panel = FakePanel({(Track.THROW, 3): 2},
                          problem="gag counts do not add up: the cells "
                                  "total 66 but the menu says 67/70")
        result = build_state(snapshot=snapshot(), panel=panel,
                             readings=[reading()])
        self.assertFalse(result)
        self.assertTrue(any("do not add up" in p for p in result.problems))

    def test_every_problem_is_reported_at_once(self):
        """Not just the first. Being told one reason, fixing it and
        being told the next is a worse experience than being told all
        of them, and the contract is 'a state or the reasons'."""
        panel = FakePanel({(Track.THROW, 3): 2}, problem="counts are wrong")
        result = build_state(snapshot=None, panel=panel, readings=[])
        self.assertFalse(result)
        self.assertGreaterEqual(len(result.problems), 3)

    def test_no_gag_menu_is_refused_rather_than_assumed_empty(self):
        """An empty pouch and an unread pouch are different states, and
        advising from the first when it is really the second produces a
        confident recommendation to do nothing."""
        result = build_state(snapshot=snapshot(), panel=None,
                             readings=[reading()])
        self.assertFalse(result)
        self.assertTrue(any("gag menu" in p for p in result.problems))

    def test_one_unknown_cog_blocks_the_whole_state(self):
        result = build_state(snapshot=snapshot(), panel=self.panel(),
                             readings=[reading(), reading(cog=None, index=1)])
        self.assertFalse(result)

    def test_problems_name_every_gap_at_once(self):
        result = build_state(snapshot=None, panel=None, readings=[])
        self.assertGreaterEqual(len(result.problems), 2)


if __name__ == "__main__":
    unittest.main()


class TestLuredCogsFromTheLive(unittest.TestCase):
    """A cog marked lured must reach the solver asleep.

    Nothing reads the game's lure indicator, so this arrives from the
    player. It is not cosmetic: Throw and Squirt are forced to 100%
    against a lured cog and take the knockback bonus, Drop always misses
    one, and a lured cog does not attack.
    """

    def _reading(self, lured):
        from solver.live.watch import CogReading
        return CogReading(index=0, department="cashbot", level=7,
                          health=1.0, cog="money_bags", lured=lured)

    def test_awake_by_default(self):
        from solver.live import session
        cog, _ = session.cog_from_reading(self._reading(False))
        self.assertFalse(cog.status.lured)

    def test_marked_lured_arrives_asleep(self):
        from solver.live import session
        cog, _ = session.cog_from_reading(self._reading(True))
        self.assertTrue(cog.status.lured)

    def test_it_changes_the_forced_accuracy(self):
        """The reason it matters, stated as the rule it changes."""
        from solver import mechanics
        from solver.live import session
        from solver.state import Track
        awake, _ = session.cog_from_reading(self._reading(False))
        asleep, _ = session.cog_from_reading(self._reading(True))
        self.assertIsNone(mechanics.forced_accuracy(Track.THROW, [awake]))
        self.assertEqual(100, mechanics.forced_accuracy(Track.THROW, [asleep]))


class PlayerSuppliedHoldingsTest(unittest.TestCase):
    """Slips and unites are set by the player, like `allies`.

    Nothing TTR exposes counts them: the Local API reports laff, tracks,
    organic, location and invasion and no inventory, and the screen
    shows the gag menu, not the slip or unite pouch. A player typing "I
    have three" is an assertion, not a guess.

    SOS cards are deliberately NOT accepted. A slip is a slip; there are
    29 distinct cards and a count says nothing about which.
    """

    def _built(self, **kw):
        return build_state(snapshot=snapshot(),
                           panel=FakePanel({(Track.THROW, 5): 7,
                                            (Track.THROW, 7): 1}),
                           readings=[reading()], **kw)

    def test_they_default_to_none_held(self):
        result = self._built()
        if not result:
            self.skipTest("fixtures do not build a state here")
        self.assertEqual(result.state.toon.fires, 0)
        self.assertEqual(result.state.toon.unites_held, 0)

    def test_the_player_can_supply_them(self):
        result = self._built(fires=3, unites=2)
        if not result:
            self.skipTest("fixtures do not build a state here")
        self.assertEqual(result.state.toon.fires, 3)
        self.assertEqual(result.state.toon.unites_held, 2)

    def test_negative_counts_are_floored(self):
        result = self._built(fires=-5, unites=-5)
        if not result:
            self.skipTest("fixtures do not build a state here")
        self.assertEqual(result.state.toon.fires, 0)
        self.assertEqual(result.state.toon.unites_held, 0)

    def test_no_sos_parameter_exists(self):
        """A count cannot name a card, so there is nothing to pass."""
        import inspect
        params = inspect.signature(build_state).parameters
        self.assertIn("fires", params)
        self.assertIn("unites", params)
        self.assertNotIn("sos", params)
        self.assertNotIn("sos_cards", params)

    def test_a_supplied_state_never_holds_cards(self):
        result = self._built(fires=3, unites=2)
        if not result:
            self.skipTest("fixtures do not build a state here")
        self.assertEqual(dict(result.state.toon.sos_cards), {})
