# How the tool reads a live battle

TTRSolver can only advise on a fight it can describe: the player's laff
(health), the gags they carry, and the cogs in front of them. This page
is the reference for where each of those facts comes from in Toontown
Rewritten (TTR), how each reader was checked, and where each one stops.

Three words are used with fixed meanings throughout:

- **Observed** means seen on a running game client, with the date where
  one was recorded.
- **Measured** means counted over a set of frames, fights or
  connections, and the count is given.
- **Untested** means the code exists and has not met the real thing.

Toontown Realms, a different Toontown server, is read by a separate
route with its own panel: a connection to the internal message bus of
the server that Realms runs on the player's own machine. That is a
different kind of access from anything on this page, it is not an
official API, and it is covered in [realms.md](realms.md). The
debugging history behind several of the readers is in
[live-notes.md](live-notes.md).

## The sources at a glance

| Source | What it gives | Module | Needs |
|---|---|---|---|
| TTR Local API | Laff, gag training, organic tracks, location, invasion, pink slips | `solver/live/ttr_local.py` | The Local API switched on in the game |
| The game's window | The rectangle to capture | `solver/live/window.py` | Windows |
| Cog plates | Each cog's level, department, health, lure state and identity | `solver/live/vision.py`, `watch.py`, `catalogue.py` | Cog levels shown in the game; numpy, Pillow, mss |
| Gag menu | How many of each gag is carried | `solver/live/gagpanel.py`, `digits.py`, `panel_memory.py` | The gag menu on screen |
| Client log | Which boss fight the toon has walked into | `solver/live/ttr_log.py` | The game's log folder |
| Discord relay | The floor and height of a cog building | `solver/live/discord_relay.py` | The game's Discord integration on |

The solver core, the Local API client and the test suite run on the
Python standard library alone. The screen readers need the packages in
`requirements-vision.txt`.

## The TTR Local API

**What it is.** TTR's own client can serve read-only JSON about the
player's toon over HTTP on the local machine. It is an official
feature, off by default, and switched on in the game's options (the
setting is stored as `"want-local-api"` in TTR's `settings.json`). The
default port is 1547. The client scans 1547 to 1552, because the game
moves up a port for each additional toon running at once.

**How it is asked.** Each request is a plain `GET` to
`http://localhost:<port>/<endpoint>.json` carrying a `User-Agent` and
an `Authorization` token. The token is random and generated once per
session. The first time the game sees a token it shows the player a
prompt naming the `User-Agent` (this tool sends
`TTRSolver (Toontown battle advisor)`), and nothing is handed over
until the player accepts it in the game.

**The `Host` header rule.** The `Host` header must be exactly
`localhost:<port>`. A request addressed to `127.0.0.1` or `[::1]` has
its connection dropped with no response at all. From the outside that
is indistinguishable from the game not running, and from the API not
being enabled, which also leaves the port closed. The client's
`NotRunning` error names all of these for that reason.

**Endpoints.**

| Endpoint | Status | Contents |
|---|---|---|
| `/all.json` | Read | Toon name and id, laff (current and maximum), location (zone, neighbourhood, district), invasion, each gag track's highest unlocked level and top organic gag, and progress on the toon's own cog disguises |
| `/pinkslips.json` | Read | A bare integer: pink slips held. Observed 2026-10-10 |
| `/sos.json` | Exists, not parsed | SOS cards, as category, then name, then count |
| `/unites.json` | Exists, not parsed | Unites, in the same shape |
| `/info.json` | Not used | A lighter form of `/all.json` that omits the disguise block |
| `/gags.json` | Not used separately | Training per track. It has no field for how many gags are carried |

`/sos.json` and `/unites.json` are not parsed because no toon holding
battle cards has been read yet, so the names the game uses for them
have not been seen. Guessing the names would be inventing data.

**What the solver takes from it.**

