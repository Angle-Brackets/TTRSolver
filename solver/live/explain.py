"""Why the solver picked this move, in numbers the panel can show.

The panel has always sent WHAT to throw and nothing about why, while
the solver computed the reasons on every score and discarded them:
`expected_incoming`, `survival_rounds`, `prevented` and the round's own
damage were all right there and none reached the page.

Everything here is READ OFF THE SAME FUNCTIONS THE SCORER USES. Nothing
is re-derived, so the panel cannot drift from the search -- the failure
this codebase has already had twice, when a second implementation of an
accuracy rule put a 5% miss on an always-hit Trap.

It is also allowed to know nothing. Every field is optional and the
whole thing degrades to an empty dict rather than raising, because a
missing explanation must never cost you the advice it was explaining.
"""
from __future__ import annotations

from typing import Dict, Optional


def _targets(state, action):
    """The cogs an action lands on: one, or every live cog for a group."""
    live = [c for c in state.cogs if not c.status.is_dead]
    if action is None or getattr(action, "target_index", None) is None:
        return live
    try:
        return [state.cogs[action.target_index]]
    except (IndexError, TypeError):
        return live


def accuracy_of(state, action, actor: int = 0) -> Optional[int]:
    """The chance this gag lands, as the game computes it.

    `toon_action_accuracy` is the simulator's own entry point, so a
    forced value -- Trap always hits, Drop always misses a lured cog --
    comes back stated rather than rolled up and capped.
    """
    if action is None or getattr(action, "is_pass", False):
        return None
    try:
        from .. import simulator
        return int(simulator.toon_action_accuracy(state, action, actor))
    except Exception:                   # noqa: BLE001 - never cost advice
        return None


def describe(state, action, actor: int = 0) -> Dict:
    """Numbers behind one recommendation. Empty dict if anything fails.

    `incoming` and `survive` describe the BOARD and hold whatever is
    advised; the rest describe this action. `survive` is capped at
    `SURVIVAL_CAP`, so 4.0 means "four or more".
    """
    out: Dict = {}
    if state is None:
        return out
    try:
        from ..search import party_search as ps

        incoming = ps.expected_incoming(state)
        out["incoming"] = round(float(incoming), 1)
        out["survive"] = round(float(ps.survival_rounds(state)), 1)
    except Exception:                   # noqa: BLE001
        pass

    acc = accuracy_of(state, action, actor)
    if acc is not None:
        out["accuracy"] = acc

    if action is None or getattr(action, "is_pass", False):
        return out

    # WHAT THE ROUND WOULD DO, from the simulator rather than a second
    # opinion about it. All-hit, matching how `_score_leaf` reads a
    # plan before averaging over the dice.
    try:
        from .. import simulator
        from ..search import party_search as ps

        probe = state.clone()
        plan = [None] * len(state.toons)
        plan[actor] = action
        simulator.apply_party_round(probe, plan, hits=[True] * len(plan))
        out["damage"] = int(ps._landed(state.cogs, probe.cogs))
        out["kills"] = int(ps._killed(state.cogs, probe.cogs))
        prevented = float(ps.prevented(state, probe))
        if prevented:
            out["prevented"] = round(prevented, 1)
        armed = float(ps.armed_credit(state, probe))
        if armed:
            out["arms"] = round(armed, 1)
    except Exception:                   # noqa: BLE001
        pass
    return out


def reason(detail: Dict) -> str:
    """One phrase for the line under the advice.

    Ordered by what actually decides a round: a kill first, then damage
    prevented, then a trap laid, then damage dealt. Empty when there is
    nothing worth saying, which the view should render as nothing rather
    than as a blank row.
    """
    if not detail:
        return ""
    kills = detail.get("kills") or 0
    if kills == 1:
        return "kills it"
    if kills > 1:
        return "kills %d" % kills
    prevented = detail.get("prevented") or 0
    if prevented >= 1:
        return "prevents ~%d incoming" % round(prevented)
    if detail.get("arms"):
        return "arms the trap"
    damage = detail.get("damage") or 0
    if damage:
        return "%d damage" % damage
    return ""
