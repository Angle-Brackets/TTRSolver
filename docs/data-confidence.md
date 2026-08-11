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
  per round, this bonus is always 0 — `mechanics.calc_bonus()` reflects
  that on purpose, not as a stub.
- **Trap+Lure combo**: modeled as the real mechanic — a persistent status
  that survives across rounds until a Lure hits that cog, at which point it
  detonates for trap damage. Separate from (and more useful than) the
  same-round PrevHits bonus above.
- **Cog attack selection**: cumulative-frequency sampling, confirmed
  algorithm. Bossbot frequency + damage tables filled in for Flunky, Pencil
  Pusher, and Yesman.
- Trap gags can't be laid on an already-trapped or already-lured cog
  (`simulator.legal_actions` enforces this).

## What's genuinely unverified — do not treat as correct yet

1. **Bossbot cog attack accuracy** (Appendix C) — not captured.
   `data/bossbot.py`'s `"accuracy"` is `None` for every cog, and
   `mechanics.cog_attack_damage_and_accuracy` raises `NotImplementedError`
   until it's filled in. Re-fetch the source repo's README and pull the
   Bossbot section of Appendix C.
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
4. **Lure wake-up isn't wired into the round loop.**
   `mechanics.lure_wakeup_chance()` is confirmed and implemented, but
   `simulator._resolve_cog_phase` currently treats any lured cog as simply
   skipping its attack every round, with no wake-up roll. The missing piece
   is storing the *pre-bonus* accuracy the Lure hit with (needed as
   `lure_wakeup_chance`'s input) on `CogStatus` at the moment Lure is
   applied — straightforward to add, just not done yet.
5. **Toon-Up heal amounts** aren't transcribed —
   `simulator._resolve_toon_action` raises `NotImplementedError` for
   `Track.TOON_UP`.
6. **Cog HP formula** (`data.cog_max_hp`) matches the wiki's own worked
   examples at levels 4 and 9, but not its stated level-12 value. Levels
   10–12 need a second source before trusting boss-tier fights.
7. **Sellbot / Cashbot / Lawbot** cog tables aren't transcribed at all —
   only Bossbot, and only 3 of its 8 cogs.
8. **`tgtDef` at cog levels 4 and 5** — the source lists two values
   (-12/-15 and -15/-20). `data/accuracy.py` uses the tier-1 (less
   negative) branch; the other branch applies to non-tier-1 cogs and isn't
   modeled.
