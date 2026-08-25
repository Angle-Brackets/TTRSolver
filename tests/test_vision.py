"""Finding cog plates in a rendered frame.

Frames are synthesised rather than loaded from a screenshot: it keeps the
suite free of a megabyte of someone's toon, and it allows testing the
cases that are awkward to capture on purpose -- a cog whose head splits
its own backdrop, a damaged meter, a 4K frame.
"""
import unittest

try:
    import numpy as np

    from solver.live import vision as V
    from solver.live.vision import (
        PARTS, Plate, TEAL, find_plates, health_fraction,
    )
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"vision needs numpy: {exc}") from None

PLATE_BG = (170, 170, 165)      # brushed metal
SCENE_BG = (96, 92, 120)        # cobblestone-ish


def frame(slots, size=(1920, 1080), head=None, health=1.0):
    """A frame with `slots` cog plates drawn at (x, y, w, h).

    `head` optionally paints a vertical bar of the cog's head across the
    middle of each slot, reproducing the case where the render splits its
    own teal backdrop into two disconnected pieces.
    """
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :] = SCENE_BG
    for x, y, w, h in slots:
        img[y - h // 3:y + 2 * h, x - w // 4:x + 3 * w] = PLATE_BG
        img[y:y + h, x:x + w] = TEAL
        if head:
            hw = max(1, int(w * head))
            img[y:y + h, x + w // 2 - hw // 2:x + w // 2 + hw // 2] = (
                150, 45, 40)
        plate = Plate(slot=(x, y, x + w, y + h), filled=w * h)
        bx0, by0, bx1, by1 = plate.region("health")
        img[by0:by1, bx0:bx1] = (20, 20, 20)
        lit = bx0 + int((bx1 - bx0) * health)
        img[by0:by1, bx0:lit] = (0, 254, 0)
    return img


class FindPlatesTest(unittest.TestCase):

    def test_finds_a_single_plate(self):
        plates = find_plates(frame([(700, 120, 66, 45)]))
        self.assertEqual(len(plates), 1)
        self.assertEqual(plates[0].slot, (700, 120, 766, 165))

    def test_finds_four_plates_left_to_right(self):
        xs = [400, 700, 1000, 1300]
        plates = find_plates(frame([(x, 120, 66, 45) for x in xs]))
        self.assertEqual([p.slot[0] for p in plates], xs)

    def test_a_head_splitting_the_backdrop_is_still_one_plate(self):
        """The cog is drawn over its own teal, cutting it in two. Treating
        each piece as a separate blob loses the plate entirely once the
        fragments fall under the area floor."""
        plates = find_plates(frame([(700, 120, 66, 45)], head=0.35))
        self.assertEqual(len(plates), 1)
        self.assertEqual(plates[0].slot, (700, 120, 766, 165))

    def test_empty_scene_finds_nothing(self):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = SCENE_BG
        self.assertEqual(find_plates(img), [])

    def test_a_teal_smudge_of_the_wrong_shape_is_rejected(self):
        """Aspect ratio is what separates a slot from stray scenery."""
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :] = SCENE_BG
        img[300:700, 300:360] = TEAL         # tall and thin
        self.assertEqual(find_plates(img), [])


class ResolutionTest(unittest.TestCase):
    """Nothing may be tuned to 1080p."""

    CASES = [((854, 480), 30, 20), ((1280, 720), 44, 29),
             ((1920, 1080), 66, 45), ((2560, 1440), 88, 60),
             ((3840, 2160), 131, 89)]

    def test_plates_are_found_at_every_resolution(self):
        for size, w, h in self.CASES:
            with self.subTest(size=size):
                x, y = size[0] // 3, size[1] // 8
                plates = find_plates(frame([(x, y, w, h)], size=size))
                self.assertEqual(len(plates), 1)
                self.assertEqual(plates[0].width, w)

    def test_split_backdrop_survives_every_resolution(self):
        for size, w, h in self.CASES:
            with self.subTest(size=size):
                x, y = size[0] // 3, size[1] // 8
                plates = find_plates(
                    frame([(x, y, w, h)], size=size, head=0.35))
                self.assertEqual(len(plates), 1)


