"""
What the solver is trying to do.

The search maximises expected reward, and the reward is a *choice*, not a
game rule. Nothing in Toontown says a Wedding Cake is worth 0.7 laff. These
knobs decide what "playing well" means, and different players mean
different things by it -- end the fight fast, take no damage, or hoard the
big gags for when they're actually needed.

Every term here is a modelling decision. None of it is [CONFIRMED] data,
and it is deliberately kept apart from solver/data/ for that reason.

WHAT MOVES THE ANSWER
---------------------
`gag_cost` and `scarcity_cost` are the two that visibly change play. With a
one-shot Opera Singer against three cogs the solver will lure first at low
gag cost -- buying insurance against the 5% whiff for almost nothing -- and
fire the Opera immediately once the cost rises, because the insurance stops
being free. Both are defensible; they are different players.

`scarcity_cost` is the more principled of the two. Rather than assuming
cost rises with gag level, it uses each gag's own carry limit: you can hold
thirty Cupcakes and exactly one Wedding Cake, so the Cake is thirty times
scarcer and is priced that way. That comes from data (`Gag.max_carry`)
rather than from a guess about levels.
"""
from dataclasses import dataclass
from typing import Dict, Optional

from .. import data
from ..data import gags as gags_mod
from ..state import Track


@dataclass(frozen=True)
class Objective:
    """The reward the search maximises."""

    name: str = "balanced"
    description: str = ""

    # Cost of spending a gag, as a multiple of its level (1-7).
    gag_cost: float = 0.1
    # Extra cost inversely proportional to how many of that gag fit in a
    # pouch, so one-per-pouch gags read as expensive without hard-coding
    # anything about levels.
    scarcity_cost: float = 0.0

    # Charged for damage aimed at hit points that are not there, scaled
    # by how scarce the wasted gag is -- see
    # `party_search.waste_penalty`. Wasting a level 7 (one per pouch)
    # must cost far more than wasting a level 1 (thirty per pouch),
    # which a flat per-gag price cannot express: before this, a gag cost
    # the same whether it was the only thing that would kill the cog or
    # simply the biggest thing in the pouch.
    #
    # READ THIS BEFORE WIRING IT INTO `step_reward`. It is consumed ONLY
    # by the party search. The solo search's labels come from `solve()`
    # under this objective and `search/fitted.py`'s weights were fitted
    # against those labels, so changing what `step_reward` returns
    # silently invalidates the fitted evaluator. Keeping the term on the
    # party path leaves the solo numbers bit-identical.
    waste_weight: float = 0.0

    # Extra charge for a gag that does not count against the pouch --
    # `data.POUCH_EXEMPT_LEVEL`, i.e. level 7. `scarcity_cost` prices a
    # gag as `1/max_carry`, which saturates at 1 and so treats a Railroad
    # exactly like any other capacity-1 gag. It is not: it is exempt from
    # the pouch and restocked on a different scale entirely.
    #
    # Without this the search spends level 7s freely, and rationally so
    # INSIDE ONE BATTLE, which is the only horizon it has. On a maxed
    # four-toon position a level 7 appeared in 9 of 10 seeds, beating a
    # line that was both cheaper (6.80 against 7.30) and less wasteful
    # (3 damage against 12) -- it was buying accuracy with a gag whose
    # real cost lands in the next fight, which is not modelled.
    rare_gag_premium: float = 0.0

    # Charged when a toon goes sad. `laff_weight` alone prices a toon at
    # 6 laff at six points, when what is actually lost is a combatant,
    # their whole pouch, and every action they would have taken. Nothing
    # restocks either, so this is closer to a partial loss than to
    # damage.
    toon_lost_penalty: float = 0.0

    # How much the SPREAD of a plan's outcomes counts against it, in
    # units of standard deviation. At 0 the search is risk-neutral: it
    # maximises expected value and is indifferent between a line that
    # always clears by 3 and one that usually clears by 30 and sometimes
    # not at all.
    #
    # That indifference is wrong for how the game is actually played,
    # and it showed up three separate ways: a Sound mix chosen because
    # it cleared the toughest cog by 3 damage over one clearing by 15;
    # Toon-Up never thrown as insurance against a Lure missing; and
    # `toon_lost_penalty` unable to bite because it only fires in the
    # sampled outcomes where a toon actually goes sad.
    #
    # Each of those is a variance complaint, not an expected-value one,
    # which is why none of the expected-value levers reached them.
    #
    # LEFT AT 0.0, BECAUSE IT DOES NOT REACH THEM EITHER, and measuring
    # why was worth more than the term. On the maxed board, the Sound
    # mix clearing the toughest cog by 3 and the one clearing by 15
    # have IDENTICAL outcome spread -- stdev 31.20 for both, clearing
    # 96% of the time each.
    #
    # They must. Gag damage here is deterministic: `calc_toon_damage`
    # interpolates at `trained_fraction=1.0`, so a maxed toon always
    # deals exactly max. Every bit of variance in a round therefore
    # comes from ACCURACY -- the Sound lands and both plans kill, or it
    # misses and neither does. The margin never gets a chance to matter.
    #
    # So the wider margin is not protection against the dice. It is
    # protection against the MODEL being wrong about the damage -- a
    # toon not quite maxed, or the interim `trained_fraction` standing
    # in for experience thresholds nobody has transcribed. That is
    # uncertainty about a parameter, not spread in an outcome, and no
    # weight over sampled returns can express it. Closing it properly
    # means either transcribing the minE/maxE thresholds so damage
    # varies with real experience, or searching against a pessimistic
    # damage assumption and comparing.
    risk_aversion: float = 0.0

    # How much `state.cogs_remaining` raises the price of a gag. A gag
    # spent on the first floor of a building is genuinely dearer than
    # the same gag spent on the last cog, because nothing restocks a
    # pouch mid-run -- `scarcity_cost` has been standing in for exactly
    # this with a constant, having no access to the quantity itself.
    #
    # Applied as `price * (1 + k * remaining)`, so the last fight of the
    # day charges the bare price and a full building ahead charges
    # several times it.
    #
    # 0.15 was measured, not picked. Strength sweep over 40 identical
    # coordinated battles at horizon 30, priced on one ruler:
    #
    #     k       gag cost   mean level   win
    #     0.033       3.01         3.57   70.0%   <- no effect, noise
    #     0.15        2.60         3.54   67.5%
    #     0.5         2.58         3.25   62.5%
    #     1.5         2.21         3.14   52.5%
    #
    # 0.033 does nothing: gag prices run 0.23 to 4.70 against a win
    # bonus of 100, so doubling them is a few percent of the signal.
    # Past 0.15 the conservation is bought with battles lost, which is
    # the wrong trade -- gags saved for a floor you never reach are not
    # saved.
    #
    # THE WIN RATE DOES COST SOMETHING, and 40 battles was too few to
    # see it. Re-measured over 120 fresh seeds at k = 0.15:
    #
    #     horizon   gag cost   mean level   win
    #     0             2.45         3.36   54.2%
    #     10            2.46         3.16   53.3%
    #     30            2.27         3.05   50.8%
    #
    # So a full building ahead buys 7% of the pouch for about 3 points
    # of win rate in the current fight. That is the intended trade and
    # not a free lunch -- whether it pays depends on how much the later
    # floors need the pouch, which one battle's search cannot see. The
    # mean gag level is the cleaner signal: 3.36 down to 3.05, the
    # search reaching for smaller gags rather than fewer.
    #
    # Horizon 0 is unchanged under every k tested, which is the check
    # that matters most: the street battle the solver has always
    # modelled is undisturbed.
    horizon_cost: float = 0.15
    # Flat charge per round. The only term that makes the solver prefer
    # finishing sooner for its own sake; without it, a line that stalls
    # safely forever costs nothing but the gags it spends.
    # Charged per round, for EVERY mode -- the default is nonzero on
    # purpose. At zero the objective asks neither for speed nor against
    # stalling, and the second half of that is the one that bites: a
    # party that has just lured the board can hold, spend nothing, and
    # burn a round of the lure for free. Measured on an uneven
    # three-cog board, toons held 0.75 times per round at 0.0, 0.38 at
    # 1.0, and 0.00 at 2.0.
    #
    # 1.0 rather than 2.0 because holding is sometimes genuinely right
    # -- a toon whose only remaining gags would be wasted should hold,
    # and a cost that abolishes the option trades one bad default for
    # another.
    #
    # SPEEDRUN overrides upward; it wants the round charge to dominate.
    turn_cost: float = 1.0
    # Multiplier on laff lost. Raise it to play defensively.
    laff_weight: float = 1.0

    win_bonus: float = 100.0
    loss_penalty: float = 100.0

    def gag_price(self, track: Track, level: int,
                  cogs_remaining: int = 0,
                  unlocked: int = 6) -> float:
        """What spending one of this gag costs the objective.

        `track=None` is a pass, which spends no gag and so is free. It is
        not free overall -- `turn_cost` still applies, and the cogs get
        their round -- but there is nothing out of the pouch to charge
        for.
        """
        if track is None:
            return 0.0
        price = self.gag_cost * float(level)
        if self.scarcity_cost:
            # `unlocked` is the HOLDER's training level in the track, so
            # scarcity is what the gag costs THAT toon. A carry limit is
            # not a property of the gag: a toon whose Trap tops out at
            # Trapdoor holds 3 of them, and one who has reached TNT holds
            # 7. Pricing both at 7 under-charged the first by more than
            # half. Defaults to a fully trained track, which is what this
            # assumed unconditionally before, so callers without a toon
            # in scope are unchanged.
            limit = gags_mod.carry_limit(track, level, unlocked) or 1
            price += self.scarcity_cost * (1.0 / limit)
        # What is still coming makes the same gag dearer. Defaults to 0
        # remaining, so every existing caller is unchanged.
        if cogs_remaining and self.horizon_cost:
            price *= 1.0 + self.horizon_cost * float(cogs_remaining)
        return price

    def step_reward(self, laff_lost: int, track: Track, level: int,
                     won: bool, lost: bool) -> float:
        """Reward for one round. Matches simulator.step's convention when
        left at its defaults, which is what keeps sampled play and searched
        play optimising the same thing."""
        reward = -self.laff_weight * float(laff_lost)
        reward -= self.gag_price(track, level)
        reward -= self.turn_cost
        if won:
            reward += self.win_bonus
        elif lost:
            reward -= self.loss_penalty
        return reward


