# Visualizer

An interactive view of the expectimax tree, running **the real solver** —
the Python package is loaded into the browser with Pyodide, so there is no
JavaScript copy of the battle rules and nothing to keep in sync.

## Running it

```
python -m visualizer.serve
```

That's the whole setup. No Node, no npm, no build step — a browser opens on
`http://localhost:8000/visualizer/index.html`. The first load pulls the
Pyodide runtime (~10 MB) from a CDN and is slow; after that it's cached.

Flags: `--port N`, `--no-browser`.

## How it works

```
index.html ──fetch /api/manifest──► serve.py  (lists solver/**/*.py)
     │                                  │
     └──fetch each .py────────────────► writes them into Pyodide's FS
     │
     └── import bridge ──► bridge.py ──► solver.outcomes / solver.search
```

`bridge.py` is the only translation layer: JSON in, JSON out. It holds
serialization and display labels and **no game rules** — if the page needs
a number it calls into `solver/`. There's a test suite for it at
`tests/test_bridge.py`, including a check that the group-gag flags it sends
the UI match `simulator.is_group_action` rather than restating them.

The tree expands lazily: clicking a node calls Python for that layer only,
so nothing is computed until you look at it. Each action shows its expected
value and **the gap to the runner-up** — near zero means the decision
doesn't matter, and a large gap means the position has a real right answer.

## Why it's built this way

The previous version was a standalone React component with its own
hardcoded port of the rules and data. It drifted, exactly as you'd expect:
by the time it was retired it still believed Small Magnet was
single-target, that lures never expired, that Flunkies had a flat 75%
accuracy, and it labelled the level-2 lure "Hypno Goggles" (that's level
6). Every one of those was correct when written.

Two copies of a rule set is one copy too many, so the JS port is gone —
`ToontownTreeExplorer.jsx`, recoverable from git history if you ever want
the old layout. The UI here is deliberately plain (inline CSS, no Tailwind
or icon library) so that it stays a thin shell over the solver and can be
served from a single file.

## Caveats

Numbers on the page inherit the model's data gaps — cog attack frequency
and accuracy in particular are pre-4.0.0 values the wiki doesn't publish.
See [../docs/data-confidence.md](../docs/data-confidence.md). A cog with a
`[TODO]` cell (Micromanager, The Big Cheese, Big Wig) shows the raise as an
inline error on the node rather than a wrong number.

Depth 3 on four cogs is slow — the search is single-threaded and blocks the
page while it runs. Start at depth 2.
