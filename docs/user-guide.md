# User guide

How to get advice on screen during a cog battle in Toontown Rewritten (TTR),
and how to read what the panel tells you. For what the project is and how
the engines work, start at the [README](../README.md).

Terms used throughout: a **gag** is an item a toon throws at a cog; a gag's
**track** is its family (Toon-Up, Trap, Lure, Sound, Throw, Squirt, Drop)
and its **level** is 1 to 7; **laff** is a toon's health; the **pouch** is
the set of gags a toon is carrying.

## What this does and does not touch

TTRSolver advises. You still play every round yourself.

It reads four things, all of them things the game shows or publishes:

| Source | What it gives | How |
|---|---|---|
| TTR's Local API | laff, gag training, organic tracks, location, invasions, pink slip count | An official, opt-in HTTP service the game runs on `localhost`. The game asks your permission first. |
| The game window | cogs (level, department, health, lured or not) and gag counts | A screenshot of the game's own window, taken through the operating system like any screenshot tool. |
| The client's log file | which boss fight you are in | A text file the game writes. |
| Discord Rich Presence | which floor of a Cog building you are on | What the game publishes to Discord over a local pipe. Optional. |

It never reads the game's memory, never hooks or injects into the game
process, and never sends a key press or mouse click to the game.

It writes only local files of its own: a library of cog heads it has
learned to recognise (`solver/live/_cog_heads/`), a cache of a few icons
extracted from your own TTR installation (`solver/live/_ttr_cache/`), and
the last Discord status it relayed. A round-by-round log of advice is
written only if you ask for one with `--feedback PATH`.

The panel talks to the game only on your own machine. Its page does
request one thing from the internet when it opens, a display font from
Google Fonts, and falls back to a system font without it.

Whether using a tool like this fits the game's rules is your own call to
make; read TTR's terms before you use it.

## 1. What you need

**Python.** The repository declares no minimum version. The code uses
`dataclass(slots=True)`, which needs Python 3.10 or later.

**Nothing else for the core.** The solver, the Local API client and the test
suite run on the standard library alone:

```
python -m unittest discover tests
```

**Optional extras.** Install only what the front end you want needs.

| Install | What it unlocks |
|---|---|
| `pip install -r requirements-vision.txt` (numpy, pillow, mss) | Screen reading: the TTR overlay, the terminal advisor and the screenshot diagnostics. numpy is also what the PPO and Playout engines run on. |
| `pip install pywebview` | The overlay window (TTR overlay and Realms panel). |
| `pip install -r requirements-realms.txt` (panda3d) | The Toontown Realms panel. |
| `pip install -r requirements-training.txt` (torch) | Training the networks. Not needed to run anything. |

`python run.py --list` marks each entry whose dependencies are missing and
prints the command that installs them.

You do **not** need Node.js. The overlay's built page is committed in
`overlay_ui/dist/`.

The screen reader compares cog plates against the department emblems in
your own TTR installation. It looks in the default install folders; if
yours is somewhere else, set the `TTR_DIR` environment variable to the
install directory.

## 2. Set up Toontown Rewritten

Two settings in TTR's `settings.json` must be on:

| Key | Why |
|---|---|
| `"want-local-api"` | Turns on the Local API. The port stays closed until this is on, which looks exactly like the game not running. |
| `"show-cog-levels"` | Draws the plate above each cog with its level, department emblem and health. This plate is the only way the panel can see the cogs. |

The Local API can also be enabled from the game's options. If you edit the
file by hand, do it with the game closed: the game has been seen to
rewrite the file from memory and discard an edit made while it was
running.

**The consent prompt.** The first time the panel talks to the Local API, the
game shows a prompt naming the application, `TTRSolver (Toontown battle
advisor)`. Accept it in game. The panel connects once when it opens and
keeps that connection, so you should see the prompt once per session. Until
you accept, the footer of the panel reads "Local API Disconnected" and no
advice can be given.

**Keep the game window visible.** The panel finds the window titled
"Toontown Rewritten" and reads only that. A minimised window cannot be
read, and neither can a part of it covered by another window.

## 3. Start it

```
python run.py
```

This prints a menu and asks for a number. `python run.py 1` starts an entry
directly, and anything after the number is passed through to it
(`python run.py 3 --once`).

