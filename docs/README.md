# Documentation index

Start with the [project README](../README.md) for what TTRSolver is and how
to run it. The documents here go further.

Each entry is marked **reference** (describes the project as it is now) or
**record** (a dated account of what was tried and found, kept for the
reasoning; later work may have superseded details in it).

## Using it

| Document | What it is | Kind |
|---|---|---|
| [user-guide.md](user-guide.md) | Setting up and using the live panels | Reference |
| [live-reading.md](live-reading.md) | How the game is read: each source and its limits | Reference |
| [realms.md](realms.md) | Toontown Realms support | Reference |
| [panel-contract.md](panel-contract.md) | The data contract between the worker and the overlay UI | Reference |
| [visualizer-spec.md](visualizer-spec.md) | The browser visualizer | Reference |

## How it works

| Document | What it is | Kind |
|---|---|---|
| [architecture-review.md](architecture-review.md) | How the pieces fit together | Reference |
| [playout.md](playout.md) | The Playout engine: Monte Carlo playouts to the end of the fight | Reference |
| [rollout-network.md](rollout-network.md) | The rollout network and the value network behind the playouts | Reference |
| [search-depth.md](search-depth.md) | The expectimax search: depth and branching | Reference |
| [scoring.md](scoring.md) | The one-round scorer used by the PPO row | Reference |
| [scorer-audit.md](scorer-audit.md) | An audit of the party scorer | Record |
| [heuristic-learning.md](heuristic-learning.md) | Learned leaf evaluation for the search | Reference |
| [ml-design.md](ml-design.md) | The PPO policy: scope and design | Reference |
| [ppo-math.md](ppo-math.md) | The mathematics of the PPO policy | Reference |
| [reward-experiments.md](reward-experiments.md) | Reward ablations for the PPO policy | Record |

## The game

| Document | What it is | Kind |
|---|---|---|
| [mechanics-notes.md](mechanics-notes.md) | Battle mechanics as implemented | Reference |
| [data-confidence.md](data-confidence.md) | What is confirmed and what is not, and what the provenance tags mean | Reference |
| [sos-notes.md](sos-notes.md) | SOS toons | Reference |
| [party-strategy.md](party-strategy.md) | Party play: what the trials found and what they cannot yet show | Record |

## Record

| Document | What it is | Kind |
|---|---|---|
| [roadmap.md](roadmap.md) | What is done, open and shelved | Record |
| [experiment-log.md](experiment-log.md) | The lab notebook: what was tried, what it measured, and what lost | Record |
| [live-notes.md](live-notes.md) | The debugging record behind the screen reader | Record |

## Reading the numbers

Win rates in these documents come from simulated fights unless a document
says otherwise. Game values are tagged by where they came from:
`[CONFIRMED]` (the Toontown Rewritten wiki), `[OWNER]` (the maintainer's
judgement as an experienced player, not a sourced fact),
`[OPEN TOONTOWN SOURCE]` (the open-source Toontown Online reimplementation;
a lead, not confirmation), `[ASSUMED]` (a labelled assumption) and `[TODO]`
(unknown; the code raises instead of substituting a value).
[data-confidence.md](data-confidence.md) has the detail.
