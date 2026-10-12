# The panel contract

The interface between the Python worker and the overlay page: every field
Python sends, every method the page may call, and the behaviour a UI
change has to respect. Written for anyone working on `overlay_ui/`.

One built page serves two programs: the Toontown Rewritten (TTR) panel
(`solver/live/panel.py`) and the Toontown Realms panel
(`solver/live/realms_panel.py`). Both send the same JSON and expose the
same method names, so the page never needs to know which one it is
talking to.

| | |
|---|---|
| Payload | `panel.model_json(model)`, where `model` is the `Model` dataclass in `solver/live/overlay.py` |
| Size | 79 top-level fields, 12 fields per cog row |
| Methods | 24, on `panel.Api` and `realms_panel.RealmsApi` |
| Page | `overlay_ui/src/App.jsx` and `CogPicker.jsx` |

If this file and the code disagree, the code is right.

## The one rule

**The page renders; Python decides.** If the page needs something the
model does not expose, add a property to `Model` rather than computing it
in JavaScript.

Every decision the panel makes (whether a fight may be confirmed, what the
evidence line says, when the feedback strip expires) lives in `Model` or
in `solver/live/worker.py`, where it is tested without a display. A second
implementation in the page would drift, and the page's copy is the one no
test covers.

## Transport

The page runs in a pywebview window and reaches Python through
`window.pywebview.api`.

- **Python pushes.** A Python thread calls
  `window.pushModel(<model JSON>)` through `evaluate_js` after each worker
  update, and at least every 0.25 seconds when there is none. The
  page installs `window.pushModel` on mount and merges each payload over
  its own defaults (`EMPTY` in `App.jsx`), so a field missing from a
  payload renders as its default rather than as `undefined`.
- **The page does not poll.** `pull()` returns the same JSON and exists
  for driving the page by hand; the page never calls it.
  `panel.PULL_INTERVAL_MS` is a leftover from an earlier design and
  nothing reads it.
- **Calls are one way.** The page calls a method and ignores the return
  value. The effect arrives in a later push. All calls go through the
  `call(name, ...args)` helper in `App.jsx`, which does nothing when
  `window.pywebview` is absent, so the page runs in a plain browser.

## Top-level fields

A type written `T | null` means the value can be absent and must render
as absent, never as zero.

### The move on screen

| Field | Type | Notes |
|---|---|---|
| `advice` | string | The move in words. `""` when there is none. It lingers for 4 seconds after a battle ends, so non-empty `advice` does not imply `in_battle`. |
| `track` | string \| null | The gag's track slug (`toon_up`, `trap`, `lure`, `sound`, `throw`, `squirt`, `drop`), or one of two sentinels: `"fire"` for a pink slip and `"sos"` for an SOS card. `null` for a pass or no advice. |
| `gag_level` | int \| null | 1 to 7. With `track` it selects the picture `gag-<track>-<level>.png`. For `"fire"` and `"sos"` it carries a placeholder 7 that the page ignores. `null` when `track` is. |
| `engine` | string | Which engine produced `advice`: `"rl"`, `"search"`, `"playout"`, or `""`. `"rl"` is the PPO row. |
| `unite` | string | A Resistance Unite to use alongside the move, as a phrase, or `""`. It is separate from `advice` because a unite costs no turn: the round is "use this, then throw that". |
| `reason` | string | A short why-line for the displayed move. `""` when there is nothing worth saying. |
| `accuracy` | int \| null | Chance to hit, percent, for the displayed move. Forced values are real: 100 and 0 are answers, not clamps. |
| `organic` | bool | Whether the displayed gag's track is organic. |
| `organic_tracks` | string[] | Every organic track the toon has. Sent but not currently read by the page. |
| `incoming` | float \| null | Expected damage to the toon's side this round. Describes the board, not the move. |
| `survive` | float \| null | Rounds the laff covers at that rate. Capped at 4.0, which means "four or more". |

