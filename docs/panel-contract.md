# The panel contract

Everything `solver/live/panel.py` sends the page, what the UI should
build next with it, and the places where a reasonable-looking guess
would be wrong.

Written for whoever is working on `overlay_ui/`. The field lists below
are read off `panel.model_json`, `overlay.Model` and `overlay.Api`
rather than from memory; if they disagree with the code, the code wins
and this file is stale.

- source: `panel.model_json`
- 52 top-level fields, 12 per cog row, 17 callable methods
- the page polls every 400 ms

## The one rule

**If the UI needs something the model does not expose, the fix is a
property on `Model`, not a calculation in JavaScript.**

`model_json` is the whole interface. Every decision the panel makes --
whether a fight can be confirmed, what the evidence line says, when
advice goes stale -- already lives in Python, where it is tested without
a display. Two implementations of "may the player confirm a battle" will
drift, and the one in the UI is the one nobody tests.

So *render* these fields, don't recompute them. Anything below marked
**needs Python** is a small change on our side -- ask for it rather than
deriving it in the page.

## What to build, in order

Ranked by how much it changes a round for the player. The first four
cost no Python at all: the data is already in the payload and the page
currently drops it on the floor.

### 1. The why-line — *in the payload*

One quiet line under the advice: `reason` plus the hit chance. Reads as
"Hypno-Goggles — *kills 2 · 95%*". Today the advice arrives as an
instruction with no argument attached, which is the single biggest thing
missing. `reason` is already ordered by what decides a round: kills,
then damage prevented, then a trap armed, then damage dealt.

*uses* `reason`, `accuracy`

### 2. Board pressure — *in the payload*

Expected damage this round, and how many rounds the party's laff covers.
This is the number that tells a player to heal instead of attack, and it
comes off the same function the scorer reads. Show `survive` as a small
gauge -- it is the one field with a natural danger threshold.

*uses* `incoming`, `survive` (capped at 4.0 — render 4.0 as "4+")

### 3. Absolute HP on each cog row — *in the payload*

"98 / 132" beats a bar with no numbers, because the player is choosing a
gag by how much damage it does. Keep the bar; put the figures beside it.
Both are `null` when the plate's level could not be read -- then show the
bar alone, never a guessed maximum.

*uses* `rows[].hp`, `rows[].max_hp`, `rows[].health`

### 4. Second opinion, as a toggle — *in the payload*

Both engines answer every round and both answers are already on the
wire. Make the engine badge a switch instead of a label: tap to read the
other one. `engine` is what produced the text on screen;
`preferred_engine` is what the player asked for -- they legitimately
differ on round one, before the search has finished. Gate the search
side on `search_ready`.

`rl_*` and `search_*` each carry their own accuracy, reason and organic
flag, so this can be two rows showing both picks side by side rather
than a toggle showing one at a time.

*uses* `engine`, `preferred_engine`, `rl_gag`, `search_gag`,
`search_ready`, `prefer_engine(name)`

### 5. Damage and kills per move — **needs Python**

`explain.describe` already computes `damage`, `kills`, `prevented` and
`arms` on every recommendation -- and `overlay.py` throws all four away,
keeping only the phrase built from them. Forwarding them is four lines.
Worth it if the UI wants to show the arithmetic rather than the summary.

It also computes `targets` (how many cogs the move actually damages)
and `each` (the per-cog amount, when every target took the same). Those
two are what stop a group gag reading as a single huge hit: Foghorn on
two cogs is `damage: 100`, `targets: 2`, `each: 50` — and "100 damage"
beside a 110 hp cog looks like a near-kill when both cogs in fact
survive. `reason` already says "50 to each of 2 cogs"; the raw numbers
would let the UI lay it out properly.

`each` is deliberately absent when the spread is uneven — a lured cog
takes the knockback bonus, so there is no single per-cog figure to
quote, and the line falls back to "300 damage across 2 cogs".

