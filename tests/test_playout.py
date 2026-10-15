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
        board = _party_board()
        pairs, note = playout.chunk_in_child(board, None, None, True, 0, 1,
                                             mode="pickup")
        self.assertEqual("", note)
        for plan, _values in pairs:
            self.assertEqual(1, len(plan))

    def test_the_mode_does_not_leak_into_the_next_call(self):
        """Pool workers are reused: a pickup board must not leave the next
        board, which named no mode, in pickup."""
        board = _party_board()
        playout.chunk_in_child(board, None, None, True, 0, 1, mode="pickup")
        self.assertEqual("pickup", playout.GROUP_MODE)
        pairs, _note = playout.chunk_in_child(board, None, None, True, 0, 1)
        self.assertEqual(playout.DEFAULT_GROUP_MODE, playout.GROUP_MODE)
        for plan, _values in pairs:
            self.assertEqual(len(board.toons), len(plan))

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


@unittest.skipUnless(HAVE, "the policy needs numpy")
class UniteTest(unittest.TestCase):
    """climb applies its unite to the board it is handed, and playouts
    hand it a copy -- so the unite has to ride on the plan."""

    def _hurt(self):
        board = _board(cogs=4, laff=137, seed=3)
        board.toons[0].laff = 30
        board.toons[0].unites_held = 2
        return playout.build_env(board, None, random.Random(3))

    def test_a_carried_unite_is_spent_in_the_round(self):
        from solver.state import Action

        env = self._hurt()
        plan = playout.with_unite([Action(track=None)], ("toon_up", 80))
        before = env.state.toons[0].laff
        playout.step_round(env, plan)
        self.assertGreater(env.state.toons[0].laff, before)
        self.assertEqual(1, env.state.toons[0].unites_held)

    def test_none_held_means_none_spent(self):
        from solver.state import Action

        env = self._hurt()
        env.state.toons[0].unites_held = 0
        playout.step_round(env, playout.with_unite([Action(track=None)],
                                                    ("toon_up", 80)))
        self.assertEqual(0, env.state.toons[0].unites_held)

    def test_the_menu_offers_the_move_with_and_without_it(self):
        menu = playout.wide_candidates(self._hurt().state)
        first = menu[0]
        self.assertIsNotNone(playout.unite_of(first))
        twins = [p for p in menu if list(p) == list(first)]
        self.assertEqual({True, False},
                         {playout.unite_of(p) is not None for p in twins})

    def test_keys_tell_them_apart(self):
        from solver.state import Action

        plain = [Action(track=None)]
        self.assertNotEqual(playout._key(plain),
                            playout._key(playout.with_unite(plain, ("toon_up", 80))))
        self.assertEqual(playout._key(plain),
                         playout._key(playout.with_unite(plain, None)))

    def test_a_plan_keeps_its_unite_through_a_pickle(self):
        import pickle
        from solver.state import Action

        plan = playout.with_unite([Action(track=None)], ("toon_up", 80))
        self.assertEqual(("toon_up", 80), playout.unite_of(pickle.loads(pickle.dumps(plan))))

    def test_the_panel_shows_the_playouts_unite_with_its_move(self):
        from solver.state import Action

        w = _worker()
        w.model.rl_gag = "Pass"
        w._advise_unite(w.model, "35 Toon-Up unite")
        w._deliver_playout(_board(), Action(track=None), "",
                           lambda a, s: ("Pass", "", 0), unite=("toon_up", 80))
        self.assertTrue(w.model.playout_unite)
        w.prefer_engine("playout")
        self.assertEqual(w.model.playout_unite, w.model.unite)
        w.prefer_engine("rl")
        self.assertEqual("35 Toon-Up unite", w.model.unite)

    def test_a_unite_added_to_the_same_move_appears_without_a_swap(self):
        """THE LIVE BUG: a later chunk kept the move and added a unite,
        and the unite only showed once the player swapped rows."""
        from solver.state import Action

        w = _worker()
        w.model.preferred_engine = "playout"
        say = lambda a, s: ("Pass", "", 0)    # noqa: E731
        w._deliver_playout(_board(), Action(track=None), "", say)
        self.assertEqual("playout", w.model.engine)
        self.assertEqual("", w.model.unite)
        w._deliver_playout(_board(), Action(track=None), "", say,
                           unite=("toon_up", 80))
        self.assertTrue(w.model.unite)
        self.assertEqual(w.model.playout_unite, w.model.unite)
        w._deliver_playout(_board(), Action(track=None), "", say)
        self.assertEqual("", w.model.unite)


