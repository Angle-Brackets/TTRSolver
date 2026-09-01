"""
Hand-entered game data, split by table.

Every table below is annotated with a confidence tag:

  [CONFIRMED] - taken directly from the QED1224/Toontown-Resources guide
                (https://github.com/QED1224/Toontown-Resources), which is
                derived from decompiled Toontown Online source and
                cross-checked against the TTR wiki.
  [PARTIAL]   - some cells confirmed, others missing.
  [TODO]      - not yet entered; using this in the simulator would silently
                give wrong answers, so the callers raise instead.

Do not fill in a TODO with a plausible-looking guess -- pull the real
number from the source repo's Appendix A/B/C and update the tag to
[CONFIRMED] when you do. See docs/data-confidence.md for the full
inventory of what's solid and what isn't.

Modules:
  accuracy.py -- toon attack accuracy formula components
  gags.py     -- gag damage tables
  cogs.py     -- cog HP formula, department registry
  bossbot.py  -- Bossbot cog attack tables (freq / damage / accuracy)
  sellbot.py  -- Sellbot cog attack tables (same shape)
  cashbot.py  -- Cashbot cog attack tables (same shape)
  lawbot.py   -- Lawbot cog attack tables (same shape)

Everything is re-exported here, so `from solver import data` then
`data.AV_PROP_ACCURACY` works regardless of which module a table lives in.
"""
from .accuracy import (
    AV_PROP_ACCURACY,
    AV_LURE_BONUS_ACCURACY,
    AV_ORGANIC_PROP_ACCURACY,
    ORGANIC_ACCURACY_TRACKS,
    TRACK_EXP_BY_LEVEL,
    TGT_DEF_BY_LEVEL,
    TGT_DEF_RANK_1,
    TGT_DEF_RANK_2_PLUS,
    tgt_def,
    ACCURACY_CAP,
    ACCURACY_CAP_IS_SOFT_IN_GAME,
    ACCURACY_FLOOR,
    ACCURACY_FLOOR_EXEMPT_TRACKS,
    PREV_HITS_BONUS_PER_HIT,
    PREV_HITS_MAX_BONUS,
    PREV_HITS_MAX_PRIOR_HITS,
    TRAP_LURE_ACCURACY_BONUS,
    TRAP_EXTRA_LURE_ACCURACY_BONUS,
    TRAP_ACTIVATION_PREV_HITS,
)
from .types import Gag, CogAttack, Cog, Department
from .gags import (
    GAGS,
    gag,
    gags_in,
    ORGANIC_BONUS_PCT,
    organic_value,
    TOON_UP_MISS_FRACTION,
    EARLY_EXPIRY_ACCURACY_FLOOR,
    MAX_GAG_TRACKS,
    POUCH_CAPACITIES,
    MAX_POUCH,
    validate_loadout,
)
from .bossbot import BOSSBOT, BOSSBOT_COGS
from .cashbot import CASHBOT, CASHBOT_COGS
from .lawbot import LAWBOT, LAWBOT_COGS
from .sellbot import SELLBOT, SELLBOT_COGS
from .gags import (
    GAG_UNLOCK_EXP, TRACK_MAX_EXP, gag_exp_window, gag_unlock_exp,
)
from .cogs import (
    COG_DEPARTMENTS, GROUP_ATTACKS, all_cogs, cog, cog_max_hp,
    department_of, is_group_attack,
)

__all__ = [
    "GAG_UNLOCK_EXP",
    "TRACK_MAX_EXP",
    "gag_unlock_exp",
    "gag_exp_window",
    "GROUP_ATTACKS",
    "is_group_attack",
    "AV_PROP_ACCURACY",
    "AV_LURE_BONUS_ACCURACY",
    "AV_ORGANIC_PROP_ACCURACY",
    "ORGANIC_ACCURACY_TRACKS",
    "TRACK_EXP_BY_LEVEL",
    "TGT_DEF_BY_LEVEL",
    "TGT_DEF_RANK_1",
    "TGT_DEF_RANK_2_PLUS",
    "tgt_def",
    "ACCURACY_CAP",
    "ACCURACY_CAP_IS_SOFT_IN_GAME",
    "ACCURACY_FLOOR",
    "ACCURACY_FLOOR_EXEMPT_TRACKS",
    "PREV_HITS_BONUS_PER_HIT",
    "PREV_HITS_MAX_BONUS",
    "PREV_HITS_MAX_PRIOR_HITS",
    "TRAP_LURE_ACCURACY_BONUS",
    "TRAP_EXTRA_LURE_ACCURACY_BONUS",
    "TRAP_ACTIVATION_PREV_HITS",
    "GAGS",
    "gag",
    "gags_in",
    "Gag",
    "CogAttack",
    "Cog",
    "Department",
    "ORGANIC_BONUS_PCT",
    "TOON_UP_MISS_FRACTION",
    "organic_value",
    "EARLY_EXPIRY_ACCURACY_FLOOR",
    "MAX_GAG_TRACKS",
    "POUCH_CAPACITIES",
    "MAX_POUCH",
    "validate_loadout",
    "BOSSBOT_COGS",
    "CASHBOT_COGS",
    "LAWBOT_COGS",
    "SELLBOT_COGS",
    "cog_max_hp",
    "cog",
    "all_cogs",
    "department_of",
    "BOSSBOT",
    "SELLBOT",
    "CASHBOT",
    "LAWBOT",
    "COG_DEPARTMENTS",
]