*would add* `damage`, `kills`, `prevented`, `arms`, `targets`, `each`
-- plus `rl_track`, `rl_gag_level`, `search_track`, `search_gag_level`
if the runner-up needs a gag icon.

### 6. The connection strip — *in the payload*

District, neighborhood, zone and any active invasion, in a thin footer.
The solver does not use any of it -- a street does not change a round.
It is there so the player can tell at a glance whether the panel is
talking to the game at all, which the cog readers cannot: they work off
pixels and look identical with the API disconnected.

*uses* `district`, `neighborhood`, `zone`, `invasion`

## Top-level fields

The complete payload from `pull()`. `| null` marks a field that will be
absent and must render as absent -- not as zero.

### The answer

| Field | Type | Notes |
|---|---|---|
| `advice` | string | The gag to throw. `""` when there is none. **Lingers 4 s after a battle ends** — a non-empty `advice` does not imply `in_battle`. |
| `track` | string \| null | Lowercase track name, for the accent colour and the gag icon. Null exactly when the advice is a pass or a pink slip — those are not gags and have no picture. |
| `gag_level` | int \| null | 1–7. With `track` it keys `gag-<track>-<level>.png`. Null in exactly the same cases as `track`. |
| `unite` | string | A unite to use *alongside* the gag, e.g. `"80 Toon-Up unite"`; `""` for none. Deliberately not folded into `advice`: a unite costs no action, so the round is "use this, *then* throw that". Rendering them as one line reads as a choice between them. |
| `reason` | string | `""` when there is nothing worth saying. Render nothing, not a blank row. |
| `organic` | bool | Whether the recommended gag's track is organic. **From the Local API, not the screen** — it states organic outright, so nothing has to recognise the sprout on the gag button. Worth showing: organic raises damage, and Lure's accuracy with it. |
| `organic_tracks` | string[] | Every organic track this toon has, lowercase. Same source. Lets the UI mark a whole gag menu, not just the advised gag. |
| `accuracy` | int \| null | Percent, as the game computes it — forced values come through stated (Trap always hits; Drop always misses a lured cog), so 100 and 0 are real answers rather than clamps. |
| `incoming` | float \| null | Expected damage to the party this round. |
| `survive` | float \| null | Rounds the party's laff covers. **Capped at 4.0**, so 4.0 means "four or more". |

### The board

| Field | Type | Notes |
|---|---|---|
| `rows` | CogRow[] | One per plate on screen. See below. |
| `turn` | int | 0 when unknown. **An estimate** — nothing reports the round, so it is inferred from the gag menu opening. It misses a round you let the timer pick for you. Label it as approximate wherever it appears. |
| `in_battle` | bool | Detected, or asserted by the player. |
| `status` | string | `"waiting"` / `"in battle"` / `"confirmed"`. The turn is deliberately not in here; show it separately. |
| `problems` | string[] | **Why there is no advice.** The builder returns a state *or* the reasons there isn't one, never a guess. If this is non-empty and unrendered, the panel looks hung. Give it real space — and see the staleness caveat below, because a non-empty `problems` also means the advice next to it is out of date. |
| `evidence` | string | What the readers can see right now — `"see: 2 cog plates, gag menu"`, or why not. |
| `thinking` | bool | A search is running. |

### Controls, mirrored back

