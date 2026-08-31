"""Running a chosen action through `BattleEnv`, correctly, once.

WHY THIS EXISTS. Every measurement script re-implemented the same
action-to-index mapping, and every one of them ended it the same way::

    i = env.PASS_INDEX
    if action is not None and not action.is_pass:
        for k, entry in enumerate(env.ACTIONS):
            if entry matches action:
                i = k
                break
    env.step(i)

That fallback is the bug. `PASS_INDEX` is not "I could not express
this", it is "hold this round" -- so an action the table cannot name
becomes a toon standing still, and the run reports a strategy failure
where the truth is a harness failure. It is silent, it is plausible, and
it has now cost four separate measurements:

* a fire has `track=None`, so a script filtering on `track is not None`
  passed instead of firing;
* an SOS has no index at all, so it passed instead of calling;
* both together read 0% at difficulty 9 and on the VP, against 60% and
  94% from a harness that mapped them -- and 0% reads like a finding.

So `play` RAISES on an action it cannot execute. A measurement that
stops is worth more than one that quietly measures the wrong policy.
"""
from __future__ import annotations

from typing import Optional

from . import env as env_mod


class UnplayableAction(ValueError):
    """An action the harness cannot put through `BattleEnv.step`."""


def action_index(action) -> Optional[int]:
    """The `ACTIONS` index for `action`, or None if it has no index.

    None is not a failure: a pass and an SOS both legitimately have no
    index, and `play` handles each. It means "not in the table".
    """
    if action is None or action.is_pass:
        return env_mod.PASS_INDEX
    if getattr(action, "sos", None):
        return None
    if getattr(action, "fire", False):
        return env_mod._FIRE_INDEX.get(action.target_index)
    for index, entry in enumerate(env_mod.ACTIONS):
        if entry is None or entry.fire or getattr(entry, "sos", None):
            continue
        if (entry.track == action.track and entry.level == action.level
                and entry.target_index == action.target_index):
            return index
    return None


def play(env, action):
    """Step `env` with `action`. Returns whatever `step` returns.

    Raises `UnplayableAction` rather than falling back to a pass, which
    is the whole point of the module.
    """
    if action is None or action.is_pass:
        return env.step(env_mod.PASS_INDEX)
    if getattr(action, "sos", None):
        # No SOS is in the table; `step` takes the raw action instead.
        return env.step(env_mod.PASS_INDEX, action=action)
    index = action_index(action)
    if index is None:
        raise UnplayableAction(
            f"{action!r} has no ACTIONS entry -- stepping a pass here "
            f"would silently measure a toon doing nothing")
    return env.step(index)


def solo_loadout(rng, laff: int = 100, max_laff: int = 137,
                 fires: int = 0, unites: int = 0, sos_cards=None,
                 pouch_capacity: int = 80):
    """A valid maxed solo toon.

    NO TOON-UP TRAINING, deliberately. A solo toon cannot heal itself,
    so training it spends part of an 80-gag pouch on gags that can never
    be thrown; positions built that way read 0% and look like a
    difficulty result.

    The pouch comes from `env.restock`, which respects
    `pouch_capacity`. Filling every gag to its carry limit sums far past
    80 and produces degenerate positions the same way.
    """
    from ..state import ToonState, Track

    tracks = [t for t in Track if t is not Track.TOON_UP]
    toon = ToonState(laff, max_laff, {t: 7 for t in tracks}, {},
                     frozenset({Track.THROW}),
                     pouch_capacity=pouch_capacity)
    env_mod.restock(toon, rng)
    toon.fires = fires
    toon.unites_held = unites
    if sos_cards:
        toon.sos_cards = dict(sos_cards)
    return toon


def check_position(state) -> None:
    """Raise if a sampled position cannot measure anything.

    `facility_position` returns `cogs=[]` and `BattleEnv.reset` fills
    them, so a state used before `reset` has nothing to fight -- another
    way a harness reads zero while looking fine.
    """
    if not state.cogs:
        raise UnplayableAction(
            "no cogs: `facility_position` builds the party and `reset` "
            "builds the board, so this state was used before `reset`")
    if not state.toons:
        raise UnplayableAction("no toons")
    if not state.can_still_damage():
        raise UnplayableAction(
            "the toons cannot damage a cog, so this position is lost "
            "before it starts")
