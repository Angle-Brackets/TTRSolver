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

Everything is re-exported here, so `from solver import data` then
`data.AV_PROP_ACCURACY` works regardless of which module a table lives in.
"""
from .accuracy import (
    AV_PROP_ACCURACY,
    AV_LURE_BONUS_ACCURACY,
    TGT_DEF_BY_LEVEL,
    ACCURACY_CAP,
    PREV_HITS_BONUS_PER_HIT,
    PREV_HITS_MAX_BONUS,
)
from .gags import GAG_DAMAGE_MINMAX
from .bossbot import BOSSBOT_COGS
from .cogs import cog_max_hp, COG_DEPARTMENTS

__all__ = [
    "AV_PROP_ACCURACY",
    "AV_LURE_BONUS_ACCURACY",
    "TGT_DEF_BY_LEVEL",
    "ACCURACY_CAP",
    "PREV_HITS_BONUS_PER_HIT",
    "PREV_HITS_MAX_BONUS",
    "GAG_DAMAGE_MINMAX",
    "BOSSBOT_COGS",
    "cog_max_hp",
    "COG_DEPARTMENTS",
]
