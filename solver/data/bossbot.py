"""
Bossbot cog attack tables.

Each cog entry:
  "levels":        list of absolute levels this cog can appear at; index
                   into the per-attack lists is (cog.level - levels[0])
  "freq":          {attack_name: [freq% at each relative level]}
  "damage":        {attack_name: [(min,max) or fixed int, at each relative level]}
  "accuracy":      {attack_name: [accuracy% at each relative level]}
  "group_attacks": set of attack names that hit all toons

[CONFIRMED] freq + damage, from Toontown-Resources Appendix A/B.
[TODO] accuracy -- the Appendix C section wasn't fully captured; re-fetch
  https://github.com/QED1224/Toontown-Resources before relying on Bossbot
  cog-accuracy numbers. mechanics.cog_attack_damage_and_accuracy raises
  while these are None rather than inventing a number.
"""

BOSSBOT_COGS = {
    "flunky": {
        "levels": [1, 2, 3, 4, 5],
        "freq": {
            "pound_key":   [30, 35, 40, 45, 50],
            "shred":       [10, 15, 20, 25, 30],
            "clip_on_tie": [60, 50, 40, 30, 20],
        },
        "damage": {
            "pound_key":   [2, 2, 3, 4, 6],
            "shred":       [3, 4, 5, 6, 7],
            "clip_on_tie": [1, 1, 2, 2, 3],
        },
        "accuracy": None,  # TODO
        "group_attacks": set(),
    },
    "pencil_pusher": {
        "levels": [2, 3, 4, 5, 6],
        "freq": {
            "fountain_pen":   [20, 20, 20, 20, 20],
            "rub_out":        [20, 20, 20, 20, 20],
            "finger_wag":     [35, 30, 25, 20, 15],
            "write_off":      [5, 10, 15, 20, 25],
            "fill_with_lead": [20, 20, 20, 20, 20],
        },
        "damage": {
            "fountain_pen":   [2, 3, 4, 6, 9],
            "rub_out":        [4, 5, 6, 8, 12],
            "finger_wag":     [1, 2, 2, 3, 4],
            "write_off":      [4, 6, 8, 10, 12],
            "fill_with_lead": [3, 4, 5, 6, 7],
        },
        "accuracy": None,  # TODO
        "group_attacks": set(),
    },
    "yesman": {
        "levels": [3, 4, 5, 6, 7],
        "freq": {
            "rubber_stamp":  [35, 35, 35, 35, 35],
            "razzle_dazzle": [25, 20, 15, 10, 5],
            "synergy":       [5, 10, 15, 20, 25],
            "tee_off":       [35, 35, 35, 35, 35],
        },
        "damage": {
            "rubber_stamp":  [2, 2, 3, 3, 4],
            "razzle_dazzle": [1, 1, 1, 1, 1],
            "synergy":       [4, 5, 6, 7, 8],
            "tee_off":       [3, 3, 4, 4, 5],
        },
        "accuracy": None,  # TODO
        "group_attacks": {"synergy"},  # Yesmen are the only Bossbot with a group attack
    },
    # micromanager, downsizer, head_hunter, corporate_raider, the_big_cheese:
    # TODO, same shape as above -- see Toontown-Resources Appendix A/B.
}
