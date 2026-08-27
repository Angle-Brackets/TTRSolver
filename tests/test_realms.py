"""Reading Toontown Realms' Astron cluster.

Skips rather than fails without panda3d, the same arrangement
tests/test_vision.py has with numpy -- `requirements-realms.txt` is an
optional extra and the suite must still run on the standard library.
Only `DCIndex` needs it, so the framing, store and decoder tests all
run everywhere.

Framing is where this class of reader usually breaks: a TCP read will
split a datagram across two recv() calls whenever it feels like it, and
a half-arrived length prefix must be held rather than parsed.

The decoder tests replay values the live reader actually produced
against a running game, so they are regression tests for real captures
rather than invented ones.

stdlib unittest only -- pytest is not installed.
"""
import struct
import unittest

try:
    from solver.live import realms
    from solver.live.realms import RealmsError
    HAVE_MODULE = True
except Exception:                       # pragma: no cover
    HAVE_MODULE = False

try:
    import panda3d                      # noqa: F401
    HAVE_PANDA = True
except ImportError:
    HAVE_PANDA = False

NUL = chr(0)


def payload(msgtype: int, body: bytes = b"", channel: int = 0,
            sender: int = 0) -> bytes:
    """One MD datagram: length, recipients, sender, type, body."""
    inner = (struct.pack("<B", 1) + struct.pack("<Q", channel)
             + struct.pack("<Q", sender) + struct.pack("<H", msgtype) + body)
    return struct.pack("<H", len(inner)) + inner


