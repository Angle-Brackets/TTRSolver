# Toontown Realms as a harness (not as a source)

Realms — what Toontown Offline became — runs a **full local Astron
cluster** on the player's own machine. That makes every field the live
readers currently guess at available as a typed value, and it makes the
game scriptable. It also makes it a *different game*, and the two facts
have to be kept apart.

## What it exposes

    MD (message director)   TCP 127.0.0.1:7199
    client agent            TCP 0.0.0.0:7198
    event logger            UDP 127.0.0.1:7197
    astron/dclass/ttoff.dc  165KB plaintext, 412 dclasses, 79 structs

Subscribing to the MD is how every AI and UberDOG process in an Astron
cluster attaches. It is the designed extension point, not a way around
one, and it is local and offline.

`DistributedSuitBase` publishes `setDNAString` (the cog's identity, no
head matching), `setLevelDist`, `setHP`/`setMaxHP`, `setSkelecog` and
`setSkeleRevives` — all `required broadcast ram`. `DistributedBattleBase`
publishes `setMembers` (toon ids *and* suit ids), `setState` and
`setChosenToonAttacks`. `DistributedToon` publishes `setHp` as
`broadcast`, so every toon's laff is visible, and `setInventory`,
`setTrackAccess` and `setTrackBonusLevel` as `ownrecv`.

That is the whole `build_state` input set, exactly, with none of
`vision.py`'s thresholds in the path.

## Why it must not feed the tables

Realms is Toontown *Online* lineage — the same family this project
already distrusts the QED1224 guide and Open Toontown for. Anything read
from it is `[OPEN TOONTOWN SOURCE]` strength at best and **never**
`[CONFIRMED]`. `resources/default/ttrm_dat_01.pak` holds its cog
definitions; they are a lead, not data.

## The differences, measured rather than assumed

The owner reports Realms caps cogs at level 12, gives a level 12 **200
HP**, and limits TNT to a carry of **2**. Against our TTR tables:

| | TTR | Realms |
|---|---|---|
| level 12 HP | 196 | 200 |
| TNT carry limit | 3 | 2 |
| highest cog level | 14 (CEO) | 12 |

**Four HP is 2%, and it flips exactly two one-shot verdicts.** Across
every gag at max training, only these disagree about killing a level 12:

    organic TNT          198  kills a TTR 12, not a Realms 12
    organic Grand Piano  196  kills a TTR 12, not a Realms 12

**And the mechanism is named.** `cog_max_hp` records that before TTR
3.0.0 (2021-12-03) a level 12 got a flat 10% boost to exactly **200**,
and that the patch replaced it with the `+14` term, making it 196.
Realms' 200 is not an arbitrary divergence — it is pre-3.0.0 Toontown,
frozen. That is the cleanest possible illustration of why this source
cannot feed the tables: it is not wrong, it is *old*, and the places it
is old are precisely the places TTR chose to rebalance.

TNT is the worked example, and the organic case is the one that counts:
a maxed toon with organic Trap throws TNT for **198**, which kills a TTR
12 (196) and fails on a Realms 12 (200). Non-organic TNT is 180 and
kills neither, so whether the owner's observation is a divergence
depends entirely on whether the Trap track is organic — and on the
owner's own toon it is. Railroad (200) kills in both.

That is the shape of the risk and why "the differences are small" is the
wrong way to think about it. The magnitudes are small; the *decisions*
are binary. A one-shot verdict is exactly what the Trap-plus-Lure line
pivots on, and a policy that learned "organic TNT does not finish a 12,
so set up a second gag" would carry that into TTR, where one gag does.

The missing levels matter in one specific place: the **CEO uses level
14** (254 HP), so no Realms position can exercise boss play at all.
For streets and buildings, 12 is the ceiling anyway.

## The rule this implies

  * **Reading pipeline — yes.** Whether `build_state` turns a `setHP`
    into the right `CogState.hp` does not depend on whether a 12 has 196
    or 200. Realms is ground truth for the plumbing, and better ground
    truth than a screenshot will ever be.
  * **Rules, training, benchmarking — no.** Nothing measured in Realms
    may be written into `solver/data/`, used to fit weights, or used to
    score a policy. The shipped policies were trained against our TTR
    tables and nothing here changes them.

