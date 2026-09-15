"""The observed-action reader, and the cases where it must say nothing.

Every test that asserts `None` here is asserting a REFUSAL. These rows
are training data: a gap can be counted and explained, a wrong row is
invisible and nothing downstream will ever re-derive it.
"""
import os
import tempfile
import unittest

from solver.live import feedback
from solver.state import Action, CogState, Track


def _cog(hp, max_hp=100):
    return CogState(cog_type="cold_caller", department="sellbot",
                    level=4, hp=hp, max_hp=max_hp)


class SpentGagTest(unittest.TestCase):

    def test_one_gag_thrown_reads_exactly(self):
        before = {(Track.THROW, 4): 3, (Track.LURE, 2): 5}
        after = {(Track.THROW, 4): 2, (Track.LURE, 2): 5}
        key, why = feedback.spent_gag(before, after)
        self.assertEqual((Track.THROW, 4), key)
        self.assertIsNone(why)

    def test_the_last_one_of_a_gag_is_a_key_disappearing(self):
        """`parse_inventory` omits empty cells, so spending your last
        Wedding Cake removes the key rather than setting it to 0."""
        key, why = feedback.spent_gag({(Track.THROW, 7): 1}, {})
        self.assertEqual((Track.THROW, 7), key)
        self.assertIsNone(why)

    def test_a_restock_makes_the_whole_round_unreadable(self):
        """A Gag-Up refills several cells at once and can refill the very
        gag that was spent, so no delta that round means anything."""
        before = {(Track.THROW, 4): 3, (Track.LURE, 2): 1}
        after = {(Track.THROW, 4): 2, (Track.LURE, 2): 9}
        key, why = feedback.spent_gag(before, after)
        self.assertIsNone(key)
        self.assertEqual(feedback.UNREADABLE_RESTOCK, why)

    def test_two_gags_down_is_refused(self):
        before = {(Track.THROW, 4): 3, (Track.SQUIRT, 3): 3}
        after = {(Track.THROW, 4): 2, (Track.SQUIRT, 3): 2}
        key, why = feedback.spent_gag(before, after)
        self.assertIsNone(key)
        self.assertEqual(feedback.UNREADABLE_MULTIPLE, why)

    def test_a_drop_of_more_than_one_is_refused(self):
        key, why = feedback.spent_gag({(Track.THROW, 4): 5},
                                      {(Track.THROW, 4): 3})
        self.assertIsNone(key)
        self.assertEqual(feedback.UNREADABLE_JUMP, why)

    def test_an_unchanged_pouch_reports_nothing_spent(self):
        counts = {(Track.THROW, 4): 3}
        key, why = feedback.spent_gag(counts, dict(counts))
        self.assertIsNone(key)
        self.assertEqual(feedback.UNREADABLE_NOTHING, why)

    def test_a_missing_side_is_refused_not_assumed(self):
        for before, after in ((None, {}), ({}, None), (None, None)):
            key, why = feedback.spent_gag(before, after)
            self.assertIsNone(key)
            self.assertEqual(feedback.UNREADABLE_NO_BEFORE, why)

    def test_it_never_returns_both_or_neither(self):
        cases = [({(Track.THROW, 4): 2}, {(Track.THROW, 4): 1}),
                 ({}, {}), (None, {}),
                 ({(Track.THROW, 4): 1}, {(Track.THROW, 4): 4})]
        for before, after in cases:
            key, why = feedback.spent_gag(before, after)
            self.assertEqual(1, (key is not None) + (why is not None),
                             (before, after))


class SpentCountTest(unittest.TestCase):

    def test_one_card_called(self):
        name, n = feedback.spent_count({"Flippy": 2}, {"Flippy": 1})
        self.assertEqual(("Flippy", 1), (name, n))

    def test_two_moving_is_refused(self):
        name, n = feedback.spent_count({"Flippy": 2, "Lil Oldman": 1},
                                       {"Flippy": 1})
        self.assertIsNone(name)

    def test_a_gain_is_refused(self):
        name, n = feedback.spent_count({"Flippy": 1}, {"Flippy": 3})
        self.assertIsNone(name)


