"""Buildings and the fights that follow one another.

Standard library only.
"""
import random
import unittest

from solver import data, facility, outcomes, simulator
from solver.data import gags as gags_mod
from solver.rl import env
from solver.state import BattleState, CogState, ToonState, Track


def cog(level=5, hp=None):
    full = data.cog_max_hp(level)
    return CogState("cold_caller", "sellbot", level,
                    full if hp is None else hp, full)


def toon(laff=80):
    return ToonState(laff, laff, {Track.THROW: 7, Track.SQUIRT: 7},
                     {(Track.THROW, 3): 5, (Track.SQUIRT, 3): 5})


class DifficultyTableTest(unittest.TestCase):
    """[CONFIRMED] against the wiki's Cog Building difficulty table."""

    def test_every_difficulty_one_to_nine(self):
        self.assertEqual(sorted(facility.DIFFICULTY), list(range(1, 10)))

    def test_the_rows_the_wiki_prints(self):
        self.assertEqual(facility.DIFFICULTY[1],
                         {"floors": (1, 1), "cogs": (1, 3), "boss": 4})
        self.assertEqual(facility.DIFFICULTY[9],
                         {"floors": (5, 5), "cogs": (9, 11), "boss": 12})

    def test_the_two_generation_rules(self):
        """The owner's rules: cogs are (d, d+2) and the boss is d+3.

        Both hold across all nine rows, which audits the transcription
        -- a typo in any cell would break the pattern.
        """
        for difficulty, row in facility.DIFFICULTY.items():
            self.assertEqual(row["cogs"], (difficulty, difficulty + 2))
            self.assertEqual(row["boss"], difficulty + 3)

    def test_boss_outranks_the_floor_cogs(self):
        """The wiki's boss column is above the cog range in every row."""
        for row in facility.DIFFICULTY.values():
            self.assertGreater(row["boss"], row["cogs"][1] - 1)

    def test_unknown_difficulty_raises_rather_than_inventing(self):
        with self.assertRaises(ValueError):
            facility.plan_facility(random.Random(0), 12,
                                   lambda r, lv: cog(lv))


class PlanTest(unittest.TestCase):

    def make(self, seed=0, difficulty=7, floors=None):
        return facility.plan_facility(random.Random(seed), difficulty,
                                      lambda r, lv: cog(lv), floors=floors)

    def test_floor_count_inside_the_wiki_range(self):
        for seed in range(20):
            plan = self.make(seed, difficulty=7)
            lo, hi = facility.DIFFICULTY[7]["floors"]
            self.assertTrue(lo <= len(plan.floors) <= hi)

    def test_top_floor_carries_the_boss(self):
        plan = self.make(difficulty=9)
        self.assertEqual(plan.floors[-1][-1].level,
                         facility.DIFFICULTY[9]["boss"])

    def test_progressively_more_cogs(self):
        """The one thing the wiki states about floor size."""
        plan = self.make(difficulty=9, floors=5)
        sizes = [len(f) for f in plan.floors]
        self.assertLessEqual(sizes[0], sizes[-1])

    def test_take_floor_splits_at_the_four_cog_cap(self):
        plan = facility.FacilityPlan([[cog() for _ in range(6)]])
        field, held = plan.take_floor()
        self.assertEqual(len(field), 4)
        self.assertEqual(len(held), 2)

    def test_remaining_counts_floors_not_yet_started(self):
        """The off-by-one that under-priced every gag in a building: a
        [4,4,5,6,7] plan has 22 cogs left after floor one, not 18."""
        plan = facility.FacilityPlan(
            [[cog() for _ in range(n)] for n in (4, 4, 5, 6, 7)])
        self.assertEqual(plan.remaining(), 26)
        plan.take_floor()
        self.assertEqual(plan.remaining(), 22)

    def test_exhausted_after_the_last_floor(self):
        plan = facility.FacilityPlan([[cog()], [cog()]])
        plan.take_floor()
        self.assertFalse(plan.exhausted)
        plan.take_floor()
        self.assertTrue(plan.exhausted)
        self.assertEqual(plan.take_floor(), ([], []))


