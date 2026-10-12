# Visualizer

A browser page for exploring one battle position without the game running.
You build a position by hand (toons, gag pouches, cogs and their status),
and the page shows what two of the solver's engines would play, the tree of
moves and outcomes underneath, and what each cog is likely to do next.

Every number on the page comes from the real `solver` package. The page is
a React app that sends JSON to a small local server, and the server calls
the same Python code the tests import. There is no JavaScript copy of the
battle rules to fall out of step.

For the design, the HTTP API and the list of known gaps, see
[docs/visualizer-spec.md](../docs/visualizer-spec.md).

## Running it

```
python -m visualizer.serve
```

or `python run.py 7`. A browser tab opens on
`http://localhost:8000/visualizer/index.html`. Stop the server with
Ctrl-C.

| Flag | Meaning |
|---|---|
| `--port N` | Serve on another port. Default 8000. |
| `--no-browser` | Do not open a tab. |

You do not need Node.js: the built page is committed in `visualizer/dist/`.

The server and the search need only the Python standard library. The PPO
engine also needs numpy (`pip install -r requirements-vision.txt`). Without
it the page still works and the PPO side reports why it is unavailable.

The server listens on `127.0.0.1` only. It serves files from the
repository directory, so do not expose the port beyond your own machine.

## What you see

### The banner

- **Engine selector.** "PPO (RL)", "Search", or "Both (Compare)". This
  chooses whose path is highlighted in the tree.
- **Preset.** The objective the search optimises (Balanced, Speedrun,
  Conserve, Survive, Glass cannon). The PPO engine ignores it.
- **Depth.** How many rounds deep the search looks when choosing its line,
  1 to 4. Depth 3 and above can take a long time on a crowded board.
- **Think.** Passed to the PPO engine as its evaluation budget. Despite the
  "s" beside it, it is not a time limit, and it does not limit the search.
- **Show Best Path.** Opens the tree along the selected engine's first
  move and folds the alternatives into a "+N more" chip.
- **Collapse.** Closes everything below the root.
- **Setup.** Opens the scenario builder.

Below the controls, a card shows the leading engine's first move. When the
two engines disagree, a second card shows the other engine's move with a
"Use Move" button that swaps them. If the PPO engine wants a Resistance
Unite used first, a "UNITE FIRST" notice appears beside the card.

The two engines here are **PPO** (`solver/search/hybrid.py`, a trained
policy with a local search) and **Search** (expectimax,
`solver/search/expectimax.py`). The **Playout** engine, which leads in the
live panel, is not available in the visualizer.

### The tree

The tree grows downward from the starting position.

| Node | Meaning |
|---|---|
| Toon's turn | A position. Its children are the moves available. |
| A gag | One move, with its expected value (EV) under the chosen preset. Values on tree nodes come from a one-round search, whatever the Depth setting. |
| An outcome | One result of that move, with its probability. The eight likeliest are shown; the rest are merged into one "N rarer outcomes" node. |
| Victory / Sad | The battle ended. |

Click a node to select it and load its children. Nothing is computed until
you open it, so a deep tree is many small requests.

Moving around:

- Scroll to zoom. The point under the cursor stays put.
- Drag to pan. A drag of more than a few pixels does not count as a click.

In "Both" mode, the first move of each engine is outlined: green for PPO,
blue for Search, amber where they agree.

### The inspector

The panel on the right describes the selected node:

