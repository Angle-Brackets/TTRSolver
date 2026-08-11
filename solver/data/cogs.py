"""
Cog-level data that isn't department-specific: the HP formula and the
registry mapping a department name to its cog attack tables.
"""
from .bossbot import BOSSBOT_COGS


def cog_max_hp(level: int) -> int:
    """Cog max HP by level.

    [PARTIAL] -- the formula HP = (level+1)*(level+2) reproduces the wiki's
    own worked examples for levels 4 and 9 (30 and 110), but the wiki's
    stated level-12 value (200) does NOT match the formula's output (182).
    Re-verify levels 10-12 before trusting boss-tier fights.
    """
    x = level + 1
    return x * (x + 1)


COG_DEPARTMENTS = {
    "bossbot": BOSSBOT_COGS,
    # sellbot, cashbot, lawbot: TODO -- freq/damage/accuracy tables exist
    # in the same source, just not yet transcribed. Add one module per
    # department alongside bossbot.py and register it here.
}