| # | Entry | What it is for |
|---|---|---|
| 1 | TTR overlay | The main panel: an always-on-top window beside the game. Most of this guide describes it. |
| 2 | TTR overlay (Tk) | The same reader in a plain Tk window, for machines without a webview. It shows one recommendation and the cog list, with two buttons, and none of the settings below. |
| 3 | TTR advice in the terminal | One line of advice per round, no window. |
| 4 | Realms panel | The panel for Toontown Realms. See [section 5](#5-the-realms-panel). |
| 5 | Narrated solo fight | No game needed. The exact search plays a simulated battle and explains each move. |
| 6 | Random-policy demo | No game needed. A baseline that picks moves at random. |
| 7 | Browser visualizer | No game needed. Build a position by hand and explore the search tree. See [visualizer/README.md](../visualizer/README.md). |
| 8 | Read one screenshot | Diagnostic: identify the cogs in one frame. `--live` grabs the game window; `--label` asks you to name cogs it does not know. |
| 9 | Watch the screen | Diagnostic: follow a battle and print what the reader sees. |
| 10 | Probe the TTR Local API | Diagnostic: print what the API reports. Use this first if the panel says the API is disconnected. |

The TTR overlay takes a few options, all of which can also be changed in
the panel afterwards except the last two:

```
python run.py 1 --objective survive --budget 10 --no-level-7
```

| Option | Meaning |
|---|---|
| `--objective NAME` | Starting preset (`balanced`, `conserve`, `glass cannon`, `speedrun`, `survive`). |
| `--budget SECONDS` | Starting think time. Default 15. |
| `--no-level-7` | Start with level 7 gags held back. |
| `--feedback PATH` | Append each round's advice, and the gag you actually threw, to a file. Off by default. |
| `--ignore-checksum` | Advise even when the gag counts fail their check. Unsafe: the pouch is known to be wrong. For debugging only. |

## 4. Reading the TTR panel

The window opens in the top-right corner of the game window, stays on top,
and can be dragged by its header. From top to bottom:

### Header

- **Status.** "WAITING FOR BATTLE" or "IN BATTLE". "IN BATTLE (CONFIRMED)"
  means you asserted the fight yourself with the button described below.
- **Engine toggle.** Three buttons, **PPO**, **SEARCH** and **PLAYOUT**,
  appear once there is an answer. The highlighted one is the engine whose
  move is shown in the large card. Click another to show its move instead.
  A trailing "…" means that engine has not answered yet.
- **Evidence line.** What the screen reader can see right now:
  - `see: 2 cog plates, gag menu` is a readable battle.
  - `nothing on screen that looks like a battle` is normal outside a fight.
  - `game window not found` means no visible window titled "Toontown
    Rewritten" (the game is closed or minimised).
- **est. turn N.** An estimate of the round number, counted from the gag
  menu opening. It misses a round you let the timer play for you.

A battle is detected when cog plates **and** the gag menu are both on
screen. The plates alone are not enough, because some scenery is the same
colour.

### The three engines

Each round, three engines look at the same position and each gives a move.

| Row | What it is | How fast |
|---|---|---|
| **PPO** | A trained policy network with a short local search on top. | Milliseconds. |
| **Search** | Expectimax: an exact search a few rounds deep. | Up to the think time. |
| **Playout** | Plays about ten candidate moves to the end of the fight many times and keeps the one that does best. | A first answer after two playouts per move; it keeps refining for the rest of the think time. |

The **Playout** row leads by default: its move fills the large card once it
is ready, and PPO's instant answer is shown until then. This is the
maintainer's preference as a player, and in simulated two-toon Vice
President (VP) fights the Playout row won 33 of 60 sides against 6 of 60
for the Search row, because only the playouts account for the waves of
cogs still to come. If you click an engine yourself, your choice sticks
for the rest of the session.

The large card shows the leading move: the gag's picture, its track and
level, the engine that produced it, and under it a short reason and the
chance to hit ("95% acc"). The other two engines appear as rows beneath:

- **agrees** means that engine picked the same move as the large card.
- **Use** switches the large card to that engine's move.
- **Thinking...** means that engine is still working.
- **refining · N playouts** means the Playout row may still change its
  mind; the count is playouts per candidate so far.
- **waiting for a readable board** means nothing is being computed because
  the position could not be read (see the problem lines).

Two more things can appear around the card:

- A green banner, **USE UNITE FIRST**, names a Resistance Unite to use
  before throwing the gag. A unite costs no turn, so it is shown beside the
  move rather than instead of it.
- A strip showing **Incoming** (expected damage to you this round) and
  **Survive** (how many rounds your laff covers at that rate, shown as "4+"
  when it is four or more).

### Cog rows

One row per cog plate, up to four. Each shows the cog's picture, level,
name, a lure button and health. The row the advice targets is highlighted.

- **Level.** If the level could not be read, a "?" picker appears. Choose
  the level you see on the plate.
- **Name.** Click the name to open a searchable list and pick the right
  cog. Do this when the row shows only a department with a question mark,
  or when the reader named the wrong cog. A cog you name that the panel has
  not seen before is added to its head library, so it should be recognised
  next time.
- **LURED / AWAKE.** Whether the cog is lured. The panel reads the lure
  marker above the plate; click the button to correct it. This matters a
  great deal: against a lured cog Throw and Squirt cannot miss and deal
  bonus damage, Drop always misses, and the cog does not attack.
- **Health.** A bar and, when the level is known, hit points as
  `current/maximum`.

Trap state is not read on TTR and there is no control for it.

### Problem lines

When the panel cannot build a trustworthy position it shows the reasons
with a warning mark and gives **no new advice**. The large card is greyed
and tagged **STALE**, because any move still on it was worked out for an
earlier position. The panel retries every two seconds on its own.

See [section 6](#6-when-it-says-nothing-or-looks-wrong) for each message.

### Solver configuration

- **Preset.** How to weigh a fight. It shapes the Search and Playout rows.
  The PPO row ignores it.

  | Preset | What it does |
  |---|---|
  | Balanced | The default. Mild gag cost, some regard for scarce gags, damage counted at face value. |
  | Conserve | Hoards the big gags. Level 7s come out only when nothing else works. |
  | Glass cannon | Only winning and losing matter; laff and gags are cheap. Closest to pure win probability. |
  | Speedrun | Ends the fight fast and spends gags freely to save turns. |
  | Survive | Weighs laff heavily and accepts long, gag-hungry fights to avoid being hit. |

- **Toon Party (1 to 4).** How many toons are in the fight, counting you.
  Nothing on the TTR screen counts toons reliably, so you set it. It
  changes how much of the cogs' damage is expected to land on you. On TTR
  the engines know only this number: they do not see what your teammates
  carry or will throw.

  In a boss fight, set it to the number of toons in the **whole** fight.
  The VP and CEO split toons across two sides, and the panel works out
  your side's share.

- **7s ON / 7s OFF.** Whether level 7 gags may be advised. Turn it off to
  save them.

- **Think Time (3 to 45 seconds).** How long the Search and Playout rows
  may take per position.

### Battle context and inventory

- **Boss Fight.** None, VP, CFO, CJ or CEO. On TTR only the VP is detected
  automatically (from the client's log on entering the room); the label
  under the name reads "Detected" when it was. Pick the others by hand.
  Naming the fight lets the Playout row plan for the cogs still to come.

  The fight sizes are the maintainer's knowledge as a player, not sourced
  from the wiki: a VP is 20 cogs a round in total, so two rounds of 20
  alone and two rounds of 10 per side with company; the CEO's first round
  is 20 per side. The sizes for the CFO, the CJ and the CEO's second round
  are not known to the project, and the panel then shows "Fight size
  unknown" rather than inventing a total.

- **Cogs Defeated.** Shown during a boss fight, with the number left when
  the size is known. It is counted from plates disappearing; correct it
  with the buttons if it drifts.

- **Pink Slips, Resistance Unites, SOS Cards.** Each box is a budget for
  the session: how many the panel may plan to spend while it is open. All
  three start at 0, which means "never advise one".

  | Box | On TTR |
  |---|---|
  | Pink Slips | Works. The count ticks down by what actually leaves your toon, as reported by the Local API, and the panel never plans with more slips than you hold. |
  | Resistance Unites | Works, with two limits. The panel cannot see which unites you hold, so it treats the number as unites of any kind and may suggest one you do not have. It also cannot see one being used, so it ticks the box down whenever a round passes with a unite advised. Correct the number if you did not use it. |
  | SOS Cards | Does nothing on TTR (the box is tagged "Inert on TTR"). The count is not passed to the engines. |

  Nothing resets these between fights. When a box reaches 0 and you want
  the panel to keep spending, raise it.

### Manual overrides

- **Fight is over** (shown during a battle). Clears the fight and stops
  advising. Use it when the panel still thinks you are fighting. Detection
  resumes once the cog plates have left the screen.
- **Force Fight State** (shown outside a battle). Tells the panel you are
  in a fight when it has not noticed. It still needs readable cog plates
  to give advice.
- **Reconsider.** Turns down the move on screen and asks for another. Two
  widths are offered: **Not this Gag** rejects that one gag, and **Not
  this Track** rejects the whole track. A rejection lasts until the
  position changes. It steers the PPO and Playout rows; the Search row
  does not take rejections.

### Footer

- **Location.** District, neighbourhood and zone from the Local API. If it
  reads "Local API Disconnected", the panel has no laff or gag training
  and cannot advise.
- **Invasion.** The current invasion, if any.
- **Show building floors.** Appears only when Discord is running and holds
  the connection the game publishes its status on. The game tells Discord,
  and nothing else, which floor of a Cog building you are on ("Floor 2 of
  4"). To read it, the panel has to sit in front of Discord, and Discord
  has to be started after the panel for that.

  Clicking the button asks "Restart Discord?". **Yes** force-closes
  Discord, takes over the connection, and starts Discord again, so
  whatever you were doing in Discord is interrupted. Afterwards your
  Discord status keeps working, because the panel passes everything
  through to Discord unchanged. You do not need to restart the game: in
  the one recorded run it reconnected to the panel about three seconds
  after Discord closed.

  If Discord is not running, the panel takes the connection by itself and
  the button never appears. The floor is shown in the location line while
  you are inside a Cog building. It is for you to read: the engines are
  not told about it and never plan for floors you have not reached.

## 5. The Realms panel

Toontown Realms is a different Toontown server. `python run.py 4` opens the
same panel page driven by a different reader: instead of reading pixels it
connects to the local server stream a running Realms client exposes.
[realms.md](realms.md) covers what that stream is and how it is read.

You need `requirements-realms.txt` and pywebview, plus numpy for the PPO
and Playout rows. Pass `--dir PATH` if Realms is not in its default
install directory.

What differs from the TTR panel:

- **Cogs are stated, not read.** Name, level, health, lured and trapped
  come from the stream, so the name and level pickers never appear and the
  LURED button does nothing.
- **Teammates are read.** The party size is filled in for you, and the
  Playout and PPO rows see your teammates' toons rather than only a count.
- **Pink slips, unites and SOS cards are read.** The three boxes become
  spending caps on what you really hold, still starting at 0, and tick
  down only by what actually leaves your toon. The SOS Cards box works
  here despite its "Inert on TTR" tag.
- **Boss fights are detected** from the battle itself.
- **Force Fight State** re-reads the stream and recomputes; it cannot
  assert a battle the server does not report.
- **A feedback strip** can appear under the buttons: a receipt of the move
  you were seen to make, and an **I'd use…** button for saying what you
  would have thrown. These record only if the panel was started with
  `--feedback PATH`.
- **Think time defaults to 4 seconds** rather than 15.

The advice is worked out with TTR's rules. Realms balances some things
differently, so damage figures will not always match what Realms rolls.

## 6. When it says nothing or looks wrong

The panel refuses to advise from a position it is not sure of. A refusal
always comes with a reason. [live-reading.md](live-reading.md) explains
how each reader works and why it declines when it does.

| What you see | What it means | What to do |
|---|---|---|
| Footer says "Local API Disconnected"; problem line "no Local API snapshot…" | The game is not running, the Local API is off, or the consent prompt has not been accepted. | Check `"want-local-api"`, accept the prompt in game, and try entry 10 (`python run.py 10`). The panel retries about every 15 seconds while disconnected. |
| Evidence "game window not found" | No visible window titled "Toontown Rewritten". | Restore the game window. Minimised windows cannot be read. |
| "no cog plates on screen" | No plates found. | Turn on `"show-cog-levels"`. Make sure the cogs are in view and not covered by another window. |
| "no gag menu on screen…" | Gag counts come only from the gag menu, and it is not visible. | Wait for the menu at the start of the round. It slides away during attack animations; that is normal. |
| "cog N: level unreadable" | The level digit on a plate could not be read with confidence. More likely at low resolutions. | Pick the level from the "?" picker on that row. |
| "cog N: a sellbot level 11, but which one is not in the head library yet…" | Department and level were read, but several cogs fit and this one's head has not been seen before. | Pick the cog from the name list on that row. It is remembered. |
| "cog N: unidentified" | Neither the department nor the cog could be settled. | Pick the cog from the name list. |
| Every cog reads as unidentified with no level | The reader has probably latched onto scenery, not plates. | Press **Fight is over** if you are not in a battle. |
| "gag counts do not add up: the cells total 66 but the menu says 67/80…" | The gag menu prints its own total, and the counts read from the cells do not sum to it. One digit was misread. | Move the mouse off the gag menu and wait for the next read. |
| "gag counts uncertain (…) and the menu's total could not be read…" | A count was doubtful and the "Total gags" label was hidden, which happens while you hover a gag (its card covers the label). | Move the mouse off the gags. |
| "gag count misread: … more than can be carried" | A count came out higher than the game allows. | Same: clear the menu and wait. |
| The move on the card is greyed and tagged STALE | Problem lines are showing; the card is from an earlier position. | Fix the problem line. Do not act on stale advice. |
| A row says "no move" or the card says "no move to recommend" | The engine found nothing legal to throw. | Check that the gag counts on the menu are what the panel should be reading. |
| The panel says IN BATTLE while you walk around | Scenery matched the plate colour. | Press **Fight is over**. |
| The advice seems to ignore that a cog is lured | The lure marker was missed. | Click the row's AWAKE button so it reads LURED. |

**A fresh checkout knows no cog heads.** Department and level together
identify a cog outright for only 8 of the 48 combinations. For the rest
the panel compares the head drawn on the plate against heads it has seen
before, and that library is built on your machine as you play. Expect to
name cogs from the list often at first and rarely later. The panel can
also work out a cog it has never seen when every other candidate has been
ruled out.

**Level 7 gags are not in the pouch total.** The game's "Total gags" label
counts levels 1 to 6 only, so a level 7 count cannot be cross-checked the
same way.

**Resolution.** Reading the department emblem has been checked from
854x480 up to 4K. At 480p the level reader declines rather than guesses,
and you will be asked for the level.

## 7. Platform notes

**Windows is the tested platform.** Everything in this guide was developed
and exercised there.

Elsewhere:

- Finding the game window is Windows-only. On other systems the reader
  falls back to capturing the whole screen, which is known to mistake
  desktop wallpaper for cog plates, and the panel reports "game window not
  found". This path is untested in play.
- The client-log reader knows only the Windows default log folder. Set
  `TTR_LOG_DIR` to the game's log directory on other systems. Without it
  the VP is not detected and you pick the boss by hand.
- The Discord relay has a Unix-socket transport written from Discord's own
  reference library. It has not been run on a Mac or on Linux.
- The installation finder lists default folders for macOS and Linux that
  have not been checked against a real install. Set `TTR_DIR` if it fails.
- The overlay window uses pywebview, which renders with Edge WebView2 on
  Windows. Other pywebview back ends are untested here.

The solver itself, the Local API client, the demos (entries 5 and 6) and
the visualizer (entry 7) are plain Python and should run anywhere Python
does.

## 8. What is unfinished

- **Teammates on TTR are a number.** Nothing reads a teammate's laff or
  gags from the TTR screen. An experiment that stood guessed teammates in
  for the Playout row did no better than the count alone in simulation and
  is switched off; its "Strangers / My party" toggle is hidden.
- **Trap state is not read on TTR.**
- **SOS cards are not usable on TTR**, and unites are a bare count.
- **Only the VP is detected on TTR.** The CFO, CJ and CEO must be picked by
  hand, and their fight sizes are partly unknown.
- **Building floors are shown, not planned for.** The engines do not peek
  at floors you have not reached.
- **Party advice rests on less evidence than solo advice.** The exact
  solver cannot reach a party position, so there is nothing to check the
  evaluator's party values against. See
  [party-strategy.md](party-strategy.md).

The project tags every game value by how it is known: `[CONFIRMED]` from
the TTR wiki, `[OWNER]` for the maintainer's judgement as a player,
`[TODO]` for unknown, and a few others.
[data-confidence.md](data-confidence.md) explains each tag and lists which
values are confirmed.
