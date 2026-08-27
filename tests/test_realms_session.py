"""Building a BattleState from Realms' typed fields.

A SECOND IMPLEMENTATION alongside `session.build_state`, not a branch
inside it, and these tests exist partly to keep it that way: the TTR
path refuses because a measurement was not confident enough, this one
refuses because an object has not arrived. Sharing the module would
mean threading both kinds of doubt through one function.

Needs no panda3d and no running cluster -- the listener is faked, and
the values are the ones a live capture actually produced.

stdlib unittest only -- pytest is not installed.
"""
import unittest

try:
    from solver.live import realms, realms_session
    from solver.state import Track
    HAVE_MODULE = True
except Exception:                       # pragma: no cover
    HAVE_MODULE = False

NUL = chr(0)

# A real toon's setInventory, read out of the YAML database: no Toon-Up,
# and level 7s in every other track.
INVENTORY = bytes.fromhex(
    "3100"              # uint16 length prefix: 49 bytes follow
    "00000000000000"    # toon-up 0/0/0/0/0/0/0
    "00000000040201"    # trap    0/0/0/0/4/2/1
    "0000000a060301"    # lure    0/0/0/10/6/3/1
    "00000005060301"    # sound   0/0/0/5/6/3/1
    "00000004070301"    # throw   0/0/0/4/7/3/1
    "00000004060301"    # squirt  0/0/0/4/6/3/1
    "00000000070301"    # drop    0/0/0/0/7/3/1
)


class Obj:
    def __init__(self, do_id, fields):
        self.do_id, self.fields = do_id, fields

    def get(self, key, default=None):
        return self.fields.get(key, default)


class Store:
    def __init__(self, objects):
        self.objs = {o.do_id: o for o in objects}

    def get(self, do_id):
        return self.objs.get(do_id)


class FakeListener:
    def __init__(self, battles, objects, lures=None):
        self._battles = battles
        self.store = Store(objects)
        self.chosen_lures = dict(lures or {})

    def battles(self):
        return list(self._battles)


def battle(members):
    return Obj(9, {"setMembers": members})


def cog(do_id, dna, dist, hp, max_hp):
    return Obj(do_id, {"setDNAString": dna, "setLevelDist": dist,
                       "setHP": hp, "setMaxHP": max_hp})


def toon(do_id=100000001, **over):
    fields = {"setHp": 98, "setMaxHp": 100, "setInventory": INVENTORY,
              "setTrackAccess": [0, 1, 1, 1, 1, 1, 1],
              "setTrackBonusLevel": [-1, -1, -1, -1, 6, -1, -1]}
    fields.update(over)
    return Obj(do_id, fields)


SOLO_MEMBERS = ([11], "", "", "0", "", "9",
                [100000001], "", "", "0", "", 1)
