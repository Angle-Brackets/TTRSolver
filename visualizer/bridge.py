"""
JSON bridge between the browser UI and the real solver.

The visualizer used to carry its own JavaScript port of the battle rules,
which drifted badly from `solver/` -- by the time it was retired it still
thought Small Magnet was single-target, that lures never expired, and that
Flunkies had a flat 75% accuracy. This module exists so that can't happen
again: the page runs the actual Python package under Pyodide and this is
the only translation layer, JSON in and JSON out.

Everything here is serialization and labelling. No game rules live in this
file, and none should ever be added -- if the UI needs a number, it comes
from `solver.mechanics` / `solver.outcomes` / `solver.search`.

Runs fine under CPython too, which is how it's tested
(`tests/test_bridge.py`).
"""
import json
from typing import Any, Dict, List, Optional

from solver import data, outcomes, simulator
from solver.search import expectimax
from solver.state import Action, BattleState, CogState, CogStatus, ToonState, Track

# ---------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------


def cog_to_dict(cog: CogState) -> Dict[str, Any]:
    st = cog.status
    return {
        "type": cog.cog_type,
        "department": cog.department,
        "level": cog.level,
        "hp": cog.hp,
        "max_hp": cog.max_hp,
        "dead": st.is_dead,
        "lured": st.lured,
        "lure_rounds": st.lure_rounds_remaining,
        "lure_acc": st.lure_acc_before_bonus,
        "lure_level": st.lure_level,
        "trapped": st.trapped,
        "trap_level": st.trap_level,
    }


def cog_from_dict(d: Dict[str, Any]) -> CogState:
    status = CogStatus(
        lured=d["lured"],
        lure_rounds_remaining=d["lure_rounds"],
        lure_acc_before_bonus=d["lure_acc"],
        lure_level=d["lure_level"],
        trapped=d["trapped"],
        trap_level=d["trap_level"],
        is_dead=d["dead"],
    )
    return CogState(cog_type=d["type"], department=d["department"],
                    level=d["level"], hp=d["hp"], max_hp=d["max_hp"],
                    status=status)


def state_to_dict(state: BattleState) -> Dict[str, Any]:
    return {
        "toon": {
            "laff": state.toon.laff,
            "max_laff": state.toon.max_laff,
            "track_exp": {t.value: lvl for t, lvl in state.toon.track_exp.items()},
            # list of [track, level, count] -- JSON has no tuple keys
            "gags": [[t.value, lvl, n]
                     for (t, lvl), n in sorted(state.toon.gag_counts.items(),
                                                key=lambda kv: (kv[0][0].value, kv[0][1]))],
        },
        "cogs": [cog_to_dict(c) for c in state.cogs],
        "round": state.round_num,
    }


def state_from_dict(d: Dict[str, Any]) -> BattleState:
    t = d["toon"]
    toon = ToonState(
        laff=t["laff"], max_laff=t["max_laff"],
        track_exp={Track(k): v for k, v in t["track_exp"].items()},
        gag_counts={(Track(track), lvl): n for track, lvl, n in t["gags"]},
    )
    return BattleState(toon=toon,
                       cogs=[cog_from_dict(c) for c in d["cogs"]],
                       round_num=d["round"])


def action_to_dict(a: Action) -> Dict[str, Any]:
    return {"track": a.track.value, "level": a.level, "target": a.target_index}


def action_from_dict(d: Dict[str, Any]) -> Action:
    return Action(track=Track(d["track"]), level=d["level"],
                  target_index=d["target"])


# ---------------------------------------------------------------------
# Labelling -- names come from the data tables, not from a UI-side copy
# ---------------------------------------------------------------------


def gag_name(track: Track, level: int) -> str:
    return data.gag(track, level).display


# Icon filenames are derived from the same identity the data uses, so they
# cannot drift from it. The page prefixes the directory; tools/fetch_icons.py
# writes the files. Both sides tolerate them being absent -- assets/ is
# gitignored, so a fresh clone has none until the fetcher is run.

def gag_icon(track: Track, level: int) -> str:
    return f"gag-{track.value}-{level}.png"


def cog_icon(department: str, cog_type: str) -> str:
    return f"cog-{department}-{cog_type}.png"


def department_icon(department: str) -> str:
    return f"dept-{department}.png"


