"""Structural invariants for the cog attack tables in solver/data/.

These are the invariants solver.mechanics relies on when it does
    table["freq"][attack_name][cog.level - table["levels"][0]]
and then indexes "damage"/"accuracy" with the same key and offset. If any
of them break, the simulator KeyErrors, IndexErrors, or -- worse -- reads a
number that belongs to a different attack.

Deliberate per-cell gaps (a None inside an otherwise-filled list) are
allowed by design: they mark a value the source guide doesn't give
unambiguously, and the ground rule is to leave them blank rather than
guess. test_no_unexpected_todo_cells pins the exact inventory of them so a
new one can't appear unnoticed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver.data import COG_DEPARTMENTS  # noqa: E402


# Every per-cell [TODO] currently in the data, as (department, cog, section,
# attack). Each one is explained by a comment in its module.
KNOWN_TODO_CELLS = {
    ("bossbot", "micromanager", "accuracy", "brain_storm"),
    ("bossbot", "the_big_cheese", "damage", "glower_power"),
    ("bossbot", "the_big_cheese", "accuracy", "glower_power"),
}

SECTIONS = ("freq", "damage", "accuracy")


def all_cogs():
    for dept, cogs in sorted(COG_DEPARTMENTS.items()):
        for cog, table in sorted(cogs.items()):
            yield dept, cog, table


class TestCogTableShape(unittest.TestCase):
    def test_departments_present(self):
        self.assertEqual(
            set(COG_DEPARTMENTS),
            {"bossbot", "cashbot", "lawbot", "sellbot"},
        )
        for dept, cogs in COG_DEPARTMENTS.items():
            with self.subTest(dept=dept):
                self.assertEqual(len(cogs), 8, f"{dept} should have 8 cogs")

    def test_required_fields(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                for field in ("levels", "freq", "damage", "accuracy", "group_attacks"):
                    self.assertIn(field, table)
                self.assertIsInstance(table["levels"], list)
                self.assertTrue(table["levels"])
                self.assertIsInstance(table["group_attacks"], set)

    def test_levels_are_contiguous_ascending(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                levels = table["levels"]
                self.assertEqual(
                    levels, list(range(levels[0], levels[0] + len(levels))),
                    f"{dept}/{cog} levels must be contiguous ascending "
                    f"for (level - levels[0]) indexing to work",
                )

    def test_key_sets_match_across_sections(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                freq_keys = set(table["freq"])
                self.assertTrue(freq_keys, f"{dept}/{cog} has no attacks")
                self.assertEqual(freq_keys, set(table["damage"]),
                                 f"{dept}/{cog}: freq vs damage keys differ")
                self.assertEqual(freq_keys, set(table["accuracy"]),
                                 f"{dept}/{cog}: freq vs accuracy keys differ")

    def test_group_attacks_are_known_attacks(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                self.assertLessEqual(
                    table["group_attacks"], set(table["freq"]),
                    f"{dept}/{cog}: group_attacks names an attack that has no "
                    f"freq entry",
                )

    def test_list_lengths_match_levels(self):
        for dept, cog, table in all_cogs():
            n = len(table["levels"])
            for section in SECTIONS:
                for attack, values in table[section].items():
                    with self.subTest(dept=dept, cog=cog, section=section, attack=attack):
                        self.assertIsInstance(values, list)
                        self.assertEqual(
                            len(values), n,
                            f"{dept}/{cog}/{section}/{attack} has {len(values)} "
                            f"entries but {n} levels",
                        )

    def test_attack_keys_are_snake_case(self):
        for dept, cog, table in all_cogs():
            for attack in table["freq"]:
                with self.subTest(dept=dept, cog=cog, attack=attack):
                    self.assertRegex(attack, r"^[a-z0-9]+(_[a-z0-9]+)*$")


class TestCogTableValues(unittest.TestCase):
    def test_frequencies_are_complete_and_sum_to_100(self):
        """Frequencies drive mechanics.pick_cog_attack's cumulative sample.
        A level that doesn't total 100 silently biases the last attack, so
        no None is tolerated here and every level must total exactly 100."""
        bad = []
        for dept, cog, table in all_cogs():
            for i, level in enumerate(table["levels"]):
                values = [table["freq"][a][i] for a in table["freq"]]
                if any(v is None for v in values):
                    bad.append(f"{dept}/{cog} level {level}: freq has a None cell")
                    continue
                total = sum(values)
                if total != 100:
                    bad.append(f"{dept}/{cog} level {level}: freq sums to {total}, not 100")
        self.assertEqual(bad, [], "frequency totals are off:\n  " + "\n  ".join(bad))

    def test_frequencies_are_non_negative_ints(self):
        for dept, cog, table in all_cogs():
            for attack, values in table["freq"].items():
                for level, v in zip(table["levels"], values):
                    with self.subTest(dept=dept, cog=cog, attack=attack, level=level):
                        self.assertIsInstance(v, int)
                        self.assertGreaterEqual(v, 0)

    def test_accuracy_within_0_100(self):
        for dept, cog, table in all_cogs():
            for attack, values in table["accuracy"].items():
                for level, v in zip(table["levels"], values):
                    if v is None:
                        continue  # deliberate [TODO]; see KNOWN_TODO_CELLS
                    with self.subTest(dept=dept, cog=cog, attack=attack, level=level):
                        self.assertIsInstance(v, int)
                        self.assertGreaterEqual(v, 0)
                        self.assertLessEqual(v, 100)

    def test_damage_is_positive_int_or_min_max_pair(self):
        for dept, cog, table in all_cogs():
            for attack, values in table["damage"].items():
                for level, v in zip(table["levels"], values):
                    if v is None:
                        continue  # deliberate [TODO]; see KNOWN_TODO_CELLS
                    with self.subTest(dept=dept, cog=cog, attack=attack, level=level):
                        if isinstance(v, tuple):
                            self.assertEqual(len(v), 2)
                            self.assertLessEqual(v[0], v[1])
                            self.assertGreater(v[0], 0)
                        else:
                            self.assertIsInstance(v, int)
                            self.assertGreater(v, 0)

    def test_no_unexpected_todo_cells(self):
        """A None cell is a deliberate, documented gap -- never a typo. Any
        new one has to be added to KNOWN_TODO_CELLS on purpose."""
        found = set()
        for dept, cog, table in all_cogs():
            for section in SECTIONS:
                for attack, values in table[section].items():
                    if any(v is None for v in values):
                        found.add((dept, cog, section, attack))
        self.assertEqual(
            found, KNOWN_TODO_CELLS,
            "unexpected: " + str(sorted(found - KNOWN_TODO_CELLS)) +
            " / no longer present: " + str(sorted(KNOWN_TODO_CELLS - found)),
        )

    def test_partial_todo_rows_are_all_or_nothing(self):
        """A row is either fully transcribed or fully blank. A half-filled
        row would mean an indexing offset went wrong somewhere."""
        for dept, cog, table in all_cogs():
            for section in SECTIONS:
                for attack, values in table[section].items():
                    nones = sum(v is None for v in values)
                    with self.subTest(dept=dept, cog=cog, section=section, attack=attack):
                        self.assertIn(nones, (0, len(values)),
                                      f"{dept}/{cog}/{section}/{attack} is partly filled: {values}")


class TestTablesDriveMechanics(unittest.TestCase):
    """Exercise the real indexing path mechanics uses, for every cog at
    every level it can appear at."""

    def test_every_cog_level_can_be_indexed(self):
        for dept, cog, table in all_cogs():
            for level in table["levels"]:
                rel = level - table["levels"][0]
                for attack in table["freq"]:
                    with self.subTest(dept=dept, cog=cog, level=level, attack=attack):
                        table["freq"][attack][rel]
                        table["damage"][attack][rel]
                        table["accuracy"][attack][rel]

    def test_pick_cog_attack_returns_a_valid_attack(self):
        import random
        from solver.mechanics import pick_cog_attack
        from solver.state import CogState

        rng = random.Random(0)
        for dept, cog, table in all_cogs():
            for level in table["levels"]:
                state = CogState(cog_type=cog, department=dept, level=level,
                                 hp=1, max_hp=1)
                for _ in range(20):
                    random.seed(rng.randrange(1 << 30))
                    with self.subTest(dept=dept, cog=cog, level=level):
                        self.assertIn(pick_cog_attack(state), table["freq"])


if __name__ == "__main__":
    unittest.main()