`reason`, `accuracy` and `organic` always mirror the engine named by
`engine`. `AdviceWorker._sync_explanation` enforces that wherever
`engine` changes.

### The three engines

Each engine reports its own move and its own reasons, so a row never
borrows another engine's numbers.

| Field | Type | Notes |
|---|---|---|
| `engines` | string[] | Which engines this panel runs at all, in row order. A row is drawn only for an engine listed here. TTR sends all three. Realms sends a subset when started with `--engine`. |
| `preferred_engine` | string | The engine whose move should lead. The dataclass default is `"rl"`, and both workers set it to `"playout"` on their first cycle. A click on an engine sets it for the rest of the session. It can differ from `engine` while the preferred engine is still thinking. |
| `rl_gag`, `search_gag`, `playout_gag` | string | That engine's move in words. `""` until it answers. |
| `rl_track`, `search_track`, `playout_track` | string | Its track slug or sentinel. `""` for none. |
| `rl_gag_level`, `search_gag_level`, `playout_gag_level` | int | Its level. 0 for none. |
| `rl_accuracy`, `search_accuracy`, `playout_accuracy` | int \| null | Its chance to hit. |
| `rl_reason`, `search_reason`, `playout_reason` | string | Its why-line. |
| `rl_organic`, `search_organic`, `playout_organic` | bool | Whether its gag is organic. |
| `search_ready` | bool | The search has answered for this position. |
| `playout_ready` | bool | The playouts have posted at least one answer. |
| `playout_pending` | bool | A playout job is running. The Playout row shows "Thinking..." only while this is true. |
| `playout_rollouts` | int | Playouts per candidate behind the move shown. |
| `playout_done` | bool | Refining has stopped. While false and `playout_ready` is true, the move may still change. |
| `playout_note` | string | Why a finished playout has no move, for the row to show instead of spinning. |
| `playout_unite` | string | The unite the playouts' move is planned with. Python copies it into `unite` when the Playout move is displayed; the page does not read it directly. |
| `thinking` | bool | PPO or the search is working. Drives "Thinking..." on those two rows and the large card. |

There is no `rl_ready`: the PPO row is ready when `rl_gag` is non-empty.

### The board

