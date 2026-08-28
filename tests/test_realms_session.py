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
        # cog doId -> (lure level, rounds elapsed since it landed)
        self.chosen_lures = dict(lures or {})
        self.chosen_traps = {}

    def battles(self):
        return list(self._battles)

    def lure_age(self, cog_do_id):
        return self.chosen_lures.get(cog_do_id)

    def trap_on(self, cog_do_id):
        entry = getattr(self, "chosen_traps", {}).get(cog_do_id)
        return None if entry is None else entry[0]

    def toons(self):
        """Only OUR toon holds an inventory -- `setInventory` is
        `ownrecv`, which is how `player_toon_id` tells us apart."""
        return [o for o in self.store.objs.values()
                if o.get("setInventory") is not None]


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
            FakeListener([battle(TWO_COG_MEMBERS)], objects, {11: (4, 0)}))
        self.assertTrue(seen, seen.problems)
        lured = [c for c in seen.state.cogs if c.status.lured]
        self.assertEqual(len(lured), 1)
        self.assertEqual(lured[0].cog_type, "double_talker",
                         "index '0' names the FIRST suit")
        self.assertEqual(lured[0].status.lure_level, 4)

    def test_lure_rounds_are_counted_down_from_the_gag(self):
        """Duration is COUNTED, because nothing carries it.

        The DC has no lure field at all -- cogs publish DNA, level, HP,
        skelecog, revives and virtual, and the word appears nowhere else
        in the file. So the remaining rounds come from the gag that
        landed (known from `setChosenToonAttacks`) minus the rounds since
        (counted from the battle's movies).
        """
        from solver.data import gags as gags_mod

        full = gags_mod.gag(Track.LURE, 4).rounds()
        for elapsed, want in ((0, full), (1, full - 1)):
            listener = FakeListener(
                [battle(TWO_COG_MEMBERS)],
                [cog(11, "sdt" + NUL + "l", 2, 20, 20),
                 cog(12, "spp" + NUL + "m", 1, 9, 12), toon()],
                {11: (4, elapsed)})
            state = realms_session.build_state(listener).state
            lured = [c for c in state.cogs if c.status.lured][0]
            self.assertEqual(lured.status.lure_rounds_remaining, want,
                             f"{elapsed} rounds elapsed")

    def test_a_lure_past_its_duration_still_has_one_round(self):
        """The cog appearing in `suits_lured` is DIRECT evidence it has
        at least one round left, and that observation outranks the
        arithmetic -- which may disagree because the duration came from
        our table and Realms is a different game. Flooring is the safe
        direction anyway: overestimating a lure plans a combo the cog
        wakes up in the middle of."""
        listener = FakeListener(
            [battle(TWO_COG_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             cog(12, "spp" + NUL + "m", 1, 9, 12), toon()], {11: (4, 99)})
        state = realms_session.build_state(listener).state
        lured = [c for c in state.cogs if c.status.lured][0]
        self.assertEqual(lured.status.lure_rounds_remaining, 1)

    def test_a_watched_trap_reaches_the_cog(self):
        """Traps come from the chosen attacks, not from `setMembers`.

        `setMembers` carries the slots and is authoritative, but it is
        only re-broadcast when membership changes -- so a trap laid
        mid-round never resends it and the roster still reads '99' with
        a cog visibly standing on a TNT. That is exactly what was seen
        live: a trapped Number Cruncher the reader knew nothing about.
        """
        listener = FakeListener(
            [battle(SOLO_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20), toon()])
        listener.chosen_traps = {11: (6, 0)}
        state = realms_session.build_state(listener).state
        status = state.cogs[0].status
        self.assertTrue(status.trapped)
        self.assertEqual(status.trap_level, 6)
        self.assertEqual(status.trap_track, Track.TRAP)

    def test_a_lured_cog_is_never_also_trapped(self):
        """A Lure SPRINGS a trap, so the two cannot coexist. Believing
        in one that has already gone off would have the solver plan for
        damage it has already collected."""
        listener = FakeListener(
            [battle(TWO_COG_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             cog(12, "spp" + NUL + "m", 1, 9, 12), toon()], {11: (4, 0)})
        listener.chosen_traps = {11: (6, 0)}
        state = realms_session.build_state(listener).state
        lured = [c for c in state.cogs if c.status.lured][0]
        self.assertTrue(lured.status.lured)
        self.assertFalse(lured.status.trapped)

    def test_trap_organic_follows_the_thrower_not_the_cog(self):
        """Organic is a property of the toon who laid it. This toon's
        organic track is Throw, so a Trap it lays is not organic."""
        listener = FakeListener(
            [battle(SOLO_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20), toon()])
        listener.chosen_traps = {11: (6, 0)}
        state = realms_session.build_state(listener).state
        self.assertFalse(state.cogs[0].status.trap_organic)

        organic_trap = FakeListener(
            [battle(SOLO_MEMBERS)],
            [cog(11, "sdt" + NUL + "l", 2, 20, 20),
             toon(setTrackBonusLevel=[-1, 6, -1, -1, -1, -1, -1])])
        organic_trap.chosen_traps = {11: (6, 0)}
        state = realms_session.build_state(organic_trap).state
        self.assertTrue(state.cogs[0].status.trap_organic)

    def test_it_finds_our_battle_among_several(self):
        """THE VP SPLITS FOUR TOONS TWO AND TWO, so a boss fight has two
        battle objects, and refusing whenever there is more than one --
        which this used to do -- silences the panel for the whole fight
        it is most wanted in. Streets hit it too, any time somebody else
        in the district is fighting.

        `setInventory` is `ownrecv`, so the toon whose pouch we hold is
        the one being played. That identifies our battle with no
        configuration and no guessing at names.
        """
        theirs = ([21], "", "", "0", "", "9", [999], "", "", "0", "", 1)
        ours = ([11], "", "", "0", "", "9", [100000001], "", "", "0", "", 1)
        listener = FakeListener(
            [Obj(8, {"setMembers": theirs}), Obj(9, {"setMembers": ours})],
            [cog(21, "spp" + NUL + "m", 1, 12, 12),
             cog(11, "sdt" + NUL + "l", 2, 20, 20), toon()])
        result = realms_session.build_state(listener)
        self.assertTrue(result, result.problems)
        self.assertEqual(result.state.cogs[0].cog_type, "double_talker",
                         "picked the other party's fight")

    def test_it_refuses_when_it_cannot_tell_which_is_ours(self):
        """Declining beats advising on somebody else's fight."""
        a = ([21], "", "", "0", "", "9", [999], "", "", "0", "", 1)
        b = ([11], "", "", "0", "", "9", [998], "", "", "0", "", 1)
        listener = FakeListener(
            [Obj(8, {"setMembers": a}), Obj(9, {"setMembers": b})],
            [cog(21, "spp" + NUL + "m", 1, 12, 12),
             cog(11, "sdt" + NUL + "l", 2, 20, 20), toon()])
        result = realms_session.build_state(listener)
        self.assertFalse(result)
        self.assertTrue(any("rosters" in line or "battles" in line
                            for line in result.problems), result.problems)

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
             cog(12, "spp" + NUL + "m", 1, 9, 12), toon()], {11: (4, 0)})
        state = realms_session.build_state(listener).state
        value, action = expectimax.best_action_iterative(
            state, depth=1, objective=objectives.DEFAULT,
            epsilon=0.05, time_budget=5.0, exact_plies=1)
        self.assertIsNotNone(action)
        self.assertIsInstance(value, float)


if __name__ == "__main__":
    unittest.main()