def describe_action(action: Action) -> str:
    name = gag_name(action.track, action.level)
    where = "all cogs" if action.target_index is None else f"cog {action.target_index + 1}"
    return f"{name} -> {where}"


def cog_label(cog: CogState, index: int) -> str:
    if cog.status.is_dead:
        return f"Cog {index + 1} defeated"
    tags = []
    if cog.status.lured:
        tags.append(f"lured {cog.status.lure_rounds_remaining}r")
    if cog.status.trapped:
        tags.append("trapped")
    suffix = f" ({', '.join(tags)})" if tags else ""
    spec = data.cog(cog.department, cog.cog_type)
    return f"{spec.display} L{cog.level} {cog.hp}/{cog.max_hp}{suffix}"


# ---------------------------------------------------------------------
# Scenario construction
# ---------------------------------------------------------------------


def build_state(cfg: Dict[str, Any]) -> BattleState:
    """cfg: {laff, cogs: [{type, department, level}], gags: [[track, level, n]]}

    Rejects loadouts no real toon could carry -- more than six gag tracks or
    more than a full pouch. Without this the solver will happily plan for a
    toon with all seven tracks and 200 gags and hand back advice nobody can
    follow.
    """
    counts = {(Track(t), lvl): n for t, lvl, n in cfg["gags"] if n > 0}
    problems = data.validate_loadout(counts)
    if problems:
        raise ValueError("; ".join(problems))

    tracks = {Track(track) for track, _lvl, n in cfg["gags"] if n > 0}
    toon = ToonState(
        laff=cfg["laff"], max_laff=cfg["laff"],
        track_exp={t: 7 for t in tracks},      # maxed in every owned track
        gag_counts={(Track(track), lvl): n for track, lvl, n in cfg["gags"]},
    )
    cogs = []
    for c in cfg["cogs"]:
        lvl = c["level"]
        cogs.append(CogState(cog_type=c["type"],
                             department=c.get("department", "bossbot"),
                             level=lvl,
                             hp=data.cog_max_hp(lvl),
                             max_hp=data.cog_max_hp(lvl)))
    return BattleState(toon=toon, cogs=cogs)


def catalogue() -> Dict[str, Any]:
    """Everything the UI needs to populate its pickers, straight from the
    data tables so the two can't disagree -- including the loadout limits,
    so the grid enforces the same rule build_state does."""
    depts = {}
    for key, dept in sorted(data.COG_DEPARTMENTS.items()):
        depts[key] = [{"type": c.key, "label": c.display,
                       "levels": list(c.levels),
                       "icon": cog_icon(c.department, c.key)} for c in dept]
    gags = []
    for track in Track:
        for level in range(1, 8):
            spec = data.gag(track, level)
            gags.append({"track": track.value, "level": level,
                         "name": spec.display,
                         "icon": gag_icon(track, level),
                         "max_carry": spec.max_carry,
                         "group": simulator.is_group_action(track, level)})
    emblems = {d: department_icon(d) for d in sorted(data.COG_DEPARTMENTS)}
    return {"departments": depts, "gags": gags, "emblems": emblems,
            "tracks": [t.value for t in Track],
            "limits": {"max_tracks": data.MAX_GAG_TRACKS,
                       "max_pouch": data.MAX_POUCH}}


# ---------------------------------------------------------------------
# Tree expansion -- lazy, one layer per call
# ---------------------------------------------------------------------


def _terminal_label(state: BattleState) -> Optional[str]:
    if state.is_win():
        return "All cogs defeated"
    if state.toon.laff <= 0:
        return "Toon is sad -- battle lost"
    return None


def expand_decision(state_dict: Dict[str, Any], depth: int) -> List[Dict[str, Any]]:
    """The toon's options from this state, each scored by expectimax and
    sorted best-first. `gap` is the EV lead over the next-best option --
    near zero means the choice doesn't matter."""
    state = state_from_dict(state_dict)
    ranked = expectimax.rank_actions(state, depth=max(1, depth))

    children = []
    for i, (value, action) in enumerate(ranked):
        gap = value - ranked[i + 1][0] if i + 1 < len(ranked) else None
        children.append({
            "kind": "action",
            "action": action_to_dict(action),
            "label": describe_action(action),
            "icon": gag_icon(action.track, action.level),
            "ev": round(value, 2),
            "gap": None if gap is None else round(gap, 2),
            "best": i == 0,
            "state": state_dict,
        })
    return children


