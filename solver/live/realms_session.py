"""Assembling a BattleState from Toontown Realms' Astron cluster.

DELIBERATELY A SECOND IMPLEMENTATION, not a branch inside
`session.py`. The two read completely different worlds and the shared
version would be a long chain of "if realms:" through code whose whole
job is to be careful about pixels.

  * `session.build_state` assembles a TTR fight from a Local API
    snapshot, a screen-read gag panel and `watch.CogReading`s. Every
    input is a measurement with a confidence, so most of that module is
    about refusing: unknown cogs, a failed pouch checksum, a department
    read below its margin.

  * this one assembles a Realms fight from typed fields. There is
    nothing to be uncertain about -- a cog's HP is an int the server
    sent -- so the refusals are of a different kind entirely: the object
    has not arrived yet, or two battles are running and we cannot tell
    which is yours.

Keeping them apart means the TTR path cannot regress because something
here changed, and neither one has to carry the other's hedging. What
they DO share is the output: both hand back a `BattleState` the solver
already knows how to search, and both return reasons instead of a state
rather than ever guessing at one.

WHAT COMES FROM WHERE, and it is worth being as strict about this as
the TTR side is:

  cogs        the suit objects named in the battle's `setMembers`
  lured       `setMembers`' lured index list, NOT a red-pixel count
  party size  `len(members.toons)`, which the TTR panel has to ask the
              player for
  laff        the toon object's `setHp` / `setMaxHp`
  pouch       `setInventory`
  slips       `setPinkSlips`
  training    `setTrackAccess`, and organic from `setTrackBonusLevel`

Realms balance must not leak into the solver's tables -- see
`docs/realms.md`. This module reads a POSITION, which is a different
thing from reading a rule.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple

from .. import data
from ..state import BattleState, CogState, ToonState
from . import realms as realms_mod


class RealmsBuild(NamedTuple):
    """A state, or the reasons there is not one. Never both."""
    state: Optional[BattleState]
    problems: List[str]

    def __bool__(self) -> bool:
        return self.state is not None


def cog_from_object(obj, lured: bool = False,
                    lure_level: Optional[int] = None,
                    rounds_elapsed: Optional[int] = None,
                    trap_level: Optional[int] = None,
                    trap_organic: bool = False
                    ) -> Tuple[Optional[CogState], List[str]]:
    """One suit object as a `CogState`, or why it cannot be."""
    problems: List[str] = []

    identity = realms_mod.parse_dna(obj.get("setDNAString"))
    level = realms_mod.cog_level(obj.get("setLevelDist"))
    hp = obj.get("setHP")
    max_hp = obj.get("setMaxHP")

    if identity is None:
        problems.append(f"cog {obj.do_id}: cannot name it from "
                        f"{obj.get('setDNAString')!r}")
    if level is None:
        problems.append(f"cog {obj.do_id}: no level yet")
    if hp is None or max_hp is None:
        problems.append(f"cog {obj.do_id}: no health yet")
    if problems:
        return None, problems

    department, cog_type = identity
    cog = CogState(department=department, cog_type=cog_type, level=level,
                   hp=int(hp), max_hp=int(max_hp))

    # A skelecog revives once rather than dying, which the solver models
    # as `revives`. Realms sends the count directly.
    revives = obj.get("setSkeleRevives")
    if revives:
        try:
            cog.status.revives = int(revives)
        except (AttributeError, TypeError, ValueError):
            pass

    if trap_level is not None and not lured:
        # A TRAP IS WATCHED, NOT READ. `setMembers` carries the slots and
        # is only re-broadcast on a membership change, so one laid
        # mid-round never resends and the roster still reads '99' under
        # a cog visibly standing on a TNT. The chosen attacks say what
        # was thrown and at whom.
        #
        # Not applied to a lured cog: a Lure springs the trap, so the
        # two states cannot coexist, and believing in a trap that has
        # already gone off would have the solver plan for damage it has
        # collected.
        from ..state import Track

        cog.status.trapped = True
        cog.status.trap_track = Track.TRAP
        cog.status.trap_level = trap_level
        cog.status.trap_organic = bool(trap_organic)

    if lured:
        if lure_level is None:
            # REFUSING RATHER THAN PICKING A LEVEL. `setMembers` says a
            # cog IS lured and never which gag did it, and the level is
            # not decoration: `mechanics.lure_can_expire_early` keys off
            # it, so a wrong level changes how likely the cog is to wake
            # -- the single number every Trap line depends on. Setting
            # `lured` without it does not even fail loudly in the right
            # place; the search raises `no gag at lure level None` deep
            # inside the cog phase.
            #
            # The level IS known whenever the Lure was thrown while this
            # reader was attached (see `_note_chosen_attacks`). It is
            # missing only when we joined a fight already in progress,
            # and then one round fixes it.
            return None, [f"cog {obj.do_id}: lured, but the Lure was "
                          f"thrown before this reader attached, so its "
                          f"level is unknown"]

        from ..data import gags as gags_mod
        from ..state import Track

        gag = gags_mod.gag(Track.LURE, lure_level)

        # HOW MUCH LURE IS LEFT IS COUNTED, NOT READ. Nothing in the DC
        # carries lure duration -- the whole file mentions "lure" nowhere
        # outside `setMembers`' untyped slots, and cogs publish only DNA,
        # level, HP, skelecog, revives and virtual. It is AI-side state
        # and is never distributed.
        #
        # What CAN be established: which Lure landed (from
        # `setChosenToonAttacks`) and how many rounds have gone by since
        # (from counting the battle's movies). Duration comes from OUR
        # table, so this is a TTR-consistent reading of a Realms
        # position rather than a measurement of Realms -- if its lure
        # durations differ, this is wrong in Realms and still right for
        # the solver being fed it.
        #
        # The floor of 1 is not decoration. The cog appearing in
        # `suits_lured` at all is direct evidence it has at least one
        # round left, and that observation outranks the arithmetic --
        # which is the safe direction anyway, since overestimating a
        # lure plans a combo the cog wakes up in the middle of.
        remaining = 1
        if rounds_elapsed is not None:
            try:
                remaining = max(1, gag.rounds() - int(rounds_elapsed))
            except (TypeError, ValueError):
                remaining = 1

        cog.status.apply_lure(gag.prop_accuracy(organic=False), remaining,
                              level=lure_level)

    return cog, []


def toon_from_object(obj, max_fires: int = 0, max_unites: int = 0,
                     max_sos: int = 0
                     ) -> Tuple[Optional[ToonState], List[str]]:
    """The player's toon object as a `ToonState`, or why it cannot be.

    `max_fires` caps the slips the solver may plan with, whatever the
    toon holds. It defaults to ZERO -- no fire is ever advised unless
    the player raises it -- because a slip is the one resource in the
    fight that costs real money to replace, and that is their call to
    make rather than the solver's.
    """
    problems: List[str] = []

    laff, max_laff = obj.get("setHp"), obj.get("setMaxHp")
    counts = realms_mod.parse_inventory(obj.get("setInventory"))
    tracks = realms_mod.parse_track_access(obj.get("setTrackAccess"))
    organic = realms_mod.parse_organic(obj.get("setTrackBonusLevel"))

    if laff is None or max_laff is None:
        problems.append(f"toon {obj.do_id}: no laff yet")
    if counts is None:
        problems.append(f"toon {obj.do_id}: no gag inventory yet "
                        f"(setInventory has not arrived)")
    if tracks is None:
        problems.append(f"toon {obj.do_id}: no gag training yet")
    if problems:
        return None, problems

    # Training LEVEL is not in setTrackAccess, which is only a flag per
    # track. Accuracy depends on it, so an owned track is taken as
    # maxed at 7 -- the same assumption `ToonState.track_exp` documents
    # for anything not modelling gag training, and the one that matches
    # how these tools get used.
    track_exp = {track: 7 for track in tracks}

    toon = ToonState(laff=int(laff), max_laff=int(max_laff),
                     track_exp=track_exp, gag_counts=counts,
                     organic_tracks=organic or frozenset())

    # PINK SLIPS. `setPinkSlips(uint8) required ownrecv db` on
    # DistributedToon -- the same ownrecv shape as `setInventory`, so it
    # only ever arrives by query, never on the broadcast stream, and
    # `ObjectStore.seen` already refreshes it on every fill because the
    # stream does not maintain it.
    #
    # Absent means ZERO rather than a refusal, and that asymmetry is
    # deliberate. A missing pouch makes advice impossible and rightly
    # blocks the state; a missing slip count only makes the advice more
    # conservative, and the fallback is the behaviour the panel had
    # before this was read at all. Blocking on it would turn a better
    # reading into a new way to get no advice.
    slips = obj.get("setPinkSlips")
    if slips is not None and max_fires:
        try:
            toon.fires = min(max(0, int(slips)), int(max_fires))
        except (TypeError, ValueError):
            problems.append(f"toon {obj.do_id}: setPinkSlips is "
                            f"{slips!r}, which is not a count")

    # UNITES. `setResistanceMessages`, same ownrecv shape. Both halves
    # are required, exactly as for slips: the wire says what is HELD and
    # the cap says what the player will SPEND, and neither alone may
    # grant one. A cap with no reading would invent a pouch; a reading
    # with no cap would spend a resource farmed from boss runs without
    # being asked.
    #
    # One number, so it cannot tell a Toon-Up unite from a Gag-Up --
    # `realms.parse_resistance` says why the categories are left
    # undecoded rather than guessed.
    if max_unites:
        held = realms_mod.parse_resistance(obj.get("setResistanceMessages"))
        if held:
            toon.unites_held = min(held, int(max_unites))

    # SOS CARDS. `setNPCFriendsDict` names them exactly, so unlike the
    # unites this loses nothing. The cap limits how many CALLS the
    # solver may plan, never which cards exist.
    if max_sos:
        cards = realms_mod.parse_npc_friends(obj.get("setNPCFriendsDict"))
        if cards:
            budget = int(max_sos)
            trimmed, spent = {}, 0
            for name in sorted(cards):
                if spent >= budget:
                    break
                take = min(cards[name], budget - spent)
                trimmed[name] = take
                spent += take
            toon.sos_cards = trimmed
    return toon, []


def player_toon_id(listener) -> Optional[int]:
    """Which toon is OURS, by the one field only we receive.

    `setInventory` is declared `ownrecv`: the pouch goes to the owning
    client and to nobody else. So among the toons on the cluster, the
    one whose inventory we hold is the one we are playing -- no
    configuration, no guessing at names.

    Returns None if that is ambiguous, which is the honest answer:
    advising the wrong toon's pouch is worse than declining.
    """
    holders = [t.do_id for t in listener.toons()
               if t.get("setInventory") is not None]
    return holders[0] if len(holders) == 1 else None


def pick_battle(listener, battles, player_do_id: Optional[int] = None):
    """(battle, reasons). Which of several battles is the player's.

    THE VP SPLITS FOUR TOONS TWO AND TWO, so a boss fight has TWO battle
    objects on the cluster and refusing whenever there is more than one
    -- which is what this used to do -- means the panel is silent for
    the entire fight it is most wanted in. Ordinary streets hit the same
    thing whenever another toon is fighting anywhere in the district.

    The roster settles it: our battle is the one whose `setMembers`
    lists our toon. Only if that cannot be established does it decline,
    because advising on somebody else's fight is worse than saying
    nothing.
    """
    if len(battles) == 1:
        return battles[0], []

    if player_do_id is None:
        player_do_id = player_toon_id(listener)
    if player_do_id is None:
        return None, [f"{len(battles)} battles running and no way to tell "
                      f"which is yours (no toon here holds an inventory)"]

    for battle in battles:
        members = realms_mod.parse_members(battle.get("setMembers"))
        if members is not None and player_do_id in members.toons:
            return battle, []
    return None, [f"{len(battles)} battles running and toon {player_do_id} "
                  f"is in none of their rosters yet"]


def build_state(listener, player_do_id: Optional[int] = None,
                round_num: int = 0, max_fires: int = 0,
                max_unites: int = 0, max_sos: int = 0) -> RealmsBuild:
    """A `BattleState` from what the listener currently holds.

    `player_do_id` names which toon is being advised. With one toon in
    the battle it is unambiguous and may be omitted; in a party it
    matters, because `toons[0]` is the toon the search plans for and
    picking the wrong one advises somebody else's pouch.
    """
    problems: List[str] = []

    battles = listener.battles()
    if not battles:
        return RealmsBuild(None, ["no battle on the cluster"])

    battle, why = pick_battle(listener, battles, player_do_id)
    if battle is None:
        return RealmsBuild(None, why)
    members = realms_mod.parse_members(battle.get("setMembers"))
    if members is None:
        return RealmsBuild(None, ["the battle has no roster yet"])
    if not members.suits:
        return RealmsBuild(None, ["the battle has no cogs in it"])
    if not members.toons:
        return RealmsBuild(None, ["the battle has no toons in it"])

    lured = set(members.lured_suits())

    # Trap damage depends on whether the TOON's Trap track is organic,
    # which is a property of the thrower rather than of the cog, so it
    # has to be read before the cogs are built.
    trap_is_organic = False
    player_obj = listener.store.get(
        player_do_id if player_do_id is not None else members.toons[0])
    if player_obj is not None:
        from ..state import Track

        organic = realms_mod.parse_organic(
            player_obj.get("setTrackBonusLevel"))
        trap_is_organic = bool(organic and Track.TRAP in organic)
    cogs: List[CogState] = []
    for do_id in members.suits:
        obj = listener.store.get(do_id)
        if obj is None:
            problems.append(f"cog {do_id}: not received yet")
            continue
        age = None
        if hasattr(listener, "lure_age"):
            age = listener.lure_age(do_id)
        trap = None
        if hasattr(listener, "trap_on"):
            trap = listener.trap_on(do_id)
        cog, why = cog_from_object(
            obj, lured=do_id in lured,
            lure_level=None if age is None else age[0],
            rounds_elapsed=None if age is None else age[1],
            trap_level=trap, trap_organic=trap_is_organic)
        problems.extend(why)
        if cog is not None:
            cogs.append(cog)

    if player_do_id is None:
        # OURS if we can tell, and only then the first seat. In a party
        # `toons[0]` is whoever joined first, and planning their pouch
        # while showing it as yours is the quietest possible way to give
        # wrong advice.
        player_do_id = player_toon_id(listener) or members.toons[0]
    elif player_do_id not in members.toons:
        problems.append(f"toon {player_do_id} is not in this battle")

    player = listener.store.get(player_do_id)
    if player is None:
        problems.append(f"toon {player_do_id}: not received yet")
        toon = None
    else:
        toon, why = toon_from_object(player, max_fires=max_fires,
                                     max_unites=max_unites,
                                     max_sos=max_sos)
        problems.extend(why)

    # Every reason at once, like `session.build_state`: being told one
    # thing at a time is the difference between fixing a setup and
    # playing whack-a-mole with it.
    if problems or toon is None or not cogs:
        if not cogs and not problems:
            problems.append("none of the battle's cogs have arrived")
        return RealmsBuild(None, problems)

    return RealmsBuild(
        BattleState(toon=toon, cogs=cogs, round_num=round_num,
                    allies_standing=members.allies_standing), [])


def describe(state: BattleState) -> str:
    lines = [f"toon {state.toon.laff}/{state.toon.max_laff} laff, "
             f"{sum(state.toon.gag_counts.values())} gags"
             + (f", {state.allies_standing} ally"
                f"{'' if state.allies_standing == 1 else 'ies'}"
                if state.allies_standing else ", solo")]
    for cog in state.cogs:
        entry = data.cog(cog.department, cog.cog_type)
        flag = " LURED" if cog.status.lured else ""
        lines.append(f"  {entry.display} (level {cog.level}) "
                     f"{cog.hp}/{cog.max_hp} hp{flag}")
    return "\n".join(lines)