class InferTargetTest(unittest.TestCase):

    def test_one_cog_losing_hp_pins_the_target(self):
        before = [_cog(100), _cog(100), _cog(100)]
        after = [_cog(100), _cog(73), _cog(100)]
        self.assertEqual(1, feedback.infer_target(before, after, group=False))

    def test_a_group_gag_has_no_single_target_by_definition(self):
        before = [_cog(100), _cog(100)]
        after = [_cog(80), _cog(80)]
        self.assertIsNone(feedback.infer_target(before, after, group=True))

    def test_two_cogs_moving_is_refused(self):
        """A cog dying to a trap it was lured onto moves hp without being
        the target, which is why 'the only one that changed' is required
        rather than 'the one that changed most'."""
        before = [_cog(100), _cog(100)]
        after = [_cog(60), _cog(80)]
        self.assertIsNone(feedback.infer_target(before, after, group=False))

    def test_nothing_moving_is_refused(self):
        before = [_cog(100), _cog(100)]
        self.assertIsNone(
            feedback.infer_target(before, list(before), group=False))


class DecisionTest(unittest.TestCase):

    def _dec(self, **kw):
        base = dict(source="realms",
                    rl=Action(track=Track.LURE, level=4),
                    search=Action(track=Track.THROW, level=4, target_index=2),
                    observed=Action(track=Track.THROW, level=4))
        base.update(kw)
        return feedback.Decision(**base)

    def test_it_reports_which_engines_were_departed_from(self):
        self.assertEqual({"rl": True, "search": False}, self._dec().beats())

    def test_an_unknown_comparison_is_none_not_false(self):
        """A missing comparison and a tie are different facts."""
        self.assertEqual({"rl": None, "search": None},
                         self._dec(observed=None).beats())
        self.assertIsNone(self._dec(rl=None).beats()["rl"])

    def test_the_target_is_ignored_when_either_side_lacks_one(self):
        """`observed` usually has no target, and counting that as a
        disagreement would label every readable round a disagreement."""
        dec = self._dec(observed=Action(track=Track.THROW, level=4),
                        search=Action(track=Track.THROW, level=4,
                                      target_index=3))
        self.assertFalse(dec.beats()["search"])

    def test_a_known_target_mismatch_is_a_disagreement(self):
        dec = self._dec(observed=Action(track=Track.THROW, level=4,
                                        target_index=0),
                        search=Action(track=Track.THROW, level=4,
                                      target_index=3))
        self.assertTrue(dec.beats()["search"])

    def test_agreement_with_both_is_not_informative(self):
        dec = self._dec(rl=Action(track=Track.THROW, level=4))
        self.assertFalse(dec.informative())
        self.assertTrue(self._dec().informative())


class FeedbackLogTest(unittest.TestCase):

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_a_source_is_required(self):
        """`source` is the quarantine flag -- Realms data can never train
        a TTR policy -- so a record cannot be written without one."""
        with self.assertRaises(ValueError):
            feedback.FeedbackLog(self.path, source="")

    def test_the_source_is_stamped_at_write_time(self):
        log = feedback.FeedbackLog(self.path, source="realms")
        dec = feedback.Decision(source="ttr",
                                observed=Action(track=Track.THROW, level=4))
        log.append(dec)
        back = feedback.read(self.path)
        self.assertEqual(["realms"], [r.source for r in back])

    def test_a_round_with_no_label_is_not_kept(self):
        log = feedback.FeedbackLog(self.path, source="realms")
        self.assertFalse(log.append(feedback.Decision(source="realms")))
        self.assertEqual(0, log.written)
        self.assertEqual(1, log.skipped)
        self.assertEqual([], feedback.read(self.path))

    def test_a_rejection_alone_is_worth_keeping(self):
        """Reconsider is a player going to the trouble of saying 'not
        this'. It was discarded when the board changed."""
        log = feedback.FeedbackLog(self.path, source="realms")
        self.assertTrue(log.append(
            feedback.Decision(source="realms", rejected=(("throw", False),))))
        self.assertEqual(1, len(feedback.read(self.path)))

    def test_records_round_trip_with_the_state_whole(self):
        from solver.state import BattleState, ToonState

        state = BattleState(toons=[ToonState(laff=90, max_laff=137)],
                            cogs=[_cog(100)])
        log = feedback.FeedbackLog(self.path, source="realms", session="s1")
        log.append(feedback.Decision(
            source="realms", state=state, round_num=3,
            observed=Action(track=Track.THROW, level=4)))
        back = feedback.read(self.path)[0]
        self.assertEqual(3, back.round_num)
        self.assertEqual("s1", back.session)
        self.assertEqual(90, back.state.toons[0].laff)
        self.assertEqual(Track.THROW, back.observed.track)

    def test_reading_a_log_that_is_not_there_is_empty_not_an_error(self):
        self.assertEqual([], feedback.read(self.path))

    def test_summarise_counts_what_is_worth_fitting_on(self):
        log = feedback.FeedbackLog(self.path, source="realms")
        rl = Action(track=Track.LURE, level=4)
        mine = Action(track=Track.THROW, level=4)
        log.append(feedback.Decision(source="realms", rl=rl, search=mine,
                                     observed=mine))
        log.append(feedback.Decision(source="realms", rl=mine, search=mine,
                                     observed=mine))
        log.append(feedback.Decision(source="realms",
                                     unreadable=feedback.UNREADABLE_RESTOCK,
                                     rejected=(("lure", True),)))
        got = feedback.summarise(feedback.read(self.path))
        self.assertEqual(3, got["records"])
        self.assertEqual(["realms"], got["sources"])
        self.assertEqual(1, got["differed"]["rl"])
        self.assertEqual(2, got["agreed"]["search"])
        self.assertEqual(1, got["rejections"])
        self.assertEqual({feedback.UNREADABLE_RESTOCK: 1}, got["unreadable"])