- *Laff*, exactly, current and maximum.
- *Gag training.* The highest gag unlocked in each track sets the
  track's accuracy bonus, so this is an input to every hit chance, not
  a display detail.
- *Organic tracks.* The API names the top organic gag in a track;
  levels up to it are treated as organic.
- *Location.* The zone string `"Cog Building"` (observed 2026-10-05)
  marks a fight as one floor of several. It is the only such string
  listed, because it is the only one that has been observed; a
  facility's or a Field Office's string is unknown.
- *Pink slips held.* The panel's slip budget ticks down by what really
  leaves the toon, and never offers more slips than are held.
- *A fight has paid out.* The toon's disguise merit totals rise the
  moment a battle resolves (observed going from 0 to 3 as a Sellbot
  street battle ended). The watcher uses a rise as proof that a fight
  is over. It is a one-way signal: it fires only for a department
  whose disguise the toon owns, so its absence proves nothing.

**What it does not expose.** The battle. Every documented endpoint
answers, and every battle-shaped guess (`/battle.json`, `/combat.json`,
`/cogs.json`) returns 404. The API also has no gag counts, no building
floor, and no way to tell a boss room from the headquarters around it.
That is why the rest of this page exists.

**The consent dialog, and why discovery is never polled.**
`ttr_local.discover()` builds a fresh client for every open port, and
each fresh client has a new token, so the game raises its consent
prompt again for each one. Calling it once per advice cycle put the
prompt on screen several times a second. `advise._snapshot` therefore
keeps one session for the life of the program:

- A snapshot is reused for `SNAPSHOT_TTL` (5 seconds). Laff moves
  during a fight; training and organic do not.
- Discovery runs only while disconnected, and at most once every
  `REDISCOVER_AFTER` (15 seconds).
- While the prompt is unanswered the same client is kept, so the next
  attempt does not stack a second prompt on the first.
- A lock allows one caller at a time, because two discoveries at once
  would be two clients and two prompts.

**Other things observed on a running client.**

- The first request on a new token took about 3 seconds, against under
  2 milliseconds afterwards, so the request timeout is long (30
  seconds) and the port-scan timeout is short (0.3 seconds).
- The zone string is empty for about a second while the toon moves
  between zones. Readers treat that as "in transit", not "nowhere".
- Three cog names arrive with a control character inside them, which
  is stripped before matching.

**Limits.** With several toons running, the panel uses the first port
that answers. The API describes one toon: the client's own.

## The game window

The screen readers capture the game's window, not the screen.
`solver/live/window.py` asks the window manager for the client area of
the window titled exactly `Toontown Rewritten`, and
`watch.Capture` grabs only that rectangle.

**Why.** The plate reader looks for a particular teal (see the next
section). Inside the game that colour is distinctive. Across a desktop
it is not. Measured with the game windowed on a 2560x1440 screen with
a blue-green wallpaper: a full-screen capture found one "plate", a
319x190 patch of wallpaper, and every read came back
`level unreadable`. Cropped to the window, the same frame gave the two
real plates (65x45 and 68x47) and read a level 6 Bossbot and a level 8
Lawbot.

**Details.**

- The rectangle is looked up on every capture and never cached,
  because the window can be moved or resized between frames.
- The client area is used, not the outer window, so the title bar and
  border are not in the frame.
- A minimised or hidden window returns nothing.

**Exactly what it calls.** Five window-manager functions, through
Python's `ctypes`: `FindWindowW`, `IsWindowVisible`, `IsIconic`,
`GetClientRect` and `ClientToScreen`. This module is the only use of
`ctypes` in the repository. It reads no memory and touches no process.
It asks where a window is, as a screenshot tool does.

**Limits.** This is Windows-only. On other systems, and whenever the
window is not found, the capture falls back to the whole screen, with
the wallpaper problem above.

## Cog plates

