# Rebuilding the visualizer

What `visualizer/` is, what it can no longer express, and what a rewrite
has to cover. Written to hand to whoever builds the page.

The RULES are not the problem and must not be touched. What has drifted
is the adapter and the UI.

## Running it

```
python tools/fetch_icons.py     # once, optional -- gag/cog/emblem art
python -m visualizer.serve      # opens localhost:8000/visualizer/index.html
```

Flags: `--port N`, `--no-browser`. Verified working: the server starts,
serves the page, and the manifest lists ~60 solver source files.

## The architecture, and why it stays

```
index.html ──postMessage──► worker.js ──fetch /api/manifest──► serve.py
   (React 18 UMD)           (Pyodide)  ──fetch each .py──────► browser FS
        ▲                              └── import bridge ──► solver.*
        └────────── {id, result} ──────────────┘
```

**The browser runs the real solver.** `serve.py` mounts the actual
`solver` package into Pyodide, so there is no JavaScript copy of the
battle rules and nothing to keep in sync. That property is the reason
this tool is trustworthy and it is not up for negotiation in a rewrite.

**The solver runs in a Web Worker.** Pyodide is single-threaded and its
calls are synchronous; in the page it froze the UI.

**No build step.** React 18 comes from a CDN as UMD, the page is one
hand-written `index.html`. First load pulls ~10 MB of Pyodide and is
slow; after that it is cached.

## The API the page calls

Every call is `postMessage({id, fn, payload})` and comes back as
`{type: "result", id, result | error}`. `result` is a JSON **string**.
`bridge[fn]` is called with `JSON.stringify(payload)`.

| `fn` | payload | returns |
|---|---|---|
| `api_catalogue` | — | pickers: departments, gags, emblems, tracks, objectives, limits |
| `api_root` | the scenario config | `{kind, label, state, cogs, cog_icons}` or `{error}` |
| `api_expand_decision` | `{state, depth, objective}` | `{children}` — one layer of the tree |
| `api_expand_action` | `{state, action, objective}` | `{children}` |
| `api_cog_forecast` | `{state}` | `{cogs}` — what each cog threatens |
| `api_best_line` | `{state, depth, objective}` | `{line}` |

`api_catalogue` is pushed once on `{type: "ready"}` at boot.

## What it cannot express

Counted by mentions in each file, which is blunt but decisive:

| feature | `bridge.py` | `index.html` |
|---|---|---|
| toons / party | 9 | **0** |
| trapped | 4 | **0** |
| organic | 5 | **0** |
| lured | 5 | 2 |
| objective | 17 | 10 |
| SOS / unites / slips | **0** (now fixed) | **0** |

So the page is a **solo, single-toon position explorer** that predates
most of what the solver became. Adding three fields will not cover it.

### Already fixed on the Python side

`toon_to_dict` / `toon_from_dict` dropped every consumable, so a
position built with slips and cards came back holding none — every line
the tool showed was for a toon carrying nothing, and a solo VP is 0% on
that footing against 45% with. They now carry `fires`, `unites_held`
and `sos_cards`, with absent keys reading as zero so older saved states
still load. Six tests pin it.

### Still needed on the Python side (not the page's job)

`build_state(cfg)` builds `BattleState(toon=..., cogs=...)` — one toon,
no consumables, no cog status, training hardcoded to 7 in every owned
track. A party-capable page needs it to accept:

- `toons: [...]` rather than a single `laff` + `gags`
- per-toon `fires`, `unites_held`, `sos_cards`, `organic`, `track_exp`
- per-cog `lured` (+ rounds), `trapped` (+ **trap level** — the level is
  required, `CogStatus` cannot spring a trap it cannot price)
- `kind` and `street`, so a VP or facility position can be built

`catalogue()` should also expose the SOS card table and the unite kinds,
so the page can offer them without hardcoding names.

## What to build, in order

1. **A party.** Up to four toons, each with their own pouch, training,
   organic tracks and consumables. This is the big one — the solver has
   been party-aware for a long time and the page has no concept of it.
2. **Cog status on the setup board.** Lured (with rounds), trapped (with
   the trap's level), and Version 2.0. Today you cannot build the
   positions that actually matter.
3. **Consumables in the scenario builder.** Slips, unites, SOS cards.
   The Python side now carries them; nothing offers them.
4. **The two engines side by side.** The overlay panel shows the policy's
   move and the exact search's answer together, each with its own
   accuracy and reason. This tool shows only the tree. Seeing where they
   disagree is exactly what a position explorer is for — measured, they
   pick the same *kind* of move but a different gag.
5. **Objective comparison.** `catalogue()` already returns every preset
   with its weights; the page uses one at a time.

## Caveats

**Never write the rules in JavaScript.** The whole point of Pyodide here
is that there is no second implementation. Anything the page needs to
know about damage, accuracy, lure or trap goes through `bridge`.

**`result` is a JSON string, not an object.** Parse it.

**The tree is lazy, one layer per call.** `api_expand_decision` returns
children, not a subtree. Deep expansion is many round trips, each one a
real solver call — keep the UI responsive and never block on it.

**A trap needs a level.** The floating marker in-game is the same banana
peel for a 50-damage Quicksand and a 180-damage TNT, and
`data.gag(TRAP, None)` raises. Any trap control must ask which.

**`build_state` validates the loadout** — more than six gag tracks or a
pouch over capacity is rejected with `{error}`. The limits are in
`catalogue().limits`; enforce them in the grid so the error is never the
first thing the user learns.

**First load is slow.** ~10 MB of Pyodide from a CDN before anything
works. Whatever replaces the current page needs an honest loading state.

## Worth deciding before starting

The overlay panel (`overlay_ui/`) is a built React app with a component
set, a theme and a published field contract (`docs/panel-contract.md`).
This is a hand-written 1005-line `index.html` on CDN React with no build
step.

Two tools, two React setups, the same domain. That is the shape that
produced the last drift — two panel workers that diverged until one's
Reconsider silently did nothing. Sharing `overlay_ui`'s components and
build would cost more up front and stop it happening again. Staying
standalone keeps the no-build-step property, which is genuinely nice for
a debugging tool.

Worth an explicit decision rather than defaulting.
