"""
Battle state representation for the solo-toon-vs-cogs simulator.

Status effects (trap, lure, etc.) are folded into explicit state fields
rather than tracked via history, so the transition function in
simulator.py stays a clean Markov step: (state, action) -> next_state.
"""
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, FrozenSet, Tuple, List

# Level 7 gags are one per pouch and pouch-EXEMPT, so nothing in the
# ordinary cost machinery restrains them: measured across a `price`
# sweep of 1.0 / 0.5 / 0.25 / 0, level-7 use did not move at all (38
# thrown every time). Set this False to forbid them outright.
#
# Must be read at call time, not captured at import, so a caller can
# toggle it between runs. `simulator.legal_actions` and
# `BattleState.can_still_damage` both consult it and must agree:
# `can_still_damage` keys on TRACKS and ignores levels, so a toon
# holding nothing but Throw-7 would otherwise be judged able to damage a
# cog while `legal_actions` offers it nothing to throw -- breaking the
# termination argument in `legal_actions`.
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


def _restore(obj, state) -> None:
    """Unpickle a slotted state class by NAME, defaulting fields added since.

    Slotted objects pickle their slots by name and nothing more, so a
    field added after a board was saved came back missing, and the first
    `clone()` of an old feedback log raised. Every field ever added did
    this to every older pickle; `sos_calls` was merely the one noticed.
    """
    if isinstance(state, tuple) and len(state) == 2:
        values = dict(state[0] or {})
        values.update(state[1] or {})
    else:
        values = dict(state or {})
    for f in dataclasses.fields(obj):
        if f.name in values:
            object.__setattr__(obj, f.name, values[f.name])
        elif f.default is not dataclasses.MISSING:
            object.__setattr__(obj, f.name, f.default)
        elif f.default_factory is not dataclasses.MISSING:
            object.__setattr__(obj, f.name, f.default_factory())


