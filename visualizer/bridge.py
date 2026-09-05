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
import dataclasses
import json
from typing import Any, Dict, List, Optional

from solver import data, outcomes, simulator
from solver.search import expectimax
from solver.search import objective as objective_mod
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


def toon_to_dict(toon: ToonState) -> Dict[str, Any]:
    return {
        "laff": toon.laff,
        "max_laff": toon.max_laff,
        "track_exp": {t.value: lvl for t, lvl in toon.track_exp.items()},
        # list of [track, level, count] -- JSON has no tuple keys
        "gags": [[t.value, lvl, n]
                 for (t, lvl), n in sorted(toon.gag_counts.items(),
                                            key=lambda kv: (kv[0][0].value,
                                                            kv[0][1]))],
        # Organic tracks were missing here, and a field that is dropped
        # in serialisation is invisible rather than broken: a state that
        # went through this round-trip came back safe, and the only
        # symptom was a benchmark whose organic and non-organic columns
        # were identical to the last decimal. Organic changes damage by
        # 10-15%, so anything measured across this boundary was measuring
        # the wrong loadout.
        "organic": sorted(t.value for t in toon.organic_tracks),
        # THE CONSUMABLES, and they were all missing. Same failure the
        # organic note above describes and for the same reason: a
        # dropped field is invisible rather than broken. A position
        # built here with five slips and a book of cards came back
        # carrying none, so every line this tool showed was the line for
        # a toon holding nothing -- and a solo VP is 0% without them
        # against 45% with.
        "fires": int(getattr(toon, "fires", 0)),
        "unites_held": int(getattr(toon, "unites_held", 0)),
        # Keyed by the card's own name, exactly as `simulator` looks
        # them up. JSON has no tuple keys but these are plain strings.
        "sos_cards": dict(getattr(toon, "sos_cards", {}) or {}),
    }


def toon_from_dict(d: Dict[str, Any]) -> ToonState:
    toon = ToonState(
        laff=d["laff"], max_laff=d["max_laff"],
        track_exp={Track(k): v for k, v in d["track_exp"].items()},
        gag_counts={(Track(track), lvl): n for track, lvl, n in d["gags"]},
        organic_tracks=frozenset(Track(t) for t in d.get("organic", ())),
        fires=int(d.get("fires", 0)),
    )
    toon.unites_held = int(d.get("unites_held", 0))
    toon.sos_cards = dict(d.get("sos_cards", {}) or {})
    return toon


def state_to_dict(state: BattleState) -> Dict[str, Any]:
    return {
        # "toon" stays for the single-toon front end; "toons" carries the
        # party. Writing both means an older reader keeps working and a
        # newer one does not have to guess which it was given.
        "toon": toon_to_dict(state.toon),
        "toons": [toon_to_dict(t) for t in state.toons],
        "cogs": [cog_to_dict(c) for c in state.cogs],
        "round": state.round_num,
    }


def state_from_dict(d: Dict[str, Any]) -> BattleState:
    toons = [toon_from_dict(t) for t in d["toons"]] if "toons" in d         else [toon_from_dict(d["toon"])]
    return BattleState(toons=toons,
                       cogs=[cog_from_dict(c) for c in d["cogs"]],
                       round_num=d["round"])


def action_to_dict(a: Action) -> Dict[str, Any]:
    # A pass has no track; the front end keys off `track: null`.
    return {"track": None if a.is_pass else a.track.value,
            "level": a.level, "target": a.target_index}


def action_from_dict(d: Dict[str, Any]) -> Action:
    # `track: null` is a pass, and must round-trip as one. `Track(None)`
    # raises, which only became reachable once the pass stopped being
    # confined to lured positions.
    track = None if d["track"] is None else Track(d["track"])
    return Action(track=track, level=d["level"], target_index=d["target"])


# ---------------------------------------------------------------------
# Labelling -- names come from the data tables, not from a UI-side copy
# ---------------------------------------------------------------------


def gag_name(track: Track, level: int) -> str:
    return data.gag(track, level).display


# Icon filenames are derived from the same identity the data uses, so they
# cannot drift from it. The page prefixes the directory; tools/fetch_icons.py
# writes the files. Both sides tolerate them being absent -- assets/ is
# gitignored, so a fresh clone has none until the fetcher is run.

def gag_icon(track, level: int):
    """None for a pass, which has no gag and therefore no icon.

    `track` is None whenever the action is a pass. That used to be
    unreachable here because a pass was only legal in one narrow
    situation the front end never rendered; widening the pass made it
    reachable and this raised AttributeError on `None.value`.
    """
    if track is None:
        return None
    return f"gag-{track.value}-{level}.png"


def cog_icon(department: str, cog_type: str) -> str:
    return f"cog-{department}-{cog_type}.png"


def department_icon(department: str) -> str:
    return f"dept-{department}.png"


def describe_action(action: Action) -> str:
    if action.is_pass:
        return "pass (wait out the lure)"
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
    presets = [{"name": o.name, "description": o.description,
                "gag_cost": o.gag_cost, "scarcity_cost": o.scarcity_cost,
                "turn_cost": o.turn_cost, "laff_weight": o.laff_weight}
               for o in objective_mod.PRESETS.values()]
    emblems = {d: department_icon(d) for d in sorted(data.COG_DEPARTMENTS)}
    return {"departments": depts, "gags": gags, "emblems": emblems,
            "tracks": [t.value for t in Track],
            "objectives": presets,
            "limits": {"max_tracks": data.MAX_GAG_TRACKS,
                       "max_pouch": data.MAX_POUCH}}