class NoHeavyImportsTest(unittest.TestCase):
    """`solver.live.__init__` must stay importable without numpy or
    panda3d, so this module has to be standard library only."""

    def test_it_is_stdlib_only(self):
        import inspect

        src = inspect.getsource(feedback)
        for banned in ("import numpy", "import panda3d", "from ..rl"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()


class RealmsPanelCapturesTheRoundTest(unittest.TestCase):
    """The panel's own hook, exercised without a cluster.

    The value of this path is that it asks the player nothing: the pouch
    is read every poll anyway, so the move is observed. These tests pin
    that it fires at the round boundary, that it captures the rejections
    BEFORE they are dropped, and that it stays silent rather than
    guessing when the round is unreadable.
    """

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _worker(self):
        from solver.live.realms_panel import RealmsWorker

        w = RealmsWorker.__new__(RealmsWorker)
        w.feedback_to = self.path
        w._feedback = None
        w._prev_state = None
        w._rl_action = Action(track=Track.LURE, level=4)
        w._search_action = Action(track=Track.THROW, level=4, target_index=1)
        w._rejected = set()
        w.objective_name = "balanced"
        w.model = type("M", (), {"engine": "rl"})()
        return w

    def _state(self, counts, hps):
        from solver.state import BattleState, ToonState

        toon = ToonState(laff=90, max_laff=137)
        toon.gag_counts = dict(counts)
        return BattleState(toons=[toon], cogs=[_cog(h) for h in hps])

    def test_a_thrown_gag_is_read_off_the_pouch(self):
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        after = self._state({(Track.THROW, 4): 2}, [100, 73])
        w._record_feedback(after)

        rec, = feedback.read(self.path)
        self.assertEqual("realms", rec.source)
        self.assertEqual(Track.THROW, rec.observed.track)
        self.assertEqual(4, rec.observed.level)
        self.assertEqual(1, rec.observed.target_index, "target from hp delta")
        self.assertTrue(rec.beats()["rl"], "player lured? no -- they threw")
        self.assertFalse(rec.beats()["search"], "search proposed this")

    def test_the_outcome_is_metadata_beside_the_label_not_part_of_it(self):
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100, 73]))
        rec, = feedback.read(self.path)
        self.assertEqual([0, 27], rec.outcome["hp"])

    def test_an_unreadable_round_records_the_reason_not_a_guess(self):
        w = self._worker()
        w._rejected = {("throw", False)}
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100])
        # A restock: the pouch went UP, so no delta means anything.
        w._record_feedback(self._state({(Track.THROW, 4): 9}, [100]))
        rec, = feedback.read(self.path)
        self.assertIsNone(rec.observed)
        self.assertEqual(feedback.UNREADABLE_RESTOCK, rec.unreadable)
        self.assertTrue(rec.rejected, "the rejection is still the label")

    def test_nothing_is_written_without_the_flag(self):
        w = self._worker()
        w.feedback_to = None
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100]))
        self.assertEqual([], feedback.read(self.path))

    def test_recording_never_costs_the_advice(self):
        """Every failure here is swallowed: a panel that stops advising
        because its bookkeeping broke is strictly worse than one that
        logs nothing."""
        w = self._worker()
        w._prev_state = object()            # no .toon, no .cogs
        w._record_feedback(object())
        self.assertEqual([], feedback.read(self.path))

    def test_the_boundary_hook_runs_before_rejections_are_dropped(self):
        import inspect

        from solver.live import realms_panel

        src = inspect.getsource(realms_panel.RealmsWorker.tick)
        self.assertLess(src.index("_record_feedback"),
                        src.index("self._rejected.clear()"),
                        "rejections would be gone by the time it ran")