@dataclass(slots=True)
class ToonState:
    def __setstate__(self, state):
        _restore(self, state)

    laff: int
    max_laff: int

    # track_exp[track] = toon's TRAINING level in that track (0-7). A
    # fixed skill stat, NOT the level of the gag about to be thrown -- a
    # toon maxed in Throw gets the same trackExp accuracy bonus whether
    # they throw a Cupcake or a Whole Cream Pie. Assume 7 (maxed) for
    # owned tracks unless modeling gag training.
    track_exp: Dict[Track, int] = field(default_factory=dict)

    # gag_counts[(track, level)] = number of that gag left in the pouch
    gag_counts: Dict[Tuple[Track, int], int] = field(default_factory=dict)

    # Tracks with organic gags. Raises damage for every track, and
    # accuracy for Lure (see Gag.prop_accuracy). Fixed for the battle, so
    # `clone` shares it rather than copying.
    organic_tracks: FrozenSet[Track] = frozenset()

    # The highest organic LEVEL per track, where known. [CONFIRMED] wiki
    # (Gag trees): trees are planted in order of level and each makes its
    # own gag organic, so levels 1..N are organic and the rest are not.
    # A track in `organic_tracks` with no entry here counts whole.
    organic_levels: Dict[Track, int] = field(default_factory=dict)

    # How many gags (levels 1-6; level 7 is exempt) this toon can carry.
    # A property of the TOON, earned by ToonTask -- see
    # `data.POUCH_CAPACITIES`, [CONFIRMED] 20 to 80.
    #
    # NOT in `outcomes.state_key`: nothing restocks a pouch mid-battle or
    # between floors, so capacity can't change any value the search
    # computes. It constrains how a toon is BUILT, not how a battle
    # goes. If restocking is ever modelled, it has to go in the key --
    # that's the `free_passes` lesson (see BattleState.free_passes).
    pouch_capacity: int = 80

    # How many pink slips a toon can hold. [CONFIRMED] wiki: "Toons can
    # hold up to 200 pink slips", reduced from 255 by the December 2021
    # rebalancing update.
    #
    # Same reasoning as `pouch_capacity`: not in `state_key`, since
    # nothing hands a toon a slip mid-battle. Here so the encoder has a
    # real number to normalise against instead of a literal.
    fire_capacity: int = 200

    # Rounds until this toon may use another unite. [CONFIRMED] wiki:
    # three rounds inside a battle, shown as the Unite Cooldown status
    # effect. Unlike `fires`, this one DOES belong in `state_key`: it
    # changes what the toon may do next round, so two positions
    # identical but for it are not the same position.
    unite_cooldown: int = 0

    # How many unites this toon HOLDS. Zero by default, deliberately: the
    # live readers cannot see a unite pouch (the Local API doesn't report
    # one and nothing reads it off the screen), so an unknown holding
    # must offer nothing rather than everything -- unbounded unites once
    # sent solo buildings from 26% to 100% wins on evidence the solver
    # never had. A harness that wants them sets this explicitly.
    #
    # [CONFIRMED] wiki: "Toons can hold up to 100 unites per type",
    # which is `CARRY_LIMIT`.
    unites_held: int = 0

    # WHICH unites are held, when known: {(kind, track): count}, kind
    # "toon_up" or "gag_up", track the slug or None (a Toon-Up, or the
    # all-tracks Gag-Up).
    #
    # Empty means UNKNOWN, not none -- the one field here where the
    # default is permissive. `unites_held` is the deny (0 unless
    # something read a pouch), so an empty stock beside a nonzero total
    # can only mean "N unites, kind unrecorded", which is what every
    # offline harness supplies.
    #
    # Mutated copy-on-write, never in place: `clone` shares this dict
    # like `gag_counts`, and mutating in place would restock a real
    # pouch from a discarded candidate.
    unite_stock: Dict[tuple, int] = field(default_factory=dict)

    # The Toon-Up unites THIS TOON'S GAME issues, or () for TTR's.
    #
    # Per toon because the builds differ and neither may overwrite the
    # other: TTR issues 20/35/50/65/80 ([CONFIRMED] wiki) and Realms
    # issues 10/20/40/80/MAX ([OWNER] from its menu). Realms data must
    # not become the solver's own table (docs/realms.md), so the Realms
    # reader sets this on the state instead.
    toon_up_values: tuple = ()

    # SOS cards held, by SOS Toon name. [CONFIRMED] wiki: up to 100 of
    # each. Empty by default, which is what keeps every existing
    # position unchanged -- an SOS is only ever a legal action for a
    # toon that holds one.
    sos_cards: Dict[str, int] = field(default_factory=dict)

    # CALLS LEFT THIS FIGHT, across every card, or None for no limit
    # beyond the cards themselves. A budget is one pool -- "five SOS this
    # VP" -- and spreading it as five of EACH card let a playout call
    # eighty: Lil Oldman five times, Moe Zart five times, all free.
    sos_calls: Optional[int] = None

    def sos_held(self, name: str) -> int:
        """How many of `name` this toon may still call."""
        if self.sos_calls is not None and self.sos_calls <= 0:
            return 0
        return self.sos_cards.get(name, 0)

    # Pink slips, "fires". [CONFIRMED] wiki: they fire a targeted cog out
    # of battle with a cannon and eliminate BOTH layers of a Version 2.0.
    # [OWNER] from play: using one costs the toon's action for the round,
    # and it cannot miss.
    #
    # LAST FIELD ON PURPOSE: `ToonState` is built positionally all over
    # the tests and tools, so a new field goes on the end unless every
    # construction site is keyword-only, or it silently shifts every
    # field after it.
    #
    # Defaults to 0, because a fire is strictly better than any gag
    # against any cog and a party holding them does not play the game.
    # They come from the CEO, two to six a run, cap 200.
    fires: int = 0

    def is_organic(self, track: Track, level: Optional[int] = None) -> bool:
        """Is this gag organic? Without a level, is any of the track."""
        if track not in self.organic_tracks:
            return False
        top = self.organic_levels.get(track)
        return top is None or level is None or level <= top

    def has_gag(self, track: Track, level: int) -> bool:
        return self.gag_counts.get((track, level), 0) > 0


