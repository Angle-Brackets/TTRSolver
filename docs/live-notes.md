# Live reader notes: how the debugging actually went

**This file is a historical record, not the current reference.** It was
written on 2026-08-30 and is the debugging history behind three
modules: `solver/live/realms.py`, `solver/live/realms_panel.py` and
`solver/live/watch.py`. It records wrong diagnoses, wire-format dead
ends, and the incidents that forced a rule. The code keeps short
docstrings that point here by section, and this is where the story and
the evidence live.

For how the tool reads a game today, see:

- [live-reading.md](live-reading.md): the current reference for every
  source the Toontown Rewritten (TTR) panel reads.
- [realms.md](realms.md): the current reference for the Toontown Realms
  reader, and the rule that nothing read from Realms may be used as TTR
  game data. It covers the same wire protocol as the first part of this
  file from the "what to trust" angle, and the two overlap on some
  facts by design.

## How to read this file

Terms used below: *Astron* is the open-source server software that
Toontown Realms runs on the player's own machine. A *dclass* is a class
in its `.dc` schema file, a *doId* is an object's id, and a *datagram*
is one message on its internal bus. A *plate* is the sign Toontown
Rewritten draws above each cog in a battle. "The maintainer" is the
project's maintainer, an experienced player whose reports from play are
cited as evidence.

The body is kept as it was written, so that the reasoning behind each
rule stays intact. Where a statement has since become false, a dated
note beside it says so:

> **Note, 2026-10-11.** Notes in this form were added later and
> describe the code as it stood on that date.

Section headings are unchanged, because code comments link to them.

## What has changed since this was written

None of the following is covered by this file. Each is described in
[live-reading.md](live-reading.md) or [realms.md](realms.md).

- **A third engine.** The panels now show three engines (PPO, Search
  and Playout) and the Playout row leads by default. Statements below
  about "the policy" and "the search" being the only two, and about
  which of them plays better being unmeasured, predate that.
- **TTR digit reading.** Gag counts and plate levels are now read by
  small classifiers trained on synthetic digits, and the gag menu is
  remembered across polls while it stays open. The `watch.py` section
  below describes the older template matching.
- **New TTR sources.** The client's log file (which boss fight), a
  relay for what the game publishes to Discord (building floors), and
  the Local API's pink slip count were all added in October 2026.
- **Realms holdings and teammates.** The Realms reader now also reads
  pink slips, unites, SOS cards and teammates, and tracks boss fights.
- **Shared worker.** Both panels now share `solver/live/worker.py`
  (`AdviceWorker`). Some functions described below under
  `realms_panel.py` have moved there.
- **Party search.** A party position can now be searched
  (`solver/search/party_search.py`). Remarks below that it cannot
  predate that.

## Sections that code comments point at

