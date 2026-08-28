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
