"""Which pairs of Lures earn the Lure Bonus.

[CONFIRMED] TTR v4.0.0 patch notes. Eligibility only -- the magnitude
is `mechanics.MULTI_LURE_ACCURACY_BONUS`, still [TODO], so nothing
consumes this in the accuracy path yet.
"""
import unittest

from solver import mechanics


class EligibilityTest(unittest.TestCase):
    """Bills are levels 1, 3, 5; group Lures are 2, 4, 6, 7."""

    def test_two_group_lures_qualify(self):
        self.assertTrue(mechanics.multi_lure_eligible(4, 6))
        self.assertTrue(mechanics.multi_lure_eligible(2, 7))

    def test_two_dollar_bills_qualify(self):
        self.assertTrue(mechanics.multi_lure_eligible(1, 5))
        self.assertTrue(mechanics.multi_lure_eligible(3, 3))

    def test_a_group_lure_beside_a_bill_does_not(self):
        """The case the notes call out explicitly."""
        self.assertFalse(mechanics.multi_lure_eligible(4, 5))
        self.assertFalse(mechanics.multi_lure_eligible(1, 6))

    def test_the_magnitude_is_still_unknown(self):
        """A guard: if someone fills this in, they must also revisit
        every [TODO] note explaining why it was None."""
        self.assertIsNone(mechanics.MULTI_LURE_ACCURACY_BONUS)


class OrganicShiftTest(unittest.TestCase):
    """"Organic Lure now shifts the base accuracy of Lure by an
    additional 10% rather than being an additive bonus during the
    battle calculation." The model already did this; now it is cited.

    It matters beyond accuracy: the notes say the shift "better
    determines who the overriding Lure Gag is", so it feeds the
    highest-accuracy-wins rule for simultaneous Lures.
    """

    def test_organic_shifts_every_lure_by_ten(self):
        from solver import data
        from solver.state import Track

        for gag in data.gags_in(Track.LURE):
            self.assertEqual(
                gag.prop_accuracy(organic=True)
                - gag.prop_accuracy(organic=False), 10,
                f"level {gag.level} organic shift is not +10")


if __name__ == "__main__":
    unittest.main()