## The panel

    python -m solver.live.realms_panel
    python -m solver.live.realms_panel --objective survive --budget 8

A **second panel**, not a mode of the first. `overlay.Worker` polls a
screen capture, runs `find_plates`, reads a gag menu and hedges every
number with a confidence; none of that applies when the server hands
over typed fields. Threading a second world through it would put
`if realms:` across the one module whose whole job is being careful
about pixels, and the TTR panel could then break from an edit made for
a game it does not read. `tests/test_realms_panel.py` greps
`overlay.py`, `panel.py` and `session.py` for the word and fails if it
ever appears.

`Model`, `CogRow` and `model_json` ARE shared, and that is a different
thing: they describe what a panel shows rather than how it reads, both
panels showing the same thing is the point, and the built React app
renders this one with no changes at all.

What the player sees differently, all of it because the data is better:

  * **cog names are never "?"** and the picker never appears -- identity
    is `setDNAString`, so there is nothing to guess at
  * **health is exact.** The TTR panel shows a fraction read off a green
    bar; this shows 9/12 because the server said 9/12
  * **LURED is read** from the battle roster, not marked by hand
  * **party size is read** from `setMembers`, not asked for

`name_cog` and `mark_lured` are deliberately **absent** from
`RealmsApi` rather than stubbed. They exist on the TTR side so a player
can supply what the readers could not see; here the server states both,
and offering them would invite overriding correct data with a guess.
`set_toon_count` exists but does nothing, because the shared page has a
button for it and the click has to land somewhere.

The search runs when the POSITION changes -- laff, each cog's health and
lure, the pouch, the party size -- and deliberately not on the battle's
state string, which cycles several times a round and would restart the
search mid-think.

## The wire protocol, as established

Every line here was settled by observation against a running cluster,
because reasoning about Astron's numbering got it wrong twice.

**Message types.** `[CONFIRMED]` means it delivered something that
decoded to a real class or field on a live capture:

| | | |
|---|---|---|
| 2014 / 2015 | `GET_ALL` / `_RESP` | [CONFIRMED] |
| 2020 / 2021 | `SET_FIELD` / `SET_FIELDS` | [CONFIRMED] |
| 2042 / 2043 | `ENTER_LOCATION_WITH_REQUIRED[_OTHER]` | [CONFIRMED] |
| 2052 | `ENTER_AI_WITH_REQUIRED` | [CONFIRMED] |
| 2040, 2046 | **not** enter messages — see below | disproven |

**A SET_FIELD does not name a class.** The object gets tagged with the
class the FIELD was declared on, which is a BASE of the real one. That
is why cogs appeared and battles and toons did not: street cogs spam
`setPathPosition`, so they were tagged `DistributedSuitBase` and
matched; a battle's `setState` fires only at phase changes and a
toon's position updates are declared on `DistributedSmoothNode`, so
both objects existed only in the ENTER messages that were being
dropped. **The ENTER path is not an optimisation, it is the only
reliable source of an object's class.**

**2040 and 2046 arrive exactly once per object** and are still not
enter messages. That ratio is why they were suspected; parsing them
that way delivered ZERO objects across a whole fight, every dclass id
refusing to resolve. They are almost certainly `SET_LOCATION` and a
`GET_LOCATION` reply. What made the wrong guess safe was making
`_enter` decline an unresolvable class in the same change — without it
the store would have filled with objects named `<60000>` and a bad
guess would have looked like a discovery.

**panda3d's DC accessors disagree with each other.**
`getFieldByIndex` returns None for a bad index; `getClass` fails a C++
assertion. The second killed the reader thread from one malformed
datagram. Bounds are checked in `DCIndex.dclass`, and `feed` catches
broadly — one bad datagram must cost one datagram.

