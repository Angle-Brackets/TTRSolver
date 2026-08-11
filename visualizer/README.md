# Visualizer

`ToontownTreeExplorer.jsx` — a standalone React component that renders a
lazy expectimax decision tree for a fight. Nodes compute their children
only when expanded, so the tree never eagerly blows up.

It expects React, `lucide-react`, and Tailwind classes; it was authored as
a self-contained Claude artifact and has no build setup in this repo yet.
Drop it into any React sandbox (or a Vite + Tailwind app) to run it.

## Not wired to `solver/`

The component carries its **own small hardcoded copy** of the game data and
rules — a subset ported from `solver/data/`, with the same confidence
distinctions (unconfirmed values are marked `isDemo` and rendered with a
dashed "demo data" badge rather than mixed in silently).

That means there are currently two copies of the battle rules in this repo.
Which one wins is a deliberate open decision — see
[docs/roadmap.md](../docs/roadmap.md) item 5:

- keep the JS port (fast, no backend, but a second copy of the rules to
  keep in sync), or
- render precomputed trees exported from the Python solver as JSON (single
  source of truth, but static rather than interactively reconfigurable
  in-browser).

Until that's settled, treat any change to `solver/` mechanics as
potentially making this file stale.