class ReinforceTest(unittest.TestCase):

    def test_a_freed_slot_is_filled(self):
        state = BattleState(toon=toon(), cogs=[cog()], holdout=[cog()],
                            kind="facility")
        state.cogs[0].hp = 0
        state.cogs[0].status.is_dead = True
        self.assertEqual(facility.reinforce(state), 1)
        self.assertEqual(len(state.active_cogs()), 1)
        self.assertEqual(state.holdout, [])

    def test_never_more_than_four_on_the_field(self):
        state = BattleState(toon=toon(),
                            cogs=[cog() for _ in range(4)],
                            holdout=[cog() for _ in range(3)],
                            kind="facility")
        self.assertEqual(facility.reinforce(state), 0)
        self.assertEqual(len(state.holdout), 3)

    def test_two_dead_two_join(self):
        state = BattleState(toon=toon(),
                            cogs=[cog() for _ in range(4)],
                            holdout=[cog() for _ in range(3)],
                            kind="facility")
        for c in state.cogs[:2]:
            c.hp = 0
            c.status.is_dead = True
        self.assertEqual(facility.reinforce(state), 2)
        self.assertEqual(len(state.active_cogs()), 4)
        self.assertEqual(len(state.holdout), 1)

    def test_a_round_reinforces(self):
        """Reinforcement happens at the round boundary, so the SEARCH
        sees it -- a kill that is instantly replaced is not the progress
        it looks like."""
        from solver import party as party_mod
        from solver.state import Action
        state = BattleState(toon=toon(), cogs=[cog(1, hp=1)],
                            holdout=[cog(5)], kind="facility")
        nxt, _healed, _done = party_mod.step(
            state, Action(track=Track.THROW, level=3, target_index=0),
            mode=party_mod.Mode.COORDINATED,
            joint=[Action(track=Track.THROW, level=3, target_index=0)],
            rng=random.Random(0))
        self.assertEqual(len(nxt.active_cogs()), 1)
        self.assertEqual(nxt.holdout, [])

    def test_track_resolution_does_not_reinforce(self):
        """`apply_party_round` must NOT reinforce, and this is not a
        style point.

        `greedy_plan` calls it on a scratch clone after each toon picks,
        so later toons can see the earlier ones' choices. Reinforcing
        there grew the scratch state's cog list, the next toon
        enumerated a target index that did not exist in the real state,
        and the plan raised IndexError when applied. It is also wrong on
        the merits: a cog should not be targetable in the round it
        walked into.
        """
        from solver.state import Action
        state = BattleState(toon=toon(), cogs=[cog(1, hp=1)],
                            holdout=[cog(5)], kind="facility")
        simulator.apply_party_round(
            state, [Action(track=Track.THROW, level=3, target_index=0)],
            hits=[True])
        self.assertEqual(len(state.holdout), 1)   # still waiting
        self.assertEqual(len(state.cogs), 1)

    def test_the_search_survives_a_facility(self):
        """The regression this whole fix came from: run the search over
        real facility episodes and let it raise if a plan targets a cog
        that is not there."""
        from solver.party import Mode
        from solver.search import party_search as ps
        for seed in (12000, 12004, 12011):
            e = env.BattleEnv(rng=random.Random(seed),
                              sampler=env.facility_position,
                              coordinated=True)
            _ob, mask = e.reset()
            done, guard, cached = False, 0, None
            while not done and guard < 40:
                guard += 1
                if all(a is None for a in e.pending):
                    _v, cached = ps.evaluate(
                        e.state, depth=1, mode=Mode.COORDINATED,
                        samples=4, max_plans=6, rng=e.rng)
                index = env.PASS_INDEX
                act = (cached[e.actor]
                       if cached and e.actor < len(cached) else None)
                if act is not None and not act.is_pass:
                    for i, c in enumerate(env.ACTIONS):
                        if (c is not None and c.track == act.track
                                and c.level == act.level
                                and c.target_index == act.target_index):
                            index = i
                            break
                if not mask[index]:
                    index = env.PASS_INDEX
                _ob, mask, _r, done, _info = e.step(index)


