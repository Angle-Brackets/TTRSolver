# Toontown Realms as a harness, not as a source

Toontown Realms ("Realms") is a different Toontown server from Toontown
Rewritten (TTR): what Toontown Offline became. It runs a complete game
server on the player's own machine. TTRSolver has a second panel that
advises during Realms battles by reading that local server directly.

This page covers three things: the rule that keeps Realms from
contaminating the TTR solver, what the Realms reader reads and how, and
the places where Realms was found to play differently from TTR.

For how the TTR panel reads a game, see
[live-reading.md](live-reading.md). The debugging history behind the
Realms reader is in [live-notes.md](live-notes.md).

## The rule

**Nothing read from Realms may train, confirm or score anything about
TTR.**

- Nothing measured in Realms may be written into `solver/data/`, the
  tables of game rules. Those come from the TTR wiki.
- Nothing recorded in Realms may be used to fit a weight or to score a
  policy for TTR. Every row the Realms panel records is stamped
  `source=realms` when it is written, so it cannot later be mixed into
  TTR training by renaming or merging a file.
- Anything learned from Realms is at best the strength of the project's
  `[OPEN TOONTOWN SOURCE]` tag, a lead to check against the wiki, and
  never `[CONFIRMED]`.

What Realms *is* good for is testing the plumbing. Whether the reader
turns a cog's health into the right number on the board does not
depend on whose balance the server runs, and a typed value from a
server is better ground truth for that than a screenshot.

The Realms panel reads a *position* and prices it with *TTR's* rules.
Its predicted damage numbers therefore will not always match what
Realms rolls.

## Why it must not feed the tables

Realms descends from Toontown Online, the same lineage as the old
strategy guide and the Open Toontown source that this project already
treats as leads and not as data. The differences found so far are small
in size and binary in effect.

The maintainer reports that Realms caps cogs at level 12, gives a level
12 cog 200 hit points, and limits TNT to a carry of 2. Against the TTR
tables:

| | TTR | Realms |
|---|---|---|
| Level 12 cog HP | 196 | 200 |
| TNT carry limit | 3 | 2 |
| Highest cog level | 14 (in the Chief Executive Officer fight) | 12 |

The Realms column is `[OWNER]`: the maintainer's report from play, not
a measurement taken by this project.

**Four hit points is 2%, and it flips exactly two one-shot verdicts.**
Across every gag at full training, only these disagree about defeating
a level 12 cog in one hit:

    organic TNT          198   defeats a TTR 12, not a Realms 12
    organic Grand Piano  196   defeats a TTR 12, not a Realms 12