@dataclass(slots=True)
class CogStatus:
    def __setstate__(self, state):
        _restore(self, state)

    lured: bool = False

    # Rounds of lure left on this cog -- the `currentlyLuredSuits[suitId][0]`
    # counter from the source pseudocode, which gates the wake-up check.
    # Counts cog phases this cog will skip; decremented every round the
    # lure holds, ending at 0. Set from mechanics.lure_duration_rounds(),
    # [CONFIRMED] TTR wiki: 2/2/3/3/4/4/8 rounds by gag level.
    lure_rounds_remaining: int = 0

    # The PRE-BONUS accuracy (propAcc + trackExp + tgtDef, no bonus term)
    # the Lure landing on this cog was rolled with -- the input to
    # mechanics.lure_wakeup_chance(). Stored per-cog at the moment the
    # Lure resolves, since accuracy bonuses must not offset the wake-up
    # odds. None whenever the cog is not lured.
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

    # An SOS trap carries its OWN damage rather than deriving it from a
    # gag level. The three Trap cards are named after real trap gags and
    # place them, but at SOS-tier numbers -- Quicksand 60 against the
    # gag's 50, Trapdoor 120 against 85, TNT 180 matching. `trap_level`
    # cannot express that, so this overrides it when set.
    trap_damage: Optional[int] = None

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
        The existing counter runs down on its original schedule and the
        new gag is simply wasted. It doesn't stack either -- TTR 3.0.0
        "Removed the Lure Stacking Rounds mechanic that allowed the
        accumulation of Lure rounds ... if multiple Lure Gags are used
        simultaneously". Neither refresh nor stack: an already-lured cog
        is untouchable by Lure until its rounds run out.

        A no-op rather than an illegal action: a group Lure over a
        partly-lured battle must still catch the un-lured cogs, so it
        can't be rejected wholesale -- it just leaves the lured ones
        alone.

        [UNVERIFIED] The no-refresh rule is play knowledge, not the wiki:
        the wiki documents the simultaneous-stacking removal above and
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

        Clears every field together: a stale `trap_level` under a
        `trapped=False` cog is the shape that makes a later Lure look up
        damage for a trap that isn't there.
        """
        self.trapped = False
        self.trap_track = None
        self.trap_level = None
        self.trap_organic = False
        self.trap_damage = None

    def copy(self) -> "CogStatus":
        return CogStatus(
            lured=self.lured,
            lure_rounds_remaining=self.lure_rounds_remaining,
            lure_acc_before_bonus=self.lure_acc_before_bonus,
            lure_level=self.lure_level,
            trapped=self.trapped,
            trap_track=self.trap_track,
            trap_level=self.trap_level,
            # An SOS trap carries its damage HERE and nowhere else.
            # `Clerk Will` and friends set `trap_damage` and leave
            # `trap_level` None, since a card's 60/120/180 isn't a gag
            # level. Must be copied or a trapped cog ends up with both
            # fields None, and `_apply_trap_trigger` raises looking for a
            # gag at trap level None.
            trap_damage=self.trap_damage,
            trap_organic=self.trap_organic,
            is_dead=self.is_dead,
            # The outer suit. Must be copied every round or a Version 2.0
            # silently loses its second layer after one round.
            suited=self.suited,
            damage_by_toon=(dict(self.damage_by_toon)
                            if self.damage_by_toon else None),
        )


@dataclass(slots=True)
class CogState:
    def __setstate__(self, state):
        _restore(self, state)

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
        carryover damage in the 3.0.0 rebalancing, so a Toontanic into a
        90 hp suit wastes 90 of its 180 -- making v2.0 the only cog that
        rewards precision over raw damage, against the grain of agents
        that favour group gags and heavy single hits.

        RETURNS THE FULL AMOUNT THROWN, not the part that fitted. Every
        scorer and the reward function read this as "damage dealt", so
        returning the clamped value would silently redefine that project
        wide. Overkill is a SCORER's concern (`plan_waste` charges for
        it) and must not be smuggled in here.
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
    def __setstate__(self, state):
        _restore(self, state)

    """A battle: one to four toons against one to four cogs.

    ONE TOON IS STILL THE ONLY SEARCHED CASE. The state holds a list so
    the rules can be written once and be correct for a party, but the
    search, the evaluator and the live readers are all still solo. What
    changes here is that the *rules* stop assuming a lone toon -- the
    losing condition especially, which is a statement about the team.

    `toons[0]` is the toon being advised; `toon` is a property for it so
    existing solo code reads unchanged.
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
    # the cost lands in the next one". This field is that quantity
    # directly, rather than a proxy for it: spending a Railroad on floor
    # one of five is a different decision from spending it on the last
    # cog of the day. Capped around 30, roughly a full building plus
    # its boss.
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
    # PRESENT, NOT SIMULATED. A count rather than entries in `toons`,
    # for reasons that broke when tried the other way:
    #
    # - `is_terminal` is "every toon sad". Teammates in `toons` that the
    #   search can't kill mean your own death no longer ends the battle
    #   -- the shape of bug that once scored a hopeless position +47.6.
    # - Their laff IS visible (the battle UI shows every toon's meter),
    #   but their GAGS are not -- the chosen-gag box stays "?" until the
    #   round resolves. A toon whose pouch is unknown can't be searched
    #   as a toon, only counted.
    # - `search/features.py` pools over `toons`, and solo feature
    #   vectors are bit-identical today, which is what keeps the fitted
    #   weights valid; stand-in toons would change that vector for
    #   every live party position.
    #
    # What a count buys: a single-target cog attack has somewhere else
    # to land (see `your_target_share`). What it can't buy, because a
    # count knows nothing about the gags: teammate coordination -- no
    # Trap for someone else's Lure, no stacking for `calc_hp_bonus`, no
    # counting their damage. The advice still plans YOUR pouch alone;
    # `solver/search/party_search.py` is what searches a joint plan.
    allies_standing: int = 0

    # How many of the LAST toons are guesses (`party.assumed_teammates`),
    # not teammates anyone read. The pickup playouts redraw those in every
    # rollout, as they redraw unseen cogs: one fixed stand-in is a specific
    # wrong teammate, and planning around it lost to the count alone.
    assumed_allies: int = 0

    # Unlured passes still available. A pass is a real move -- conserving
    # a scarce gag, or in a party declining to hit a cog because
    # `mechanics.pick_cog_target` prefers whoever damaged it most, so
    # attacking draws its next swing onto you.
    #
    # BUDGETED rather than free, which is what keeps `solve()` exact.
    # Termination rests on a lexicographic measure that must strictly
    # decrease: (gags remaining, lure rounds remaining, free passes). An
    # unlured pass spends no gag and ticks no lure, so without a budget
    # the search could walk pass -> pass -> pass forever, and the state
    # graph would stop being a DAG.
    #
    # IN USE: `simulator.legal_actions` offers an unlured pass while
    # this lasts. For two days it was not -- the wider pass was reverted
    # when exact `solve()` valued one position at +88.85 with a budget of
    # 2 and +84.30 with 1. The pass was never the fault: `solve()` sized
    # its depth as "gags + 1", assuming every action spends a gag, so a
    # line with a pass in it was cut short and scored by the heuristic.
    # The depth now counts `free_passes` too (d3fafd7). 3 is where exact
    # solve's cost stopped rising with the budget.
    #
    # A pass while lured does NOT draw on this budget -- the lure timer
    # is already the decreasing quantity for the trap-and-wait line,
    # which can need many rounds.
    free_passes: int = 3

    # Battle-wide timed status effects from SOS Toons. [OWNER] TTR models
    # Toons Hit and Cogs Miss exactly as it models Lured and Trapped --
    # an effect with a round counter -- so they live here with one,
    # rather than as special cases in a scorer.
    #
    # [CONFIRMED] wiki: +75% gag accuracy and -75% cog accuracy, for 3,
    # 4 or 5 rounds depending on the card's tier.
    #
    # Belong in `outcomes.state_key`: two positions identical but for a
    # Cogs Miss are not the same position -- the `free_passes` lesson.
    toons_hit_rounds: int = 0
    cogs_miss_rounds: int = 0

    # REALMS PLAYS THOSE TWO AS TOONTOWN ONLINE DID: [OWNER] 100% to hit,
    # or every cog missing, for the ONE turn after the call -- not TTR's
    # 75% for 3-5. A property of the server, so the Realms reader sets it
    # on the board; TTR's numbers stay the default (docs/realms.md).
    sos_one_round: bool = False

    # REALMS ONLY, AND ONLY FOR THE LOG: which battle of a boss fight this
    # board came from, its cogs' skelecog flags and the tracker's count.
    # See `RealmsWorker._context_of`. Not carried by `clone`: no engine
    # reads it, and a searched board is not the one that was on screen.
    realms_context: Optional[dict] = None

    def __init__(self, cogs: List[CogState], toon: Optional[ToonState] = None,
                 toons: Optional[List[ToonState]] = None,
                 round_num: int = 0, free_passes: int = 3,
                 cogs_remaining: int = 0,
                 holdout: Optional[List[CogState]] = None,
                 kind: str = "street", street: str = "",
                 allies_standing: int = 0,
                 toons_hit_rounds: int = 0, cogs_miss_rounds: int = 0,
                 sos_one_round: bool = False):
        if (toon is None) == (toons is None):
            raise ValueError("pass exactly one of `toon` or `toons`")
        self.toons = list(toons) if toons is not None else [toon]
        self.cogs = cogs
        self.round_num = round_num
        self.free_passes = free_passes
        self.toons_hit_rounds = toons_hit_rounds
        self.cogs_miss_rounds = cogs_miss_rounds
        self.sos_one_round = sos_one_round
        self.realms_context = None
        self.cogs_remaining = cogs_remaining
        self.holdout = list(holdout) if holdout else []
        self.kind = kind
        self.street = street
        self.allies_standing = allies_standing
        self.assumed_allies = 0

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

        Exists because `copy.deepcopy` was 91% of a depth-2 search's
        runtime (expectimax copies a state per outcome branch per node);
        this is ~20x faster for the same result. Extend it whenever you
        add a mutable field to any battle dataclass.
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
                # track_exp is fixed for the whole battle; nothing
                # mutates it. gag_counts does change, but only in
                # simulator.apply_toon_action, which copies before
                # writing -- so sharing here plus copying there costs one
                # dict copy per action instead of one per outcome branch.
                track_exp=t.track_exp,
                gag_counts=t.gag_counts,
                organic_tracks=t.organic_tracks,
                organic_levels=t.organic_levels,
                pouch_capacity=t.pouch_capacity,
                fire_capacity=t.fire_capacity,
                unite_cooldown=t.unite_cooldown,
                # SPENT, so carried -- same reason as `fires` below.
                unites_held=t.unites_held,
                unite_stock=t.unite_stock,
                toon_up_values=t.toon_up_values,
                sos_cards=t.sos_cards,
                sos_calls=t.sos_calls,
                # Pink slips are SPENT, so they must be carried. A field
                # left out of this list defaults to zero on every clone
                # and silently evaporates across the search.
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
            toons_hit_rounds=self.toons_hit_rounds,
            cogs_miss_rounds=self.cogs_miss_rounds,
            sos_one_round=self.sos_one_round,
        )._with_assumed(self.assumed_allies)

    def _with_assumed(self, count: int) -> "BattleState":
        self.assumed_allies = count
        return self

    def active_cogs(self) -> List[CogState]:
        return [c for c in self.cogs if not c.status.is_dead]

    def is_terminal(self) -> bool:
        return (not self.active_toons()
                or (len(self.active_cogs()) == 0 and not self.holdout)
                or not self.can_still_damage())

    def is_win(self) -> bool:
        """Won when the field is clear AND nothing is still walking in.

        The holdout check is belt and braces: `facility.reinforce` fills
        freed slots during round resolution, so a live holdout beside an
        empty field shouldn't normally exist. If one arises on a path
        that skips reinforcement, checking here avoids ending the floor
        early on a victory the toon hasn't actually had.
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

        WHY UNIFORM, WHEN `mechanics.pick_cog_target` IS NOT: that
        function sends `REVENGE_CHANCE` (75%) of attacks at whoever
        damaged the cog, weighted by how much, and only 25% uniformly.
        Uniform is what that resolves to when everyone throws gags at
        roughly equal rates, which is the normal case.

        OPTIMISTIC IN A SPECIFIC, KNOWN CASE: if you alone just damaged a
        cog your teammates haven't touched, revenge concentrates its
        attacks on you and your real share is nearer 0.75 than 0.25 --
        invisible here since it would need each teammate's damage and
        nothing reports it. The alternative, assuming revenge always
        lands on you, is safe there but wrong everywhere else (at four
        toons it gives 0.81, making the dilution this field exists for
        nearly disappear).
        """
        allies = max(0, int(self.allies_standing))
        return 1.0 / (1.0 + allies)

    def _consumables_can_damage(self) -> bool:
        """Whether a held SOS card or unite can still lead to damage.

        Counted: a damage card (every cog, or every unlured one -- a lured
        cog wakes, so that one still lands eventually); a restock of an
        attack track the toon is trained in, or of every track; a trap
        card when someone holds a Lure to spring it; a Gag-Up unite on an
        attack track or on all of them. NOT counted: heals, Lure and
        Toon-Up restocks, cogs-miss and toons-hit -- each helps, none of
        them can take a hit point off a cog.

        Finite and strictly spent, like a pink slip, so counting them does
        not threaten the termination argument in `simulator.legal_actions`.
        """
        from . import sos as sos_mod

        attack = (Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP)
        lure_held = any(
            n > 0 and track == Track.LURE
            for toon in self.active_toons()
            for (track, _level), n in toon.gag_counts.items())
        for toon in self.active_toons():
            trained = {t for t in attack if toon.track_exp.get(t, 0) > 0}
            for name in (getattr(toon, "sos_cards", {}) or {}):
                card = sos_mod.BY_NAME.get(name)
                if card is None or toon.sos_held(name) <= 0:
                    continue
                if card.kind in (sos_mod.DAMAGE_ALL, sos_mod.DAMAGE_UNLURED):
                    return True
                if card.kind == sos_mod.RESTOCK and (
                        (card.track is None and trained)
                        or card.track in trained):
                    return True
                if card.kind == sos_mod.TRAP and lure_held:
                    return True
            if getattr(toon, "unites_held", 0) > 0:
                stock = getattr(toon, "unite_stock", {}) or {}
                for (kind, track), n in stock.items():
                    if (kind == "gag_up" and n > 0
                            and (track is None or track in trained)):
                        return True
        return False

    def can_still_damage(self) -> bool:
        """Whether any sequence of remaining gags can hurt a cog.

        A solo toon that cannot damage cogs cannot win, however much laff
        or however many gags it holds. Pink slips, damage/restock SOS
        cards, and Gag-Up unites all count as a way back -- see
        `_consumables_can_damage`. So this is the real losing condition,
        and "the pouch is empty" is only its most obvious case.

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
        # Pooled across the team, not per toon -- the whole difference
        # between the solo rule and the party one. Eighty Lures and no
        # attacks loses solo; in a party it's a fine support loadout,
        # because the damage is somebody else's job. Asking toon-by-toon
        # would call a winnable fight lost the moment one member ran out.
        #
        # A pink slip removes a cog outright, checked before the track
        # check so "eighty Lures and no attacks" doesn't read as lost
        # while a fire sits unused.
        if any(toon.fires > 0 for toon in self.active_toons()):
            return True

        # An attack gag in hand is the common case, so it is checked
        # before the cards: the answer is an OR of these tests, so their
        # order changes only the cost (this was a third of a search).
        for toon in self.active_toons():
            for (track, level), n in toon.gag_counts.items():
                if (n > 0 and track in _ATTACK_TRACKS
                        and toon.track_exp.get(track, 0) > 0
                        and (ALLOW_LEVEL_7 or level != LEVEL_SEVEN)):
                    return True

        # Cards and unites that put damage back in reach -- without this
        # a toon down to Lure with a Restock All in hand read as LOST,
        # and the solver couldn't value climbing back out of the very
        # state a solo VP reaches after spending its power gags.
        if self._consumables_can_damage():
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


_ATTACK_TRACKS = frozenset({Track.THROW, Track.SQUIRT, Track.SOUND, Track.DROP})


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

    # The name of an SOS Toon, when this action is calling one. An SOS
    # costs the toon's turn like any gag, so it belongs here -- see
    # solver/sos.py.
    #
    # Like a fire, it has no track and no level, so anything guarding on
    # `is_pass` alone will mistake it for a gag and reach for
    # `action.track.value`; `is_pass` below excludes both for that
    # reason.
    sos: Optional[str] = None

    @property
    def is_pass(self) -> bool:
        return self.track is None and not self.fire and self.sos is None

    def describe(self) -> str:
        if self.sos:
            return f"SOS {self.sos}"
        if self.fire:
            return f"fire -> {self.target_index}"
        if self.is_pass:
            return "pass"
        target = "all" if self.target_index is None else self.target_index
        return f"{self.track.value}/{self.level} -> {target}"


# The one pass action. Actions are compared by value, so this is a
# convenience rather than a singleton anything depends on.
PASS = Action(track=None, level=0, target_index=None)