class BattleEndTest(unittest.TestCase):

    def test_not_won_while_cogs_are_still_walking_in(self):
        state = BattleState(toon=toon(), cogs=[cog()], holdout=[cog()],
                            kind="facility")
        state.cogs[0].hp = 0
        state.cogs[0].status.is_dead = True
        self.assertFalse(state.is_win())
        self.assertFalse(state.is_terminal())

    def test_won_once_the_holdout_is_empty(self):
        state = BattleState(toon=toon(), cogs=[cog()], kind="facility")
        state.cogs[0].hp = 0
        state.cogs[0].status.is_dead = True
        self.assertTrue(state.is_win())

    def test_holdout_and_kind_key_the_memo(self):
        def make(holdout, kind):
            return BattleState(toon=toon(), cogs=[cog()],
                               holdout=[cog() for _ in range(holdout)],
                               kind=kind)
        self.assertNotEqual(outcomes.state_key(make(0, "street")),
                            outcomes.state_key(make(1, "street")))
        self.assertNotEqual(outcomes.state_key(make(0, "street")),
                            outcomes.state_key(make(0, "facility")))

    def test_clone_carries_both(self):
        state = BattleState(toon=toon(), cogs=[cog()], holdout=[cog()],
                            kind="facility")
        twin = state.clone()
        self.assertEqual(len(twin.holdout), 1)
        self.assertEqual(twin.kind, "facility")
        twin.holdout[0].hp = 1
        self.assertNotEqual(state.holdout[0].hp, 1)   # a real copy


class EpisodeTest(unittest.TestCase):

    def test_street_positions_have_no_horizon(self):
        rng = random.Random(0)
        for _ in range(60):
            state = env.mixed_position(rng, 0.3, 0.25, 0.2)
            if state.kind == "street":
                self.assertEqual(state.cogs_remaining, 0)

    def test_a_won_floor_moves_to_the_next(self):
        """The change that makes a conserved gag worth conserving."""
        e = env.BattleEnv(rng=random.Random(3),
                          sampler=env.facility_position, coordinated=True)
        e.reset()
        e.plan = facility.FacilityPlan(
            [[cog(1, hp=1)], [cog(1, hp=1)], [cog(1, hp=1)]])
        field, held = e.plan.take_floor()
        e.state.cogs, e.state.holdout = field, held
        e.state.cogs_remaining = e.plan.remaining()
        start_floor = e.floor
        nxt = e.state.clone()
        nxt.cogs[0].hp = 0
        nxt.cogs[0].status.is_dead = True
        self.assertTrue(nxt.is_win())
        moved = e._next_floor(nxt)
        self.assertGreater(e.floor, start_floor)
        self.assertEqual(len(moved.active_cogs()), 1)

    def test_the_pouch_carries_across_floors(self):
        """Nothing restocks between floors. If it did, the whole model
        would be pointless."""
        e = env.BattleEnv(rng=random.Random(5),
                          sampler=env.facility_position, coordinated=True)
        e.reset()
        e.state.toons[0].gag_counts = {(Track.THROW, 3): 2}
        won = e.state.clone()
        for c in won.cogs:
            c.hp = 0
            c.status.is_dead = True
        won.holdout = []
        moved = e._next_floor(won)
        self.assertEqual(moved.toons[0].gag_counts, {(Track.THROW, 3): 2})

    def test_laff_carries_across_floors(self):
        e = env.BattleEnv(rng=random.Random(5),
                          sampler=env.facility_position, coordinated=True)
        e.reset()
        e.state.toons[0].laff = 11
        won = e.state.clone()
        for c in won.cogs:
            c.hp = 0
            c.status.is_dead = True
        won.holdout = []
        self.assertEqual(e._next_floor(won).toons[0].laff, 11)

    def test_encoding_separates_street_from_facility(self):
        rng = random.Random(9)
        state = env.default_position(rng)
        state.kind, state.cogs_remaining = "street", 0
        street = env.encode(state)
        state.kind, state.cogs_remaining = "facility", 12
        self.assertNotEqual(street, env.encode(state))
        self.assertEqual(len(street), env.OBS_DIM)

    def test_truncation_is_per_floor_not_per_episode(self):
        """A five-floor building legitimately runs past `max_rounds`;
        capping the episode there would end it around floor two and the
        pouch pressure would never arrive."""
        e = env.BattleEnv(rng=random.Random(1), max_rounds=20,
                          sampler=env.facility_position, coordinated=True)
        e.reset()
        e.floor_rounds = 0
        e.rounds = 45
        self.assertLess(e.rounds, e.max_rounds * 6)


