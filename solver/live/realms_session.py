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
    """A state, or the reasons there is not one. Never both.

    `boss` and `suit_ids` ride along for the boss tracker, and default
    to "not a boss fight" so every existing two-argument build is
    unchanged.
    """
    state: Optional[BattleState]
    problems: List[str]
    boss: Optional["BossBattle"] = None
    battle_id: Optional[int] = None
    suit_ids: Tuple[int, ...] = ()
    # The OTHER toons standing in this battle, read the way the player's
    # toon is. Only the playouts use them (pickup mode: your move chosen,
    # theirs modelled); the board everything else sees still counts them
    # as `allies_standing`. A teammate who cannot be read is left out
    # rather than guessed at.
    allies: Tuple[ToonState, ...] = ()

    def __bool__(self) -> bool:
        return self.state is not None


# WHICH BOSS a boss-room battle belongs to. Read from the client's own DC
# declarations, not from Open Toontown: `DistributedBattleFinal`
# declares `setBossCogId(uint32) required`, alongside `setBattleNumber`
# and `setBattleSide`, and the boss object's class names the fight. This
# is the client's own declaration, so it is evidence for this client --
# nothing here carries over to the other front end, which has no such
# stream and identifies the fight by location instead.
BOSS_BATTLE_CLASS = "DistributedBattleFinal"
BOSS_CLASSES = {"DistributedSellbotBoss": "vp",
                "DistributedCashbotBoss": "cfo",
                "DistributedLawbotBoss": "cj",
                "DistributedBossbotBoss": "ceo"}


# Battles that are one floor of several, by the battle object's own class.
# More floors may follow and their cogs are unknown, so the playouts keep
# a value on the pouch. Boss rooms are named separately (`boss_of`).
MULTI_FLOOR_BATTLES = frozenset({
    "DistributedBattleBldg", "DistributedCogdoBattleBldg",
    "DistributedLevelBattle", "DistributedBattleFactory",
    "DistributedCountryClubBattle"})


def battle_kind(battle) -> str:
    return ("facility" if getattr(battle, "dclass", None) in MULTI_FLOOR_BATTLES
            else "street")


class BossBattle(NamedTuple):
    """A boss-room battle, as the stream states it."""
    kind: str
    # The boss object's doId. A new one is a new fight, even of the same
    # kind -- which is what restarts the count between two VPs.
    boss_id: int
    # Recorded, not yet used to set the round: whether it counts from 0
    # or 1 has not been observed, and `BossTracker` infers the round
    # from cogs defeated instead. Kept so the first real fight shows it.
    battle_number: Optional[int]
    side: Optional[int]
    # Toons in the whole fight, both sides, or None if the boss does not
    # say. [OPEN TOONTOWN SOURCE] `DistributedBossCog.setToonIds(toonIds,
    # battleA, battleB)` -- not yet seen on this stream, so it is read
    # where present and nothing is assumed where it is not. It matters
    # because one toon in your battle may be a solo VP or one side of a
    # two-player one, which meet twenty cogs a round and ten.
    players: Optional[int] = None


def boss_of(listener, battle) -> Optional[BossBattle]:
    """The boss fight `battle` belongs to, or None for any other battle."""
    if getattr(battle, "dclass", None) != BOSS_BATTLE_CLASS:
        return None
    boss_id = battle.get("setBossCogId")
    if isinstance(boss_id, (list, tuple)):
        boss_id = boss_id[0] if boss_id else None
    if boss_id is None:
        return None
    boss_obj = listener.store.get(boss_id)
    kind = BOSS_CLASSES.get(getattr(boss_obj, "dclass", None))
    if kind is None:
        return None

    def _scalar(name):
        value = battle.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return value

    return BossBattle(kind, boss_id, _scalar("setBattleNumber"),
                      _scalar("setBattleSide"), _players(boss_obj))