| Field | Type | Notes |
|---|---|---|
| `can_confirm` | bool | May the player assert or end a fight. True whenever the game window is found. |
| `can_advise` | bool | May "work it out now" be pressed. False while thinking, and with no battle. |
| `allow_level_7` | bool | Whether level 7 gags are being offered. |
| `toon_count` | int | 1–4, including you. Set by the player; nothing on screen counts toons reliably. |
| `objective` | string | Preset name, e.g. `"balanced"`, `"survive"`. |
| `budget` | float | Search budget, in seconds. |
| `max_fires` | int | 0–99. Pink slips the solver may plan with. **On TTR this is the count, not a cap on one** — nothing the client exposes says how many a toon holds, so the number typed here is the whole story. Label it "how many you have". |
| `max_unites` | int | 0–99. **Inert on TTR.** Round-trips through the model and never reaches the solver. |
| `max_sos` | int | 0–99. **Inert on TTR**, for the same reason. |
| `fires_left` | int | What is LEFT of `max_fires` after the advice already given this fight. **This is what the solver plans with**, not `max_fires`. Show it as "2 of 5" so a spent resource visibly runs down — the panel used to keep offering slips a run had already used, with nothing on screen to say so. |
| `unites_left` | int | Same, for unites. A unite costs no action, so it is charged alongside the gag it was advised beside. |
| `sos_left` | int | Same, for SOS cards. |

### Engines

| Field | Type | Notes |
|---|---|---|
| `engine` | string | `"rl"` / `"search"` / `""`. What produced the text currently on screen. |
| `preferred_engine` | string | `"rl"` / `"search"`. The player's standing choice; persists across rounds. |
| `rl_gag` | string | The policy's answer, always present once computed. |
| `rl_track` / `rl_gag_level` | string / int | Its track and level, for the gag icon. |
| `rl_accuracy` / `rl_reason` / `rl_organic` | int \| null / string / bool | **The policy's own reasons.** |
| `search_gag` | string | The search's answer. `""` until it finishes. |
| `search_track` / `search_gag_level` | string / int | Same, for the search's pick. |
| `search_accuracy` / `search_reason` / `search_organic` | int \| null / string / bool | **The search's own reasons.** |
| `search_ready` | bool | Whether `search_gag` is worth offering yet. |

The displayed `accuracy` / `reason` / `organic` always mirror the engine
named by `engine`. The per-engine copies exist so the *other* engine's
answer can be shown as a second row with its own numbers rather than
borrowing the winner's — which is what a single pair forced it to do,
and which shipped as a real bug: a Grand Piano was captioned "95% ·
kills 2" because those were the search's Wedding Cake numbers.

### Where you are, and decoration

| Field | Type | Notes |
|---|---|---|
| `zone` | string | From the Local API. `""` when not connected. |
| `neighborhood` | string | Same. |
| `district` | string | Same. |
| `invasion` | string | Active invasion, or `""`. |
| `lure_icon` | string | A `data:` URI for the game's own lure magnet, read from the player's install at runtime. `""` when the game is not installed — **fall back to a text badge, never a broken image**. |
| `map_icon` | string | Same contract. |
| `organic_icon` | string | The game's own green leaf badge, cut out of the battle-GUI palette. Same contract — `""` when the game is not installed, so fall back to a text marker. Pair it with `organic` / `organic_tracks`, which are the *data*; this is only the picture. |
| `track_icons` | object | Track slug → data URI, for the Silly Team badge of each of the seven tracks (`toon_up`, `trap`, `lure`, `sound`, `throw`, `squirt`, `drop`). Read from the player's install like the others, so it is `{}` when the game is not there and **may be partial** — look each one up and fall back to the track's name. Note the key is the solver's `toon_up`, not the game's `toonup`. |

## Each cog row

A plate carries only what a plate shows. Lure and trap state are marked
by the player, not read off the screen.