def best_line(state_dict: Dict[str, Any], depth: int,
               steps: int = 6) -> List[Dict[str, Any]]:
    """The principal variation: what the solver plays from here, following
    its own recommendation and then the single most likely outcome of it.

    This is the "expected" line, not a guaranteed one -- each step takes the
    modal outcome, so the whole line is much less likely than any step in it.
    Its job is to answer "what is the plan?", which a tree of probabilities
    doesn't say on its own.
    """
    state = state_from_dict(state_dict)
    line = []

    for _ in range(steps):
        if state.is_terminal():
            break
        try:
            value, action = expectimax.evaluate(state, depth=max(1, depth))
        except NotImplementedError:
            break
        if action is None:
            break

        branches = outcomes.action_outcomes(state, action)
        if not branches:
            break
        prob, next_state, reward = max(branches, key=lambda b: b[0])

        line.append({
            "action": action_to_dict(action),
            "label": describe_action(action),
            "ev": round(value, 2),
            "prob": round(prob, 4),
            "reward": round(reward, 2),
            "laff_lost": state.toon.laff - next_state.toon.laff,
            "cogs": [cog_label(c, i) for i, c in enumerate(next_state.cogs)],
            "terminal": _terminal_label(next_state),
        })
        state = next_state

    return line


def expand_action(state_dict: Dict[str, Any], action_dict: Dict[str, Any],
                   cap: int = 8) -> List[Dict[str, Any]]:
    """Every outcome of taking this action, with exact probabilities from
    `outcomes.action_outcomes`. Outcomes past `cap` are merged into one
    bucket so a node never spawns dozens of children."""
    state = state_from_dict(state_dict)
    action = action_from_dict(action_dict)

    branches = sorted(outcomes.action_outcomes(state, action),
                      key=lambda b: b[0], reverse=True)

    children = []
    for prob, next_state, reward in branches[:cap]:
        terminal = _terminal_label(next_state)
        children.append({
            "kind": "terminal" if terminal else "decision",
            "label": terminal or "Toon's turn",
            "prob": round(prob, 4),
            "reward": round(reward, 2),
            "laff_lost": state.toon.laff - next_state.toon.laff,
            "state": state_to_dict(next_state),
            "cogs": [cog_label(c, i) for i, c in enumerate(next_state.cogs)],
            "cog_icons": [cog_icon(c.department, c.cog_type)
                          for c in next_state.cogs],
        })

    rest = branches[cap:]
    if rest:
        total = sum(p for p, _s, _r in rest)
        children.append({
            "kind": "bucket",
            "label": f"{len(rest)} rarer outcomes",
            "prob": round(total, 4),
            "reward": round(sum(p * r for p, _s, r in rest) / total, 2),
            "state": None,
            "cogs": [],
        })
    return children


def cog_forecast(state_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What each surviving cog is about to do, and how likely each attack
    is. Marginal per cog -- see outcomes.cog_phase_summary for why not the
    joint."""
    state = state_from_dict(state_dict)
    summary = outcomes.cog_phase_summary(state)
    for entry in summary:
        cog = state.cogs[entry["index"]]
        entry["icon"] = cog_icon(cog.department, cog.cog_type)
        entry["department"] = cog.department
        entry["dept_icon"] = department_icon(cog.department)
    return summary


# ---------------------------------------------------------------------
# String entry points -- Pyodide passes strings most cleanly
# ---------------------------------------------------------------------


def api_catalogue() -> str:
    return json.dumps(catalogue())


def api_root(cfg_json: str) -> str:
    try:
        state = build_state(json.loads(cfg_json))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({
        "kind": "decision",
        "label": "Toon's turn",
        "state": state_to_dict(state),
        "cogs": [cog_label(c, i) for i, c in enumerate(state.cogs)],
        "cog_icons": [cog_icon(c.department, c.cog_type) for c in state.cogs],
    })


def api_expand_decision(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        children = expand_decision(payload["state"], payload.get("depth", 2))
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"children": children})


def api_expand_action(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        children = expand_action(payload["state"], payload["action"])
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"children": children})


def api_cog_forecast(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        return json.dumps({"cogs": cog_forecast(payload["state"])})
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})


def api_best_line(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        line = best_line(payload["state"], payload.get("depth", 2))
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"line": line})