class CorrectionsTest(unittest.TestCase):
    """A correction is a NEW ROW, not an edit.

    The log is append-only and opened per write on purpose, so rewriting
    the tail would mean holding a handle and losing the end of every
    session the window is killed in.
    """

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _log_one(self, target=None):
        log = feedback.FeedbackLog(self.path, source="realms", session="s")
        log.append(feedback.Decision(
            source="realms",
            observed=Action(track=Track.THROW, level=4, target_index=target)))
        return log, feedback.read(self.path)[0].rid

    def test_rows_get_an_id(self):
        _log, rid = self._log_one()
        self.assertEqual("s:0", rid)

    def test_a_target_correction_is_folded_in_on_read(self):
        log, rid = self._log_one(target=None)
        self.assertTrue(log.correct(rid, target_index=2))
        rec, = feedback.read(self.path)
        self.assertEqual(2, rec.observed.target_index)

    def test_a_discard_removes_the_row(self):
        log, rid = self._log_one()
        self.assertTrue(log.correct(rid, discard=True))
        self.assertEqual([], feedback.read(self.path))

    def test_the_original_survives_in_the_raw_stream(self):
        """How often the reader is overruled is itself worth knowing."""
        log, rid = self._log_one()
        log.correct(rid, discard=True)
        self.assertEqual(2, len(feedback.read(self.path, raw=True)))

    def test_a_correction_for_a_row_that_is_not_there_is_dropped(self):
        """A label with no position is not a label."""
        log, _rid = self._log_one()
        log.correct("s:999", target_index=1)
        rows = feedback.read(self.path)
        self.assertEqual(1, len(rows))
        self.assertFalse(any(r.corrects for r in rows))

    def test_correcting_nothing_is_refused(self):
        log, _ = self._log_one()
        self.assertFalse(log.correct(""))

    def test_summarise_sees_the_corrected_view(self):
        log, rid = self._log_one()
        log.correct(rid, discard=True)
        self.assertEqual(0, feedback.summarise(feedback.read(self.path))["records"])