| Field | Type | Notes |
|---|---|---|
| `index` | int \| null | **Plate order, and the key for every per-cog call** — `mark_lured`, `mark_trapped` and `name_cog` all take this. Not the detected bounding box, which moves a few pixels between frames and matched once and never again. |
| `name` | string | Display name, or a placeholder when unidentified. |
| `identified` | bool | False means the readers could not narrow the plate to one cog. Show the picker. |
| `level` | int \| null | Null at low resolution — the level reader declines rather than guessing. |
| `department` | string \| null | Bossbot / Sellbot / Cashbot / Lawbot. |
| `health` | float | 0.0–1.0. **Snapped:** anything at or above 0.85 comes through as exactly 1.0, because the bar under-reads and the shortfall scales with plate size. Don't un-snap it — showing 91% while the solver correctly used full HP reads as a bug, and was reported as one. |
| `hp` | int \| null | Absolute, derived from the level and the snapped fraction. Null whenever `level` is null. |
| `max_hp` | int \| null | Same condition. |
| `art` | string \| null | `<department>-<key>`, matching `cog-*.png`. Null when unidentified — fall back to the department emblem. Drawing a specific cog would assert more than was read. |
| `lured` | bool | Player-marked. Changes four things at once: Throw and Squirt are forced to 100% and collect knockback, Drop always misses, and the cog does not attack. |
| `trapped` | bool | **Currently inert — do not present it as working.** `mark_trapped` writes onto the model row, and the poll rebuilds every row from the watcher 400 ms later, so the toggle springs back and the solver never hears about it. Making it real needs a trap set on the watcher (like `lured`) *and* a way to say **which** trap gag is under the cog, because `CogStatus.trap_level` is what the damage comes from — a checkbox cannot express that. Ask before building UI for it. |
| `choices` | object[] | **Every cog in the game, not the plate's shortlist** — likely ones sorted first and flagged `likely: true`. The department read can be wrong, and then the cog actually on screen is the one option never offered. Each entry: `key`, `display`, `department`, `likely`, `current`. *Needs a filter box or a grouped list, not a flat dropdown.* |

## What the page may call

Small on purpose. Everything here is a request to Python, which
recomputes and ships a fresh model on the next pull.

| Method | Argument | Notes |
|---|---|---|
| `pull()` | — | Returns the JSON above. The page polls it every 400 ms. Python cannot safely push into the page from its worker thread, so the page asks — which also means a hand-reloaded page recovers on its own. **Don't add a second poller.** |
| `toggle_fight()` | — | Confirm a fight, or end one and reset. |
| `ask_now()` | — | "Work it out now." Gate on `can_advise`. |
| `reconsider(scope)` | `"gag"` \| `"track"` \| omitted | "No, not that." Turns down the move on screen and asks again. `"gag"` rejects this gag alone (no Grand Piano; Safe still offered), `"track"` rejects the track entirely (no Drop at any level), and omitting it keeps the original **kind** width — `(track, group)`, so single-target Drops go and the group one stays. The rejection lasts until the board changes. **It steers the RL engine only** — the search runs in a child process through `expectimax`, which has no root filter, so pressing it while the SEARCH answer is displayed records the rejection but cannot re-aim that engine. |
| `prefer_engine(name)` | `"rl"` \| `"search"` | Swaps which answer is displayed. Both are already computed, so this is free. |
| `mark_lured(index, lured)` | int, bool | Row `index`, not slot. |
| `mark_trapped(index, trapped)` | int, bool | Same. |
| `name_cog(index, key)` | int, string | Applies to this battle only, and is painted immediately. Deliberately not written to the head catalogue — an entry there is consulted forever, so a wrong one poisons every later match, while a wrong name here costs one fight. |
| `set_level_7(allow)` | bool | Recomputes — the advice on screen was worked out under the old setting. |
| `set_toon_count(count)` | int 1–4 | Recomputes. Party size changes how much of each cog's damage is aimed at *you*. |
| `set_max_fires(count)` | int 0–99 | Real. Also **resets what we thought was spent** — the player can see the pouch and the panel cannot, so their number wins outright. |
| `set_max_unites(count)` | int 0–99 | **Inert on TTR.** |
| `set_max_sos(count)` | int 0–99 | **Inert on TTR.** |
| `set_objective(name)` | string | Preset name. |
| `set_budget(seconds)` | float | Search budget. |
| `set_height(px)` | int | **Measure the page and report it** every time the content changes height. The window used to hardcode a height and clip its own last line — and an open cog picker (four rows plus a 208 px list) runs past it, clipping exactly the part being clicked. Clamped 160–900. |
| `close()` | — | Quit. |

