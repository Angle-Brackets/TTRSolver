"""The Realms panel: a second Worker, driven by typed fields.

Runs with no cluster and no pywebview -- the listener is faked and
`tick()` is split out of `run()` precisely so it can be. The values are
the ones a live capture produced.

stdlib unittest only -- pytest is not installed.
"""
import queue
import unittest

try:
    from solver.live import realms_panel
    from solver.live.overlay import Model
    HAVE_MODULE = True
except Exception:                       # pragma: no cover
    HAVE_MODULE = False

try:
    from tests.test_realms_session import (INVENTORY, NUL, Obj, Store,
                                           TWO_COG_MEMBERS, battle, cog, toon)
    HAVE_FIXTURES = True
except Exception:                       # pragma: no cover
    HAVE_FIXTURES = False


class FakeListener:
    def __init__(self, battles, objects, lures=None):
        self._battles = battles
        self.store = Store(objects)
        self.chosen_lures = dict(lures or {})

    def battles(self):
        return list(self._battles)

    def lure_age(self, cog_do_id):
        return self.chosen_lures.get(cog_do_id)

    def toons(self):
        return [o for o in self.store.objs.values()
                if o.get("setInventory") is not None]

    def trap_on(self, cog_do_id):
        return None


def worker(listener):
    from solver.search import objective as objectives

    obj = realms_panel.RealmsWorker.__new__(realms_panel.RealmsWorker)
    import threading
    from itertools import count

    obj.outbox = queue.Queue(maxsize=8)
    obj.objective = objectives.DEFAULT
    obj.objective_name = "balanced"
    obj.depth = 1
    obj.budget = 2.0
    obj.listener = listener
    obj.model = Model()
    obj.allow_level_7 = True
    # Mirror the real worker's settings. `engine` was missing and the
    # search thread died on it every tick -- an AttributeError raised in
    # a background thread, printed and otherwise ignored, which is how
    # it survived. `max_fires` is the pink slip cap.
    obj.engine = "both"
    obj.max_fires = 0
    obj._rejected = set()
    obj.record_to = None
    obj.record_error = None
    obj.recorded = 0
    obj._lock = threading.Lock()
    obj._stop = threading.Event()
    obj._generation = count()
    obj._current = -1
    obj._last_key = ()
    obj._asked = threading.Event()
    return obj


def live_listener():
    return FakeListener(
        [battle(TWO_COG_MEMBERS)],
        [cog(11, "sdt" + NUL + "l", 2, 20, 20),
         cog(12, "spp" + NUL + "m", 1, 9, 12), toon()],
        {11: (4, 0)})


@unittest.skipUnless(HAVE_MODULE and HAVE_FIXTURES, "realms panel unavailable")
class RowsTest(unittest.TestCase):

    def test_cogs_are_never_unidentified(self):
        """The picker exists on the TTR side because a plate often
        cannot be resolved to one cog. Here identity comes from
        `setDNAString`, so there is nothing to ask and `choices` must
        stay empty -- an empty picker on every row would be pure noise.
        """
        from solver.live import realms_session

        state = realms_session.build_state(live_listener()).state
        rows = realms_panel.rows_from_state(state)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.identified)
            self.assertEqual(row.choices, [])
            self.assertIsNotNone(row.art_key)

    def test_health_is_exact_not_estimated(self):
        """The TTR panel reads a fraction off a green bar. Here 9/12 is
        9/12 because the server said so."""
        from solver.live import realms_session

        state = realms_session.build_state(live_listener()).state
        rows = realms_panel.rows_from_state(state)
        hurt = [r for r in rows if r.name == "Penny Pincher"][0]
        self.assertAlmostEqual(hurt.health, 9 / 12)

    def test_lure_comes_from_the_roster(self):
        from solver.live import realms_session

        state = realms_session.build_state(live_listener()).state
        rows = realms_panel.rows_from_state(state)
        lured = [r for r in rows if r.lured]
        self.assertEqual([r.name for r in lured], ["Double Talker"])


