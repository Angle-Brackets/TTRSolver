"""Boss-fight tracking: which fight, cogs down, and the horizon it implies.

Every live wave of a VP used to reach the solver as a standalone street
battle -- no `kind`, `cogs_remaining` of 0 -- so a level 7 cost the least
it ever could. In simulation that blindness took a solo VP from 13/100
to 5/100. These tests pin the part that gives the solver back what a
player knows: the published round structure, counted against.
"""
import random
import unittest

from solver.live import boss
from solver.live.boss import BossTracker


class _Reading:
    def __init__(self, health):
        self.health = health


class KindTest(unittest.TestCase):

    def test_only_the_four_bosses_are_accepted(self):
        tracker = BossTracker()
        for kind in ("vp", "cfo", "cj", "ceo"):
            tracker.set_kind(kind)
        with self.assertRaises(ValueError):
            tracker.set_kind("factory")

    def test_buildings_and_facilities_are_never_named(self):
        """The sign-off covers boss fights only: a building's next floor
        is something a player cannot see."""
        self.assertEqual({"vp", "cfo", "cj", "ceo"}, set(boss.BOSS_KINDS))

    def test_changing_the_fight_restarts_the_count(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(7)
        tracker.set_kind("ceo")
        self.assertEqual(0, tracker.defeated)

    def test_nothing_is_counted_outside_a_boss_fight(self):
        tracker = BossTracker()
        tracker.note_defeated(3)
        tracker.note_dead_ids([1, 2])
        self.assertEqual(0, tracker.defeated)


class VPStructureTest(unittest.TestCase):

    def test_the_cog_round_knows_the_skelecog_round_is_coming(self):
        tracker = BossTracker(kind="vp")
        self.assertEqual(0, tracker.round_index())
        self.assertEqual(20, tracker.later_rounds())

    def test_the_twentieth_defeat_moves_to_the_skelecog_round(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(19)
        self.assertEqual(0, tracker.round_index())
        tracker.note_defeated(1)
        self.assertEqual(1, tracker.round_index())
        self.assertEqual(0, tracker.later_rounds())

    def test_left_in_fight_counts_the_cogs_on_the_field(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(10)
        self.assertEqual(26, tracker.left_in_fight(on_field=4))

    def test_it_matches_what_the_simulator_gives_the_solver(self):
        """`later_rounds` must mean what `FacilityPlan.remaining` means,
        or live advice would be priced on a different horizon from every
        measured result."""
        from solver import vp as vp_mod
        from solver.rl import env as env_mod

        plan = vp_mod.vp_plan(random.Random(1), env_mod._sample_cog
                              if hasattr(env_mod, "_sample_cog")
                              else (lambda rng, lvl: None))
        plan.take_floor()
        self.assertEqual(plan.remaining(), BossTracker(kind="vp").later_rounds())

    def test_a_party_vp_side_meets_ten_a_round(self):
        """[OWNER] twenty a round in all, split across the two sides."""
        for players in (2, 3, 4):
            tracker = BossTracker(kind="vp", party_size=players)
            self.assertEqual(10, tracker.later_rounds())
            self.assertEqual(20, tracker.left_in_fight())

    def test_a_solo_ceo_faces_both_sides(self):
        self.assertEqual((40, None), BossTracker(kind="ceo").rounds())
        self.assertEqual((20, None), BossTracker(kind="ceo", party_size=2).rounds())

    def test_the_simulator_builds_what_the_tracker_expects(self):
        import random

        from solver import vp as vp_mod
        from solver.rl import env as env_mod

        for players in (1, 2):
            e = env_mod.BattleEnv(rng=random.Random(5), sampler=vp_mod.vp_position)
            e.boss_players = players
            e.reset()
            side = len(e.state.cogs) + len(e.state.holdout)
            expect = BossTracker(kind="vp", party_size=players).rounds()
            self.assertEqual(expect, (side, e.state.cogs_remaining))


class UnknownSizesTest(unittest.TestCase):

    def test_cfo_and_cj_count_but_invent_no_horizon(self):
        for kind in ("cfo", "cj"):
            tracker = BossTracker(kind=kind)
            tracker.note_defeated(5)
            self.assertEqual(5, tracker.defeated)
            self.assertIsNone(tracker.later_rounds(), kind)
            self.assertIsNone(tracker.left_in_fight(), kind)

    def test_ceo_battle_two_is_unknown_until_seen(self):
        tracker = BossTracker(kind="ceo")
        self.assertEqual(0, tracker.round_index())
        self.assertIsNone(tracker.later_rounds())


class CountingTest(unittest.TestCase):

    def test_an_id_is_counted_once_however_often_it_is_reported(self):
        tracker = BossTracker(kind="vp")
        tracker.note_dead_ids([11, 12])
        tracker.note_dead_ids([11, 12, 13])
        self.assertEqual(3, tracker.defeated)

    def test_the_player_can_correct_the_count(self):
        tracker = BossTracker(kind="vp")
        tracker.note_defeated(9)
        tracker.correct(12)
        self.assertEqual(12, tracker.defeated)
        tracker.correct(-4)
        self.assertEqual(0, tracker.defeated)


class DiedPlatesTest(unittest.TestCase):
    """The screen reader has no ids, and plates hide behind animations."""

    def test_a_nearly_empty_plate_that_vanishes_died(self):
        before = [_Reading(0.05), _Reading(1.0), _Reading(1.0)]
        self.assertEqual(1, boss.died_plates(before, before[1:]))

    def test_a_healthy_plate_that_vanishes_was_only_hidden(self):
        before = [_Reading(1.0), _Reading(0.9), _Reading(1.0)]
        self.assertEqual(0, boss.died_plates(before, before[:2]))

    def test_never_more_than_the_count_actually_fell(self):
        before = [_Reading(0.1), _Reading(0.1), _Reading(0.1)]
        self.assertEqual(1, boss.died_plates(before, before[:2]))

    def test_a_cog_walking_in_is_not_a_death(self):
        before = [_Reading(0.1)]
        self.assertEqual(0, boss.died_plates(before, before + [_Reading(1.0)]))


class ApplyTest(unittest.TestCase):

    def _state(self):
        from solver import data
        from solver.state import BattleState, CogState, ToonState

        hp = data.cog_max_hp(10)
        return BattleState(toons=[ToonState(laff=140, max_laff=140)],
                           cogs=[CogState(cog_type="mr_hollywood",
                                          department="sellbot", level=10,
                                          hp=hp, max_hp=hp)])

    def test_a_vp_state_gets_its_kind_and_horizon(self):
        state = self._state()
        BossTracker(kind="vp").apply(state)
        self.assertEqual("vp", state.kind)
        self.assertEqual(20, state.cogs_remaining)

    def test_holdout_is_never_invented(self):
        """How many cogs are waiting is known; WHICH cogs is not."""
        state = self._state()
        BossTracker(kind="vp").apply(state)
        self.assertEqual([], list(state.holdout))

    def test_an_unknown_horizon_leaves_cogs_remaining_alone(self):
        state = self._state()
        BossTracker(kind="cfo").apply(state)
        self.assertEqual("cfo", state.kind)
        self.assertEqual(0, state.cogs_remaining)

    def test_no_fight_changes_nothing(self):
        state = self._state()
        BossTracker().apply(state)
        self.assertEqual("street", state.kind)
        self.assertEqual(0, state.cogs_remaining)


def _boss_battle(do_id, members, boss_id=500):
    from tests.test_realms_session import Obj

    obj = Obj(do_id, {"setMembers": members, "setBossCogId": boss_id,
                      "setBattleNumber": 0, "setBattleSide": 0})
    obj.dclass = "DistributedBattleFinal"
    return obj


def _boss_obj(boss_id=500, dclass="DistributedSellbotBoss"):
    from tests.test_realms_session import Obj

    obj = Obj(boss_id, {})
    obj.dclass = dclass
    return obj


def _members(ids):
    return (list(ids), "", "", "0" * len(ids), "", "9" * len(ids),
            [100000001], "", "", "0", "", 1)


class RealmsDetectionTest(unittest.TestCase):
    """The stream names the fight: the battle points at its boss."""

    def test_a_boss_battle_names_its_boss(self):
        from solver.live import realms_session
        from tests.test_realms_panel import FakeListener

        for dclass, kind in realms_session.BOSS_CLASSES.items():
            listener = FakeListener([], [_boss_obj(dclass=dclass)])
            found = realms_session.boss_of(listener,
                                           _boss_battle(9, _members([11])))
            self.assertEqual(kind, found.kind)
            self.assertEqual(500, found.boss_id)

    def test_the_boss_says_how_many_toons_came(self):
        from solver.live import realms_session
        from tests.test_realms_panel import FakeListener

        boss = _boss_obj()
        battle = _boss_battle(9, _members([11]))
        self.assertIsNone(realms_session.boss_of(FakeListener([], [boss]), battle).players)
        boss.fields["setToonIds"] = ([11, 12], [11], [12])
        self.assertEqual(2, realms_session.boss_of(FakeListener([], [boss]), battle).players)

    def test_a_street_battle_is_not_a_boss_fight(self):
        from solver.live import realms_session
        from tests.test_realms_session import Obj
        from tests.test_realms_panel import FakeListener

        street = Obj(9, {"setMembers": _members([11])})
        street.dclass = "DistributedBattle"
        self.assertIsNone(realms_session.boss_of(FakeListener([], []), street))

    def test_an_unknown_boss_class_is_not_guessed(self):
        from solver.live import realms_session
        from tests.test_realms_panel import FakeListener

        listener = FakeListener([], [_boss_obj(dclass="DistributedMystery")])
        self.assertIsNone(realms_session.boss_of(
            listener, _boss_battle(9, _members([11]))))


class RealmsCountingTest(unittest.TestCase):
    """The worker counts by cog id across a whole VP."""

    def setUp(self):
        from tests.test_realms_panel import FakeListener, worker
        from tests.test_realms_session import NUL, cog, toon

        self.cogs = {i: cog(i, "sdt" + NUL + "l", 2, 20, 20)
                     for i in (11, 12, 13, 14)}
        self.toon = toon()
        self.listener = FakeListener([], [])
        self.worker = worker(self.listener)
        self.searched = []
        self.worker._search = self.searched.append

    def _show(self, battle, boss_id=500):
        from tests.test_realms_session import Store

        self.listener._battles = [battle] if battle else []
        self.listener.store = Store(list(self.cogs.values())
                                    + [self.toon, _boss_obj(boss_id)])
        self.worker.tick()

    def test_a_cog_leaving_the_roster_is_counted(self):
        self._show(_boss_battle(9, _members([11, 12])))
        self.assertEqual("vp", self.worker.model.boss_kind)
        self.assertEqual(0, self.worker.model.cogs_defeated)
        self._show(_boss_battle(9, _members([12])))
        self.assertEqual(1, self.worker.model.cogs_defeated)

    def test_the_search_is_given_the_horizon(self):
        self._show(_boss_battle(9, _members([11, 12])))
        self.assertEqual(20, self.searched[-1].cogs_remaining)
        self.assertEqual("vp", self.searched[-1].kind)

    def test_the_gap_between_rounds_keeps_the_count(self):
        self._show(_boss_battle(9, _members([11, 12])))
        self._show(_boss_battle(9, _members([12])))
        self._show(None)
        self.assertEqual(1, self.worker.boss_tracker().defeated)

    def test_a_replaced_battle_means_its_last_cogs_died(self):
        """The round's last kill may never reach the roster -- the
        battle object goes first. The next battle of the same boss is
        proof the round was cleared."""
        self._show(_boss_battle(9, _members([11, 12])))
        self._show(_boss_battle(9, _members([12])))
        self._show(None)
        self._show(_boss_battle(10, _members([13, 14])))
        self.assertEqual(2, self.worker.boss_tracker().defeated)

    def test_a_new_boss_restarts_the_count(self):
        self._show(_boss_battle(9, _members([11, 12])))
        self._show(_boss_battle(9, _members([12])))
        self._show(_boss_battle(10, _members([13]), boss_id=501), boss_id=501)
        self.assertEqual(0, self.worker.boss_tracker().defeated)

    def test_a_street_battle_ends_the_boss_fight(self):
        from tests.test_realms_session import Obj

        self._show(_boss_battle(9, _members([11, 12])))
        street = Obj(9, {"setMembers": _members([13])})
        street.dclass = "DistributedBattle"
        self._show(street)
        self.assertEqual("", self.worker.model.boss_kind)
        self.assertEqual(0, self.searched[-1].cogs_remaining)


class ScreenCountingTest(unittest.TestCase):
    """The screen-reading worker counts plates, and the player rules."""

    def _worker(self):
        import threading

        from solver.live import overlay

        w = overlay.Worker.__new__(overlay.Worker)
        w.model = overlay.Model()
        w.toon_count = 1
        w._lock = threading.Lock()
        w._settings_changed = lambda: None
        return w

    def test_nothing_is_counted_until_a_fight_is_named(self):
        from solver.live.watch import Event

        w = self._worker()
        w._track_boss(w.model, [Event("cog_defeated", "")],
                      [_Reading(0.05), _Reading(1.0)], [_Reading(1.0)])
        self.assertEqual(0, w.model.cogs_defeated)
        self.assertEqual("", w.model.boss_kind)

    def test_a_picked_fight_counts_dying_plates(self):
        from solver.live.watch import Event

        w = self._worker()
        w.set_boss("vp")
        w._track_boss(w.model, [Event("cog_defeated", "")],
                      [_Reading(0.05), _Reading(1.0)], [_Reading(1.0)])
        self.assertEqual("vp", w.model.boss_kind)
        self.assertEqual(1, w.model.cogs_defeated)
        self.assertEqual(38, w.model.cogs_left)

    def test_an_unconfirmed_size_shows_no_total(self):
        w = self._worker()
        w.set_boss("cfo")
        w._track_boss(w.model, [], [], [])
        self.assertEqual(-1, w.model.cogs_left)

    def test_the_player_can_correct_and_clear(self):
        w = self._worker()
        w.set_boss("vp")
        w.set_cogs_defeated(17)
        w._track_boss(w.model, [], [], [])
        self.assertEqual(17, w.model.cogs_defeated)
        w.set_boss("")
        w._track_boss(w.model, [], [], [])
        self.assertEqual("", w.model.boss_kind)

    def test_a_party_side_counts_its_share(self):
        w = self._worker()
        w.set_boss("vp")
        w.toon_count = 2
        w._track_boss(w.model, [], [], [])
        self.assertEqual(20, w.model.cogs_left)

    def test_the_pill_is_the_whole_fight(self):
        """One pill, the toons in the whole fight [OWNER]. In a duo VP each
        toon is alone on a side: 10 + 10 a side, and no teammate in your
        battle to share the cogs' attacks."""
        w = self._worker()
        w.set_boss("vp")
        w._track_boss(w.model, [], [], [])
        self.assertEqual(40, w.model.cogs_left)
        w.toon_count = 2
        w._track_boss(w.model, [], [], [])
        self.assertEqual(20, w.model.cogs_left)
        self.assertEqual(0, w.allies_in_battle())

    def test_off_a_boss_the_pill_is_your_battle(self):
        w = self._worker()
        w.toon_count = 3
        self.assertEqual(2, w.allies_in_battle())

    def test_the_client_log_names_the_vp(self):
        """OBSERVED 2026-10-10: a VP logs ('CogHQBossBattle', 11000). The
        Local API cannot tell it from Sellbot HQ's courtyard."""
        from types import SimpleNamespace
        w = self._worker()
        w._places = SimpleNamespace(place=lambda: ("CogHQBossBattle", 11000))
        w._track_boss(w.model, [], [], [])
        self.assertEqual("vp", w.boss_tracker().kind)
        w._places = SimpleNamespace(place=lambda: ("Playground", 2000))
        w._track_boss(w.model, [], [], [])
        self.assertIsNone(w.boss_tracker().kind, "leaving the room ends it")

    def test_no_boss_zone_is_known_yet(self):
        """Filled only from an observed string, never a plausible one."""
        self.assertEqual({}, boss.TTR_BOSS_ZONES)
        self.assertIsNone(boss.boss_from_location("Sellbot HQ"))


class StaysStdlibTest(unittest.TestCase):

    def test_it_imports_nothing_heavy(self):
        import inspect

        src = inspect.getsource(boss)
        for banned in ("numpy", "panda3d"):
            self.assertNotIn("import " + banned, src)


if __name__ == "__main__":
    unittest.main()


class OwnerPouchTest(unittest.TestCase):

    def test_fills_the_pouch_exactly_with_magnets_last(self):
        import random

        from solver import vp
        from solver.data import gags
        from solver.data.types import Track

        toon = vp.maxed_toon(random.Random(1), laff=120,
                             tracks=[t for t in Track if t is not Track.TOON_UP])
        vp.owner_vp_pouch(toon)
        self.assertEqual(80, gags.pouch_total(toon.gag_counts))
        self.assertEqual(10, toon.gag_counts[(Track.LURE, 4)])
        self.assertEqual(3, toon.gag_counts[(Track.LURE, 6)])
        self.assertNotIn((Track.TRAP, 4), toon.gag_counts)

    def test_skips_tracks_the_toon_lacks(self):
        import random

        from solver import vp
        from solver.data.types import Track

        toon = vp.maxed_toon(random.Random(1), laff=120,
                             tracks=[Track.THROW, Track.SQUIRT, Track.DROP])
        vp.owner_vp_pouch(toon)
        self.assertTrue(all(t in (Track.THROW, Track.SQUIRT, Track.DROP)
                            for t, _ in toon.gag_counts))


class PlayoutLeadsInBossFightsTest(unittest.TestCase):
    """The Playout row is shown in a boss fight unless the player chose."""

    def _worker(self):
        from solver.live import overlay

        w = overlay.Worker.__new__(overlay.Worker)
        w.model = overlay.Model()
        w._boss = None
        w._boss_manual = None
        return w

    def test_the_playouts_lead_in_every_fight(self):
        """[OWNER] prefers the Playout row's choice in all instances."""
        w = self._worker()
        w._boss_into(w.model)
        self.assertEqual("playout", w.model.preferred_engine)
        w.boss_tracker().set_kind("vp")
        w._boss_into(w.model)
        self.assertEqual("playout", w.model.preferred_engine)
        w.boss_tracker().set_kind(None)
        w._boss_into(w.model)
        self.assertEqual("playout", w.model.preferred_engine)

    def test_a_players_choice_is_never_overridden(self):
        import threading

        w = self._worker()
        w._lock = threading.Lock()
        w._post = lambda: None
        w.prefer_engine("search")
        w.boss_tracker().set_kind("vp")
        w._boss_into(w.model)
        self.assertEqual("search", w.model.preferred_engine)