| Code location | Section |
|---|---|
| `realms.py` module docstring | [solver/live/realms.py](#solverliverealmspy) |
| `realms.py`, state server message constants | [State server message numbering](#state-server-message-numbering-six-of-the-constants-were-wrong) |
| `realms.py`, `PROBE_ENTER` | [2040 and 2046 are not ENTER messages](#2040-and-2046-are-not-enter-messages) |
| `realms.py`, `BATTLE_CLASSES` | [BATTLE_CLASSES](#battle_classes-distributedbattlebase-has-to-lead-the-list) |
| `realms.py`, `DCIndex` | [DCIndex](#dcindex-use-the-games-own-parser-and-guard-dclass) |
| `realms.py`, `ObjectStore.enter` | [ObjectStore.enter and the `fill_only` rule](#objectstoreenter-and-the-fill_only-rule) |
| `realms.py`, `DNA_COGS` | [Suit DNA](#suit-dna) |
| `realms.py`, `cog_level` | [cog_level](#cog_level-its-the-level-minus-one-not-a-range-offset) |
| `realms.py`, `DC_TRACK_ORDER` | [Track order](#track-order-is-written-out-not-taken-from-the-enum) |
| `realms.py`, `parse_organic` | [parse_inventory, parse_track_access, parse_organic](#parse_inventory-parse_track_access-parse_organic) |
| `realms.py`, `Members` and `Members.traps` | [Members / setMembers](#members--setmembers) |
| `realms.py`, `RealmsListener.refresh` | [RealmsListener.refresh and refresh_battle_members](#realmslistenerrefresh-and-refresh_battle_members) |
| `realms.py`, `_note_chosen_attacks` | [_note_chosen_attacks](#_note_chosen_attacks-tracking-lure-and-trap-intent) |
| `realms.py`, `apply_movie` | [apply_movie](#apply_movie-correcting-for-stale-hp-and-the-doubled-datagram) |
| `realms.py`, `trap_on` | [trap_on / lure_age](#trap_on--lure_age) |

## solver/live/realms.py

### The Astron control protocol

Control messages address channel 1 and OMIT the sender field that every
other message carries. Getting that wrong shifts the message type by
eight bytes and every datagram after it decodes as garbage, which looks
like a wire format problem rather than an off-by-one.

### State server message numbering: six of the constants were wrong

The original numbering was guessed rather than sourced, and six of the
values were wrong. Confirmed by observation: 2020 carried every one of
567 datagrams in the first live capture and decoded as `SET_FIELD`, and
2014/2015 round-tripped a `GET_ALL` query into a full object. Those four
match Astron's documented numbering exactly, which is the reason to
trust that numbering for the rest rather than the numbers previously
here — 2007, 2060 and 2064-2067 were invented, and 2060 is really
`SET_OWNER`, so an ownership change was being applied as a relocation.

`_unknown` counts anything unrecognised, so a number that is still wrong
shows up as a count instead of as silence — that is how the six wrong
ones were eventually found.

`OBJECT_ENTER_LOCATION_WITH_REQUIRED` (2042), `_OTHER` (2043) and
`OBJECT_ENTER_AI_WITH_REQUIRED` (2052) are `[CONFIRMED] live`: in one
fight, 2042 delivered `DistributedBattle` and `DistributedSuit`, 2043
delivered `DistributedToon`, and 2052 delivered `DistributedBattle` — 34
objects between them, every dclass id resolving to a real class. These
three are what a battle and the player's own toon arrive on, and nothing
else announces them.

### 2040 and 2046 are not ENTER messages

They arrive exactly once per object, which is the ENTER pattern and is
why they were suspected — but parsing them that way delivered ZERO
objects across a whole fight while 2042/2043/2052 delivered 34. `_enter`
refused every one because the dclass id did not resolve: the guess was
wrong and the validation is what said so, rather than a store full of
objects named `<60000>`.

They are left unparsed deliberately. They are almost certainly
`SET_LOCATION` (2040, a command TO the state server rather than a
broadcast, so it carries no object) and a `GET_LOCATION` reply (2044 and
2046 turn up together). Neither describes an object, so neither is
wanted; both are counted in `_unknown` and ignored.

### BATTLE_CLASSES: DistributedBattleBase has to lead the list

A `SET_FIELD` names no class, so `_record` tags the object with the
class the field was DECLARED on -- for an inherited field that's the
base. Both `setState` and `setMembers` are declared on
`DistributedBattleBase`, so a battle learned only from the live stream
(never seen via an ENTER message) is tagged `DistributedBattleBase` and
must appear in `BATTLE_CLASSES` under that name or `battles()` matches
nothing. Cogs were unaffected by the equivalent gap because
`DistributedSuitBase` was already first in `COG_CLASSES` -- which is
exactly why the missing battle base went unnoticed for a while: the
tool that called `refresh_all` first got the real class from the ENTER
path and worked, and the one that relied on the stream alone saw no
battles at all.

### DCIndex: use the game's own parser, and guard `dclass()`

A hand-rolled `.dc` parser assumed the field numbering follows
declaration order. It does not — that numbering is the wire contract
between client and server — and the hand-rolled version put
`DistributedSuit.setPathPosition` at 492 and decoded live cog traffic as
`DistributedPlayer.setDISLname`, which is wrong in a way that looks
plausible until you notice street cogs do not have account names.
panda3d's `DCFile` is the parser the game itself uses, so it is right by
construction rather than by agreement.

`DCIndex.dclass` is guarded because panda3d's two accessors disagree:
`getFieldByIndex` politely returns `None` for a bad index; `getClass`
fails a C++ assertion and takes the thread with it. An out-of-range id
off the wire killed the reader thread rather than being skipped as one
bad datagram, before bounds were checked centrally in `dclass`.

`DCIndex.unpack` returns `(None, None)` on failure rather than raising,
because one malformed field must not take down a listener reading a
whole cluster's traffic. It also unwraps `unpackObject`'s one-tuple
return for single-argument fields (`setHP` comes back as `(6,)`, not
`6`) — multi-argument fields like `setMembers` and `setState` keep their
tuple.

### ObjectStore.enter and the `fill_only` rule

A `GET_ALL` answer describes the object as the state server saw it when
the query was processed, so it is already stale by the time it lands.
Applying it wholesale REVERTED values the live stream had since
delivered: with the battle roster re-queried every poll, a cog's HP was
overwritten with a pre-hit snapshot about twice a second, which read as
health stuck a round behind the fight. The stream is the authority and
the query is the bootstrap: use it to learn what was missed before
attaching, never to correct what is already known. `fill_only=True`
writes only fields not already present.

`setdefault` was tried first and was too blunt — it froze fields the
stream never sends. `setInventory` is declared `ownrecv`, so **the
pouch goes to the owning client and not to a listener — a query is the
only way it is ever seen.** Filling it once and never again left the
solver planning with the gags the toon started the session holding,
which is a far worse error than the stale HP the fill-only rule exists
to prevent. `obj.streamed` tracks which fields the stream has actually
delivered, and only those are protected from a refresh.

### Suit DNA

`DNA_DEPARTMENTS` is `[CONFIRMED BY OBSERVATION]`: all four letters
turned up in one live capture and each agreed with the cog it was
attached to — `'sf\0\0c'` a Flunky, `'scc\0s'` a Cold Caller, `'spp\0m'`
a Penny Pincher, `'sdt\0l'` a Double Talker.

`DNA_COGS` is `[OPEN TOONTOWN SOURCE]` — a naming map, not game data, so
it does not fall under the ban on Realms numbers reaching
`solver/data/`; nothing here is a stat. Five entries (`sc`, `cc`, `f`,
`pp`, `dt`) are `[CONFIRMED BY OBSERVATION]` from live captures. Six
more are confirmed from the game's own data pack, which prints them into
its log beside the localiser key — `'mh'` next to `#SuitMrHollywood`,
`'nd'` to `#SuitNameDropper`, `'gh'` to `#SuitGladHander`, `'ms'` to
`#SuitMoverShaker`, `'m'` to `#SuitTheMingler`, `'cc'` again to
`#SuitColdCaller`. The rest follow the same scheme; an unknown code
returns `None` rather than a guess.

### cog_level: it's the level minus one, not a range offset

Four live reads settled this, cross-checked against our own HP table
rather than against Realms:

    Flunky        dist 0, hp 6   -> level 1   (both readings agree)
    Cold Caller   dist 0, hp 6   -> level 1   (both agree)
    Penny Pincher dist 1, hp 12  -> level 2   (range starts at 2,
                                               so an offset would
                                               have been 0)
    Double Talker dist 2, hp 20  -> level 3   (range starts at 3,
                                               offset would be 0)

The last two discriminate, and both say `level = dist + 1`. The two
readings (offset-into-own-range vs. absolute-minus-one) agree for every
cog whose range starts at 1, which is what makes them easy to confuse.

### Track order is written out, not taken from the enum

`DC_TRACK_ORDER` is written out rather than taken from `Track`'s
declaration order, which happens to match today. Iterating the enum
would couple the wire format to the order members are declared in an
unrelated file, and reordering that enum — an edit with no obvious
connection to this module — would silently shift every gag count by one
track. The wire order is a property of the game, so it is stated here.

### parse_inventory, parse_track_access, parse_organic

`parse_inventory` was verified against a real toon: the Toon-Up row was
all zeros and that toon's `setTrackAccess[0]` was 0, an independent way
of saying the same thing.

`parse_track_access`: a toon with `[0, 1, 1, 1, 1, 1, 1]` has no
Toon-Up, which is a real and awkward loadout rather than a misread.

`parse_organic` reads `setTrackBonusLevel`: -1 means not organic,
otherwise the level the bonus reaches. **The level is 0-based and 6
means the whole track**, per the maintainer — a real toon read
`[-1, -1, -1, -1, 6, -1, -1]`: Throw organic, all seven levels. This
project treats organic as a property of the whole track (see
`ToonState.organic_tracks`), matching how TTR works — a track is earned
organic by ToonTask and every gag in it is organic thereafter — so any
non-negative entry makes the track organic and the level itself is
dropped.

> **Note, 2026-10-11.** The level is no longer dropped, and the
> statement about how TTR works was wrong. A change on 2026-10-07 made
> organic stop at the highest gag planted rather than cover the whole
> track. `parse_organic_levels` now keeps how far up the bonus reaches,
> and it reaches the board as `ToonState.organic_levels`.
> `parse_organic` still answers only which tracks are organic.

Whether "organic" means the same thing in both games is a separate
question, and the answer is no: Realms gives organic a flat +10% to
damage, while TTR's bonus varies by track and also raises Lure accuracy
(`Gag.organic_damage` is a per-gag column here for that reason). So this
function correctly reads WHICH tracks are organic, and the solver then
prices them by TTR's rules — reading a position is not reading a rule —
but a damage number predicted here will not match what Realms rolls.

### Members / setMembers

The DC declares twelve untyped-looking slots:

    setMembers(uint32[], string, string, string, string, string,
               uint32[], string, string, string, string, int16)

— Toontown's long-standing shape: the suits and their four state
strings, then the toons and theirs, then a timestamp. Observed live as

    ([401005039], '', '', '0', '', '9', [100000001], '', '', '0',
     '', -23220)

one cog and one toon, a solo street battle, reading correctly as such.

**The state strings are two different encodings**, settled by
observation rather than assumed. A second capture, two cogs with the
first one lured:

    active='01'   lured='0'   traps='99'

`traps` has one character per suit. `active` and `lured` do NOT — they
are the INDICES of the suits in that state. One lured cog out of two
gives `'0'`, where a per-suit encoding would have given `'10'` or
similar. The earlier single-cog capture (`lured=''`, `traps='9'`) agrees
with both readings and so decides nothing; it is the two-cog frame that
discriminates. Reading `lured` as one-char-per-suit would mark the wrong
cog asleep, in a solver where lure is the pivot of every Trap line.

**What a trap looks like was long unobserved.** Every capture for a
while had `'9'` in every trap slot, and `setMembers` was believed to be
re-broadcast only on membership change — so a trap set mid-round would
never resend it, and `trapped_indices` could only report "this slot is
not 9", enough to know a trap is there and not which gag it is. This
was later corrected: see "the roster does refresh" below.

**Traps, decoded.** `traps()` reads one character per suit, and it is
the trap gag's 0-BASED LEVEL rather than a flag: `'9'` is the sentinel
for no trap (there are only seven trap levels, so 0-6 are real values
and 9 cannot collide). `[CONFIRMED]` live: a trapped Money Bags read
`'4'`; the decode says level 5, Trapdoor; the maintainer confirmed a Trapdoor
is what they threw. Untrapped cogs read `'9'` in every capture across
many fights.

**And the roster does refresh.** This module previously said the
opposite — that `setMembers` is only re-broadcast on a membership
change, so a trap laid mid-round would never appear. That was wrong: the
slot updated with the cog still in the fight. The watched-attacks path
(`chosen_traps`, fed from `setChosenToonAttacks`) stays as a fallback
for when a stale roster and a fresh observation disagree, but the roster
is authoritative and preferred.

### RealmsListener.refresh and refresh_battle_members

**Why `refresh` exists at all.** The stream carries CHANGES. An object
generated before the listener attached has therefore never been
described to it: the first live run saw 944 datagrams, decoded every
one, and still reported `hp=None` for a cog standing in front of the
player, because the cog's `setHP` was packed into a generate message
that had already been and gone. Requiring the tool to be attached before
the fight starts is not workable for something a player turns on when
they want advice, so `refresh` asks instead — and it is still a read:
`OBJECT_GET_ALL` is a query, it mutates no object, sends nothing to the
client, and is answered on the listener's own private channel.

**The missing link was `refresh_battle_members`.** A live capture showed
a battle with one suit in its roster and `cogs: 0` in the store. Cogs
are generated long before the fight — they walk the street first — so
the listener usually never sees a field update for them, and
`refresh_all` only asks about objects it already knows. The battle
itself says which cogs matter, so reading its roster and asking about
those doIds directly closes the loop.

### _note_chosen_attacks: tracking Lure and Trap intent

`setMembers` says a cog IS lured and never which gag did it, and the
solver cannot use a lure without that — `lure_can_expire_early` keys off
the gag's level, and a cog marked lured with no level raises the moment
the search touches it. `setChosenToonAttacks(toonIds, tracks, levels,
targets, ...)` is the only field that says. Targets are indices into
the battle's suit roster, so the roster has to be read at the same time
— cogs die and the indices shift.

Only Lure and Trap are kept from this field. Everything else the solver
reads from state rather than from intent, and intent is the weaker
source: a chosen attack is what a toon MEANT to do, and it may miss.

**Traps come from here** because `setMembers`'s `suit_traps` slots,
while authoritative when fresh, are not always fresh (see above) — a
trap laid mid-round could read `'99'` with a cog visibly standing on a
TNT. A trap always targets exactly one cog (there is no group Trap), so
the target index is always a real slot.

**A battle-wide Lure fallback exists because the per-target index is not
always usable.** A GROUP Lure hits every cog and has no single target,
so its `target` field is a sentinel rather than a slot — keying only on
the slot recorded nothing at all, and the reader then refused a cog it
had watched be lured, wrongly saying the Lure was thrown before it
attached.

**A Lure spends a trap**, so landing one clears any trap held for the
cogs it reaches (all of them, for a group Lure). Clearing on the LURE
rather than on the cog turning up lured is the whole point: a trapped
cog dragged onto its trap takes the damage and is knocked awake, so it
never appears in `suits_lured` at all — waiting for it to would hold the
trap forever and have the solver plan a second combo for damage already
collected.

This is DELIBERATELY CONSERVATIVE in the other direction too: a Lure
that MISSES leaves the trap in place, and this forgets it anyway, so the
solver stops seeing a combo that is really still available. That is the
safe direction — under-claiming a trap costs a better line, over-
claiming one plans damage that will never arrive.

### apply_movie: correcting for stale HP, and the doubled datagram

**Why this exists at all.** The server writes a cog's `setHP` at COMMIT
time, and the value it writes is the HP going INTO that round — the
damage a round deals only reaches the state server at the NEXT commit.
Confirmed against a live fight: HP 90 at one commit, 61 at the next,
with the maintainer confirming every gag in between had hit. That leaves the
panel a round stale over exactly the window it's used in
(`WaitForInput`, while the player chooses), and no amount of re-querying
fixes it, because the state server does not have the number yet either.

`setMovie` does: it is `required broadcast ram`, carries the round's
resolution (`ToonAttack.hp` is damage per target), and arrives WITH the
commit, before the animation plays. Applying it moves the reader from a
round behind to slightly ahead. It's safe to apply because `setHP` is
ABSOLUTE — when the real value turns up at the next commit it overwrites
this rather than compounding with it. This is a forward correction the
server later confirms.

**Every datagram arrives twice**, because a full-range subscription
matches both an object's own channel and its location channel — without
de-duplication (`_last_movie`, keyed by a fingerprint of the value) the
damage would apply twice and every cog would die at half health.

> **Note, 2026-10-11.** The same doubling was later found in the round
> counter, which had not been guarded. Counting every datagram that
> named the movie state aged each Lure two rounds per round. Rounds are
> now counted on entering the movie state (`_note_state`). See
> [realms.md](realms.md#reading-a-vp-live-three-things-the-first-log-turned-up).

### trap_on / lure_age

`trap_on` prefers `setMembers`: a slot that is not `'9'` means the
server says there is a trap there, and if that ever disagrees with what
was watched being thrown, the server wins. **The watched-attacks
fallback has never fired** and should not be relied on: a live capture
counted two Trap attacks (`traps_seen == 2`) and stored none of them, so
the target in `setChosenToonAttacks` is evidently not a roster slot for
Trap the way it is for a single-target Lure. It's left in place because
it costs nothing and the roster is authoritative anyway, but anything
that starts depending on it needs to establish what that target actually
is first.

`lure_age` falls back to the last Lure thrown in the whole battle when
no specific cog entry exists. Right for a group Lure, right for a solo
fight; the only case it can be wrong is two different Lure levels aimed
at different cogs in one round, which needs a party, and a party cannot
be searched yet anyway.

> **Note, 2026-10-11.** A party can now be searched, so that last
> clause no longer excuses the gap; the limit itself still stands. Both
> functions also now find a cog's battle by its roster
> (`RealmsListener._battle_of`) instead of requiring exactly one battle
> on the server. A Vice President fight has two battle objects, one per
> side, and requiring exactly one made every Lure and Trap in a boss
> fight read as unseen.

## solver/live/realms_panel.py

### Why a second panel, not a mode of the first

`overlay.Worker` polls a screen capture, runs `find_plates`, reads a gag
menu and hedges every number it produces with a confidence. None of that
applies here: `realms_session` is handed typed fields by the server.
Threading a second world through the TTR worker would put `if realms:`
through the one module whose entire job is being careful about pixels,
and the TTR panel would then be able to break from an edit made for a
game it does not read.

`Model`, `CogRow` and `model_json` are imported and never modified —
they are the VIEW, a description of what a panel shows, and both panels
showing the same thing is the point rather than a leak. The built React
app renders this with no changes at all. What is not shared is every
line of reading.

What the player sees differently, all of it because the data is better:
cog names are never "?" and the picker is never needed (identity comes
from `setDNAString`); health is exact (20/20 because the server said
20/20, not a fraction read off a green bar); LURED is read from the
battle roster rather than marked by hand; party size is read from
`setMembers` rather than asked for.

> **Note, 2026-10-11.** `overlay.Worker` and the Realms worker now both
> subclass `AdviceWorker` in `solver/live/worker.py`, which holds the
> controls and the engine plumbing the two panels have in common. The
> reading is still separate, and a test fails if the TTR modules or the
> shared worker mention Realms. The Realms panel also reads more than
> is listed here; see [realms.md](realms.md#the-panel).

### DEFAULT_BUDGET: depth 4 was tried at 12s and bought nothing

Depth 4 never completes — depth 3 was measured at "many minutes"
([search-depth.md](search-depth.md)) — so iterative deepening always runs to the deadline, however long that
is. Measured on the maintainer's real 70-gag loadout, the recommended move
stops changing by 2s in every position tried: one cog, two cogs and
four. It's not free time either: the search is CPU-bound Python in the
same process as the UI, so a long one starves the poll loop and the
window both, which showed up as a panel that dragged when moved and cog
health that appeared to stop updating. Budget was cut to 4.0s.

### search_in_child runs in a process, not a thread

The search is CPU-bound pure Python, so a thread holds the GIL for most
of its slice and starves both the poll loop and the window — the panel
dragged when moved and cog health appeared to stall. Cutting the search
from twelve seconds to four only made that less obvious, not fixed. A
process has its own interpreter and cannot interfere at all.

`search_in_child` is a top-level function, not a closure, because
Windows spawns rather than forks, and a closure cannot be pickled into a
fresh interpreter. It returns `(text, track, level)` rather than an
`Action` so nothing but a string and two scalars crosses the process
boundary, and the child renders the wording itself so it stays identical
either way.

> **Note, 2026-10-11.** It now returns `(text, track, level, target)`.
> The target was added because the panel's explanation of a move
> simulates the round, and a move rebuilt without its target read as
> hitting every cog.

### RealmsWorker.reconsider and the rejection-key bug

Rejections key on `hybrid.reject_key`, not the exact action: every fire
shares one key, so dismissing "pink slip on cog 2" dismisses spending a
slip at all, rather than offering the same move against cog 3, then cog
1, then cog 4 — which is exactly how this control would become useless.

`reconsider` does NOT reset `self._last_key`. That line used to be there
to force a recompute, and it silently undid the rejection: `tick` clears
the rejected set whenever the position key differs, and an empty key
always differs — so the rejection was wiped on the very next tick,
before anything could read it, which is why the button appeared to do
nothing at all. `ask_now` already forces the recompute through the
`_asked` flag and leaves the key alone, so the board still counts as
unchanged and the rejection survives.

> **Note, 2026-10-11.** `reconsider` now lives on the shared
> `AdviceWorker` and takes a scope: this gag only, the whole track, or
> the middle width described above, which is the default. The rule that
> it must not reset the position key is unchanged.

### _first_answer: the policy answers first, the search may override

`hybrid.climb` is what every offline evaluation in this project actually
runs — the CEO sweeps, the building runs, the ship gate — and it is a
thousand times faster than the search: 1-224ms against 9-12s on the same
positions. It answers immediately, not to replace the search, because
which of the two plays better is genuinely not established: they agreed
on one of three test positions and differed on the other two, and
nothing here has measured which was right. The fast answer goes up
first and the search replaces it if it disagrees.

> **Note, 2026-10-11.** This is no longer how the panel behaves. There
> are three rows now. The policy's answer (the PPO row) still appears
> first, and the Playout row, which plays candidate moves out to the
> end of the fight, takes the lead when it posts unless the player has
> picked a row. Comparisons have also been measured since: on one side
> of a two-player Vice President fight the Search row won 6 of 60 and
> the Playout row 33 of 60.

### Refresh throttling: the fight is refreshed every poll, the world isn't

Both used to share a five-second timer, so a cog's HP was up to five
seconds stale — the server does not re-send `setHP` on every hit, it
sends `damageSuit` for the animation, and the store's value is only as
fresh as the last query. Advice computed against a cog that died four
seconds ago is worse than late advice. The asymmetry is what makes this
cheap: the roster is two to five objects; the full sweep was 137, and it
was the full sweep that needed throttling.

The `_headless` runner's comment records the incident that motivated it
directly: refreshing everything every poll, at roughly 2.5 polls a
second across 133 objects, put a few hundred queries a second through
the message director — 6,000 `GET_ALL` replies in one fight, most of
them re-describing a butterfly that had not changed.

> **Note, 2026-10-11.** The comment in `_headless` has since been
> shortened and no longer carries these figures; this section is where
> they are kept. In the current code the battle's roster is refreshed
> on every poll and the full sweep runs every ten seconds.

### _record_position: pickle the exact state, not a summary

Reconstructing a board from a screenshot has failed twice on picks the
maintainer reported — a Storm Cloud at a lured level 1, and a pass with four
lured cogs and a full pouch. Both rebuilt boards gave sensible moves,
meaning the panel was searching something other than what was
reconstructed, and no amount of rebuilding by hand will find that.
Pickling the exact state avoids the failure mode of a summary: a summary
records what its author thought to write down, which is exactly the
assumption that keeps being wrong. `record_error` is set and surfaced once rather
than swallowed — this used to be a silent `pass`, and the directory the
maintainer chose did not exist, so every round failed silently and the
recording they were relying on was never written.

### pump(): push the model, don't just store it

`App.jsx` installs `window.pushModel` and waits to be called; it does
not poll (`Api.pull` exists only for `npm run dev`, where there is no
Python). Updating `state.model` and stopping there left the page
rendering its own defaults forever — "waiting for a battle" and a 15s
budget while the reader could see the fight perfectly, because 15 is
`App.jsx`'s own fallback and not this module's 12, and that mismatch is
what gave the bug away.

> **Note, 2026-10-11.** The module's default budget was 12 seconds when
> this happened. It is now 4 seconds, for the reasons given under
> `DEFAULT_BUDGET` above.

`pump` also always skips to the newest queued model:
`window.evaluate_js` is a round trip into WebView2 and slower than the
worker's poll, so models pile up behind it, and rendering each in turn
would show the player a replay rather than the fight. The same
"newest wins" rule is why `_post` overwrites the queue instead of
blocking on it: a stale battle state isn't merely late, it's wrong — the
advice beside it was computed for a cog that has since taken damage or
died, and there is no value in an old model once a newer one exists.
This used to be a FIFO that dropped the newest model when it filled, so
under load the panel rendered a queue of stale ones and never caught up
— cog health visibly a round behind the fight.

## solver/live/watch.py

### What counts as a battle: two mistakes, opposite directions

**Teal plates are not sufficient.** The slot colour is not unique
outside a battle screenshot: standing in Donald's Dreamland, 2.1% of a
live frame matched the teal mask and two blobs cleared both the size and
aspect filters, so `in_battle` called it a battle and then called cogs
defeated as the player walked around and the blobs came and went. Every
reading it produced was `level unreadable / unidentified`, which is what
a false positive looks like from the inside — plate-shaped scenery has
no level to read. Entering a battle also requires the gag menu, which
is free: nothing can be advised without it anyway, since gag counts come
only from the screen, and `find_panel` returns `None` on the same
overworld frame that fools the plate detector. The claim in `vision`'s
docstring that the slot colour "appears nowhere else in Toontown's
high-key palette" was validated on battle screenshots only and is false
in the wider game.

> **Note, 2026-10-11.** That docstring has since been corrected and now
> says what this paragraph says.

**Teal plates are not necessary either**, which is the subtler one. When
a round resolves, TTR cuts the camera to show the attack and takes the
menu and every plate with it for the length of the animation. Before
`BATTLE_GRACE` existed, absence was treated as the end, and a single
fight reported itself starting and ending once per round. Absence
therefore means nothing until it outlasts one animation; a crowded
battle animates several attacks back to back, which is where the upper
end of `BATTLE_GRACE` (20s) comes from. Erring long costs only a delayed
`battle_ended`; erring short costs the identity of the fight.

Entry is strict (plates *and* menu) and continuation is lenient (plates
alone), because the menu slides away during attack animations and
requiring it every frame would flap the battle on and off mid-fight.

### Cost: scanning every pixel is the expensive part

Full frame scan: ~70ms at 1080p, ~280ms at 4K, against ~33ms just to
grab the frame. So it's avoided in both states the watcher spends time
in:

- **During a battle**, plates barely move, so the scan is confined to a
  padded band of rows around where they were last seen: 1080p
  75ms -> 19ms, 4K 281ms -> 75ms, one full scan instead of eight.
- **Between battles**, there are no plates to narrow to (this is where
  the watcher is almost always), so a subsampled presence test answers
  "is there any teal at all" for a fraction of the cost, and the exact
  scan runs only once something shows up: 1440p 110ms -> 6.7ms, ~17x.

### Capture: the game's window, not the whole screen

Played windowed, a full-screen grab hands the plate reader the whole
desktop, and the teal mask has no way to tell a portrait slot from a
blue-green wallpaper. On a real desktop this cost every read: one
wallpaper blob outscored both actual plates. `Capture` looks up the
window rectangle per grab rather than caching it, because the window can
be moved, resized or alt-tabbed between frames and a stale rectangle
would silently read the wrong part of the screen — the lookup is a
single `FindWindow` and costs far less than the grab. Falls back to the
whole screen when the window can't be found (the old behaviour).

### _outside_the_menu: a false plate is worse than a missed one

The gag menu holds plenty of teal — cell backgrounds, the empty Drop
slot — and after the slot floor came down to admit a real plate at 1110
pixels, an 80x49 patch inside the TRAP row started passing as a second
cog. A false plate is worse than a missed one: the search then plans
against a cog nobody is fighting. This check costs nothing extra because
`find_panel` has already run this poll for the read gate, and its bounds
are exactly what's needed to exclude the menu region.

### read_frame: identification is re-run only when it's worth it

Identifying a cog (a department match, a level match, a signature
comparison per plate) is the expensive part of a poll, and it was being
redone on every frame, including the ones where TTR is swinging the
camera through an attack — the worst possible input, since the plates
are moving, half-occluded, and the readings flicker. That flicker wasn't
just wasted work: it wiped a cog the player had named by hand.

The gag menu being up is a good clock for "look properly now", because
it's exactly when a decision is due and the board is still. But a boss
fight walks new cogs in mid-round with the menu down, so a change in the
number of plates forces a look too. Between those two triggers, last
round's answer is still this round's answer, because cogs don't change
identity mid-animation.

`menu_visible` is passed in, never computed inside `read_frame`:
`find_panel` sweeps seven colours over the whole frame, and calling it
just to decide whether to skip a read cost 33x what the read itself did
— 495ms a poll against 15. The caller already needs the answer for its
own "is the menu up" display, so it computes it once and hands it over;
a gate has to be cheaper than what it gates.

Level and department reads are both gated on a margin, not just a raw
score, and the margin is the dangerous one to skip: a live plate reading
"Level 8" was read as 6 at score 0.709, over a runner-up of 0.670. A
low score means the region holds nothing legible; a low margin means it
holds something legible that could equally be another digit.

> **Note, 2026-10-11.** The level is now read by a small classifier
> when its weights are present, with the template match described here
> as the fallback. Both gates still apply, on the same scales. The
> player can also type a level the reader refused. See
> [live-reading.md](live-reading.md#level-department-and-health).

The player's own naming is consulted BEFORE the catalogue match, not
after. Consulting the name only when nothing else identified the plate
meant a confident wrong answer from the catalogue (six heads of
thirty-two, happy to match a Number Cruncher against the Bean Counter it
has) could never be corrected — which is the exact case that was
reported and is why the order was flipped.

### _forget_names: debounced, and only drops what's actually gone

The first version cleared every hand-picked name whenever the plate
count changed, which sounds safe and destroyed the feature: `find_plates`
is a heuristic on teal pixels and drops a plate for a frame whenever a
cog is mid-animation or obscured, and the pick the player had just made
was gone with it — the same flicker that shows up as the panel briefly
reporting "1 cog plate" with two cogs on screen.

Now: a name for a plate that's no longer there is stale and goes; a name
for a plate that still exists is kept even if the count moved, because
the alternative is losing every pick to noise. The drop is also
debounced across `FORGET_AFTER_FRAMES` (5) frames, because acting on the
first missing frame meant a single dropout threw the pick away, which
is indistinguishable from the dropdown not working. Indices can still
shift onto the wrong cog when one dies, but that's visible in the
dropdown and correctable, where a silently discarded pick is not.

> **Note, 2026-10-11.** Two rules were added later. A frame with no
> plates at all forgets nothing: it means the reader cannot see, not
> that the cogs have gone, and the attack animation between rounds
> lasts longer than the debounce. And every mark is cleared when a
> fight ends or a new one starts, because marks are keyed on plate
> order and one set in an earlier fight otherwise landed on whatever
> stood in that position in the next.

### name_plate: writing the player's pick into the head library

A signature is consulted forever, so a wrong entry poisons every later
match, while a wrong name costs one battle — which was the reason not to
write player picks into the library by default. Writing was later
enabled on the maintainer's instruction, because `catalogue.add` overwrites
rather than accumulates and keeps the source crop in the catalogue
directory, so a mis-click can be seen and corrected, and a player naming
a cog they are looking at is better evidence than a signature match
against four known heads. The write is deferred to the next frame that
reads the slot, because `name_plate` is called from the UI thread with
no frame in hand.

### _locate: full-frame coordinates only

The first version returned band-relative plate slots and expected
callers to add the offset back. Every reader then sampled the full frame
with a box short by the band's top edge — silently, on the path that
runs for the whole of every battle. `_locate` now always returns
full-frame coordinates.
