"""
Cog-level data that isn't department-specific: the HP formula and the
registry mapping a department name to its cog attack tables.
"""
from .bossbot import BOSSBOT
from .cashbot import CASHBOT
from .lawbot import LAWBOT
from .sellbot import SELLBOT


# Cog HP by level, straight from the wiki's own table. [CONFIRMED]
# https://toontownrewritten.wiki/Health_of_Cogs
#
# Kept as an explicit table because it is what the wiki publishes; the
# formulas below reproduce it exactly and are asserted against it in
# tests/test_data.py.
COG_HP_BY_LEVEL = {
    1: 6,    2: 12,   3: 20,   4: 30,   5: 42,
    6: 56,   7: 72,   8: 90,   9: 110,  10: 132,
    11: 156, 12: 196, 13: 224, 14: 254, 15: 286,
    16: 320, 17: 356, 18: 394, 19: 434, 20: 476,
}

# The level at and above which the +14 boss-tier term applies. [CONFIRMED]
HP_BOOST_LEVEL = 12
HP_BOOST = 14


def cog_max_hp(level: int) -> int:
    """Cog max HP by level. [CONFIRMED] from the TTR wiki.

    https://toontownrewritten.wiki/Health_of_Cogs

        levels 1-11:  f(x) = (x + 1)(x + 2)
        levels 12+:   f(x) = (x + 1)(x + 2) + 14

    The old single-formula version was right for levels 1-11 and wrong for
    every level from 12 up: it returned 182 at level 12 where TTR gives 196.
    That is not a wiki inconsistency, it is a balance change --

        TTR 3.0.0 (2021-12-03) "Decreased Level 12 Cog health very slightly.
        Level 13+ Cogs use a different formula to determine their health."

    Before 3.0.0 a level-12 cog got a flat 10% boost to 200; since 3.0.0 the
    +14 term applies from level 12 upward and 200 became 196. The wiki's own
    worked example at level 16 -- (17)(18) + 14 = 320 -- matches its table,
    as do all 20 published rows (asserted in tests/test_data.py).
    """
    x = level + 1
    hp = x * (x + 1)
    if level >= HP_BOOST_LEVEL:
        hp += HP_BOOST
    return hp


# All four departments, 8 cogs each.
#
# Damage, attack rosters, single/group targeting and level ranges are
# [CONFIRMED] from the TTR wiki (each cog's own page, cross-checked against
# each attack's page). Frequency and accuracy are NOT published anywhere on
# the wiki and remain guide-derived and unverified -- see each module's
# docstring for the per-department breakdown and the TTR 4.0.0 changelog
# entry that makes those two columns actively suspect.
COG_DEPARTMENTS = {
    "bossbot": BOSSBOT,
    "sellbot": SELLBOT,
    "cashbot": CASHBOT,
    "lawbot": LAWBOT,
}


def cog(department: str, cog_key: str):
    """The Cog object for a department/type pair."""
    return COG_DEPARTMENTS[department][cog_key]


def all_cogs():
    """Every cog in the game, department order then ladder order."""
    for dept in COG_DEPARTMENTS.values():
        for c in dept:
            yield c
