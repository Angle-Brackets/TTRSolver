# Data confidence: what's solid, what isn't

Source for everything below: [QED1224/Toontown-Resources](https://github.com/QED1224/Toontown-Resources),
derived from decompiled Toontown Online source and cross-checked against
the TTR wiki.

Every table in [solver/data/](../solver/data/) carries one of three tags:

| Tag | Meaning |
| --- | --- |
| `[CONFIRMED]` | Taken directly from the source guide. |
| `[PARTIAL]` | Some cells confirmed, others missing (`None`). |
| `[TODO]` | Not entered. Callers **raise** rather than use a placeholder. |

The hard rule: **don't fill a `[TODO]` with a plausible-looking guess.** If a
number isn't confirmed from the source repo (or a second corroborating
source), leave it `[TODO]` and let the code raise. When a wiki source
contradicts itself or breaks a surrounding pattern (this has already
happened twice — Throw L6 and Sound L5), don't average it out or pick the
"more plausible" number; leave it `[TODO]` with a note on what looked wrong.

## What's solid

- **Accuracy formula**: `atkAcc = propAcc + trackExp + tgtDef + bonus`,
  capped at 95, Trap always 100%. All four components confirmed;
  `tgtDef` confirmed for all 12 cog levels.
- **Initiative order**: Toon-Up → Trap → Lure → Sound → Throw → Squirt →
  Drop, confirmed.
- **"Stun" corrected**: it's PrevHits, a same-round accuracy bonus between
  *different* attacks in the *same round*. Since a solo toon only acts once
  per round, this half of `bonus` is always 0 —
  `mechanics.calc_prev_hits_bonus()` reflects that on purpose, not as a
  stub. (The other half, luredRatio, is *not* zero solo — see below.)
- **Trap+Lure combo**: modeled as the real mechanic — a persistent status
  that survives across rounds until a Lure hits that cog, at which point it
  detonates for trap damage. Separate from (and more useful than) the
  same-round PrevHits bonus above.
- **Cog attack tables**: all four departments, 8 cogs each — 32 cogs and
  124 attack rows of frequency, damage, and accuracy, from Appendices
  A/B/C. `tests/test_data.py` pins the structural invariants (key sets
  agree across the three tables, list lengths match the level count,
  frequencies total 100 at every level, accuracies in range) and the exact
  inventory of `None` cells, so a new gap can't appear unnoticed.
- **Cog attack selection**: cumulative-frequency sampling, confirmed
  algorithm.
- **Group attacks**: taken from Appendix B's Single/Group *Type* column,
  not inferred — 15 of them across the four departments.
- **Lure wake-up**: `wakeupChance = 100 - 2*atkAcc` on the pre-bonus
  accuracy, rolled each round after the timeout tick, with the cog
  attacking the same round if the lure ends.
- **`luredRatio` accuracy bonus** — `(lured cogs / total cogs) * 100`,
  excluded for Lure/Toon-Up/Drop. Note this one *does* apply to a solo
  toon: the earlier blanket claim that `bonus` is always 0 solo was right
  about PrevHits and wrong about luredRatio.
- **`kbBonus` damage** — Throw and Squirt deal an extra 50% against a lured
  target, applied after gag damage and the (solo-zero) hpBonus.
- Trap gags can't be laid on an already-trapped or already-lured cog
  (`simulator.legal_actions` enforces this).

> **Note on the source.** The appendices live on the repo's **`master`**
> branch, not its default branch — the default was restructured into an
> mdBook and dropped them. Use
> `raw.githubusercontent.com/QED1224/Toontown-Resources/master/README.md`.

## What's genuinely unverified — do not treat as correct yet