# ---------------------------------------------------------------------
# Tree expansion -- lazy, one layer per call
# ---------------------------------------------------------------------


def resolve_objective(spec: Optional[Dict[str, Any]]):
    """Turn the UI's {preset, overrides...} into an Objective.

    The presets are the interesting part -- they change what "best" means,
    not how hard the solver looks -- so they live in solver/search and the
    page only names one.
    """
    if not spec:
        return objective_mod.DEFAULT
    base = objective_mod.get(spec.get("preset", "balanced"))
    tweaks = {k: float(v) for k, v in spec.items()
              if k in ("gag_cost", "scarcity_cost", "turn_cost", "laff_weight")
              and v is not None}
    return dataclasses.replace(base, **tweaks) if tweaks else base


def _terminal_label(state: BattleState) -> Optional[str]:
    if state.is_win():
        return "All cogs defeated"
    if state.toon.laff <= 0:
        return "Toon is sad -- battle lost"
    return None


def expand_decision(state_dict: Dict[str, Any], depth: int,
                     objective=None) -> List[Dict[str, Any]]:
    """The toon's options from this state, each scored by expectimax and
    sorted best-first. `gap` is the EV lead over the next-best option --
    near zero means the choice doesn't matter."""
    state = state_from_dict(state_dict)
    ranked = expectimax.rank_actions(state, depth=max(1, depth),
                                     objective=objective)

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
               steps: Optional[int] = None,
               objective=None) -> List[Dict[str, Any]]:
    """The principal variation: what the solver plays from here, following
    its own recommendation and then the single most likely outcome of it.

    This is the "expected" line, not a guaranteed one -- each step takes the
    modal outcome, so the whole line is much less likely than any step in it.
    Its job is to answer "what is the plan?", which a tree of probabilities
    doesn't say on its own.
    """
    state = state_from_dict(state_dict)
    # Default to what the pouch allows rather than a round number: every
    # action spends a gag, so no line can run longer than that, and a fixed
    # cap silently truncates plans that need one more move than it allows.
    if steps is None:
        steps = sum(n for n in state.toon.gag_counts.values() if n > 0) + 1
    line = []

    for _ in range(steps):
        if state.is_terminal():
            break
        try:
            value, action = expectimax.evaluate(state, depth=max(1, depth),
                                                objective=objective)
        except NotImplementedError:
            break
        if action is None:
            break

        branches = outcomes.action_outcomes(state, action, objective)
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
                   cap: int = 8, objective=None) -> List[Dict[str, Any]]:
    """Every outcome of taking this action, with exact probabilities from
    `outcomes.action_outcomes`. Outcomes past `cap` are merged into one
    bucket so a node never spawns dozens of children."""
    state = state_from_dict(state_dict)
    action = action_from_dict(action_dict)

    branches = sorted(outcomes.action_outcomes(state, action, objective),
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
        children = expand_decision(payload["state"], payload.get("depth", 2),
            objective=resolve_objective(payload.get("objective")))
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"children": children})


def api_expand_action(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        children = expand_action(payload["state"], payload["action"],
            objective=resolve_objective(payload.get("objective")))
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
        line = best_line(payload["state"], payload.get("depth", 2),
            objective=resolve_objective(payload.get("objective")))
    except NotImplementedError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"line": line})


def climb_plan(state_dict: Dict[str, Any], budget: int = 24,
               width: int = 16) -> Dict[str, Any]:
    """What the POLICY would play here, beside what the search says.

    `hybrid.climb` is the engine the overlay panel plays with by
    default: PPO proposes a menu and `_quick_score` disposes. Every
    other number this module returns comes from `expectimax`, so
    without this the tool cannot show the engine that actually gives
    the advice -- and the two are measured to disagree, picking the same
    KIND of move and a different gag.

    It needs numpy and the exported policy, neither of which existed in
    the browser: `worker.js` never called `loadPackage` and the source
    manifest globbed `*.py`, so the 7.7 MB export never arrived. Server
    side both are simply present. `available()` is still checked, so a
    checkout without the export reports why instead of raising.
    """
    from solver.search import hybrid

    if not hybrid.available():
        return {"available": False, "reason": hybrid.unavailable_reason()}
    import random

    state = state_from_dict(state_dict)
    # A FIXED SEED. The page re-asks the same position as the user
    # clicks about, and `climb` is deterministic given one -- an answer
    # that changed on every refresh would look like a bug in the solver.
    hybrid.LAST_UNITE = None
    plan = hybrid.climb(state, random.Random(0), budget=budget, width=width)
    if plan is None:
        return {"available": True, "plan": None}
    return {
        "available": True,
        "budget": budget,
        "width": width,
        "unite": list(hybrid.LAST_UNITE) if hybrid.LAST_UNITE else None,
        "plan": [None if a is None else action_to_dict(a) for a in plan],
        "labels": [describe_action(a) for a in plan],
    }


def api_climb(payload_json: str) -> str:
    payload = json.loads(payload_json)
    try:
        return json.dumps(climb_plan(
            payload["state"],
            budget=int(payload.get("budget", 24)),
            width=int(payload.get("width", 16))))
    except (NotImplementedError, ValueError, KeyError) as exc:
        return json.dumps({"error": f"{exc.__class__.__name__}: {exc}"})