class RegionTest(unittest.TestCase):

    def test_regions_scale_with_the_plate(self):
        """A plate drawn twice as large must yield regions twice as large.

        Not exactly 2.0: the regions are ~20px tall at 1080p, so rounding
        each edge to a whole pixel moves the ratio by a few percent. The
        tolerance is that quantisation and nothing more -- a genuine
        scaling error would be far larger.
        """
        small = Plate(slot=(100, 100, 166, 145), filled=0)
        large = Plate(slot=(100, 100, 232, 190), filled=0)
        for part in PARTS:
            with self.subTest(part=part):
                sx0, sy0, sx1, sy1 = small.region(part)
                lx0, ly0, lx1, ly1 = large.region(part)
                self.assertAlmostEqual((lx1 - lx0) / (sx1 - sx0), 2.0,
                                       delta=0.1)
                self.assertAlmostEqual((ly1 - ly0) / (sy1 - sy0), 2.0,
                                       delta=0.1)

    def test_unknown_region_names_raise(self):
        with self.assertRaises(KeyError):
            Plate(slot=(0, 0, 66, 45), filled=0).region("nose")


class TextIsolationTest(unittest.TestCase):
    """The two ways reading "Level N" went wrong on real frames.

    Both are hermetic: they exercise the mask handling, not the font, so
    they run without a Toontown installation.
    """

    @staticmethod
    def letters(gaps=(2, 2, 2, 2), width=6, height=10, top=2):
        """A row of blobs standing in for "Level", plus a digit."""
        total = width * (len(gaps) + 2) + sum(gaps) + 8
        mask = np.zeros((height + top + 4, total), dtype=bool)
        x = 0
        for gap in list(gaps) + [8]:
            mask[top:top + height, x:x + width] = True
            x += width + gap
        mask[top:top + height, x:x + width] = True
        return mask

    def test_a_speck_does_not_stretch_the_ink_box(self):
        """One stray pixel below the text turned an 18px-tall "Level 6"
        into a 32px box, shrinking the glyphs against the templates and
        dropping the correct answer to IoU 0.08."""
        mask = self.letters()
        tall = np.zeros((mask.shape[0] + 12, mask.shape[1]), dtype=bool)
        tall[:mask.shape[0]] = mask
        tall[-1, -1] = True                        # the speck
        cleaned = V._denoise(tall)
        self.assertFalse(cleaned[-1, -1])
        self.assertTrue(cleaned[2:12, 0:6].any())  # text survives

    def test_the_widest_gap_splits_word_from_number(self):
        digits = V._digits_only(self.letters())
        self.assertIsNotNone(digits)
        self.assertEqual(digits.shape[1], 6)       # just the last blob

    def test_a_full_height_border_does_not_steal_the_digit(self):
        """The level region reaches the plate's edge, which thresholds as
        a thin full-height bar. Being rightmost, it was being taken for
        the number: at 1440p a 4x40 sliver beat the real '8'."""
        mask = self.letters()
        # Real borders measured 1.74x and 2.6x the glyph height; 2.0x
        # here rather than a value sitting exactly on the threshold.
        tall = mask.shape[0] + 4
        wide = np.zeros((tall, mask.shape[1] + 14), dtype=bool)
        wide[:mask.shape[0], :mask.shape[1]] = mask
        wide[:, -3:] = True                        # plate border
        digits = V._digits_only(wide)
        self.assertIsNotNone(digits)
        self.assertEqual(digits.shape[1], 6)       # the digit, not the bar
        self.assertLess(digits.shape[0], tall)

    def test_text_with_no_word_break_reads_as_nothing(self):
        even = self.letters(gaps=(2, 2, 2, 2))
        even = even[:, :even.shape[1] - 8]         # drop the wide gap
        self.assertIsNone(V._digits_only(even))


class HealthTest(unittest.TestCase):

    def read(self, health):
        img = frame([(700, 120, 66, 45)], health=health)
        return health_fraction(img, find_plates(img)[0])

    def test_a_full_bar_reads_full(self):
        """A hand-drawn box around the meter read a full bar as 83%,
        which would have corrupted every use of this."""
        self.assertGreater(self.read(1.0), 0.97)

    def test_an_empty_bar_reads_empty(self):
        self.assertEqual(self.read(0.0), 0.0)

    def test_partial_bars_track_the_fill(self):
        for want in (0.25, 0.5, 0.75):
            with self.subTest(want=want):
                self.assertAlmostEqual(self.read(want), want, delta=0.03)