@unittest.skipUnless(HAVE, "the policy needs numpy")
class PlayableTest(unittest.TestCase):
    """climb scores plans on boards a unite already changed."""

    def test_a_gag_only_a_gag_up_restocks_needs_the_gag_up(self):
        from solver.data.types import Track
        from solver.state import Action

        board = _board(cogs=2, seed=4)
        toon = board.toons[0]
        toon.unites_held = 1
        toon.gag_counts = {k: v for k, v in toon.gag_counts.items()
                           if k != (Track.THROW, 6)}
        cake = [Action(track=Track.THROW, level=6, target_index=0)]
        self.assertFalse(playout.playable(board, cake))
        self.assertTrue(playout.playable(board, playout.with_unite(cake, ("gag_up", Track.THROW))))
        toon.unites_held = 0
        self.assertFalse(playout.playable(board, playout.with_unite(cake, ("gag_up", Track.THROW))))

    def test_a_held_card_is_playable(self):
        from solver.state import Action

        board = _board(cogs=2, seed=4)
        board.toons[0].sos_cards = {"Flippy": 1}
        call = Action(track=None, sos="Flippy")
        self.assertTrue(playout.playable(board, [call]))


@unittest.skipUnless(HAVE, "the policy needs numpy")
class TeammateUniteTest(unittest.TestCase):
    """A unite costs no turn, so a teammate holding one uses it."""

    def setUp(self):
        import json
        import os
        import tempfile
        from solver.search import fastplayer

        n_in, n_out = len(fastplayer.features_dim_probe()), fastplayer.n_outputs()
        bias = [0.0] * len(fastplayer.unite_slots())
        bias[5] = 5.0                      # the fifth Toon-Up value: 80 on TTR
        payload = {"layers": [[[[0.0] * 4] * n_in, [0.0] * 4],
                              [[[0.0] * n_out] * 4, [0.0] * n_out]],
                   "unite": [[[0.0] * len(bias)] * 4, bias]}
        path = os.path.join(tempfile.mkdtemp(), "w.json")
        with open(path, "w") as fh:
            json.dump(payload, fh)
        self.assertTrue(fastplayer.use(path))

    def tearDown(self):
        from solver.search import fastplayer

        fastplayer._MODEL = fastplayer._UNITE = fastplayer._PATH = None
        playout.TEAMMATE_UNITES = True

    def _party(self, held):
        import copy

        board = _board(cogs=3, laff=137, seed=5)
        mate = copy.deepcopy(board.toons[0])
        mate.laff, mate.unites_held = 20, held
        board.toons.append(mate)
        return playout.build_env(board, None, random.Random(5))

    def _round(self, env):
        from solver.state import Action

        playout.step_round(env, [Action(track=None), Action(track=None)])
        return env.state.toons[1]

    def test_a_teammate_holding_one_heals_themselves(self):
        mate = self._round(self._party(held=2))
        self.assertEqual(1, mate.unites_held)
        self.assertGreater(mate.laff, 20)

    def test_none_held_none_used(self):
        mate = self._round(self._party(held=0))
        self.assertEqual(0, mate.unites_held)

    def test_the_switch_turns_it_off(self):
        playout.TEAMMATE_UNITES = False
        mate = self._round(self._party(held=2))
        self.assertEqual(2, mate.unites_held)

    def test_the_seat_view_puts_that_toon_first(self):
        env = self._party(held=2)
        view = playout.seat_view(env.state, 1)
        self.assertEqual(1, len(view.toons))
        self.assertEqual(20, view.toons[0].laff)
        self.assertEqual(1, view.allies_standing)