| Field | Type | Notes |
|---|---|---|
| `in_battle` | bool | Detected, or asserted by the player. |
| `status` | string | `"waiting"`, `"in battle"` or `"confirmed"` (the player asserted it). |
| `turn` | int | Estimated round number, 0 when unknown. On TTR it is inferred from the gag menu opening and misses a round the timer played. Label it as an estimate. |
| `rows` | CogRow[] | One per cog. See [Cog rows](#cog-rows). The page draws at most four. |
| `problems` | string[] | Why there is no position to advise on. Non-empty also means the move still on screen is stale. The page draws at most four. |
| `evidence` | string | What the reader can see: `"see: 2 cog plates, gag menu"`, `"nothing on screen that looks like a battle"` or `"game window not found"`. |
| `pouch` | PouchRow[] | The gags the toon is carrying, for the "I'd use…" picker. Filled by the Realms panel only; `[]` on TTR, which hides the picker. |

### Controls, mirrored back

Each of these is owned by the worker. The page shows the value it is sent
and never keeps its own copy.

| Field | Type | Notes |
|---|---|---|
| `can_confirm` | bool | Whether the fight button is enabled. True during a battle; outside one, true when the game window is found. |
| `can_advise` | bool | In a battle and not thinking. Gates the Reconsider button. |
| `allow_level_7` | bool | Whether level 7 gags may be advised. |
| `objective` | string | Preset name: `balanced`, `conserve`, `glass cannon`, `speedrun` or `survive`. |
| `budget` | float | Think time in seconds. |
| `toon_count` | int | 1 to 4, counting the player. Set by hand on TTR; read from the server on Realms. |
| `party_mode` | string | `"pickup"`, `"coordinated"`, or `""`. The Strangers / My party toggle is drawn only when this is non-empty and `toon_count > 1`. Both panels currently send `""`: the TTR feature behind it is switched off (`Worker.stand_in_teammates`). |
| `max_fires` | int | The pink slip budget box, 0 to 99. A session budget that ticks down as slips are spent. |
| `max_unites` | int | The unite budget box. |
| `max_sos` | int | The SOS card budget box. On TTR it is not passed to the engines. |
| `fires_left`, `unites_left`, `sos_left` | int | What the engines may still plan with. Equal to the boxes today. The page reads only `fires_left`, to decide whether the "I'd use…" picker offers a pink slip. |

### Boss fight

| Field | Type | Notes |
|---|---|---|
| `boss_kind` | string | `"vp"`, `"cfo"`, `"cj"`, `"ceo"`, or `""` for none. The fight in effect. |
| `boss_manual` | string | What the player picked, or `""` for "use detection". The page labels the picker "Detected" when `boss_kind` is set and this is empty. |
| `cogs_defeated` | int | Cogs defeated this boss fight. 0 when there is no boss. |
| `cogs_left` | int | Cogs still to beat, or -1 where the fight's size is not known. Render -1 as unknown, never as a number. |

### Location and decoration

| Field | Type | Notes |
|---|---|---|
| `zone`, `neighborhood`, `district` | string | From the TTR Local API. `""` when not connected. While inside a Cog building with the floor known, `zone` ends with `", floor 2 of 4"`. |
| `invasion` | string | Active invasion in words, or `""`. |
| `discord_floors` | string | State of the building-floor reader: `"on"`, `"blocked"` (Discord holds the pipe, so the page offers a restart), `"restarting"`, or `""` where there is none. |
| `lure_icon` | string | A `data:` URI of the game's lure icon, read from the player's own TTR installation at start-up. `""` when the game is not installed. |
| `organic_icon` | string | Same, for the organic leaf. |
| `track_icons` | object | Track slug to `data:` URI for each track's badge. May be `{}` or partial. |
| `map_icon` | string | Same contract. Sent but not currently read by the page. |

Each icon can be missing. The page must fall back to text and never show a
broken image.

### Feedback strip

A receipt of the move the player was seen to make. Only the Realms panel
fills these. On TTR they stay at their defaults and the strip never
renders.

| Field | Type | Notes |
|---|---|---|
| `feedback_showing` | bool | Whether the strip is on screen. A decision made in Python: it expires 3.5 seconds after the row was written. |
| `feedback_move` | string | The move that was logged. |
| `feedback_stated` | bool | True when the player said it through "I'd use…", false when it was inferred from the pouch. The strip words these differently ("you said:" and "logged:"). |
| `feedback_against` | string | The engines whose advice it differed from. |
| `feedback_problem` | string | Shown instead of a move when the round could not be logged. |
| `feedback_fixable` | bool | Whether the "wrong?" control is offered. True only for the most recent row. |
| `feedback_needs_target` | bool | Whether the row is missing its target cog, in which case "wrong?" offers the cogs to pick from. |

## Cog rows

| Field | Type | Notes |
|---|---|---|
| `index` | int \| null | Position in the row order. The key for every per-cog call. |
| `name` | string | Display name, or the department name when the cog is unidentified. |
| `identified` | bool | False when the reader could not settle on one cog. |
| `level` | int \| null | `null` when the level could not be read; the page then shows a level picker. |
| `department` | string \| null | `bossbot`, `sellbot`, `cashbot` or `lawbot`. |
| `health` | float | 0.0 to 1.0. On TTR, anything read at 0.85 or above is sent as exactly 1.0, because the bar under-reads and the solver treats it as full. Do not undo this. |
| `hp`, `max_hp` | int \| null | Hit points. Set on TTR when the level is known. The Realms panel leaves both `null`, so its rows show a percentage. |
| `art` | string \| null | `<department>-<cog key>`, selecting `cog-<art>.png`. `null` when unidentified; fall back to the department emblem `dept-<department>.png` rather than draw a specific cog. |
| `lured` | bool | On TTR, read from the plate and overridable by the player. On Realms, stated by the server. |
| `trapped` | bool | Stated by the server on Realms. Always false on TTR, where nothing reads it. The page does not draw it. |
| `choices` | object[] | Options for the name picker: `key`, `display`, `department`, `likely`, `current`. On TTR this is every cog in the game with the likely ones flagged, because a misread department would otherwise hide the right answer. `[]` on Realms. |

A pouch row (Realms only) is `{track, level, count, name, group}`. `group`
marks a gag that hits every cog, for which the picker asks for no target.

## Methods

Both API classes define every method, because the page is shared and a
missing method fails silently at click time. A method that has no meaning
for one panel exists there and does nothing.

| Method | Arguments | TTR panel | Realms panel | Called by the page |
|---|---|---|---|---|
| `pull()` | none | Returns the model JSON. | Same. | No |
| `prefer_engine(name)` | `"rl"`, `"search"` or `"playout"` | Shows that engine's move and makes it the standing preference. Anything else is treated as `"rl"`. | Same. | Yes |
| `reconsider(scope)` | `"gag"`, `"track"`, or omitted | Rejects the displayed move and recomputes. `"gag"` rejects that gag, `"track"` the whole track, and omitting it rejects the gag's kind (same track and same single-target or group type). Lasts until the position changes. Reaches the PPO and Playout engines; the search has no rejection filter. | Same. | Yes, with `"gag"` and `"track"` |
| `toggle_fight()` | none | In a battle: ends it and clears everything derived from it. Otherwise: asserts a battle and recomputes. | Re-reads the stream and recomputes. | Yes |
| `ask_now()` | none | Recompute on the next cycle. | Same. | No |
| `set_objective(name)` | preset name | Switches preset and recomputes. Unknown names are ignored. | Same. | Yes |
| `set_budget(seconds)` | number | Think time, clamped to 1 to 60. | Same. | Yes |
| `set_level_7(allow)` | bool | Allows or withholds level 7 gags and recomputes. | Same. | Yes |
| `set_toon_count(count)` | int | Toons in the fight, clamped to 1 to 4. Recomputes. | Sets a floor on the toons in a boss fight; the party in the player's own battle is read and not overridden. | Yes |
| `set_party_mode(mode)` | `"pickup"` or `"coordinated"` | Stored, but has no effect while the feature is off. | Does nothing. | Yes, but the control is hidden |
| `set_boss(kind)` | `"vp"`, `"cfo"`, `"cj"`, `"ceo"` or `""` | Names the boss fight by hand; `""` returns to detection. A detected fight takes precedence over a manual pick. Changing the fight restarts its count. | Same. | Yes |
| `set_cogs_defeated(count)` | int | Corrects the boss count. | Same. | Yes |
| `set_max_fires(count)` | int | Sets the pink slip box, clamped to 0 to 99. Recomputes. | Same. | Yes |
| `set_max_unites(count)` | int | Sets the unite box. | Same. | Yes |
| `set_max_sos(count)` | int | Sets the SOS box. Stored but unused on TTR. | Sets the SOS box. | Yes |
| `mark_lured(index, lured)` | int, bool | Overrides the lure read for that row and recomputes. | Does nothing. | Yes |
| `mark_trapped(index, trapped)` | int, bool | Writes the flag onto the current row only. The next read rebuilds the rows and the engines never see it. | Does nothing. | No |
| `name_cog(index, key)` | int, cog key | Names that row's cog for this fight, shown at once. A cog not yet in the head library is also added to it. | Does nothing. | Yes |
| `set_cog_level(index, level)` | int, int | States a level the reader could not settle, for this fight. | Does nothing. | Yes |
| `suggest_move(track, level, target_index, fire, is_pass)` | see below | Does nothing. | Records the move the player says they would make. Needs `--feedback PATH`. | Yes |
| `correct_feedback(target_index, discard)` | int \| null, bool | Does nothing. | Amends the last feedback row with a target, or discards it. | Yes |
| `restart_discord()` | none | Closes Discord, takes its pipe, starts Discord again. Runs off the UI thread. | Does nothing. | Yes |
| `set_height(px)` | int | Resizes the window to the page. Clamped to 160 to 900. | Resizes to `px + 16`, minimum 120. | Yes |
| `close()` | none | Quits. | Same. | Yes |

`suggest_move` takes five positional arguments: a track slug or `null`, a
level or `null`, a target row index or `null`, whether it is a pink slip,
and whether it is a pass.

The page must report its height through `set_height` whenever its content
changes size. It measures `#panel.scrollHeight`, on mount and from a
`ResizeObserver`.

## What the tests enforce

| Test | What it checks |
|---|---|
| `tests/test_panel_bridge.py` | Every `call('name', ...)` in `overlay_ui/src/*.jsx` names a method on `panel.Api` with the same number of arguments. Every `model.<field>` the page reads is in `model_json`. `call` is declared at module scope so every component can reach it. `panel.main` imports. |
| `tests/test_realms_panel.py` | Every method the page calls exists on `RealmsApi`. The Realms panel pushes the model into the page. |
| `tests/test_overlay.py` | The decisions in `Model` and the workers, without a display. |

The argument check reads call sites with a regular expression that stops
at the first `)`. Keep every `call(...)` flat: pass plain variables, not
nested function calls, or the check counts the wrong number of arguments.

Run them with the rest of the suite:

```
python -m unittest discover tests
```

## Behaviour a UI change must respect

**Null means unknown.** `incoming`, `survive`, `accuracy`, `hp`, `max_hp`
and `level` arrive as `null`, and `reason` as `""`, when they could not be
worked out. Hide the element. Rendering `null` as 0 would say "nothing is
coming at you", the opposite of "not known".

**`survive` saturates.** Render 4.0 as "4+".

**`cogs_left` of -1 is "unknown".** Several boss fights have sizes the
project has not confirmed, and the panel does not invent a total.

**Non-empty `problems` means stale advice.** Cog rows are rebuilt on every
read; the advice is replaced only when an engine answers. While
`problems` is non-empty the page shows live rows beside a move computed
for an earlier position, so it greys the move and tags it "STALE". On TTR
the worker retries every 2 seconds in this state.

**`engine` and `preferred_engine` can differ.** The Playout and Search
engines take seconds. Until the preferred one answers, the move on screen
is another engine's. Show the preference as selected and the source as a
badge on the move.

**The player's marks are scoped to one fight and keyed on row order.** A
hand-picked name, level or lure mark is stored against the row index and
cleared when the battle ends. Within a fight the indexes shift when a cog
is defeated. Drive every toggle from the model and let the call be the
only writer; a local mirror in the page will fight the next push.

**Cogs have no weaknesses.** Every gag works on every cog. There is no
field for a type chart because there is nothing of the kind to read.

**The game's own icons come from the player's installation.** `lure_icon`,
`organic_icon`, `track_icons` and `map_icon` are extracted at run time and
passed inline. The gag and cog pictures under `overlay_ui/src/assets/` are
separate files bundled into the build.

**The window is small and sits over a running game.** Keep the move
readable at a glance and keep motion away from it.

## Adding a field or a method

1. Add the field to `Model` (or a property, if it is a decision) and to
   `model_json`.
2. Add its default to `EMPTY` in `App.jsx`.
3. For a method, add it to **both** `panel.Api` and
   `realms_panel.RealmsApi`, as a stub where it has no meaning.
4. Run the tests above, then `npm run build` in `overlay_ui/` and commit
   `dist/`. See [overlay_ui/README.md](../overlay_ui/README.md).
5. Update this file.
