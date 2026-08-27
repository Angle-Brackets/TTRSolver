"""
Teammates as a COUNT: `BattleState.allies_standing`.

The live readers cannot see a teammate's pouch -- the box beside their
laff meter is the gag they picked and stays a "?" until the round
resolves -- so a teammate cannot be searched as a toon. What a count
alone determines exactly is where a cog's single-target attack lands,
and that is all this models.

The two things most likely to be broken by a later change are here:
group attacks must NOT dilute, and the solo path must stay exactly what
it was.

stdlib unittest only -- pytest is not installed.
"""
import random
import unittest

from solver import data, outcomes, simulator
from solver.state import BattleState, CogState, ToonState, Track


def cog(dept, key, level):
    hp = data.cog_max_hp(level)
    return CogState(department=dept, cog_type=key, level=level,
                    hp=hp, max_hp=hp)


def toon(laff=100):
    return ToonState(laff, laff, {t: 7 for t in Track}, {}, frozenset())


def expected(dist):
    return sum(d * p for d, p in dist.items())


class ShareTest(unittest.TestCase):

    def test_uniform_over_the_toons_standing(self):
        for allies, want in ((0, 1.0), (1, 0.5), (2, 1 / 3), (3, 0.25)):
            st = BattleState(toons=[toon()], cogs=[], allies_standing=allies)
            self.assertAlmostEqual(st.your_target_share(), want)

    def test_clone_carries_it(self):
        """`clone` is hand-written and its docstring says to extend it
        for every new field. `fires` records what happens when someone
        does not: the value silently defaults and the effect evaporates.
        """
        st = BattleState(toons=[toon()], cogs=[], allies_standing=3)
        self.assertEqual(st.clone().allies_standing, 3)


class DilutionTest(unittest.TestCase):

    def test_single_target_attacks_scale_as_one_over_n(self):
        """A cog with no group attacks at all is the clean case."""
        c = cog("lawbot", "legal_eagle", 10)
        self.assertEqual(
            [n for _p, n, d, _h in outcomes.cog_attack_outcomes(c)
             if d and data.is_group_attack(n)], [],
            "picked a cog that turns out to have a group attack")
        solo = expected(outcomes.cog_damage_distribution(c))
        for allies in (1, 2, 3):
            got = expected(outcomes.cog_damage_distribution(c, allies))
            self.assertAlmostEqual(got, solo / (1 + allies), places=9)

    def test_group_attacks_are_not_diluted(self):
        """THE ONE THAT MATTERS. Scaling a cog's merged distribution by
        the share -- the obvious implementation -- would quietly halve
        the group attacks that are exactly what makes a crowded battle
        dangerous. A Big Wig is nearly as bad in a four-toon fight as
        it is solo, and the model has to say so.
        """
        c = cog("lawbot", "big_wig", 11)
        group = sum(p for p, n, d, _h in outcomes.cog_attack_outcomes(c)
                    if d and data.is_group_attack(n))
        self.assertGreater(group, 0.3, "expected a group-heavy cog here")

        solo = expected(outcomes.cog_damage_distribution(c))
        crowd = expected(outcomes.cog_damage_distribution(c, 3))
        self.assertGreater(crowd, solo / 4.0 * 1.5,
                           "group attacks were diluted along with the rest")
        self.assertLess(crowd, solo, "a full group should still help some")

    def test_distributions_stay_normalised(self):
        for allies in range(4):
            for dept, key, lvl in (("lawbot", "big_wig", 11),
                                   ("bossbot", "head_hunter", 8),
                                   ("cashbot", "money_bags", 9)):
                dist = outcomes.cog_damage_distribution(cog(dept, key, lvl),
                                                        allies)
                self.assertAlmostEqual(sum(dist.values()), 1.0, places=9)

    def test_solo_is_the_identical_cached_object(self):
        """Solo must not merely agree, it must take the old path. The
        fitted evaluator weights were trained on solo positions and
        nothing has retrained them.
        """
        c = cog("sellbot", "the_mingler", 9)
        self.assertIs(outcomes.cog_damage_distribution(c),
                      outcomes.cog_damage_distribution(c, 0))


class KeyTest(unittest.TestCase):

    def test_state_key_separates_party_sizes(self):
        """`solve` takes a caller-supplied memo. One reused across party
        sizes would answer a solo question with a party value -- exactly
        how `free_passes` went wrong when it was left out of this key.
        """
        a = BattleState(toons=[toon()], cogs=[cog("bossbot", "flunky", 1)])
        b = BattleState(toons=[toon()], cogs=[cog("bossbot", "flunky", 1)],
                        allies_standing=3)
        self.assertNotEqual(outcomes.state_key(a), outcomes.state_key(b))

    def test_merge_key_ignores_it_deliberately(self):
        """Every sibling being merged is an outcome of ONE action in ONE
        state, so the party size is identical across all of them. Same
        argument that keeps the gag counts out of this key.
        """
        a = BattleState(toons=[toon()], cogs=[cog("bossbot", "flunky", 1)])
        b = BattleState(toons=[toon()], cogs=[cog("bossbot", "flunky", 1)],
                        allies_standing=3)
        self.assertEqual(outcomes.merge_key(a), outcomes.merge_key(b))


class SamplerAgreesTest(unittest.TestCase):
    """`simulator` and `outcomes` implement the round rules twice, and
    the suite's existing job is to keep them honest about it. The
    dilution had to be added to both, so it is checked in both."""

    def test_sampled_damage_matches_the_enumerated_mean(self):
        c = cog("bossbot", "head_hunter", 8)
        for allies in (0, 2, 3):
            st = BattleState(toons=[toon()], cogs=[c.copy()],
                             allies_standing=allies)
            random.seed(1234 + allies)
            n = 20000
            total = sum(simulator._resolve_cog_phase(st.clone())
                        for _ in range(n))
            want = expected(outcomes.cog_damage_distribution(c, allies))
            self.assertAlmostEqual(total / n, want, delta=0.35)


class WorkerTest(unittest.TestCase):

    def test_set_toon_count_clamps_and_ignores_junk(self):
        from solver.live import overlay

        w = overlay.Worker.__new__(overlay.Worker)
        import threading
        w._lock = threading.Lock()
        w.toon_count = 1
        w._post = lambda: None

        for given, want in ((3, 3), (4, 4), (9, 4), (0, 1), (-2, 1)):
            overlay.Worker.set_toon_count(w, given)
            self.assertEqual(w.toon_count, want)

        overlay.Worker.set_toon_count(w, "nonsense")
        self.assertEqual(w.toon_count, 1, "junk must leave it alone")


if __name__ == "__main__":
    unittest.main()
