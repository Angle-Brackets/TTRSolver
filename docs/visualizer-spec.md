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

## The architecture

```
page ──POST /api/call {fn, payload}──► serve.py ──► bridge ──► solver.*
  ▲                                                              │
  └──────────────── JSON ────────────────────────────────────────┘
```

**The solver runs in the server, not the browser.** `serve.py` is
CPython in the repo: numpy is installed, `solver/rl/ppo_facility.json`
is on disk, and `bridge` imports directly.

It used to run in the browser under Pyodide, and that is now gone from
the plan. The property Pyodide existed for -- no JavaScript copy of the
battle rules -- is kept and is in fact stronger, since every answer
comes from `bridge` calling the same `solver` package the tests import.
A JSON call over HTTP is a shorter path to that than shipping the
interpreter.

What it cost, and why it went:

| | Pyodide | server |
|---|---|---|
| first load | ~10 MB runtime | nothing |
| numpy | must `loadPackage`; never was | already installed |
| policy weights | 7.7 MB download; never mounted | already on disk |
| search speed | Pyodide's interpreter | full CPython |
| the PPO engine | **blocked** | works |

The search is CPU-bound against a seconds budget, so an interpreter
penalty comes straight off the depth it reaches.

The one thing Pyodide bought was hosting the page with no backend, and
that was never used -- the tool has always required
`python -m visualizer.serve`, and a server was needed regardless
because `file://` blocks the fetches.

**No Web Worker either.** It existed because Pyodide is synchronous and
froze the page. `serve.py` is a `ThreadingTCPServer`, so a long search
occupies its own thread and the page just awaits a `fetch`.

## The API the page calls

`POST /api/call` with `{"fn": "...", "payload": {...}}`, JSON back.
One endpoint rather than a route per call, so adding a bridge function
needs no server change. Only names beginning `api_` are callable --
`bridge` is full of helpers that take Python objects. Anything that
raises comes back as `{"error": "..."}` with a 200, because the useful
failures here are ordinary: a loadout over the pouch cap, a `[TODO]`
attack table.

| `fn` | payload | returns |
|---|---|---|
| `api_catalogue` | — | pickers: departments, gags, emblems, tracks, objectives, limits |
| `api_root` | the scenario config | `{kind, label, state, cogs, cog_icons}` or `{error}` |
| `api_expand_decision` | `{state, depth, objective}` | `{children}` — one layer of the tree |
| `api_expand_action` | `{state, action, objective}` | `{children}` |
| `api_cog_forecast` | `{state}` | `{cogs}` — what each cog threatens |
| `api_best_line` | `{state, depth, objective}` | `{line}` |
| `api_climb` | `{state, budget?, width?}` | `{available, plan, labels, unite}` or `{available: false, reason}` |

`api_catalogue` takes no payload; call it once at boot to fill the
pickers.

`api_climb` is new and is the policy -- `hybrid.climb`, the engine the
overlay panel plays with. Deterministic on a fixed seed, because the
page re-asks the same position as the user clicks about and an answer
that changed each time would read as a solver bug. Defaults are
`budget=24, width=16`, matching the panel.

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

## It cannot run the policy at all, and that is the biggest gap

`bridge.py`, `index.html` and `worker.js` mention `hybrid`, `climb`,
`policy`, `ppo` and `numpy` **zero times each**. Every number this tool
shows comes from `expectimax` — the exact search.

That is the engine you do NOT play with. The overlay panel's default is
`hybrid.climb`: the PPO policy proposes a menu and `_quick_score`
disposes. So the tool for understanding the solver cannot show the
engine that actually gives the advice, and the two are measured to
disagree — same kind of move, different gag, on 6 boards out of 6.

Two hard blockers, both verified:

1. **numpy is never loaded.** `worker.js` has no `loadPackage` call, so
   `hybrid.available()` is False in the browser however the API is
   wired. Pyodide ships numpy; it just has to be asked for.
2. **The policy weights are not mounted.** `serve.python_manifest`
   globs `*.py` only — 59 files, no non-Python entry — so
   `solver/rl/ppo_facility.json` never reaches the browser filesystem
   and `hybrid._load()` finds no export.

Neither is hard to fix. The cost is the thing to decide: numpy adds
several MB to the boot and the policy export is **7.7 MB**, on top of
the ~10 MB of Pyodide already downloaded. Roughly doubling first load
for a debugging tool is a real trade, and it may be worth loading the
policy lazily — only when the user asks for the PPO answer.

What it buys is the comparison the panel already makes and this tool
cannot: the policy's move beside the search's, on a position you built
by hand, with the tree underneath showing why the search disagrees.

## What to build, in order

1. **A party.** Up to four toons, each with their own pouch, training,
   organic tracks and consumables. This is the big one — the solver has
   been party-aware for a long time and the page has no concept of it.
2. **Cog status on the setup board.** Lured (with rounds), trapped (with
   the trap's level), and Version 2.0. Today you cannot build the
   positions that actually matter.
3. **Consumables in the scenario builder.** Slips, unites, SOS cards.
   The Python side now carries them; nothing offers them.
4. **The two engines side by side** — see the section above. Needs
   numpy loaded, the 7.7 MB policy mounted, and an `api_climb` exposing
   `hybrid.climb`. This is the single most valuable addition: it is the
   comparison the panel already makes and the reason to open this tool
   at all.
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

## The stack: match the overlay panel

[OWNER] Decided -- the page is rebuilt on the same stack and the same
colours as the live UI, rather than staying a hand-written CDN page.

From `overlay_ui/package.json`:

| | |
|---|---|
| build | Vite 8 (`npm run dev` / `npm run build`) |
| framework | React 19 |
| styling | Tailwind 4 + daisyUI 5, via `@tailwindcss/vite` |
| font | Fredoka, falling back to Segoe UI / system-ui |

Reuse `overlay_ui/src/index.css` wholesale rather than re-deriving it.
The pieces that carry the identity:

- The daisyUI theme block -- `--color-base-100` through `-300`,
  `--color-primary`, `success`, `warning`, `error`, and the
  `--radius-box` / `--radius-field` rounding.
- The seven track palettes, `.track-toon_up` through `.track-drop`,
  each giving `--track-bg`, `--track-border`, `--track-text` and an
  `--accent-glow`. Plus `.track-none`, `.track-fire` and `.track-sos`,
  which are sentinels rather than gag tracks and must stay visually
  distinct from a pass.
- `.toontown-card-hero`, `.toontown-card-panel` and `.toontown-btn-3d`.

A tree node coloured by its gag's track, using the same palette the
panel uses for its advice card, is most of the visual work done.

### This does not threaten the Pyodide property

The build step applies to the PAGE. `serve.py` still mounts the real
`solver` package into the browser at runtime and the worker still
imports `bridge`, so there is still no JavaScript copy of the rules.
What changes is that `index.html` becomes a Vite entry point with
components instead of one 1005-line file.

Two consequences to plan for:

- **`visualizer/dist` gets committed**, the way `overlay_ui/dist` is,
  so running the tool needs Node no more than running the solver needs
  a compiler. `serve.py` then serves the built page.
- **Pyodide still comes from the CDN at runtime** -- it is not an npm
  dependency and should not become one.

### Shared components

The two tools now overlap: a cog row, a gag icon, a track badge, an
advice card. Whether they share a package or copy is worth deciding
early. Copying is what produced the last drift here -- two panel
workers diverged until one's Reconsider silently did nothing, which is
why `solver/live/worker.py` now exists.

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
