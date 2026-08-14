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
  Gives laff, unlocked gag tracks, organic, location, invasion. It does
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

Still solo and **must not be quietly generalised**:

- `simulator.legal_actions` enumerates one toon's moves.
- The live readers see one toon: the Local API reports the client's own
  laff and training, and nothing reads a teammate's laff meter off the
  screen.

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
still winnable by waiting. It is deliberately offered *only* when a cog
is lured and nothing else is productive — widening it breaks both
shallow play and the termination argument. `simulator.legal_actions`
explains why; don't widen it without reading that.

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
