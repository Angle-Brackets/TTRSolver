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