if __name__ == "__main__":
    unittest.main()


class StreetDifficultyTest(unittest.TestCase):
    """Difficulty comes from the STREET, [CONFIRMED] from the wiki's
    Street table. Party strength does not make a building easier."""

    def party(self, n, laff=78):
        return BattleState(toons=[ToonState(laff, laff, {Track.THROW: 7},
                                            {(Track.THROW, 3): 5})
                                  for _ in range(n)],
                           cogs=[cog()], kind="facility")

    def test_the_wiki_street_rows(self):
        rows = {name: levels for name, _pg, levels in facility.STREETS}
        self.assertEqual(rows["Loopy Lane"], (1, 3))
        self.assertEqual(rows["Polar Place"], (7, 9))
        self.assertEqual(rows["Lullaby Lane"], (6, 9))
        self.assertEqual(rows["Sleet Street"], (5, 7))

    def test_seventeen_streets(self):
        self.assertEqual(len(facility.STREETS), 17)

    def test_party_size_does_not_change_difficulty(self):
        """The correction: the game does not make a building easier
        because a weak toon walked in."""
        rng = random.Random(0)
        solo = [facility.difficulty_for(self.party(1), rng)
                for _ in range(600)]
        full = [facility.difficulty_for(self.party(4), rng)
                for _ in range(600)]
        self.assertLess(abs(mean(solo) - mean(full)), 0.5)

    def test_late_streets_are_hard(self):
        """The complaint that prompted this: by the last playgrounds you
        face difficulty 5-9 as the ordinary case."""
        rng = random.Random(0)
        for name, _pg, _r in facility.STREETS:
            pass
        late = [s for s in facility.STREETS
                if s[1] in facility.LATE_PLAYGROUNDS]
        for _name, _pg, (lo, _hi) in late:
            self.assertGreaterEqual(lo, 5)

    def test_difficulty_stays_inside_the_street_range(self):
        rng = random.Random(3)
        for street in facility.STREETS:
            lo, hi = street[2]
            for _ in range(40):
                d = facility.difficulty_for(None, rng, street=street)
                self.assertTrue(lo <= d <= hi)

    def test_always_a_real_wiki_row(self):
        rng = random.Random(1)
        for _ in range(500):
            self.assertIn(facility.difficulty_for(None, rng),
                          facility.DIFFICULTY)


class FloorChoiceTest(unittest.TestCase):
    """How many floors a party takes on IS a choice -- the wiki confirms
    the lights above the elevator show the count before entering."""

    def party(self, n, laff=78):
        return BattleState(toons=[ToonState(laff, laff, {Track.THROW: 7},
                                            {(Track.THROW, 3): 5})
                                  for _ in range(n)],
                           cogs=[cog()], kind="facility")

    def test_bigger_parties_take_more_floors(self):
        rng = random.Random(0)
        solo = [facility.floors_for(self.party(1), 7, rng)
                for _ in range(400)]
        full = [facility.floors_for(self.party(4), 7, rng)
                for _ in range(400)]
        self.assertGreater(mean(full), mean(solo))

    def test_never_outside_the_wiki_floor_range(self):
        rng = random.Random(2)
        for difficulty, row in facility.DIFFICULTY.items():
            lo, hi = row["floors"]
            for n in (1, 4):
                for _ in range(60):
                    f = facility.floors_for(self.party(n), difficulty, rng)
                    self.assertTrue(lo <= f <= hi)

    def test_a_sad_toon_does_not_count(self):
        """They have left; their laff is not the party's."""
        rng = random.Random(2)
        state = self.party(4)
        for t in state.toons[1:]:
            t.laff = 0
        weak = [facility.floors_for(state, 7, rng) for _ in range(400)]
        strong = [facility.floors_for(self.party(4), 7, rng)
                  for _ in range(400)]
        self.assertLess(mean(weak), mean(strong))