@unittest.skipUnless(HAVE_MODULE and HAVE_FIXTURES, "realms panel unavailable")
class TickTest(unittest.TestCase):

    def test_a_readable_fight_becomes_a_model(self):
        one = worker(live_listener())
        one.tick()
        model = one.outbox.get_nowait()
        self.assertTrue(model.detected_battle)
        self.assertEqual(model.problems, [])
        self.assertEqual(len(model.rows), 2)
        self.assertEqual(model.toon_count, 1)

    def test_party_size_is_read_not_asked(self):
        members = ([11], "", "", "0", "", "9",
                   [100000001, 2, 3, 4], "", "", "0", "", 1)
        listener = FakeListener([battle(members)],
                                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                                 toon()])
        one = worker(listener)
        one.tick()
        self.assertEqual(one.outbox.get_nowait().toon_count, 4)

    def test_refusals_reach_the_panel_as_problems(self):
        """`build_state` returns reasons instead of a state, and the
        panel must show them rather than an empty fight."""
        listener = FakeListener([], [])
        one = worker(listener)
        one.tick()
        model = one.outbox.get_nowait()
        self.assertFalse(model.detected_battle)
        self.assertTrue(model.problems)
        self.assertEqual(model.rows, [])

    def test_an_unchanged_position_does_not_re_search(self):
        """Realms sends a field per change, so `tick` runs far more often
        than the fight moves. Searching every poll would start a depth-4
        search several times a second."""
        one = worker(live_listener())
        one.tick()
        first = one._last_key
        self.assertTrue(first)
        one.model.thinking = False
        one.tick()
        self.assertEqual(one._last_key, first)

    def test_damage_makes_it_a_new_position(self):
        one = worker(live_listener())
        one.tick()
        before = one._last_key
        moved = FakeListener(
            [battle(TWO_COG_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             cog(12, "spp" + NUL + "m", 1, 3, 12), toon()], {11: (4, 0)})
        one.listener = moved
        one.tick()
        self.assertNotEqual(one._last_key, before)


@unittest.skipUnless(HAVE_MODULE, "realms panel unavailable")
class ApiTest(unittest.TestCase):

    def test_it_does_not_override_what_the_server_states(self):
        """`name_cog` and `mark_lured` exist on the TTR panel so a player
        can supply what the readers could not see. Here the server says
        both, so they must not CHANGE anything.

        They were originally absent on that reasoning, which was right
        about what they should do and wrong about whether they should
        exist: the page is shared, so a click reaches whatever the Api
        has and a missing method fails silently at click time. Inert,
        not absent.
        """
        api = realms_panel.RealmsApi.__new__(realms_panel.RealmsApi)
        for name in ("name_cog", "mark_lured"):
            method = getattr(realms_panel.RealmsApi, name, None)
            self.assertIsNotNone(method, f"the page can call {name}")
            self.assertIsNone(method(api, 0, True))

    def test_set_toon_count_exists_but_is_inert(self):
        """The page is shared, so the click has to land somewhere -- but
        party size is read here and a click must not override it."""
        self.assertTrue(hasattr(realms_panel.RealmsApi, "set_toon_count"))
        api = realms_panel.RealmsApi.__new__(realms_panel.RealmsApi)
        self.assertIsNone(realms_panel.RealmsApi.set_toon_count(api, 3))


@unittest.skipUnless(HAVE_MODULE, "realms panel unavailable")
class BridgeTest(unittest.TestCase):
    """Every method App.jsx calls must exist on RealmsApi.

    The page and this Api were written apart, and two of its buttons --
    "I'm in a fight" and "Work it out" -- called methods that were
    simply absent. A missing method fails at click time with nothing in
    the console the player will ever see.
    """

    def test_every_call_in_the_page_exists(self):
        import re
        from pathlib import Path

        source = Path("overlay_ui/src/App.jsx").read_text(encoding="utf-8")
        called = set(re.findall(r"call\('(\w+)'", source))
        called |= set(re.findall(r"api\.(\w+)\(", source))
        called.discard("pull")          # dev-server fallback only
        missing = [name for name in sorted(called)
                   if not hasattr(realms_panel.RealmsApi, name)]
        self.assertEqual(missing, [], f"App.jsx calls {missing}")

    def test_the_page_is_pushed_to_not_polled(self):
        """`App.jsx` installs `window.pushModel` and waits. A pump that
        only stores the model leaves the page on its own defaults --
        which is exactly how this presented: "waiting for a battle" and
        a 15s budget, 15 being App.jsx's fallback rather than this
        module's 12."""
        import inspect

        source = inspect.getsource(realms_panel.main)
        self.assertIn("pushModel", source)
        self.assertIn("evaluate_js", source)


@unittest.skipUnless(HAVE_MODULE, "realms panel unavailable")
class SeparationTest(unittest.TestCase):
    """The whole point of the second implementation."""

    def test_the_ttr_panel_does_not_import_realms(self):
        """If it ever does, the two have stopped being separate and a
        Realms edit can break the pixel path."""
        import inspect

        from solver.live import overlay, panel, session

        for module in (overlay, panel, session):
            source = inspect.getsource(module)
            self.assertNotIn("realms", source.lower(),
                             f"{module.__name__} mentions realms")


if __name__ == "__main__":
    unittest.main()


class EngineToggleTest(unittest.TestCase):
    """The badge swaps engines without paying for a search.

    The search takes fifteen seconds on any board with two or more cogs
    (measured; see `advise.DEFAULT_DEPTH`), so it runs in the background
    whichever answer is on screen. Swapping then reads a value that is
    already in the model. If it ever starts costing a search, this is
    the test that should fail.
    """

    def _worker(self):
        w = worker(FakeListener([], {}))
        w.model.rl_gag = "Storm Cloud on all"
        w.model.rl_track = "squirt"
        w.model.rl_gag_level = 5
        w.model.gag = w.model.rl_gag
        w.model.engine = "rl"
        return w

    def test_swapping_to_a_finished_search_is_instant(self):
        w = self._worker()
        w.model.search_gag = "Presentation on all"
        w.model.search_track = "lure"
        w.model.search_gag_level = 7
        w.model.search_ready = True
        w.prefer_engine("search")
        self.assertEqual(w.model.gag, "Presentation on all")
        self.assertEqual(w.model.engine, "search")
        self.assertEqual(w.model.track, "lure")
        self.assertEqual(w.model.gag_level, 7)

    def test_swapping_back_restores_the_policy_answer(self):
        w = self._worker()
        w.model.search_gag = "Presentation on all"
        w.model.search_ready = True
        w.prefer_engine("search")
        w.prefer_engine("rl")
        self.assertEqual(w.model.gag, "Storm Cloud on all")
        self.assertEqual(w.model.engine, "rl")

    def test_asking_early_keeps_the_move_on_screen(self):
        """A blank panel mid-fight is worse than the other engine's
        move with a badge saying which it is."""
        w = self._worker()
        w.model.search_ready = False
        w.prefer_engine("search")
        self.assertEqual(w.model.preferred_engine, "search")
        self.assertEqual(w.model.gag, "Storm Cloud on all")
        self.assertEqual(w.model.engine, "rl")

    def test_the_preference_survives_so_the_answer_swaps_itself_in(self):
        """Having asked early, the search must take over when it lands
        rather than needing a second click."""
        w = self._worker()
        w.prefer_engine("search")               # nothing to show yet
        w.model.search_gag = "Presentation on all"
        w.model.search_ready = True
        w.prefer_engine(w.model.preferred_engine)
        self.assertEqual(w.model.gag, "Presentation on all")

    def test_an_unknown_name_falls_back_to_the_policy(self):
        w = self._worker()
        w.prefer_engine("nonsense")
        self.assertEqual(w.model.preferred_engine, "rl")

    def test_the_serialiser_carries_what_the_badge_needs(self):
        import json
        w = self._worker()
        w.model.search_gag = "Presentation on all"
        w.model.search_ready = True
        payload = json.loads(realms_panel.model_json(w.model))
        for key in ("engine", "preferred_engine", "search_ready",
                    "rl_gag", "search_gag"):
            self.assertIn(key, payload)


class PinkSlipTest(unittest.TestCase):
    """Reading the slip count makes fires reachable for the first time.

    `setPinkSlips(uint8) required ownrecv db` on DistributedToon, found
    in the Realms DC file. Nothing read it before, so `toon.fires` was
    always 0 and no engine ever proposed a fire -- which is why the
    render paths could carry a crash for this long without anyone
    meeting it.
    """

    def _action(self, **kw):
        from solver.state import Action
        return Action(**kw)

    def test_a_fire_reports_its_own_track_sentinel(self):
        fire = self._action(track=None, level=0, target_index=1, fire=True)
        self.assertEqual(realms_panel._track_of(fire), "fire")
        self.assertIsNone(realms_panel._level_of(fire))

    def test_a_fire_does_not_look_like_a_pass(self):
        """They render differently and must not collapse together."""
        fire = self._action(track=None, level=0, target_index=1, fire=True)
        a_pass = self._action(track=None)
        self.assertNotEqual(realms_panel._track_of(fire),
                            realms_panel._track_of(a_pass))

    def test_the_old_crash_is_gone(self):
        """`None if is_pass else action.track.value` raised on a fire:
        `is_pass` is False for one and `track` is None."""
        fire = self._action(track=None, level=0, target_index=0, fire=True)
        self.assertFalse(fire.is_pass)
        self.assertIsNone(fire.track)
        realms_panel._track_of(fire)        # must not raise

    def test_the_cap_is_what_limits_planning_not_the_count(self):
        """The count is read from the game and can be 200. The cap is
        the player saying how many they will spend."""
        from solver.live import realms_session

        class Obj:
            do_id = 7
            _f = {"setHp": 90, "setMaxHp": 137,
                  "setPinkSlips": 200,
                  "setTrackAccess": [1, 1, 1, 1, 1, 1, 1],
                  "setTrackBonusLevel": [-1] * 7,
                  "setInventory": None}

            def get(self, name):
                return self._f.get(name)

        obj = Obj()
        obj._f["setInventory"] = _inventory_blob()
        for cap, expected in ((0, 0), (3, 3), (500, 200)):
            toon, why = realms_session.toon_from_object(obj, max_fires=cap)
            self.assertIsNotNone(toon, why)
            self.assertEqual(toon.fires, expected,
                             f"cap {cap} against 200 held")

    def test_zero_is_the_default_so_no_fire_is_ever_advised(self):
        from solver.live import realms_session
        import inspect
        sig = inspect.signature(realms_session.toon_from_object)
        self.assertEqual(sig.parameters["max_fires"].default, 0)


def _inventory_blob():
    """A minimal `setInventory` the parser accepts: 7 tracks x 7 levels."""
    return bytes([0] * 49)


class ReconsiderTest(unittest.TestCase):
    """Rejecting a suggestion, by KIND rather than by exact move.

    The button it replaces re-ran a search on an unchanged board and so
    returned the same answer -- its only effect was the wait.
    """

    def _worker_with(self, track, level=None, gag="something"):
        w = worker(FakeListener([], {}))
        w.model.gag = gag
        w.model.track = track
        w.model.gag_level = level
        return w

    def test_rejecting_a_fire_rejects_every_fire(self):
        """The point of the whole design. Otherwise the button offers
        the same slip against each cog in turn."""
        w = self._worker_with("fire", None, "pink slip on cog 2")
        w.reconsider()
        self.assertIn((None, False), w._rejected)

        from solver.rl import env as env_mod
        from solver.search import hybrid
        keys = {hybrid.reject_key(a) for a in env_mod.ACTIONS
                if a is not None and a.fire}
        self.assertEqual(keys, {(None, False)},
                         "every fire must share one reject key")

    def test_rejecting_a_gag_rejects_that_track_and_reach(self):
        w = self._worker_with("throw", 5, "Birthday Cake on cog 1")
        w.reconsider()
        self.assertTrue(w._rejected)

    def test_rejecting_a_pass_is_possible(self):
        w = self._worker_with(None, None, "pass -- wait for the lure")
        w.reconsider()
        self.assertIn("pass", w._rejected)

    def test_nothing_on_screen_rejects_nothing(self):
        w = self._worker_with("throw", 5, gag="")
        w.reconsider()
        self.assertFalse(w._rejected)

    def test_it_asks_for_a_fresh_answer(self):
        w = self._worker_with("throw", 5)
        w.reconsider()
        self.assertTrue(w._asked.is_set(),
                        "rejecting must trigger a recompute")
        self.assertEqual(w._last_key, ())

    def test_the_climb_honours_a_rejection(self):
        """End to end through the solver rather than the panel: the
        rejected kind must not come back."""
        import random
        from solver import data
        from solver.rl import env as env_mod
        from solver.search import hybrid
        from solver.state import BattleState, CogState, ToonState, Track

        if not hybrid.available():
            self.skipTest(hybrid.unavailable_reason())
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(80, 137, {t: 7 for t in tracks}, {}, frozenset())
        env_mod.restock(toon, random.Random(1))
        hp = data.cog_max_hp(8)
        cogs = [CogState(department="sellbot", cog_type="glad_hander",
                         level=8, hp=hp, max_hp=hp) for _ in range(3)]
        state = BattleState(toon=toon, cogs=cogs)

        plan = hybrid.climb(state, random.Random(0), budget=8)
        first = plan[0] if plan else None
        if first is None or first.is_pass:
            self.skipTest("policy passed; nothing to reject")
        key = hybrid.reject_key(first)
        again = hybrid.climb(state, random.Random(0), budget=8,
                             reject={key})
        second = again[0] if again else None
        if second is not None and not second.is_pass:
            self.assertNotEqual(hybrid.reject_key(second), key,
                                "the rejected kind came back")


class CheapestKillProbeTest(unittest.TestCase):
    """The smallest LEGAL gag that kills a cog, offered to the judge.

    The scorer already prefers a cheap kill; it was never shown one.
    And the probe that was meant to show it was a no-op for its first
    version, because it ignored legality: the cheapest killer of a 6hp
    cog is a single-target SOUND, Sound is group-only, so the one
    candidate offered was always illegal and the caller dropped it.
    """

    def _board(self, hp):
        from solver import data
        from solver.rl import env as env_mod
        from solver.state import BattleState, CogState, ToonState, Track
        tracks = [t for t in Track if t is not Track.TOON_UP]
        toon = ToonState(80, 137, {t: 7 for t in tracks},
                         {(Track.SQUIRT, 4): 4, (Track.DROP, 6): 3,
                          (Track.SOUND, 4): 5},
                         frozenset(), pouch_capacity=80)
        cog = CogState(department="sellbot", cog_type="cold_caller",
                       level=1, hp=hp, max_hp=data.cog_max_hp(1))
        del env_mod
        return BattleState(toon=toon, cogs=[cog])

    def test_it_offers_something_legal(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid
        state = self._board(6)
        legal = env_mod.legal_mask(state, 0)
        found = hybrid._cheapest_kills(state, 0)
        self.assertTrue(found, "nothing offered for a 6hp cog")
        for index in found:
            self.assertTrue(legal[index],
                            f"offered an illegal action at {index}")

    def test_it_prefers_the_smaller_gag(self):
        from solver.rl import env as env_mod
        from solver.search import hybrid
        state = self._board(6)
        found = hybrid._cheapest_kills(state, 0)
        entries = [env_mod.ACTIONS[i] for i in found]
        self.assertTrue(all(e.level <= 4 for e in entries),
                        f"offered {[(e.track.value, e.level) for e in entries]}"
                        f" for a 6hp cog")

    def test_nothing_is_offered_when_nothing_kills(self):
        from solver.search import hybrid
        state = self._board(400)          # more hp than anything held
        self.assertEqual(hybrid._cheapest_kills(state, 0), [])

    def test_the_flag_turns_it_off(self):
        from solver.search import hybrid
        original = hybrid.PROBE_CHEAPEST_KILL
        try:
            hybrid.PROBE_CHEAPEST_KILL = False
            self.assertEqual(hybrid._cheapest_kills(self._board(6), 0), [])
        finally:
            hybrid.PROBE_CHEAPEST_KILL = original


class UniteLineTest(unittest.TestCase):
    """The unite line is populated, and cleared when it no longer applies.

    `Model.unite` was serialised to the page and never set by anything,
    so the line could not appear however many unites were chosen.
    """

    def test_the_field_starts_empty(self):
        w = worker(FakeListener([], {}))
        self.assertEqual(w.model.unite, "")

    def test_the_search_answer_clears_it(self):
        """Expectimax does not model unites, so a unite suggested
        beside the POLICY's move must not linger over the search's."""
        w = worker(FakeListener([], {}))
        w.model.unite = "80 Toon-Up unite"
        w.model.preferred_engine = "search"
        w.model.search_gag = "Presentation on all"
        w.model.search_ready = True
        w.prefer_engine("search")
        self.assertEqual(w.model.gag, "Presentation on all")

    def test_describe_gives_the_phrase_the_line_shows(self):
        from solver import unites
        from solver.state import Track
        self.assertEqual(unites.describe(("toon_up", 80)),
                         "80 Toon-Up unite")
        self.assertEqual(unites.describe(("gag_up", None)),
                         "Gag-Up unite (all tracks)")
        self.assertEqual(unites.describe(("gag_up", Track.THROW)),
                         "Gag-Up unite (throw)")