BALANCED = Objective(
    name="balanced",
    description="The default. Mild gag cost, some regard for scarcity, "
                "damage counted at face value.",
    # Scarcity was 0 here, which made "balanced" balance laff against
    # speed and not against resources at all. A Geyser -- one per pouch
    # -- priced at 0.700 against a Seltzer Bottle's 0.400, on a scale
    # where winning is worth 100. Effectively free.
    #
    # It shows up because the solver optimises ONE battle. Spending an
    # irreplaceable gag to end a fight now is genuinely optimal inside
    # that horizon; the cost lands in the next fight, which is not
    # modelled. `scarcity_cost` is the only lever that stands in for it,
    # and it was switched off.
    #
    # Observed on a real position (Spin Doctor 104, Yesman 72): the
    # level 7s won by 2.2 points over a Lure that costs almost nothing.
    # Sweeping this, the choice flips between 1.0 and 2.0, so 4.0 is
    # past the crossover with room, and far below CONSERVE's 12.
    #
    # Checked that it is a nudge and not a ban: against a 90hp cog that
    # only a Geyser one-shots, the Geyser is still chosen at every laff
    # level from 60 down to 8.
    scarcity_cost=4.0,

    # Charged for overkill, scaled by the scarcity of what was thrown.
    # `scarcity_cost` prices a gag by how few fit in a pouch; it cannot
    # tell whether the gag was NEEDED. A Railroad is 4.70 whether it was
    # the only thing that would kill the cog or a 120-damage answer to a
    # cog with 8 hit points left.
    #
    # This charges the difference, and the "unless it is the only
    # option" case falls out rather than being special-cased: a level 7
    # into a 132hp cog wastes 0 and pays nothing extra, the same gag
    # into an 8hp cog wastes 112 and pays nearly in full.
    #
    # Swept over 60 random party positions at samples=12: the plan
    # changes in 48% of them, and level 7 choices fall from 5 to 3.
    # Checked that it is a nudge and not a ban, the same check
    # `scarcity_cost` got -- given only a level 6 (100 dmg) and a level 7
    # (120) against a 110hp cog, the level 7 is still chosen, because
    # there the overkill really is only 10.
    #
    # CHOSEN, not derived. Nothing in the game states it; it is a
    # preference about how to spend a pouch, like every other weight
    # here. Consumed only on the party path -- see the field comment.
    waste_weight=20.0,

    # Level 7s are pouch-exempt and restocked on a different scale, and
    # `scarcity_cost` cannot see that -- it prices them as "one per
    # pouch", the same as any capacity-1 gag.
    #
    # Swept on the maxed four-toon position, 8 seeds at samples=96:
    # level 7 appears in 2/8 plans at 0.0 and 0/8 at 4.0 and above, and
    # the most common plan becomes 2 Foghorn + 2 Aoogah. Set at 6.0, a
    # little past the crossover.
    #
    # Checked that it nudges rather than bans, the same check the other
    # two weights got: where a level 7 is the only gag that kills the
    # cog, it is still chosen.
    #
    # NOTE most of this effect was not the premium. A shortlist bug was
    # keeping 2 Foghorn + 2 Aoogah off the candidate list entirely, and
    # while that held, no value of this changed a single plan.
    rare_gag_premium=6.0,
)

