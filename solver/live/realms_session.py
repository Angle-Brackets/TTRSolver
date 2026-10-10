"""Assembling a BattleState from Toontown Realms' Astron cluster.

A SECOND IMPLEMENTATION, deliberately, not a branch inside
`session.py`: `session.build_state` reads TTR from pixels and a Local
API snapshot, so most of it is about refusing a low-confidence
measurement. Here the fields are typed -- a cog's HP is an int the
server sent -- so the refusals are a different kind: the object has not
arrived, or two battles are running and we cannot tell which is ours.
Keeping them apart means a change here cannot regress the pixel path.
Both hand back a `BattleState`, or reasons instead of one, never a guess.

WHAT COMES FROM WHERE:

  cogs        the suit objects named in the battle's `setMembers`
  lured       `setMembers`' lured index list, NOT a red-pixel count
  party size  `len(members.toons)`, which the TTR panel has to ask for
  laff        the toon object's `setHp` / `setMaxHp`
  pouch       `setInventory`
  slips       `setPinkSlips`
  training    `setTrackAccess`, and organic from `setTrackBonusLevel`

Realms balance must not leak into the solver's tables -- see
`docs/realms.md`. This module reads a POSITION, not a rule.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Tuple

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
    # The OTHER toons standing, read the way the player's own toon is.
    # Only the playouts use them (pickup mode: your move chosen, theirs
    # modelled); everything else still counts them as `allies_standing`.
    # A teammate who cannot be read is left out, not guessed at.
    allies: Tuple[ToonState, ...] = ()
    # The battle is a boss-room one, whether or not `boss` resolved. A
    # boss room's battle can arrive before its link to the boss does --
    # "unknown", which must not read as "not a boss fight".
    boss_room: bool = False

    def __bool__(self) -> bool:
        return self.state is not None


# WHICH BOSS a boss-room battle belongs to, from the client's own DC
# declarations (not Open Toontown): `DistributedBattleFinal` declares
# `setBossCogId(uint32) required` alongside `setBattleNumber` and
# `setBattleSide`, and the boss object's class names the fight. Evidence
# for this client only -- the TTR front end has no such stream and
# identifies a boss fight by location instead.
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
    # A new boss_id is a new fight, even of the same kind -- that's what
    # restarts the count between two VPs.
    boss_id: int
    # Recorded but unused: whether rounds count from 0 or 1 is
    # unobserved, and `BossTracker` infers the round from cogs defeated
    # instead. Kept so the first real fight shows it.
    battle_number: Optional[int]
    side: Optional[int]
    # Toons in the whole fight, both sides, or None if unstated.
    # [OPEN TOONTOWN SOURCE] `DistributedBossCog.setToonIds(toonIds,
    # battleA, battleB)` -- not yet seen live, so read where present and
    # assumed nowhere else. Matters because your battle may be a solo VP
    # or one side of a two-player one, which face twenty cogs vs. ten.
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
                    trap_organic: bool = False,
                    lure_organic: bool = False
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

    if cog.hp <= 0 and not getattr(cog.status, "revives", 0):
        # DYING, NOT ALIVE. [OWNER] a cog killed this round stays on the
        # field at 0 HP through its death animation, into the next turn.
        # Read as alive it drew every engine toward group gags and SOS
        # cards that "killed" cogs already dead: Moe Zart into a Mr.
        # Hollywood and three corpses. Marked rather than dropped so the
        # indices still match the roster the player targets by.
        cog.hp = 0
        cog.status.is_dead = True

    if trap_level is not None and not lured:
        # A trap is WATCHED, not read: `setMembers`' slot is only
        # re-broadcast on a membership change, so one laid mid-round
        # still reads '99'. The chosen attacks say what was thrown.
        #
        # Not applied to a lured cog -- a Lure springs the trap, so the
        # two cannot coexist, and believing in a sprung trap would plan
        # for damage already collected.
        from ..state import Track

        cog.status.trapped = True
        cog.status.trap_track = Track.TRAP
        cog.status.trap_level = trap_level
        cog.status.trap_organic = bool(trap_organic)

    if lured:
        if lure_level is None:
            # REFUSING RATHER THAN GUESSING A LEVEL. `setMembers` says a
            # cog IS lured but never with what, and the level is not
            # decoration -- `mechanics.lure_can_expire_early` keys off it,
            # so a wrong one changes how likely the cog wakes. The level
            # is known whenever the Lure landed while attached (see
            # `_note_chosen_attacks`); it's missing only when we joined a
            # fight already in progress, and one round then fixes it.
            return None, [f"cog {obj.do_id}: lured, but the Lure was "
                          f"thrown before this reader attached, so its "
                          f"level is unknown"]

        from ..data import gags as gags_mod
        from ..state import Track

        gag = gags_mod.gag(Track.LURE, lure_level)

        # Remaining Lure rounds are COUNTED, not read: nothing in the DC
        # carries duration (cogs publish only DNA, level, HP, skelecog,
        # revives, virtual), so this is our table's duration minus
        # rounds elapsed since the Lure landed (`setChosenToonAttacks`,
        # counted off the battle's movies) -- a TTR-consistent reading
        # of a Realms position, not a measurement of Realms itself.
        #
        # Floored at 1: the cog appearing in `suits_lured` at all is
        # direct evidence it has a round left, which outranks the
        # arithmetic -- and floor is the safe direction, since
        # overestimating plans a combo the cog wakes up inside.
        remaining = 1
        if rounds_elapsed is not None:
            try:
                remaining = max(1, gag.rounds() - int(rounds_elapsed))
            except (TypeError, ValueError):
                remaining = 1

        cog.status.apply_lure(gag.prop_accuracy(organic=lure_organic), remaining,
                              level=lure_level)

    return cog, []


def toon_from_object(obj, max_fires: int = 0, max_unites: int = 0,
                     max_sos: int = 0
                     ) -> Tuple[Optional[ToonState], List[str]]:
    """The player's toon object as a `ToonState`, or why it cannot be.

    `max_fires` caps the slips the solver may plan with regardless of
    how many the toon holds, and defaults to ZERO: a slip costs real
    money to replace, so advising one is the player's call, not ours.
    """
    problems: List[str] = []

    laff, max_laff = obj.get("setHp"), obj.get("setMaxHp")
    counts = realms_mod.parse_inventory(obj.get("setInventory"))
    tracks = realms_mod.parse_track_access(obj.get("setTrackAccess"))
    organic = realms_mod.parse_organic(obj.get("setTrackBonusLevel"))
    organic_levels = realms_mod.parse_organic_levels(obj.get("setTrackBonusLevel"))

    if laff is None or max_laff is None:
        problems.append(f"toon {obj.do_id}: no laff yet")
    if counts is None:
        problems.append(f"toon {obj.do_id}: no gag inventory yet "
                        f"(setInventory has not arrived)")
    if tracks is None:
        problems.append(f"toon {obj.do_id}: no gag training yet")
    if problems:
        return None, problems

    # setTrackAccess is only a per-track flag, not a level, so an owned
    # track is taken as maxed at 7 -- the same assumption
    # `ToonState.track_exp` documents elsewhere for unmodelled training.
    track_exp = {track: 7 for track in tracks}

    toon = ToonState(laff=int(laff), max_laff=int(max_laff),
                     track_exp=track_exp, gag_counts=counts,
                     organic_tracks=organic or frozenset(),
                     organic_levels=organic_levels or {})

    # PINK SLIPS. `setPinkSlips(uint8) required ownrecv db` -- same
    # ownrecv shape as `setInventory`, so only a query ever delivers it.
    #
    # Absent means ZERO, not a refusal: a missing pouch rightly blocks
    # the state, but a missing slip count should just make the advice
    # more conservative -- the behaviour before this was ever read, not
    # a new way to get no advice.
    slips = obj.get("setPinkSlips")
    if slips is not None and max_fires:
        try:
            toon.fires = min(max(0, int(slips)), int(max_fires))
        except (TypeError, ValueError):
            problems.append(f"toon {obj.do_id}: setPinkSlips is "
                            f"{slips!r}, which is not a count")

    # UNITES. `setResistanceMessages`, same ownrecv shape as slips: wire
    # says what is HELD, cap says what the player will SPEND, neither
    # alone may grant one.
    #
    # Toon-Up and Gag-Up only (`realms.RESISTANCE_CATEGORIES`).
    # Jellybeans buy nothing in a battle and Toon-Down is CUSTOM TO
    # REALMS -- counting either would inflate the pouch with unites the
    # search can never play.
    if max_unites:
        messages = obj.get("setResistanceMessages")
        held = realms_mod.battle_unites(messages)
        if held:
            toon.unites_held = min(held, int(max_unites))
            # WHICH ones, so a toon holding only a Lure restock is not
            # offered a Squirt one. Toon-Up keys on the kind alone (the
            # value is this build's own, not TTR's); Gag-Up keys on the
            # track the menu names exactly.
            by_kind = realms_mod.parse_resistance(messages) or {}
            stock = {}
            if by_kind.get("toon_up"):
                stock[("toon_up", None)] = by_kind["toon_up"]
            for track, count in (realms_mod.gag_up_tracks(messages)
                                 or {}).items():
                if count > 0:
                    stock[("gag_up", track)] = count
            toon.unite_stock = stock
            # WHICH Toon-Up VALUES this build issues: Realms is
            # 10/20/40/80/MAX, not TTR's 20/35/50/65/80. Set on the
            # state, never on `unites.TOON_UP_VALUES` -- that table
            # stays TTR's, per docs/realms.md.
            toon.toon_up_values = realms_mod.TOON_UP_VALUES

    # SOS CARDS. `setNPCFriendsDict` names them exactly, so unlike the
    # unites this loses nothing. The cap limits how many CALLS the
    # solver may plan, never which cards exist.
    if max_sos:
        cards = realms_mod.parse_npc_friends(obj.get("setNPCFriendsDict"))
        if cards:
            # ONLY NAMES `sos.BY_NAME` KNOWS. `npc_names()` maps all 593
            # NPCs, of which 29 are SOS cards, so a stray id would arrive
            # as a plausible-looking name like "Al Capella" -- offered by
            # `legal_actions`, then `KeyError` on `BY_NAME[action.sos]`
            # inside the search's child process, reading as a dead search
            # rather than a nonexistent card. `_sos_probes` already
            # filters this way.
            from .. import sos as sos_mod

            cards = {name: count for name, count in cards.items()
                     if name in sos_mod.BY_NAME}
        if cards:
            # EVERY CARD TYPE survives, each capped at the budget --
            # never the first `budget` cards alphabetically, which used
            # to let spelling decide what existed: at a cap of 3, Barnacle
            # Bessie x2 and Clumsy Ned x28 crowded out Professor Pete
            # (Restock All), Flippy and Daffy Don entirely.
            #
            # The cap still bounds CALLS, not card types: a toon calls at
            # most one a round, and `AdviceWorker.note_spent` charges each
            # against `remaining("sos")`.
            budget = int(max_sos)
            toon.sos_cards = {name: min(int(count), budget)
                              for name, count in cards.items() if count > 0}
    return toon, []


def player_toon_id(listener) -> Optional[int]:
    """Which toon is OURS, by the one field only we receive.

    `setInventory` is `ownrecv`, so the toon whose pouch we hold is the
    one we're playing -- no configuration, no guessing at names.
    Returns None if that's ambiguous: declining beats advising the
    wrong toon's pouch.
    """
    holders = [t.do_id for t in listener.toons()
               if t.get("setInventory") is not None]
    return holders[0] if len(holders) == 1 else None


def pick_battle(listener, battles, player_do_id: Optional[int] = None):
    """(battle, reasons). Which of several battles is the player's.

    A VP splits four toons two and two, so a boss fight has TWO battle
    objects on the cluster, and so does an ordinary street whenever
    another toon is fighting elsewhere in the district. The roster
    settles it: ours is the one whose `setMembers` lists our toon.
    Declines only if that can't be established -- advising on somebody
    else's fight is worse than silence.
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

    # A Trap's damage and a Lure's stored accuracy depend on whether THAT
    # gag was organic -- the thrower's trees, up to the level planted --
    # so the player's organic levels are read before the cogs are built.
    # Taken as the player's: who threw a teammate's gag is not tracked.
    from ..state import Track

    organic_top: dict = {}
    player_obj = listener.store.get(
        player_do_id if player_do_id is not None else members.toons[0])
    if player_obj is not None:
        organic_top = realms_mod.parse_organic_levels(
            player_obj.get("setTrackBonusLevel")) or {}

    def _organic(track, level):
        return level is not None and level <= organic_top.get(track, 0)
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
            trap_level=trap, trap_organic=_organic(Track.TRAP, trap),
            lure_organic=_organic(Track.LURE, None if age is None else age[0]))
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
                    kind=battle_kind(battle), sos_one_round=True), [],
        boss=boss_of(listener, battle),
        battle_id=getattr(battle, "do_id", None),
        boss_room=getattr(battle, "dclass", None) == BOSS_BATTLE_CLASS,
        suit_ids=tuple(members.suits),
        allies=tuple(allies))
