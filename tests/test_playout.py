"""Judging by playing it out: the horizon, the drawn fight, the pick.

The rule these pin hardest is NO PEEKING: a playout may know how many
cogs are coming and from which level band, never which cogs.
"""
import random
import time
import unittest

from solver.live.boss import BossTracker

try:
    from solver.search import hybrid, playout
    HAVE = hybrid.available()
except Exception:                       # pragma: no cover
    HAVE = False


def _board(cogs=2, laff=140, seed=1):
    from solver import vp as vp_mod
    from solver.data.types import Track
    from solver.rl import env as env_mod
    from solver.state import BattleState

    rng = random.Random(seed)
    have = [t for t in Track if t is not Track.TOON_UP]
    toon = vp_mod.maxed_toon(rng, tracks=have, laff=laff)
    env = env_mod.BattleEnv(rng=random.Random(seed))
    return BattleState(toons=[toon],
                       cogs=[env._sellbot_cog(rng, 4) for _ in range(cogs)],
                       kind="vp")


class HorizonTest(unittest.TestCase):

    def test_the_cog_round_knows_what_is_still_walking_in(self):
        hz = BossTracker(kind="vp").horizon(on_field=4)
        self.assertEqual(16, hz.holdout)
        self.assertEqual((1, 12), hz.band)
        self.assertEqual(((20, (8, 12)),), hz.later)
        self.assertEqual("sellbot", hz.department)

    def test_the_count_moves_with_defeats(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(10)
        self.assertEqual(6, tracker.horizon(on_field=4).holdout)

    def test_the_skelecog_round_has_nothing_after_it(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(25)
        hz = tracker.horizon(on_field=4)
        self.assertEqual(11, hz.holdout)
        self.assertEqual((8, 12), hz.band)
        self.assertEqual((), hz.later)

    def test_the_ceo_horizon_stops_at_the_unknown_battle(self):
        hz = BossTracker(kind="ceo").horizon(on_field=4)
        self.assertEqual("bossbot", hz.department)
        self.assertEqual((), hz.later)

    def test_unconfirmed_fights_have_no_horizon(self):
        self.assertIsNone(BossTracker(kind="cfo").horizon())
        self.assertIsNone(BossTracker(kind="cj").horizon())
        self.assertIsNone(BossTracker().horizon())
        self.assertEqual(10, BossTracker(kind="vp", party_size=2).horizon().holdout)


@unittest.skipUnless(HAVE, "the policy needs numpy")
class BuildTest(unittest.TestCase):

    def test_without_a_horizon_the_battle_on_screen_is_all_there_is(self):
        env = playout.build_env(_board(), None, random.Random(0))
        self.assertEqual([], env.state.holdout)
        self.assertEqual(0, env.state.cogs_remaining)
        self.assertIsNone(env.plan)
        self.assertEqual("vp", env.state.kind)

    def test_unseen_cogs_are_drawn_in_the_right_numbers_and_band(self):
        hz = BossTracker(kind="vp").horizon(on_field=2)
        env = playout.build_env(_board(), hz, random.Random(0))
        self.assertEqual(18, len(env.state.holdout))
        self.assertEqual(20, env.state.cogs_remaining)
        for cog in env.state.holdout:
            self.assertTrue(1 <= cog.level <= 12)
            self.assertEqual("sellbot", cog.department)
        for cog in env.plan.floors[0]:
            self.assertTrue(8 <= cog.level <= 12)

    def test_a_real_holdout_on_the_board_is_never_used(self):
        """The simulator's own state carries the true cogs. A playout
        that read them would be advice no player could compute."""
        from solver.rl import env as env_mod

        board = _board()
        maker = env_mod.BattleEnv(rng=random.Random(9))
        board.holdout = [maker._sellbot_cog(random.Random(9), 12)
                         for _ in range(3)]
        env = playout.build_env(board, None, random.Random(0))
        self.assertEqual([], env.state.holdout)
        hz = BossTracker(kind="vp").horizon(on_field=2)
        drawn = [playout.build_env(board, hz, random.Random(s)).state.holdout
                 for s in (1, 2)]
        self.assertNotEqual([(c.cog_type, c.level) for c in drawn[0]],
                            [(c.cog_type, c.level) for c in drawn[1]])

    def test_the_live_board_is_not_touched(self):
        board = _board()
        before = [(c.hp, c.status.lured) for c in board.cogs]
        playout.rollout(board, [None], None, seed=3)
        self.assertEqual(before, [(c.hp, c.status.lured) for c in board.cogs])


@unittest.skipUnless(HAVE, "the policy needs numpy")
class PickTest(unittest.TestCase):

    def test_a_party_is_left_to_the_caller(self):
        board = _board()
        board.toons.append(board.toons[0].clone()
                           if hasattr(board.toons[0], "clone")
                           else board.clone().toons[0])
        self.assertIsNone(playout.pick(board, None, rollouts=2))

    def test_the_scorers_pick_is_tried_first(self):
        board = _board()
        res = playout.pick(board, None, seed=1, rollouts=2)
        self.assertEqual(playout._key(res.candidates[0]),
                         playout._key(playout.candidates(board)[0]))
        self.assertIn(playout._key(res.plan),
                      [playout._key(c) for c in res.candidates])

    def test_same_seed_same_answer(self):
        board = _board()
        a = playout.pick(board, None, seed=4, rollouts=2)
        b = playout.pick(board, None, seed=4, rollouts=2)
        self.assertEqual(playout._key(a.plan), playout._key(b.plan))
        self.assertEqual(a.means, b.means)

    def test_a_deadline_still_leaves_a_minimum(self):
        res = playout.pick(_board(), None, seed=1, rollouts=50,
                           deadline=time.monotonic())
        self.assertEqual(playout.MIN_ROLLOUTS, res.rollouts)

    def test_a_rollout_counts_only_what_could_be_defeated(self):
        board = _board(cogs=2)
        got = playout.rollout(board, [None], None, seed=2)
        self.assertTrue(0 <= got <= 2 + playout.LAFF_WEIGHT)


def _worker():
    import queue
    import threading

    from solver.live import overlay

    w = overlay.Worker.__new__(overlay.Worker)
    w.model = overlay.Model()
    w.outbox = queue.Queue(maxsize=8)
    w._lock = threading.Lock()
    w._rejected = set()
    w.allow_level_7 = True
    w.objective_name = "balanced"
    w.budget = 1.0
    w.toon_count = 1
    return w


class EngineSlotTest(unittest.TestCase):
    """The third answer rides the same rails as the other two."""

    def _describe(self, action, state):
        return "Pass", "", 0

    def test_a_delivered_playout_fills_its_own_row(self):
        from solver.state import Action

        w = _worker()
        move = Action(track=None)
        w._deliver_playout(_board(), move, "", self._describe)
        self.assertTrue(w.model.playout_ready)
        self.assertEqual("Pass", w.model.playout_gag)
        self.assertEqual("rl", w.model.preferred_engine)
        self.assertNotEqual("playout", w.model.engine)

    def test_choosing_it_shows_its_move_and_rejects_it(self):
        from solver.state import Action

        w = _worker()
        move = Action(track=None)
        w._deliver_playout(_board(), move, "", self._describe)
        w.prefer_engine("playout")
        self.assertEqual("playout", w.model.engine)
        self.assertEqual("Pass", w.model.gag)
        self.assertIs(move, w.displayed_action())

    def test_it_cannot_be_chosen_before_it_answers(self):
        w = _worker()
        w.prefer_engine("playout")
        self.assertEqual("playout", w.model.preferred_engine)
        self.assertNotEqual("playout", w.model.engine)

    def test_a_note_replaces_thinking_when_there_is_no_move(self):
        w = _worker()
        w._deliver_playout(_board(), None, "solo only", self._describe)
        self.assertTrue(w.model.playout_ready)
        self.assertEqual("", w.model.playout_gag)
        self.assertEqual("solo only", w.model.playout_note)

    def test_a_move_that_cannot_be_worded_is_still_shown(self):
        """Live, wording one playout move failed and the move was thrown
        away. It must survive in plain words."""
        import contextlib
        import io

        from solver.state import Action

        def broken(action, state):
            raise ValueError("no wording")

        w = _worker()
        with contextlib.redirect_stderr(io.StringIO()):
            w._deliver_playout(_board(), Action(track=None), "", broken)
        self.assertEqual("pass", w.model.playout_gag)
        self.assertEqual("", w.model.playout_note)

    def test_clearing_puts_the_row_back_to_thinking(self):
        from solver.state import Action

        w = _worker()
        w._deliver_playout(_board(), Action(track=None), "", self._describe)
        w._clear_engine(w.model, "playout")
        self.assertFalse(w.model.playout_ready)
        self.assertEqual("", w.model.playout_gag)

    def test_the_page_receives_it(self):
        import json

        from solver.live import panel

        page = json.loads(panel.model_json(_worker().model))
        for key in ("playout_gag", "playout_ready", "playout_note", "engines"):
            self.assertIn(key, page)


@unittest.skipUnless(HAVE, "the policy needs numpy")
class ChildTest(unittest.TestCase):

    def test_a_party_is_labelled_not_left_thinking(self):
        board = _board()
        board.toons.append(board.clone().toons[0])
        action, note = playout.pick_in_child(board, None, 1.0)
        self.assertIsNone(action)
        self.assertEqual("solo only", note)

    def test_solo_returns_a_move(self):
        action, note = playout.pick_in_child(_board(), None, 1.0)
        self.assertIsNotNone(action)
        self.assertEqual("", note)


class SwapRuleTest(unittest.TestCase):
    """While refining, the move on screen changes only for a real lead."""

    def test_a_steady_lead_replaces_the_move(self):
        from solver.search.playout import leads
        self.assertTrue(leads([5, 6, 5, 6], [3, 4, 3, 4]))

    def test_noise_does_not(self):
        from solver.search.playout import leads
        self.assertFalse(leads([9, 1, 9, 1], [1, 9, 1, 8]))

    def test_one_rollout_is_never_enough(self):
        from solver.search.playout import leads
        self.assertFalse(leads([10], [0]))

    def test_behind_is_never_a_lead(self):
        from solver.search.playout import leads
        self.assertFalse(leads([1, 1, 1], [2, 2, 2]))


@unittest.skipUnless(HAVE, "the policy needs numpy")
class ChunkTest(unittest.TestCase):

    def test_chunks_add_up_to_one_uninterrupted_pick(self):
        """Same cogs and dice for rollout k however it is chunked, so
        the panel's anytime totals are the batch result."""
        board = _board(cogs=3)
        first, _ = playout.chunk_in_child(board, None, None, True, 0, 2, wide=False)
        second, _ = playout.chunk_in_child(board, None, None, True, 2, 4, wide=False)
        whole = playout.pick(board, None, seed=0, rollouts=4)
        self.assertEqual([playout._key(p) for p, _v in first],
                         [playout._key(p) for p in whole.candidates])
        for (_p, a), (_q, b), mean in zip(first, second, whole.means):
            self.assertEqual(len(a), 2)
            self.assertAlmostEqual((sum(a) + sum(b)) / 4.0, mean)

    def test_only_the_named_candidates_are_rolled(self):
        board = _board(cogs=3)
        pairs, _ = playout.chunk_in_child(board, None, None, True, 0, 2)
        keep = [playout._key(pairs[0][0])]
        again, _ = playout.chunk_in_child(board, None, None, True, 2, 4, keep)
        self.assertEqual([playout._key(p) for p, _v in pairs],
                         [playout._key(p) for p, _v in again])
        self.assertEqual(2, len(again[0][1]))
        self.assertTrue(all(v == [] for _p, v in again[1:]))

    def test_the_wide_menu_spans_kinds_and_keeps_climbs_pick(self):
        board = _board(cogs=3)
        wide = playout.wide_candidates(board)
        self.assertEqual(playout._key(wide[0]),
                         playout._key(playout.candidates(board)[0]))
        self.assertLessEqual(len(wide), playout.WIDE_CAP)
        kinds = {playout._kind(p[0]) for p in wide}
        self.assertGreater(len(kinds), 1)

    def test_a_party_chunk_is_coordinated_by_default(self):
        """Teammates on the board: joint plans for everyone, your part
        first -- the teammates are assumed to play theirs."""
        self.assertEqual("coordinated", playout.GROUP_MODE)
        board = _party_board()
        pairs, note = playout.chunk_in_child(board, None, None, True, 0, 1)
        self.assertEqual("", note)
        for plan, values in pairs:
            self.assertEqual(len(board.toons), len(plan))
            self.assertEqual(1, len(values))

    def test_pickup_mode_offers_your_moves_alone(self):
        old = playout.GROUP_MODE
        try:
            playout.GROUP_MODE = "pickup"
            board = _party_board()
            pairs, note = playout.chunk_in_child(board, None, None, True, 0, 1)
            self.assertEqual("", note)
            for plan, _values in pairs:
                self.assertEqual(1, len(plan))
        finally:
            playout.GROUP_MODE = old

    def test_no_advice_once_you_are_out(self):
        board = _party_board()
        board.toons[0].laff = 0
        self.assertEqual((None, "you are out"),
                         playout.chunk_in_child(board, None, None, True, 0, 1))

    def test_the_schedule_overshoots_by_one_short_chunk_at_most(self):
        steps = [b - a for a, b in zip((0,) + playout.SCHEDULE, playout.SCHEDULE)]
        self.assertLessEqual(max(steps), 4)
        self.assertEqual(playout.MIN_ROLLOUTS, playout.SCHEDULE[0])


class _InlinePool:
    """Runs submitted work at once, so the split-and-merge can be checked
    without spawning processes."""

    class _Done:
        def __init__(self, value):
            self.value = value

        def result(self, timeout=None):
            return self.value

    def submit(self, fn, *args):
        return self._Done(fn(*args))


@unittest.skipUnless(HAVE, "the policy needs numpy")
class SplitTest(unittest.TestCase):

    def test_splitting_across_processes_changes_no_number(self):
        board = _board(cogs=3)
        w = _worker()
        w._playout_executor = _InlinePool()
        split, note = w._playout_chunk(board, None, frozenset(), 0, 2, None, 5.0)
        whole, _ = playout.chunk_in_child(board, None, frozenset(), True, 0, 2)
        self.assertEqual("", note)
        self.assertEqual([playout._key(p) for p, _v in whole],
                         [playout._key(p) for p, _v in split])
        self.assertEqual([v for _p, v in whole], [v for _p, v in split])

    def test_every_delivery_is_worded_against_a_board(self):
        """The refining loop reused a name for the candidate on screen,
        so every move after the first was worded against a key tuple and
        fell back to raw text -- inconsistent with the other two rows."""
        import time

        from solver.state import BattleState

        got = []

        def describe(action, st):
            got.append(type(st))
            return action.describe(), "", 0

        w = _worker()
        w._post = lambda: None
        w._playout_executor = _InlinePool()
        w._start_playout(_board(cogs=3), None, 2.0, lambda: True, describe)
        t0 = time.time()
        while not w.model.playout_done and time.time() - t0 < 60:
            time.sleep(0.05)
        self.assertTrue(w.model.playout_done)
        self.assertGreater(len(got), 1)
        self.assertTrue(all(t is BattleState for t in got), got)

    def test_the_menu_call_matches_the_chunk_menu(self):
        board = _board(cogs=3)
        keys, _ = playout.menu_in_child(board, frozenset(), True)
        pairs, _ = playout.chunk_in_child(board, None, frozenset(), True, 0, 1)
        self.assertEqual(keys, [playout._key(p) for p, _v in pairs])


def _party_board(seed=2):
    board = _board(cogs=3, seed=seed)
    board.toons.append(_board(seed=seed + 50).toons[0])
    return board


@unittest.skipUnless(HAVE, "the policy needs numpy")
class PickupTest(unittest.TestCase):
    """Pickup playouts: your move chosen, teammates modelled."""

    def test_the_menu_is_yours_alone_and_stays_small(self):
        board = _party_board()
        board.toons.append(_board(seed=77).toons[0])
        res = playout.pick_pickup(board, None, seed=1, stages=(1,))
        self.assertLessEqual(len(res.candidates), playout.WIDE_CAP)
        for plan in res.candidates:
            self.assertEqual(1, len(plan))

    def test_the_solo_view_counts_the_others(self):
        board = _party_board()
        view = playout.solo_view(board)
        self.assertEqual(1, len(view.toons))
        self.assertEqual(1, view.allies_standing)

    def test_laff_breaks_a_tie_between_two_wins(self):
        a, b = _board(cogs=1), _board(cogs=1)
        for st in (a, b):
            st.cogs[0].hp = 0
        b.toons[0].laff = 10
        self.assertGreater(playout.value(a, 1), playout.value(b, 1))
        self.assertLess(playout.value(a, 1) - playout.value(b, 1), 1.0)


@unittest.skipUnless(HAVE, "the policy needs numpy")
class PartyTest(unittest.TestCase):
    """A party board in `pick_wide`: coordinated by default, as live."""

    def test_coordinated_by_default(self):
        board = _party_board()
        res = playout.pick_wide(board, None, seed=1, stages=(2,))
        self.assertEqual(len(board.toons), len(res.plan))
        self.assertIn(playout._key(res.plan),
                      [playout._key(c) for c in res.candidates])

    def test_every_candidate_is_a_whole_joint_plan(self):
        board = _party_board()
        for plan in playout.wide_candidates(board):
            self.assertEqual(len(board.toons), len(plan))

    def test_pickup_mode_chooses_your_move_alone(self):
        res = playout.pick_wide(_party_board(), None, seed=1, stages=(2,),
                                mode="pickup")
        self.assertEqual(1, len(res.plan))


if __name__ == "__main__":
    unittest.main()


class PouchValueTest(unittest.TestCase):
    """What is left in the pouch when a playout stops before the fight."""

    def _toon(self, counts):
        from solver.state import ToonState, Track

        exp = {Track.SOUND: 6, Track.THROW: 5, Track.DROP: 7}
        return ToonState(54, 54, exp, dict(counts), frozenset(), pouch_capacity=40)

    def _value(self, counts):
        from solver.state import BattleState

        return playout.pouch_value(BattleState(toons=[self._toon(counts)], cogs=[]))

    def test_spending_a_group_gag_costs_more_than_a_single(self):
        """[OWNER] a Foghorn could hit every cog; on a lone one that is waste."""
        from solver.state import Track

        start = {(Track.SOUND, 6): 2, (Track.THROW, 5): 3}
        fog = self._value({(Track.SOUND, 6): 1, (Track.THROW, 5): 3})
        pie = self._value({(Track.SOUND, 6): 2, (Track.THROW, 5): 2})
        self.assertLess(fog, pie)
        self.assertLess(pie, self._value(start))

    def test_a_weak_group_gag_is_cheaper_than_a_strong_single(self):
        """[OWNER] on a cog with 1 hp you spend the cheapest kill: an
        Aoogah, not a Safe. Worth is damage x reach, so a group gag is not
        dear just for being a group gag."""
        from solver.state import Track

        start = {(Track.SOUND, 4): 3, (Track.DROP, 5): 3}
        aoogah = self._value({(Track.SOUND, 4): 2, (Track.DROP, 5): 3})
        safe = self._value({(Track.SOUND, 4): 3, (Track.DROP, 5): 2})
        self.assertGreater(aoogah, safe)     # spending the Aoogah keeps more

    def test_the_last_copy_is_dearest(self):
        from solver.state import Track

        three = self._value({(Track.THROW, 5): 3})
        two = self._value({(Track.THROW, 5): 2})
        one = self._value({(Track.THROW, 5): 1})
        self.assertGreater(one - 0, two - one)
        self.assertGreater(two - one, three - two)

    def test_only_a_building_without_a_horizon_carries_it(self):
        from solver.state import BattleState, Track

        board = BattleState(toons=[self._toon({(Track.THROW, 5): 3})], cogs=[],
                            kind="facility")
        self.assertGreater(playout._carry(board, None)[1], 0)
        board.kind = "street"
        self.assertEqual(0.0, playout._carry(board, None)[1])
        board.kind = "facility"
        hz = BossTracker(kind="vp").horizon(on_field=0)
        self.assertEqual(0.0, playout._carry(board, hz)[1])


class FightKindTest(unittest.TestCase):

    def test_ttr_reads_a_building_from_the_zone(self):
        from solver.live import session

        self.assertEqual("facility", session.fight_kind("Cog Building"))
        self.assertEqual("street", session.fight_kind("Silly Street"))
        self.assertEqual("street", session.fight_kind(""))

    def test_the_other_client_reads_it_from_the_battle_class(self):
        from solver.live import realms_session

        class Battle:
            dclass = "DistributedBattleBldg"
        self.assertEqual("facility", realms_session.battle_kind(Battle()))
        Battle.dclass = "DistributedBattle"
        self.assertEqual("street", realms_session.battle_kind(Battle()))