**A group Lure has no target.** `setChosenToonAttacks` names its target
as an index into the suit roster, and a group Lure's is a sentinel
rather than a slot, so keying only on the slot recorded nothing — and
the reader then refused a cog it had watched being lured, blaming a
Lure thrown "before it attached". The last Lure in a battle is
remembered battle-wide as a fallback.

**Ask sparingly.** `refresh_all` over 137 objects at every poll put
several hundred `GET_ALL` queries a second through the message
director and 6,000 replies through one fight, most of them
re-describing a butterfly that had not moved. The battle roster is
cheap and worth refreshing often; the full sweep is not.

## Verified end to end

A live street fight, read with nothing on screen:

    Mover & Shaker L9 110/110 LURED
    -> Birthday Cake on cog 1

Which cross-checks three ways against tables Realms never touched: our
`COG_HP_BY_LEVEL[9]` is 110 and the server said 110; the toon's organic
Throw makes Birthday Cake 110 damage; and the cog being lured forces
accuracy and adds knockback. An exact kill, chosen for reasons that can
be checked by hand.

## Consumable holdings, read from a live client

Captured from a running Realms client (toon #100000001, 100 laff), which
settles a question this project had been answering by assumption: the
overlay CAN know what the player is carrying.

    setPinkSlips          0
    setResistanceMessages [[0,998],[1,999],[2,999],[3,999],[4,998],
                           [100,999]...[107,999],
                           [200,999]...[203,998],
                           [300,998]...[304,998]]
    setNPCFriendsDict     [(4125,100),(2003,100),(1116,100),(2311,100),
                           (4119,99),(4219,100),(4115,100),(3112,100),
                           (1323,100),(2308,100),(2011,100),(2001,100),
                           (2132,100),(2121,100),(5124,100),(4230,100)]
    setMaxNPCFriends      16

All three are `required ownrecv db` -- the same keywords as
`setInventory`, which the reader already decodes -- so they arrive by
the same route.

**The toon is invisible until it re-generates.** The stream carries only
changes and the player's toon is generated at login, before the listener
attaches, so `toons()` reads zero however long it waits. A zone change
regenerates it; walking through a tunnel is enough. This cost an hour of
looking for a subscription bug that was not there.

### SOS cards resolve exactly

`setNPCFriendsDict` is (npc id, count), and
`phase_3/data/npctoons.json` inside `ttrm_dat_01.pak` names all 712
NPCs. All 16 ids the live toon held resolve, and all 16 are in
`sos.BY_NAME`: Flippy, Moe Zart, Lil Oldman, Clerk Clara, Professor
Pete, Barnacle Bessie, Franz Neckvein, Sid Sonata, Barbara Seville,
Stinky Ned, Nancy Gas, Daffy Don, Madam Chuckle, Melody Wavers, Soggy
Bottom, Julius Wheezer.

The table is read from the install at runtime, never vendored, and lives
in `solver/live/realms.py` -- the reader decoding an id, the same job
`parse_inventory` does for a pouch. It does not go in `solver/data/`.

### Unites are counted, NOT categorised

Ids group as `category * 100 + index`: 0-4, 100-107, 200-203, 300-304.
It is tempting to read category 0 as Toon-Up because it has five entries
and `TOON_UP_VALUES` has five, and category 1 as Gag-Up because eight is
seven tracks plus all-tracks.

**Nothing in the install confirms it.** The only "resistance" files in
the archives are three particle effects. So `parse_resistance` returns
the TOTAL and nothing finer, and the cost is stated rather than hidden:
`unites_held` is one number, so a toon holding only Toon-Up unites is
still offered a Gag-Up. Fixing that needs the category table, not more
inference.

### The caps

`max_fires`, `max_unites` and `max_sos` are all the same contract: the
wire says what is HELD, the cap says what the player will SPEND, and
**neither alone grants anything**. A cap with no reading would invent a
pouch; a reading with no cap would spend a resource farmed from boss
runs without being asked. All three default to 0.

The counts in this capture (998/999 per unite, 100 per card) are a
maxed-out sandbox toon on an offline build, not typical play. They show
the FORMAT, and nothing about what a real player carries.
