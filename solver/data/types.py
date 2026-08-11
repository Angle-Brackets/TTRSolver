"""
The shapes game data comes in.

Everything in `data/` used to be parallel dicts keyed the same way -- one
for damage, one for organic damage, one for heals, one for names, one for
group levels, and Lure in a file of its own because it happened to be
rewritten first. Finding out what a gag does meant looking it up in six
places and knowing which of them Lure was exempt from.

These types collapse that: one object per gag, one per cog, one per cog
attack, each carrying everything known about it. A `None` field still means
"no source gives this", and accessors raise `NotImplementedError` naming the
gap rather than returning a silent default -- the no-guessing rule survives
the refactor, it just lives in one place now.

Levels are 1-indexed everywhere, matching the game and the wiki. Cog attack
rows are indexed by *relative* level (`cog.rel_index(level)`), because a
Micromanager's first row is level 4, not level 1 -- `Cog.attack_at` does
that arithmetic so callers stop repeating `level - levels[0]`.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

from ..state import Track

Range = Tuple[int, int]


def _require(value, what: str, where: str):
    if value is None:
        raise NotImplementedError(f"{what} for {where} is marked TODO in data/.")
    return value


@dataclass(frozen=True)
class Gag:
    """One gag: a (track, level) pair and everything known about it."""

    track: Track
    level: int
    name: str
    accuracy: int                       # propAcc, 0-100
    group: bool                         # hits every cog (or every toon)

    damage: Optional[Range] = None
    organic_damage: Optional[Range] = None
    heal: Optional[Range] = None
    organic_heal: Optional[Range] = None
    organic_accuracy: Optional[int] = None
    lure_rounds: Optional[int] = None    # Lure only

    @property
    def key(self) -> Tuple[Track, int]:
        return (self.track, self.level)

    def prop_accuracy(self, organic: bool = False) -> int:
        """Base accuracy, organic or not. Only Lure's accuracy changes when
        organic; every other track gets damage or healing instead, so this
        falls back to the ordinary value rather than pretending otherwise."""
        if organic and self.organic_accuracy is not None:
            return self.organic_accuracy
        return self.accuracy

    def damage_at(self, trained_fraction: float = 1.0,
                   organic: bool = False) -> int:
        span = self.organic_damage if organic else self.damage
        low, high = _require(span, "Damage", self)
        return round(low + (high - low) * trained_fraction)

    def heal_at(self, trained_fraction: float = 1.0,
                 organic: bool = False) -> int:
        span = self.organic_heal if organic else self.heal
        low, high = _require(span, "Heal", self)
        return round(low + (high - low) * trained_fraction)

    def rounds(self) -> int:
        return _require(self.lure_rounds, "Lure duration", self)

    def __str__(self) -> str:
        return f"{self.name} ({self.track.value} {self.level})"


@dataclass(frozen=True)
class CogAttack:
    """One attack a cog can use, across that cog's level range.

    `damage`, `accuracy` and `frequency` are per relative level and always
    the same length as the cog's `levels`. A `None` inside one of them is a
    per-cell gap; `modeled=False` marks an attack the wiki confirms exists
    but for which no frequency is published anywhere, so it can't be fired.
    """

    name: str
    display: str
    damage: Tuple[Optional[int], ...]
    accuracy: Tuple[Optional[int], ...] = ()
    frequency: Tuple[Optional[int], ...] = ()
    group: bool = False
    modeled: bool = True

    def damage_at(self, index: int) -> int:
        return _require(self.damage[index], "Damage", f"{self.display}")

    def accuracy_at(self, index: int) -> int:
        return _require(self.accuracy[index], "Accuracy", f"{self.display}")

    def frequency_at(self, index: int) -> int:
        return _require(self.frequency[index], "Frequency", f"{self.display}")

    def __str__(self) -> str:
        return self.display


@dataclass(frozen=True)
class Cog:
    """One cog type, with its attack roster and the levels it appears at."""

    key: str
    display: str
    department: str
    levels: Tuple[int, ...]
    attacks: Tuple[CogAttack, ...] = ()
    note: str = ""

    @property
    def rank(self) -> int:
        """Position on the department's corporate ladder, 1-8. [CONFIRMED]
        equal to the lowest level the cog appears at, for all 32 cogs --
        which is why there's no separate table. Feeds tgtDef."""
        return self.levels[0]

    @property
    def modeled_attacks(self) -> Tuple[CogAttack, ...]:
        return tuple(a for a in self.attacks if a.modeled)

    @property
    def unmodeled_attacks(self) -> Tuple[CogAttack, ...]:
        """Attacks the cog really has but the simulator can't fire, for want
        of a published frequency. Their existence means this cog's damage
        output is UNDER-estimated."""
        return tuple(a for a in self.attacks if not a.modeled)

    def rel_index(self, level: int) -> int:
        if level not in self.levels:
            raise ValueError(
                f"{self.display} does not appear at level {level} "
                f"(only {self.levels[0]}-{self.levels[-1]})")
        return level - self.levels[0]

    def _cell(self, attack_name: str, level: int, field: str):
        """One cell of one attack, raising with full context if it's a gap.

        Prefer these over CogAttack's own accessors: an attack doesn't know
        which cog owns it, so its message can only say "Glower Power", while
        this can say which cog, which level, and which module to go fix.
        """
        attack = self.attack(attack_name)
        value = getattr(attack, field)[self.rel_index(level)]
        if value is None:
            raise NotImplementedError(
                f"{self.key}/{attack_name} at level {level}: {field} is "
                f"marked TODO in data/{self.department}.py.")
        return value

    def damage_at(self, attack_name: str, level: int) -> int:
        return self._cell(attack_name, level, "damage")

    def accuracy_at(self, attack_name: str, level: int) -> int:
        return self._cell(attack_name, level, "accuracy")

    def frequency_at(self, attack_name: str, level: int) -> int:
        return self._cell(attack_name, level, "frequency")

    def attack(self, name: str) -> CogAttack:
        for a in self.attacks:
            if a.name == name:
                return a
        raise KeyError(f"{self.display} has no attack '{name}'")

    def __str__(self) -> str:
        return self.display


@dataclass(frozen=True)
class Department:
    """A cog department and its eight cogs, in ladder order."""

    key: str
    display: str
    cogs: Tuple[Cog, ...]

    def __getitem__(self, cog_key: str) -> Cog:
        for cog in self.cogs:
            if cog.key == cog_key:
                return cog
        raise KeyError(f"{self.display} has no cog '{cog_key}'")

    def __iter__(self):
        return iter(self.cogs)

    def __len__(self) -> int:
        return len(self.cogs)

    def __contains__(self, cog_key) -> bool:
        return any(c.key == cog_key for c in self.cogs)

    def keys(self):
        return [c.key for c in self.cogs]

    def items(self):
        return [(c.key, c) for c in self.cogs]

    def values(self):
        return list(self.cogs)

    def get(self, cog_key: str, default=None):
        try:
            return self[cog_key]
        except KeyError:
            return default
