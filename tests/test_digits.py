"""The learned digit reader and the count cropping it relies on.

No game frames here (the project keeps game images out of the repo):
glyphs are drawn with PIL's own default font or as plain arrays.
"""
import unittest

try:
    import numpy as np
    from solver.live import digits, gagpanel as gp
    HAVE = True
except ImportError:                       # numpy is an optional extra
    HAVE = False


@unittest.skipUnless(HAVE, "needs numpy")
class OtsuTest(unittest.TestCase):

    def test_splits_two_clusters(self):
        v = np.array([10] * 50 + [240] * 50)
        t = digits.otsu(v)
        self.assertTrue(10 <= t < 240)


@unittest.skipUnless(HAVE, "needs numpy")
class GlyphVectorTest(unittest.TestCase):

    def test_fixed_width_whatever_the_glyph(self):
        for shape in ((14, 9), (30, 4), (8, 20)):
            v = digits.glyph_vector(np.random.default_rng(0).random(shape))
            self.assertEqual(digits.GLYPH_H * digits.GLYPH_W + 1, v.shape[0])


@unittest.skipUnless(HAVE, "needs numpy")
class ShippedWeightsTest(unittest.TestCase):

    def test_they_load(self):
        self.assertIsNotNone(digits.count_classifier())

    def test_a_drawn_digit_is_read(self):
        """A clean "7" drawn with PIL's own font, cut by the live cropping."""
        from PIL import Image, ImageDraw, ImageFont

        try:
            font = ImageFont.load_default(size=40)
        except TypeError:                 # older Pillow: fixed-size default
            self.skipTest("Pillow too old for a sized default font")
        img = Image.new("RGB", (60, 60), (30, 140, 230))
        ImageDraw.Draw(img).text((32, 6), "7", font=font, fill=(250, 250, 250))
        glyphs = gp._count_glyphs(np.asarray(img).astype(np.int16), region=(0, 0, 1, 1))
        self.assertEqual(1, len(glyphs))
        digit, margin = digits.count_classifier().classify(glyphs[0][1])
        self.assertEqual(7, digit)


@unittest.skipUnless(HAVE, "needs numpy")
class CountCroppingTest(unittest.TestCase):

    def _corner(self, blocks, size=(40, 40), base=(30, 140, 230)):
        a = np.zeros(size + (3,), dtype=np.int16) + np.array(base, dtype=np.int16)
        for x0, y0, x1, y1 in blocks:
            a[y0:y1, x0:x1] = 250
        return a

    def test_a_bright_icon_streak_left_of_the_count_is_dropped(self):
        """A Fog Horn highlight read as extra "1"s, turning 1 into 111."""
        streak = (6, 2, 8, 14)            # thin, high, far left
        digit = (28, 8, 33, 24)           # the count, at the right
        glyphs = gp._count_glyphs(self._corner([streak, digit]), region=(0, 0, 1, 1))
        self.assertEqual(1, len(glyphs))

    def test_two_digit_counts_keep_both_glyphs(self):
        glyphs = gp._count_glyphs(self._corner([(18, 8, 23, 24), (26, 8, 31, 24)]),
                                  region=(0, 0, 1, 1))
        self.assertEqual(2, len(glyphs))

    def test_blue_bleed_does_not_erase_a_white_stroke(self):
        """Video colour bleed tints thin white strokes blue; brightness,
        not colourlessness, decides ink."""
        a = self._corner([])
        a[8:24, 28:33] = (205, 225, 255)  # bright but tinted
        self.assertEqual(1, len(gp._count_glyphs(a, region=(0, 0, 1, 1))))


@unittest.skipUnless(HAVE, "needs numpy")
class LevelGlyphsTest(unittest.TestCase):
    """The plate's number, cut from "Level N" and read."""

    def _plate(self, text, size=22):
        from PIL import Image, ImageDraw, ImageFont

        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            self.skipTest("Pillow too old for a sized default font")
        img = Image.new("RGB", (120, 44), (200, 200, 205))
        ImageDraw.Draw(img).text((2, 8), text, font=font, fill=(25, 25, 30))
        return np.asarray(img).astype(np.int16)

    def test_one_digit_level_gives_one_glyph(self):
        self.assertEqual(1, len(V.level_glyphs(self._plate("Level 6"))))

    def test_two_digit_level_gives_two_glyphs(self):
        self.assertEqual(2, len(V.level_glyphs(self._plate("Level 12"))))

    def test_the_plates_frame_is_not_a_digit(self):
        a = self._plate("Level 5").copy()
        a[:, -4:-1] = 40                      # the frame, full height
        self.assertEqual(1, len(V.level_glyphs(a)))

    def test_the_shipped_level_weights_load(self):
        self.assertIsNotNone(digits.level_classifier())


try:
    from solver.live import vision as V
except ImportError:                           # pragma: no cover
    V = None
