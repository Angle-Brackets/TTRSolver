# Data confidence: what's solid, what isn't

## Source of truth: the TTR wiki

**<https://toontownrewritten.wiki> is authoritative.** The
[QED1224/Toontown-Resources](https://github.com/QED1224/Toontown-Resources)
strategy guide this project started from documents *Toontown Online* and
predates TTR's 3.0.0 / 4.0.0 / 4.3.3 rebalancing passes.

The wiki 403s ordinary page fetches but serves its MediaWiki API:

```
curl -sSL "https://toontownrewritten.wiki/api.php?action=parse&page=Lure&prop=wikitext&format=json"
```

Every table below has now been audited against it. The guide's record was
mixed in an informative way: **cog damage was 114/122 correct, gag damage
12/14, and the accuracy formula almost entirely correct — but Lure was
wrong in nearly every particular.** The lesson isn't "the guide is
garbage", it's that TTR's rebalances hit some systems hard and left others
untouched, and you cannot tell which from the inside.

| Tag | Meaning |
| --- | --- |
| `[CONFIRMED]` | Verified against the wiki. |
| `[UNVERIFIED — GUIDE-DERIVED]` | Guide value, wiki publishes nothing. Not a gap you can close by looking harder. |
| `[TODO]` / `None` | Not entered. Callers **raise** rather than use a placeholder. |

The hard rules, in [CLAUDE.md](../CLAUDE.md): never guess a value, never
split the difference when sources conflict, and delete a synthetic stand-in
the moment its real data lands.

## The biggest limitation: cog frequency and accuracy are unknowable from public sources

**The wiki does not publish cog attack frequency or accuracy anywhere.**
The `Cog attack` page defines both concepts and gives no numbers; the
`CogAttackTable` template carries only Attack / Target / Level / Damage; no
cog page, attack page, or `insource:` search turns up either field.

Worse, both are known to have changed. TTR 4.0.0 "Under New Management":

> "All Cog Attacks across all Cog departments have been rebalanced…"
> "Tweaked numerous **accuracy** values…" "Tweaked numerous **frequency**
> values across all Cogs that have their attack pool updated."

So the frequency and accuracy tables in `data/*.py` are pre-rebalance
values for a game that has since rebalanced them, with no published
replacement. Eight cogs whose attack pool demonstrably changed are tagged
`[FREQ STALE]` — their frequencies distribute 100% across the wrong set of
attacks.

**This bounds what the solver can honestly claim.** Its relative judgements
(group gags against three cogs, taking a lethal hit) rest on damage and HP,
which are solid. Its absolute numbers — win rates, expected laff loss —
inherit this error. If TTR frequencies ever surface, the rebalancing PDFs
at `cdn.toontownrewritten.com` are the likeliest place.

## What's solid

- **Accuracy formula**: `atkAcc = propAcc + trackExp + tgtDef + bonus`.
  All four components confirmed, plus the 5% floor.
- **propAcc**: confirmed for all seven tracks. Only Lure and Toon-Up vary
  by level — the wiki states this outright, so the flat rows for
  Throw/Squirt/Sound/Drop are correct, not lazy transcription.
- **tgtDef**: confirmed for levels 1–12 and 20, *keyed on cog rank as well
  as level*. Rank is the cog's position on its department ladder, which
  equals the lowest level it appears at (`levels[0]`) for all 32 cogs.
- **Cog HP**: `(x+1)(x+2)` for levels 1–11, `+14` from level 12 up, matching
  all 20 published rows. The old single formula was right through 11 and
  wrong above it (182 vs TTR's 196 at level 12).
- **Cog damage, targeting, rosters, level ranges**: wiki-verified for all
  32 cogs, cross-checked between each cog's page and each attack's page.
- **Gag damage and heals**: all 35 damage cells filled, plus Toon-Up heals,
  organic damage, and per-track organic bonus percentages.
- **Lure**, wholesale: durations 2/2/3/3/4/4/8, base and organic accuracy,
  and group levels 2/4/6/7.
- **Lure no longer expires early.** 3.3.0 removed early expiry below 50%
  base accuracy, and the lowest gag is 55% — so a lure runs its full
  duration. The `wakeupChance` machinery survives behind
  `mechanics.lure_can_expire_early`, since the threshold is a balance knob.
- **Lured cogs**: Throw/Squirt are guaranteed hits and get the 50%
  `kbBonus`; Drop always misses; Sound wakes them without a bonus.
- **`luredRatio`**: `(lured / total) * 100`, to all Sound gags and level-7
  Throw/Squirt only. It *does* apply to a solo toon — the old blanket claim
  that `bonus` is always 0 solo was right about PrevHits, wrong about this.
- **Toon-Up misses still heal** 20% of value, rounded up. The only track
  where a miss isn't a no-op.
- **Initiative order**: Toon-Up → Trap → Lure → Sound → Throw → Squirt →
  Drop.

## What's genuinely unverified

1. **Cog attack frequency and accuracy** — see above. The largest gap in
   the project, and not closable from the wiki.
2. **Twelve 4.0.0 cog attacks are not modeled.** Their damage and targeting
   are wiki-confirmed and parked in an `"unmodeled_attacks"` key, but with
   no frequency there's no way to fold them into the sampling table. **The
   simulator therefore under-estimates all eight affected cogs**, and nine
   of the twelve are group attacks. Pinned by
   `tests/test_data.py::test_unmodeled_attack_inventory_is_pinned`.
3. **`lawbot/big_wig/finger_wag` damage** — the wiki contradicts itself. The
   Big Wig page says `9,11,13,16,18`; `/Finger_Wag` says `13,15,17,19,21`.
   They share an identical tail (20,22,25), so one page was refreshed in a
   rebalance and the other wasn't; the `/Finger_Wag` row is also
   non-monotonic across the seam, which no other damage row is. Left `None`,
   so Big Wig raises roughly half the time it attacks.
4. **`sellbot/the_mingler/power_trip` is probably not real.** The wiki's
   Mingler roster has four attacks and `/Power_Trip` doesn't list this cog.
   Kept anyway, tagged `[STALE]`: removing it would strand 15% frequency,
   and the sampler's fall-through would silently dump that onto whichever
   attack happens to be first in the dict. Treat its damage as fiction.
5. **Two gag cells, on genuine three-way source conflicts**: Trapdoor
   organic damage (83–94 vs 84–94 vs 83–93) and Lipstick minimum heal
   (25 vs 27).
6. **The 95% cap is soft since 4.3.3** — bonuses "can slightly push the
   final accuracy value higher" — but the wiki never quantifies it or gives
   a replacement ceiling. Modeled as the pre-4.3.3 hard cap, flagged by
   `data.ACCURACY_CAP_IS_SOFT`.
7. **`calc_toon_damage` interpolates min/max** rather than using the real
   experience-based formula. `mechanics.gag_damage_from_exp` is transcribed
   and correct but needs per-gag `minE`/`maxE` thresholds; the gag
   infoboxes' `prevexp`/`nextexp` fields look like the right source but
   haven't been chased.
8. **Cogs can appear three levels above their normal range** (an 8-level
   span, damage published for all 8). Not modeled, and largely moot: the
   upper levels have no frequency or accuracy from either source.
9. **Re-luring does not refresh a lure's duration** — an already-lured cog
   is untouchable by Lure until its rounds run out, neither stacking nor
   refreshing. Modeled, but from play knowledge: the wiki only documents
   3.0.0 removing *simultaneous* stacking and is silent on re-luring across
   rounds.
10. **Whether Throw/Squirt damage ends a lure.** The wiki names Sound
   explicitly, which is modeled. It's silent on knockback, so that isn't
   (`mechanics.LURE_ENDS_ON_DAMAGE = None`). Same for a cog that just
   detonated its trap.