SPEEDRUN = Objective(
    name="speedrun",
    description="End it fast. Charges per round and barely charges for "
                "gags, so it spends freely to save turns.",
    gag_cost=0.02, turn_cost=2.0,
)

CONSERVE = Objective(
    name="conserve",
    description="Hoard the big gags. Prices each gag by how few fit in a "
                "pouch, so level 7s come out only when nothing else works.",
    gag_cost=0.1, scarcity_cost=12.0,
)

SURVIVE = Objective(
    name="survive",
    description="Take no damage. Weights laff heavily and accepts long, "
                "gag-hungry fights to avoid being hit.",
    gag_cost=0.02, laff_weight=3.0,
)

GLASS_CANNON = Objective(
    name="glass cannon",
    description="Damage is cheap, turns and gags are cheap; only winning "
                "and losing matter. Closest to pure win probability.",
    gag_cost=0.0, laff_weight=0.25,
)

PRESETS: Dict[str, Objective] = {
    o.name: o for o in (BALANCED, SPEEDRUN, CONSERVE, SURVIVE, GLASS_CANNON)
}


def from_axes(caution: float = 0.3, thrift: float = 0.4,
              name: Optional[str] = None) -> Objective:
    """A playstyle from two knobs, each 0 to 1.

    The five presets are already points on a plane and the axes are
    visible in their numbers, so this interpolates rather than inventing
    anything:

        CAUTION  what a point of laff is worth. `laff_weight` runs
                 0.25 in glass cannon to 3.0 in survive, and it is the
                 ONLY field any preset uses to express risk.

        THRIFT   how dearly gags are held. Four fields move together --
                 `gag_cost`, `scarcity_cost`, `waste_weight` and
                 `rare_gag_premium` -- because no preset moves one
                 without the others.

    Roughly where the presets land:

        glass cannon   caution 0.00  thrift 0.0
        speedrun       caution 0.27  thrift 0.1   (also turn_cost 2)
        balanced       caution 0.27  thrift 0.4
        conserve       caution 0.27  thrift 1.0
        survive        caution 1.00  thrift 0.1

    The interpolation is linear between the extremes each field
    actually takes, so no value here is invented -- every endpoint is a
    number some preset already uses. What IS a choice is that the four
    thrift fields move together; nothing measured says they must, only
    that no preset separates them.

    UNMEASURED AS A CONTINUUM. The corners are the shipped presets and
    have been evaluated; the space between them has not. Treat an
    interior point as a preference, not as a tuned configuration.
    """
    caution = max(0.0, min(1.0, float(caution)))
    thrift = max(0.0, min(1.0, float(thrift)))

    def lerp(low: float, high: float, t: float) -> float:
        return low + (high - low) * t

    return Objective(
        name=name or f"caution {caution:.2f} / thrift {thrift:.2f}",
        description=(f"Two-axis playstyle: caution {caution:.2f}, "
                     f"thrift {thrift:.2f}."),
        # Caution: the glass cannon floor to the survive ceiling.
        laff_weight=lerp(0.25, 3.0, caution),
        # Thrift: each field from the loosest preset to the tightest.
        gag_cost=lerp(0.0, 0.10, thrift),
        scarcity_cost=lerp(0.0, 12.0, thrift),
        waste_weight=lerp(0.0, 20.0, thrift),
        rare_gag_premium=lerp(0.0, 6.0, thrift),
    )

DEFAULT = BALANCED


def get(name: str) -> Objective:
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(f"no such objective {name!r}; "
                       f"have {sorted(PRESETS)}") from None
