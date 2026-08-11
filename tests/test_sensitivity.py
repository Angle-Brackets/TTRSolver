"""The accuracy sweep has to actually perturb something.

This was silently broken for a while: the perturbation still spoke the old
nested-dict shape after the data became frozen objects, so it raised on
every call and no test noticed. The failure mode if it had *not* raised is
worse -- a sweep that reports a perfectly flat, perfectly plausible,
entirely wrong "the answer never changes".

So these check the machinery moves numbers and puts them back, not just
that it runs.

stdlib unittest only -- pytest is not installed.
"""
import unittest

from solver import data, outcomes
from solver.search import demo, expectimax, sensitivity
from solver.state import CogState


def flunky_row():
    return data.cog("bossbot", "flunky").attack("pound_key").accuracy


class TestPerturbation(unittest.TestCase):
    def test_shifts_every_cell_and_restores(self):
        before = flunky_row()
        with sensitivity.perturbed_cog_accuracy(-20):
            self.assertEqual(flunky_row(),
                             tuple(v - 20 for v in before))
        self.assertEqual(flunky_row(), before)

    def test_clamps_to_0_100(self):
        with sensitivity.perturbed_cog_accuracy(60):
            self.assertTrue(all(v <= 100 for v in flunky_row()))
        with sensitivity.perturbed_cog_accuracy(-200):
            self.assertTrue(all(v >= 0 for v in flunky_row()))

    def test_leaves_todo_cells_alone(self):
        """A gap must stay a gap; shifting None into a number would invent
        exactly the value the project refuses to invent."""
        with sensitivity.perturbed_cog_accuracy(30):
            row = data.cog("bossbot", "the_big_cheese").attack(
                "glower_power").accuracy
            self.assertTrue(all(v is None for v in row))

    def test_both_registry_bindings_move(self):
        """data.cogs owns the dict, data/__init__ re-exports it, and callers
        use either -- patching one and not the other half-applies."""
        with sensitivity.perturbed_cog_accuracy(-10):
            from solver.data import cogs as cogs_mod
            self.assertIs(data.COG_DEPARTMENTS, cogs_mod.COG_DEPARTMENTS)
            self.assertEqual(
                cogs_mod.COG_DEPARTMENTS["bossbot"]["flunky"]
                .attack("pound_key").accuracy, flunky_row())

    def test_the_outcome_cache_is_invalidated(self):
        """outcomes caches attack distributions by (dept, type, level); a
        stale cache would make the whole sweep read flat."""
        cog = CogState(cog_type="flunky", department="bossbot", level=4,
                       hp=30, max_hp=30)
        base = outcomes.cog_damage_distribution(cog)
        with sensitivity.perturbed_cog_accuracy(-20):
            shifted = outcomes.cog_damage_distribution(cog)
        self.assertNotEqual(base, shifted,
                            "perturbation did not reach the cached path")
        self.assertEqual(outcomes.cog_damage_distribution(cog), base)

    def test_zero_offset_round_trips(self):
        before = flunky_row()
        with sensitivity.perturbed_cog_accuracy(0):
            self.assertEqual(flunky_row(), before)
        self.assertEqual(flunky_row(), before)


class TestSweep(unittest.TestCase):
    def test_policy_stability_reports_one_row_per_offset(self):
        report = sensitivity.policy_stability("default", 1, (-20, 0, 20), 0)
        self.assertEqual([r["offset"] for r in report["rows"]], [-20, 0, 20])
        self.assertGreater(report["states"], 0)
        for row in report["rows"]:
            self.assertLessEqual(row["agree"], row["total"])

    def test_baseline_agrees_with_itself(self):
        """Offset 0 still round-trips the tables, so a bug in the
        perturbation shows up here as the baseline disagreeing with
        itself."""
        report = sensitivity.policy_stability("default", 1, (0,), 0)
        row = report["rows"][0]
        self.assertEqual(row["agree"], row["total"])


if __name__ == "__main__":
    unittest.main()