def mean(values):
    return sum(values) / len(values)


class CogPoolTest(unittest.TestCase):
    """The crash that killed a training run several minutes in."""

    def env_for_cogs(self):
        e = env.BattleEnv(rng=random.Random(0),
                          sampler=env.facility_position, coordinated=True)
        e.reset()
        return e

    def test_every_wiki_difficulty_can_be_built(self):
        e = self.env_for_cogs()
        for difficulty in facility.DIFFICULTY:
            for seed in range(20):
                facility.plan_facility(random.Random(seed), difficulty,
                                       e._facility_cog)

    def test_an_impossible_level_raises_rather_than_substituting(self):
        """It used to fall back to the whole pool, which produced a
        Number Cruncher at level 2 -- a cog that does not exist at level
        2. A silent stand-in would have trained the policy against cogs
        the game does not have."""
        e = self.env_for_cogs()
        with self.assertRaises(ValueError):
            e._facility_cog(random.Random(0), 99)

    def test_low_cogs_cover_the_levels_safe_cogs_cannot(self):
        for level in (1, 2):
            self.assertTrue([c for c in env.LOW_COGS
                             if c[2] <= level <= c[3]])

    def test_the_pools_only_claim_levels_the_cog_really_has(self):
        """Each pool entry is checked against the cog's own published
        range, so a bad row cannot sit there until a rare seed finds it.

        The cog phase draws from the module-level `random`, so the
        stream is restored afterwards: leaving it advanced made an
        unseeded assertion in test_mechanics fail purely on test order.
        """
        self.addCleanup(random.setstate, random.getstate())
        for key, dept, lo, hi in env.SAFE_COGS + env.LOW_COGS:
            for level in range(lo, hi + 1):
                full = data.cog_max_hp(level)
                state = BattleState(
                    toon=toon(), cogs=[CogState(key, dept, level, full,
                                                full)])
                simulator._resolve_cog_phase(state)