class _Bare(unittest.TestCase):
    """A listener with no DC file and no socket.

    `RealmsListener.__init__` builds a `DCIndex`, which needs an
    installation. The framing and store tests need neither, so they are
    handed an object carrying just the attributes they touch.
    """

    def listener(self, index=None):
        obj = realms.RealmsListener.__new__(realms.RealmsListener)
        obj.index = index
        obj.store = realms.ObjectStore()
        obj.on_event = None
        obj.datagrams = 0
        obj.undecoded = 0
        return obj


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class FramingTest(_Bare):

    def test_a_split_datagram_is_held_not_parsed(self):
        """THE FAILURE THIS CLASS OF READER ALWAYS HAS. TCP gives no
        message boundaries, so half a datagram arrives routinely, and
        parsing one would read a length prefix against absent bytes."""
        whole = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 42))
        one = self.listener()
        left = one.feed(whole[:5])
        self.assertEqual(left, whole[:5], "a partial datagram must be kept")
        self.assertEqual(one.datagrams, 0)

        left = one.feed(left + whole[5:])
        self.assertEqual(left, b"")
        self.assertEqual(one.datagrams, 1)

    def test_several_datagrams_in_one_read(self):
        """The other half of the same problem: one recv() can carry
        three messages and a fragment of a fourth."""
        a = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 1))
        b = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 2))
        c = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 3))
        one = self.listener()
        left = one.feed(a + b + c[:4])
        self.assertEqual(one.datagrams, 2)
        self.assertEqual(left, c[:4])

    def test_a_malformed_datagram_does_not_stop_the_stream(self):
        """One bad message must not take down a reader watching a whole
        cluster. It is counted and skipped."""
        bad = struct.pack("<H", 3) + bytes([1, 0, 0])
        good = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 7))
        one = self.listener()
        one.feed(bad + good)
        self.assertEqual(one.datagrams, 2)
        self.assertEqual(one.undecoded, 1)


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class ControlMessageTest(unittest.TestCase):

    def test_control_messages_carry_no_sender(self):
        """Astron control messages address channel 1 and OMIT the sender
        field every other message carries. Including it shifts the
        message type by eight bytes, and the server reads a subscription
        request as something else entirely."""
        raw = realms._control(realms.CONTROL_ADD_CHANNEL,
                              struct.pack("<Q", 1234))
        (length,) = struct.unpack_from("<H", raw, 0)
        self.assertEqual(len(raw) - 2, length)
        count, channel, msgtype = struct.unpack_from("<BQH", raw, 2)
        self.assertEqual((count, channel), (1, realms.CONTROL_CHANNEL))
        self.assertEqual(msgtype, realms.CONTROL_ADD_CHANNEL)


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class ObjectStoreTest(unittest.TestCase):

    def test_a_field_update_creates_the_object(self):
        """Updates arrive for objects generated before the listener
        attached, so a set on an unknown doId is normal, not an error."""
        store = realms.ObjectStore()
        store.set_field(7, "setHP", 42)
        self.assertEqual(store.get(7).get("setHP"), 42)

    def test_enter_fills_in_the_class_and_location(self):
        store = realms.ObjectStore()
        store.set_field(7, "setHP", 42)
        store.enter(7, "DistributedSuit", 401000000, 2337, {"setMaxHP": 90})
        obj = store.get(7)
        self.assertEqual(obj.dclass, "DistributedSuit")
        self.assertEqual(obj.zone, 2337)
        self.assertEqual(obj.get("setHP"), 42, "earlier fields must survive")
        self.assertEqual(obj.get("setMaxHP"), 90)

    def test_delete_removes_it(self):
        store = realms.ObjectStore()
        store.enter(7, "DistributedSuit", 0, 1, {})
        store.delete(7)
        self.assertIsNone(store.get(7))

    def test_a_battle_learned_from_the_stream_is_found(self):
        """REGRESSION. A SET_FIELD names no class, so an object learned
        from the live stream is tagged with the class the FIELD was
        declared on -- and both `setState` and `setMembers` are declared
        on `DistributedBattleBase`, not on the concrete battle classes.

        With the base missing from `BATTLE_CLASSES`, `battles()` matched
        nothing and the lure watcher sat there finding no fight at all.
        It went unnoticed because cogs were fine (the base IS in
        `COG_CLASSES`) and because the CLI calls `refresh_all` first,
        which resolves the real class through the ENTER path and papers
        over it. The tool that did not call it saw nothing.
        """
        store = realms.ObjectStore()
        store.set_field(9, "setMembers", None)
        store.objects[9].dclass = "DistributedBattleBase"
        self.assertEqual(len(store.of_class(*realms.BATTLE_CLASSES)), 1)

    def test_the_base_classes_are_in_both_lists(self):
        """Cogs and battles must behave the same way here. They did not,
        which is the whole reason the bug above survived."""
        self.assertIn("DistributedSuitBase", realms.COG_CLASSES)
        self.assertIn("DistributedBattleBase", realms.BATTLE_CLASSES)

    def test_of_class_selects(self):
        store = realms.ObjectStore()
        store.enter(1, "DistributedSuit", 0, 1, {})
        store.enter(2, "DistributedToon", 0, 1, {})
        store.enter(3, "DistributedButterfly", 0, 1, {})
        self.assertEqual({o.do_id for o in store.of_class("DistributedSuit")},
                         {1})
        self.assertEqual(len(store.of_class(*realms.TOON_CLASSES)), 1)


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class MembersTest(unittest.TestCase):
    """Two live captures, replayed. The values are the ones the reader
    actually produced against a running game."""

    SOLO = ([401005039], "", "", "0", "", "9",
            [100000001], "", "", "0", "", -23220)
    TWO_COGS = ([401005045, 401005050], "", "", "01", "0", "99",
                [100000001], "", "", "0", "", 17404)

    def test_party_size_comes_straight_out(self):
        solo = realms.parse_members(self.SOLO)
        self.assertEqual(solo.toon_count, 1)
        self.assertEqual(solo.allies_standing, 0)

    def test_lured_is_indices_not_one_char_per_suit(self):
        """THE ONE THAT MATTERS, and why two captures were needed.

        Two cogs with the first lured gives lured='0'. Read as one
        character per suit that says "suit 0 is in state 0", which would
        mark the WRONG cog asleep in a solver where lure is the pivot of
        every Trap line. Read as a list of indices it says "suit 0",
        which is what it is. The single-cog capture agrees with both
        readings and so decides nothing.
        """
        members = realms.parse_members(self.TWO_COGS)
        self.assertEqual(members.lured_suits(), (401005045,))
        self.assertEqual(members.active_suits(), (401005045, 401005050))

    def test_nothing_lured_reads_as_nothing(self):
        self.assertEqual(realms.parse_members(self.SOLO).lured_suits(), ())

    def test_traps_are_one_char_per_suit(self):
        """'9' is this field's "no trap", in every slot of every capture
        so far. Two cogs give two characters where lured gives one
        index: the two fields genuinely differ."""
        members = realms.parse_members(self.TWO_COGS)
        self.assertEqual(len(members.suit_traps), len(members.suits))
        self.assertEqual(members.trapped_suits(), ())

    def test_an_index_outside_the_roster_is_dropped(self):
        """Defensive. An index naming a suit not in the list would
        otherwise raise, and a reader watching a whole cluster must not
        die of one odd frame."""
        odd = ([1, 2], "", "", "01", "7", "99", [10], "", "", "0", "", 0)
        self.assertEqual(realms.parse_members(odd).lured_suits(), ())

    def test_junk_is_refused(self):
        for bad in (None, "", (1, 2, 3), ["x"] * 12):
            self.assertIsNone(realms.parse_members(bad))


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class DNATest(unittest.TestCase):

    LIVE = {
        "sdt" + NUL + "l": ("lawbot", "double_talker"),
        "spp" + NUL + "m": ("cashbot", "penny_pincher"),
        "sf" + NUL + NUL + "c": ("bossbot", "flunky"),
        "scc" + NUL + "s": ("sellbot", "cold_caller"),
        "ssc" + NUL + "m": ("cashbot", "short_change"),
    }

    def test_the_live_reads_decode(self):
        for dna, want in self.LIVE.items():
            self.assertEqual(realms.parse_dna(dna), want, repr(dna))

    def test_every_code_names_a_cog_we_know(self):
        """The map translates identifiers, it is not game data -- and it
        is worthless if it points at keys `solver.data` does not have."""
        from solver import data

        for code, key in realms.DNA_COGS.items():
            found = [d for d in realms.DNA_DEPARTMENTS.values()
                     if key in data.COG_DEPARTMENTS[d]]
            self.assertEqual(len(found), 1,
                             f"{code} -> {key} found in {found}")

    def test_all_four_departments_and_every_cog(self):
        self.assertEqual(set(realms.DNA_DEPARTMENTS.values()),
                         {"bossbot", "sellbot", "cashbot", "lawbot"})
        self.assertEqual(len(realms.DNA_COGS), 32)

    def test_an_unknown_code_is_refused_not_guessed(self):
        """Same rule the head catalogue follows. Being handed a typed
        field instead of a picture is no reason to start guessing."""
        for bad in ("szz" + NUL + "l", "sdt" + NUL + "x", "",
                    "xdt" + NUL + "l", None, 5):
            self.assertIsNone(realms.parse_dna(bad), repr(bad))

    def test_level_is_dist_plus_one(self):
        """Cross-checked against our OWN HP table rather than Realms'.
        A Penny Pincher at dist 1 had 12 hp and a Double Talker at dist
        2 had 20, which are levels 2 and 3. Both cogs' ranges start
        above level 1, so an offset-into-range reading would have given
        0 for each -- which is what makes these two discriminating."""
        from solver.data.cogs import COG_HP_BY_LEVEL

        for dist, hp in ((0, 6), (1, 12), (2, 20)):
            self.assertEqual(COG_HP_BY_LEVEL[realms.cog_level(dist)], hp)
        self.assertIsNone(realms.cog_level(None))


