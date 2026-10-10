"""The three implementations of a round agree.

`outcomes.action_outcomes` (the Search row), `simulator.step` (solo) and
`party.step` (the playouts) each resolve a round. A rule added to one
and not the others is invisible to every test of that one path: Cogs
Miss once did nothing in a party and nothing in exact search, and the
party round capped Realms' certain hit back to 95. This holds them
against each other on random positions, fixed seeds, so it is exact
rather than flaky. `tools/round_parity.py` runs the full-size check.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


class RoundParityTest(unittest.TestCase):

    def test_exact_solo_and_party_agree(self):
        import round_parity

        round_parity.SAMPLES = 300
        checked, flags = round_parity.check(25, seed=11)
        self.assertGreater(checked, 30)
        self.assertEqual({}, dict(flags))


if __name__ == "__main__":
    unittest.main()
