"""
Cog-level data that isn't department-specific: the HP formula and the
registry mapping a department name to its cog attack tables.
"""
from .bossbot import BOSSBOT_COGS
from .cashbot import CASHBOT_COGS
from .lawbot import LAWBOT_COGS
from .sellbot import SELLBOT_COGS


def cog_max_hp(level: int) -> int:
    """Cog max HP by level.

    [PARTIAL] -- the formula HP = (level+1)*(level+2) reproduces the wiki's
    own worked examples for levels 4 and 9 (30 and 110), but the wiki's
    stated level-12 value (200) does NOT match the formula's output (182).
    Re-verify levels 10-12 before trusting boss-tier fights.
    """
    x = level + 1
    return x * (x + 1)


# All four departments, 8 cogs each, transcribed from Appendices A/B/C of
# the QED1224/Toontown-Resources strategy guide (master branch). See each
# module's docstring for the confidence tag and the per-cell [TODO]s.
COG_DEPARTMENTS = {
    "bossbot": BOSSBOT_COGS,
    "cashbot": CASHBOT_COGS,
    "lawbot": LAWBOT_COGS,
    "sellbot": SELLBOT_COGS,
}
