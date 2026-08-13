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
from typing import Dict

from .. import data
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
    # Flat charge per round. The only term that makes the solver prefer
    # finishing sooner for its own sake; without it, a line that stalls
    # safely forever costs nothing but the gags it spends.
    turn_cost: float = 0.0
    # Multiplier on laff lost. Raise it to play defensively.
    laff_weight: float = 1.0

    win_bonus: float = 100.0
    loss_penalty: float = 100.0

    def gag_price(self, track: Track, level: int) -> float:
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
            limit = data.gag(track, level).max_carry or 1
            price += self.scarcity_cost * (1.0 / limit)
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
    description="The default. Mild gag cost, damage counted at face value.",
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

DEFAULT = BALANCED


def get(name: str) -> Objective:
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(f"no such objective {name!r}; "
                       f"have {sorted(PRESETS)}") from None
