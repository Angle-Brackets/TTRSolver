"""Reading gag counts off the gag menu.

Panels are synthesised so these run with no game and no screenshot. The
geometry they build is the geometry measured from a real 1080p frame: a
label area then seven cells, rows in track order, each backed by its own
colour.
"""
import unittest

try:
    import numpy as np

    from solver.live import gagpanel as G
    from solver.live.gagpanel import PanelCell, find_panel, read_panel
    from solver.state import Track
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"gagpanel needs numpy: {exc}") from None


PANEL_X, PANEL_W, ROW_H, TOP = 389, 862, 73, 270
BLUE = (60, 140, 220)
GREY = (90, 88, 86)
SCENE = (70, 70, 80)


def panel_frame(counts, size=(1920, 1080), unlocked=None):
    """A frame containing a gag panel showing `counts` per track."""
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :] = SCENE
    for r, (track, colour) in enumerate(G.ROW_COLOURS):
        top = TOP + r * ROW_H
        img[top:top + ROW_H, PANEL_X:PANEL_X + PANEL_W] = colour
        row = counts.get(track, [0] * 7)
        for col in range(7):
            x0 = PANEL_X + round((G.CELL_LEFT + G.CELL_PITCH * col) * PANEL_W)
            x1 = x0 + round(G.CELL_WIDTH * PANEL_W)
            value = row[col]
            if value is None:               # slot drawn but never filled
                img[top + 4:top + ROW_H - 6, x0:x1] = BLUE
                continue
            img[top + 4:top + ROW_H - 6, x0:x1] = BLUE if value else GREY
            if value:
                _draw_digit(img, value, x0, top, x1 - x0)
    return img


def _draw_digit(img, value, x0, top, cell_w):
    """Paint the count where the game paints it, in the game's font."""
    from PIL import Image, ImageDraw, ImageFont

    from solver.live import ttr_assets

    font = ImageFont.truetype(str(ttr_assets.interface_font()), 26)
    tile = Image.new("RGB", (cell_w, ROW_H), tuple(int(c) for c in BLUE))
    draw = ImageDraw.Draw(tile)
    text = str(value)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((cell_w - (box[2] - box[0]) - 6,
               ROW_H - (box[3] - box[1]) - 20), text, font=font,
              fill=(255, 255, 255))
    img[top:top + ROW_H, x0:x0 + cell_w] = np.asarray(tile)


class FindPanelTest(unittest.TestCase):

    def test_finds_the_panel_and_its_rows(self):
        located = find_panel(panel_frame({}))
        self.assertIsNotNone(located)
        left, width, bands, height = located
        self.assertAlmostEqual(left, PANEL_X, delta=3)
        self.assertAlmostEqual(width, PANEL_W, delta=6)
        self.assertEqual(len(bands), 7)
        self.assertAlmostEqual(height, ROW_H, delta=2)

    def test_no_panel_in_an_empty_scene(self):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = SCENE
        self.assertIsNone(find_panel(img))

    def test_scattered_track_colours_are_not_a_panel(self):
        """A purple cog and a green lawn match the row colours; only a
        long unbroken run of one is a row."""
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = SCENE
        for r, (_track, colour) in enumerate(G.ROW_COLOURS):
            img[200 + r * 40:230 + r * 40, 100:180] = colour   # short blobs
        self.assertIsNone(find_panel(img))

    def test_a_partial_panel_is_rejected(self):
        """Six rows out of seven is something else on screen."""
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = SCENE
        for r, (_t, colour) in enumerate(G.ROW_COLOURS[:6]):
            top = TOP + r * ROW_H
            img[top:top + ROW_H, PANEL_X:PANEL_X + PANEL_W] = colour
        self.assertIsNone(find_panel(img))


