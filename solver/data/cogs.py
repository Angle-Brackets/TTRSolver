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
def _fill_unmodeled(spec):
    """Give `modeled=False` attacks a borrowed accuracy and frequency.

    [ASSUMED] -- NOT [CONFIRMED], and the distinction is the whole point.

    Twelve attacks across eight cogs are confirmed by the wiki to exist,
    with damage published, but NO accuracy or frequency anywhere. Nine
    of the twelve are GROUP attacks hitting the whole team for 3-21, so
    leaving them unfired understates cog threat in exactly the direction
    that flatters toons -- and worst for parties, which is the same
    shape as the group-cog-attacks gap fixed earlier.

    Open Toontown cannot supply them, checked rather than assumed: its
    tables give Mr Hollywood only PowerTrip 50 / RazzleDazzle 50 and
    Robber Baron only PowerTrip 50 / TeeOff 50 -- precisely the attacks
    already modelled. TTR added the rest in a rebalancing pass, so the
    Toontown Online lineage predates them and structurally has nothing
    to say. (One partial lead it does give: Big Wig's Throw Book at
    frequency 50. Not used here, since applying it alone would make one
    cog's mix sourced and the rest borrowed.)

    So each unmodeled attack borrows the MEAN of its own cog's modelled
    attacks at that level, and every attack is then rescaled so the
    level still sums to 100. Borrowing within the cog rather than across
    cogs matters: accuracy is per-cog, and shared attacks disagree at
    the same level 149 times against 19 agreements.

    This is a preference for being roughly right over being precisely
    silent, taken knowingly. If the wiki ever publishes the columns,
    delete this function -- do not tune it.
    """
    from .types import CogAttack
    import dataclasses

    modelled = [a for a in spec.attacks if a.modeled and a.frequency]
    unmodelled = [a for a in spec.attacks if not a.modeled]
    if not modelled or not unmodelled:
        return spec

    n = len(spec.levels)
    filled = []
    for attack in spec.attacks:
        if attack.modeled:
            filled.append(attack)
            continue
        acc, freq = [], []
        for i in range(n):
            accs = [a.accuracy[i] for a in modelled
                    if i < len(a.accuracy) and a.accuracy[i] is not None]
            frqs = [a.frequency[i] for a in modelled
                    if i < len(a.frequency) and a.frequency[i] is not None]
            acc.append(round(sum(accs) / len(accs)) if accs else None)
            freq.append(round(sum(frqs) / len(frqs)) if frqs else None)
        filled.append(dataclasses.replace(
            attack, accuracy=tuple(acc), frequency=tuple(freq),
            modeled=True))

    # Rescale so each level still sums to 100. `pick_cog_attack` walks a
    # cumulative frequency and would silently never reach the tail if
    # they summed higher.
    rescaled = []
    totals = [sum(a.frequency[i] for a in filled
                  if a.frequency[i] is not None) for i in range(n)]
    for attack in filled:
        freq = []
        for i in range(n):
            value = attack.frequency[i]
            freq.append(value if not totals[i]
                        else max(1, round(value * 100 / totals[i])))
        rescaled.append(dataclasses.replace(attack, frequency=tuple(freq)))

    # Rounding can leave the total off by a point or two; give the
    # remainder to the commonest attack rather than leaving a gap.
    fixed = list(rescaled)
    for i in range(n):
        drift = 100 - sum(a.frequency[i] for a in fixed)
        if drift:
            j = max(range(len(fixed)), key=lambda k: fixed[k].frequency[i])
            freq = list(fixed[j].frequency)
            freq[i] += drift
            fixed[j] = dataclasses.replace(fixed[j], frequency=tuple(freq))
    return dataclasses.replace(spec, attacks=tuple(fixed))


def _fill_department(dept):
    import dataclasses

    return dataclasses.replace(
        dept, cogs=tuple(_fill_unmodeled(c) for c in dept.cogs))


COG_DEPARTMENTS = {
    "bossbot": _fill_department(BOSSBOT),
    "sellbot": _fill_department(SELLBOT),
    "cashbot": _fill_department(CASHBOT),
    "lawbot": _fill_department(LAWBOT),
}


def cog(department: str, cog_key: str):
    """The Cog object for a department/type pair."""
    return COG_DEPARTMENTS[department][cog_key]


def department_of(cog_key: str) -> str:
    """Which department a cog belongs to, from its key alone.

    The plate's medallion gives the department directly, but it is
    unreadable below 900p while the head render still identifies the cog
    -- and a named cog already implies its department.
    """
    for name, dept in COG_DEPARTMENTS.items():
        for entry in dept:
            if entry.key == cog_key:
                return name
    raise KeyError(f"no such cog {cog_key!r}")


def all_cogs():
    """Every cog in the game, department order then ladder order."""
    for dept in COG_DEPARTMENTS.values():
        for c in dept:
            yield c


# Cog attacks that hit EVERY toon rather than one.
#
# [CONFIRMED] TTR wiki, which maintains this as a pair of categories --
# "Group Cog attacks" (14) and "Single Cog attacks" (54). Fetched via
# the MediaWiki API:
#
#   api.php?action=query&list=categorymembers
#           &cmtitle=Category:Group%20Cog%20attacks&cmlimit=500
#
# The two categories cover all 68 attack names in these tables exactly,
# with nothing left over on either side, so every attack is classified
# and none is guessed. Being group is a property of the ATTACK, not of
# the cog throwing it, which is why this is one set rather than a column
# in each department's table.
GROUP_ATTACKS = frozenset({
    "beguile",               # Beguile
    "close_the_loop",        # Close the Loop
    "flood_the_market",      # Flood the Market
    "guilt_trip",            # Guilt Trip
    "hostile_takeover",      # Hostile Takeover
    "money_talks",           # Money Talks
    "nickel_and_dime",       # Nickel and Dime
    "paradigm_shift",        # Paradigm Shift
    "power_trip",            # Power Trip
    "quake",                 # Quake
    "quash",                 # Quash
    "shake",                 # Shake
    "synergy",               # Synergy
    "tremor",                # Tremor
})


def is_group_attack(attack_name: str) -> bool:
    """Does this attack hit the whole team?

    Solo it makes no difference -- the lone toon is both the target and
    the group -- which is why the tables went so long without it.
    """
    return attack_name in GROUP_ATTACKS