def _players(boss_obj) -> Optional[int]:
    """Toons in the boss fight from `setToonIds`, or None."""
    value = boss_obj.get("setToonIds") if boss_obj is not None else None
    if isinstance(value, (list, tuple)) and value:
        toons = value[0]
        if isinstance(toons, (list, tuple)) and toons:
            return len(toons)
    return None


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
    # Toon-Up and Gag-Up only. The categories decode off the in-game
    # menu -- see `realms.RESISTANCE_CATEGORIES` -- so Jellybeans are
    # excluded (a battle cannot spend one) and so is Toon-Down, which is
    # CUSTOM TO REALMS and does not exist in the game this solver is
    # for. Counting either would inflate the pouch with unites the
    # search can never play.
    #
    # Still one number, so it cannot tell a Toon-Up unite from a Gag-Up.
    # That is now a modelling gap rather than a missing reading:
    # `realms.gag_up_tracks` decodes the finer answer and nothing
    # consumes it, because `ToonState.unites_held` is an int.
    if max_unites:
        messages = obj.get("setResistanceMessages")
        held = realms_mod.battle_unites(messages)
        if held:
            toon.unites_held = min(held, int(max_unites))
            # WHICH ones, so a toon carrying only a Lure restock is not
            # offered a Squirt one. Toon-Up keys on the kind alone --
            # the wire gives a count per value but the values are the
            # build's own, and Realms is not TTR -- while Gag-Up keys on
            # the track, which the menu names exactly.
            by_kind = realms_mod.parse_resistance(messages) or {}
            stock = {}
            if by_kind.get("toon_up"):
                stock[("toon_up", None)] = by_kind["toon_up"]
            for track, count in (realms_mod.gag_up_tracks(messages)
                                 or {}).items():
                if count > 0:
                    stock[("gag_up", track)] = count
            toon.unite_stock = stock
            # And WHICH Toon-Up unites this build issues. Realms offers
            # 10/20/40/80/MAX where TTR offers 20/35/50/65/80, so
            # without this the heal predicted is simply the wrong
            # number. Set on the state, never on `unites.TOON_UP_VALUES`
            # -- that table is TTR's and docs/realms.md keeps it so.
            toon.toon_up_values = realms_mod.TOON_UP_VALUES

    # SOS CARDS. `setNPCFriendsDict` names them exactly, so unlike the
    # unites this loses nothing. The cap limits how many CALLS the
    # solver may plan, never which cards exist.
    if max_sos:
        cards = realms_mod.parse_npc_friends(obj.get("setNPCFriendsDict"))
        if cards:
            # ONLY NAMES `sos.BY_NAME` KNOWS. `npc_names()` maps every
            # NPC in the game -- 593 of them, of which 29 are SOS cards
            # -- so a stray id in the dict arrives here as a perfectly
            # plausible name like "Al Capella". `legal_actions` would
            # then offer calling it and `apply_toon_action` would raise
            # `KeyError` on `BY_NAME[action.sos]`, inside the search's
            # child process, where it looks like a search that failed
            # rather than a card that does not exist. `_sos_probes`
            # already filters this way, which is why the POLICY merely
            # went quiet while the search died.
            from .. import sos as sos_mod

            cards = {name: count for name, count in cards.items()
                     if name in sos_mod.BY_NAME}
        if cards:
            # EVERY CARD TYPE, each capped at the budget -- not the first
            # `budget` cards alphabetically. This used to walk the names in
            # sorted order and stop once the cap was spent, which decided
            # WHICH cards exist by spelling: at a cap of 3, a deck holding
            # Barnacle Bessie x2 and Clumsy Ned x28 gave the solver those
            # two and nothing else, and Professor Pete (Restock All),
            # Flippy and Daffy Don never reached it. That contradicted the
            # comment above it, and it is a large part of why the panel
            # "never uses SOS cards" on Realms: the restock and heal cards
            # a solo VP turns on were filtered out before scoring began.
            #
            # The cap still bounds CALLS: a solo toon calls at most one
            # card a round, and `AdviceWorker.note_spent` charges each
            # call against `remaining("sos")`, which feeds this budget, so
            # the total across a fight never exceeds what the box says.
            budget = int(max_sos)
            toon.sos_cards = {name: min(int(count), budget)
                              for name, count in cards.items() if count > 0}
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

    allies = []
    for do_id in members.toons:
        if do_id == player_do_id:
            continue
        obj = listener.store.get(do_id)
        if obj is None:
            continue
        # Their slips, cards and unites are not ours to plan with, and
        # the teammate model does not use them: zero.
        ally, why = toon_from_object(obj, max_fires=0, max_unites=0,
                                     max_sos=0)
        if ally is not None and not why and ally.laff > 0:
            allies.append(ally)

    return RealmsBuild(
        BattleState(toon=toon, cogs=cogs, round_num=round_num,
                    allies_standing=members.allies_standing,
                    kind=battle_kind(battle)), [],
        boss=boss_of(listener, battle),
        battle_id=getattr(battle, "do_id", None),
        suit_ids=tuple(members.suits),
        allies=tuple(allies))


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