class ReceiptStripTest(unittest.TestCase):
    """The strip under the advice: what was logged, or why nothing was."""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _worker(self):
        from solver.live.overlay import Model
        from solver.live.realms_panel import RealmsWorker

        w = RealmsWorker.__new__(RealmsWorker)
        w.feedback_to = self.path
        w._feedback = None
        w._prev_state = None
        w._last_rid = ""
        w._rl_action = Action(track=Track.LURE, level=4)
        w._search_action = Action(track=Track.THROW, level=4, target_index=1)
        w._rejected = set()
        w.objective_name = "balanced"
        w.model = Model()
        w._post = lambda: None
        return w

    def _state(self, counts, hps):
        from solver.state import BattleState, ToonState

        toon = ToonState(laff=90, max_laff=137)
        toon.gag_counts = dict(counts)
        return BattleState(toons=[toon], cogs=[_cog(h) for h in hps])

    def test_a_logged_round_names_the_move_and_the_engine_it_departs_from(self):
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100, 73]))

        self.assertEqual("Whole Fruit Pie", w.model.feedback_move)
        self.assertEqual("rl", w.model.feedback_against)
        self.assertEqual("", w.model.feedback_problem)
        self.assertTrue(w.model.feedback_fixable)
        self.assertTrue(w.model.feedback_showing)

    def test_an_unreadable_round_shows_the_reason_instead_of_a_move(self):
        """The case worth surfacing: a gap seen now costs a glance, and
        one found at fit time costs the run."""
        w = self._worker()
        w._rejected = {("throw", False)}
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100])
        w._record_feedback(self._state({(Track.THROW, 4): 9}, [100]))

        self.assertEqual("", w.model.feedback_move)
        self.assertEqual(feedback.UNREADABLE_RESTOCK, w.model.feedback_problem)
        self.assertTrue(w.model.feedback_showing)

    def test_a_target_is_only_asked_for_when_it_is_missing(self):
        w = self._worker()
        # One cog moved: the target is pinned, so nothing to ask.
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100, 73]))
        self.assertFalse(w.model.feedback_needs_target)

        # Two moved: unknowable from the board, so worth one question.
        w2 = self._worker()
        w2._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w2._record_feedback(self._state({(Track.THROW, 4): 2}, [60, 73]))
        self.assertTrue(w2.model.feedback_needs_target)

    def test_a_single_cog_board_never_asks(self):
        w = self._worker()
        w._prev_state = self._state({(Track.SOUND, 3): 2}, [100])
        w._record_feedback(self._state({(Track.SOUND, 3): 1}, [89]))
        self.assertFalse(w.model.feedback_needs_target)

    def test_naming_the_cog_corrects_the_row(self):
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [60, 73]))
        self.assertIsNone(feedback.read(self.path)[0].observed.target_index)

        w.correct_feedback(target_index=1)
        self.assertEqual(1, feedback.read(self.path)[0].observed.target_index)
        self.assertFalse(w.model.feedback_fixable, "one row, one correction")

    def test_discarding_removes_the_row_and_says_so(self):
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100, 73]))
        w.correct_feedback(discard=True)

        self.assertEqual([], feedback.read(self.path))
        self.assertEqual("", w.model.feedback_move)
        self.assertIn("wrong", w.model.feedback_problem)

    def test_correcting_twice_cannot_touch_an_older_row(self):
        """Only the most recent row is amendable: a correction names the
        row it fixes, and offering this on an older one would quietly
        edit whichever happened to be last."""
        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [60, 73]))
        w.correct_feedback(target_index=1)
        w.correct_feedback(target_index=0)       # second press, nothing left
        self.assertEqual(1, feedback.read(self.path)[0].observed.target_index)

    def test_the_receipt_expires_on_its_own(self):
        from solver.live.overlay import FEEDBACK_LINGER

        w = self._worker()
        w._prev_state = self._state({(Track.THROW, 4): 3}, [100, 100])
        w._record_feedback(self._state({(Track.THROW, 4): 2}, [100, 73]))
        self.assertTrue(w.model.feedback_showing)
        w.model.feedback_at -= FEEDBACK_LINGER + 1
        self.assertFalse(w.model.feedback_showing)

    def test_an_idle_model_shows_nothing(self):
        from solver.live.overlay import Model

        self.assertFalse(Model().feedback_showing)

    def test_the_fields_reach_the_page(self):
        import json

        from solver.live.overlay import Model
        from solver.live.panel import model_json

        got = json.loads(model_json(Model()))
        for key in ("feedback_move", "feedback_against", "feedback_problem",
                    "feedback_fixable", "feedback_needs_target",
                    "feedback_showing"):
            self.assertIn(key, got)

    def test_the_shared_page_never_learns_which_front_end_records(self):
        """`overlay`, `panel` and `worker` are the shared VIEW, and a
        test elsewhere already forbids the word. The feedback fields are
        source-neutral for the same reason."""
        import inspect

        from solver.live import overlay, panel

        for module in (overlay, panel):
            src = inspect.getsource(module).lower()
            self.assertNotIn("realms", src, module.__name__)