## Caveats

Each of these has already cost a debugging session or a wrong
recommendation.

### Do not build a "weakness" line

The mockup's `WEAKNESS: TRAP, LURE` has no basis -- cogs in this game
have no weaknesses, no type chart, no resistances. Every gag works on
every cog. A UI that says otherwise is teaching the player something
false, and there is no field behind it because there is no such thing to
read.

### Do not build a "best combo" panel

The solver plans **one round**, with a single-step lookahead for whether
a trap gets sprung. It does not produce a multi-round sequence, so there
is nothing truthful to put behind a combo display. If a combo view is
wanted, that is a real search change rather than a rendering one -- ask
first.

### Four fields are optional, and mean "unknown", not zero

`incoming`, `survive` and `accuracy` arrive as `null`, and `reason` as
`""`, whenever the explanation could not be computed. That is by design:
an explanation that fails must never cost the advice it was explaining.
Rendering a null as `0` would say "nothing is coming at you" -- the exact
opposite of "we don't know". Hide the element instead.

### `survive` saturates at 4.0

A gauge drawn on a 0-4 scale sits pinned at full for most of a healthy
fight and looks broken. Render 4.0 as **"4+"** and treat the interesting
range as 0-3.

### Player marks must survive the poll

`lured`, `trapped` and a hand-named cog are the player's assertions, and
the model is replaced wholesale every 400 ms. Python now holds these
across the round transition, so a cog named in round two stays named in
round three. If the UI keeps its own local mirror of them it will fight
that: drive the toggles from the model, and let the call be the only
writer.

### The engine badge has two truths at once

`engine` and `preferred_engine` disagreeing is not a bug. The search
takes up to fifteen seconds on any board with two or more cogs, so on the
first round of a fight the displayed answer is always the policy's,
whatever the player prefers. Show the preference as selected and the
actual source as the state -- a spinner on the unselected side reads
correctly.

### Player marks are scoped to one fight, and keyed on plate order

`lured`, `trapped` and a hand-picked cog name are stored against the
plate's **index**, not against the cog. They are cleared when a battle
ends (and again when one starts, in case the end was missed), so nothing
carries into the next fight — that was a real bug: a cog named in one
battle was stamped onto whatever stood at the same index in the next,
and the player's name outranks the readers, so the stale pick *beat* a
correct read.

Within one fight the indices still shift when a cog dies. That is
visible and correctable in the dropdown, which is why it is preferred
over silently discarding the pick — but it means the UI should never
treat a name as permanent.

### Non-empty `problems` means the advice on screen is stale

The cog rows are rebuilt from the readers every poll; the advice is only
replaced when a search succeeds. So while `problems` is non-empty the
page shows **live cog state beside frozen advice** — a cog you have just
marked lured, sitting next to a recommendation computed when it was
awake. That combination was reported as "it's a mess", and it reads as a
mechanics bug rather than a stale frame.

Grey the advice card, or badge it, whenever `problems` is non-empty.
Python retries every 2 s in that state, so it is usually brief.

### Never bundle TTR artwork

`lure_icon` and `map_icon` are read from the player's own installation at
runtime and handed over inline for exactly this reason. Copying game art
into `overlay_ui` would put TTR's assets in the repository, and would go
stale the next time the game patches.

### The dark theme is the functional one

It sits on top of a running game, always on top, in the player's
peripheral vision. Whatever happens to the light theme, the dark one is
what gets used mid-fight: high contrast on the advice line, everything
else quiet, and no animation that pulls the eye away from the game.

---

Read the docstrings in `solver/live/overlay.py` and
`solver/live/panel.py` before changing behaviour. Most of the
constraints above are recorded there beside the code that enforces them,
each with the failure that caused it.
