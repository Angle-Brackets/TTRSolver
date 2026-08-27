"""
Battle state representation for the solo-toon-vs-cogs simulator.

Design note: status effects (trap, lure, etc.) are folded into explicit
state fields rather than tracked via history, so the transition function
in simulator.py stays a clean Markov step: (state, action) -> next_state.
See docs/data-confidence.md for why this matters and what it does/doesn't buy you.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, FrozenSet, Tuple, List

# Level 7 gags are one per pouch and pouch-EXEMPT, so nothing in the
# ordinary cost machinery restrains them: measured across a `price`
# sweep of 1.0 / 0.5 / 0.25 / 0, level-7 use did not move at all (38
# thrown every time). What restrains them today is only that the policy
# rarely proposes one. Set this False to forbid them outright.
#
# IT MUST BE READ AT CALL TIME, not captured at import, so a caller can
# toggle it between runs. Both `simulator.legal_actions` and
# `BattleState.can_still_damage` consult it, and they have to agree:
# `can_still_damage` keys on TRACKS and ignores levels, so a toon
# holding nothing but Throw-7 would otherwise be judged able to damage a
# cog while `legal_actions` offered it nothing -- a position the search
# treats as playable and cannot play, which breaks the termination
# argument in `legal_actions`.
ALLOW_LEVEL_7 = True

# Kept here rather than imported from `data.gags` so `state` stays free
# of data imports; asserted equal in tests/test_level_seven.py.
LEVEL_SEVEN = 7


class Track(str, Enum):
    TOON_UP = "toon_up"
    TRAP = "trap"
    LURE = "lure"
    SOUND = "sound"
    THROW = "throw"
    SQUIRT = "squirt"
    DROP = "drop"


# Fixed initiative order used to resolve a round.
# [CONFIRMED] via Toontown-Resources README ("misc-2" section).
ATTACK_ORDER: List[Track] = [
    Track.TOON_UP, Track.TRAP, Track.LURE,
    Track.SOUND, Track.THROW, Track.SQUIRT, Track.DROP,
]

GROUP_TRACKS = {Track.TOON_UP, Track.SOUND, Track.LURE}  # can hit all cogs
# Throw/Squirt only go multi-target at level 7 (Wedding Cake / Geyser).


@dataclass(slots=True)
class ToonState:
    laff: int
    max_laff: int

    # track_exp[track] = toon's TRAINING level in that track (0-7).
    # This is a fixed skill stat, NOT the level of the gag about to be
    # thrown -- a toon maxed in Throw gets the same trackExp accuracy
    # bonus whether they throw a Cupcake or a Whole Cream Pie.
    # Assume 7 (maxed) for owned tracks unless modeling gag training.
    track_exp: Dict[Track, int] = field(default_factory=dict)

    # gag_counts[(track, level)] = number of that gag left in the pouch
    gag_counts: Dict[Tuple[Track, int], int] = field(default_factory=dict)


    # Tracks whose gags are organic. Organic is a property of the whole
    # track, not of an individual gag -- a toon earns an organic track
    # from a ToonTask and every gag in it is organic thereafter.
    #
    # Raises damage for every track, and accuracy for Lure specifically
    # (see Gag.prop_accuracy). Fixed for the battle, so `clone` shares it
    # rather than copying, exactly like track_exp.
    organic_tracks: FrozenSet[Track] = frozenset()

    # How many gags (levels 1-6; level 7 is exempt) this toon can carry.
    # A property of the TOON, earned by ToonTask -- see
    # `data.POUCH_CAPACITIES`, [CONFIRMED] 20 to 80. It is not a
    # property of where they are standing, which an earlier version had
    # it as, deriving capacity from the street the building was on.
    #
    # Deliberately NOT in `outcomes.state_key`: nothing restocks a pouch
    # mid-battle or between floors, so capacity cannot change any value
    # the search computes. It constrains how a toon is BUILT, not how a
    # battle goes. If restocking is ever modelled, it has to go in the
    # key -- that is the `free_passes` lesson.
    pouch_capacity: int = 80

    # Pink slips, "fires". [CONFIRMED] wiki: they fire a targeted cog out
    # of battle with a cannon and eliminate BOTH layers of a Version 2.0.
    # The owner confirms the rest from play: using one costs the toon's
    # action for the round, and it cannot miss.
    #
    # LAST FIELD ON PURPOSE. `ToonState` is built positionally all over
    # the tests and tools, so inserting this between existing fields
    # shifted every one after it -- `organic_tracks` landed in `fires`
    # and 26 tests died on "frozenset > int". A new field goes on the
    # end unless every construction site is keyword-only.
    #
    # Defaults to 0, because a fire is strictly better than any gag
    # against any cog and a party holding them does not play the game.
    # They come from the CEO, two to six a run, cap 200.
    fires: int = 0

    def is_organic(self, track: Track) -> bool:
        return track in self.organic_tracks

    def has_gag(self, track: Track, level: int) -> bool:
        return self.gag_counts.get((track, level), 0) > 0


@dataclass(slots=True)
class CogStatus:
    lured: bool = False

    # Rounds of lure left on this cog -- the `currentlyLuredSuits[suitId][0]`
    # counter from the source pseudocode, which gates the wake-up check.
    # Counts cog phases this cog will skip; decremented every round the lure
    # holds, and the lure ends when it reaches 0. Set from
    # mechanics.lure_duration_rounds(), which is [CONFIRMED] against the
    # TTR wiki: 2/2/3/3/4/4/8 rounds by gag level.
    lure_rounds_remaining: int = 0

    # The PRE-BONUS accuracy (propAcc + trackExp + tgtDef, no bonus term)
    # that the Lure landing on this cog was rolled with. This is the input
    # to mechanics.lure_wakeup_chance(); the source stores it per-cog at the
    # moment the Lure resolves, because accuracy bonuses must not offset the
    # wake-up odds. None whenever the cog is not lured.
    lure_acc_before_bonus: Optional[int] = None

    # Level of the Lure gag that landed. Needed because whether a lure can
    # expire early is a property of that gag's base accuracy -- see
    # mechanics.lure_can_expire_early. None whenever the cog is not lured.
    lure_level: Optional[int] = None

    trapped: bool = False
    trap_track: Optional[Track] = None   # which gag laid the trap
    trap_level: Optional[int] = None
    # Whether the toon's Trap track was organic when this trap was laid.
    # Recorded here because the damage is dealt later, when a Lure drags
    # a cog onto it, by which time the action is long gone.
    trap_organic: bool = False

    is_dead: bool = False

    # A Version 2.0 Cog is wearing its outer suit. [CONFIRMED] wiki: a
    # v2.0 is suit + Skelecog form, each with the health of a normal cog
    # of that level, and it is only defeated when both are gone -- the
    # published totals are exactly twice the normal table on all twelve
    # levels. So this needs no second hp number: `hp`/`max_hp` are the
    # CURRENT layer, and this flag says another one is waiting behind it.
    suited: bool = False

    # Damage this cog has taken, per toon index, for cog target
    # selection -- a cog prefers to hit back at whoever hurt it most.
    # None while solo, where there is only one toon to attack and
    # nothing to weigh, so the common case allocates nothing and
    # `copy` stays as cheap as it was. See mechanics.pick_cog_target.
    damage_by_toon: Optional[Dict[int, int]] = None

    def record_damage(self, toon_index: int, amount: int) -> None:
        if amount <= 0:
            return
        if self.damage_by_toon is None:
            self.damage_by_toon = {}
        self.damage_by_toon[toon_index] = (
            self.damage_by_toon.get(toon_index, 0) + amount)

    def apply_lure(self, acc_before_bonus: int, rounds: int,
                    level: Optional[int] = None) -> bool:
        """A Lure lands on this cog. Returns whether it did anything.

        **Re-luring an already-lured cog does NOT refresh its duration.**
        The existing counter runs down on its original schedule and the new
        gag is simply wasted on that cog. It doesn't stack either -- TTR
        3.0.0 "Removed the Lure Stacking Rounds mechanic that allowed the
        accumulation of Lure rounds ... if multiple Lure Gags are used
        simultaneously". Neither refresh nor stack: an already-lured cog is
        untouchable by Lure until its rounds run out.

        This is a no-op rather than an illegal action on purpose. A group
        Lure over a partly-lured battle has to be able to catch the
        un-lured cogs, so it can't be rejected wholesale -- it just leaves
        the already-lured ones alone.

        [UNVERIFIED] The no-refresh rule comes from play knowledge, not the
        wiki: the wiki documents the simultaneous-stacking removal above and
        says nothing about re-luring across rounds.
        """
        if self.lured:
            return False
        self.lured = True
        self.lure_rounds_remaining = rounds
        self.lure_acc_before_bonus = acc_before_bonus
        self.lure_level = level
        return True

    def clear_lure(self) -> None:
        """Cog stops being lured -- woke up early, or its rounds ran out."""
        self.lured = False
        self.lure_rounds_remaining = 0
        self.lure_acc_before_bonus = None
        self.lure_level = None

    def clear_trap(self) -> None:
        """No trap under this cog -- sprung, or cancelled by a second one.

        Every field together, because a stale `trap_level` under a
        `trapped=False` cog is the shape that makes a later Lure look up
        damage for a trap that is not there.
        """
        self.trapped = False
        self.trap_track = None
        self.trap_level = None
        self.trap_organic = False

    def copy(self) -> "CogStatus":
        return CogStatus(
            lured=self.lured,
            lure_rounds_remaining=self.lure_rounds_remaining,
            lure_acc_before_bonus=self.lure_acc_before_bonus,
            lure_level=self.lure_level,
            trapped=self.trapped,
            trap_track=self.trap_track,
            trap_level=self.trap_level,
            trap_organic=self.trap_organic,
            is_dead=self.is_dead,
            # The outer suit. Omitting it silently un-2.0'd every Version
            # 2.0 after ONE round -- the flag survived only until the
            # first copy, so a CEO's second battle, which is entirely
            # 2.0s, was fought against ordinary cogs with half the health.
            # Same omission as `fires` in ToonState.clone, found the same
            # way: a marker that appeared on round one and never again.
            suited=self.suited,
            damage_by_toon=(dict(self.damage_by_toon)
                            if self.damage_by_toon else None),
        )


@dataclass(slots=True)
class CogState:
    cog_type: str          # key into data/ cog tables, e.g. "flunky"
    department: str        # "bossbot" | "sellbot" | "cashbot" | "lawbot"
    level: int              # absolute level, e.g. 3
    hp: int
    max_hp: int
    status: CogStatus = field(default_factory=CogStatus)

    def copy(self) -> "CogState":
        return CogState(cog_type=self.cog_type, department=self.department,
                        level=self.level, hp=self.hp, max_hp=self.max_hp,
                        status=self.status.copy())

    def take_damage(self, amount: int) -> int:
        """Apply damage through the Version 2.0 layers. Returns damage USED.

        THE ONE RULE WORTH KNOWING: a hit that destroys the outer suit
        does NOT carry the excess into the Skelecog form. TTR removed
        carryover damage in the 3.0.0 rebalancing of December 2021, so a
        Toontanic into a 90 hp suit wastes 90 of its 180.

        That makes v2.0 the only cog in the game that rewards precision
        over raw damage, and it cuts directly against how both agents
        play -- they favour group gags and heavy single hits, and a
        board full of v2.0s punishes exactly that.

        RETURNS THE FULL AMOUNT THROWN, not the part that fitted. Every
        scorer and the reward function read this as "damage dealt", and
        returning the clamped value silently redefined that for the whole
        project -- a 180-damage TNT into a 42 hp cog reported 42, and
        three organic-damage tests caught it. Overkill is a SCORER's
        concern (`plan_waste` already charges for it) and must not be
        smuggled in here.
        """
        if amount <= 0 or self.status.is_dead:
            return 0
        self.hp -= amount
        if self.hp > 0:
            return amount
        self.hp = 0
        if self.status.suited:
            # The suit comes off and the Skelecog steps out at FULL
            # health. The overkill is discarded here, which is the whole
            # of the no-carryover rule.
            self.status.suited = False
            self.hp = self.max_hp
        else:
            self.status.is_dead = True
        return amount



@dataclass(slots=True)
class BattleState:
    """A battle: one to four toons against one to four cogs.

    ONE TOON IS STILL THE ONLY SEARCHED CASE. The state holds a list so
    the rules can be written once and be correct for a party, but the
    search, the evaluator and the live readers are all still solo. What
    changes here is that the *rules* stop assuming a lone toon -- the
    losing condition especially, which is a statement about the team and
    was written as a statement about one toon.

    `toons[0]` is the toon being advised. `toon` is kept as a property
    for it, because every caller in the project refers to it that way
    and rewriting them all would bury the parts of this change that
    matter.
    """

    toons: List[ToonState]
    cogs: List[CogState]
    round_num: int = 0

    # Cogs still to come AFTER this battle -- the rest of a building's
    # floors, a factory, a boss run. 0 means this is the last fight.
    #
    # The solver has always optimised ONE battle, which is why
    # `objective.scarcity_cost` exists: a hand-tuned stand-in for "an
    # irreplaceable gag is worth more than this fight suggests, because
    # the cost lands in the next one". This is that quantity instead of
    # a proxy for it. Spending a Railroad on floor one of five is a
    # different decision from spending it on the last cog of the day,
    # and nothing in the state could previously tell the two apart.
    #
    # Capped around 30, which is roughly a full building plus its boss.
    cogs_remaining: int = 0

    # Cogs waiting off-field to walk into THIS battle as slots free.
    # [CONFIRMED] Cog Building: "As Toons continuously battle Cogs, more
    # Cogs may exit from the elevator to join." At most four are ever
    # present, so a floor of six is four on the field and two here.
    #
    # This is why a facility is not a pool divided by four: there is no
    # gap between a kill and its replacement.
    holdout: List[CogState] = field(default_factory=list)

    # STREET or FACILITY. See `solver/facility.py`. Held as a plain
    # string so `state_key` stays hashable and cheap, and so nothing in
    # here has to import the facility module.
    kind: str = "street"

    # Which street this fight is on, when it is a facility -- the name
    # from `facility.STREETS`. The party is generated to suit it, so the
    # building has to be built from the SAME street rather than a second
    # roll, or a Dreamland party ends up in a Toontown Central building.
    #
    # Not in `outcomes.state_key`, for the same reason as
    # `ToonState.pouch_capacity`: nothing in a battle reads it. It
    # decides how the position was BUILT, not how it plays out.
    street: str = ""

    # Teammates in this battle besides you: 0 solo, up to 3.
    #
    # PRESENT, NOT SIMULATED, AND THE DISTINCTION IS THE WHOLE DESIGN.
    # They are a count rather than entries in `toons` for two reasons,
    # both of which broke when tried the other way round.
    #
    # `is_terminal` is "every toon sad". Teammates in `toons` that the
    # search cannot kill mean YOUR going sad no longer ends the battle,
    # and the search happily evaluates positions from beyond your own
    # death. That is the shape of bug that once scored a hopeless
    # position at +47.6.
    #
    # Their laff would have to come from somewhere, and IT IS ON THE
    # SCREEN -- the battle UI prints every toon's meter along the
    # bottom ("80/95", "91/106", ...), not just yours, which is worth
    # writing down because this file previously implied otherwise. What
    # is genuinely missing is their GAGS: the box beside each meter is
    # the gag they have chosen and it stays a "?" until the round
    # resolves. A toon whose pouch is unknown cannot be searched as a
    # toon, only counted -- so counted is what this is.
    #
    # And `search/features.py` pools over `toons`. Solo feature vectors
    # are bit-identical today, which is what keeps the fitted weights
    # valid; putting stand-in toons in the list would change the vector
    # for every live party position and quietly invalidate them.
    #
    # So what this buys is exactly one thing, and it is the one thing a
    # COUNT determines without knowing anything else about the people
    # holding the gags: a single-target cog attack now has somewhere
    # else to land. See `your_target_share`.
    #
    # What it deliberately does NOT buy, because a count cannot know it:
    # teammate gags. No Trap set for someone else's Lure, no stacking a
    # track for `calc_hp_bonus`, no counting their damage toward the
    # fight. The advice still plans YOUR pouch alone and is correct to
    # -- `solver/search/party_search.py` is the module that searches a
    # party's joint plan, and it needs their loadouts to do it.
    allies_standing: int = 0

    # Unlured passes still available. A pass is a real move -- conserving
    # a scarce gag, or in a party declining to hit a cog because
    # `mechanics.pick_cog_target` makes it prefer whoever damaged it
    # most, so attacking draws its next swing onto you.
    #
    # It is BUDGETED rather than free, and that is what keeps `solve()`
    # exact. Termination rests on a lexicographic measure that must
    # strictly decrease: (gags remaining, lure rounds remaining, free
    # passes). An unlured pass spends no gag and ticks no lure, so
    # without a budget the search could walk pass -> pass -> pass
    # forever and the state graph would stop being a DAG.
    #
    # CURRENTLY UNUSED -- `legal_actions` is back to the narrow rule.
    #
    # The widening (pass as an ordinary choice: conserve a scarce gag,
    # or decline to attack because `pick_cog_target` aims a cog at
    # whoever hurt it) is right, and shipping it broke exact `solve()`.
    # With a budget of 2 the solver valued a position at +88.85 and with
    # 1 at +84.30, choosing to pass in the first -- but passing only
    # costs laff and a turn, so it cannot CREATE 4.55 points. Working
    # the same node by hand gives ~79.9, and enumerating its outcomes
    # directly gives 84.59: three different numbers for one value, which
    # is a memo serving answers to the wrong question.
    #
    # Adding `free_passes` to `outcomes.state_key` was necessary and not
    # sufficient, so something else in the search caches across it. That
    # has to be found before this comes back: exact `solve()` is what
    # the solo results and every fitted label rest on, and a wrong
    # answer there is worth more than any strategic gain here.
    #
    # A pass while lured does NOT draw on this, because a lured pass has
    # its own decreasing quantity in the lure timer -- that is the
    # trap-and-wait line, which can need many rounds.
    free_passes: int = 3

    def __init__(self, cogs: List[CogState], toon: Optional[ToonState] = None,
                 toons: Optional[List[ToonState]] = None,
                 round_num: int = 0, free_passes: int = 3,
                 cogs_remaining: int = 0,
                 holdout: Optional[List[CogState]] = None,
                 kind: str = "street", street: str = "",
                 allies_standing: int = 0):
        if (toon is None) == (toons is None):
            raise ValueError("pass exactly one of `toon` or `toons`")
        self.toons = list(toons) if toons is not None else [toon]
        self.cogs = cogs
        self.round_num = round_num
        self.free_passes = free_passes
        self.cogs_remaining = cogs_remaining
        self.holdout = list(holdout) if holdout else []
        self.kind = kind
        self.street = street
        self.allies_standing = allies_standing

    @property
    def toon(self) -> ToonState:
        """The toon being advised. Multi-toon code should say which."""
        return self.toons[0]

    @toon.setter
    def toon(self, value: ToonState) -> None:
        self.toons[0] = value

    def active_toons(self) -> List[ToonState]:
        """Toons still standing. A sad toon leaves the battle; the fight
        carries on without them, which is why the losing condition is
        about the team rather than about you."""
        return [t for t in self.toons if t.laff > 0]

    def clone(self) -> "BattleState":
        """A deep-enough copy: every mutable field is fresh, and the shared
        leaves (Track enums, the (track, level) tuples used as gag keys) are
        immutable.

        Exists because `copy.deepcopy` dominated the solver's runtime -- it
        was 91% of a depth-2 search, since expectimax copies a state per
        outcome branch per node. This is ~20x faster for the same result.
        Extend it whenever you add a mutable field to any battle dataclass.
        """
        return BattleState(
            toons=[ToonState(
                laff=t.laff,
                max_laff=t.max_laff,
                # Both dicts are SHARED, not copied. Cloning is the single
                # most expensive thing the search does -- 586,000 clones
                # for one three-cog depth-2 position -- and copying these
                # two was most of it.
                #
                # track_exp is the toon's training level per track. It is
                # fixed for the whole battle; nothing mutates it.
                #
                # gag_counts does change, but only in
                # simulator.apply_toon_action, which copies before
                # writing. Sharing here plus copying there costs one dict
                # copy per action instead of one per outcome branch.
                track_exp=t.track_exp,
                gag_counts=t.gag_counts,
                organic_tracks=t.organic_tracks,
                pouch_capacity=t.pouch_capacity,
                # Pink slips are SPENT, so they must be carried. Omitting
                # this defaulted every clone to zero and the fires simply
                # evaporated -- a CEO sweep reported "20 used every run"
                # which was not usage at all, it was the loss being read
                # as spending. Anything mutable enough to be spent has to
                # appear here; the field list is not decoration.
                fires=t.fires,
            ) for t in self.toons],
            cogs=[c.copy() for c in self.cogs],
            round_num=self.round_num,
            free_passes=self.free_passes,
            cogs_remaining=self.cogs_remaining,
            holdout=[c.copy() for c in self.holdout],
            kind=self.kind,
            street=self.street,
            allies_standing=self.allies_standing,
        )

    def active_cogs(self) -> List[CogState]:
        return [c for c in self.cogs if not c.status.is_dead]

    def is_terminal(self) -> bool:
        return (not self.active_toons()
                or (len(self.active_cogs()) == 0 and not self.holdout)
                or not self.can_still_damage())

    def is_win(self) -> bool:
        """Won when the field is clear AND nothing is still walking in.

        The holdout check is belt and braces: `facility.reinforce` fills
        freed slots during round resolution, so a state with a live
        holdout and an empty field should not normally exist. Should one
        arise on a path that skips reinforcement, calling it a win would
        end the floor early and hand back a victory the toon has not
        had -- expensive and silent, so it is checked here too.
        """
        return (bool(self.active_toons())
                and len(self.active_cogs()) == 0
                and not self.holdout)

    def your_target_share(self) -> float:
        """Probability a SINGLE-target cog attack picks you.

        1/(1+allies): uniform among the toons standing. Group attacks
        are not diluted at all -- they hit everyone -- so this is
        applied per attack by name against `data.GROUP_ATTACKS`, never
        to a cog's damage as a whole.

        WHY UNIFORM, WHEN `mechanics.pick_cog_target` IS NOT. That
        function sends `REVENGE_CHANCE` (75%) of attacks at whoever
        damaged the cog, weighted by how much, and only the remaining
        25% uniformly. Uniform is what that resolves to when everyone
        is throwing gags at roughly equal rates, which is what a real
        group is doing -- the damage weights are then roughly equal and
        the revenge branch spreads like the uniform one.

        IT IS OPTIMISTIC IN A SPECIFIC, KNOWABLE CASE, and this is the
        limitation to hold in mind rather than a hidden one: if you are
        the one dealing the damage -- you dropped a Railroad on a cog
        your teammates have not touched -- revenge concentrates that
        cog's attacks on you, and your real share is nearer 0.75 than
        0.25. The model cannot see it, because it would need each
        teammate's damage and nothing reports it.

        The alternative was to assume the revenge branch always lands on
        you, which is safe in that case and badly wrong in every other:
        at four toons it gives a share of 0.81, so the dilution would be
        almost nil and the count would not be worth reading.
        """
        allies = max(0, int(self.allies_standing))
        return 1.0 / (1.0 + allies)

    def can_still_damage(self) -> bool:
        """Whether any sequence of remaining gags can hurt a cog.

        A solo toon that cannot damage cogs cannot win, however much laff
        or however many gags it is holding -- there is no restocking
        mid-fight, since SOS cards, Unites and Fires are not modelled. So
        this is the real losing condition, and "the pouch is empty" is
        only its most obvious case.

        Damage is possible from an attack track outright, or from Trap,
        which deals its damage only when a Lure drags a cog onto it. That
        gives the awkward cases their answers:

          * eighty Lures and no attack gags -- lost, nothing can deal
            damage
          * Toon-Up and Trap only -- lost, Toon-Up heals and the Trap can
            never be sprung
          * Trap plus Lure -- NOT lost, even with every cog currently
            lured and the Trap unplayable this round; the lure runs out
            and the combo wins from there. That case needs `pass`, which
            `simulator.legal_actions` supplies.
          * a cog already trapped, holding only Lure -- NOT lost, the
            Lure springs the existing trap
        """
        # Pooled across the team, not per toon, and that is the whole
        # difference between the solo rule and the party one. Eighty
        # Lures and no attacks loses solo; in a party it is a perfectly
        # good support loadout, because the damage is somebody else's
        # job. Asking this toon-by-toon would call a winnable fight lost
        # the moment one member ran out of attacks.
        # A pink slip removes a cog outright, so a party holding one can
        # always still finish the fight even with an empty pouch. This has
        # to come before the track check or "eighty Lures and no attacks"
        # would read as lost while a fire sat unused.
        if any(toon.fires > 0 for toon in self.active_toons()):
            return True

        held = set()
        for toon in self.active_toons():
            held |= {track for (track, level), n in toon.gag_counts.items()
                     if n > 0 and toon.track_exp.get(track, 0) > 0
                     and (ALLOW_LEVEL_7 or level != LEVEL_SEVEN)}
        if held & {Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP}:
            return True
        if Track.LURE in held:
            if Track.TRAP in held:
                return True
            if any(c.status.trapped for c in self.active_cogs()):
                return True
        return False


@dataclass
class Action:
    """A solo toon's choice for one round.

    `track=None` is the pass: the toon does nothing and lets the round
    go by. It is a real choice and occasionally the only winning one --
    see `simulator.legal_actions` for when it is offered and why it is
    not offered more often.

    `fire=True` with `track=None` is a pink slip, which is NOT a pass --
    hence `is_pass` checking both. It spends no gag, so anything reasoning
    about the pouch has to know about it separately.
    """
    track: Optional[Track]
    level: int = 0
    # target_index: index into state.cogs, or None for a track that hits
    # all active cogs (Toon-Up, Sound, Lure, or level-7 Throw/Squirt/Drop/Trap)
    target_index: Optional[int] = None
    # A pink slip aimed at `target_index`. Instant, unmissable, and it
    # removes a Version 2.0's Skelecog form along with its suit.
    fire: bool = False

    @property
    def is_pass(self) -> bool:
        return self.track is None and not self.fire

    def describe(self) -> str:
        if self.fire:
            return f"fire -> {self.target_index}"
        if self.is_pass:
            return "pass"
        target = "all" if self.target_index is None else self.target_index
        return f"{self.track.value}/{self.level} -> {target}"


# The one pass action. Actions are compared by value, so this is a
# convenience rather than a singleton anything depends on.
PASS = Action(track=None, level=0, target_index=None)
