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
        # A real index when one is available: the crash this guards
        # against happens INSIDE the DC lookup, so a None index would
        # skip the very code under test.
        if index is None:
            try:
                index = realms.DCIndex()
            except Exception:
                index = None
        obj.index = index
        obj.store = realms.ObjectStore()
        obj.on_event = None
        obj.datagrams = 0
        obj.undecoded = 0
        obj._unknown = {}
        obj.chosen_lures = {}
        obj.battle_rounds = {}
        return obj


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class InstallDirTest(unittest.TestCase):
    """The error for a missing install says "Set REALMS_DIR"; for a long
    time nothing read it."""

    def _install(self, root):
        import pathlib
        folder = pathlib.Path(root) / "astron" / "dclass"
        folder.mkdir(parents=True)
        (folder / "ttoff.dc").write_text("")
        return pathlib.Path(root)

    def test_realms_dir_is_honoured(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as root:
            here = self._install(root)
            with mock.patch.dict(os.environ, {"REALMS_DIR": str(here)}):
                self.assertEqual(here, realms.install_dir())

    def test_an_explicit_override_wins(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as root,                 tempfile.TemporaryDirectory() as other:
            here = self._install(root)
            with mock.patch.dict(os.environ, {"REALMS_DIR": other}):
                self.assertEqual(here, realms.install_dir(str(here)))

    def test_a_wrong_realms_dir_says_where_it_looked(self):
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as empty:
            with mock.patch.dict(os.environ, {"REALMS_DIR": empty}):
                with self.assertRaises(realms.RealmsError) as caught:
                    realms.install_dir()
        self.assertIn(empty, str(caught.exception))


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class RoundCountTest(_Bare):
    """A round is one ENTRY into the movie state."""

    def test_the_doubled_datagram_counts_once(self):
        obj = self.listener(index=object())
        for name in ("WaitForInput", "PlayMovie", "PlayMovie",
                     "WaitForInput", "WaitForInput", "PlayMovie", "PlayMovie"):
            obj._note_state(9, (name, 0))
        self.assertEqual(2, obj.battle_rounds[9])


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

    def test_a_bad_dclass_id_does_not_kill_the_thread(self):
        """REGRESSION, and it was a hard crash rather than a bad read.

        An ENTER message with an out-of-range dclass id reached
        `DCIndex.required_fields`, which called panda3d's `getClass` --
        and that fails a C++ ASSERTION rather than returning None, the
        way `getFieldByIndex` politely does for a bad index. The two
        live on the same object and behave differently.

        `AssertionError` was not in the narrow tuple `feed` caught, so
        it escaped, killed the listener thread, and left the panel
        showing a fight that had quietly stopped updating.
        """
        body = struct.pack("<IIIH", 99, 401000000, 2337, 60000)
        raw = payload(realms.OBJECT_ENTER_LOCATION_WITH_REQUIRED, body)
        one = self.listener()
        one.feed(raw)                   # must not raise
        self.assertEqual(one.datagrams, 1)

    def test_an_unrecognised_message_is_counted(self):
        """Six of the message-type constants were invented and wrong.
        They failed silently, because anything unmatched simply fell off
        the end of the if-chain. Counting them means a number that is
        still wrong shows up as a number."""
        one = self.listener()
        one.feed(payload(9999, b"\x00\x00\x00\x00"))
        self.assertEqual(one._unknown.get(9999), 1)

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

    def test_a_query_reply_never_reverts_a_live_value(self):
        """THE ONE-ROUND-STALE HEALTH BUG, and it was self-inflicted.

        A `GET_ALL` answer describes the object as the state server saw
        it when the query was PROCESSED, so it is already old when it
        lands. Applied wholesale it overwrote values the stream had
        since delivered -- and with the battle roster re-queried every
        poll, a cog's HP was reverted to a pre-hit snapshot about twice
        a second.

        The trace settled where the fault was: `setHP` arrives in the
        same millisecond as the attack choice, thirteen seconds before
        the animation ends. The server was never late.
        """
        store = realms.ObjectStore()
        store.enter(1, "DistributedSuit", 0, 1, {"setHP": 90})
        store.set_field(1, "setHP", 72)
        store.enter(1, "DistributedSuit", 0, 1, {"setHP": 90},
                    fill_only=True)
        self.assertEqual(store.get(1).get("setHP"), 72)

    def test_a_query_refreshes_what_the_stream_never_sends(self):
        """THE OTHER HALF, and the fill-only rule got it wrong.

        `setInventory` is declared `ownrecv`: the pouch goes to the
        owning client and not to a listener, so a QUERY is the only way
        it is ever seen. Filling it once and never again froze the pouch
        at whatever the toon held when the reader attached, and the
        solver went on planning with gags that had been thrown -- a
        worse error than the stale HP the rule was added to prevent.

        The rule is therefore about PROVENANCE, not about age: a query
        may refresh anything the stream does not maintain, and must
        never touch anything it does.
        """
        store = realms.ObjectStore()
        store.set_field(1, "setHP", 90)
        store.enter(1, "DistributedToon", 0, 1,
                    {"setInventory": b"first", "setHP": 90}, fill_only=True)
        store.set_field(1, "setHP", 61)
        store.enter(1, "DistributedToon", 0, 1,
                    {"setInventory": b"second", "setHP": 90}, fill_only=True)
        obj = store.get(1)
        self.assertEqual(obj.get("setHP"), 61, "stream owns this")
        self.assertEqual(obj.get("setInventory"), b"second",
                         "the query is the only source of this")

    def test_a_query_reply_still_fills_what_is_missing(self):
        """Which is the whole reason to query: an object generated
        before we attached has never been described on the stream."""
        store = realms.ObjectStore()
        store.set_field(1, "setHP", 72)
        store.enter(1, "DistributedSuit", 0, 1,
                    {"setLevelDist": 7, "setHP": 90}, fill_only=True)
        obj = store.get(1)
        self.assertEqual(obj.get("setLevelDist"), 7)
        self.assertEqual(obj.get("setHP"), 72, "must not revert")

    def test_a_real_generate_does_overwrite(self):
        """An ENTER is the object arriving, not a snapshot of one, so it
        carries the current truth and replaces what we held."""
        store = realms.ObjectStore()
        store.set_field(1, "setHP", 72)
        store.enter(1, "DistributedSuit", 0, 1, {"setHP": 90})
        self.assertEqual(store.get(1).get("setHP"), 90)

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
        """'9' is this field's "no trap". Two cogs give two characters
        where lured gives one index: the two fields genuinely differ."""
        members = realms.parse_members(self.TWO_COGS)
        self.assertEqual(len(members.suit_traps), len(members.suits))
        self.assertEqual(members.trapped_suits(), ())
        self.assertEqual(members.traps(), {})

    def test_the_trap_character_is_a_zero_based_level(self):
        """Observed live: a trapped Money Bags read '4', and the toon's
        pouch held four Trapdoors -- level 5. There are only seven trap
        levels, so 0-6 are the real values and the '9' sentinel cannot
        collide with one."""
        one = ([501], "", "", "0", "", "4", [1], "", "", "0", "", 0)
        self.assertEqual(realms.parse_members(one).traps(), {501: 5})

    def test_only_the_trapped_slot_is_read(self):
        mixed = ([501, 502], "", "", "01", "", "95",
                 [1], "", "", "0", "", 0)
        members = realms.parse_members(mixed)
        self.assertEqual(members.traps(), {502: 6})
        self.assertEqual(members.trapped_suits(), (502,))

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
class LureAgeTest(unittest.TestCase):
    """Which Lure landed, and how long ago."""

    def listener(self):
        obj = realms.RealmsListener.__new__(realms.RealmsListener)
        obj.store = realms.ObjectStore()
        obj.chosen_lures = {}
        obj.chosen_traps = {}
        obj.last_lure = {}
        obj.battle_rounds = {}
        obj.attacks_seen = 0
        obj.lures_seen = 0
        obj.traps_seen = 0
        obj.store.enter(9, "DistributedBattle", 0, 1, {
            "setMembers": ([11, 12], "", "", "01", "", "99",
                           [100000001], "", "", "0", "", 1)})
        return obj

    def test_a_single_target_lure_is_keyed_on_the_cog(self):
        one = self.listener()
        # (toonIds, tracks, levels, targets, ...): Lure is track 2,
        # level 3 on the wire is level 4 here, aimed at slot 1.
        one._note_chosen_attacks(9, ([100000001], [2], [3], [1], [0]))
        self.assertEqual(one.lure_age(12), (4, 0))

    def test_a_group_lure_still_registers(self):
        """THE ONE THAT BROKE IT LIVE. A group Lure hits every cog and
        has no single target, so its `target` is a sentinel rather than
        a slot. Keying only on the slot recorded nothing, and the reader
        then refused a cog it had WATCHED be lured -- claiming the Lure
        predated it, which was untrue and could not be fixed by
        waiting."""
        one = self.listener()
        one._note_chosen_attacks(9, ([100000001], [2], [5], [255], [0]))
        self.assertEqual(one.lure_age(11), (6, 0))
        self.assertEqual(one.lure_age(12), (6, 0))

    def test_a_group_lure_spends_every_trap_it_reaches(self):
        """THE CASE THE OWNER ASKED ABOUT. Group Lure, one cog trapped.

        Our own simulator says what happens: the trapped cog is dragged
        onto its trap, takes the damage and is knocked AWAKE, while the
        others are lured. So the sprung cog never appears in
        `suits_lured` -- and clearing the trap only when a cog turns up
        lured would hold it forever and have the solver plan a second
        combo for damage already collected.
        """
        one = self.listener()
        one._note_chosen_attacks(9, ([100000001], [1], [5], [0], [0]))
        self.assertEqual(one.trap_on(11), 6)

        # A group Lure: the target is a sentinel, not a slot.
        one._note_chosen_attacks(9, ([100000001], [2], [5], [255], [0]))
        self.assertIsNone(one.trap_on(11), "the trap has been spent")

    def test_a_boss_fight_s_two_battles_do_not_hide_the_lure(self):
        """THE VP BUG. A boss fight has a battle object per side, and the
        lookups used to give up unless there was exactly one -- so every
        Lure in a VP read as unseen and the panel refused to advise the
        moment a cog was lured. Each cog is found in its own battle."""
        one = self.listener()
        one.store.enter(8, "DistributedBattle", 0, 1, {
            "setMembers": ([21, 22], "", "", "00", "", "99",
                           [100000002], "", "", "0", "", 1)})
        one._note_chosen_attacks(9, ([100000001], [2], [5], [255], [0]))
        self.assertEqual(one.lure_age(11), (6, 0))
        self.assertEqual(one.lure_age(12), (6, 0))
        self.assertIsNone(one.lure_age(21), "nothing was thrown on the other side")
        one._note_chosen_attacks(8, ([100000002], [1], [4], [0], [0]))
        self.assertEqual(one.trap_on(21), 5)

    def test_a_single_lure_spends_only_that_cog_s_trap(self):
        one = self.listener()
        one._note_chosen_attacks(9, ([100000001], [1], [5], [0], [0]))
        one._note_chosen_attacks(9, ([100000001], [1], [5], [1], [0]))
        self.assertEqual((one.trap_on(11), one.trap_on(12)), (6, 6))

        one._note_chosen_attacks(9, ([100000001], [2], [3], [1], [0]))
        self.assertEqual(one.trap_on(11), 6, "the other trap survives")
        self.assertIsNone(one.trap_on(12))

    def test_rounds_elapsed_are_counted(self):
        one = self.listener()
        one._note_chosen_attacks(9, ([100000001], [2], [3], [1], [0]))
        one.battle_rounds[9] = 2
        self.assertEqual(one.lure_age(12), (4, 2))

    def test_a_non_lure_attack_records_nothing(self):
        one = self.listener()
        one._note_chosen_attacks(9, ([100000001], [4], [3], [1], [0]))
        self.assertEqual(one.lures_seen, 0)
        self.assertIsNone(one.lure_age(12))

    def test_an_unseen_lure_is_still_unknown(self):
        """Attaching mid-fight must still refuse rather than invent."""
        self.assertIsNone(self.listener().lure_age(12))


@unittest.skipUnless(HAVE_MODULE, "solver.live.realms did not import")
class MovieDamageTest(unittest.TestCase):
    """Applying a round's damage from `setMovie`.

    THE ACTUAL CAUSE of health reading a round behind, after three
    wrong answers. The server writes `setHP` at COMMIT time and the
    value is the HP going INTO that round -- a round's damage only
    reaches the state server at the NEXT commit. Confirmed live: 90 at
    one commit, 61 at the next, with every gag in between having hit.

    So the panel was stale over exactly the window it is used in, and
    no amount of re-querying could fix it: the state server did not
    have the number either. `setMovie` does, and it arrives with the
    commit.
    """

    def listener(self):
        obj = realms.RealmsListener.__new__(realms.RealmsListener)
        obj.store = realms.ObjectStore()
        obj._last_movie = {}
        obj.store.enter(11, "DistributedSuit", 0, 1,
                        {"setHP": 90, "setMaxHP": 90})
        obj.store.enter(12, "DistributedSuit", 0, 1,
                        {"setHP": 42, "setMaxHP": 42})
        return obj

    def movie(self, attacks, suits=(11, 12)):
        return (1, [100], list(suits), attacks, [])

    def test_single_target_damage_lands(self):
        one = self.listener()
        one.apply_movie(9, self.movie([(0, 4, 3, 11, [29], 0, 0, [0], 0, 0)]))
        self.assertEqual(one.store.get(11).get("setHP"), 61)
        self.assertEqual(one.store.get(12).get("setHP"), 42, "untouched")

    def test_the_same_movie_is_not_applied_twice(self):
        """EVERY DATAGRAM ARRIVES TWICE -- a full-range subscription
        matches an object's own channel AND its location channel -- so
        without a guard every cog would die at half health."""
        one = self.listener()
        movie = self.movie([(0, 4, 3, 11, [29], 0, 0, [0], 0, 0)])
        one.apply_movie(9, movie)
        one.apply_movie(9, movie)
        self.assertEqual(one.store.get(11).get("setHP"), 61)

    def test_a_group_gag_hits_every_active_suit(self):
        one = self.listener()
        one.apply_movie(9, self.movie(
            [(0, 3, 5, -1, [20, 20], 0, 0, [0], 0, 0)]))
        self.assertEqual(one.store.get(11).get("setHP"), 70)
        self.assertEqual(one.store.get(12).get("setHP"), 22)

    def test_a_miss_changes_nothing(self):
        one = self.listener()
        one.apply_movie(9, self.movie([(0, 4, 3, 11, [0], 0, 0, [0], 0, 0)]))
        self.assertEqual(one.store.get(11).get("setHP"), 90)

    def test_an_unrecognised_shape_is_left_to_the_server(self):
        """Three damage numbers against two suits is not something this
        knows how to place. Guessing would put damage on the wrong cog;
        the server's own next write is correct anyway, just late."""
        one = self.listener()
        one.apply_movie(9, self.movie(
            [(0, 3, 5, -1, [10, 10, 10], 0, 0, [0], 0, 0)]))
        self.assertEqual(one.store.get(11).get("setHP"), 90)

    def test_health_never_goes_below_zero(self):
        one = self.listener()
        one.apply_movie(9, self.movie([(0, 4, 6, 11, [500], 0, 0, [0], 0, 0)]))
        self.assertEqual(one.store.get(11).get("setHP"), 0)

    def test_a_later_setHP_overrides_rather_than_compounds(self):
        """`setHP` is ABSOLUTE, which is what makes applying the movie
        safe: the server's real value replaces our forward correction
        instead of stacking with it."""
        one = self.listener()
        one.apply_movie(9, self.movie([(0, 4, 3, 11, [29], 0, 0, [0], 0, 0)]))
        one.store.set_field(11, "setHP", 61)
        self.assertEqual(one.store.get(11).get("setHP"), 61)


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