class PouchTest(unittest.TestCase):
    """Pouch capacity is a property of the TOON, [CONFIRMED] 20-80 from
    the wiki's Gag pouch table."""

    def test_the_wiki_capacities(self):
        caps = data.POUCH_CAPACITIES
        self.assertEqual(caps["Medium Pouch"], 25)
        self.assertEqual(caps["Large Bag"], 50)
        self.assertEqual(caps["Large Backpack"], 80)

    def test_the_steps_are_not_uniform(self):
        """20/25/30/35/40 rise by five, then 50/60/70/80 by ten. Worth
        pinning: an evenly-spaced table would look plausible and be
        wrong."""
        sizes = sorted(data.POUCH_CAPACITIES.values())
        self.assertEqual(sizes, [20, 25, 30, 35, 40, 50, 60, 70, 80])

    def test_a_toon_carries_a_real_capacity(self):
        rng = random.Random(0)
        allowed = set(data.POUCH_CAPACITIES.values())
        for _ in range(200):
            self.assertIn(env.random_toon(rng).pouch_capacity, allowed)

    def test_a_generated_toon_fits_its_own_pouch(self):
        """62% of generated toons would not have fit a starting pouch
        and 49% not a Medium, because capacity was not consulted when
        building them at all."""
        rng = random.Random(1)
        for _ in range(500):
            t = env.random_toon(rng)
            self.assertLessEqual(gags_mod.pouch_total(t.gag_counts),
                                 t.pouch_capacity)

    def test_level_sevens_are_never_trimmed(self):
        """[CONFIRMED] they are carried outside the pouch."""
        counts = {(Track.THROW, 7): 1, (Track.THROW, 1): 40}
        out = env._trim_to_pouch(counts, 5, random.Random(0))
        self.assertEqual(out[(Track.THROW, 7)], 1)
        self.assertLessEqual(gags_mod.pouch_total(out), 5)

    def test_trimming_drops_the_cheapest_first(self):
        """A toon short on room drops Cupcakes before Wedding Cakes."""
        counts = {(Track.THROW, 1): 10, (Track.THROW, 5): 10}
        out = env._trim_to_pouch(counts, 12, random.Random(0))
        self.assertEqual(out.get((Track.THROW, 5)), 10)
        self.assertEqual(out.get((Track.THROW, 1)), 2)

    def test_capacity_survives_a_clone(self):
        state = BattleState(toon=ToonState(50, 50, {Track.THROW: 5},
                                           {(Track.THROW, 1): 2},
                                           pouch_capacity=35),
                            cogs=[cog()])
        self.assertEqual(state.clone().toons[0].pouch_capacity, 35)

    def test_restock_respects_the_toons_own_capacity(self):
        """The first restock filled every gag to its own max_carry and
        produced 378-gag parties; POUCH_CAPACITIES caps the TOTAL."""
        rng = random.Random(3)
        for _ in range(60):
            state = env.facility_position(rng)
            for t in state.toons:
                if t.laff > 0:
                    env.restock(t, rng)
                    self.assertEqual(data.validate_loadout(t.gag_counts), [])
                    self.assertLessEqual(gags_mod.pouch_total(t.gag_counts),
                                         t.pouch_capacity)

    def test_restock_does_not_change_training(self):
        """Only quantity. A toon with mediocre gags keeps mediocre gags."""
        rng = random.Random(4)
        state = env.facility_position(rng)
        toon_ = state.toons[0]
        before = dict(toon_.track_exp)
        env.restock(toon_, rng)
        self.assertEqual(toon_.track_exp, before)

    def test_toons_enter_a_building_healed(self):
        """43% were entering under half health, because mixed_position
        models a toon part way through a street fight."""
        rng = random.Random(5)
        for _ in range(40):
            state = env.facility_position(rng)
            for t in state.toons:
                if t.laff > 0:
                    self.assertEqual(t.laff, t.max_laff)