(*Organic* gags are a toon's boosted track.) Ordinary TNT does 180 and
defeats neither; Railroad does 200 and defeats both.

**The mechanism has a name.** TTR's 3.0.0 patch notes say "Decreased
Level 12 Cog health very slightly", and `solver/data/cogs.py` quotes
them. An earlier
version of that module's notes recorded the value before the patch as a
flat 10% boost to 200. Realms' 200 is consistent with Toontown as it
was before that patch. So Realms is not wrong, it is old, and the
places where it is old are the places TTR chose to rebalance.

That is why "the differences are small" is the wrong way to think
about it. A one-shot verdict is what a Trap-then-Lure plan turns on. A
policy that learned on Realms that organic TNT does not finish a level
12, and so sets up a second gag, would carry that into TTR, where one
gag is enough.

The level cap matters in one specific place: TTR's Chief Executive
Officer fight uses level 14 cogs (254 HP), which no Realms position can
contain.

## What Realms plays differently from TTR

Each difference found is kept on the Realms side of the code. None of
them changes a TTR table.

| Rule | TTR | Realms | Where the Realms value lives |
|---|---|---|---|
| Level 12 cog HP | 196 `[CONFIRMED]` | 200 `[OWNER]` | Nowhere. Health is read from the server, not computed |
| TNT carry limit | 3 `[CONFIRMED]` | 2 `[OWNER]` | Nowhere. The pouch is read from the server |
| Organic bonus | Varies by track, and raises Lure accuracy | A flat 10% to damage | Nowhere. The reader records which tracks are organic and how far up; the solver prices them by TTR's rules |
| Toon-Up unite values | 20, 35, 50, 65, 80 `[CONFIRMED]` | 10, 20, 40, 80, MAX `[OWNER]` | `realms.TOON_UP_VALUES`, handed to the board as `ToonState.toon_up_values` |
| Toon-Down unites | Do not exist | A fourth unite category `[OWNER]` | Decoded and ignored; never offered |
| "Toons Hit" and "Cogs Miss" SOS cards | 75% for 3 to 5 rounds | Certain, for the one turn after the call `[OWNER]` | `BattleState.sos_one_round`, set by the Realms reader and nowhere else |

A *unite* is a consumable that restores laff (health) or gags to nearby
toons. An *SOS card* calls a non-player toon to help for a round. A
*pink slip* removes one cog from the battle.

Two of these are worth a sentence each:

- **Toon-Up unite values.** `solver/unites.py` keeps TTR's table, from
  the wiki. Realms' values come from its in-game menu and live in the
  reader. They reach the solver on the board for that one toon, so
  neither build's table can overwrite the other's.
- **Toon-Down** is custom to Realms. It does not exist in the game this
  solver is for, which makes the whole Realms unite category table
  Realms-specific. A server that adds a category is exactly the hazard
  the rule above is about.

## What kind of access this is

This is a different kind of access from TTR's Local API, and it should
be judged separately. The Local API is a feature TTR's developers offer
to third-party tools, switched on by the player and gated by a consent
prompt. The Realms reader uses no such offer. It reads the internal
message bus of a server running on the player's own computer.

Realms' server is built on Astron, an open-source server for this
family of games. Its parts talk to each other through a *Message
Director*, which in the default install listens on TCP `127.0.0.1:7199`.
`solver/live/realms.py`:

1. Opens a TCP connection to the Message Director on the local machine.
2. Sends three control messages: one naming the connection
   (`ttrsolver-reader`), one subscribing to the whole channel range,
   and one adding a private channel for replies.
3. Listens to the object updates that pass.
4. Sends `OBJECT_GET_ALL` queries, which ask the server to describe an
   object it already holds.

It sends no object update and no command, and it does not connect to,
read the memory of, or send input to the game client. It also reads two
files from the Realms install: the `.dc` schema file
(`astron/dclass/ttoff.dc`), parsed with panda3d, the library the game
itself uses for that file; and the table of non-player toon names in
the game's data pack, to turn an SOS card's id into a name. Neither is
copied into this repository.

A subscription to the whole range is used because a narrower one would
need the battle's location, which is what the reader is trying to find.
One consequence is that the reader can see fields the game would not
show the player on screen, such as a teammate's exact pouch. See
[Teammates](#teammates).

## What it exposes

Checked against one local install on 2026-10-11:

    Message Director    TCP 127.0.0.1:7199
    client agent        TCP 0.0.0.0:7198
    event logger        UDP 127.0.0.1:7197
    astron/dclass/ttoff.dc   165 KB of plain text, 412 dclasses, 79 structs

A *dclass* is a class in the schema. Only the Message Director is
used. The fields the reader depends on, with the keywords the schema
gives them:

| Object | Fields | Keywords |
|---|---|---|
| Cog (`DistributedSuitBase`) | `setDNAString` (which cog), `setLevelDist`, `setHP`, `setMaxHP`, `setSkelecog`, `setSkeleRevives` | `required broadcast ram` |
| Battle (`DistributedBattleBase`) | `setMembers` (toon ids and cog ids), `setState`, `setMovie` | `required broadcast ram` |
| Battle | `setChosenToonAttacks` | `broadcast ram` |
| Toon (`DistributedToon`) | `setHp`, `setMaxHp`, `setTrackAccess`, `setTrackBonusLevel` | `required broadcast ownrecv db` |
| Toon | `setInventory`, `setPinkSlips`, `setResistanceMessages` (unites), `setNPCFriendsDict` (SOS cards) | `required ownrecv db` |

Fields marked `ownrecv` without `broadcast` are sent only to the toon's
own client, never on the stream. The reader sees them only by asking.

## The panel

    python -m solver.live.realms_panel
    python -m solver.live.realms_panel --objective survive --budget 8

It needs panda3d (`requirements-realms.txt`), pywebview, and Realms
running. The install is looked for in the usual Windows locations;
`--dir` names another. Other flags: `--engine both|rl|search|none`,
`--no-level-7`, `--headless` (no window; print what the reader sees
each poll) and `--trace` (log every field the cogs and the battle
receive). The recording flags are under [Recording](#recording).

**A second panel, not a mode of the first.** The TTR worker polls a
screen capture, finds plates, reads a gag menu and hedges every number
with a confidence. None of that applies when a server hands over typed
fields. Threading a second game through it would put `if realms:`
across the one module whose whole job is being careful about pixels.
`tests/test_realms_panel.py` checks the source of `overlay.py`,
`panel.py`, `session.py` and the shared `worker.py` for the word, and
fails if it appears.

What the two panels share is the view and the controls: the page, the
`Model` it draws, and `AdviceWorker`, which runs the three engines.
What they do not share is any line of reading.

**What the Realms panel reads that the TTR panel cannot:**

| | TTR panel | Realms panel |
|---|---|---|
| Which cog | Matched from the head on its plate, or picked by the player | Stated by `setDNAString` |
| Cog health | A fraction read off a bar | Exact |
| Lured, and with which gag | Lured only, from a red tile; the player can mark it | From the battle's roster and the attacks chosen |
| Trap under a cog | Not read | From the battle's roster, including which trap |
| Toons in the battle | A number the player enters | From the battle's roster |
| Teammates' laff, pouch and training | Not available | Read |
| Gag counts | Digits read off the gag menu | Exact |
| Pink slips | Read from the Local API | Read |
| Unites | A count the player enters, kind unknown | Read, by kind and track |
| SOS cards | Not available | Read, by name |
| Which boss fight, and cogs defeated | The client's log for one fight; defeats inferred from plates | The boss object's class; defeats counted by cog id |

Because the server states them, the controls for naming a cog, typing
its level, and marking it lured or trapped are inert in this panel.
They exist, since both panels render the same page and a missing
method would fail at click time, and they do nothing. The toon-count
control acts only as a lower bound on the size of a boss fight. The
"I'm in a fight" button refreshes and recomputes; it does not override
detection.

The engines run when the *position* changes: laff, each cog's health
and lure, the pouch, the party size. They deliberately do not run on
the battle's state string, which cycles several times a round.

## How a board is built

`solver/live/realms_session.py` assembles the board. Like the TTR
builder, it returns a board or the reasons there is none, and never a
guess. The refusals are a different kind, because the values are
typed: an object has not arrived yet, or it cannot tell which battle is
the player's.

| Fact | From |
|---|---|
| Cogs in the fight | The cog ids in the battle's `setMembers` |
| Cog identity, level, health | `setDNAString`, `setLevelDist` (the level minus one), `setHP` and `setMaxHP` |
| Lured | The lured list in `setMembers` |
| Which Lure, and rounds left | `setChosenToonAttacks`, and a count of rounds since |
| Trap | The trap slots in `setMembers` |
| Laff | `setHp`, `setMaxHp` |
| Pouch | `setInventory` |
| Tracks owned, organic | `setTrackAccess`, `setTrackBonusLevel` |

Points that are not obvious:

- **Which battle is yours.** More than one battle can exist at once: a
  Vice President (VP) fight has two, one per side. The player's is the
  one whose roster lists the player's toon. If that cannot be
  established the reader declines.
- **A lured cog needs its Lure's level.** The roster says a cog is
  lured and not with what, and the solver's wake-up rule depends on the
  gag. The level is known whenever the Lure was thrown while the reader
  was attached. If the reader joined mid-fight it refuses that board,
  and one round later the gap has closed.
- **Lure rounds left are counted, not read.** The server does not
  publish a duration. The reader takes TTR's duration for that gag and
  subtracts the rounds since it landed, never going below one. This is
  a TTR-consistent reading of a Realms position, not a measurement of
  Realms.
- **Health is corrected forward.** When a round is committed the server
  writes each cog's health as it stood going into that round, so the
  stored value is a round behind while the player chooses. The round's
  own result (`setMovie`) arrives with the commit and is applied; the
  server's next write then overwrites it. Observed on a live fight:
  health 90 at one commit and 61 at the next, with every gag in between
  having hit.
- **Training level is not read.** `setTrackAccess` says only whether a
  track is owned. An owned track is taken as fully trained, which
  affects accuracy for a toon that is not.
- **Organic is taken as the player's.** Whether a laid Trap or a landed
  Lure was organic is decided from the player's own tracks. Who threw a
  teammate's gag is not tracked.

## Consumable holdings, read from a live client

The toon's pink slips, unites and SOS cards arrive by the same route as
the pouch. They were first captured from a running Realms client on a
maxed-out sandbox toon, holding 998 or 999 of each unite and 99 or 100
of each of 16 SOS cards. Those counts show the format and say nothing
about what a real player carries.

**The toon is invisible until it is described again.** The stream
carries only changes, and the player's toon is created at login, before
the reader attaches. A zone change describes it again; walking through
a tunnel is enough. Finding this cost an hour of looking for a
subscription bug that was not there.

### SOS cards resolve exactly

`setNPCFriendsDict` is a list of (non-player toon id, count). The names
come from `phase_3/data/npctoons.json` inside the install's data pack,
read at run time and never copied into the repository. Checked against
one local install on 2026-10-11: the table names 712 non-player toons,
of which 29 distinct names are SOS cards the solver knows. All 16 ids
in the first capture resolved to cards in `sos.BY_NAME`. An id the
table does not name, or a name the solver does not know as a card, is
dropped and never guessed.

### Unites: the categories, from the menu itself

`setResistanceMessages` is a list of (id, count), where the id is
`category * 100 + index`. Nothing in the install names the categories.
The maintainer supplied them from the in-game SpeedChat menu, so the
table is `[OWNER]`:

    category 0   ids 0-4       Toon-Up      5 entries   10, 20, 40, 80, MAX
    category 1   ids 100-107   Gag-Up       8 entries   one per track, then All
    category 2   ids 200-203   Jellybeans   4 entries   100, 200, 350, 600
    category 3   ids 300-304   Toon-Down    5 entries   custom to Realms

The entry counts corroborate the reading and do not establish it:
category 1 holds exactly eight, which is seven tracks plus all-tracks.
The Gag-Up submenu is in Toontown's usual track order, so index 107 is
"All" and not an eighth track.

Only Toon-Up and Gag-Up are counted as usable in a battle. On the
captured toon that was 12,985 of a grand total of 21,973, so counting
everything would have inflated the holding by two thirds with unites no
battle can spend.

**Which unites, not only how many.** `ToonState.unite_stock` holds
`{(kind, track): count}` and `unites.candidates` filters on it, so a
toon holding only a Lure restock is not offered a Squirt one. Gag-Up
All is its own menu item with its own key: holding seven single-track
restocks does not grant it. A Toon-Up is keyed on the kind alone, since
the values are this server's own.

**An empty stock means unknown, not none.** A toon with a unite count
and no stock recorded is read as "this many unites, kind unrecorded",
which is what every offline test harness supplies. The count is what
denies: it is zero unless something read a pouch.

Spending is copy-on-write. Copies of a board share the stock the way
they share gag counts, and changing it in place is the bug that once
grew a Trap pouch from 25 to 51 with no unite used.

### The caps

The panel has three boxes: pink slips, unites and SOS calls. All
default to zero. The server says what is *held*; the box says what the
player is willing to *spend*; and neither alone grants anything. A box
with no reading would invent a holding, and a reading with no box would
spend a scarce resource without being asked.

- **The boxes are a session budget** `[OWNER]`: what the panel may plan
  with while it is open. Each slip, unite or card that really leaves
  the toon ticks its box down, on screen too, and when a box runs out
  the player raises it. Nothing resets. Per-fight budgets were tried
  first and broke twice, because where one fight ends is something the
  panel has to infer and where the session ends is not.
- **Spending is observed, not assumed.** The toon's real counts arrive
  every poll, so a box falls only by what actually left. A count that
  rises, such as a reward, grants nothing.
- **The SOS box is one pool.** "Five SOS calls" once reached the solver
  as five of every card held, so with sixteen card types a simulated
  fight could call eighty. `ToonState.sos_calls` carries the pool, and
  every card type the toon holds stays available within it.

## Teammates

The battle's roster names every toon in it, and the reader queries each
one. A teammate that can be read becomes a full toon on the board the
PPO and Playout engines see: laff, pouch and training. Those two
engines then plan the party's moves together and the panel shows the
player's part. The Search engine still counts teammates as a number.
A teammate who cannot be read is left out, not guessed at, and a
teammate's slips, unites and cards are never planned with.

This is more than a player sees on screen. A teammate's pouch is sent
by the game only to that teammate's own client, and the reader obtains
it by asking the server. Anyone judging the tool should know that.

Measured in simulation, not in Realms play: on 40 party VP fights,
planning the party's moves together won 23 and each toon planning alone
won 0. That was with each side facing the cog count of a solo fight. At
the smaller count the maintainer reports a two-toon side really faces,
both ways of planning won all 40.

## Boss fights

A boss room's battle object carries the id of its boss, and the boss
object's class names the fight (`DistributedSellbotBoss` is the VP, and
so on for the other three). Cogs defeated are counted exactly: a cog id
that leaves a boss battle's roster was defeated, each counted once.
The count restarts when the boss object changes, which is what
separates two fights of the same kind.

The number of toons in the whole fight is read from the boss object's
`setToonIds` where it is present. That field's meaning comes from the
Open Toontown source and had not been seen live when the code was
written, so the toon-count control remains as a lower bound.

## The wire protocol, as established

Every line here was settled by observation against a running server,
because reasoning about Astron's message numbering got it wrong twice.
The full account of each is in [live-notes.md](live-notes.md).

**Message types.** "Confirmed" here means the message delivered
something that decoded to a real class or field on a live capture:

| Number | Message | Status |
|---|---|---|
| 2014 / 2015 | `GET_ALL` and its reply | Confirmed |
| 2020 / 2021 | `SET_FIELD` / `SET_FIELDS` | Confirmed |
| 2042 / 2043 | `ENTER_LOCATION_WITH_REQUIRED` and its `_OTHER` form | Confirmed |
| 2052 | `ENTER_AI_WITH_REQUIRED` | Confirmed |
| 2040, 2046 | **Not** enter messages; see below | Disproven |

**A `SET_FIELD` does not name a class.** The object is tagged with the
class the field was declared on, which is a base of the real one. Cogs
appeared early because street cogs constantly send a field declared on
their base class. A battle's state changes only at phase changes, so
battles existed only in the enter messages. The enter messages are the
only reliable source of an object's class.

**2040 and 2046 arrive exactly once per object** and are still not
enter messages. Parsed as such they delivered no objects across a whole
fight, against 34 for the three confirmed types. What made the wrong
guess safe was that the reader declines any object whose class does not
resolve. Without that the store would have filled with nameless objects
and a bad guess would have looked like a discovery.

**panda3d's two accessors disagree.** Asked for a field that does not
exist, one returns nothing; asked for a class that does not exist, the
other fails a C++ assertion and takes the thread with it. One malformed
datagram (message) once killed the reader. Bounds are now checked in
one place, and one bad datagram costs one datagram.

**A group Lure has no target.** The attacks field names its target as a
position in the cog roster, and a group Lure's is a placeholder. The
last Lure thrown in a battle is remembered battle-wide as a fallback.

**The stream is the authority; a query only fills gaps.** A query's
answer is stale when it lands. Applied wholesale it reverted values the
stream had since delivered, which read as health stuck a round behind.
Fields that only a query can deliver, such as the pouch, are refreshed
by every query.

**Ask sparingly.** Re-asking about all 137 objects on every poll put
several hundred queries a second through the server and 6,000 replies
through one fight, most of them describing a butterfly that had not
moved. The battle's roster is refreshed every poll; the full sweep runs
every ten seconds.

## Verified end to end

A live street fight, read with nothing on screen:

    Mover & Shaker, level 9, 110/110, LURED
    -> Birthday Cake on cog 1

It cross-checks three ways against tables Realms never touched. The TTR
table gives a level 9 cog 110 hit points and the server said 110. The
toon's organic Throw makes Birthday Cake 110 damage. And the cog being
lured forces the hit. An exact defeat, chosen for reasons that can be
checked by hand.

## Reading a VP live: three things the first log turned up

The first logged solo VP, 34 boards, exposed three reader faults. All
three are fixed.

**A defeated cog stays on the field at 0 HP**, through its animation
and into the next turn `[OWNER]`. Fourteen of the 34 boards had one,
and every engine advised group gags and SOS cards into cogs that were
already gone. A cog at 0 HP with no revive left is now marked dead. It
keeps its position, so targets still match the roster.

**Rounds are counted on entering the movie state**, not per datagram.
Every datagram arrives twice, and counting each one aged every Lure two
rounds per round: a $10 Bill read 2 rounds left after one round of
four, and a Presentation 4 of 8.

**Every recorded row holds all three engines' moves.** Rows where the
player stated a preference used to drop the Playout row's move, which
is why the first log could not compare it on six boards.

## Recording

Three flags record what the panel saw. All are off by default.

| Flag | Writes |
|---|---|
| `--feedback PATH` | One row per round: the board, each engine's proposal, and the move actually made |
| `--watch PATH` | One fight as a sequence of boards, written when the fight ends. Pair with `--engine none` to record without computing advice |
| `--record PATH` | Every searched position and its advice, exactly, so a questioned pick can be replayed |

The move actually made is observed, not asked for: the pouch is read
every poll, and a thrown gag takes one off one cell. A round that
cannot be read cleanly is recorded as unreadable, with the reason.

Every row is stamped `source=realms`. These rows are one player's
preferences on a different server, and by the rule at the top of this
page they are quarantined from TTR training.

## Known gaps

- **Lure rounds and damage are TTR's.** The panel prices a Realms
  position by TTR's rules, so its numbers can differ from what Realms
  rolls wherever the two games differ. Lure duration is the doubtful
  one: TTR rebalanced it and Realms may not have.
  `python -m solver.live.realms_lurewatch` exists to measure how long a
  Lure really lasts in Realms. No result from it is recorded here, and
  by the rule above any result could only adjust the Realms reader,
  never a TTR table.
- **Training level** is not read (see above).
- **Trap fallback.** When the roster does not show a trap, the reader
  falls back to the attacks it watched being chosen. That fallback has
  never fired on a live capture and should not be relied on.
- **Two Lure levels in one party round** aimed at different cogs can be
  attributed wrongly by the battle-wide fallback.
- **Which toon is yours in a party.** The reader takes the player's
  toon to be the one toon whose pouch it holds, and declines to choose
  when it holds more than one. The board builder then falls back to
  the first toon in the battle's roster. Since teammates' pouches are
  also queried, a party is where more than one pouch is held. Whether
  the fallback then names the right toon has not been checked.
- **Boss fights other than the VP** are named by the same mechanism.
  The project's notes describe Realms VP fights read live and mention
  no other boss fight read this way. The sizes of the Chief Financial
  Officer and Chief Justice fights are not known to the solver.
- **Other platforms.** The install is looked for in Windows locations
  only.