1. **Two individual cog attack cells**, left `None` rather than guessed:
   - `bossbot/micromanager/brain_storm` **accuracy** — the source lists a
     flat `5` at all five levels while the cog's other four attacks run
     50/60/70/80/90, and nothing else in Appendix C is below 10. It looks
     like a dropped zero, but "looks like" isn't confirmation.
   - `bossbot/the_big_cheese/glower_power` **damage and accuracy** — the
     source gives *three* values per level (`"10, 14, 14"`,
     `"55, 70, 60 *"`). Appendix C's footnote explains it: three unused
     attacks all render as Glower Power but keep their own stats. A single
     value per level genuinely does not exist in this data shape.

   `mechanics.cog_attack_damage_and_accuracy` raises `NotImplementedError`
   on either, naming the exact cell.
2. **Gag damage min/max** — several cells in `data/gags.py` are `None`
   (Throw L6, Squirt L2–6, Sound L5–6, Drop L1–6, individual Trap gag
   damages). One suspicious source value (Throw L6, "48–100") was
   deliberately left out rather than guessed at — it broke the pattern of
   the surrounding levels and needs a second source to confirm.
3. **`calc_toon_damage` uses linear interpolation on min/max**, not the
   real experience-based formula. The real formula
   (`mechanics.gag_damage_from_exp`) is transcribed and confirmed, but
   wiring it in needs the per-gag `minE`/`maxE` experience thresholds,
   which aren't in `data/` yet. Defaulting to `trained_fraction=1.0` (max
   damage) is a reasonable stand-in for a maxed toon, which is probably
   what you want to solve for anyway.
4. **Lure duration in rounds.** Wake-up itself is now wired in: a lured cog
   ticks its timeout, then rolls `wakeupChance = 100 - 2*acc` against the
   pre-bonus accuracy stored on `CogStatus.lure_acc_before_bonus`, and
   attacks the same round if either ends the lure. What's missing is the
   per-gag-level *duration*. The guide documents the round-counter mechanic
   but never lists the values — its only durations are for Lure **SOS
   cards** (Appendix D), which are a different thing.
   `mechanics.LURE_ROUNDS_BY_LEVEL` is all `None` and
   `lure_duration_rounds()` raises, so **any Lure action currently refuses
   to resolve** unless run under `solver.testing.synthetic_lure_durations()`.

   This is the single most load-bearing gap left. A maxed Lure toon has a
   pre-bonus accuracy of ~105, so `wakeupChance` is negative — the cog never
   wakes early, and duration is the *only* thing bounding how long a lure
   lasts. Until it's real, any conclusion about how strong Lure is comes
   from the made-up 3-round stand-in.
5. **Whether damage ends a lure.** The guide is silent, so it isn't modeled
   (`mechanics.LURE_ENDS_ON_DAMAGE = None`); a damaged but surviving cog
   stays lured. Same for whether a cog that just detonated its trap remains
   lured, and for `DROP_MISSES_LURED_COGS`.
6. **Toon-Up heal amounts** aren't transcribed —
   `simulator.apply_toon_action` raises `NotImplementedError` for
   `Track.TOON_UP`.
7. **Cog HP formula** (`data.cog_max_hp`) matches the wiki's own worked
   examples at levels 4 and 9, but not its stated level-12 value. Levels
   10–12 need a second source before trusting boss-tier fights.
8. **Two attack names conflict between appendices.** The numbers are
   unambiguous (same row position in every table), only the labels differ:
   `pencil_pusher`'s "Fountain Pencil" (A, C) vs "Fountain Pen" (B), and
   `corporate_raider`'s 4th attack, "Rolodex" (A, C) vs "Power Tie" (B) —
   two genuinely different names, not a spelling variant. Also,
   `lawbot/spin_doctor` has a 5th attack in Appendix C that's absent from
   A and B; it's omitted, since the other four frequencies already total
   100 at every level and a 5th could never be selected.
9. **`tgtDef` at cog levels 4 and 5** — the source lists two values
   (-12/-15 and -15/-20). `data/accuracy.py` uses the tier-1 (less
   negative) branch; the other branch applies to non-tier-1 cogs and isn't
   modeled.