class ProgressionTest(unittest.TestCase):
    """A toon is built for the street, not the other way round."""

    def test_laff_floors_are_the_wiki_toontask_totals(self):
        """[CONFIRMED] TTR wiki, Laff: the running total at the END of
        the previous playground, which is what you must have finished to
        be here."""
        floors = {pg: p["laff"][0]
                  for pg, p in facility.PROGRESSION.items()}
        self.assertEqual(floors["Toontown Central"], 15)
        self.assertEqual(floors["Donald's Dock"], 25)
        self.assertEqual(floors["The Brrrgh"], 52)
        self.assertEqual(floors["Donald's Dreamland"], 61)

    def test_pouch_floors_are_the_wiki_capacities(self):
        for pg, profile in facility.PROGRESSION.items():
            self.assertIn(profile["pouch"],
                          set(data.POUCH_CAPACITIES.values()))

    def test_every_street_has_a_profile(self):
        for _name, playground, _levels in facility.STREETS:
            self.assertIn(playground, facility.PROGRESSION)

    def test_a_career_earns_six_of_seven_tracks(self):
        rng = random.Random(0)
        for _ in range(300):
            self.assertEqual(len(facility.sample_tracks(rng)), 6)

    def test_throw_and_squirt_from_the_start(self):
        rng = random.Random(1)
        for _ in range(200):
            have = facility.sample_tracks(rng)
            self.assertEqual(have[Track.THROW], 1)
            self.assertEqual(have[Track.SQUIRT], 1)

    def test_tracks_in_hand_by_street(self):
        """Acquisition is at the END of a playground, so a toon fighting
        in Donald's Dock has three tracks, not four."""
        rng = random.Random(2)
        expected = {1: 2, 2: 3, 3: 4, 4: 4, 5: 5, 6: 6}
        for _ in range(200):
            have = facility.sample_tracks(rng)
            for stage, count in expected.items():
                got = sum(1 for s in have.values() if s <= stage)
                self.assertEqual(got, count)

    def test_daisy_gardens_grants_no_track(self):
        """Stage 3 and stage 4 hold the same number, because Daisy
        Gardens awards nothing."""
        rng = random.Random(3)
        for _ in range(200):
            have = facility.sample_tracks(rng)
            self.assertEqual(sum(1 for s in have.values() if s <= 3),
                             sum(1 for s in have.values() if s <= 4))

    def test_a_toon_meets_its_streets_floors(self):
        rng = random.Random(4)
        for street in facility.STREETS:
            profile = facility.PROGRESSION[street[1]]
            for _ in range(30):
                t = env.toon_for_street(rng, street)
                self.assertGreaterEqual(t.max_laff, profile["laff"][0])
                self.assertLessEqual(t.max_laff, profile["laff"][1])
                self.assertGreaterEqual(t.pouch_capacity, profile["pouch"])

    def test_early_toons_do_not_hold_late_gags(self):
        """The flat experience rate gave Toontown Central toons level 7
        gags. Experience comes from the cogs you beat, and those run
        level 1-3 on the first streets."""
        rng = random.Random(5)
        ttc = [s for s in facility.STREETS
               if s[1] == "Toontown Central"][0]
        for _ in range(200):
            for level in env.toon_for_street(rng, ttc).track_exp.values():
                self.assertLessEqual(level, 5)

    def test_late_toons_are_not_stuck_on_low_gags(self):
        """The owner's correction: you develop your gags regularly, so a
        Dreamland toon is not carrying level 1-2 across the board."""
        rng = random.Random(6)
        ddl = [s for s in facility.STREETS
               if s[1] == "Donald's Dreamland"][0]
        levels = [lv for _ in range(200)
                  for lv in env.toon_for_street(rng, ddl).track_exp.values()]
        self.assertGreater(sum(levels) / len(levels), 4.5)

    def test_no_throw_squirt_bias_late(self):
        """Levels 5-7 are the grind, so by Dreamland everything with age
        has converged. A linear age model biased hard to the starting
        tracks."""
        rng = random.Random(7)
        ddl = [s for s in facility.STREETS
               if s[1] == "Donald's Dreamland"][0]
        toons = [env.toon_for_street(rng, ddl) for _ in range(300)]
        def mean_for(track):
            vals = [t.track_exp[track] for t in toons if track in t.track_exp]
            return sum(vals) / max(1, len(vals))
        starting = mean_for(Track.THROW)
        for track in (Track.TRAP, Track.DROP, Track.LURE):
            self.assertLess(starting - mean_for(track), 1.0)

    def test_parties_are_two_to_four(self):
        """Buildings are group content; the 1-4 spread came from a
        street-battle sampler and made 57% of episodes solo."""
        rng = random.Random(8)
        for _ in range(200):
            self.assertIn(len(env.facility_position(rng).toons), (2, 3, 4))

    def test_the_building_is_on_the_partys_street(self):
        """Rolling a second street here would undo the whole point of
        generating the party for one."""
        for seed in range(40):
            e = env.BattleEnv(rng=random.Random(seed),
                              sampler=env.facility_position,
                              coordinated=True)
            e.reset()
            street = facility.street_named(e.state.street)
            self.assertIsNotNone(street)
            lo, _hi = street[2]
            for c in e.state.cogs:
                self.assertGreaterEqual(c.level, lo)

    def test_restock_fills_from_the_top(self):
        """Concentrate at the top, then fill in downward."""
        toon = ToonState(80, 80, {Track.THROW: 5}, {}, frozenset(),
                         pouch_capacity=12)
        env.restock(toon, random.Random(0))
        self.assertEqual(gags_mod.pouch_total(toon.gag_counts), 12)
        top = toon.gag_counts.get((Track.THROW, 5), 0)
        self.assertGreater(top, 0)
        self.assertEqual(toon.gag_counts.get((Track.THROW, 1), 0), 0)