class ReadPanelTest(unittest.TestCase):

    def read(self, counts, **kw):
        panel = read_panel(panel_frame(counts), **kw)
        self.assertIsNotNone(panel)
        return panel

    def test_reads_single_digit_counts(self):
        panel = self.read({Track.THROW: [0, 0, 0, 1, 7, 3, 1]})
        got = [c.count for c in panel.cells if c.track == Track.THROW]
        self.assertEqual(got, [0, 0, 0, 1, 7, 3, 1])

    def test_reads_two_digit_counts(self):
        """A pouch holds thirty Cupcakes, so counts pass nine."""
        panel = self.read({Track.THROW: [30, 12, 0, 0, 0, 0, 0]})
        got = [c.count for c in panel.cells if c.track == Track.THROW]
        self.assertEqual(got[:2], [30, 12])

    def test_greyed_cells_read_as_zero(self):
        panel = self.read({Track.TRAP: [0, 0, 0, 0, 7, 3, 1]})
        got = [c.count for c in panel.cells if c.track == Track.TRAP]
        self.assertEqual(got[:4], [0, 0, 0, 0])

    def test_a_blank_slot_is_not_zero(self):
        """Drop trained to 6 leaves an empty seventh cell. Calling that
        zero would tell the solver a level-7 Drop exists to be spent."""
        panel = self.read({Track.DROP: [0, 0, 0, 0, 7, 3, None]})
        cell = [c for c in panel.cells
                if c.track == Track.DROP and c.level == 7][0]
        self.assertIsNone(cell.count)
        self.assertFalse(cell.unlocked)

    def test_api_track_exp_marks_locked_levels(self):
        """Entitlement comes from the Local API, which states it, rather
        than from pixels, which cannot tell an empty cell from a greyed
        one (std 42 against 38 on a real frame)."""
        panel = self.read({Track.DROP: [0, 0, 0, 0, 7, 3, 0]},
                          track_exp={Track.DROP: 6})
        cell = [c for c in panel.cells
                if c.track == Track.DROP and c.level == 7][0]
        self.assertFalse(cell.unlocked)
        self.assertIsNone(cell.count)

    def test_counts_maps_to_gag_counts(self):
        panel = self.read({Track.SOUND: [0, 0, 0, 5, 5, 2, 1]})
        counts = panel.counts()
        self.assertEqual(counts[(Track.SOUND, 4)], 5)
        self.assertEqual(counts[(Track.SOUND, 7)], 1)
        self.assertNotIn((Track.SOUND, 1), counts)   # zeros are omitted

    def test_track_exp_uses_unlocked_not_carried(self):
        """An empty pouch still carries its accuracy bonus."""
        panel = self.read({Track.SOUND: [0, 0, 0, 0, 0, 0, 0]},
                          track_exp={Track.SOUND: 7})
        self.assertEqual(panel.track_exp()[Track.SOUND], 7)


class PouchTotalTest(unittest.TestCase):
    """Level 7 gags are carried outside the pouch."""

    def test_pouch_total_excludes_level_sevens(self):
        panel = read_panel(panel_frame({Track.THROW: [0, 0, 0, 1, 7, 3, 1]}))
        self.assertEqual(panel.total(), 12)
        self.assertEqual(panel.pouch_total(), 11)

    def test_the_menu_label_is_a_checksum_on_the_reading(self):
        """A real frame carrying 75 gags printed "Total gags 70 / 70",
        the difference being exactly its five level 7s. Agreement
        between the two is evidence no digit was misread."""
        counts = {Track.TRAP: [0, 0, 0, 0, 7, 3, 1],
                  Track.LURE: [0, 0, 0, 7, 7, 3, 1],
                  Track.SOUND: [0, 0, 0, 5, 5, 2, 1],
                  Track.THROW: [0, 0, 0, 1, 7, 3, 1],
                  Track.SQUIRT: [0, 0, 0, 0, 7, 3, 1],
                  Track.DROP: [0, 0, 0, 0, 7, 3, 0]}
        panel = read_panel(panel_frame(counts))
        self.assertEqual(panel.total(), 75)
        self.assertEqual(panel.pouch_total(), 70)


class MergeColumnsTest(unittest.TestCase):
    """Thresholding splits a digit; two digits must stay apart."""

    def test_stacked_pieces_of_one_glyph_merge(self):
        merged = G._merge_columns([(18, 6, 28, 14), (18, 13, 28, 20)])
        self.assertEqual(merged, [(18, 6, 28, 20)])

    def test_side_by_side_digits_stay_separate(self):
        merged = G._merge_columns([(4, 6, 12, 20), (14, 6, 22, 20)])
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()