class StyleTest(unittest.TestCase):
    """The panel's preset reaches the playouts, relative to Balanced."""

    def tearDown(self):
        playout.set_style(None)

    def _scored(self, preset, rounds=0):
        from solver.search import objective

        board = _board(cogs=2, laff=137, seed=7)
        board.toons[0].laff = 68
        playout.set_style(objective.PRESETS[preset])
        return playout.value(board, total=4, rounds=rounds)

    def test_balanced_is_the_measured_engine(self):
        board = _board(cogs=2, laff=137, seed=7)
        board.toons[0].laff = 68
        playout.set_style(None)
        unset = playout.value(board, total=4, rounds=30)
        self.assertEqual(unset, self._scored("balanced", rounds=30))
        self.assertAlmostEqual(4 - 2 + playout.LAFF_WEIGHT * 68 / 137
                               - playout.ROUND_TIEBREAK * 30, unset)

    def test_survive_values_laff_three_times_as_much(self):
        base = self._scored("balanced") - 2
        self.assertAlmostEqual(3 * base, self._scored("survive") - 2)

    def test_glass_cannon_puts_no_value_on_gags_left(self):
        from solver.search import objective

        board = _board(cogs=2, seed=7)
        board.kind = "facility"
        playout.set_style(objective.PRESETS["glass cannon"])
        self.assertEqual((0.0, 0.0), playout._carry(board, None))
        playout.set_style(objective.PRESETS["conserve"])
        self.assertGreater(playout._carry(board, None)[1],
                           playout.POUCH_WEIGHT["facility"])

    def test_only_speedrun_charges_for_rounds(self):
        """Every preset pays the tie-break (a thousandth of a cog a round);
        only Speedrun pays a real charge on top."""
        for preset in ("balanced", "survive", "conserve", "glass cannon"):
            self.assertAlmostEqual(self._scored(preset) - playout.ROUND_TIEBREAK * 20,
                                   self._scored(preset, rounds=20), msg=preset)
        self.assertLess(self._scored("speedrun", rounds=20), self._scored("speedrun"))

    def test_a_child_process_takes_the_panels_preset(self):
        from solver.search import objective

        playout.chunk_in_child(_board(cogs=1), None, None, True, 0, 0,
                               only=[], style="survive")
        self.assertIs(objective.PRESETS["survive"], playout.STYLE)
        playout.chunk_in_child(_board(cogs=1), None, None, True, 0, 0, only=[])
        self.assertIs(objective.PRESETS["balanced"], playout.STYLE)


@unittest.skipUnless(HAVE, "the policy needs numpy")
class UniteVariantTest(unittest.TestCase):
    """A unite reaches the playouts' menu whether or not climb pays its price."""

    def _board(self, laff=33, held=5, cooldown=0):
        board = _board(cogs=3, laff=100, seed=3)
        toon = board.toons[0]
        toon.laff, toon.unites_held, toon.unite_cooldown = laff, held, cooldown
        return board

    def test_a_heal_and_a_restock_are_offered(self):
        from solver.state import Action, Track

        plan = [Action(Track.THROW, 5, 0)]
        board = self._board()
        # Room in the pouch: this board starts at 80/80, where a Gag-Up
        # restocks nothing and must not be offered (next test).
        counts = board.toons[0].gag_counts
        for key in [k for k in counts if k[1] < 7 and counts[k] > 0][:6]:
            counts[key] = 0
        kinds = {playout.unite_of(p)[0] for p in playout._unite_variants(board, plan)}
        self.assertEqual({"toon_up", "gag_up"}, kinds)

    def test_a_full_pouch_is_offered_the_heal_only(self):
        """Seen live on Realms: Gag-Up advised at 80/80."""
        from solver.state import Action, Track

        plan = [Action(Track.THROW, 5, 0)]
        kinds = {playout.unite_of(p)[0] for p in playout._unite_variants(self._board(), plan)}
        self.assertEqual({"toon_up"}, kinds)

    def test_none_held_or_cooling_down_offers_none(self):
        from solver.state import Action, Track

        plan = [Action(Track.THROW, 5, 0)]
        self.assertEqual([], playout._unite_variants(self._board(held=0), plan))
        self.assertEqual([], playout._unite_variants(self._board(cooldown=2), plan))

    def test_the_menu_carries_a_unite_when_one_is_held(self):
        menu = playout.wide_candidates(self._board())
        self.assertTrue(any(playout.unite_of(p) for p in menu))