class SuggestMoveTest(unittest.TestCase):
    """The positive channel: the player naming the move they'd make.

    Kept separate from the observed one on purpose. Following the advice
    to see how it plays out records agreement, a misclick records a
    preference nobody holds, and an unreadable round records nothing --
    all cases where watching is a poor label and a statement is a good
    one.
    """

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _worker(self, counts=None, cogs=2):
        from solver.live.overlay import Model
        from solver.live.realms_panel import RealmsWorker
        from solver.state import BattleState, ToonState

        toon = ToonState(laff=90, max_laff=137)
        toon.gag_counts = dict(counts or {(Track.THROW, 4): 3,
                                          (Track.SOUND, 7): 1})
        w = RealmsWorker.__new__(RealmsWorker)
        w.feedback_to = self.path
        w._feedback = None
        w._last_rid = ""
        w._rl_action = Action(track=Track.LURE, level=4)
        w._search_action = Action(track=Track.THROW, level=4, target_index=1)
        w._rejected = set()
        w.objective_name = "balanced"
        w.model = Model()
        w._post = lambda: None
        w._prev_state = BattleState(toons=[toon],
                                    cogs=[_cog(100) for _ in range(cogs)])
        return w

    def test_a_stated_move_is_recorded_against_the_board_on_screen(self):
        w = self._worker()
        w.suggest_move(track="throw", level=4, target_index=1)
        rec, = feedback.read(self.path)
        self.assertEqual(Track.THROW, rec.preferred.track)
        self.assertEqual(1, rec.preferred.target_index)
        self.assertIsNone(rec.observed, "nothing was watched here")
        self.assertTrue(rec.stated())

    def test_a_statement_outranks_an_inference(self):
        dec = feedback.Decision(
            source="realms",
            observed=Action(track=Track.LURE, level=4),
            preferred=Action(track=Track.THROW, level=4))
        self.assertEqual(Track.THROW, dec.player_move().track)

    def test_a_gag_the_toon_does_not_hold_is_refused(self):
        """A preference for a move that was never available is not a
        preference."""
        w = self._worker()
        w.suggest_move(track="drop", level=6, target_index=0)
        self.assertEqual([], feedback.read(self.path))
        self.assertIn("not carrying", w.model.feedback_problem)

    def test_a_group_gag_takes_no_target(self):
        w = self._worker()
        w.suggest_move(track="sound", level=7, target_index=1)
        rec, = feedback.read(self.path)
        self.assertIsNone(rec.preferred.target_index)

    def test_a_pass_is_sayable(self):
        w = self._worker()
        w.suggest_move(is_pass=True)
        rec, = feedback.read(self.path)
        self.assertTrue(rec.preferred.is_pass)

    def test_the_strip_says_it_was_stated_not_inferred(self):
        w = self._worker()
        w.suggest_move(track="throw", level=4, target_index=1)
        self.assertTrue(w.model.feedback_stated)
        self.assertTrue(w.model.feedback_showing)
        self.assertIn("Whole Fruit Pie", w.model.feedback_move)

    def test_an_observed_row_clears_the_stated_flag(self):
        from solver.state import BattleState, ToonState

        w = self._worker()
        w.suggest_move(track="throw", level=4, target_index=1)
        self.assertTrue(w.model.feedback_stated)

        toon = ToonState(laff=90, max_laff=137)
        toon.gag_counts = {(Track.THROW, 4): 2}
        after = BattleState(toons=[toon], cogs=[_cog(100), _cog(73)])
        w._record_feedback(after)
        self.assertFalse(w.model.feedback_stated)

    def test_nothing_is_written_without_the_flag(self):
        w = self._worker()
        w.feedback_to = None
        w.suggest_move(track="throw", level=4, target_index=0)
        self.assertEqual([], feedback.read(self.path))

    def test_summarise_separates_stated_from_inferred(self):
        w = self._worker()
        w.suggest_move(track="throw", level=4, target_index=1)
        log = feedback.FeedbackLog(self.path, source="realms")
        log.append(feedback.Decision(
            source="realms", observed=Action(track=Track.LURE, level=4)))
        got = feedback.summarise(feedback.read(self.path))
        self.assertEqual(1, got["stated"])
        self.assertEqual(1, got["inferred"])

    def test_said_and_did_counts_only_where_both_exist(self):
        log = feedback.FeedbackLog(self.path, source="realms")
        mine = Action(track=Track.THROW, level=4)
        other = Action(track=Track.LURE, level=4)
        log.append(feedback.Decision(source="realms", preferred=mine,
                                     observed=mine))
        log.append(feedback.Decision(source="realms", preferred=mine,
                                     observed=other))
        log.append(feedback.Decision(source="realms", preferred=mine))
        self.assertEqual((1, 2),
                         feedback.summarise(feedback.read(self.path))["said_and_did"])

    def test_the_pouch_reaches_the_page(self):
        import json

        from solver.live.panel import model_json
        from solver.live.realms_panel import _pouch_of

        w = self._worker()
        w.model.pouch = _pouch_of(w._prev_state)
        got = json.loads(model_json(w.model))
        names = {row["name"] for row in got["pouch"]}
        self.assertIn("Whole Fruit Pie", names)
        self.assertTrue(all(row["count"] > 0 for row in got["pouch"]))

    def test_the_page_only_ever_sees_what_is_carried(self):
        from solver.live.realms_panel import _pouch_of
        from solver.state import BattleState, ToonState

        toon = ToonState(laff=90, max_laff=137)
        toon.gag_counts = {(Track.THROW, 4): 3, (Track.DROP, 1): 0}
        rows = _pouch_of(BattleState(toons=[toon], cogs=[]))
        self.assertEqual(["throw"], [r["track"] for r in rows])


