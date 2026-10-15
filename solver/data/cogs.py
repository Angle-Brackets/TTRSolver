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

    A single formula without the +14 term is right for 1-11 and wrong
    from 12 up (182 vs TTR's 196) -- not a wiki inconsistency but a
    balance change, TTR 3.0.0: "Decreased Level 12 Cog health very
    slightly. Level 13+ Cogs use a different formula." The wiki's own
    worked example at level 16 -- (17)(18) + 14 = 320 -- matches its
    table, as do all 20 published rows (asserted in tests/test_data.py).
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
    are GROUP attacks hitting the whole team for 3-21, so leaving them
    unfired understates cog threat in the direction that flatters toons
    (worst for parties).

    Open Toontown cannot supply them, checked rather than assumed: its
    tables give only the attacks already modelled for these cogs, since
    TTR added the rest in a later rebalancing pass the Toontown Online
    lineage predates.

    So each unmodeled attack borrows the MEAN of its own cog's modelled
    attacks at that level, then every attack is rescaled so the level
    still sums to 100. Borrowing within the cog rather than across cogs
    matters: accuracy is per-cog, and shared attacks disagree at the
    same level 149 times against 19 agreements.

    A preference for being roughly right over precisely silent, taken
    knowingly. If the wiki ever publishes the columns, delete this
    function -- do not tune it.
    """
    from .types import CogAttack
    import dataclasses

    modelled = [a for a in spec.attacks if a.modeled and a.frequency]
    unmodelled = [a for a in spec.attacks if not a.modeled]
    blank = ([a for a in spec.attacks
              if a.modeled and all(v is None for v in a.accuracy)]
             if BORROW_BLANK_ACCURACY else [])
    if not modelled or (not unmodelled and not blank):
        return spec

    n = len(spec.levels)
    filled = []
    for attack in spec.attacks:
        # A MODELLED attack with an entirely empty accuracy column needs
        # the same borrow. `the_big_cheese/glower_power` is the case:
        # its damage is published and its frequency known, but the wiki
        # gives no accuracy at any level and the guide gave three values
        # for one attack, so the cell was left [TODO]. That made the Big
        # Cheese unusable -- it is why the street pools exclude it -- and
        # the CEO's second battle opens with one, so "roughly right over
        # precisely silent" applies here exactly as it does below.
        blank_accuracy = (BORROW_BLANK_ACCURACY
                          and all(v is None for v in attack.accuracy))
        if attack.modeled and not blank_accuracy:
            filled.append(attack)
            continue
        if attack.modeled and blank_accuracy:
            acc = []
            for i in range(n):
                accs = [a.accuracy[i] for a in modelled
                        if i < len(a.accuracy) and a.accuracy[i] is not None]
                acc.append(round(sum(accs) / len(accs)) if accs else None)
            filled.append(dataclasses.replace(attack, accuracy=tuple(acc)))
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



# ---------------------------------------------------------------------
# Boss-only levels 13-15
# ---------------------------------------------------------------------
# Three Bossbot cogs go above level 12, and only inside the Bossbot
# Clubhouse -- the CEO's first cog battle draws levels 9-14 and its
# second opens with a level 14 Big Cheese. The main tables stop at 12
# because that is the STREET range; the Big Cheese's own infobox carries
# the footnote "The Big Cheese can have three additional levels, up to
# level 15."
#
# DAMAGE IS [CONFIRMED], read from each cog's CogAttackTable on the wiki.
# Our stored arrays are an exact PREFIX of the wiki's eight levels per
# attack on all three cogs, which is how the extension was checked
# rather than trusted -- see tests/test_boss_levels.py.
#
# ACCURACY AND FREQUENCY ARE [ASSUMED], the only guess here. The wiki
# publishes neither at any level above 12, and Open Toontown's
# SuitBattleGlobals stores only five levels per cog same as we do, so
# that lineage has nothing above 12 either (checked, not assumed).
#
# So the last published value is CARRIED FORWARD FLAT -- a deliberately
# dull choice: extrapolating the visible trend would invent a curve,
# while a flat carry invents only "no further change". It errs toward
# weaker cogs (flattering toons), so treat any CEO clear rate as an
# upper bound. `solver.search.sensitivity` finds the recommended move
# unchanged across +-20 accuracy points, so this costs forecast
# precision rather than advice.
HIGH_LEVEL_DAMAGE = {
    ("bossbot", "head_hunter"): {
        "levels": (6, 7, 8, 9, 10, 11, 12, 13),
        "fountain_pen": (5, 6, 8, 10, 12, 14, 16, 18),
        "rolodex": (6, 7, 8, 9, 10, 11, 12, 13),
        "glower_power": (7, 8, 10, 12, 13, 15, 17, 18),
        "half_windsor": (8, 10, 12, 14, 16, 18, 20, 22),
        "head_shrink": (10, 12, 15, 18, 21, 23, 26, 29),
    },
    ("bossbot", "corporate_raider"): {
        "levels": (7, 8, 9, 10, 11, 12, 13, 14),
        "canned": (6, 7, 8, 9, 10, 11, 12, 13),
        "evil_eye": (12, 15, 18, 21, 24, 27, 30, 33),
        "play_hardball": (7, 8, 12, 15, 16, 20, 23, 24),
        "power_tie": (10, 12, 14, 16, 18, 20, 22, 24),
        "hostile_takeover": (10, 13, 14, 15, 18, 19, 20, 23),
    },
    ("bossbot", "the_big_cheese"): {
        "levels": (8, 9, 10, 11, 12, 13, 14, 15),
        "tee_off": (8, 11, 14, 17, 20, 22, 24, 26),
        "glower_power": (10, 12, 15, 18, 20, 22, 24, 26),
        "power_trip": (11, 13, 14, 16, 19, 21, 22, 24),
        "flood_the_market": (13, 15, 16, 18, 21, 23, 24, 26),
    },
}




# OFF BY DEFAULT, AND THAT IS THE POINT. A modelled attack whose accuracy
# column is entirely None is a deliberate [TODO] -- the wiki publishes no
# accuracy for it, so the cell was left missing so `accuracy_at` RAISES
# rather than substituting. Four tests depend on exactly that behaviour.
#
# `the_big_cheese/glower_power` is the case, which is why the street cog
# pools exclude the Big Cheese. The CEO's second battle opens with one,
# so `solver.ceo` turns this on and accepts a borrowed accuracy -- the
# same [ASSUMED] mechanism `_fill_unmodeled` already applies elsewhere,
# stated rather than smuggled.
#
# Anything measured with this on inherits an approximation. Leave it off
# unless you are modelling a fight that cannot be built without it.
BORROW_BLANK_ACCURACY = False

def _carry(column, extra: int):
    """Extend a per-level column by `extra`, repeating its last value.

    Pads with None when there is nothing to repeat, or when the last
    known value is itself None -- the point is never to invent a number,
    only to decline to change one.
    """
    column = tuple(column)
    if extra <= 0:
        return column
    last = column[-1] if column else None
    return column + (last,) * extra


def _extend_high_levels(spec):
    """Give the three Clubhouse cogs their boss-only levels.

    Raises rather than silently skipping if the published prefix does not
    match what we already store -- a mismatch would mean the wiki table
    and our table are describing different things, and quietly appending
    to that would corrupt the levels we do have.
    """
    import dataclasses

    table = HIGH_LEVEL_DAMAGE.get((spec.department, spec.key))
    if table is None:
        return spec

    levels = table["levels"]
    if tuple(spec.levels) == levels:
        return spec                        # already extended
    if tuple(spec.levels) != levels[:len(spec.levels)]:
        raise ValueError(
            f"{spec.key}: stored levels {spec.levels} are not a prefix of "
            f"the published {levels}")

    grown = []
    for attack in spec.attacks:
        published = table.get(attack.name)
        if published is None:
            raise ValueError(f"{spec.key}: no published damage for "
                             f"{attack.name}")
        have = len(attack.damage)
        if tuple(attack.damage) != published[:have]:
            raise ValueError(
                f"{spec.key}.{attack.name}: stored damage {attack.damage} is "
                f"not a prefix of the published {published}")
        extra = len(levels) - have
        grown.append(dataclasses.replace(
            attack,
            damage=published,
            # [ASSUMED] flat carry -- see the note above. An EMPTY or
            # all-None column pads with None rather than inventing a
            # number: `_fill_unmodeled` runs after this and borrows
            # across the cog's other attacks, which is a real source,
            # where a made-up value would not be.
            accuracy=_carry(attack.accuracy, extra),
            frequency=_carry(attack.frequency, extra),
        ))
    return dataclasses.replace(spec, levels=levels, attacks=tuple(grown))


def _fill_department(dept):
    import dataclasses

    return dataclasses.replace(
        dept, cogs=tuple(_fill_unmodeled(_extend_high_levels(c))
                         for c in dept.cogs))


COG_DEPARTMENTS = {
    "bossbot": _fill_department(BOSSBOT),
    "sellbot": _fill_department(SELLBOT),
    "cashbot": _fill_department(CASHBOT),
    "lawbot": _fill_department(LAWBOT),
}


def live_play_assumptions() -> None:
    """What the LIVE panels need that the data tables leave [TODO].

    A cog in front of the player has to be advised on, and a Big Cheese
    -- in a building, at levels 8 to 15 -- made every engine raise
    `MissingData` on Glower Power's accuracy, so the panel showed nothing
    useful for the whole fight. [OWNER] live play uses the assumed value
    rather than failing: the same borrow the simulated CEO fight already
    takes, stated in `_fill_unmodeled`. The tables keep the [TODO], and
    a process that never calls this still raises, which is what the data
    tests check.

    Called by each panel's `main` and as the INITIALIZER of each worker
    pool: those processes are spawned fresh and would otherwise start
    with the borrow off.
    """
    enable_blank_accuracy_borrow()


def enable_blank_accuracy_borrow() -> None:
    """Turn the borrow on and rebuild the tables.

    The departments are built at import, so flipping the flag alone
    changes nothing -- a caller that set it and carried on would get the
    old specs and no warning. Idempotent, and there is deliberately no
    way to turn it back off: half the process holding borrowed accuracy
    and half holding a [TODO] would be worse than either.
    """
    global BORROW_BLANK_ACCURACY, COG_DEPARTMENTS
    if BORROW_BLANK_ACCURACY:
        return
    BORROW_BLANK_ACCURACY = True
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