class PassOnTheMenuTest(unittest.TestCase):
    """A lone toon's menu offers a pass only when nothing else is
    productive. Offered everywhere, it won by luck on lured boards and the
    owner was told to "pass and let the lure lapse"."""

    def _board(self, counts, lured):
        from solver import data
        from solver.state import BattleState, CogState, ToonState

        hp = data.cog_max_hp(10)
        cogs = [CogState("mr_hollywood", "sellbot", 10, hp, hp) for _ in lured]
        for cog, is_lured in zip(cogs, lured):
            if is_lured:
                cog.status.apply_lure(90, 3, level=6)
        toon = ToonState(80, 100, {t: 7 for t, _ in counts}, {k: 3 for k in counts})
        return BattleState(toons=[toon], cogs=cogs)

    def test_no_pass_while_there_is_something_to_throw(self):
        from solver.data.types import Track
        board = self._board([(Track.THROW, 5)], [True, True])
        self.assertFalse(playout._pass_is_needed(board))
        self.assertFalse(playout._pass_is_needed(self._board([(Track.THROW, 5)], [False])))

    def test_the_trap_and_lure_wait_keeps_it(self):
        from solver.data.types import Track
        board = self._board([(Track.TRAP, 5), (Track.LURE, 4)], [True, True])
        self.assertTrue(playout._pass_is_needed(board))

    def _sampled(self, seed):
        """A toon drawn for a street, its cogs all lured: the boards the
        pass leaked onto."""
        import random
        from solver import data
        from solver.rl import env as env_mod
        from solver.state import BattleState, CogState

        rng = random.Random(seed)
        street = env_mod.facility.sample_street(rng)
        toon = env_mod.toon_for_street(rng, street)
        env_mod.restock(toon, rng)
        level = rng.randint(street[2][0], street[2][1])
        hp = data.cog_max_hp(level)
        cogs = [CogState("mr_hollywood", "sellbot", level, hp, hp) for _ in range(3)]
        for cog in cogs:
            cog.status.apply_lure(90, 3, level=3)
        return BattleState(toons=[toon], cogs=cogs, kind="facility", street=street[0])

    @unittest.skipUnless(HAVE, "needs numpy and the policy weights")
    def test_the_menu_itself_holds_no_pass_unless_one_is_needed(self):
        """THE MENU, not the helper. `PASS_ON_MENU` once gated only the
        explicit entry, and the pass came in through climb's pick and the
        best-of-kind slots on 10-20% of boards like these."""
        checked = 0
        for seed in range(24):
            board = self._sampled(seed)
            if board.is_terminal() or playout._pass_is_needed(board):
                continue
            checked += 1
            menu = playout.wide_candidates(board)
            self.assertTrue(menu, seed)
            self.assertFalse([p for p in menu if playout._bare_pass(p)], seed)
        self.assertGreater(checked, 10)

    @unittest.skipUnless(HAVE, "needs numpy and the policy weights")
    def test_the_old_behaviour_is_still_selectable(self):
        """"kinds" is what "needed" used to do, kept so a sweep can
        compare the two."""
        old = playout.PASS_ON_MENU
        try:
            playout.PASS_ON_MENU = "kinds"
            leaked = sum(any(playout._bare_pass(p)
                             for p in playout.wide_candidates(self._sampled(s)))
                         for s in range(24))
        finally:
            playout.PASS_ON_MENU = old
        self.assertGreater(leaked, 0)


if __name__ == "__main__":
    unittest.main()


class GagEconomyTest(unittest.TestCase):
    """[OWNER] The playouts priced nothing they spent off a building: a
    Storm Cloud on a level 5 was free. Now every gag costs the preset's
    price, at the preset's own gag-for-laff rate."""

    def _charge(self, action, style=None):
        from solver import data
        from solver.data.types import Track
        from solver.simulator import apply_toon_action
        from solver.state import BattleState, CogState, ToonState

        toon = ToonState(100, 100, {Track.SQUIRT: 7, Track.DROP: 7},
                         {(Track.SQUIRT, 6): 3, (Track.DROP, 5): 3})
        hp = data.cog_max_hp(5)
        start = BattleState(toons=[toon], cogs=[CogState("flunky", "bossbot", 5, hp, hp)])
        end = start.clone()
        apply_toon_action(end, action, hit=True)
        saved = playout.STYLE
        playout.set_style(style)
        try:
            return playout.economy(start, end)
        finally:
            playout.set_style(saved)

    def test_a_storm_cloud_costs_more_than_a_safe(self):
        from solver.data.types import Track
        from solver.state import Action
        cloud = self._charge(Action(Track.SQUIRT, 6, 0))
        safe = self._charge(Action(Track.DROP, 5, 0))
        self.assertGreater(cloud, safe)
        self.assertLess(cloud, 0.05, "a tiebreak among sure kills, not a cog")

    def test_it_follows_the_preset(self):
        from solver.data.types import Track
        from solver.search import objective as O
        from solver.state import Action
        cloud = Action(Track.SQUIRT, 6, 0)
        self.assertEqual(0.0, self._charge(cloud, O.PRESETS["glass cannon"]))
        self.assertGreater(self._charge(cloud, O.PRESETS["conserve"]), self._charge(cloud))