@unittest.skipUnless(HAVE_MODULE and HAVE_PANDA,
                     "needs panda3d (requirements-realms.txt)")
class DCIndexTest(unittest.TestCase):
    """Needs the .dc file from a real installation, so it skips when
    Realms is not installed rather than failing."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.index = realms.DCIndex()
        except RealmsError as exc:
            raise unittest.SkipTest(str(exc))

    def test_the_battle_fields_resolve(self):
        """These are the fields the module exists to read. A DC file
        without them is not one we can use."""
        for cls_name, field in (("DistributedSuitBase", "setHP"),
                                ("DistributedSuitBase", "setMaxHP"),
                                ("DistributedSuitBase", "setLevelDist"),
                                ("DistributedSuitBase", "setDNAString"),
                                ("DistributedBattleBase", "setMembers"),
                                ("DistributedBattleBase", "setState"),
                                ("DistributedToon", "setHp")):
            fid = self.index.field_id(cls_name, field)
            self.assertIsNotNone(fid, f"{cls_name}.{field} missing")
            self.assertEqual(self.index.name(fid), f"{cls_name}.{field}",
                             "a field id must round-trip to its own name")

    def test_numbering_is_not_declaration_order(self):
        """Recorded because assuming it was cost real time: a
        hand-rolled parser numbered fields in file order, put
        setPathPosition at 492, and decoded live cog traffic as
        DistributedPlayer.setDISLname. The game's own parser is used
        precisely so this cannot be got wrong again."""
        fid = self.index.field_id("DistributedSuitBase", "setHP")
        self.assertEqual(self.index.name(fid), "DistributedSuitBase.setHP")

    def test_required_fields_skip_molecular_ones(self):
        """A molecular field is an alias for several atomic fields and
        is never packed on the wire. Counting one would consume bytes
        that are not there and desynchronise the rest of the message."""
        dclass_id = None
        for i in range(4000):
            if self.index.class_name(i) == "DistributedSuit":
                dclass_id = i
                break
        if dclass_id is None:
            self.skipTest("DistributedSuit not in this DC file")
        for field in self.index.required_fields(dclass_id):
            self.assertIsNone(field.asMolecularField())


if __name__ == "__main__":
    unittest.main()