With cog levels shown (`"show-cog-levels"` in the game's settings), TTR
draws a metal sign above each cog in a battle: a portrait of the cog's
head on a teal backdrop, the text "Level N", the department emblem and
a health bar. This sign is the only route to the cogs.

### Finding a plate

`vision.find_plates` anchors on the flat teal square behind the head.
It does not use fixed coordinates, because the sign floats in 3D and
moves with the camera. Every threshold is a fraction of the frame, and
every sub-region of a plate is a multiple of its own teal square, so
nothing depends on resolution. Measured: both plates of a two-cog
battle are found from 854x480 to 2160p.

A candidate must hold enough teal, have the plate's aspect ratio, be no
wider than 12% of the frame's width and not touch the frame's edge. The
watcher then drops any candidate that sits inside the gag menu, which
holds teal of its own. Each of those rules came from a real false
positive, recorded beside the code that applies it.

Where the scenery itself is the plate's colour, the teal search finds
nothing. In Bossbot HQ the mortar between the cobblestones matched and
19.7% of a frame came back as one connected blob. For that case a
fallback looks for the saturated green of a health bar and works back
to where the plate must be, then checks for teal there. It runs only
when the first search finds nothing. Known limit: it was calibrated on
full health bars, and a badly hurt cog's bar is too short to pass.

### Teal alone does not mean a battle

`find_plates` finds plate-shaped teal and nothing more. Measured in
Donald's Dreamland, outside any battle: 2.1% of a live frame matched
the teal mask and two patches passed the size and shape filters, so an
early version announced a battle and then a stream of cog defeats as
the player walked about.

`BattleWatcher.in_battle` is the decision, and it also requires the gag
menu:

- **Entry is strict.** Plates and the gag menu must both be on screen.
  This costs nothing, because gag counts come only from the menu and no
  advice is possible without it.
- **Continuation is lenient.** Once in a battle, plates alone are
  enough. The menu slides away during attack animations, and requiring
  it on every frame turned one fight into several.
- **Absence is not the end.** The game cuts the camera for each attack
  and takes the menu and every plate with it. A battle is over only
  when the plates have been gone for `BATTLE_GRACE` (20 seconds), or
  when the Local API shows the fight paying out.
- **A reading must repeat.** A change is reported once the same
  reading arrives on two polls running.

The sign of scenery being mistaken for a plate is a read in which every
cog is `level unreadable / unidentified`: scenery shaped like a plate
has no level printed on it. The player can also override detection in
either direction with the panel's "I'm in a fight" control.

### Level, department and health

| Reading | How | Refused when |
|---|---|---|
| Level | The digits of "Level N" are cut out and read by a small classifier (see [Reading digits](#reading-digits)); without its weights, by matching against the game's own font | The match is weak, or the winner does not clearly beat the runner-up, or the number is outside 1 to 12 |
| Department | The emblem is matched against the four department emblems by shape and by colour tint | The winning margin over the runner-up is below `MIN_DEPARTMENT_MARGIN` |
| Health | The share of the health bar's width that is lit | Never refused; see below |

A refused reading is reported as unknown. It is never replaced with the
most likely value.

- **Level.** The margin matters more than the score. Observed: a plate
  reading "Level 8" was once read as 6 with a respectable score and a
  runner-up close behind. A high score says the region holds a legible
  digit; only the margin says which digit. At 854x480 the level is not
  readable and the reader returns nothing. On real plates the
  classifier has been checked on levels 5 and 6 only (all 57 battle
  plates of one recorded building run, plus the plates the old matcher
  had refused); the other levels rest on a held-out set of synthetic
  plates. When the level is refused, the player can type it into the
  panel, and that number stands for the rest of the fight.
- **Department.** The emblems are tinted: Bossbot warm, Sellbot red,
  Cashbot green, Lawbot blue. Measured: matching on shape alone gave
  margins of 0.07 to 0.22 and picked the wrong department at 720p;
  with tint the margins are 0.21 to 0.61 and correct from 854x480 to
  4K. A department read below the margin is not used to narrow the
  list of possible cogs, because narrowing to the wrong five is worse
  than not narrowing: the cog actually on screen would never be
  offered.
- **Health.** A cog's hit points are its maximum for its level times
  the bar's fraction, rounded. A full bar does not read 1.0: observed
  full bars read between 0.90 and 0.99, so anything at or above 0.85
  is taken as full. The two errors are not equal. Reading a full cog
  as damaged leaves it alive on a sliver; reading a lightly damaged
  cog as full costs a few points of overkill.

### Lure and trap

- **Lured.** The game floats a red tile above a lured cog's plate. The
  reader tests for that red and reports asleep or awake. It does not
  read the number of rounds on the tile. A cog read as lured is given
  one round of lure, the cautious end, and the player can set or clear
  the mark by hand.
- **Trapped.** Not read. The game's marker is the same for every Trap
  gag, and the solver needs to know which trap it is. The panel has a
  mark for a trapped cog, but in the current code it changes only what
  the panel shows; it does not reach the board the engines see. This is
  unfinished.

### Which cog it is

Department and level do not name a cog. Of the 48 department-and-level
pairs, 8 identify a single cog and the rest allow up to five. The
remaining evidence is the head in the portrait.

No per-cog icon ships with the game to match against. The game's
`cogIcons` are the four department emblems, and the per-cog images in
its archives are 3D texture skins. The reference therefore has to be
the plate's own render, which works because its camera, light and
backdrop are fixed.

**The collected library** (`solver/live/catalogue.py`). For each cog
the library stores a small signature of the head with the teal masked
out, beside the image it came from, so a bad entry can be seen and
deleted. The library is not shipped with the repository. Each install
builds its own while the player plays, in three ways:

- A cog whose plate allows only one candidate is recorded
  automatically.
- A cog the player names in the panel is recorded, replacing any
  earlier entry for that cog.
- `python -m solver.live.read_battle --label` walks a screenshot and
  asks about each cog it cannot name.

A match is accepted when it is close and clearly beats the runner-up.
When there is no runner-up, because only one of the candidates is in
the library, it is held to a much tighter distance instead. Measured,
on three readings of two cogs: correct matches scored 0.000, 0.020 and
0.028, and wrong ones 0.132 to 0.157. That is a wide gap from a thin
sample.

**Deduction by elimination.** `HeadCatalogue.eliminate` names a cog the
library has never seen: when every known candidate is ruled out and
exactly one candidate is left, that one is the cog. It refuses unless
exactly one candidate is unknown, at least one is known, and none of
the known ones could be a match. So the library never has to be
finished. What it deduces is not written to the library: a stored
signature is consulted forever, so a wrong one damages every later
match, while a wrong deduction costs one battle.

**The player's word comes first.** A name given in the panel is used
before any library match, so a confident wrong match can be corrected.

**Ready-made cog art is not a substitute.** This was measured.
Matching plates against a set of cog images ranked the right cog first
for 3 of 4 known plates, with margins of 0.001 to 0.004, against 0.028
correct versus 0.132 wrong for the collected library. Every candidate
scored about the same, so the hits were chance; one plate ranked its
true cog last.

## Gag counts

The Local API says which gags are unlocked and never how many are
carried. The in-battle gag menu shows the counts, so they are read from
the screen (`solver/live/gagpanel.py`).

**Finding the menu.** Each of the seven track rows has its own
background colour. A long unbroken run of that colour, seven times, at
even spacing, is a gag menu and nothing else in the game. A row whose
cells carry organic badges is broken into pieces, and is accepted on a
stricter test.

**Reading a cell.** Whether a gag is unlocked comes from the Local API,
not from pixels. The count in each cell is cut out by brightness
against the cell's own background and read digit by digit.

### Reading digits

Counts and plate levels go through small classifiers
(`solver/live/digits.py`), which need only numpy at play time. They are
trained on synthetic digits: the game's own font, rendered at on-screen
sizes, distorted the way real frames are (blur, colour bleed,
compression, clutter), and cut out by the same cropping the live reader
uses. `tools/train_digits.py` rebuilds them, reading the font from the
player's own install. The trained weights are in the repository. No
game frame is used to train them, and the tests draw their own digits.
Without the weights, the older template matchers are used.

- Counts are cropped by brightness, not colour. Video compression
  bleeds the cell's blue into thin white strokes, which erased most of
  a digit under the old colour test.
- Only the right-aligned run of glyphs is kept. The highlight on a gag
  icon otherwise read as extra 1s.
- All counts are drawn at one size. A glyph outside that size band is
  marked doubtful whatever the classifier says: it is the mouse cursor
  sitting on a digit.

Measured on a hand-labelled benchmark of 168 cells: the old reader got
151 right, the new cropping with the old matcher 166, and the
classifier 167. The one miss was the mouse cursor on a digit, which the
size rule now flags.

### The "Total gags" checksum

The menu prints its own total, "Total gags N / M". Level 7 gags do not
count against the pouch, so the label counts levels 1 to 6 only.

`read_pouch_label` reads that label and `GagPanel.checksum_problem`
compares it with the sum of the cells. The two readings share no
machinery on purpose: the cells are white digits on blue and the label
is near-black on yellow, so a fault in one cannot make both agree
while both are wrong. When they disagree, no board is built.

The label reader declines instead of guessing. It requires one to
three confident digits either side of a single unmatched glyph (the
slash) and rejects a total above its capacity. When the label cannot
be read, the checksum does not run. A count above a gag's carry limit
is refused in every case, and with the label unreadable any doubtful
cell in the pouch is refused too. The label is unreadable whenever a
gag is hovered, because the gag's card replaces it.

### Repairing a single cell

The first real frame the test suite saw was off by one: a Trap cell
holding 6 read as 5, giving 66 against a label of 67. The template
matcher could not recover it at any threshold, because the true digit
did not even place second.

`_repair_with_label` solves that case from the label. If exactly one
pouch cell is doubtful, every other cell is confident, and the label
was read, the doubtful cell must hold the total minus the rest. It
fires only then. Two doubtful cells make the split ambiguous; a
negative remainder, or one above the gag's carry limit, means something
else is wrong; a level 7 cell is outside the pouch. In each of those
cases it declines and the checksum refuses the board as before.

Doubt is measured, not assumed. Over all 41 digits of a real menu the
template matcher's median margin over the runner-up was 0.128, its
worst correct read 0.063, and its one wrong read 0.011. The threshold
sits between.

### The remembered menu

Gags are spent when the round resolves, and the menu is gone by then.
So while the menu stays open the counts cannot change, and every poll
is another look at the same numbers (`solver/live/panel_memory.py`).
Each poll's confident reads are kept as votes per cell. A doubtful
read takes the cell's settled value if one leads outright, and a
confident read is overruled only by a value seen at least twice and
more often than itself. The memory is cleared when the menu closes.

Measured by replaying one recorded building run in order: 42 of 45 menu
frames were accepted (38 without the memory) and none of the accepted
frames was found wrong. The three refused were the first frame of a
menu with the cursor on a digit, which the panel's retry covers.

## The client log

The Local API names a street or `"Cog Building"` but not a boss room.
The game's own log does. Each time the toon changes place, the client
writes one line containing `enter(requestStatus={...})` with a `where`
and a `hoodId`. `solver/live/ttr_log.py` reads the newest log file in
the game's log folder, a little at a time, and keeps the last place it
names. It is a file the game writes. Nothing else about the game is
read to get it.

**What has been observed** (2026-10-10): entering a Vice President
(VP) fight logged `'where': 'CogHQBossBattle'` with `'hoodId': 11000`,
Sellbot HQ, and a cog building logged `'SuitInterior'`.

**What that maps to.** Only the VP. `boss.TTR_BOSS_PLACES` holds that
one entry. The Chief Financial Officer, Chief Justice and Chief
Executive Officer fights are left on the panel's manual picker until
each has been seen: the same `where` with another `hoodId` is the
obvious guess, and a wrong guess would name the wrong fight without
any sign of it.

**Details and limits.**

- The game's module names in the log are obfuscated, so the line is
  found by `enter(requestStatus=` and its two keys, never by a module
  name.
- The log folder is known for a default Windows install only. Anywhere
  else, set the `TTR_LOG_DIR` environment variable.
- With no log to read, the panel falls back to the picker.

Knowing the fight matters because the engines can then count cogs
defeated against the fight's known structure
(`solver/live/boss.py`). On screen-read frames a defeat is a plate
that vanished while nearly empty, and the player can correct the count.

## The Discord relay

**What the game publishes.** While the game's Discord integration is
on, TTR sends its status to Discord's Rich Presence over a local
connection. Observed 2026-10-10: "In a Three Story Sellbot Building"
with "Floor 3 of 3". That is the only place a building's height and
current floor exist outside the game. The Local API says only
`"Cog Building"`, the log only `SuitInterior`, and Discord does not
let one program read another's status.

**How the relay reads it.** The relay sits between the game and
Discord, on Discord's own local connection (its IPC, or inter-process
communication, pipe). It is not inside the game and not inside Discord.
A Discord client such as the game connects to the first of
`discord-ipc-0` to `discord-ipc-9` that exists, and Discord claims the
first free one when it starts. `solver/live/discord_relay.py` creates
`discord-ipc-0` itself:

- **Discord not running.** The relay answers the game's handshake as
  Discord would, so the game keeps publishing.
- **Relay started before Discord.** Discord settles on `discord-ipc-1`.
  The relay passes every byte between the game and Discord unchanged
  in both directions, so the player's Discord status still shows.

Either way it records each status the game sets (Discord's
`SET_ACTIVITY` message) and nothing else. It parses only the wording
that was observed. Anything else, such as a street or a
facility, yields nothing. The story count in the first line must agree
with "of N" in the second, or the record is not trusted.

**A Discord that already holds the pipe cannot be displaced.**
Measured: with 1, 4 or 16 extra listeners on `discord-ipc-0` beside
Discord's own, Windows gave all 54 new connections to Discord. So the
relay has to be listening before Discord starts.

**The restart flow.** The panel retries the pipe every few seconds.
While Discord holds it, the panel offers a button, "Restart Discord to
show floors". Pressing it force-closes Discord (on Windows with
`taskkill /F`, because Discord treats an ordinary close as "hide to the
tray"), takes the pipe as soon as it is free, and starts Discord again
through Discord's own launcher. That is a forced stop of the player's
own program, done only when the player presses the button. It reaches
into neither Discord nor the game.

Observed 2026-10-10: the game reconnected to the relay 3 seconds after
Discord quit and published "In a One Story Lawbot Building" / "Floor 1
of 1". Discord, restarted, took `discord-ipc-1`.

**Handing the game back.** A game that connected while Discord was
away is being answered by the relay. The next time the game sends
anything, and at most once every 5 seconds, the relay looks for
Discord. If it is there, the relay replays the game's opening
handshake to it, discards Discord's reply (the game already had the
relay's), and forwards everything from then on. Observed 2026-10-10:
the player's Discord status came back.

**The `discord-pipe-number` setting does not help.** TTR's
`settings.json` has a `"discord-pipe-number"` key, which looks like a
way to point the game at another pipe. The game reads it only at
launch. Tested three ways on 2026-10-10: edited while the game ran;
edited, then the integration toggled; toggled off, edited, toggled on.
Each time the game stayed on pipe 0, and toggling rewrote the file
from memory over the edit.

**Limits.**

- The floor is shown in the panel only while the Local API says the
  toon is in a cog building. In the current code it is displayed and
  not yet used by any engine.
- On Windows the connection is a named pipe; on macOS and Linux it is
  a Unix socket, following Discord's published reference library. The
  Windows transport has been observed working. The Unix transport has
  been run against itself and has not met a real Mac or Linux machine.
  The same is true of the commands that restart Discord there.
- The relay reads what the game publishes. Hooking the game's process
  to read the connection directly was ruled out as tampering with the
  client.

## Joining the sources

`solver/live/session.py` turns the readings into a `BattleState`, the
board the engines search, and `solver/live/advise.py` runs the engines
on it. Each source is the authority for one thing and is never used to
stand in for another.

| Fact | Authority |
|---|---|
| Laff, current and maximum | Local API |
| Gag training and organic tracks | Local API |
| Count of each gag | Gag menu |
| Which cogs, their levels and health | Cog plates |
| Whether a cog is lured | Cog plate, with the player's mark as override |
| Inside a cog building | Local API zone |
| Which boss fight | Client log, else the player's pick |
| Pink slips held | Local API |

The gag menu shows training too, but it is not taken from there.
Counts are what the screen is good at; what a toon has unlocked is
something the API states outright.

**A state, or the reasons there is none.** `build_state` returns either
a board or a list of everything that stopped it from building one. It
never fills a gap with something plausible, because advice computed
for an invented fight is worse than no advice. The reasons are all
reported at once and shown in the panel:

- no Local API snapshot;
- no cog plates on screen;
- no gag menu on screen;
- the gag counts do not add up to the menu's total, or a count is
  impossible or doubtful;
- a cog's level is unreadable;
- a cog's department and level were read but its identity is not in
  the library yet, in which case the panel offers the candidates in a
  dropdown.

**What the player supplies.** Some facts have no source on a TTR
client, and the panel asks for them instead of guessing:

- how many toons are in the fight (nothing reads a teammate from the
  screen, and the Local API describes one toon);
- which boss fight this is, where the log has not been mapped;
- how many pink slips, unites and SOS cards the panel may plan to
  spend, each defaulting to zero. Unites are a count with their kind
  unknown, and no SOS card is ever placed on a TTR board, because
  nothing names the cards held.

**When the engines run.** The readers run on every poll (the panel
polls every 0.5 seconds). The engines run only when the board changes:
a battle starts, a cog joins, is damaged or defeated, or a reading
corrects itself. A read that produced no board is retried, because the
frame at a round boundary is the likeliest to be unreadable. Each
engine is handed a copy of the board, never the live one.

## What the tool does not read or touch

- **It does not read the game's memory**, attach to its process, or
  inject anything into it. Nothing in the code does any of these.
- **It sends no input to the game.** No key presses, no mouse clicks.
  It shows advice; the player plays.
- **It does not open the game's encrypted code.** The game's Python
  lives in an encrypted archive, which this project leaves alone.
  `solver/live/ttr_assets.py` does parse the game's unencrypted art
  archives (`phase_*.mf`) in the player's own install, to take the
  interface font and the four department emblems. They go into a local
  cache that is excluded from version control, and nothing extracted is
  redistributed.
- **The live readers send nothing over the network.** The Local API is
  HTTP on the local machine, and the Discord relay is a local pipe.
- **It does not change the game's settings.** The Local API, cog
  levels and the Discord integration are switched on by the player.
- **It does not see other players' toons.** On TTR a teammate is a
  number the player enters.

Two things it does do outside its own window are worth stating plainly,
since a reader judging the tool should know them. It creates Discord's
`discord-ipc-0` pipe so that the game's status passes through it, and
at the player's request it force-closes and relaunches Discord. Both
are described under [The Discord relay](#the-discord-relay).

Everything it knows comes from one of five places: an API the game
offers and the player consents to, pixels of the game's own window, a
log file the game writes, what the game publishes to Discord, and what
the player tells the panel.
