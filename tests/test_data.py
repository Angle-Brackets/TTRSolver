"""Structural invariants for the cog attack tables in solver/data/.

These are the invariants solver.mechanics relies on when it does
    rows(table, "frequency")[attack_name][cog.level - table.levels[0]]
and then indexes "damage"/"accuracy" with the same key and offset. If any
of them break, the simulator KeyErrors, IndexErrors, or -- worse -- reads a
number that belongs to a different attack.

Deliberate per-cell gaps (a None inside an otherwise-filled list) are
allowed by design: they mark a value no source gives unambiguously, and the
ground rule is to leave them blank rather than guess.
test_no_unexpected_todo_cells pins the exact inventory of them so a new one
can't appear unnoticed.

"unmodeled_attacks" is the other deliberate gap, at whole-attack granularity
rather than per cell: attacks the TTR wiki confirms a cog has, with damage
and single/group targeting, but for which no frequency exists anywhere. They
are held outside "freq"/"damage"/"accuracy" so the samplers keep working on
the attacks that do have frequencies; the trade-off is that the simulator
under-estimates those cogs. test_unmodeled_attacks_are_well_formed keeps the
shape honest and keeps the names from colliding with modeled attacks.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver.data import COG_DEPARTMENTS  # noqa: E402
from solver.data.cogs import (  # noqa: E402
    COG_HP_BY_LEVEL,
    HP_BOOST,
    HP_BOOST_LEVEL,
    cog_max_hp,
)


# Every per-cell [TODO] currently in the data, as (department, cog, section,
# attack). Each one is explained by a comment in its module.
KNOWN_TODO_CELLS = {
    # (micromanager/brain_storm accuracy was here on a suspected dropped
    # zero. Open Toontown's SuitBattleGlobals.py has the same flat 5, so the
    # guide was faithful and the value is real. Filled in.)
    # The guide gave three values per level (three unused attacks all
    # rendered as Glower Power). TTR 4.0.0 split them into real attacks, so
    # the wiki now has a single damage row -- but still no accuracy.
    ("bossbot", "the_big_cheese", "accuracy", "glower_power"),
    # (big_wig/finger_wag damage was here. The conflicting Finger_Wag page
    # turned out to be showing Throw Book's row -- confirmed by the wiki's
    # own Throw Book entry and by Open Toontown, whose Big Wig has no Finger
    # Wag at all. Filled in from the Big Wig page.)
}

# Cogs whose "freq" row cannot sum to 100 over the attacks the cog really
# has, because at least one real attack has no published frequency. Every
# one of these is a cog whose attack pool changed in TTR 4.0.0.
COGS_WITH_UNMODELED_ATTACKS = {
    ("bossbot", "micromanager"),
    ("bossbot", "corporate_raider"),
    ("bossbot", "the_big_cheese"),
    ("cashbot", "penny_pincher"),
    ("cashbot", "money_bags"),
    ("cashbot", "robber_baron"),
    ("lawbot", "big_wig"),
    ("sellbot", "mr_hollywood"),
}

SECTIONS = ("freq", "damage", "accuracy")
SECTION_FIELDS = {"freq": "frequency", "damage": "damage",
                  "accuracy": "accuracy"}


def all_cogs():
    for dept_key, dept in sorted(COG_DEPARTMENTS.items()):
        for spec in dept:
            yield dept_key, spec.key, spec


def rows(spec, field):
    """{attack_name: per-level tuple} for one field, modeled attacks only --
    the shape these invariants were written against."""
    return {a.name: getattr(a, field) for a in spec.modeled_attacks}


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
                for field in ("levels", "attacks", "rank", "display",
                              "modeled_attacks", "unmodeled_attacks"):
                    self.assertTrue(hasattr(table, field))
                self.assertIsInstance(table.levels, tuple)
                self.assertTrue(table.levels)
                self.assertTrue(all(isinstance(a.group, bool)
                                    for a in table.attacks))

    def test_levels_are_contiguous_ascending(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                levels = table.levels
                self.assertEqual(
                    list(levels), list(range(levels[0], levels[0] + len(levels))),
                    f"{dept}/{cog} levels must be contiguous ascending "
                    f"for (level - levels[0]) indexing to work",
                )

    def test_key_sets_match_across_sections(self):
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                freq_keys = set(rows(table, "frequency"))
                self.assertTrue(freq_keys, f"{dept}/{cog} has no attacks")
                self.assertEqual(freq_keys, set(rows(table, "damage")),
                                 f"{dept}/{cog}: freq vs damage keys differ")
                self.assertEqual(freq_keys, set(rows(table, "accuracy")),
                                 f"{dept}/{cog}: freq vs accuracy keys differ")

    def test_group_flags_belong_to_real_attacks(self):
        """Every group attack is one of the cog's attacks. Note this spans
        unmodeled attacks too -- nine of the twelve 4.0.0 additions are
        group attacks, and the old layout couldn't express that because
        group membership lived in a set keyed off the frequency table."""
        for dept, cog, table in all_cogs():
            with self.subTest(dept=dept, cog=cog):
                grouped = {a.name for a in table.attacks if a.group}
                self.assertLessEqual(grouped, {a.name for a in table.attacks})

    def test_list_lengths_match_levels(self):
        for dept, cog, table in all_cogs():
            n = len(table.levels)
            for section in SECTIONS:
                for attack, values in rows(table, SECTION_FIELDS[section]).items():
                    with self.subTest(dept=dept, cog=cog, section=section, attack=attack):
                        self.assertIsInstance(values, tuple)
                        self.assertEqual(
                            len(values), n,
                            f"{dept}/{cog}/{section}/{attack} has {len(values)} "
                            f"entries but {n} levels",
                        )

    def test_attack_keys_are_snake_case(self):
        for dept, cog, table in all_cogs():
            names = [a.name for a in table.attacks]
            for attack in names:
                with self.subTest(dept=dept, cog=cog, attack=attack):
                    self.assertRegex(attack, r"^[a-z0-9]+(_[a-z0-9]+)*$")

    def test_unmodeled_attacks_are_well_formed(self):
        """An unmodeled attack carries the two things the wiki does give --
        damage per level and single/group -- and nothing that pretends to be
        a frequency. Its name must not collide with a modeled attack, or the
        same attack would exist twice with different meanings."""
        for dept, cog, table in all_cogs():
            n = len(table.levels)
            for attack, entry in {a.name: a for a in table.unmodeled_attacks}.items():
                with self.subTest(dept=dept, cog=cog, attack=attack):
                    self.assertNotIn(
                        attack, {a.name for a in table.modeled_attacks},
                        f"{dept}/{cog}: '{attack}' is both modeled and unmodeled")
                    self.assertIsInstance(entry.group, bool)
                    self.assertFalse(entry.modeled)
                    self.assertEqual(len(entry.damage), n)
                    for v in entry.damage:
                        self.assertIsInstance(v, int)
                        self.assertGreater(v, 0)

    def test_unmodeled_attack_inventory_is_pinned(self):
        """Which cogs the simulator under-estimates is load-bearing enough
        to state out loud: every cog listed here has a real attack it can
        never fire. Shrinking this set means a frequency was found (good);
        growing it silently means a cog quietly got worse."""
        found = {(dept, cog) for dept, cog, table in all_cogs()
                 if {a.name: a for a in table.unmodeled_attacks}}
        self.assertEqual(found, COGS_WITH_UNMODELED_ATTACKS)


class TestCogTableValues(unittest.TestCase):
    def test_frequencies_are_complete_and_sum_to_100(self):
        """Frequencies drive mechanics.pick_cog_attack's cumulative sample.
        A level that doesn't total 100 silently biases the last attack, so
        no None is tolerated here and every level must total exactly 100.

        Note what this does NOT check: for the cogs in
        COGS_WITH_UNMODELED_ATTACKS the 100 is spread over a smaller attack
        pool than the cog really has, so the sampler is self-consistent but
        the distribution is wrong. Only a real frequency table fixes that."""
        bad = []
        for dept, cog, table in all_cogs():
            for i, level in enumerate(table.levels):
                values = [rows(table, "frequency")[a][i] for a in rows(table, "frequency")]
                if any(v is None for v in values):
                    bad.append(f"{dept}/{cog} level {level}: freq has a None cell")
                    continue
                total = sum(values)
                if total != 100:
                    bad.append(f"{dept}/{cog} level {level}: freq sums to {total}, not 100")
        self.assertEqual(bad, [], "frequency totals are off:\n  " + "\n  ".join(bad))

    def test_frequencies_are_non_negative_ints(self):
        for dept, cog, table in all_cogs():
            for attack, values in rows(table, "frequency").items():
                for level, v in zip(table.levels, values):
                    with self.subTest(dept=dept, cog=cog, attack=attack, level=level):
                        self.assertIsInstance(v, int)
                        self.assertGreaterEqual(v, 0)

    def test_accuracy_within_0_100(self):
        for dept, cog, table in all_cogs():
            for attack, values in rows(table, "accuracy").items():
                for level, v in zip(table.levels, values):
                    if v is None:
                        continue  # deliberate [TODO]; see KNOWN_TODO_CELLS
                    with self.subTest(dept=dept, cog=cog, attack=attack, level=level):
                        self.assertIsInstance(v, int)
                        self.assertGreaterEqual(v, 0)
                        self.assertLessEqual(v, 100)

    def test_damage_is_positive_int_or_min_max_pair(self):
        for dept, cog, table in all_cogs():
            for attack, values in rows(table, "damage").items():
                for level, v in zip(table.levels, values):
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
                for attack, values in rows(table, SECTION_FIELDS[section]).items():
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
                for attack, values in rows(table, SECTION_FIELDS[section]).items():
                    nones = sum(v is None for v in values)
                    with self.subTest(dept=dept, cog=cog, section=section, attack=attack):
                        self.assertIn(nones, (0, len(values)),
                                      f"{dept}/{cog}/{section}/{attack} is partly filled: {values}")


class TestCogHealth(unittest.TestCase):
    """cog_max_hp is two formulas, not one: TTR 3.0.0 added a +14 term from
    level 12 up. The old single formula matched the wiki at levels 4 and 9
    and was wrong at every level from 12 on (182 where TTR gives 196)."""

    def test_formula_reproduces_every_published_level(self):
        for level, hp in sorted(COG_HP_BY_LEVEL.items()):
            with self.subTest(level=level):
                self.assertEqual(cog_max_hp(level), hp)

    def test_wiki_worked_examples(self):
        """The three examples the wiki spells out by hand."""
        self.assertEqual(cog_max_hp(4), 30)     # (4+1)(4+2)
        self.assertEqual(cog_max_hp(16), 320)   # (16+1)(16+2) + 14
        self.assertEqual(cog_max_hp(12), 196)   # was 200 before TTR 3.0.0

    def test_boost_applies_from_level_12_and_not_before(self):
        below = HP_BOOST_LEVEL - 1
        x = below + 1
        self.assertEqual(cog_max_hp(below), x * (x + 1))
        x = HP_BOOST_LEVEL + 1
        self.assertEqual(cog_max_hp(HP_BOOST_LEVEL), x * (x + 1) + HP_BOOST)

    def test_health_is_increasing(self):
        levels = sorted(COG_HP_BY_LEVEL)
        for a, b in zip(levels, levels[1:]):
            with self.subTest(level=b):
                self.assertGreater(cog_max_hp(b), cog_max_hp(a))

    def test_every_reachable_cog_level_has_health(self):
        """Including the three over-levels the wiki says each cog can reach
        but that the attack tables don't model -- cog_max_hp still has to
        answer for them."""
        for _dept, _cog, table in all_cogs():
            for level in range(table.levels[0], table.levels[-1] + 4):
                with self.subTest(level=level):
                    self.assertGreater(cog_max_hp(level), 0)


class TestTablesDriveMechanics(unittest.TestCase):
    """Exercise the real indexing path mechanics uses, for every cog at
    every level it can appear at."""

    def test_every_cog_level_can_be_indexed(self):
        for dept, cog, table in all_cogs():
            for level in table.levels:
                rel = level - table.levels[0]
                for attack in rows(table, "frequency"):
                    with self.subTest(dept=dept, cog=cog, level=level, attack=attack):
                        rows(table, "frequency")[attack][rel]
                        rows(table, "damage")[attack][rel]
                        rows(table, "accuracy")[attack][rel]

    def test_pick_cog_attack_returns_a_valid_attack(self):
        import random
        from solver.mechanics import pick_cog_attack
        from solver.state import CogState

        rng = random.Random(0)
        for dept, cog, table in all_cogs():
            for level in table.levels:
                state = CogState(cog_type=cog, department=dept, level=level,
                                 hp=1, max_hp=1)
                for _ in range(20):
                    random.seed(rng.randrange(1 << 30))
                    with self.subTest(dept=dept, cog=cog, level=level):
                        self.assertIn(pick_cog_attack(state), rows(table, "frequency"))


if __name__ == "__main__":
    unittest.main()


class PouchExemptionTest(unittest.TestCase):
    """Level 7 gags do not count against the gag pouch.

    [CONFIRMED] three ways: the wiki gives level 7s a separate carry
    limit and a ToonTask titled "Change +1 level 7 gag carry capacity";
    a live gag menu holding 75 gags printed "Total gags 70 / 70", the
    difference being exactly its five level 7s; and the player confirmed
    it. Counting them in rejected legal loadouts.
    """

    def test_pouch_total_ignores_level_sevens(self):
        from solver.data.gags import pouch_total
        from solver.state import Track
        counts = {(Track.THROW, 5): 10, (Track.THROW, 7): 1,
                  (Track.DROP, 7): 1}
        self.assertEqual(pouch_total(counts), 10)

    def test_a_full_pouch_plus_level_sevens_is_legal(self):
        from solver.data.gags import validate_loadout
        from solver.state import Track
        counts = {(Track.THROW, 5): 7, (Track.THROW, 6): 3,
                  (Track.SQUIRT, 5): 7, (Track.SQUIRT, 6): 3}
        counts.update({(t, 7): 1 for t in
                       (Track.TRAP, Track.LURE, Track.SOUND, Track.THROW,
                        Track.SQUIRT, Track.DROP)})
        self.assertEqual(validate_loadout(counts), [])

    def test_an_oversized_pouch_is_still_caught(self):
        from solver.data.gags import validate_loadout
        from solver.state import Track
        counts = {(Track.THROW, lvl): 30 for lvl in (1, 2, 3, 4)}
        problems = validate_loadout(counts)
        self.assertTrue(any("pouch" in p for p in problems), problems)


class ToonUpOrganicRuleTest(unittest.TestCase):
    """`organic = ceil(1.2 x base)` WITHIN the Toon-Up track only.

    Not a general organic rule, and saying so was a real error: organic
    varies by track. Throw converges on x1.1 (Wedding Cake 120 -> 132),
    Squirt and Drop sit around x1.15-1.2. The relationship below is a
    Toon-Up regularity and nothing wider.

    Lipstick's heal is NOT derived from it any more -- the Lipstick page
    states 25-30 outright, and the summary tables saying 27 are simply
    wrong. The relationship is kept as a consistency check on the track,
    which is all it ever was.
    """

    def test_the_multiplier_is_NOT_general(self):
        """Guards the claim above, so nobody generalises the 1.2."""
        from solver import data
        from solver.state import Track

        throw7 = data.gag(Track.THROW, 7)
        self.assertEqual(throw7.damage, (120, 120))
        self.assertEqual(throw7.organic_damage, (132, 132))  # x1.1, not 1.2

    def test_the_rule_holds_for_every_toon_up_gag(self):
        import math

        from solver import data
        from solver.state import Track

        for gag in data.gags_in(Track.TOON_UP):
            base, organic = gag.heal, gag.organic_heal
            self.assertIsNotNone(base, f"{gag.display} has no base heal")
            self.assertEqual(
                (math.ceil(1.2 * base[0]), math.ceil(1.2 * base[1])),
                tuple(organic),
                f"{gag.display}: organic is not ceil(1.2 x base)")

    def test_lipstick_is_the_derived_value(self):
        from solver import data
        from solver.state import Track

        self.assertEqual(data.gag(Track.TOON_UP, 3).heal, (25, 30))
