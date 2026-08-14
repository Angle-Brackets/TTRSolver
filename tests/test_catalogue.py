"""The head-render reference library.

Signatures are built from synthesised slots rather than real captures, so
these run without a game, a screenshot, or a populated library.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np

    from solver.live.catalogue import (
        GRID, MAX_DISTANCE, MAX_UNVERIFIED_DISTANCE, HeadCatalogue, Match,
        candidates, distance, signature,
    )
    from solver.live.vision import TEAL, Plate
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"catalogue needs numpy: {exc}") from None


SLOT = (100, 100, 166, 145)


def slot_frame(head_colour=(180, 60, 50), head_width=0.3, size=(400, 300)):
    """A frame holding one plate slot with a coloured head in it."""
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :] = (70, 70, 80)
    x0, y0, x1, y1 = SLOT
    img[y0:y1, x0:x1] = TEAL
    w = x1 - x0
    half = max(1, int(w * head_width / 2))
    mid = (x0 + x1) // 2
    img[y0:y1, mid - half:mid + half] = head_colour
    return img


def plate():
    return Plate(slot=SLOT, filled=(SLOT[2] - SLOT[0]) * (SLOT[3] - SLOT[1]))


class CandidatesTest(unittest.TestCase):

    def test_department_and_level_narrow_the_field(self):
        self.assertEqual(candidates("lawbot", 9),
                         ["backstabber", "big_wig", "legal_eagle",
                          "spin_doctor"])

    def test_some_pairs_identify_a_single_cog(self):
        self.assertEqual(candidates("bossbot", 1), ["flunky"])

    def test_unknown_department_widens_to_every_cog_at_that_level(self):
        wide = candidates(None, 1)
        self.assertEqual(len(wide), 4)       # one per department
        self.assertIn("flunky", wide)

    def test_knowing_nothing_lists_everything(self):
        self.assertEqual(len(candidates(None, None)), 32)


class SignatureTest(unittest.TestCase):

    def test_signature_has_the_expected_shape(self):
        self.assertEqual(signature(slot_frame(), plate()).shape,
                         GRID + (4,))

    def test_the_teal_backdrop_is_masked_out(self):
        """Otherwise the score is dominated by how much backdrop shows,
        which says nothing about which cog it is."""
        sig = signature(slot_frame(head_width=0.3), plate())
        mask = sig[:, :, 3]
        self.assertLess(mask.mean(), 0.6)
        self.assertGreater(mask.mean(), 0.05)

    def test_the_same_cog_matches_itself(self):
        a = signature(slot_frame(), plate())
        self.assertAlmostEqual(distance(a, a), 0.0, places=6)

    def test_different_colours_are_further_apart_than_identical_ones(self):
        red = signature(slot_frame((190, 60, 50)), plate())
        red2 = signature(slot_frame((188, 62, 52)), plate())
        green = signature(slot_frame((60, 190, 90)), plate())
        self.assertLess(distance(red, red2), distance(red, green))

    def test_an_empty_slot_yields_a_blank_signature(self):
        img = np.zeros((300, 400, 3), dtype=np.uint8)
        img[:, :] = (70, 70, 80)
        x0, y0, x1, y1 = SLOT
        img[y0:y1, x0:x1] = TEAL             # all backdrop, no cog
        self.assertEqual(signature(img, plate())[:, :, 3].sum(), 0.0)


class CatalogueTest(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cat = HeadCatalogue(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_starts_empty_and_knows_what_it_is_missing(self):
        self.assertEqual(len(self.cat), 0)
        self.assertEqual(len(self.cat.missing()), 32)

    def test_adding_a_cog_makes_it_matchable(self):
        frame = slot_frame((190, 60, 50))
        self.cat.add("penny_pincher", frame, plate())
        match = self.cat.match(frame, plate())
        self.assertIsNotNone(match)
        self.assertEqual(match.cog, "penny_pincher")
        self.assertTrue(match.confident)

    def test_matching_is_restricted_to_the_candidate_pool(self):
        """The plate already ruled out most cogs; the library must not
        overrule it with a cog of the wrong department or level."""
        self.cat.add("penny_pincher", slot_frame((190, 60, 50)), plate())
        self.cat.add("flunky", slot_frame((60, 190, 90)), plate())
        match = self.cat.match(slot_frame((190, 60, 50)), plate(),
                               among=["flunky"])
        self.assertEqual(match.cog, "flunky")

    def test_matching_an_empty_pool_returns_nothing(self):
        self.assertIsNone(self.cat.match(slot_frame(), plate(), among=[]))

    def test_an_unlearned_cog_is_not_confidently_matched(self):
        self.cat.add("penny_pincher", slot_frame((190, 60, 50)), plate())
        match = self.cat.match(slot_frame((60, 190, 90)), plate())
        self.assertFalse(match.confident)

    def test_unknown_cog_keys_are_refused(self):
        with self.assertRaises(KeyError):
            self.cat.add("not_a_cog", slot_frame(), plate())

    def test_entries_survive_a_reload(self):
        self.cat.add("penny_pincher", slot_frame((190, 60, 50)), plate())
        reopened = HeadCatalogue(self.dir)
        self.assertEqual(len(reopened), 1)
        match = reopened.match(slot_frame((190, 60, 50)), plate())
        self.assertEqual(match.cog, "penny_pincher")

    def test_a_crop_is_kept_so_a_bad_label_can_be_seen(self):
        self.cat.add("penny_pincher", slot_frame(), plate())
        self.assertTrue((self.dir / "penny_pincher.png").is_file())


if __name__ == "__main__":
    unittest.main()


class UnverifiedMatchTest(unittest.TestCase):
    """A match that beat nothing is a different claim from one that won.

    The library fills one cog at a time, so for a long while every pool
    holds exactly one known candidate. With no runner-up the margin is
    infinity, which satisfies any margin test trivially -- so a single
    Spin Doctor entry made every Lawbot of level 6-10 match it at full
    confidence, whatever it actually looked like.
    """

    def test_a_lone_close_match_is_accepted(self):
        m = Match("yesman", 0.028)
        self.assertIsNone(m.runner_up)
        self.assertTrue(m.confident)

    def test_a_lone_distant_match_is_not(self):
        """0.147 is what a WRONG cog scores. It clears MAX_DISTANCE at
        0.22, which is why the distance check alone was not enough."""
        self.assertLess(0.147, MAX_DISTANCE)
        self.assertFalse(Match("yesman", 0.147).confident)

    def test_the_margin_rule_still_applies_when_there_is_a_runner_up(self):
        close = Match("yesman", 0.10, "downsizer", 0.11)
        self.assertFalse(close.confident)      # margin 0.01, too near
        clear = Match("yesman", 0.10, "downsizer", 0.20)
        self.assertTrue(clear.confident)

    def test_the_unverified_bar_sits_between_right_and_wrong(self):
        self.assertGreater(MAX_UNVERIFIED_DISTANCE, 0.028)
        self.assertLess(MAX_UNVERIFIED_DISTANCE, 0.132)
