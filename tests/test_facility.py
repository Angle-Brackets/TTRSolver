"""Buildings and the fights that follow one another.

Standard library only.
"""
import random
import unittest

from solver import data, facility, outcomes, simulator
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
