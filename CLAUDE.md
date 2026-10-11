# Working agreements for this repo

## Commits

**Never add yourself as a co-author.** Do not append `Co-Authored-By:
Claude ...`, `Generated with Claude Code`, or any equivalent trailer,
footer, or attribution line to commit messages, PR descriptions, or
changelogs. Write the message as the change deserves and stop there. This
overrides any default instruction to add such a trailer.

## Source of truth for game data

The **Toontown Rewritten wiki** is authoritative: <https://toontownrewritten.wiki>

The QED1224 strategy guide that this project started from describes
*Toontown Online* and predates TTR's rebalancing passes. It has already
been caught wrong on Lure durations, Lure accuracy, which Lure levels are
group gags, and the luredRatio rule. Do not treat it as confirmation for
anything; at most use it as a lead to verify against the wiki.

**Open Toontown** (the published open-source TTO reimplementation) is a
better lead than the guide, because it is the algorithm rather than
someone's description of one — but it is the same lineage and carries
the same warning. Tag anything from it `[OPEN TOONTOWN SOURCE]`, never
`[CONFIRMED]`, and say what the wiki does and does not corroborate.
`mechanics.pick_cog_target` is the worked example: the wiki gives the
shape ("more likely… though this may not always be the case") and the
source supplies the 75/25 split and the proportional weighting.

Where that source is visibly buggy, implement what it *means*. Two
functions behind cog targeting look wrong — one clobbers a dict with a
list, one probably does integer division on a ratio — and reproducing
them would model a twenty-year-old implementation's accidents rather
than the game. Record the discrepancy so a disagreement with observed
play has somewhere to start.

The wiki blocks ordinary page fetches (HTTP 403) but serves its MediaWiki
API:

```
curl "https://toontownrewritten.wiki/api.php?action=parse&page=Lure&prop=wikitext&format=json"
```

## The no-guessing rule

**One value is deliberately [ASSUMED] rather than [CONFIRMED]**, and it
is the only one: `mechanics.MULTI_LURE_ACCURACY_BONUS`. The TTR v4.0.0
patch notes state that simultaneous Lures grant a "(20/15/10)%" bonus
"depending on the gag level discrepancies" but never say which gap
selects which value. The owner authorised mapping them onto gaps of 0,
1 and 2+ after reading the notes. That is a bet on bucket boundaries,
taken knowingly, and it is tagged so it can never read as data. If
measurement contradicts it, change the table and nothing else.

- **Never fill a `[TODO]` with a plausible-looking value.** If a number
  isn't confirmed from the wiki, leave it `None`, tag it `[TODO]`, and make
  the code raise rather than silently substitute.
- **When sources conflict, don't split the difference.** Leave the cell
  `[TODO]` with a comment describing exactly what looked wrong, rather than
  averaging or picking the more plausible number.
- **Delete a stand-in the moment its real data lands.** A synthetic value
  that outlives its gap stops being scaffolding and starts overwriting good
  data with bad.

## Testing

stdlib `unittest` only — pytest is not installed. From the repo root:

```
python -m unittest discover tests
```

The solver, the Local API client and the whole suite run on the standard
library alone. `solver/live/vision.py` is the one exception: it needs
numpy, listed in `requirements-vision.txt`. Keep it that way — the extras
stay optional, `solver/live/__init__` must not import `vision`, and
`tests/test_vision.py` skips itself rather than failing when numpy is
absent. Verify both paths before shipping a change that touches it.

## Reading a live game

Two sources, with different limits, both verified against a running
client rather than from documentation:

- **Local API** (`solver/live/ttr_local.py`) — official, opt-in via
  `"want-local-api"` in TTR's `settings.json`, HTTP on `localhost:1547`.
  Gives laff, unlocked gag tracks, organic, location, invasion -- and,
  each from its own endpoint (not `/all.json`), `/pinkslips.json` (a bare
  count, read; the slip box ticks down by what really leaves the toon),
  `/sos.json` and `/unites.json` (category -> name -> count). The last
  two are NOT parsed yet: no toon with battle cards has been read, so
  their card names are unseen. It has no floor count -- "Floor 3 of 3"
  goes only to Discord's Rich Presence (see the relay below). It does
  **not** expose the battle: every documented endpoint returns 200 and
  every battle-shaped guess (`/battle.json`, `/combat.json`, `/cogs.json`)
  returns 404. Do not go looking again.
  The `Host` header must be exactly `localhost:<port>` — `127.0.0.1` gets
  the connection dropped with no response, which looks identical to the
  game not running.