class TestDarkenedTracks(unittest.TestCase):
    """The game dims a whole track when it cannot be used this round.

    Both cell tests assumed a bright cell: `B > 130` for "holds
    something", and an absolute white floor of 150 for the digit. A
    dimmed row failed both, so its gags vanished from the pouch and the
    checksum refused the state -- on a live VP panel the cells summed to
    45 against a menu label of 70, the missing 25 being the darkened
    TRAP, LURE and SOUND rows.
    """

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed")

    def _cell(self, bright, digit):
        import numpy as np
        h, w = 38, 46
        p = np.zeros((h, w, 3), dtype=np.uint8)
        p[:, :] = (int(0.25 * bright), int(0.45 * bright), bright)
        y0, x0 = int(0.45 * h), int(0.60 * w)
        p[y0 + 2:y0 + 4, x0 + 2:x0 + 12] = digit
        p[y0 + 4:y0 + 14, x0 + 8:x0 + 10] = digit
        return p

    def test_a_bright_cell_reads(self):
        from solver.live import gagpanel as gp
        from solver.state import Track
        cell = gp._read_cell(self._cell(200, 240), Track.TRAP, 5)
        self.assertTrue(cell.unlocked)
        self.assertEqual(7, cell.count)

    def test_a_darkened_cell_reads_the_same(self):
        from solver.live import gagpanel as gp
        from solver.state import Track
        cell = gp._read_cell(self._cell(90, 110), Track.TRAP, 5)
        self.assertTrue(cell.unlocked)
        self.assertEqual(7, cell.count)

    def test_a_grey_cell_is_still_empty(self):
        """Dominance, not brightness -- a grey cell has neither."""
        import numpy as np
        from solver.live import gagpanel as gp
        from solver.state import Track
        grey = np.full((38, 46, 3), 120, dtype=np.uint8)
        cell = gp._read_cell(grey, Track.TRAP, 5)
        self.assertEqual(0, cell.count)

    def test_a_dark_empty_cell_finds_no_ink(self):
        """WHITE_FLOOR_MIN stops a relative floor finding a digit in
        noise once the cell is dark enough."""
        import numpy as np
        from solver.live import gagpanel as gp
        dark = np.zeros((38, 46, 3), dtype=np.uint8)
        dark[:, :] = (10, 18, 40)
        self.assertIn(gp._read_count(dark), (None, (None, 0.0)))


class TestOrganicRowBands(unittest.TestCase):
    """An organic track's sprout badges cut its colour strip to pieces.

    `find_panel` needs all seven rows and returns None if one is short,
    so an organic track meant the menu was never found and no battle was
    ever detected -- permanently, since organic is a property of the
    track rather than of the moment. Live: organic TRAP ran 247px against
    a 288px requirement while the other six ran 862px.
    """

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed")

    def _need(self, width=1921):
        from solver.live.gagpanel import MIN_RUN_FRAC
        return int(width * MIN_RUN_FRAC)

    def test_an_unbroken_band_qualifies(self):
        import numpy as np
        from solver.live.gagpanel import _qualifies
        row = np.zeros(1921, dtype=bool)
        row[400:1262] = True
        self.assertTrue(_qualifies(row, self._need()))

    def test_a_band_broken_by_badges_qualifies(self):
        import numpy as np
        from solver.live.gagpanel import _longest_run, _qualifies
        row = np.zeros(1921, dtype=bool)
        row[400:1262] = True
        for i in range(7):
            row[500 + i * 110:518 + i * 110] = False
        self.assertLess(_longest_run(row), self._need(),
                        "fixture must fail the unbroken test")
        self.assertTrue(_qualifies(row, self._need()))

    def test_scattered_scenery_does_not(self):
        """Blobs of the right colour spanning the frame are what the
        unbroken rule existed to reject; coverage still rejects them."""
        import numpy as np
        from solver.live.gagpanel import _qualifies
        row = np.zeros(1921, dtype=bool)
        for x in range(200, 1700, 180):
            row[x:x + 30] = True
        self.assertFalse(_qualifies(row, self._need()))

    def test_a_short_solid_patch_does_not(self):
        import numpy as np
        from solver.live.gagpanel import _qualifies
        row = np.zeros(1921, dtype=bool)
        row[400:600] = True
        self.assertFalse(_qualifies(row, self._need()))