class WatchModeTest(unittest.TestCase):
    """Whole fights, recorded as trajectories.

    A demonstration rather than a preference: the question is "what does
    this player do", not "which of these was better". The episode shape
    exists for one reason -- whether a VP run was won is carried
    entirely by its last transition, and per-round rows throw exactly
    that away.
    """

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".pkl")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _worker(self):
        from solver.live.overlay import Model
        from solver.live.realms_panel import RealmsWorker

        w = RealmsWorker.__new__(RealmsWorker)
        w.watch_to = self.path
        w._watch = None
        w._episode = None
        w._prev_state = None
        w.model = Model()
        return w

    def _state(self, counts, hps, laff=90, kind="vp"):
        from solver.state import BattleState, ToonState

        toon = ToonState(laff=laff, max_laff=137)
        toon.gag_counts = dict(counts)
        return BattleState(toons=[toon], cogs=[_cog(h) for h in hps],
                           kind=kind)

    def _play(self, w, boards):
        """Walk the worker through a fight, board by board."""
        for board in boards:
            if w._prev_state is not None:
                w._watch_step(board)
            w._prev_state = board

    def test_a_fight_becomes_one_episode(self):
        w = self._worker()
        self._play(w, [
            self._state({(Track.THROW, 4): 3}, [100, 100]),
            self._state({(Track.THROW, 4): 2}, [100, 73]),
            self._state({(Track.THROW, 4): 1}, [100, 40]),
        ])
        w._prev_state = self._state({(Track.THROW, 4): 1}, [100, 0])
        w._close_episode()

        ep, = feedback.read_episodes(self.path)
        self.assertEqual("realms", ep.source)
        self.assertEqual("vp", ep.kind)
        self.assertEqual(3, ep.rounds(), "two played rounds plus the last")
        self.assertEqual(Track.THROW, ep.steps[0].action.track)

    def test_the_terminal_round_is_kept(self):
        """The round the fight ended on used to be dropped entirely --
        the recorder keys off the board CHANGING, and at the end it
        stops changing."""
        w = self._worker()
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                       self._state({(Track.THROW, 4): 2}, [40])])
        w._close_episode()

        ep, = feedback.read_episodes(self.path)
        self.assertEqual("the fight ended on this round",
                         ep.steps[-1].unreadable)
        self.assertIsNotNone(ep.steps[-1].state)

    def test_a_cleared_board_is_a_win(self):
        w = self._worker()
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                       self._state({(Track.THROW, 4): 2}, [10])])
        w._prev_state = self._state({(Track.THROW, 4): 2}, [])
        w._close_episode()
        self.assertEqual("won", feedback.read_episodes(self.path)[0].outcome)

    def test_a_dead_toon_is_a_loss(self):
        w = self._worker()
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                       self._state({(Track.THROW, 4): 2}, [100])])
        w._prev_state = self._state({(Track.THROW, 4): 2}, [100], laff=0)
        w._close_episode()
        self.assertEqual("lost", feedback.read_episodes(self.path)[0].outcome)

    def test_a_fight_that_merely_vanished_is_not_called_a_loss(self):
        """A client that dropped or a player who walked away is not a
        position that was lost, and training on it as one teaches the
        wrong lesson about where it stopped."""
        w = self._worker()
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                       self._state({(Track.THROW, 4): 2}, [80])])
        w._close_episode()
        self.assertEqual("unknown",
                         feedback.read_episodes(self.path)[0].outcome)

    def test_an_empty_fight_is_not_written(self):
        w = self._worker()
        w._close_episode()
        self.assertEqual([], feedback.read_episodes(self.path))

    def test_each_fight_is_its_own_episode(self):
        w = self._worker()
        for _ in range(2):
            self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                           self._state({(Track.THROW, 4): 2}, [70])])
            w._close_episode()
            w._prev_state = None
        self.assertEqual(2, len(feedback.read_episodes(self.path)))

    def test_the_state_recorded_is_the_one_before_the_action(self):
        w = self._worker()
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100, 100]),
                       self._state({(Track.THROW, 4): 2}, [100, 73])])
        w._close_episode()
        ep, = feedback.read_episodes(self.path)
        first = ep.steps[0]
        self.assertEqual((100, 100), first.hp, "the board before the throw")
        self.assertEqual(3, first.state.toon.gag_counts[(Track.THROW, 4)])

    def test_an_unreadable_round_keeps_its_place_in_the_trajectory(self):
        """A gap in the middle of a fight must not silently become a
        shorter fight -- the rounds either side are still a sequence."""
        w = self._worker()
        self._play(w, [
            self._state({(Track.THROW, 4): 3}, [100]),
            self._state({(Track.THROW, 4): 9}, [100]),     # restocked
            self._state({(Track.THROW, 4): 8}, [70]),
        ])
        w._close_episode()
        ep, = feedback.read_episodes(self.path)
        self.assertEqual(3, ep.rounds())
        self.assertIsNone(ep.steps[0].action)
        self.assertEqual(feedback.UNREADABLE_RESTOCK, ep.steps[0].unreadable)
        self.assertIsNotNone(ep.steps[1].action)

    def test_nothing_is_written_without_the_flag(self):
        w = self._worker()
        w.watch_to = None
        self._play(w, [self._state({(Track.THROW, 4): 3}, [100]),
                       self._state({(Track.THROW, 4): 2}, [70])])
        w._close_episode()
        self.assertEqual([], feedback.read_episodes(self.path))

    def test_a_source_is_required(self):
        with self.assertRaises(ValueError):
            feedback.WatchLog(self.path, source="")

    def test_summarise_shows_collection_problems_as_numbers(self):
        w = self._worker()
        self._play(w, [
            self._state({(Track.THROW, 4): 3}, [100]),
            self._state({(Track.THROW, 4): 9}, [100]),     # restocked
            self._state({(Track.THROW, 4): 8}, [70]),
        ])
        w._close_episode()
        got = feedback.summarise_episodes(feedback.read_episodes(self.path))
        self.assertEqual(1, got["episodes"])
        self.assertEqual(3, got["rounds"])
        self.assertEqual(1, got["readable"], "two of three unreadable")
        self.assertEqual({"vp": 1}, got["kinds"])

    def test_watching_runs_no_engine(self):
        """A VP is forty-plus rounds at fifteen seconds of search each."""
        import inspect

        from solver.live import realms_panel

        src = inspect.getsource(realms_panel.RealmsWorker._search)
        self.assertIn('self.engine == "none"', src)
        self.assertLess(src.index('self.engine == "none"'),
                        src.index("threading.Thread"))


