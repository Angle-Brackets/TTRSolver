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

THIS IS ONE OF THREE WEIGHT SYSTEMS
-----------------------------------
`weights.QUICK_W` and `weights.GREEDY_W` price several of the
same concepts -- laff, gags spent, overkill, kills -- on their own
scales, because the two fast scorers take no objective and cannot read
these fields. `docs/scoring.md` is the inventory: every term, which
system defines it, who reads it, and where two of them disagree. A term
added here that the fast scorers cannot see is only half-wired, which
is exactly what happened to `waste_weight`.
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

    # Charged for damage aimed at hit points that aren't there, scaled by
    # how scarce the wasted gag is (`party_search.waste_penalty`) -- a
    # flat per-gag price can't tell a Railroad that was the only kill
    # from one that was mere overkill.
    #
    # DO NOT WIRE INTO `step_reward`: the solo search's labels come from
    # `solve()` under this objective, and `fitted.py`'s weights are
    # fitted to those labels, so changing `step_reward` would silently
    # invalidate them. This term stays on the party path only, which
    # keeps solo numbers bit-identical.
    #
    # Reaches even less than that: only `party_search.evaluate` and
    # `tools/gen_party_data.py` read it (via `waste_penalty`).
    # `_quick_score` takes no objective, so `hybrid.climb`'s RL-policy
    # ranking can't see this field at all -- that path's overkill is
    # charged only by `QUICK_W["waste"]` (0.0). See docs/scoring.md.
    waste_weight: float = 0.0

    # Extra charge for a level 7 (`data.POUCH_EXEMPT_LEVEL`): exempt from
    # the pouch and restocked on a different scale, which
    # `scarcity_cost`'s `1/max_carry` (saturating at 1) can't express --
    # it prices a Railroad like any other capacity-1 gag.
    #
    # Without this the search spends level 7s freely, rationally so
    # inside one battle's horizon: on a maxed four-toon position a level
    # 7 appeared in 9 of 10 seeds, beating a line both cheaper (6.80 vs
    # 7.30) and less wasteful (3 damage vs 12) -- buying accuracy with a
    # cost that lands in the next, unmodelled fight.
    rare_gag_premium: float = 0.0

    # Charged when a toon goes sad. `laff_weight` alone prices a toon at
    # 6 laff at six points, when what is actually lost is a combatant,
    # their whole pouch, and every action they would have taken. Nothing
    # restocks either, so this is closer to a partial loss than to
    # damage.
    toon_lost_penalty: float = 0.0

    # How much the SPREAD of a plan's outcomes counts against it (units
    # of standard deviation). At 0 the search is risk-neutral, which
    # looked wrong three ways: a Sound mix chosen for clearing by 3 over
    # one clearing by 15, Toon-Up never thrown as Lure insurance, and
    # `toon_lost_penalty` only firing in sampled outcomes where a toon
    # actually goes sad.
    #
    # LEFT AT 0.0 because it can't reach them either. Gag damage is
    # deterministic (`calc_toon_damage` at `trained_fraction=1.0`), so a
    # maxed toon's only variance is ACCURACY: both the 3-margin and
    # 15-margin Sound plans have identical outcome spread (stdev 31.20,
    # 96% clear). The wider margin isn't insurance against the dice --
    # it's insurance against the MODEL being wrong about damage (a toon
    # not quite maxed, or `trained_fraction` standing in for
    # untranscribed experience thresholds). That's parameter uncertainty,
    # which no weight over sampled returns can express; fixing it means
    # transcribing the real thresholds or searching a pessimistic damage
    # assumption instead.
    risk_aversion: float = 0.0

    # How much `state.cogs_remaining` raises the price of a gag -- a gag
    # spent on floor one of a building is dearer than the same gag on the
    # last cog, since nothing restocks a pouch mid-run. Replaces
    # `scarcity_cost`'s constant stand-in for this with the actual
    # quantity. Applied as `price * (1 + k * remaining)`.
    #
    # 0.15, measured. Strength sweep, 40 coordinated battles, horizon 30:
    # k 0.033/0.15/0.5/1.5 -> gag cost 3.01/2.60/2.58/2.21, win
    # 70.0%/67.5%/62.5%/52.5%. 0.033 does nothing (gag prices run
    # 0.23-4.70 against a 100 win bonus); past 0.15 conservation costs
    # more battles than it's worth -- gags saved for a floor never
    # reached aren't saved.
    #
    # Re-measured the win-rate cost on 120 fresh seeds at k=0.15: horizon
    # 0/10/30 -> gag cost 2.45/2.46/2.27, win 54.2%/53.3%/50.8%. So a full
    # building ahead buys about 7% of the pouch (mean level 3.36 -> 3.05)
    # for about 3 points of win rate now -- the intended trade, not a
    # free lunch. Horizon 0 is unchanged at every k, so the plain street
    # battle is undisturbed.
    #
    # NOT READ BY THE FAST SCORERS, and worse: `party_search._score_leaf`
    # builds a default `Objective()` purely to take this number, so the
    # party shortlist scales gag prices by 0.15 regardless of the
    # caller's actual objective. See docs/scoring.md.
    horizon_cost: float = 0.15
    # Flat charge per round -- the only term making the solver prefer
    # finishing sooner for its own sake. Nonzero by default on purpose:
    # at zero, a party that just lured the board can hold and burn a
    # round of the lure for free (measured: holds/round at 0.0/1.0/2.0 =
    # 0.75/0.38/0.00 on an uneven three-cog board).
    #
    # 1.0 rather than 2.0 because holding is sometimes genuinely right --
    # a toon whose only remaining gags would be wasted should hold, and a
    # cost that abolishes the option just trades one bad default for
    # another. SPEEDRUN overrides upward to make the round charge
    # dominate.
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
    # Was 0, which made "balanced" price laff and speed but not
    # resources at all -- a one-per-pouch Geyser (0.700) read as barely
    # dearer than a thirty-per-pouch Seltzer Bottle (0.400) on a scale
    # where winning is 100. The solver optimises one battle, so an
    # irreplaceable gag spent to end it now is genuinely optimal inside
    # that horizon; `scarcity_cost` is the only lever standing in for the
    # cost that lands in the next, unmodelled fight.
    #
    # 4.0: on a real position (Spin Doctor 104, Yesman 72) level 7s won
    # by 2.2 over an almost-free Lure; the choice flips between 1.0 and
    # 2.0, so 4.0 clears the crossover with room, well below CONSERVE's
    # 12. Checked as a nudge, not a ban: a 90hp cog only a Geyser
    # one-shots still gets the Geyser at every laff level from 60 to 8.
    scarcity_cost=4.0,

    # Charged for overkill, scaled by the gag's scarcity. `scarcity_cost`
    # can't tell whether a gag was NEEDED -- a Railroad prices 4.70
    # whether it was the only kill or a 120-damage answer to an 8hp cog.
    # This charges the difference, so "unless it's the only option" falls
    # out rather than being special-cased: a level 7 into 132hp wastes 0
    # and pays nothing extra; the same gag into 8hp wastes 112 and pays
    # nearly in full.
    #
    # Swept over 60 random party positions: the plan changes in 48% of
    # them, level 7 choices fall from 5 to 3. Checked as a nudge, not a
    # ban: with only a level 6 (100 dmg) and a level 7 (120) against a
    # 110hp cog, the level 7 is still chosen (overkill there is only 10).
    #
    # CHOSEN, not derived -- a preference, like every weight here.
    # Consumed only on the party path, see the field's own comment.
    waste_weight=20.0,

    # Level 7s are pouch-exempt and restocked on a different scale,
    # which `scarcity_cost` can't see (it prices them as any other
    # capacity-1 gag).
    #
    # Swept on the maxed four-toon position: level 7 appears in 2/8 plans
    # at 0.0 and 0/8 at 4.0+, most commonly replaced by 2 Foghorn + 2
    # Aoogah. 6.0 is a little past that crossover. Checked as a nudge:
    # where a level 7 is the only kill, it's still chosen.
    #
    # NOTE: most of this effect was a shortlist bug keeping 2 Foghorn + 2
    # Aoogah off the candidate list entirely, not the premium -- while
    # that held, no value here changed a single plan.
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