if __name__ == "__main__":
    unittest.main()


class PlateSizeCeilingTest(unittest.TestCase):
    """A plate is small. Large teal scenery is not a plate.

    The minimum-size and aspect filters both pass on big background
    geometry: a grey-blue machine on a Lullaby Lane street matched as a
    629x391 blob at aspect 1.61, in a frame whose real plates were 69x47
    and 65x45. It read as a third cog with an unreadable level and 0%
    health, which blocked the whole battle.
    """

    def test_a_huge_teal_region_is_not_a_plate(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[:, :] = (70, 70, 80)
        # 620x385: the shape that fooled it, aspect 1.61.
        frame[100:485, 1200:1820] = V.TEAL
        self.assertEqual(V.find_plates(frame), [])

    def test_a_plate_sized_region_still_is(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[:, :] = (70, 70, 80)
        frame[100:145, 600:666] = V.TEAL
        self.assertEqual(len(V.find_plates(frame)), 1)

    def test_the_ceiling_leaves_room_for_a_closer_camera(self):
        """Real plates measure 3.4-3.6% of frame width; the ceiling is
        more than three times that, so a genuine plate may be much
        nearer than any yet captured and still be found."""
        self.assertGreater(V.MAX_SLOT_WIDTH_FRAC, 0.036 * 3)


class OverlapAlignmentTest(unittest.TestCase):
    """Template matching compares centred masks, not top-left ones.

    A glyph 13 pixels wide against a 15-pixel template, both pinned to
    the top left, is offset by two -- and these glyphs are 13 to 18
    pixels tall, so two pixels is most of a stroke. It read as a
    template problem and was an alignment problem: a plate saying
    "Level 8" scored 6 at 0.701 over 8 at 0.689, on two separate frames.
    """

    def test_a_shifted_copy_of_a_shape_still_matches_itself(self):
        small = np.zeros((10, 6), bool)
        small[2:8, 1:5] = True
        wide = np.zeros((10, 10), bool)
        wide[2:8, 3:7] = True             # same blob, centred in a wider box
        self.assertGreater(V._overlap(small, wide), 0.9)

    def test_identical_masks_are_still_one(self):
        m = np.zeros((8, 5), bool)
        m[1:7, 1:4] = True
        self.assertAlmostEqual(V._overlap(m, m), 1.0)

    def test_disjoint_masks_are_still_zero(self):
        a = np.zeros((8, 8), bool); a[0:2, 0:2] = True
        b = np.zeros((8, 8), bool); b[6:8, 6:8] = True
        self.assertEqual(V._overlap(a, b), 0.0)

    def test_empty_masks_do_not_divide_by_zero(self):
        z = np.zeros((4, 4), bool)
        self.assertEqual(V._overlap(z, z), 0.0)


class TestPlatesAtTheFrameEdge(unittest.TestCase):
    """A blob running into the border is not a cog plate."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed")

    def _frame(self):
        import numpy as np
        return np.zeros((1081, 1921, 3), dtype=np.uint8)

    def test_a_blob_touching_the_top_edge_is_rejected(self):
        """Measured live: a 58x48 box at (793, 0) passed every size and
        aspect test, read level score 0.00 and 0% health, and displaced a
        real plate in the panel."""
        from solver.live.vision import find_plates
        frame = self._frame()
        frame[0:48, 793:851] = (60, 140, 150)
        self.assertEqual([], find_plates(frame))

    def test_a_free_floating_plate_is_kept(self):
        from solver.live.vision import find_plates
        frame = self._frame()
        frame[300:347, 741:810] = (60, 140, 150)
        self.assertEqual(1, len(find_plates(frame)))

    def test_the_other_three_edges_too(self):
        from solver.live.vision import find_plates
        import numpy as np
        for name, box in (("left", (np.s_[300:347], np.s_[0:69])),
                          ("right", (np.s_[300:347], np.s_[1852:1921])),
                          ("bottom", (np.s_[1034:1081], np.s_[741:810]))):
            frame = self._frame()
            frame[box[0], box[1]] = (60, 140, 150)
            self.assertEqual([], find_plates(frame), f"{name} edge")


class TestLureIndicator(unittest.TestCase):
    """The red tile the game floats above a lured cog's plate."""

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed")

    def _plate(self):
        from solver.live.vision import Plate
        return Plate(slot=(877, 119, 947, 166), filled=1500)

    def _frame(self):
        import numpy as np
        return np.zeros((1081, 1921, 3), dtype=np.uint8)

    def test_absent_on_an_empty_frame(self):
        from solver.live.vision import lure_indicator
        self.assertFalse(lure_indicator(self._frame(), self._plate()))

    def test_found_when_the_tile_is_there(self):
        from solver.live.vision import lure_indicator
        plate, frame = self._plate(), self._frame()
        x0, y0, _x1, _y1 = plate.region("lure")
        frame[y0 + 5:y0 + 25, x0 + 5:x0 + 45] = (220, 40, 40)
        self.assertTrue(lure_indicator(frame, plate))

    def test_the_region_sits_above_the_plate(self):
        """Negative offsets: the tile floats over the sign, not on it."""
        plate = self._plate()
        _lx0, ly0, _lx1, ly1 = plate.region("lure")
        self.assertLess(ly1, plate.slot[1])

    def test_a_stray_red_highlight_is_not_enough(self):
        from solver.live.vision import lure_indicator
        plate, frame = self._plate(), self._frame()
        x0, y0, _x1, _y1 = plate.region("lure")
        frame[y0 + 5:y0 + 7, x0 + 5:x0 + 8] = (220, 40, 40)
        self.assertFalse(lure_indicator(frame, plate))

    def test_the_health_bar_green_does_not_trigger_it(self):
        """The bar is bright and saturated but not red, and it is below
        the plate rather than above it."""
        from solver.live.vision import lure_indicator
        plate, frame = self._plate(), self._frame()
        hx0, hy0, hx1, hy1 = plate.region("health")
        frame[hy0:hy1, hx0:hx1] = (40, 220, 60)
        self.assertFalse(lure_indicator(frame, plate))


class TestTealUnderASceneTint(unittest.TestCase):
    """Lawbot HQ lights its courtroom sepia and the mask stopped seeing
    plates -- not one candidate, with a cog in plain view.

    An absolute box around a sampled colour cannot survive the game
    recolouring a whole scene. Channel ORDER can: a tint moves all three
    together and leaves blue leading green leading red.
    """

    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is not installed")

    def test_the_untinted_colour_matches(self):
        import numpy as np
        from solver.live.vision import TEAL, teal_mask
        frame = np.full((4, 4, 3), TEAL, dtype=np.uint8)
        self.assertTrue(teal_mask(frame).all())

    def test_a_shifted_slot_the_old_box_rejects_still_matches(self):
        """The box is +/-34 per channel around one sampled colour. A
        scene lit differently moves every channel past that while leaving
        blue over green over red intact, which is what the relational
        clause is for."""
        import numpy as np
        from solver.live.vision import TEAL, TOLERANCE, teal_mask
        shifted = (TEAL[0] - 36, TEAL[1] - 20, TEAL[2] - 20)
        boxed = all(abs(a - b) < TOLERANCE for a, b in zip(shifted, TEAL))
        self.assertFalse(boxed, "fixture must fall outside the old box")
        frame = np.full((4, 4, 3), shifted, dtype=np.uint8)
        self.assertTrue(teal_mask(frame).all())

    def test_brown_is_not_teal(self):
        import numpy as np
        from solver.live.vision import teal_mask
        frame = np.full((4, 4, 3), (150, 110, 70), dtype=np.uint8)
        self.assertFalse(teal_mask(frame).any())

    def test_a_dark_blue_shadow_is_not_teal(self):
        """The lightness band keeps the relational clause off shadows,
        where the leads are meaningless."""
        import numpy as np
        from solver.live.vision import teal_mask
        frame = np.full((4, 4, 3), (5, 30, 60), dtype=np.uint8)
        self.assertFalse(teal_mask(frame).any())