class LureLastsItsTableValueTest(unittest.TestCase):
    """How many cog phases a lure actually skips.

    Measured two ways that agree: this simulation, and a recorded solo
    VP where laff held across four consecutive gag-menu rounds after a
    Hypno-goggles and fell on the fifth.

    The IN-GAME TOOLTIP reads one higher -- 5 for Hypno-goggles, 4 for
    Big Magnet, 9 for Presentation -- because it counts the round the
    lure is thrown in, which is not a round the cog would have attacked
    in. Anyone checking this table against footage will see the tooltip
    first and conclude the table is one short. It is not, and this test
    is here so that conclusion fails loudly.
    """

    def _lured_board(self, level):
        from solver import data, mechanics
        from solver.state import BattleState, ToonState

        gag = data.gag(Track.LURE, level)
        rounds = mechanics.lure_duration_rounds(level)
        toon = ToonState(laff=140, max_laff=140)
        toon.track_exp = {Track.LURE: 7}
        cogs = []
        for lvl in (9, 3, 12, 2):
            hp = data.cog_max_hp(lvl)
            cogs.append(CogState(
                cog_type="mr_hollywood" if lvl >= 8 else "cold_caller",
                department="sellbot", level=lvl, hp=hp, max_hp=hp))
        state = BattleState(toons=[toon], cogs=cogs)
        for cog in state.cogs:
            cog.status.apply_lure(acc_before_bonus=gag.accuracy,
                                  rounds=rounds, level=level)
        return state, rounds

    def _phases_skipped(self, level):
        from solver import simulator

        state, rounds = self._lured_board(level)
        skipped = 0
        for _ in range(rounds + 4):
            if simulator._resolve_cog_phase(state) > 0:
                break
            skipped += 1
        return skipped, rounds

    def test_every_lure_level_skips_exactly_its_table_value(self):
        from solver import data

        for level in range(1, 8):
            data.gag(Track.LURE, level)
            skipped, rounds = self._phases_skipped(level)
            self.assertEqual(rounds, skipped,
                             "lure level %d skipped %d cog phases, table "
                             "says %d" % (level, skipped, rounds))

    def test_the_cogs_attack_on_the_very_next_phase(self):
        """Not one later -- which is what an off-by-one would look like."""
        from solver import simulator

        state, rounds = self._lured_board(6)
        for _ in range(rounds):
            self.assertEqual(0, simulator._resolve_cog_phase(state))
        self.assertGreater(simulator._resolve_cog_phase(state), 0)

    def test_the_table_still_matches_the_wiki(self):
        """[CONFIRMED] TTR wiki: 2/2/3/3/4/4/8 by level."""
        from solver import mechanics

        self.assertEqual([2, 2, 3, 3, 4, 4, 8],
                         [mechanics.lure_duration_rounds(l)
                          for l in range(1, 8)])
