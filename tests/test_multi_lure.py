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


class MagnitudeTest(unittest.TestCase):
    """[ASSUMED], not [CONFIRMED] -- the owner authorised filling this
    in on the balance of evidence after reading the v4.0.0 notes. No
    source states which gap selects which of 20/15/10; mapping them onto
    gaps 0, 1 and 2+ is the only assignment consistent with all three
    statements about it, and it is still an inference.

    If measurement contradicts it, change the table and nothing else.
    """

    def test_equal_levels_pay_most(self):
        self.assertEqual(mechanics.multi_lure_bonus([6, 6]), 20)

    def test_one_apart_pays_the_middle_value(self):
        self.assertEqual(mechanics.multi_lure_bonus([7, 6]), 15)

    def test_two_apart_falls_to_the_default(self):
        # 6 and 4 are both group gags, so eligible, but two apart.
        self.assertEqual(mechanics.multi_lure_bonus([6, 4]), 10)

    def test_a_wide_gap_pays_least(self):
        self.assertEqual(mechanics.multi_lure_bonus([7, 2]), 10)

    def test_a_lone_lure_earns_nothing(self):
        self.assertEqual(mechanics.multi_lure_bonus([6]), 0)
        self.assertEqual(mechanics.multi_lure_bonus([]), 0)

    def test_ineligible_pairs_earn_nothing_however_close(self):
        """A group Lure beside a Bill, which the notes rule out."""
        self.assertEqual(mechanics.multi_lure_bonus([5, 4]), 0)


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