- **Toon Party.** Each toon's laff and pink slips.
- **Cog Lineup.** Each cog's level, hit points, and whether it is lured
  (with rounds left), trapped (with the trap's level) or a Version 2.0 cog.
- **Cog Threat Forecast.** For each cog, its three likeliest attacks with
  the chance of each and its damage.
- **Expected Best Line.** The search's plan from the starting position:
  its best move, then the single most likely outcome, then its best move
  from there, and so on. It is the modal line, not a guaranteed one.

### The scenario builder

**Setup** opens a dialog for the position.

- **Scenario presets** fill it with a generated position: Cog Building,
  Scrappy Fight, Weird Mid-Battle, Wall of Cogs, Combo Setup.
- **Toons.** One to four. For each: laff, organic track, pink slips, and a
  grid of gag counts by track and level. "Randomize Toon" fills one in.
- **Cogs.** One to four. For each: department, name, level, hit points,
  lured (and for how many rounds), trapped (and with which trap), and
  Version 2.0.

**Update Battle Tree** sends the position to the server. The server
rejects a loadout no toon could carry (more than six gag tracks, more than
a full pouch, or more of one gag than its carry limit) and reports why.
Those limits are `[CONFIRMED]` from the TTR wiki and live in
`solver/data/gags.py`; [docs/data-confidence.md](../docs/data-confidence.md)
explains the tags.

## Known gaps

The page was rebuilt recently and is less finished than the live panel.
These are visible in the source; none of them affects the solver itself.

- **Forecast card.** The cog's name, the "Target" line and the "Dmg" totals
  read fields the server does not send, so they show placeholders ("Cog
  1", "Random Toon", 0). The per-attack percentages and damage are real.
  Attack names are not shown.
- **Inspector counts for unites and SOS cards** are not filled in.
- **Unites and SOS cards cannot be edited** in the builder. The default
  position carries two of each. A toon loaded from a preset or randomised
  arrives without unites.
- **The Fit button does nothing.**
- **Path highlighting covers the first move only**, not the whole line.
- **The builder repeats two tables from the solver**: per-gag carry limits
  and the cog hit-point formula. The server validates the loadout again,
  so a stale copy cannot produce a wrong answer, but it can mislabel a
  limit in the dialog.
- **Parties are only partly supported.** The builder and the server accept
  up to four toons. The tree and the best line come from the solo search,
  which chooses for the first toon. The PPO engine plans every toon and
  the page shows the first toon's move.
- **Data gaps carry through.** A cog with a `[TODO]` cell in its attack
  table makes the server report an error for that node rather than show a
  made-up number.

## Icons

The page shows an icon for each gag, a portrait for each cog and an emblem
for each department. They are Toontown Rewritten's artwork, taken from the
TTR wiki.

```
python tools/fetch_icons.py
```

downloads 85 images into `visualizer/assets/`, which is gitignored.
File names are derived from the solver's own identifiers
(`gag-lure-2.png`, `cog-bossbot-the_big_cheese.png`, `dept-lawbot.png`),
and `tests/test_bridge.py` checks that.

You only need to run it before rebuilding the page: the build copies
`visualizer/assets/` into `visualizer/dist/assets/`, and the committed
build already contains a copy. An icon whose file is missing hides itself
and the page falls back to text.

## Changing the page

```
python tools/fetch_icons.py                 # once; the build copies these
python -m visualizer.serve --no-browser     # the API, on port 8000
cd visualizer
npm install
npm run dev                                 # Vite dev server; /api is proxied to port 8000
npm run build                               # writes dist/, which is committed
```

| Path | What it is |
|---|---|
| `serve.py` | The local server: static files and `POST /api/call`. |
| `bridge.py` | The only translation layer between JSON and the solver. Serialisation and labels, no game rules. |
| `src/App.jsx` | Page state: the tree, the two engines' answers. |
| `src/api.js` | One function per server call. |
| `src/components/` | `DualEngineBanner`, `TreeCanvas`, `Inspector`, `ScenarioBuilder`, `Icons`. |
| `dist/` | The built page that `serve.py` serves. |
| `worker.js` | Left over from an earlier version that ran the solver in the browser. The current page does not load it. |

If the page needs a number, add it to `bridge.py` so it comes from the
solver. Do not compute game rules in JavaScript.

Tests for the server side run with the rest of the suite
(`python -m unittest discover tests`): `tests/test_bridge.py`,
`tests/test_visualizer_bridge.py` and `tests/test_visualizer_e2e.py`.
