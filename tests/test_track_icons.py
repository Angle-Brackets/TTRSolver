"""The Silly Team badges, one per gag track.

Read from the player's installation at runtime like the lure magnet and
the map globe, and never vendored. That rule bites harder here than
usual: this art is also published on the TTR wiki, so copying it in from
there would put the game's files in this repository by a different door
while looking like an ordinary asset fetch.
"""
import unittest

try:
    from PIL import Image

    from solver.live import ttr_assets
except ImportError as exc:                   # Pillow is an optional extra
    raise unittest.SkipTest(f"track icons need Pillow: {exc}") from None


class TrackIconKeyTest(unittest.TestCase):
    """Keyed the SOLVER's way, checked against the enum itself."""

    def test_every_track_has_a_file_and_no_others(self):
        from solver.state import Track

        self.assertEqual(sorted(t.value for t in Track),
                         sorted(ttr_assets.TRACK_ICON_FILES))

    def test_the_game_spells_toon_up_differently(self):
        """The one place the two namings diverge, which is the whole
        reason the mapping is a table rather than a format string."""
        self.assertEqual("toonup", ttr_assets.TRACK_ICON_FILES["toon_up"])


class TrackIconReadTest(unittest.TestCase):

    def setUp(self):
        try:
            self.icons = ttr_assets.track_icons()
        except ttr_assets.AssetError as exc:
            raise unittest.SkipTest(f"no Toontown installation: {exc}")
        if not self.icons:
            raise unittest.SkipTest("no track icons in this installation")

    def test_all_seven_are_read(self):
        self.assertEqual(sorted(ttr_assets.TRACK_ICON_FILES),
                         sorted(self.icons))

    def test_each_is_a_cut_out_rather_than_a_square(self):
        """The alpha is a separate SGI file; without it every badge
        would be a 128x128 tile of background."""
        for track, path in self.icons.items():
            with Image.open(path) as icon:
                self.assertEqual("RGBA", icon.mode, track)
                low, high = icon.getchannel("A").getextrema()
                self.assertEqual(0, low, f"{track} has no transparency")
                self.assertEqual(255, high, f"{track} is fully transparent")

    def test_nothing_lands_in_the_repository(self):
        """The cache is gitignored; a badge written anywhere tracked
        would be the vendoring this avoids."""
        import subprocess
        from pathlib import Path

        root = Path(ttr_assets.__file__).resolve().parents[2]
        for path in self.icons.values():
            out = subprocess.run(
                ["git", "check-ignore", str(path)],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(0, out.returncode,
                             f"{path} is not gitignored")


class MissingInstallationTest(unittest.TestCase):
    """A decoration that cannot be read must never stop the panel.

    Driven by making the extraction fail rather than by pointing at a
    missing installation: `extract` answers from its cache before it
    ever looks for the game, so a warm cache keeps serving these after
    an uninstall -- which is the intended behaviour, and would make the
    obvious version of this test pass for the wrong reason.
    """

    def test_a_failed_read_gives_an_empty_set_rather_than_raising(self):
        def boom(*_a, **_k):
            raise ttr_assets.AssetError("no installation")

        saved = ttr_assets.extract
        ttr_assets.extract = boom
        try:
            self.assertEqual({}, ttr_assets.track_icons())
        finally:
            ttr_assets.extract = saved

    def test_one_unreadable_track_does_not_lose_the_others(self):
        """A partial set still leaves every badge it did find correct."""
        saved = ttr_assets.extract

        def flaky(subfile, *a, **k):
            if "sound" in subfile:
                raise ttr_assets.AssetError("missing")
            return saved(subfile, *a, **k)

        ttr_assets.extract = flaky
        try:
            got = ttr_assets.track_icons()
        finally:
            ttr_assets.extract = saved
        if not got:
            self.skipTest("no Toontown installation")
        self.assertNotIn("sound", got)
        self.assertIn("throw", got)


if __name__ == "__main__":
    unittest.main()


class StatusIconTest(unittest.TestCase):
    """The markers TTR floats above a cog: trapped, lured.

    `ttr_m_gui_bat_statusEffect.bam` names forty of them
    (`..._icon_trapped`, `..._icon_lured`, `..._icon_v2_0` and the rest)
    but does not say which palette cell each sits in, so the two mapped
    here were identified by eye against a live frame: the trap marker is
    a banana peel, the lure marker the red magnet.
    """

    def setUp(self):
        try:
            self.icons = {n: ttr_assets.status_icon(n)
                          for n in ttr_assets.STATUS_ICON_CELLS}
        except ttr_assets.AssetError as exc:
            raise unittest.SkipTest(f"no Toontown installation: {exc}")

    def test_only_verified_cells_are_claimed(self):
        """An entry is a claim that the cell is right. The other thirty
        icons are findable the same way and are deliberately absent."""
        self.assertEqual({"trapped", "lured"},
                         set(ttr_assets.STATUS_ICON_CELLS))

    def test_each_is_a_cut_out(self):
        for name, path in self.icons.items():
            with Image.open(path) as icon:
                self.assertEqual("RGBA", icon.mode, name)
                low, high = icon.getchannel("A").getextrema()
                self.assertEqual(0, low, f"{name} has no transparency")
                self.assertEqual(255, high, f"{name} is fully transparent")

    def test_the_two_markers_are_different_pictures(self):
        """Cheap guard against both entries pointing at one cell."""
        import hashlib

        digests = {hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in self.icons.values()}
        self.assertEqual(len(self.icons), len(digests))

    def test_nothing_lands_in_the_repository(self):
        import subprocess
        from pathlib import Path

        root = Path(ttr_assets.__file__).resolve().parents[2]
        for path in self.icons.values():
            out = subprocess.run(["git", "check-ignore", str(path)],
                                 cwd=root, capture_output=True, text=True)
            self.assertEqual(0, out.returncode, f"{path} is not gitignored")


class TrapReachesTheCogTest(unittest.TestCase):
    """A marked trap has to arrive as a LEVEL, not a flag.

    `CogStatus.trapped` with `trap_level=None` raises the moment a Lure
    springs it -- `data.gag(TRAP, None)` has nothing to look up. The
    floating marker is the same banana peel for Quicksand and for TNT,
    so the screen can say a trap is there and cannot say which.
    """

    def _reading(self, **kw):
        from solver.live.watch import CogReading

        base = dict(index=0, department="sellbot", level=8, health=1.0,
                    cog="mr_hollywood")
        base.update(kw)
        return CogReading(**base)

    def test_a_level_arrives_on_the_cog(self):
        from solver.live.session import cog_from_reading

        cog, problems = cog_from_reading(
            self._reading(trapped=True, trap_level=4))
        self.assertEqual([], problems)
        self.assertTrue(cog.status.trapped)
        self.assertEqual(4, cog.status.trap_level)

    def test_a_flag_without_a_level_is_not_applied(self):
        """Better untrapped than trapped-and-unpriceable: the second
        raises when a Lure lands, the first only under-plans."""
        from solver.live.session import cog_from_reading

        cog, _ = cog_from_reading(self._reading(trapped=True))
        self.assertFalse(cog.status.trapped)
        self.assertIsNone(cog.status.trap_level)

    def test_the_watcher_takes_a_level_and_clears_it(self):
        from solver.live.watch import BattleWatcher

        w = BattleWatcher.__new__(BattleWatcher)
        w.mark_trapped(1, 5)
        self.assertEqual({1: 5}, w._traps())
        w.mark_trapped(1, None)
        self.assertEqual({}, w._traps())

    def test_it_refuses_a_level_no_trap_gag_has(self):
        from solver.live.watch import BattleWatcher

        w = BattleWatcher.__new__(BattleWatcher)
        for bad in (0, 8, -1, "x"):
            w.mark_trapped(0, bad)
        self.assertEqual({}, w._traps())

    def test_marks_are_not_shared_between_watchers(self):
        """A dict on the class would leak one battle's traps into the
        next watcher built."""
        from solver.live.watch import BattleWatcher

        a = BattleWatcher.__new__(BattleWatcher)
        b = BattleWatcher.__new__(BattleWatcher)
        a.mark_trapped(0, 3)
        self.assertEqual({}, b._traps())