TWO_COG_MEMBERS = ([11, 12], "", "", "01", "0", "99",
                   [100000001], "", "", "0", "", 1)


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class InventoryTest(unittest.TestCase):

    def test_seven_by_seven_with_a_length_prefix(self):
        counts = realms.parse_inventory(INVENTORY)
        self.assertEqual(counts[(Track.TRAP, 6)], 2, "two TNT")
        self.assertEqual(counts[(Track.TRAP, 7)], 1, "one Railroad")
        self.assertEqual(counts[(Track.LURE, 4)], 10)
        self.assertEqual(sum(n for (_t, lvl), n in counts.items() if lvl <= 6),
                         76)

    def test_a_track_the_toon_lacks_is_simply_absent(self):
        """Toon-Up is all zeros for this toon, which is the same fact
        `setTrackAccess[0] == 0` states -- two independent ways of
        saying it, and they agree."""
        counts = realms.parse_inventory(INVENTORY)
        self.assertFalse([k for k in counts if k[0] is Track.TOON_UP])
        self.assertNotIn(Track.TOON_UP,
                         realms.parse_track_access([0, 1, 1, 1, 1, 1, 1]))

    def test_junk_is_refused(self):
        for bad in (None, 5, b"", b"\x00" * 10, "not bytes at all"):
            self.assertIsNone(realms.parse_inventory(bad), repr(bad))

    def test_track_order_is_written_out_not_inherited(self):
        """`DC_TRACK_ORDER` must match `Track`'s values today, but it is
        stated rather than derived: reordering the enum in an unrelated
        file would otherwise shift every gag count by one track, with
        nothing to catch it."""
        self.assertEqual(realms.DC_TRACK_ORDER,
                         ("toon_up", "trap", "lure", "sound",
                          "throw", "squirt", "drop"))

    def test_organic_is_a_whole_track(self):
        organic = realms.parse_organic([-1, -1, -1, -1, 6, -1, -1])
        self.assertEqual(organic, frozenset({Track.THROW}))
        self.assertEqual(realms.parse_organic([-1] * 7), frozenset())
        self.assertIsNone(realms.parse_organic([-1] * 3))


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class BuildStateTest(unittest.TestCase):

    def test_a_whole_solo_fight(self):
        listener = FakeListener([battle(SOLO_MEMBERS)],
                                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                                 toon()])
        result = realms_session.build_state(listener)
        self.assertTrue(result, result.problems)
        state = result.state
        self.assertEqual((state.toon.laff, state.toon.max_laff), (98, 100))
        self.assertEqual(state.allies_standing, 0)
        self.assertEqual(len(state.cogs), 1)
        self.assertEqual(state.cogs[0].cog_type, "double_talker")
        self.assertEqual(state.cogs[0].level, 3)
        self.assertEqual(state.cogs[0].hp, 20)

    def test_party_size_comes_from_the_roster(self):
        """The TTR panel has to ask the player for this. Here the game
        states it, and it drives `allies_standing`."""
        members = ([11], "", "", "0", "", "9",
                   [100000001, 2, 3, 4], "", "", "0", "", 1)
        listener = FakeListener([battle(members)],
                                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                                 toon()])
        result = realms_session.build_state(listener)
        self.assertTrue(result, result.problems)
        self.assertEqual(result.state.allies_standing, 3)

    def test_a_lured_cog_needs_the_lure_that_landed(self):
        """`setMembers` says lured and never with what. Without the
        level the search raises deep in the cog phase, so this refuses
        up front and says why."""
        objects = [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                   cog(12, "spp" + NUL + "m", 1, 9, 12), toon()]
        blind = realms_session.build_state(
            FakeListener([battle(TWO_COG_MEMBERS)], objects))
        self.assertFalse(blind)
        self.assertTrue(any("level is unknown" in p for p in blind.problems),
                        blind.problems)

        seen = realms_session.build_state(
            FakeListener([battle(TWO_COG_MEMBERS)], objects, {11: 4}))
        self.assertTrue(seen, seen.problems)
        lured = [c for c in seen.state.cogs if c.status.lured]
        self.assertEqual(len(lured), 1)
        self.assertEqual(lured[0].cog_type, "double_talker",
                         "index '0' names the FIRST suit")
        self.assertEqual(lured[0].status.lure_level, 4)

    def test_lure_rounds_are_the_pessimistic_floor(self):
        """Duration is not sent. One round is what is certainly left;
        assuming the full duration would plan a combo the cog wakes up
        in the middle of."""
        listener = FakeListener(
            [battle(TWO_COG_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             cog(12, "spp" + NUL + "m", 1, 9, 12), toon()], {11: 4})
        state = realms_session.build_state(listener).state
        lured = [c for c in state.cogs if c.status.lured][0]
        self.assertEqual(lured.status.lure_rounds_remaining, 1)

    def test_it_refuses_when_two_battles_are_running(self):
        """Another toon fighting elsewhere in the district is ordinary,
        and guessing which is yours would advise somebody else's fight."""
        listener = FakeListener([battle(SOLO_MEMBERS), battle(SOLO_MEMBERS)],
                                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                                 toon()])
        result = realms_session.build_state(listener)
        self.assertFalse(result)
        self.assertTrue(any("2 battles" in p for p in result.problems))

    def test_it_refuses_a_cog_it_cannot_name(self):
        listener = FakeListener([battle(SOLO_MEMBERS)],
                                [cog(11, "szz" + NUL + "l", 2, 20, 20),
                                 toon()])
        result = realms_session.build_state(listener)
        self.assertFalse(result)
        self.assertTrue(any("cannot name" in p for p in result.problems))

    def test_it_refuses_when_the_pouch_has_not_arrived(self):
        listener = FakeListener([battle(SOLO_MEMBERS)],
                                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                                 toon(setInventory=None)])
        result = realms_session.build_state(listener)
        self.assertFalse(result)
        self.assertTrue(any("inventory" in p for p in result.problems))

    def test_every_reason_at_once(self):
        """Same rule `session.build_state` follows: being told one
        problem at a time is the difference between fixing a setup and
        playing whack-a-mole with it."""
        listener = FakeListener([battle(TWO_COG_MEMBERS)],
                                [cog(11, "szz" + NUL + "l", 2, 20, 20),
                                 toon(setHp=None)])
        result = realms_session.build_state(listener)
        self.assertFalse(result)
        self.assertGreaterEqual(len(result.problems), 2, result.problems)

    def test_the_state_is_searchable(self):
        """The point of the whole module. A state the solver raises on
        is not a state."""
        from solver.search import expectimax, objective as objectives

        listener = FakeListener(
            [battle(TWO_COG_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             cog(12, "spp" + NUL + "m", 1, 9, 12), toon()], {11: 4})
        state = realms_session.build_state(listener).state
        value, action = expectimax.best_action_iterative(
            state, depth=1, objective=objectives.DEFAULT,
            epsilon=0.05, time_budget=5.0, exact_plies=1)
        self.assertIsNotNone(action)
        self.assertIsInstance(value, float)


if __name__ == "__main__":
    unittest.main()
