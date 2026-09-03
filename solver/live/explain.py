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

    # ORGANIC, WHICH IS NOT READ OFF THE SCREEN. The Local API states
    # which tracks are organic, so this is the authoritative answer and
    # the gag menu's sprout does not have to be recognised to get it.
    # It is worth showing: organic raises a gag's damage, and Lure's
    # accuracy along with it.
    try:
        track = getattr(action, "track", None)
        if track is not None:
            out["organic"] = bool(state.toons[actor].is_organic(track))
    except Exception:                   # noqa: BLE001
        pass

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

        # HOW IT LANDS, not just how much. A group gag's total is the
        # number the SCORER wants and the wrong one to show a player:
        # Foghorn against two cogs reported "100 damage" beside a
        # 110/110 cog, which reads as very nearly a kill. It is 50 each
        # and both cogs live. Sound is the whole reason this matters --
        # spreading damage IS the track's point, so the spread has to be
        # visible rather than summed away.
        #
        # Taken from actual hp deltas rather than the gag's table value,
        # so a lured cog's knockback bonus shows up as the larger number
        # it is. `each` is therefore offered only when every target
        # really did take the same amount.
        hits = [before.hp - after.hp
                for before, after in zip(state.cogs, probe.cogs)
                if before.hp > after.hp]
        out["targets"] = len(hits)
        if len(hits) > 1 and len(set(hits)) == 1:
            out["each"] = int(hits[0])
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
    # A MOVE THAT CANNOT LAND IS THE MOST IMPORTANT THING TO SAY, and
    # this used to say nothing at all: no kill, nothing prevented, no
    # trap, no damage, so every branch below fell through to "". A blank
    # line under a recommendation reads as a broken explainer rather
    # than as a warning, which is exactly backwards -- it was reported
    # from live play as "doesn't give the reasoning", when the reasoning
    # was that the gag was a guaranteed miss.
    #
    # Zero is reachable one way only. `ACCURACY_FLOOR` lifts every
    # rolled accuracy to 5%, and Drop is the single track exempt from
    # it, so a stated 0 is always the rule that Drop misses a lured cog.
    if detail.get("accuracy") == 0:
        return "always misses a lured cog"
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
        targets = detail.get("targets") or 0
        each = detail.get("each")
        if targets > 1:
            # Per cog when they all took the same, the total otherwise --
            # a mixed spread has no single "each" to quote.
            return ("%d to each of %d cogs" % (each, targets) if each
                    else "%d damage across %d cogs" % (damage, targets))
        return "%d damage" % damage
    return ""
