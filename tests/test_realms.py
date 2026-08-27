"""Reading Toontown Realms' Astron cluster.

Skips rather than fails without panda3d, the same arrangement
tests/test_vision.py has with numpy -- `requirements-realms.txt` is an
optional extra and the suite must still run on the standard library.

The parts worth testing without a live cluster are the wire framing and
the store. Framing is where this class of reader usually breaks: a TCP
read will split a datagram across two recv() calls whenever it feels
like it, and a length prefix that is half-arrived must be held rather
than parsed.

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
    given an object with just the attributes they touch.
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
        message boundaries, so half a datagram arrives routinely. Parsing
        it would decode a length prefix against absent bytes."""
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
        bad = struct.pack("<H", 3) + b"\x01\x00\x00"
        good = payload(realms.OBJECT_DELETE_RAM, struct.pack("<I", 7))
        one = self.listener()
        one.feed(bad + good)
        self.assertEqual(one.datagrams, 2)
        self.assertEqual(one.undecoded, 1)


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class ControlMessageTest(unittest.TestCase):

    def test_control_messages_carry_no_sender(self):
        """Astron control messages address channel 1 and OMIT the sender
        field every other message has. Including it shifts the message
        type by eight bytes, and the server sees a subscription request
        as something else entirely."""
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

    def test_of_class_selects(self):
        store = realms.ObjectStore()
        store.enter(1, "DistributedSuit", 0, 1, {})
        store.enter(2, "DistributedToon", 0, 1, {})
        store.enter(3, "DistributedButterfly", 0, 1, {})
        self.assertEqual({o.do_id for o in store.of_class("DistributedSuit")},
                         {1})
        self.assertEqual(len(store.of_class(*realms.TOON_CLASSES)), 1)


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
        """These are the fields the whole module exists to read. A DC
        file that does not have them is not one we can use."""
        for cls_name, field in (("DistributedSuitBase", "setHP"),
                                ("DistributedSuitBase", "setMaxHP"),
                                ("DistributedSuitBase", "setLevelDist"),
                                ("DistributedSuitBase", "setDNAString"),
                                ("DistributedBattleBase", "setMembers"),
                                ("DistributedBattleBase", "setState"),
                                ("DistributedToon", "setHp")):
            fid = self.index.field_id(cls_name, field)
            self.assertIsNotNone(fid, f"{cls_name}.{field} missing")
            self.assertEqual(self.index.name(fid),
                             f"{cls_name}.{field}",
                             "field id must round-trip to its own name")

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