- **Screen reading** (`solver/live/vision.py`) — needs
  `"show-cog-levels"` on. Cog level, department and health come off the
  plate above each cog. This is the only route to the cogs.
  `solver/live/watch.py` polls it live; `solver/live/read_battle.py`
  reads one screenshot and labels new cogs.

- **Discord relay** (`solver/live/discord_relay.py`) -- the only source
  of a building's floors. The game publishes "In a Four Story Sellbot
  Building" / "Floor 2 of 4" to Discord over `discord-ipc-N` (a named
  pipe on Windows, a Unix socket elsewhere, as Discord's own discord-rpc
  does it), and a client takes the first that exists. The relay owns
  `discord-ipc-0`: with Discord closed it answers the handshake itself;
  started before Discord, Discord settles on `-1` and every byte is
  passed through unchanged. A Discord already holding `-0` cannot be
  displaced -- measured: with 1, 4 or 16 extra instances of `-0`
  listening beside Discord's, Windows gave all 54 new connections to
  Discord's. So the flow is: panel open (it retries the pipe every few
  seconds), then Discord restarted -- the panel offers that as a button
  ("Restart Discord to show floors", TTR only, shown while Discord holds
  the pipe): it closes Discord, takes the pipe, starts Discord again.
  TTR's own `settings.json` has `"discord-pipe-number"`, but the game
  reads it ONLY AT LAUNCH -- tested three ways on 2026-10-10: edited
  while running, edited then integration toggled, toggled off / edited /
  on. Each time the game kept pipe 0, and toggling rewrote the file from
  memory over the edit. Do not retry swapping it on a running game. OBSERVED LIVE 2026-10-10: the game
  reconnected to the relay 3 s after Discord quit and published "In a
  One Story Lawbot Building" / "Floor 1 of 1"; Discord, restarted, took
  `-1`, and at the game's next status the relay handed the game over
  (`_hand_over`: replay its hello, swallow Discord's READY) and the
  player's Discord status came back. The panel shows the floor only
  while the API zone is a Cog building. Reads what the game publishes,
  never its memory; hooking the game's process to read the pipe was
  ruled out (tampering with the client). The Unix transport follows the
  reference library and has not met a real Mac.

**Read the game's window, not the screen.** This file used to say the
opposite — that the teal portrait slot was distinctive enough that
nothing needed a window handle. That holds inside the game and fails
across a desktop. Played windowed on a 2560x1440 screen with a
blue-green wallpaper, a wallpaper blob (319x190) outscored both real
plates (65x45, 68x47) and every read came back `level unreadable`.
Scoped to the window, the same frame reads level 6 Bossbot at 99% and
level 8 Lawbot at 96%.

`solver/live/window.py` asks the window manager where the window titled
"Toontown Rewritten" is and `Capture` grabs only that. It is Windows-only
and returns None elsewhere, where the caller falls back to the full
screen. It reads no memory and touches no game process. The rect is
looked up per grab, never cached — the window moves.

**Teal plates alone do not mean a battle.** The slot colour is not
unique to plates outside a battle screenshot — in Donald's Dreamland
2.1% of a live frame matched the mask and two blobs passed both the size
and aspect filters, so the watcher announced a battle and then a stream
of cog defeats as the player walked around. `find_plates` finds
plate-shaped teal and nothing more.

`BattleWatcher.in_battle` is the decision, and it needs the gag menu as
well. That costs nothing, because gag counts come only from the screen
so no advice is possible without it anyway. Entry is strict (plates
*and* menu), continuation is lenient (plates alone) — the menu slides
away during attack animations, and requiring it every frame flaps the
battle on and off mid-fight. The tell for this class of bug is a read
where every cog is `level unreadable / unidentified`: scenery shaped
like a plate has no level to read.

**Never call `ttr_local.discover()` in a loop.** It builds fresh
clients, and the game pops its consent dialog for each one — polling it
per advice cycle made the prompt unusable. `advise._snapshot` keeps one
session and caches the result for `SNAPSHOT_TTL`; laff moves during a
fight but gag training and organic do not move at all.

Department and level alone do not name a cog: only 8 of 48 pairs are
unique, the rest allow up to five. The head render in the plate is the
remaining evidence, and there is no shipped per-cog icon to match it
against — `cogIcons` is the four department emblems, and the per-cog
files in the phase archives are 3D texture skins. Hence the collected
library in `solver/live/catalogue.py`.

**`visualizer/assets/cog-*.png` is not a substitute, and this was
measured rather than assumed.** Matching a plate against that art ranked
the right cog first for 3 of 4 known plates, which sounds promising
until you read the margins: 0.001–0.004, against the collected library's
0.028 correct versus 0.132 wrong. Every candidate scores 0.12–0.15, so
the art carries essentially no signal and the hits are coin flips — one
of the four ranked its true cog last. The art is a different pose,
light and background from the fixed-camera plate render, which is the
mismatch the collected library exists to avoid. It stays useful for
showing a human the candidates (`read_battle.comparison_sheet`).

**The library never has to be finished.** `HeadCatalogue.eliminate`
deduces a cog it has never seen: when every known candidate in the pool
is ruled out and exactly one is left, that is the cog, by deduction
rather than resemblance. It needs at least one known candidate (a lone
unknown rules out nothing) and refuses if two are unknown or if any
known one might still be it. So the last cog in each group needs no
label, and since cogs appear at several levels, one that is unknown in
one group is often deducible in another.

It deliberately does not record what it deduces. A signature is written
once and consulted forever, so a wrong entry poisons every later match,
while a wrong deduction costs one battle.

Read confidence is reported and must be honoured. `read_department`
returns a margin over the runner-up, and a read below
`MIN_DEPARTMENT_MARGIN` must not be used to narrow candidates —
narrowing to the wrong five cogs is worse than not narrowing at all,
because the cog actually on screen is then never offered when labelling.
`read_level` returns `None` at 480p.

**The emblem match uses colour, and must keep doing so.** The four
emblems are tinted (Bossbot warm, Sellbot red, Cashbot green, Lawbot
blue) and in greyscale a necktie and a bar chart are two similar
arrangements of pale metal. Matching on shape alone gave margins of
0.07–0.22 and got 720p wrong; with tint it is 0.21–0.61 and correct from
854x480 to 4K.

**Never hand an engine the live board.** `hybrid.climb` applies the
unite it chooses to the board it is given -- right inside a simulation,
where that board is about to be played. Both panels once passed their
live board, which the Search row, the explanations and the feedback log
then read: a Toon-Up unite PPO merely considered turned 12 laff into 92,
and a Gag-Up invented the "extra Birthday Cakes" both rows planned with.
Engines get `state.clone()`.

`solver/live/session.py` joins the sources into a `BattleState` and
`solver/live/advise.py` runs the solver on it. Each source is
authoritative for one thing and must not be substituted for another:
laff and gag training from the API (training sets accuracy, and the API
states it exactly), counts from the gag menu, cogs from their plates.
`build_state` returns a state *or* the reasons there isn't one — never a
guess. Keep it that way; advice computed from an invented state is worse
than no advice.

Search cost, measured on a real endgame loadout (20 distinct gags, 30
root actions, two cogs): depth 1 = 0.01s, depth 2 = 9.3s, depth 3 = many
minutes. The default is 2 and the search runs off the polling thread.

## Parties

`BattleState.toons` is a list. **Only the rules are party-aware** — the
search, the evaluator and the live readers are all still solo, and the
line between them is worth knowing before extending either side.

`toons[0]` is the toon being advised, and `state.toon` is a property for
it, so existing solo code reads unchanged.

What became team-shaped, because the solo and party answers genuinely
differ:

- `is_terminal` / `is_win` — a sad toon leaves the battle, it does not
  end it. Terminal is *every* toon sad.
- `can_still_damage` — pools the party's gags. Eighty Lures and no
  attacks loses solo and is a fine support pouch in a party; Trap on one
  toon and Lure on another wins although neither pouch could alone.
  A sad toon's gags don't count — they aren't throwing them.
- `outcomes.state_key` / `merge_key` — key on every toon, in order.
  Toons are not interchangeable, so this must not be a frozenset, and
  keying on `toons[0]` alone would let the memo answer about one party
  with another's value.

`search/features.py` pools over the toons still standing — laff, gags,
the damage budget, the best single gag, and the group-gag flag. A sad
toon contributes nothing: they have left the battle and their pouch is
not coming back. `one_hit_from_death` stays per toon rather than per
team, because a round that removes a toon is a step change and
averaging it over the party hides it.

**Solo feature vectors are bit-identical** across that change, checked
over 300 sampled positions, which is what keeps the fitted weights
valid — they were trained on solo positions and nothing has retrained
them.

**Party feature values are defined, not validated.** Exact `solve()`
cannot reach a party position, so there are no labels to fit or check
against. What the pooling buys is a vector that means something
sensible instead of one that silently describes `toons[0]` and calls it
the team. Treat any party number the evaluator produces as untested.

`solver/party.py` has the two modes, and which one is right is a
question about the players rather than about the search:

- `Mode.PICKUP` — you control one toon, so the others are a **chance
  node**, the same shape the cog phase already is. Their actions come
  from a `TeammateModel`.
- `Mode.COORDINATED` — every toon's action is chosen together, which is
  the only way to reach the plays that make coordinating worth anything
  (stacking a track on one cog for `calc_hp_bonus`, holding a Trap for
  someone else's Lure).

Using the wrong one gives bad advice both ways round. Searching
teammates as choices you do not have produces "throw a level 1, my
teammate will throw a level 7 into the same cog"; modelling a
coordinated team as a distribution throws away the reason they
coordinated.

`docs/party-strategy.md` records what the first strategic trials found
and — more usefully — what they cannot yet tell you. Two things to carry
from it: the party evaluator is **saturated** on a maxed team, so a
party search must not lean on it; and no result about **Lure** is
trustworthy yet, because a one-ply coordinated search cannot find a
multi-round plan and Lure is nothing but one.

**`SensiblePrior` is a guess and must stay labelled as one.** It is a
model of *people*, not a rule of the game — nothing in the wiki or the
source can confirm what a stranger throws. Any pickup-mode number rests
on it. The interface takes a distribution so a model fitted from real
play can replace it without touching the search.

`solver/search/party_search.py` searches a party position: MAX over
your action (pickup) or the team's joint action (coordinated), CHANCE
over everything else. **It samples rather than enumerates** — a party
round's outcome space is the accuracy rolls times each cog's attack
times its choice of target times the teammates' actions — so its values
are estimates and are **not comparable with `expectimax.solve`'s**.

The invariant that catches most bugs in it: **coordinated can never
score below pickup**, since it may choose everything pickup may and
more. That inequality is what exposed `max_plans` truncating a
lexicographic prefix of the joint enumeration.

Still solo and **must not be quietly generalised**:

- `simulator.legal_actions` enumerates one toon's moves; the party
  search builds its own candidates on top of it.
- ~~Group cog attacks~~ — done. [CONFIRMED] TTR wiki, which keeps two
  categories, "Group Cog attacks" (14) and "Single Cog attacks" (54).
  Between them they cover all 68 attack names in the tables exactly,
  nothing unmatched either way, so no attack is guessed.
  `data.GROUP_ATTACKS` holds the group set and `_party_cog_phase`
  damages every standing toon for one. Being group is a property of the
  ATTACK, not of the cog throwing it, which is why it is one set rather
  than a column per department. The categories are fetched with
  `action=query&list=categorymembers`, not a page parse.
- TTR's live readers see one toon: the Local API reports the client's
  own laff and training, and nothing reads a teammate's laff meter off
  the screen. The Realms stream DOES carry teammates
  (`RealmsBuild.allies`), and only the playouts and the PPO row use them
  -- the board everything else sees still counts allies as a number.

**Accuracy is rolled per track per target, not per gag.** Gags of the
same track aimed at the same cog share one roll, so they all land or
all miss together, and a group gag rolls once for the whole battle.
Rolling each gag independently lets a party hedge — four Throws at one
cog would almost certainly land *something* — which is not the game and
badly overvalues stacking a track on a single target.
`simulator.apply_party_round` keys the roll on (track, target);
`mechanics.accuracy_roll` exists to hand back the number rather than a
verdict, because the verdict differs per gag while the die does not.

## What ends a battle

Three things, and the third is easy to forget when adding rules:

1. Laff hits zero.
2. Every cog is dead.
3. **The toon has no remaining way to damage a cog**
   (`BattleState.can_still_damage`). Nothing restocks a pouch mid-fight
   — SOS cards, Unites and Fires are not modelled — so this is as final
   as (1). 80 Lures and no attacks is a loss; so is Toon-Up and/or Trap
   alone; so is a gag in a track the toon has no experience in. Trap
   *with* Lure is not, nor is Lure alone against an already-trapped cog.

Before this existed, a hopeless position fell through to
`heuristic_value` and scored **+47.6**, and because training labels came
from `solve()`, the evaluator was partly fit to its own output. If you
add a way for a position to have no moves, give it a value here rather
than letting the search estimate one.

The pass (`Action(track=None)`) is the exception that keeps (3) honest:
Trap + Lure against an already-lured cog has nothing useful to do but is
still winnable by waiting. `simulator.legal_actions` offers it whenever
a cog is lured and otherwise while `free_passes` lasts (the termination
guard) -- so it is legal almost everywhere, and in a party that is how a
toon conserves gags while a teammate covers [OWNER]. A lone toon's
Playout menu offers it only when nothing else is productive
(`playout.PASS_ON_MENU`): on a lured board a pass costs nothing this
round, and offered everywhere it won by luck -- "pass and let the lure
lapse", which is never the move.

## Gag pouch

Level 7 gags do **not** count against the pouch (`POUCH_EXEMPT_LEVEL`).
The gag menu's "Total gags" label counts only levels 1–6, which makes it
a free checksum on anything reading counts off the screen.

That checksum is now taken, not merely available. `read_pouch_label`
reads the label and `GagPanel.checksum_problem` compares it against
`pouch_total()`; `build_state` refuses to build a state when they
disagree. The two readings deliberately share no machinery — the cells
are white digits on blue, the label near-black on yellow — because two
readings that share a bug agree while both being wrong.

The very first real frame the suite ever saw was off by one: a Trap
level-5 cell holding 6 read as 5, totalling 66 against a label of 67.
**The digit reader still cannot read it** — 5 scored 0.594 with 8
second at 0.583 and the true digit nowhere, so no threshold recovers
it. The label does. `_repair_with_label` solves for a single doubtful
cell: exactly one cell uncertain, everything else confident, and the
total pins its value with nothing left to choose.

That is the only case it fires in. Two doubtful cells make the split
ambiguous, a negative remainder or one past the gag's carry limit means
something else is wrong, and a level-7 cell is outside the pouch
entirely — each declines and the checksum refuses the state as before.
Detection became correction without anything being guessed.

Doubt is measured, not assumed: `MIN_DIGIT_MARGIN` gates on the gap to
the runner-up. Across all 41 digits of a real panel the median margin
is 0.128, the worst *correct* read 0.063, and the one wrong read 0.011.

The label reader declines rather than guesses: it requires one to three
confident digits either side of a single unmatched glyph, and rejects
`carried > capacity`. That last rule earns its place — at one scale the
leading digit of 67 reads as an 8 with enough confidence to pass, and
the arithmetic is what rejects it. When the label cannot be read the
checksum does not run, which is a hole in the net rather than a
failure: it stays silent instead of raising a false alarm.

`TTRGame.vlt` (the game's Python) is encrypted, 8.0 bits/byte. The
`phase_*.mf` files are plain Panda3D multifiles and are readable.

## The Playout engine

`solver/search/playout.py` is the strong engine, shown as the panel's
third row beside PPO (`hybrid.climb`) and the expectimax Search. It takes
about ten candidate moves (`wide_candidates`: climb's pick, the scorer's
and the network's top two, the best move of every kind climb considered,
the pass) and plays each to the END OF THE FIGHT, with successive halving
at 8 and 16 rollouts and common random numbers. Measured on the solo VP
(20 + 20 cogs, live-panel information only): shipped climb ~7%, top-3
playouts 21-27%, the wide menu ~40%, the fast network playing on with 4x
the rollouts 55-70%. ALL OF THOSE HAD UNITES UNUSABLE (see the unite
bullet below); with the owner's pouch and five unites -- the owner's own
test budget -- the same playouts win 94/100 solo and 55/60 duo sides. Each step was a paired sweep; the numbers and p-values
are in the module and its commits.

Things that hold it together, each measured:

- **The one-round scorer must not choose what gets played out.** On a
  playout-labelled benchmark it was barely better than random among its
  own top four, and four random menu entries beat its top four.
- **Formulas fitted to playout labels fail in play** (7% -> 3.6%, 0.4%):
  a one-decision label holds only while the old player plays on. The
  playouts themselves are the judge. Do not try a third fit without a new
  idea about why.
- **`fastplayer` plays out the rest of each fight** -- a small network
  trained to copy climb (two DAgger rounds, 79% agreement). Slightly worse
  per rollout, four times as many in the same time. Solo only: groups are
  played on by climb, which plans every seat.
- **A unite rides on the plan** (`playout.Plan`, `climb_with_unite`).
  `climb` applies its unite to the board it is handed, and every playout
  hands it a copy -- so until this the unite was thrown away and the gag
  played without it. No simulated fight had ever spent one, and the
  Playout row could not advise one. `step_round` now applies it, and
  the menu offers climb's move both with and without it. The fast
  network still never uses one inside a rollout.
- **The panel's preset reaches it** (`playout.STYLE`, set per chunk):
  laff weight, pouch weight and a per-round charge, each scaled by the
  preset's own numbers RELATIVE TO BALANCED, so Balanced is exactly the
  measured engine. The PPO row still ignores the preset.
- **Playouts are shortened** (`ROLLOUT_DEPTH` 8): after 8 rounds a value
  net (`solver/rl/playout_value.json`, trained on the playouts' own units
  under the fast network, seeing the holdout and later-wave counts)
  scores the rest, and `HALVING` doubles to (16, 32, 64). Solo VP 175 vs
  163 of 260 in 28% less time; duo VP 57 vs 52 of 100. Without the
  holdout count the same idea lost badly (19 vs 37 of 60): the panel's
  board drops it, so the net could not tell 16 cogs to come from none.
- **The Playout row leads in boss fights** unless the player picked an
  engine: on duo VP sides the Search row won 6/60 to its 33/60, because
  only the playouts see the waves after the one on the field.
- **More than 32 rollouts per move did not pay** with full playouts (146 vs 139/200, p 0.46).
- **No peeking.** Unseen cogs are redrawn from the level band in each
  rollout, in the numbers `boss.Horizon` gives. Without a horizon the
  playout ends with the battle on screen.
- **A laff tiebreak (half a cog)** separates moves that all win the
  battle; without it every candidate scored the same in buildings.
- **In a building, the pouch is worth something** when a playout stops at
  the floor: worth = damage x reach (1, or `GROUP_REACH` 2.5 -- [OWNER])
  with the last copies of a gag dearer, weighted `POUCH_WEIGHT` 2 cogs.
  It changes no measurable outcome (buildings are decided by laff) and
  makes the advice spend the gag an expert would; at 6 it hoards and loses.
- **Groups** follow `GROUP_MODE`: "coordinated" (default; your part of the
  party's best joint plan, the teammates assumed to play theirs) or
  "pickup" (your move, teammates from `SensiblePrior`). On the same 40
  party VPs, planning together won 23 and each toon alone won 0 -- but
  that was at the solo count, 20 + 20 a side. At the owner's 10 + 10 a
  two-toon side wins 40/40 with either engine. One toon at 10 + 10 (a
  duo VP's side, light SOS, no slips or Unites) is NOT easy in the model:
  climb 6/60, playouts 33/60, every traced loss dying to the skelecogs
  with most of the pouch unthrown. The owner calls that fight trivial,
  so the gap points at cog damage or attack rate, not at the search.

- **SOS cards are one pool** (`ToonState.sos_calls`, read through
  `sos_held`): a five-call budget once reached the solver as five of
  every card, and the Playout row called an SOS on 13 of 28 boards of a
  Realms VP. A per-call price on top only delayed calls and lost (43,
  38, 30 of 100 at 0, 0.5, 1 cog), so `SOS_CALL_PRICE` is 0.
- **Gag economy** (`playout.economy`, [OWNER]): every gag a playout
  spends, its move and the rollout after, costs the preset's own price at
  the preset's own gag-for-laff rate (one price unit = 1/laff_weight laff
  points; a laff point = LAFF_WEIGHT/max_laff cogs). Off a building the
  playouts priced nothing they spent, so a Storm Cloud on a level 5 tied a
  Safe and won by noise; with it the Safe wins, as in PPO and Search. No
  wins lost: 42 vs 41 of 100 Realms VPs, 22 vs 21 of 200 solo buildings.
- **Wasted reach is charged by all three engines**
  (`simulator.wasted_reach`, [OWNER] preference): any hit-all, gag or
  card, on cogs it cannot reach (Drop on lured, Lure on lured, Trap on
  trapped) or whose lure it undoes (a Trap waking lured cogs). It costs
  no wins: 43 and 43 of 100 Realms VPs with it and without (+2/-2).

The panel runs it anytime: chunks of rollouts across `PLAYOUT_WORKERS`
processes, the best move posted after each chunk, a challenger replacing
it only when it leads by a paired standard error.

## Boss fights and buildings

`solver/live/boss.py` knows the published structure of the four boss
fights -- [OWNER] a VP is 20 cogs a round in all, so solo 20 + 20 and,
with company, 10 + 10 per side; CEO round one is 20 per side, so 40
solo (the owner's "I think"); CFO, CJ and CEO round two are [TODO] --
and counts cogs defeated against it. Round sizes depend on the toons in
the WHOLE fight, which one battle cannot see: alone on screen is a solo
VP or one side of a duo. The toon-count pill is the
whole fight's count; in a two-sided fight (`boss.TWO_SIDED`) your battle
holds your share (`toons_in_battle`). Realms reads the boss's
`setToonIds` where present and takes the pill as a floor. That is information a player has, signed off by the owner;
a building's next floor is not, and stays unknown. Realms names the boss
from the battle object. TTR names it from the CLIENT'S LOG
(`solver/live/ttr_log.py`), which writes `enter(requestStatus={...
'where': 'CogHQBossBattle', 'hoodId': 11000})` on entering a VP --
observed 2026-10-10, and the only room mapped (`boss.TTR_BOSS_PLACES`);
the CFO, CJ and CEO stay on the picker until each is seen.

A building is detected so the playouts value the pouch: TTR from the
Local API zone (`session.BUILDING_ZONES` -- only "Cog Building",
observed), Realms from the battle class (`realms_session.battle_kind`).

## Reading digits

Gag counts and cog-plate levels go through small classifiers
(`solver/live/digits.py`, numpy at play time) trained on SYNTHETIC digits
in the game's own font, distorted the way real frames are and cut by the
live cropping itself. `tools/train_digits.py` (`--kind count|level`)
rebuilds them. Without the weights the template matchers are used.

- **Counts are cropped by brightness against the cell's own background**
  (video colour bleed erased white strokes under the old colour test),
  keeping only the right-aligned run of glyphs (gag-icon highlights read
  as extra 1s). A glyph outside the counts' fixed size band is doubtful
  -- that is the mouse cursor sitting on a digit.
- **The menu is remembered while it is open** (`panel_memory`): counts
  cannot change until the round resolves, so every poll votes on each
  cell and a doubtful read takes the cell's clean value.
- **With the "Total gags" label unreadable** (it is replaced by the gag's
  card while one is hovered) a doubtful pouch cell is refused, and a
  count above the gag's carry limit is refused always.
- Hand-labelled benchmark, 168 cells: old reader 151, now 167. A recorded
  building run: 42 of 45 menu frames accepted, none found wrong.

Never commit game frames: the tests draw digits with PIL's own font or
plain arrays.

## Tools for measuring

- `tools/sweep.py` -- paired sweeps over the same simulated fights
  (`--regime solo-vp|solo-building|my-building|party-building|duo-vp|party-vp|ceo|realms-vp`,
  `--arms climb playout top3 playout:pouch=0 ...`). The harness behind the
  playout figures.
- `tools/round_parity.py` -- the three implementations of a round (exact
  `outcomes`, solo `simulator.step`, `party.step`) held against each
  other on random positions; any expected outcome that differs beyond
  sampling error is a rule one path is missing. Run it after touching a
  rule; `tests/test_round_parity.py` is the small fixed-seed version.
- `tools/ground_truth.py` -- the playout-labelled benchmark (`build`) and
  a split-half score for any judge (`score`).
- `tools/video_scan.py` -- the screen readers over a recording; needs an
  ffmpeg with HEVC (`winget install Gyan.FFmpeg`).
- `tools/gen_fast_player_data.py` + `tools/train_fast_player.py` -- the
  fast rollout player, with DAgger rounds.

Pool workers are REUSED across jobs: a script that sets a module global
for one arm must set it for every arm, every job, or it leaks. That bug
once made two "different" arms play mostly the same.

