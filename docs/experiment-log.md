# Experiment log

This is the project's lab notebook: what was tried, what it measured, and
what lost. What the code does can be read from the code. What was tried
and abandoned cannot, and without a record the same idea gets rebuilt.
Many entries describe a change that was built, measured and thrown away.
Those are the most useful ones, and none has been removed.

For where the project stands now, read [roadmap.md](roadmap.md). For how
far each number in the game data can be trusted, and for the tags
`[CONFIRMED]`, `[OWNER]`, `[ASSUMED]` and `[TODO]`, read
[data-confidence.md](data-confidence.md). In this log `[OWNER]` marks a
judgement by the maintainer, who is an experienced player.

## How to read an entry

Each entry has a date, a one-line outcome, and four parts:

- **Question.** What was being asked, and why.
- **Setup.** What was run: the fights, the sample, the arms compared.
- **Result.** The numbers.
- **Conclusion.** What was decided, and what the result does not show.

Where a later result changed an earlier conclusion, the earlier entry is
kept as it was and carries a dated note pointing at the later one.

**Results are from simulated fights unless an entry says a running game
was observed.** A simulated fight uses this project's model of the rules
and its cog attack tables, some of which are known to be out of date
([data-confidence.md](data-confidence.md)). A win rate here is a
statement about the model.

### Conventions

- **Paired comparison.** Two engines play the same seeds, so the fights
  and the dice match and only the engine differs. `+a/-b` counts the
  discordant seeds: `a` fights the new arm won and the old arm lost, `b`
  the reverse. The p-value is a sign test on those.
- **Selection and confirmation.** A p-value from the same seeds a setting
  was chosen on is a selection number, not a confirmation. The practice
  the project settled on is to select on one block of seeds and confirm on
  another. The older entries predate it. Several entries
  record an effect that shrank or vanished on a larger or fresh sample.
- **Common random numbers.** Candidate moves are played out from the same
  seed so the comparison between them is paired.
- Entries dated 2026-08-20 to 2026-09-02 were recovered from longer
  versions of `docs/scorer-audit.md` and `docs/scoring.md`; the full
  originals are in those files' git history. Entries from 2026-10-01 on
  were written as the work was done or reconstructed from commit messages
  and the maintainer's working notes. Commit hashes are given where a
  commit carries the measurement, and an entry says so where its figures
  are in no commit.

### Terms

| Term | Meaning |
|---|---|
| toon, cog, gag | The player's character, the enemy, and the item thrown at it. |
| track, level | Gags come in seven tracks (Toon-Up, Trap, Lure, Sound, Throw, Squirt, Drop) and seven levels. A level 7 gag is the strongest and rarest. |
| laff | A toon's health. A toon at zero laff is "sad" and leaves the battle. |
| lure | A lured cog skips its attacks for some rounds and takes bonus damage from Throw and Squirt. |
| pouch | The gags a toon carries. Nothing restocks it during a fight except a restock card. |
| pink slip, "fire" | A consumable that removes one cog outright. |
| Unite | A consumable phrase that heals (Toon-Up) or restocks gags (Gag-Up), used alongside the round's gag. |
| SOS card | A consumable that calls a helper in place of the round's gag. |
| building, floor | A cog building is several consecutive battles (floors); laff and pouch carry across them. "Facility" in the code. |
| VP, CFO, CJ, CEO | The four boss fights. Each has rounds of cog battles before the boss. |
| side | A boss fight splits its toons across two simultaneous battles. One battle is a side, and sweeps count sides. |
| skelecog, Version 2.0 cog | Cog variants in boss fights. A Version 2.0 cog has two layers of health. |
| leftovers | In the CEO fight, cogs that survive the banquet round and join the second battle. "CEO 5" means five leftovers. |
| difficulty 1 to 9 | The sampler's scale for street and building cog levels. |
| policy, "plain" | The PPO network. "Plain" is the network's own top choice with no refinement. |
| climb | `hybrid.climb`: the policy proposes moves for each toon and a coordinate ascent over the joint plan picks among them. The panel's PPO row. |
| `_quick_score` | The one-round scorer that climb judges plans with. Its weights are `QUICK_W` in `solver/search/weights.py`. |
| budget, width | Climb's number of scorer calls, and how many of the policy's top moves it considers per toon. |
| Search row | The expectimax search (`solver/search/expectimax.py`). |
| Playout row | `solver/search/playout.py`: each candidate move is played to the end of the fight many times. |
| rollout, fast network | One playout of the rest of a fight, and the small network (`solver/search/fastplayer.py`) that chooses the moves inside it. |
| pickup, coordinated | Party modes. Pickup: you choose your move and teammates are modelled. Coordinated: every toon's move is chosen together. |
| `SensiblePrior` | The default model of what an unknown teammate throws. A guess about people, not a rule of the game. |
| Realms | Toontown Realms, a different server with its own panel. |
| sweep regime | A named kind of simulated fight in `tools/sweep.py`: `solo-vp` (one toon, 20 + 20 cogs), `duo-vp` (one side of a two-player VP: one toon, 10 + 10 cogs), `party-vp` (one side of a four-player VP: two toons, 10 + 10 cogs), `solo-building`, `my-building` (the maintainer's toon in Daisy Gardens buildings), `party-building` (two to four toons), `ceo` (a two-toon CEO side), `solo-ceo`, `realms-vp` (a solo VP set up as on Realms). |

## Contents

**[Part 1. The plan scorer and the PPO policy on boss fights](#part-1-the-plan-scorer-and-the-ppo-policy-on-boss-fights)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-08-20 | [Both plan scorers assumed every gag hits](#2026-08-20-both-plan-scorers-assumed-every-gag-hits) | Fixed |
| 2026-08-20 | [Pink slips were free so the party never had one left](#2026-08-20-pink-slips-were-free-so-the-party-never-had-one-left) | A price per slip scaled by cogs remaining, kept |
| 2026-08-20 | [Pricing a slip at the use it gives up](#2026-08-20-pricing-a-slip-at-the-use-it-gives-up) | Refuted and reverted |
| 2026-08-21 | [Retraining the policy on boss sides](#2026-08-21-retraining-the-policy-on-boss-sides) | The first change to the policy that moved climb |
| 2026-08-21 | [Is the CEO lost by not healing](#2026-08-21-is-the-ceo-lost-by-not-healing) | Refuted |
| 2026-08-21 | [Widening the candidate window of climb](#2026-08-21-widening-the-candidate-window-of-climb) | Refuted |
| 2026-08-21 | [The prevention weight moved from 2 to 9](#2026-08-21-the-prevention-weight-moved-from-2-to-9) | Kept |
| 2026-08-21 | [Probes and paired moves turned on after the scorer changed](#2026-08-21-probes-and-paired-moves-turned-on-after-the-scorer-changed) | Kept |
| 2026-08-22 | [The wrongly trained policy was the better proposer](#2026-08-22-the-wrongly-trained-policy-was-the-better-proposer) | Explained |
| 2026-08-22 | [Training more seeds and picking the best](#2026-08-22-training-more-seeds-and-picking-the-best) | Refuted |
| 2026-08-28 | [Track probes on in a party and off solo](#2026-08-28-track-probes-on-in-a-party-and-off-solo) | Kept |

**[Part 2. Scorer weights, consumables and observation versions](#part-2-scorer-weights-consumables-and-observation-versions)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-08-30 | [The survive weight double-counted damage prevention](#2026-08-30-the-survive-weight-double-counted-damage-prevention) | Bug found by a sweep and fixed |
| 2026-08-30 | [Consumables are reserved for hard content without a rule](#2026-08-30-consumables-are-reserved-for-hard-content-without-a-rule) | Kept |
| 2026-08-31 | [The slip price floor raised from 20 to 120](#2026-08-31-the-slip-price-floor-raised-from-20-to-120) | Kept |
| 2026-08-31 | [A harness fallback that produced four false results](#2026-08-31-a-harness-fallback-that-produced-four-false-results) | Harness bug |
| 2026-08-31 | [The scarcity weight swept and left at 20](#2026-08-31-the-scarcity-weight-swept-and-left-at-20) | Null |
| 2026-08-31 | [Why there is no penalty for a group gag on one cog](#2026-08-31-why-there-is-no-penalty-for-a-group-gag-on-one-cog) | Left alone |
| 2026-08-31 | [Earlier sweeps used maxed toons so two prices were re-run](#2026-08-31-earlier-sweeps-used-maxed-toons-so-two-prices-were-re-run) | Both shipped values held on realistic toons |
| 2026-08-31 | [How good a ranker is the one-round scorer](#2026-08-31-how-good-a-ranker-is-the-one-round-scorer) | Good on this benchmark (corrected 2026-09-01 after a seeding bug) |
| 2026-09-01 | [The survive weight re-run on realistic toons](#2026-09-01-the-survive-weight-re-run-on-realistic-toons) | 400 holds |
| 2026-09-01 | [What the scorer gets wrong at difficulty 9](#2026-09-01-what-the-scorer-gets-wrong-at-difficulty-9) | Nothing changed |
| 2026-09-01 | [Observation version 3 is indistinguishable from version 2](#2026-09-01-observation-version-3-is-indistinguishable-from-version-2) | Null |
| 2026-09-01 | [Crediting lured cogs for the quiet they will actually provide](#2026-09-01-crediting-lured-cogs-for-the-quiet-they-will-actually-provide) | Kept |
| 2026-09-01 | [Should scarcity price the carry limit or the count held](#2026-09-01-should-scarcity-price-the-carry-limit-or-the-count-held) | Switched to the count held, on the argument |
| 2026-09-01 | [The price weight cannot be tuned on its own](#2026-09-01-the-price-weight-cannot-be-tuned-on-its-own) | Stays at 1.0 |
| 2026-09-01 | [A sweep script that swept the wrong knob](#2026-09-01-a-sweep-script-that-swept-the-wrong-knob) | Harness bug |
| 2026-09-01 | [The price multiplier split into one for gags and one for consumables](#2026-09-01-the-price-multiplier-split-into-one-for-gags-and-one-for-consumables) | Kept |
| 2026-09-02 | [Six fresh policies and nothing to promote](#2026-09-02-six-fresh-policies-and-nothing-to-promote) | Null |
| 2026-09-04 | [Widening the menu of climb to 16](#2026-09-04-widening-the-menu-of-climb-to-16) | Kept |

**[Part 3. From a one-round judge to playouts](#part-3-from-a-one-round-judge-to-playouts)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-08-17 | [A PPO rollout as the judge for climb](#2026-08-17-a-ppo-rollout-as-the-judge-for-climb) | Refuted and later removed |
| 2026-09-30 | [Crediting a restock card with the round it enables](#2026-09-30-crediting-a-restock-card-with-the-round-it-enables) | Null and later removed |
| 2026-10-01 | [Judging a move by playing the rest of the fight out](#2026-10-01-judging-a-move-by-playing-the-rest-of-the-fight-out) | Kept |
| 2026-10-01 | [The playouts choose what gets played out](#2026-10-01-the-playouts-choose-what-gets-played-out) | Kept |
| 2026-10-01 | [A fast network plays out the rest of each fight](#2026-10-01-a-fast-network-plays-out-the-rest-of-each-fight) | Kept |
| 2026-10-02 | [Playouts for parties](#2026-10-02-playouts-for-parties) | Pickup playouts kept (+20 wins in 600 party buildings) |
| 2026-10-05 | [Reading gag counts and cog levels from recorded frames](#2026-10-05-reading-gag-counts-and-cog-levels-from-recorded-frames) | Kept |
| 2026-10-05 | [The hover card of the gag menu as a third check](#2026-10-05-the-hover-card-of-the-gag-menu-as-a-third-check) | Not shipped |
| 2026-10-05 | [Valuing the pouch when a playout stops at the floor](#2026-10-05-valuing-the-pouch-when-a-playout-stops-at-the-floor) | Kept at weight 2 |
| 2026-10-05 | [Boss rounds sized by who came](#2026-10-05-boss-rounds-sized-by-who-came) | Kept |

**[Part 4. Tuning the Playout engine](#part-4-tuning-the-playout-engine)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-10-06 | [Expert iteration round 2 for the rollout network](#2026-10-06-expert-iteration-round-2-for-the-rollout-network) | Not shipped |
| 2026-10-06 | [Unites were never spent in simulation](#2026-10-06-unites-were-never-spent-in-simulation) | Bug fixed |
| 2026-10-07 | [A rollout network that sees and uses Unites](#2026-10-07-a-rollout-network-that-sees-and-uses-unites) | Stronger alone, no better inside the playouts and slower |
| 2026-10-07 | [Groups with Unites and the Unite-aware network re-checked](#2026-10-07-groups-with-unites-and-the-unite-aware-network-re-checked) | The Unite-aware network shipped on realism against a non-significant dip |
| 2026-10-07 | [The preset of the panel in the playouts](#2026-10-07-the-preset-of-the-panel-in-the-playouts) | Kept |
| 2026-10-08 | [Open-loop tree search over your own decisions](#2026-10-08-open-loop-tree-search-over-your-own-decisions) | Not better than flat playouts at any setting, and no better with two or four times the budget |
| 2026-10-08 | [A network model of teammates](#2026-10-08-a-network-model-of-teammates) | No measurable difference in what the engine assumes |

**[Part 5. The exact search and learned values](#part-5-the-exact-search-and-learned-values)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-10-08 | [Squeezing depth out of the exact search](#2026-10-08-squeezing-depth-out-of-the-exact-search) | 1.5x exact from profiling |
| 2026-10-08 | [The chosen move stops changing at depth 4](#2026-10-08-the-chosen-move-stops-changing-at-depth-4) | In a single battle the panel is already at the tactical plateau |
| 2026-10-08 | [Pruning and move ordering in the exact search](#2026-10-08-pruning-and-move-ordering-in-the-exact-search) | Best-first ordering is exact and on by default |
| 2026-10-08 | [Tighter bounds and a hint from the shallower pass](#2026-10-08-tighter-bounds-and-a-hint-from-the-shallower-pass) | Tighter static bounds bought no pruning and were removed |
| 2026-10-09 | [A learned leaf for the Search row](#2026-10-09-a-learned-leaf-for-the-search-row) | Three tries, none better in play |
| 2026-10-09 | [Shortened playouts with a value network](#2026-10-09-shortened-playouts-with-a-value-network) | Shipped |

**[Part 6. What live play turned up](#part-6-what-live-play-turned-up)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-10-09 | [The TTR panel plans around the Unites the player states](#2026-10-09-the-ttr-panel-plans-around-the-unites-the-player-states) | Kept |
| 2026-10-10 | [Two logged Realms VPs and what the engines got wrong](#2026-10-10-two-logged-realms-vps-and-what-the-engines-got-wrong) | Running game observed; the engines matched the maintainer's move on 12 to 29% of boards; bugs fixed |
| 2026-10-10 | [SOS cards as one pool and a price per call that lost](#2026-10-10-sos-cards-as-one-pool-and-a-price-per-call-that-lost) | The pool is kept |
| 2026-10-10 | [Wasted reach charged by all three engines](#2026-10-10-wasted-reach-charged-by-all-three-engines) | Kept as a stated preference; costs no wins and gains none |
| 2026-10-10 | [Three implementations of a round held against each other](#2026-10-10-three-implementations-of-a-round-held-against-each-other) | Tool kept |
| 2026-10-10 | [A rule and two tie-breaks from live play](#2026-10-10-a-rule-and-two-tie-breaks-from-live-play) | Kept |
| 2026-10-10 | [The pass on the menu of the Playout row](#2026-10-10-the-pass-on-the-menu-of-the-playout-row) | Kept |
| 2026-10-10 | [Budgets for slips, Unites and SOS cards as a session total](#2026-10-10-budgets-for-slips-unites-and-sos-cards-as-a-session-total) | Kept |
| 2026-10-10 | [Detecting the VP on TTR and reading pink slips held](#2026-10-10-detecting-the-vp-on-ttr-and-reading-pink-slips-held) | Running game observed; the VP is detected from the game's log file |
| 2026-10-10 | [Reading the floors of a building through the Discord relay](#2026-10-10-reading-the-floors-of-a-building-through-the-discord-relay) | Running game observed; works if the relay starts before Discord |

**[Part 7. Expert iteration, the gag economy and teammates](#part-7-expert-iteration-the-gag-economy-and-teammates)**

| Date | Entry | Outcome |
|---|---|---|
| 2026-10-11 | [Expert iteration for the rollout network shipped](#2026-10-11-expert-iteration-for-the-rollout-network-shipped) | Shipped |
| 2026-10-11 | [Later rounds of expert iteration did not beat the shipped network](#2026-10-11-later-rounds-of-expert-iteration-did-not-beat-the-shipped-network) | Not shipped |
| 2026-10-11 | [Charging the playouts for the gags they spend](#2026-10-11-charging-the-playouts-for-the-gags-they-spend) | Kept, at twice the preset's exchange rate |
| 2026-10-11 | [The Search row restarted before it could finish](#2026-10-11-the-search-row-restarted-before-it-could-finish) | Fixed |
| 2026-10-11 | [The Playout row leads in every fight](#2026-10-11-the-playout-row-leads-in-every-fight) | Kept, on the maintainer's judgement and the 2026-10-09 comparison |
| 2026-10-11 | [A new fight read fresh and advice recomputed on a corrected reading](#2026-10-11-a-new-fight-read-fresh-and-advice-recomputed-on-a-corrected-reading) | Fixed |
| 2026-10-11 | [Stand-in teammates for the TTR Playout row](#2026-10-11-stand-in-teammates-for-the-ttr-playout-row) | Shelved |
| 2026-10-12 | [The pass still reached the menu another way](#2026-10-12-the-pass-still-reached-the-menu-another-way) | Kept |
| 2026-10-12 | [A pink slip was free to the Search row](#2026-10-12-a-pink-slip-was-free-to-the-search-row) | Kept, `[ASSUMED]` |

---

## Part 1. The plan scorer and the PPO policy on boss fights

These entries date from 2026-08-20 to 2026-08-28, when the PPO row (climb)
was the only fast engine and the CEO fight was the hard case. They were
recovered from `docs/scorer-audit.md`.

### 2026-08-20 Both plan scorers assumed every gag hits

**Outcome:** fixed; worth +5.5 points on CEO sides for climb, nothing for the party search.

**Question.** `_quick_score` and `_greedy_score` each played one round in
which every gag hit. `_quick_score` is climb's only judge. Does that
assumption cost anything?

**Setup.** In a cog building accuracy runs 70 to 95% and hardly varies by
track, so ranking by damage and ranking by expected damage pick the same
gag. Against level 13 and 14 cogs it spans 51% to 95% and the two stop
agreeing: the all-hit score prefers the gag with the largest printed
damage, which is reliably the least likely to land. Seed 99013 shows it
in three rounds: two Grand Pianos into four level 13 cogs on one shared
54% roll, both miss; a Throw and a Lure, both miss; the party is dead
with no cog below full health.

Both scorers now take the expectation over every way the dice can fall,
through one shared `_expected_over_rolls`. The outcomes are enumerated,
not sampled. A party is at most four toons and each rolls at most one
die, so there are at most 16 branches, and an exact expectation cannot
rank the same position differently on two calls. Branching is over roll
groups, not toons, which keeps correlated dice right: a plan still
cannot hedge by stacking one track on one target.

Accuracy is conditional on what else is thrown, and the conditions are
large. The probabilities are read from the simulator's own record per
branch, because a fixed table of per-gag accuracies would get all of
these wrong:

| Situation | Accuracy |
|---|---|
| Drop 7, nothing landed first | 54% |
| Drop 7, a Throw landed first (stun) | 79% |
| Lure 6 alone, then two Lure 6s (multi-Lure bonus) | 79%, then 95% |
| Lure 6 into an untrapped, then a trapped target | 79%, then 95% |

**Result.**

| Engine | Before | After | Paired | Cost per decision |
|---|---|---|---|---|
| climb, 200 CEO sides | 69.5% | 75.0% | +24/-13, p=0.049 | 1.7 ms to 3.3 ms |
| the party search (`party_search`) | 73.3% | 73.3% | +2/-2 | 794 ms to 1245 ms |

A 40-side sample of the climb result had read +12.5 points; 200 sides
read +5.5.

**Conclusion.** Kept in both scorers. For the party search it buys no
measurable gain at 1.6 times the cost, and is kept as a correctness fix:
its `rollout_value` is `greedy_plan` played forward, and an all-hit
rollout values every position as though the party never misses. Quote
the larger sample; the smaller one overstated the effect, which happened
twice in the same session.

### 2026-08-20 Pink slips were free so the party never had one left

**Outcome:** a price per slip scaled by cogs remaining, kept; `FIRE_PRICE = 20` is supported in direction, not proven.

**Question.** The scorer charged nothing for a pink slip, on the stated
reasoning that slips are the reward for the CEO fight and may be fired
freely. Is that close to right?

**Setup.** CEO sides, two battles: the waiter battle, then the Big
Cheese with some number of banquet leftovers.

**Result.** It is not close to right. The party spent all ten slips on
the waiter battle and reached the Big Cheese holding 0.3 of 10 on
average. That is the whole reason ten leftovers sat at exactly 0%.
Battle two in isolation, from full resources, clears 93% at ten
leftovers, so the second fight was never the problem. Which resource
decides it, on 40 sides per cell:

| | 10 slips | 0 slips |
|---|---|---|
| Full laff | 92.5% | 50.0% |
| 65% laff | 82.5% | 17.5% |

The slips are worth 42 points of clear rate and the laff 10.

A flat price per slip was tried first. It helped at five leftovers
(38.0% to 49.5%, p=0.008) and hurt at zero (88.5% to 82.0%, p=0.021),
because it also suppressed slips in the last battle, and a slip carried
out of the fight unspent is worth nothing. Scaling the price by
`cogs_remaining` sends it to zero when there is nothing left to save
for. Over 200 sides, `FIRE_PRICE = 20` with that scaling:

| Leftovers | Before | After | p |
|---|---|---|---|
| 0 | 88.5% | 88.0% | 0.50 |
| 5 | 38.0% | 41.5% | 0.22 |
| 10 | 0% | above 0% at every non-zero price tried | |

**Conclusion.** The shape of the price matters more than its size: hoard
while cogs are still coming, spend freely at the end. `FIRE_PRICE = 20`
is neutral at zero leftovers (the flat price's harm is gone), positive
but not significant at five, and clearly unsticks ten leftovers from 0%.

### 2026-08-20 Pricing a slip at the use it gives up

**Outcome:** refuted and reverted.

**Question.** A price per cog remaining cannot tell a level 10 waiter
from a level 14 Version 2.0 cog, and only one of those is worth a slip.
Should the price be the opportunity cost instead? Rank every cog that
could be fired, standing or still to arrive, and with F slips held
charge the F-th best, since that is the use being given up. That needs
no tuned constant.

**Setup.** Built and compared with the count price on 200 CEO sides per
row.

**Result.**

| Leftovers | Count price (20 per cog) | Opportunity cost | Paired |
|---|---|---|---|
| 0 | 88.0% | 76.0% | +11/-35, p=0.0003 |
| 5 | 41.5% | 28.5% | +20/-46, p=0.0009 |
| 10 | 4.0% | 2.0% | |

The implementation did what it was designed to. On the opening waiter
board, firing a cog is worth 241.3 against an opportunity cost of 333.9,
so it declines. It barely hoards: 9.00 slips fired against 9.85, two
left at the end against 0.25. It loses six sides in forty by declining
0.85 slips.

**Conclusion.** What matters is which slips are declined, not how many.
The ones it declines are the early ones, and a slip spent early stops
that cog attacking for the rest of the battle. The comparison prices
what a slip buys in removal and ignores what it saves in laff over time,
which in a twenty-cog battle is most of its value. `_fire_value` carries
one round of the cog's damage (`_cog_threat`), and one round is not the
horizon a slip buys. A working version would have to price the damage a
slip prevents between now and the end of the battle. The code was
reverted, not left behind a disabled switch.

### 2026-08-21 Retraining the policy on boss sides

**Outcome:** the first change to the policy that moved climb; CEO gains replicated on held-out sides. The policy shipped here was withdrawn the next day (see the note at the end).

**Question.** Does adding boss positions to PPO training help on boss
fights, and does a better policy show up after climb refines it? Five
earlier changes to training had moved the plain policy and not climb
([reward-experiments.md](reward-experiments.md)).

**Setup.** Six runs of 6 million steps, three seeds per arm. A control
arm was needed because the observation was widened at the same time;
without it, "boss positions helped" and "the wider observation helped"
would be one number. Both arms used `--coordinated --facility-fraction
0.5 --fire-fraction 0.25 --hidden 256`; the treatment adds
`--boss-fraction 0.25`. 120 sides per cell, common random numbers.
Per-seed figures are in brackets.

**Result.**

| Set | Mode | Control | Boss |
|---|---|---|---|
| Buildings | plain | 63.3% [64/63/62] | 60.3% [56/64/61] |
| Buildings | climb | 72.5% [72/73/72] | 69.2% [63/72/72] |
| VP | plain | 95.0% | 96.4% |
| VP | climb | 98.1% | 99.7% |
| CEO 0 | plain | 43.3% [34/56/40] | 76.4% [68/78/83] |
| CEO 0 | climb | 79.2% | 88.1% [88/88/88] |
| CEO 5 | plain | 10.0% [5/10/15] | 31.9% [19/37/40] |
| CEO 5 | climb | 28.6% | 40.0% |
| CEO 10 | either | about 0.5% | about 1.2% |

Paired over sides, boss against control:

| Cell | Difference | Paired |
|---|---|---|
| CEO 0 plain | +33.1 | +140/-21, p<0.0001 |
| CEO 0 climb | +8.9 | +45/-13, p<0.0001 |
| CEO 5 plain | +21.9 | p<0.0001 |
| CEO 5 climb | +11.4 | +90/-49, p=0.0003 |
| VP climb | +1.7 | p=0.035 |
| Buildings climb | -3.3 | p=0.033 |

The buildings cost came from a single outlying seed ([63/72/72] against
the control's [72/73/72]). Two explanations were open: real harm, or
displacement, since at `--boss-fraction 0.25` the boss arm gets a quarter
fewer building episodes (0.375 against 0.500 effective). A third arm,
"bossmatched", at `--facility-fraction 0.667` restores that exposure.
All three were re-scored on 180 held-out sides per cell:

| Set | Mode | Control | Boss | Bossmatched |
|---|---|---|---|---|
| Buildings | climb | 66.3% | 69.6% | 66.9% |
| Buildings | plain | 61.7% | 60.6% | 59.6% |
| VP | climb | 99.4% | 99.4% | 99.3% |
| CEO 0 | climb | 78.7% | 88.9% | 87.6% |
| CEO 0 | plain | 46.7% | 73.9% | 79.6% |
| CEO 5 | climb | 32.4% | 43.1% | 46.9% |
| CEO 5 | plain | 7.8% | 35.2% | 30.6% |

On seeds nobody tuned against, the sign on buildings flips: boss is 3.3
points above control. Bossmatched lands between the other two with the
widest per-seed spread of the three, [71/63/66].

**Conclusion.**

- This was the first policy-side change that moved climb. An earlier
  prediction had been that climb is saturated on CEO boards, because
  budgets of 8, 16, 32 and 64 all score the same, so a better proposal
  would show on plain and not on climb. Budget saturation says only that
  more iterations do not help. It says nothing about where climb starts,
  and coordinate ascent from a different starting plan reaches a
  different local optimum.
- The earlier finding in [reward-experiments.md](reward-experiments.md)
  stands for the five changes tried there, but is now bounded: those
  changes were all on positions climb already handled well.
- The buildings deficit was seed noise. There was nothing to fix.
- The CEO gain replicated: +10.2 at CEO 0 on climb, +10.7 at CEO 5, +27
  on both plain cells, with per-seed ranges that do not overlap (boss
  [67/76/79] against control [37/57/47]). Everything else measured that
  day shrank or vanished on a larger sample.
- CEO 10 did not move. Four separate attempts had by then failed to
  shift it.

The policy shipped was `boss_s2`, selected on the in-training building
evaluation (+44.76 return, 84.5% win, 70.0% of floors finished, the best
of the three boss seeds there) and not on any set reported above. An
earlier policy had been shipped after choosing its seed on a set that
was never reported.

*Note, 2026-08-22:* `boss_s2` turned out to have been trained under a
wrong Lure rule and was withdrawn. See
[2026-08-22 The wrongly trained policy was the better proposer](#2026-08-22-the-wrongly-trained-policy-was-the-better-proposer).

### 2026-08-21 Is the CEO lost by not healing

**Outcome:** refuted. Not healing on a boss board is correct play in the model.

**Question.** The policy never heals on a boss board: zero Toon-Ups in
1,446 decisions across 40 CEO sides, including 99 rounds with the party
under 35% laff, while each toon carries eleven heals and a level 7 group
Toon-Up restores 210 laff to the other toon. In a losing trace the party
sits at 25 and 23 laff and throws Sound and Drop. Is that the hole?

(A group Toon-Up is split evenly between its recipients, and the thrower
is not one of them. A two-toon party has one recipient, who receives the
whole 210; a four-toon party gets three shares of 70.)

**Setup.** Two experiments, 120 sides per cell.

**Result.**

*Raising the heal weight does nothing.* Taking `QUICK_W["heal"]` from 2
to 40 moved CEO clears from 88.3% to 89.2% at zero leftovers and 37.5%
to 39.2% at five, and the agent still healed 0.1 times a side. It could
not have worked: climb can only reorder what the policy proposes, and
Toon-Up gets essentially no probability on these boards, so the weight
was never reached. Tuning a term that never fires produces a flat sweep
that looks like evidence.

*`probe_tracks` reaches a heal, and then loses.* That flag offers each
toon the best action of every track it holds, so a heal becomes a
candidate however the policy ranks it. It had been off since an earlier
measurement, made against an all-hit scorer that no longer existed.
Re-run against the expectation scorer:

| Set | Probes off | Probes on | Toon-Ups per side | Paired |
|---|---|---|---|---|
| Buildings | 71.7% | 70.0% | 1.31 to 1.82 | +4/-6, p=0.38 |
| VP | 100.0% | 98.3% | 0.00 to 0.39 | +0/-2 |
| CEO 0 | 88.3% | 80.8% | 0.00 to 0.56 | +4/-13, p=0.025 |
| CEO 5 | 37.5% | 30.8% | 0.01 to 0.91 | +15/-23, p=0.13 |

**Conclusion.** The mechanism works, the agent heals, and it costs 7.5
points on the CEO. The scorer was right to decline: at laff 25 and 23 it
prices the attack at 851 against 227 for a double heal. On a board where
incoming damage scales with the number of cogs standing, killing is the
prevention, and a round spent healing is a round four cogs attack for
free. `probe_tracks` stayed off, refuted twice for two different
reasons.

*Note, later the same day:* once the scorer's Lure model and prevention
weight were corrected, probes were re-tested and turned on. See
[2026-08-21 Probes and paired moves turned on after the scorer changed](#2026-08-21-probes-and-paired-moves-turned-on-after-the-scorer-changed).

"It never heals" is specific to the CEO. On buildings the policy
proposes 1.31 heals a side unprompted.

What is left is duller. The waiter battle is a damage race with no
slack: twenty cogs at levels 9 to 14 against 217 laff. Two traced sides
play structurally the same game with the same nine or ten slips; one
leaves for the Big Cheese on 139 laff and one on 6. The loser makes no
identifiable mistake. It is on the wrong side of the accuracy rolls.

### 2026-08-21 Widening the candidate window of climb

**Outcome:** refuted. A wider window looked like a win on the discovery seeds and was exactly zero on fresh ones.

**Question.** Climb offers each toon only the policy's top `width`
actions, 3 by default. Is that too narrow?

**Setup.** On the opening round of the CEO's second battle, all 2,132
legal joint plans were enumerated and scored:

    board  c0:14=254V c1:9=110V c2:10=132V c3:12=196V   laff 71/65

    585.6   lure/6->all   + trap/7->all     <- best legal plan
    559.6   squirt/7->all + drop/7->all
    525.0   toon_up/5->1  + drop/7->all
    472.7   squirt/7->all + drop/6->c0      <- played, rank 17 of 2132

The best plan opens with a Lure and pairs it with a Trap, the kind of
two-track setup a one-toon-at-a-time sweep assembles badly. Climb lands
in the top 0.8%, 113 points short.

**Result.**

*A correction to the first analysis.* The first version claimed the best
plan was `lure/6->all + squirt/7->all` at 831.7. The second toon holds no
level 7 Squirt, so that plan is illegal. `_quick_score` does not check
playability (`_playable` is a separate function), so a hand-built plan
could score a gag the toon does not own. Climb never had the problem:
illegal actions are masked out before the sweep, and across 3,198
actions played on buildings, the VP and the CEO, none was illegal. The
design, generate legal moves and then score them, is right. What made it
a trap was an inconsistency underneath. A pouch holds explicit zeroes,
so spending a missing key raised an error that `_quick_score` turns into
minus infinity, while spending a zero count went quietly to -1 and dealt
full damage:

    key absent      _quick_score  -inf    simulator KeyError
    key present, 0  _quick_score  72.8    count -> -1, damage dealt

`simulator._spend_gag` now refuses both. Two other readings in that
first analysis came from the same mistake: "squirt/7->all ranks 49 for
the second toon" was not a finding about the policy, since that toon had
48 legal actions and rank 49 meant illegal.

*Coordination is live and correct.* Every sweep recomputes each toon's
scores with the current joint plan visible and that toon's own slot
blanked, and the rankings do respond: committing the first toon to a
Lure lifts `throw/5->3` to second for the other toon and drops
`drop/6->0` from second to fifth.

*Widening.* Raw `width` is worse, because `budget` counts scorer calls
and a sweep costs about toons times width of them. Width 8 at budget 8
buys candidates at the price of convergence: buildings fall to 65.8%
(p=0.033) and CEO 0 to 75.0% (p=0.0019). At matched sweeps it looked
like a win: CEO 5 37.5% to 50.0% (p=0.022), CEO 0 +4.2, buildings +1.6.
It did not replicate on 240 fresh sides per set:

| Set | Width 3, budget 8 | Width 5, budget 14 | Flips |
|---|---|---|---|
| Buildings | 69.2% | 70.0% | +12/-10 |
| VP | 98.8% | 100.0% | +3/-0 |
| CEO 0 | 90.4% | 91.2% | +12/-10 |
| CEO 5 | 48.8% | 48.8% | +50/-50 |

The baseline itself moved from 37.5% to 48.8% between the two seed sets,
so the discovery set was a hard draw and the wider window was fitting
it.

*Budget alone* buys nothing: +0/-0 on CEO 0 and +1/-1 on CEO 5 at three
times the budget. Climb converges long before budget 8.

**Conclusion.** Three attempts to widen what climb considers
(`probe_tracks`, raw width, matched width) either lost or did nothing,
while the one thing that improved it in that period was making the
scorer more accurate about plans it already saw. A hypothesis, not
tested then: `_quick_score` ranks a few plausible plans well and a wide
field badly, so widening feeds it the comparisons it is worst at.

A specific prediction also failed. A wider window was expected to lure
more. Lures per side went down wherever the window widened (6.65 to 6.11
on CEO 5, 4.44 to 4.11 on CEO 0) while the win rate rose on the
discovery set. Wider windows find better pairings: one well-supported
Lure replaces two poorly supported ones.

*Note, 2026-09-04:* on a solo VP the conclusion reversed, and the menu
was widened to 16. See
[2026-09-04 Widening the menu of climb to 16](#2026-09-04-widening-the-menu-of-climb-to-16).

### 2026-08-21 The prevention weight moved from 2 to 9

**Outcome:** kept. CEO 0 went from 9.0% to 54.0% on untouched seeds, the largest confirmed effect in the project at that date.

**Question.** `QUICK_W["prevent"]` weights the cog damage a plan
prevents, mostly by luring. It sat at 2.0. Was that right once the Lure
rule was corrected?

**Setup.** The old weight had been fitted against a `prevented` term
that multiplied by the full Lure duration, under a rule where a lured
cog stayed asleep through damage. The term overstated Lure and the fit
pushed the weight down to compensate: two errors pointing opposite
ways, so inspecting either alone gave the wrong answer about the other.
The rule was corrected (a landed attack wakes a lured cog), the term
remodelled, and the weight swept from 2 to 14, then confirmed on seeds
the sweep had not touched, 200 sides per cell (commit 4718c1f).

**Result.**

| Set | Weight 2 | Weight 9 | Paired |
|---|---|---|---|
| CEO 0 | 9.0% | 54.0% | +96/-6, p<0.0001 |
| Buildings | 66.0% | 67.0% | +8/-6, not significant |
| VP | 98.5% | 98.5% | not significant |
| Share of gags that are Lures | 21% | 37% | |

**Conclusion.** Plus 45 points with no cost elsewhere, and the Lure
share nearly doubling shows a change in behaviour and not only in the
score. The maintainer had called it from play ("it should be luring")
against three readings that pointed the other way: the term appeared to
over-credit Lure, a raw correlation had losing sides luring more, and
the scorer preferred Sound. The first two were artefacts (a compensating
weight, and a confound with fight length) and only the intervention
settled it.

A policy retrained under the corrected rule, `lurefix_s3`, cleared 0% of
CEO sides at either weight while proposing Lures on 5 to 7% of gags. It
had been trained with a leftover range (0 to 10) that under the corrected
rule spans 13% to 0%, so nearly every CEO episode was a loss and carried
no gradient. That was a mistake in the training range, not a fact about
the game.

### 2026-08-21 Probes and paired moves turned on after the scorer changed

**Outcome:** kept. Both had been refuted twice; with the corrected scorer they are worth 8.5 points on buildings and 34 to 55 on the CEO.

**Question.** Track probes (offer each toon the best action of every
track it holds) and paired moves (change two toons' actions at once) had
each lost twice, on the argument that more reach for an approximate
scorer is more scope to act on its errors. Does that still hold after
the scorer was corrected (previous entry)?

**Setup.** 200 held-out sides per set, climb with and without both
(commit a4c5927).

**Result.**

| Set | Without | With probes and pairs | p |
|---|---|---|---|
| Buildings | 65.0% | 73.5% | 0.0002 |
| VP | 99.0% | 99.5% | not significant |
| CEO 0 | 54.0% | 88.5% | <0.0001 |
| CEO 2 | 18.5% | 73.5% | <0.0001 |
| CEO 4 | 7.0% | 45.0% | <0.0001 |

Cost: 3.5 ms to 5.8 ms a decision. Three tracks had been structurally
invisible. Trap sat at a median rank of 25 in the policy's ordering and
entered the 3-wide window 0 times in 521 toon-decisions; Toon-Up sat at
rank 10 and entered 1% of the time. The scorer wanted both: a group Trap
with a group Lure was the highest-scoring plan on the board where it was
measured, and heal use went from 0% to 15% once it was reachable.

**Conclusion.** The order of work matters: fix the model, then the
weights, then the reach. In the reverse order each stage measures the
previous stage's errors and refutes a sound idea for the wrong reason,
which is what happened to these two flags, twice each. It is also why
the earlier heal sweep read flat at twenty times the weight: it tuned a
term the search never consulted.

### 2026-08-22 The wrongly trained policy was the better proposer

**Outcome:** explained. Training scores the policy on its own play; deployment uses it as a proposer for climb. The wrongly trained policy was withdrawn.

**Question.** `boss_s2` had been trained under a Lure rule later found to
be wrong, and it beat every correctly trained policy on the CEO: 88.0%
against a best of 63.3% across nine of them, while matching them on
buildings and the VP. Why?

**Setup.** Every policy was asked about the same 273 CEO positions,
instead of each being scored on boards its own play produced. The table
shows each policy's top proposal per toon.

**Result.**

| Policy | Lure | Trap | Throw | Squirt | Group gag | Fires |
|---|---|---|---|---|---|---|
| `boss_s2` | 83% | 0% | 8% | 1% | 98% | 218 |
| `v2_s3` | 14% | 12% | 33% | 27% | 37% | 478 |
| `v4_s18` | 0% | 0% | 55% | 30% | 30% | 471 |
| `v3_s5` | 0% | 11% | 63% | 24% | 42% | 427 |

`boss_s2` proposes a group Lure four times in five. Every correctly
trained policy proposes single-target attacks and lures 0 to 14% of the
time. It is not the leftover range, seed noise, or a scorer weight.

**Conclusion.** `boss_s2` learned to lure where Lure was overpowered,
and the scorer's prevention weight (`prevent = 9`, validated separately
and worth 45 points on the CEO) wants exactly that behaviour. Its wrong
training happens to produce what climb is looking for.

The structural cause is not a bug in either half. Training scores the
policy on its own top-choice play. Deployment scores it as a proposer
that climb then refines. Those two jobs reward different behaviour. PPO
is trained on parties throughout (16% of positions solo, 31% two toons,
26% three, 28% four) and one network chooses for every toon in turn
while seeing what its teammates have committed, so it coordinates with
itself. What it never sees in training is climb. A Lure it throws in
training is followed by whatever its own top choice is next, usually
another attack and not the attack that exploits the Lure. Scored that
way Lure is weak and the policy correctly learns to skip it. In
deployment climb can pair the Lure with its follow-up, and Lure becomes
the best move on the board. The correctly trained policies are right
about the game they were scored in and wrong about the job they were
given.

This also explains why probes and paired moves do not close the gap.
They can reach a Lure the policy ranks low, but climb still starts from
the policy's top plan, and a sweep that begins on four single-target
attacks does not walk to a coordinated Lure line.

What would fix it, none of it cheap: train with climb in the loop, so
the policy is scored on the play it enables; shape training toward what
a searcher wants, which means deciding that in advance; or generate boss
candidates without the policy.

Shipped at that point: `v2_s3`, correctly trained, 63.5% on CEO 0.
`boss_s2` was withdrawn, because an 88% that rests on a rule the game
does not have is a number about an old bug. (Later policies were shipped
on 2026-08-23 and 2026-08-28; commits f7f1fb0 and a2e9271.)

### 2026-08-22 Training more seeds and picking the best

**Outcome:** refuted. The winner of the selection set lost on held-out sides.

**Question.** If one training seed can differ so much from another, why
not train several and keep the best?

**Setup.** Eight seeds at the better leftover range, scored on a
selection set. The winner was then re-measured against the shipped
`v2_s3` on 200 held-out sides per cell.

**Result.** On the selection set, CEO at zero leftovers ran from 23.3%
to 62.5% across eight policies differing only in training seed, while
buildings sat inside a two-point band (73.3 to 75.0%). `v4_s18` won the
selection at 62.5%. Held out:

| Set | `v2_s3` | `v4_s18` | Paired |
|---|---|---|---|
| Buildings | 72.5% | 66.0% | +5/-18, p=0.005 |
| VP | 99.5% | 99.0% | not significant |
| CEO 0 | 63.5% | 67.5% | +37/-29, p=0.19 |
| CEO 2 | 53.0% | 42.0% | +24/-46, p=0.006 |
| CEO 4 | 24.0% | 18.0% | +19/-31, p=0.06 |

**Conclusion.** Taking the maximum of eight draws from a distribution
that wide selects the friendliest selection draw, not the better policy.
The advantage did not transfer, and the winner was significantly worse
on buildings and on CEO 2. This is the same mistake as fitting a weight
on the set that is then reported. The spread says that a single CEO
number cannot distinguish two policies at this sample size; that needs
many more evaluation sides or an evaluation that is not one
high-variance fight. `v2_s3` stayed shipped.

### 2026-08-28 Track probes on in a party and off solo

**Outcome:** kept. One number argued for turning probes off everywhere; four others refuted it.

**Question.** On a solo VP, climb won 24.8% with track probes against
34.0% without. Should probes be off?

**Setup.** Five sets, 250 runs per cell, same seeds (commit 16b9572).

**Result.** Win rate with probes off, minus win rate with probes on:

| Set | Off minus on |
|---|---|
| Building, solo | +0.4 |
| Building, party | -1.2 |
| VP, solo | +9.2 |
| VP, party | -1.2 |
| CEO, party | -17.6 (20.0% with probes, 2.4% without) |

**Conclusion.** Solo is the only place where turning probes off wins,
and the CEO is where they earn their keep. In a party the joint plan
space is much larger and a per-toon top-k is likely to miss a move that
only works in combination. Solo there is no combination to miss, so the
extra reach only gives an approximate scorer more room to act on its
errors. `probe_tracks=None` now decides from the party size.

---

## Part 2. Scorer weights, consumables and observation versions

These entries date from 2026-08-30 to 2026-09-04 and concern the weights
of `_quick_score`, the prices of pink slips, Unites and SOS cards, and
the PPO observation. Most were recovered from `docs/scoring.md`.

### 2026-08-30 The survive weight double-counted damage prevention

**Outcome:** bug found by a sweep and fixed; the term is now constant across the action menu by construction.

**Question.** `QUICK_W["survive"]` weights a term for how many rounds
the party can survive. What should it be?

**Setup.** The term was `survival_rounds(probe)`, read from the board
after the plan. Solo buildings at difficulty 8, no slips, no
consumables, 200 runs per cell on two independent seed blocks.

**Result.**

| Survive weight | Block A | Block B |
|---|---|---|
| 0 | 26.0% | 27.0% |
| 100 | 21.0% | 25.0% |
| 200 | 16.0% | not run |
| 400 | 10.0% (p=0.000) | 16.5% (p=0.000) |
| 800 | 10.0% (p=0.000) | 14.5% (p=0.000) |

Raising the weight cost sixteen points of ordinary play. Reading the
board after the plan makes the term move with the plan, because killing
or luring a cog lowers expected incoming damage. It therefore paid for
damage prevention a second time, on top of the `prevented` term, and the
extra payment landed on ordinary gag choice where no heal is involved.

The fix: `survival_rounds(state, incoming=...)` takes an override, and
`_quick_score` always passes the expected incoming damage of the board
before the plan. The term then varies only with laff, and nothing in a
plan changes laff. A Toon-Up gag looks as though it should, but healing
is returned separately by the party step and never reaches the probed
board's laff. Measured directly: on a party board with a toon down to
20 laff, a level 7 Toon-Up and a level 7 Throw both receive a survive
contribution of 531.91, which is 800 x 0.6649, the `survival_rounds` of
the unplanned board.

After the fix, solo buildings read 26.0% and 27.0% at every weight from
0 to 800, with +0/-0 seeds moved and identical round counts.

**Conclusion.** The term is a constant across the whole action menu and
cannot reorder it. The only thing it separates is "Unite or SOS applied"
from "not", because those change laff on the state before the plan is
judged. `tests/test_survive_weight.py` pins that property. The behaviour
lock (a fixed set of positions with recorded picks and scores) agreed:
the pick was unchanged on all 120 sampled positions and the score
shifted by a per-state constant between 12.16 and 1600.00 (400 x
`SURVIVAL_CAP`).

### 2026-08-30 Consumables are reserved for hard content without a rule

**Outcome:** kept. Easy content spends no Unites or cards at the shipped prices.

**Question.** Once Unites and SOS cards were switched on, would they
trivialise ordinary play?

**Setup.** Survive weight 400, five Unites held and a full 29-card SOS
book, 120 runs per cell.

**Result.**

| Difficulty | Win | Unites per run | Cards per run |
|---|---|---|---|
| 3 | 100% | 0.00 | 0.00 |
| 5 | 100% | 0.15 | 0.00 |
| 7 | 100% | 2.54 | 0.00 |
| 9 | 42% | 4.88 | 1.16 |
| VP, 12 cogs | 93% | 3.48 | 0.17 |

`SURVIVAL_CAP` was swept as a possible limiter and left at 4.0. Lowering
it reduces consumable use everywhere in proportion (at 2.0: buildings
90.8% on 2.64 Unites, VP 85.8% on 2.38). It does not separate easy
content from hard.

**Conclusion.** Ordinary street play spends nothing. The maintainer's
rule, that standard play should not need consumables `[OWNER]`, falls
out of the prices and needs no exemption for buildings. An earlier
reading that consumables "trivialise buildings" was an artefact of
testing at difficulty 8, near the top of the scale, where a solo toon
wins only 26% without them. A toon losing three fights in four is not
standard play, and spending a heal there is correct. What separates easy
from hard content is how much danger the toon is in, which the survive
term already reads.

### 2026-08-31 The slip price floor raised from 20 to 120

**Outcome:** kept. No slip spent on easy content and nearly one slip fewer per VP at the same win rate.

**Question.** `FIRE_FLOOR` is the minimum price of a pink slip on any
board. It had been swept when a solo VP read about 86%. With consumables
on, the VP reads 94%. Does the floor have room to rise?

**Setup.** Solo runs by difficulty (d3, d5, d9) and solo VP; two seed
blocks where two figures are shown.

**Result.**

| Floor | d3 slips | d5 slips | d9 win | VP win | VP slips |
|---|---|---|---|---|---|
| 20 | 0.63 / 0.58 | 1.16 / 1.12 | 63% / 66% | 95% / 95% | 4.89 / 4.88 |
| 60 | 0.00 / 0.00 | 0.12 / 0.15 | 65% / 70% | 94% / 94% | 4.69 / 4.66 |
| 120 | 0.00 / 0.00 | 0.03 / 0.05 | 65% / 67% | 95% / 94% | 3.96 / 4.03 |
| 200 | 0.00 | 0.03 | 53% | 85% | 2.93 |

**Conclusion.** 120 removes the slip spent on easy content and spends
nearly a whole slip less per VP at the same win rate. 200 is too far.
Difficulty 9 is within noise between 60 and 120; the economy separates
them. The behaviour lock caught the change and was read before being
re-recorded: 9 picks moved, 8 of them from a slip to a gag and one a
gag-to-gag change from the ascent settling differently. All 53 shifted
scores were positions whose scored action is itself a slip, so the floor
reaches slip-bearing plans only, as designed.

### 2026-08-31 A harness fallback that produced four false results

**Outcome:** harness bug; `solver/rl/harness.py` now raises instead of passing.

**Question.** Why did several measurements produce 0% cells that looked
like findings?

**Setup.** Every measurement script re-implemented the same mapping from
an action to an index in the environment's action table, and each ended
with a fallback to the pass action.

**Result.** The pass index means "hold this round", not "this action
could not be expressed". An action the table cannot name became a toon
standing still, and the run reported a strategy failure where the truth
was a harness failure. It cost four measurements:

- A pink slip has no track, so a script that filtered on "has a track"
  passed instead of firing.
- An SOS card had no index at all, so it passed instead of calling.
- Together those read 0% at difficulty 9 and on the VP, against 60% and
  94% from a harness that mapped them.
- A solo toon given Toon-Up training spends part of an 80-gag pouch on
  gags it can never throw, and a pouch built at every gag's carry limit
  sums far past the pouch capacity. Both read 0% too.
- `facility_position` returns no cogs until the environment is reset, so
  a state used before the reset has nothing to fight.

**Conclusion.** `harness.play` raises `UnplayableAction` instead of
falling back, `solo_loadout` builds a valid solo toon, and
`check_position` refuses a board that cannot measure anything. A
measurement that stops is worth more than one that quietly measures the
wrong policy.

### 2026-08-31 The scarcity weight swept and left at 20

**Outcome:** null. No win-rate signal from 0 to 150; left at 20.

**Question.** The maintainer: "It should be weighted by the fact you can
carry 7 \$10 bills and only 3 hypnos" `[OWNER]`. `_gag_units` already
charges `level + SCARCITY_UNITS / carry_limit`, so Hypno-goggles (level
6, carry 3) costs 12.67 against a Small Magnet's (level 2, carry 25)
2.80. Is 20 the right weight?

**Setup.** 0, 20, 60 and 150, 150 runs per cell, through the corrected
harness. "Scarce" is the share of thrown gags whose carry limit is 5 or
fewer.

**Result.**

| Units | d5 win / scarce | d9 win / scarce | VP win / scarce |
|---|---|---|---|
| 0 | 100% / 88% | 13% / 69% | 41% / 78% |
| 20 | 100% / 88% | 10% / 68% | 45% / 78% |
| 60 | 100% / 83% | 8% / 64% | 47% / 75% |
| 150 | 100% / 80% | 8% / 55% | 45% / 69% |

**Conclusion.** Raising the weight does hoard scarce gags (69% to 55% at
difficulty 9), but no win-rate signal separates 0 from 150 at this
sample size, and the two hard cells move in opposite directions. Left at
20: a shipped constant should not move on a wash. The sweep does
establish that Hypno-goggles is 61.5% of Lures thrown at difficulty 9
and 62.2% in the VP, and that this is not the scarcity term failing; the
term is outweighed by a better gag on a multi-cog board.

### 2026-08-31 Why there is no penalty for a group gag on one cog

**Outcome:** left alone. The case occurs twice in about 3,500 group gags.

**Question.** On a one-cog board a group gag and a single-target gag
score identically: a single \$1 Bill and a group \$1 Bill both read
1785.26 on a reported one-cog position. Should the scorer charge for the
wasted breadth?

**Setup.** With a pouch holding nothing below Big Magnet, the panel
advises the group Big Magnet on a lone cog, because at 4 + 20/15 = 5.33
it is cheaper than a \$10 Bill at 5 + 20/7 = 7.86. That is arguably
right: a toon carries 15 Big Magnets and 7 \$10 Bills. From \$10 Bill up
it picks the single bill; from Hypno-goggles up it abandons the Lure and
throws. To see how often the case arises, group gags thrown onto a
single live cog were counted across 150 runs per cell.

**Result.**

| | Group gags thrown | Onto one cog |
|---|---|---|
| Difficulty 5 | 659 | 0 |
| Difficulty 9 | 1,410 | 1 |
| VP, 12 cogs | 1,476 | 1 |

**Conclusion.** Two in about three and a half thousand. A penalty would
be tuning a 0.06% case, and an earlier menu change that looked plausible
and went in unmeasured had cost difficulty 9 eighteen points (60% to
42%).

*Note, 2026-10-10:* all three engines now charge for wasted reach, as a
stated preference of the maintainer and not for wins. See
[2026-10-10 Wasted reach charged by all three engines](#2026-10-10-wasted-reach-charged-by-all-three-engines).

### 2026-08-31 Earlier sweeps used maxed toons so two prices were re-run

**Outcome:** both shipped values held on realistic toons.

**Question.** Every sweep before this date gave the toon maximum
training in every track. A maxed track adds 60 points of accuracy,
against a spread of only 35 points between the weakest and strongest gag
in a track, so against low-level cogs the 95% cap flattens the whole
track and gag choice stops depending on accuracy. Do the conclusions
hold on the toons the building sampler actually produces?

**Setup.** `facility_position` samples a spread of training. Across 300
sampled parties:

| Training level | Tracks | Accuracy bonus |
|---|---|---|
| 2 | 125 | +10 |
| 3 | 465 | +20 |
| 4 | 920 | +30 |
| 5 | 1,458 | +40 |
| 6 | 547 | +50 |
| 7 | 537 | +60 |

About 13% of tracks are maxed. Which conclusions were at risk:
`SCARCITY_UNITS` was not, because only level 6 and 7 gags have a carry
limit of 5 or fewer and a toon trained to 5 holds none. `FIRE_FLOOR` and
`SOS_PRICE` were, because both price a guaranteed effect against a gag
that can miss, and at lower training gags miss more. The survive weight
was mildly at risk.

`FIRE_FLOOR` and `SOS_PRICE` were re-run on the sampler's own toons:
mean training 4.65, parties of two to four matched to their street, 250
runs per cell, paired on seeds.

**Result.**

| `FIRE_FLOOR` | Win | Slips | Against 20 |
|---|---|---|---|
| 20 | 89.2% | 17.33 | |
| 60 | 88.4% | 17.03 | +1/-3, p=0.625 |
| 120 (shipped) | 88.8% | 16.91 | +5/-6, p=1.000 |
| 200 | 85.6% | 16.58 | +3/-12, p=0.035 |

| `SOS_PRICE` | Win | Cards | Against 250 |
|---|---|---|---|
| 250 (shipped) | 88.8% | 0.74 | |
| 400 | 87.2% | 0.47 | +0/-4, p=0.125 |
| 150 | 89.6% | 1.03 | +3/-1, p=0.625 |

**Conclusion.** Both shipped values hold. 120 is indistinguishable from
20 while spending fewer slips, and 200 still overshoots. 250 beats the
old 400 on every seed that moved, and 150 is noise. The maxed-toon bias
is a real limitation of the earlier method and changed neither number.
These are party runs, unlike the solo sweeps above: slips read about 17
a run because each of two to four toons carries five, and pouch, laff
and slips carry across floors.

### 2026-08-31 How good a ranker is the one-round scorer

**Outcome:** good on this benchmark (corrected 2026-09-01 after a seeding bug); later found weak on a different benchmark.

**Question.** `_quick_score` is what climb judges with and what the
weight fits tune, so most of this part of the log rests on it ordering
moves well. It had never been measured against outcomes.

**Setup.** For each sampled position take the best candidate of each
track, so the candidate set is not chosen by the thing under test. Play
the candidate, finish the battle, and repeat 16 times on the same board
with independent dice. Score the candidate by how often it won and
compare that ordering with the scorer's.

**Result.**

| Difficulty | Positions | Rank correlation | Picked the best | Best | Scorer | Random | Worst |
|---|---|---|---|---|---|---|---|
| 5 | 3 | +0.696 | 3/3 | 1.000 | 1.000 | 0.990 | 0.938 |
| 7 | 13 | +0.701 | 13/13 | 1.000 | 1.000 | 0.977 | 0.923 |
| 9 | 94 | +0.545 | 88/94 | 0.991 | 0.987 | 0.887 | 0.755 |

It captures 96 to 100% of the gap between chance and best. On the
largest sample it picks the best candidate in 94% of positions and gives
up 0.004 of win rate.

*The first version of this entry said the opposite, and it was a bug.*
It reported a rank correlation of +0.013 and "captures 24% of the gap",
concluding the scorer was barely better than chance (commit 83a9e65,
retracted in a91b4aa). The environment had been re-seeded identically on
every repeat, so all sixteen playouts of a candidate shared one set of
accuracy rolls and cog attacks. Sixteen repeats were one sample, which
is why every value came out as exactly 1.000 or 0.000. The fix rolls the
round from the captured position with a fresh random generator per
playout. The conclusion drawn from the wrong version, that the flat
weight sweeps might be flat because the ranker could not discriminate,
was withdrawn. Those sweeps are flat for their own reasons.

**Conclusion.** The stakes are usually small. Only 13 of 60 positions at
difficulty 7 had any spread between candidates, and 3 of 120 at
difficulty 5. Where the choice matters, even the worst candidate of each
track wins 76 to 94% of the time. Difficulty 9 is where it matters most
(worst 0.755 against best 0.991) and where the scorer is least sharp.

*Note, 2026-10-01:* on a benchmark labelled by playing whole solo VPs to
the end, the same scorer was barely better than random among climb's own
top four. The two benchmarks differ: this one finishes a single battle
at building difficulty, that one finishes a forty-cog boss fight. See
[2026-10-01 Judging a move by playing the rest of the fight out](#2026-10-01-judging-a-move-by-playing-the-rest-of-the-fight-out).

### 2026-09-01 The survive weight re-run on realistic toons

**Outcome:** 400 holds.

**Question.** The survive weight was the last of three weights still
resting on maxed-toon measurement. Does 400 hold?

**Setup.** The sampler's own toons (mean training 4.65 and 4.71),
parties of two to four matched to their street, 250 runs per cell,
paired on seeds, two blocks.

**Result.**

| Survive weight | Block A | Block B |
|---|---|---|
| 0 | 77.6% | 74.4% |
| 100 | 81.6% (+12/-2, p=0.013) | not run |
| 200 | 86.0% (+21/-0, p<0.001) | 84.4% (+25/-0, p<0.001) |
| 400 (shipped) | 87.2% (+25/-1) | 84.0% (+25/-1) |
| 800 | 87.2% (+26/-2) | 84.8% (+26/-0) |

**Conclusion.** Rising to 200 and flat after, on both blocks, the same
shape the maxed-toon sweep found. 400 sits mid-plateau and stands. All
three weights flagged as dependent on maxed toons have been re-run and
all three held.

### 2026-09-01 What the scorer gets wrong at difficulty 9

**Outcome:** nothing changed. The six misses are the residual of a weight that is right.

**Question.** The ranker study left one lead: at difficulty 9 the scorer
was wrong on 6 of 94 positions. What are they, and can they be fixed?

**Setup.** The six positions were decomposed term by term, and the
prevention weight was swept on the same ranking benchmark.

**Result.** All six misses are the same mistake. On a fresh board of
three or four cogs, none lured or trapped, the scorer takes a long group
Lure where the outcomes prefer group Sound. (The move names in the table
are as originally recorded. The original text calls the preferred move
group Sound while the table labels it Railroad, which is a Trap; the 360
damage across four cogs in the decomposition fits a level 7 Sound.)

| Seed | Scorer picked | Won | Best by outcome | Won | Score gap |
|---|---|---|---|---|---|
| 770015 | Presentation, all | 0.88 | Railroad, all | 0.94 | +1042.6 |
| 770032 | Presentation, all | 0.94 | Railroad, all | 1.00 | +918.8 |
| 770059 | Presentation, all | 0.94 | Railroad, all | 1.00 | +1049.1 |
| 770091 | Presentation, all | 0.94 | Railroad, all | 1.00 | +1072.6 |
| 770104 | Wedding Cake, all | 0.94 | Railroad, all | 1.00 | +706.1 |
| 770110 | Presentation, all | 0.94 | Railroad, all | 1.00 | +914.9 |

Decomposed on seed 770032 (four cogs, levels 10, 9, 11, 10):

    Presentation/all   0 damage, 0 kills, prevented 144.7 x 9.0 = 1301.9
                       total 1898.5
    Railroad/all     360 damage, 0 kills, prevented   0.0        =    0.0
                       total 1003.7

So the cause is `QUICK_W["prevent"] = 9.0`: a point of prevented damage
is worth nine of dealt damage, and an eight-round group Lure on four
cogs prevents a great deal. Lowering the weight makes the ranker much
worse:

| Prevent weight | Rank correlation | Picked the best | Captures |
|---|---|---|---|
| 4 | +0.269 | 49/99 (49%) | 38% |
| 6 | +0.418 | 69/96 (72%) | 80% |
| 9 (shipped) | +0.545 | 88/94 (94%) | 96% |
| 12 | +0.516 | 91/97 (94%) | 97% |
| 18 | +0.514 | 92/98 (94%) | 97% |
| 30 | +0.478 | 94/99 (95%) | 97% |

**Conclusion.** 9.0 sits at the bottom edge of a broad plateau. Below it
the ranker falls apart (regret rises from 0.004 to 0.073 at 4.0) and
above it nothing improves. The residual is worth 0.004 of win rate and
every way of chasing it costs more.

### 2026-09-01 Observation version 3 is indistinguishable from version 2

**Outcome:** null. Left at version 3 on an argument, not on a measurement.

**Question.** `env.OBS_VERSION` is 3, so every policy trained from this
date uses it, but nothing trained at 3 had shipped. Version 3 adds each
toon's absolute remaining laff (four per-toon scalars become five, 302
inputs become 306). Is it better?

**Setup.** Three training seeds at version 3 against the same three at
version 2, judged on the toons the building sampler produces.

**Result.** With consumables, near the ceiling, there is no signal:

| Seed | Version 2 | Version 3 | Paired |
|---|---|---|---|
| 51 | 97.2% | 97.6% | +3/-2 |
| 52 | 97.2% | 97.6% | +4/-3 |
| 53 | 97.2% | 96.8% | +2/-3 |

Without consumables, where the cell discriminates:

| Block | Seed | Version 2 | Version 3 | Paired |
|---|---|---|---|---|
| 770000 | 51 | 74.8% | 73.2% | +7/-11 |
| 770000 | 52 | 73.6% | 71.6% | +9/-14 |
| 770000 | 53 | 76.0% | 74.8% | +8/-11 |
| 660000 | 51 | 75.6% | 74.4% | +8/-11 |
| 660000 | 52 | 73.6% | 73.6% | +12/-12 |
| 660000 | 53 | 74.0% | 74.4% | +13/-12 |
| 880000 | 51 | 74.4% | 73.6% | +9/-11 |
| 880000 | 52 | 71.6% | 73.2% | +14/-10 |
| 880000 | 53 | 74.0% | 74.4% | +14/-13 |

Pooled over all nine: +94/-105, p=0.478, a mean of -0.49 points, with
version 3 losing 5 of 9.

The training-time metric says the opposite. `eval_return` at export
averaged 35.90 for version 2 and 40.51 for version 3, and version 3 won
all three pairs.

**Conclusion.** Indistinguishable. The first block alone had read -1.60
with three losses from three, and was first reported as version 3
losing. That was one block of noise presented as a result: three paired
runs is not a sample.

Left at 3. It is not worse, and the argument for it is one the
measurement cannot see. The two existing laff features are a ratio and
a ceiling, and what decides a fight is their product: half of 137 laff
survives a Legal Eagle's attack and half of 40 does not. A linear layer cannot
multiply, so handing it the product is more information for four more
inputs. This has the same standing as `SCARCITY_USES_HELD_COUNT` below:
neutral on measurement, kept on the argument, and labelled as such. The
shipped policy at this date predated the version field and did not use
version 3.

### 2026-09-01 Crediting lured cogs for the quiet they will actually provide

**Outcome:** kept. Neutral in buildings, worth 17 to 27 points on large solo VPs.

**Question.** `SLEEPERS_WAKE_IN_TURN` (formerly `PER_COG_REACH`) credits
four lured cogs with 1+2+3+4 rounds of silence, not 4+4+4+4, since the
cog about to die was never going to stay asleep. It shipped on a
judgement call: it helped at 12 cogs a round and hurt at 8. Does that
still hold after the search budget was raised to 24, consumables were
added and the survive weight went to 400?

**Setup.** Building play, 250 runs per cell on two seed blocks. Solo VP
at several round sizes, 200 runs per cell, paired.

**Result.** Buildings: 88.0% against 86.8% (+1/-4, p=0.375) and 84.4%
against 84.8% (+1/-0, p=1.000). On a sampled board the flag moves
`prevented` from 110.54 to 174.87 and the score by 550 points, and still
decides almost nothing outside the VP.

| Solo VP, cogs a round | Flag on | Flag off | Paired |
|---|---|---|---|
| 8 | 99.0% | 99.0% | +0/-0 |
| 12 | 100.0% | 99.5% | +1/-0 |
| 16 | 93.0% | 66.5% | +58/-5, p<0.001 |
| 16 (held out) | 85.0% | 67.5% | +47/-12, p<0.001 |
| 20 (held out) | 26.5% | 15.0% | +40/-17, p=0.003 |

**Conclusion.** The old worry is gone. At 8 cogs the flag is exactly
neutral, and at 16 and 20 it is worth 17 to 27 points. The original
reading was taken before the budget was raised, before consumables
existed and with the survive weight at zero. This flag and three related
ones (`LURE_IS_SPENT_ON_SLEEPERS`, `LURED_KILL_SILENCES_NOTHING`,
`SURVIVAL_CAP`) carry a pointer in `weights.py` to
`party_search.prevented`, where their reasoning is written out.

An earlier version of this entry claimed +0/-0 across 500 building
games. That came from a broken harness; see
[2026-09-01 A sweep script that swept the wrong knob](#2026-09-01-a-sweep-script-that-swept-the-wrong-knob).

### 2026-09-01 Should scarcity price the carry limit or the count held

**Outcome:** switched to the count held, on the argument. Measured as a small, non-significant negative.

**Question.** The maintainer, looking at a pouch with nine Big Magnets:
"shouldn't it be scaled by 9 not 15, since that's how many magnets I
actually have" `[OWNER]`. The carry limit prices how replaceable the gag
type is and does not move as the pouch drains. The count held prices
what would be missed now, and rises as gags are spent.

**Setup.** Implemented behind `SCARCITY_USES_HELD_COUNT` and measured
paired on seeds: solo VP at 12, 16 and 20 cogs, and building play at
250 runs per cell, then at four seed blocks (1,000 runs per cell).

**Result.** On the pouch in question it changes no ordering:

| Gag | Carry limit | Held | Price by carry limit | Price by count held |
|---|---|---|---|---|
| Big Magnet | 15 | 9 | 5.33 | 6.22 |
| \$10 Bill | 7 | 6 | 7.86 | 8.33 |
| Hypno-goggles | 3 | 3 | 12.67 | 12.67 |
| Presentation | 1 | 1 | 27.00 | 27.00 |

Solo VP: +0/-0 in every cell. Buildings:

| Block | Carry limit | Count held | Paired | Gags spent |
|---|---|---|---|---|
| 440000 | 88.8% | 88.0% | +1/-3 | 14.2 to 14.0 |
| 990000 | 85.2% | 84.4% | +1/-3 | 16.1 to 15.5 |
| 660000 | 88.4% | 88.0% | +2/-3 | 15.1 to 14.7 |
| 770000 | 87.6% | 88.0% | +2/-1 | 13.7 to 13.5 |

Pooled +6/-10, p=0.454, a mean of -0.40 points, negative in 3 of 4
blocks. It does its job: 2.4% fewer gags spent, in every block.

Why it changes so little: the whole price term is a median 4.79% of
`_quick_score` (mean 5.53%, maximum 13.24% across 120 boards). The
scarcity half at its most extreme, a last Big Magnet going from 5.33 to
24.00, moves 18.67 points on a score of about 1500, or 1.24%. Damage and
prevention dominate by two orders of magnitude, so no scarcity rule at
this weight can change the chosen move. That also explains the earlier
`SCARCITY_UNITS` sweep reading flat from 0 to 150: the rule is not
wrong, the lever is too short.

**Conclusion.** Turned on, on principle and not on measurement, and
recorded so nobody reads it as evidence-backed. The maintainer: "Sure,
but logically we should use the held count anyway" `[OWNER]`. Nothing
restocks mid-run, so the cost within the run is what the solver is
optimising, and the carry limit cannot express it. Combined with the
horizon scaling of the price, scarcity gives "dear when scarce and
early, cheap when scarce but last", the shape the slip price had to be
rebuilt to get. The switch moved 1 pick of 120 in the behaviour lock and
no scored value. If the price weight is ever raised, watch this: at a
longer lever a last gag of a kind would cost nearly what a Presentation
costs, and a gag carried out of a fight unspent is worth nothing.

An earlier version of this entry reported +0/-0 on buildings. That came
from the broken harness described two entries below.

### 2026-09-01 The price weight cannot be tuned on its own

**Outcome:** stays at 1.0. The real finding is that one multiplier priced gags and consumables together.

**Question.** After finding scarcity too short a lever, what does
sweeping the whole price weight, `QUICK_W["price"]`, show?

**Setup.** The price it multiplied was assembled from three sources: the
gags spent (scaled by the horizon), the slip price times slips fired,
and `SOS_PRICE` times cards called. Turning the weight down therefore
made gags, slips and cards free together. Building play on two seed
blocks.

**Result.** The first sweep, with consumables on:

| Price weight | Win | Gags | Slips |
|---|---|---|---|
| 0.0 | 91.6% / 89.6% | 10.2 | 16.5 |
| 1.0 (shipped) | 88.0% / 84.4% | 14.0 | 17.1 |
| 2.0 | 83.6% | 12.4 | 18.6 |
| 4.0 | 76.4% | 10.0 | 19.9 |
| 16.0 | 60.0% | 6.8 | 20.5 |

Zero beating one on both blocks (p=0.022, p=0.015) is not a finding
about gag conservation. It is unpriced consumables. The same sweep with
no slips, Unites or cards, so the multiplier reaches gags only:

| Price weight | Block A | Block B | Gags |
|---|---|---|---|
| 0.0 | 68.8% | 62.8% | 28.6 / 30.9 |
| 0.5 | 67.2% | 61.2% | 27.6 / 29.2 |
| 1.0 (shipped) | 68.4% | 62.0% | 27.7 / 28.1 |
| 2.0 | 68.0% | 60.8% | 26.7 / 27.1 |
| 4.0 | 64.4% (p=0.052) | 54.8% (p<0.001) | 24.6 / 25.8 |

**Conclusion.** Anything from 0 to 2 is indistinguishable and 4 clearly
hurts. Higher weights conserve (about 15% fewer gags at 4.0) and buy
nothing with it. 1.0 stands. Gag thrift could not be tuned without
unpricing consumables, so the multiplier was split (two entries below).

### 2026-09-01 A sweep script that swept the wrong knob

**Outcome:** harness bug; three claims were re-measured and corrected.

**Question.** Why did several sweeps return +0/-0?

**Setup.** A scratch sweep script dispatched on the name of the knob
being swept, with a final `else` branch that set `SOS_PRICE`.

**Result.** Every knob added later (the prevention weight, the
lured-cog credit, the held-count scarcity flag, the price weight) fell
through that `else` and swept `SOS_PRICE` instead. The edits that were
meant to add branches for them had been made with string replacements
that did not match and failed silently.

**Conclusion.** A catch-all in a measurement harness is the same defect
as the pass fallback in a play harness: it turns "I cannot do what you
asked" into a plausible number. The dispatch now names every knob and
raises on an unknown one. Three claims were re-measured and corrected in
the entries above. `FIRE_FLOOR`, `SOS_PRICE`, the survive weight and the
search budget were never affected, because those knobs had real
branches.

### 2026-09-01 The price multiplier split into one for gags and one for consumables

**Outcome:** kept. Both weights stay at 1.0; the consumable weight is a stated preference and not to be tuned for win rate.

**Question.** With `price` weighting gags and a new `spend` weighting
slips and cards, what does each sweep show?

**Setup.** `_score_leaf` builds the gag price and the consumable price
separately and scales each by its own weight. At 1.0 and 1.0 the old
arithmetic is reproduced exactly (the behaviour lock is clean across all
eleven pinned values). Building play with consumables on.

**Result.**

| `price` | Win | Gags | Before the split |
|---|---|---|---|
| 0.0 | 86.8% (+6/-9, not significant) | 15.5 | 91.6% (+11/-2, p=0.022) |
| 1.0 (shipped) | 88.0% | 14.0 | 88.0% |
| 2.0 | 87.2% (+5/-7, not significant) | 11.9 | 83.6% |
| 4.0 | 82.0% (+4/-19, p=0.003) | 10.4 | 76.4% |

| `spend` | Win | Gags |
|---|---|---|
| 0.0 | 92.4% (+12/-1, p=0.003) | 10.1 |
| 1.0 (shipped) | 88.0% | 14.0 |
| 2.0 | 83.2% (+2/-14, p=0.004) | 15.4 |
| 4.0 | 80.4% (+2/-21, p<0.001) | 15.9 |

**Conclusion.** `price = 0` had looked like a win and was unpriced
consumables; it is now indistinguishable from 1.0. A usable conservation
setting appears: `price = 2.0` spends 11.9 gags against 14.0, about 15%
of the pouch, for 0.8 points that do not survive a sign test. That trade
was invisible before the split.

Free consumables win by four points, significantly. That is the expected
answer and not a reason to change anything: cheaper cards always clear
more, and the search would be right about the number while spending a
currency earned from whole boss runs. The maintainer's position is that
slips are for bosses and cards are a last resort `[OWNER]`. The price
encodes reluctance, not win maximisation, and the split lets that
preference sit on its own axis.

### 2026-09-02 Six fresh policies and nothing to promote

**Outcome:** null. No policy promoted; the training-time metric disagreed with play for the third time.

**Question.** Should a version 3 policy be trained and promoted, given
that the shipped policy predated the version field?

**Setup.** Three training seeds at observation version 3 and the same
three at version 1, 6 million steps each, paired by seed. Held-out play
at 250 runs per cell.

**Result.** Training-time `eval_return` favours version 1 in 3 of 3:

| Seed | Version 3 | Version 1 | Difference |
|---|---|---|---|
| 71 | 35.47 | 44.58 | +9.11 |
| 72 | 41.05 | 43.46 | +2.41 |
| 73 | 37.24 | 41.35 | +4.11 |
| Mean | 37.92 | 43.13 | +5.21 |

Held-out play says they are the same:

| Cell | Version 3 | Version 1 | Paired |
|---|---|---|---|
| With consumables | 96.4% | 96.4% | +10/-10, p=1.000 |
| Without (discriminating) | 70.1% | 71.2% | +26/-34, p=0.366 |

Against the shipped policy, in the discriminating cell:

| Policy | Win | Against shipped |
|---|---|---|
| Shipped | 68.8% | |
| Fresh, version 3, seed 71 | 70.4% | +12/-8, p=0.503 |
| Fresh, version 3, seed 72 | 70.0% | +12/-9, p=0.664 |
| Fresh, version 3, seed 73 | 70.0% | +10/-7, p=0.629 |
| Fresh, version 1, seed 71 | 70.4% | +12/-8, p=0.503 |
| Fresh, version 1, seed 72 | 70.4% | +13/-9, p=0.523 |
| Fresh, version 1, seed 73 | 72.8% | +18/-8, p=0.076 |

**Conclusion.**

- This is the third time `eval_return` and play disagreed, and the
  second time in opposite directions: it preferred version 3 in the
  earlier comparison and version 1 here, while play called both even.
  `eval_return` is a training-progress signal, not a ranking.
- Every fresh policy beats the shipped one by 1.2 to 4.0 points, none
  significantly. They share evaluation seeds, so a sign test across
  policies is not valid. Promoting the best of six at p=0.076 would be
  the same selection that the 2026-08-22 entry refuted. The shipped
  policy stays.
- The shipped policy had a reputation as a 3.8 standard deviation
  outlier from an earlier, different measurement. In this cell it is the
  worst of seven. That reputation should not be carried into new
  comparisons unexamined.
- `OBS_VERSION` stays at 3. There is no evidence to move it either way,
  and no positive case for it beyond the argument that a linear layer
  cannot multiply a ratio by a ceiling.

### 2026-09-04 Widening the menu of climb to 16

**Outcome:** kept. Solo VP 48% to 75% on held-out seeds; buildings unmoved. This reverses the 2026-08-21 conclusion for the solo VP.

**Question.** The PPO row and the Search row disagreed on some boards.
Is that climb's weights, or what it is offered?

**Setup.** Every plan the scorer was asked to judge was logged on four
boards where the two engines disagreed. Then solo VPs at 20 cogs a
round with everything carried, paired on identical seeds, and multi-floor
buildings with parties averaging 2.6 toons (commits 391f0e1, 2fc36f3,
7fccf0e, e01a15c).

**Result.**

| Width | The search's move was offered | Climb agreed with it |
|---|---|---|
| 3 | 0 of 4 | 0 of 4 |
| 8 | 2 of 4 | 2 of 4 |
| 16 | 4 of 4 | 3 of 4 |

A first check at 10 runs per cell read 80%, 70% and 80% cleared at
widths 3, 8 and 16, and the width was left at 3. The maintainer did not
accept "it buys nothing" on 10 runs, and a larger sample showed the gain:

| Solo VP runs | Seeds | Width 3 | Width 16 | Paired |
|---|---|---|---|---|
| 25 | selection | 60% | 76% | +6/-2 |
| 40 | held out | 48% | 75% | +15/-4, p=0.019 |

Buildings: 82% at both widths, +0/-0 over 40 paired runs. Cost: 20 ms
to 26 ms a decision.

Width and budget are coupled. The budget counts scorer calls and the
loop stops when it is spent, so a menu wider than the budget never
reaches the probes appended after the policy's own entries (the
cheapest kill, the cheapest Lure, the SOS list). On a board with one
trapped cog:

| Width | Budget | Move |
|---|---|---|
| 16 | 8 | Foghorn, wasting the armed trap |
| 16 | 24 | \$1 Bill, springing it |
| 32 | 24 | Small Magnet, starved again |
| 32 | 48 | \$1 Bill |

**Conclusion.** At width 3 the scorer never saw the search's move, so no
weight on price or waste could reach it; those earlier sweeps were
measuring a menu and not a scorer. An earlier reading that width 32 was
worse than width 3 (+3/-7) was budget starvation. The default budget was
raised to 24 to match. The gain is specific to where the pouch binds: a
solo VP is 40 cogs with 4,255 cog HP against a pouch worth about 2,730
single-target damage, while a two-floor building shared by three toons
never gets near that constraint.

---

## Part 3. From a one-round judge to playouts

The first two entries are attempts to give climb a longer view. Both
were switched off for measured reasons and their code was removed on
2026-10-05; the text records what the code's own notes said. The rest of
this part is the Playout engine as it was built from 2026-10-01 to
2026-10-06, reconstructed from commit messages and from the notes in
`solver/search/playout.py`.

### 2026-08-17 A PPO rollout as the judge for climb

**Outcome:** refuted and later removed. Deeper rollouts were monotonically worse.

**Question.** `_quick_score` judges one round. Can climb judge a plan by
playing it and then letting the PPO policy play on for a few rounds,
totalling the reward the training environment pays? This is rollout
with the learned policy as the base policy.

**Setup.** 180 held-out buildings, climb at budget 8. Every candidate
plan was rolled out from the same seed (common random numbers). This was
not the same as an earlier two-round judge that let a greedy planner
answer for the next round, which had cost nearly three points.

**Result.**

| Judge | Buildings finished | Time |
|---|---|---|
| `_quick_score`, one round | 64.4% | 0.76 ms |
| PPO rollout, two rounds | 61.1% | 2.50 ms |
| PPO rollout, four rounds | 60.6% | 3.23 ms |

Other observations recorded with it: four random weight vectors for
`_quick_score` finish 62.5 to 65.0% of the same buildings, and zeroing
every term costs five points, so the terms matter and their sizes
barely do. PPO's own value estimate ranking PPO's samples scored 57.8 to
58.3% against 58.9% for the policy's plain top choice. `_quick_score` as
the judge is worth 58.9% to 64.4%. Toon-Up use rose from 4.1% to 5.3%
with rollouts on, so the longer view pushes in the right direction.

**Conclusion.** Scoring a plan by what happens when PPO plays on
measures how well PPO exploits the resulting position, not how good the
position is. A strong plan that leads somewhere PPO handles badly is
marked down. The idea of a horizon is not refuted; asking the policy to
grade itself is. This was the third time that was established: the
policy's own value estimate and the greedy two-round lookahead had both
lost before it. The judge that helped was one that shares none of the
proposer's blind spots.

*Note, 2026-10-01:* superseded by the Playout engine, which changes the
three things that sank this: it plays to the end of the fight and not
two to four rounds, it scores cogs defeated and not a reward with no
credit for damage, and it averages many rollouts and not one seed. See
the next entries.

### 2026-09-30 Crediting a restock card with the round it enables

**Outcome:** null and later removed. It made restocks happen and clears did not move.

**Question.** A restock SOS card deals nothing and prevents nothing in
the round it is played, so `_quick_score` scored it exactly `SOS_PRICE`
below a pass. On a solo VP that had spent its strongest gags, "wait for
the Lure to lapse, lure again, wait" beat restocking forever (on one
such board a pass scored 672.7 and Restock All 422.7). Should a restock
be judged on what it enables next round?

**Setup.** `RESTOCK_LOOKAHEAD` touched only plans that call a restock,
and credited only the difference between next round with the restock
and next round without it. With a full pouch that difference is near
zero. Solo VP, realistic loadout, 100 paired sides with common random
numbers.

**Result.** 13 of 100 without, 14 of 100 with, +4/-3, sign test p=1.00.
Restocks went from 0.00 to 0.63 a side and cards were spent a little
more.

**Conclusion.** Null. The sweep also ran without the boss structure
(the engine did not know how many cogs were still to come), which by
itself cost 13 to 5. The Playout engine replaced the need for it.

### 2026-10-01 Judging a move by playing the rest of the fight out

**Outcome:** kept. Solo VP wins roughly tripled against the PPO row. This is the origin of the Playout row.

**Question.** If the one-round scorer cannot see the rest of a fight,
does playing each candidate move to the end of the fight judge it
better?

**Setup.** Solo VP: one toon against 20 cogs and then 20 skelecogs.
Each of climb's top three moves is played to the end of the fight eight
times and the best mean is kept. A playout starts from the board a
player sees. Cogs the player cannot see, the rest of this round and the
later round, are drawn fresh in each playout from the level band the
wiki gives, in the numbers the boss tracker says are coming. Without
such a horizon (a street, a building) the playout ends with the battle
on screen, because the next floor is unknown to the player too. The
unit of score is cogs defeated.

A benchmark was built first: positions from solo VPs with each
candidate labelled by playouts. On it, the one-round scorer's regret
was 0.65 cogs against 0.73 for picking at random among climb's own top
four.

**Result.**

| Solo VP | PPO row (climb) | Top 3 played out 8 times | Paired |
|---|---|---|---|
| 500 sides | 36 (7.2%), 31.3 cogs defeated | 106 (21.2%), 33.2 cogs | +90/-20, p<0.0001; +1.87 cogs a fight (se 0.35) |
| 200 fresh sides, through the shipped module | 10 (5.0%) | 54 (27.0%) | +50/-6, p<0.0001; +3.02 cogs a fight (se 0.56) |

Two formulas fitted to the same playout labels were tried as
replacement scorers and lost in play: 3.6% and 0.4% against climb's 7%.

**Conclusion.** The playouts are the judge. A formula fitted to
one-decision labels fails because a label holds only while the old
player plays on, and a fitted judge used every round is a different
player. All figures in this entry were measured before 2026-10-06, when
Unites were unusable in simulation; see
[2026-10-06 Unites were never spent in simulation](#2026-10-06-unites-were-never-spent-in-simulation).

### 2026-10-01 The playouts choose what gets played out

**Outcome:** kept. A menu built for diversity doubled solo VP wins over the scorer's top three.

**Question.** The first version played out the scorer's top three
moves. Is the scorer a good filter for what deserves a playout?

**Setup.** On the playout-labelled benchmark, the scorer's top four
were compared with four random entries from climb's menu. Then
`wide_candidates` was built: climb's pick, the scorer's and the
network's top two, the scorer's best move of every kind climb
considered (each track, single and group, each kind of SOS card, a pink
slip), and the pass, up to ten. Successive halving drops the weaker
half of the candidates after set numbers of rollouts, with common
random numbers throughout. 200 fresh paired solo VP sides.

**Result.** Four random menu entries beat the scorer's own top four
(+0.92 against +0.70 cogs over an average candidate), and the best move
lay outside the scorer's top four in 49% of positions.

| Solo VP, 200 sides | Top 3, 8 rollouts each | Wide menu |
|---|---|---|
| Cleared | 38 (19.0%) | 79 (39.5%) |
| Paired | | +57/-16, p<0.001 |

**Conclusion.** The one-round scorer must not choose what gets played
out. Two panel changes went with it. Playouts run in chunks and the
best move so far is posted after each; the move on screen changes only
when a challenger leads by more than one paired standard error, because
without that rule the advice flipped between four moves on noise during
a VP opening. The playouts were also split across four processes with
the same seeds, so the numbers match a single process: the first move
appears in 1.5 s instead of 3.0 s, and eight rollouts per candidate
take 2.3 s instead of 5.8 s.

### 2026-10-01 A fast network plays out the rest of each fight

**Outcome:** kept. Slightly worse per rollout than climb and four times as many in the same time: 111 wins against 71 of 200.

**Question.** 91% of a playout's time was climb choosing each later
round. Can a small network that imitates climb play the rollouts
instead?

**Setup.** `fastplayer` takes the environment's observation plus the
SOS cards held, and outputs the environment's 250 actions plus one per
SOS card. It was trained on climb's decisions over solo VPs, buildings
and street fights, with two DAgger rounds (the network plays, climb
labels the positions it reaches). It matched climb on 79% of held-out
decisions at about a tenth of the cost. Solo VP, 200 paired sides, wide
menu.

**Result.**

| Rollout player | Rollouts per halving stage | Wins of 200 | Time per move | Against climb |
|---|---|---|---|---|
| climb | 2 / 4 / 8 | 71 | 3.37 s | |
| network | 2 / 4 / 8 | 63 | 0.78 s | p=0.42 |
| network | 8 / 16 / 32 | 111 | 3.06 s | +60/-20, p<0.001, +2.83 cogs a fight (se 0.63) |

Climb's own budget inside a rollout was also reduced from 24 to 8,
which tied on 200 paired solo VPs (72 against 78 wins, +37/-43, p=0.58)
at half the cost.

**Conclusion.** The network is the default rollout player, with climb
as the fallback when the weights or numpy are missing. Volume matters
more than the last bit of rollout quality.

*Note, 2026-10-11:* this network was replaced by one trained on the
Playout engine's own choices. See
[2026-10-11 Expert iteration for the rollout network shipped](#2026-10-11-expert-iteration-for-the-rollout-network-shipped).

### 2026-10-02 Playouts for parties

**Outcome:** pickup playouts kept (+20 wins in 600 party buildings); coordinated planning shown to matter far more than who plays the rollouts; two nulls recorded.

**Question.** The fast network knows one seat. How should the Playout
engine handle a party, and do more rollouts help?

**Setup.** Three variants, each a paired sweep. *Joint plans:* the
candidates are joint plans from climb's menu, kept diverse by what each
toon does, and climb plays out the rest. *Pickup:* the candidates are
your moves alone, the fast network plays you, and each rollout draws
the teammates' moves from `SensiblePrior`. *Coordinated:* the engine
plans on a board carrying the teammates as toons and shows your part of
the party's best joint plan.

**Result.**

| Sweep | Baseline | Variant | Paired |
|---|---|---|---|
| CEO, two toons, two leftovers, 200 sides: climb against joint-plan playouts | 43 | 48 | +16/-11, p=0.44 |
| Solo VP, 200: halving at 8/16/32 against 16/32/64 rollouts | 139 | 146 | +36/-29, p=0.46, at twice the time |
| Party buildings, 600 sides: climb against pickup playouts | 268 | 288 | +34/-14, p=0.006, 0.25 s a decision |
| Party VP, 300 sides: climb against pickup playouts | 0 | 1 | uninformative |
| Laff tiebreak, solo VP 200 / solo buildings 600 | 123 / 66 | 119 / 69 | no harm either way |
| 40 party VPs: each toon planned alone against the party planned together | 0 | 23 (26 with joint-plan playouts) | |

The laff tiebreak adds at most half a cog for the laff the team has
left. Without it, a playout that ends with the battle on screen scored
every sensible move the same (all four cogs die) and the scorer's pick
won by default.

**Conclusion.** More than 32 rollouts per move did not pay with full
playouts, so the cap stayed at 32. Joint-plan playouts on the CEO were
neutral. In party VPs, uncoordinated toons each spend their level 7
gags on the first round and meet the skelecogs unlured, whether the
teammate is `SensiblePrior` or climb. `playout.GROUP_MODE` defaults to
"coordinated", with "pickup" for playing with strangers. The Search row
and the TTR panel keep allies as a count.

*Note, 2026-10-05:* the 40 party VPs were run when the simulator gave a
two-toon side the solo fight's 20 + 20 cogs. At the corrected 10 + 10 a
two-toon side wins 40 of 40 with either engine. See
[2026-10-05 Boss rounds sized by who came](#2026-10-05-boss-rounds-sized-by-who-came).

### 2026-10-05 Reading gag counts and cog levels from recorded frames

**Outcome:** kept. These results are from frames of a running game, not from simulation.

**Question.** How reliable are the screen readers on real frames, and
what do learned digit classifiers and a memory of the open menu add?

**Setup.** A recorded solo building run from a running TTR client (a
compressed video, whose blur is harder on the digit reader than a
lossless capture), with 45 frames showing the gag menu, plus a
hand-labelled benchmark of 168 menu cells from two lossless screenshots
and four recorded frames. Four changes were measured in turn
(commits 68c7ad4, 3172479, 8b92fb9, 29dcdb4):

1. *Refuse instead of pass.* The checksum against the menu's "Total
   gags" label returned "no problem" whenever the label could not be
   read, and it cannot be read while a gag is hovered. Now a count above
   the gag's carry limit is always refused, and with no label a doubtful
   cell is refused.
2. *Cropping by brightness.* Ink had been "near-white and barely
   coloured"; video colour bleed tints thin white strokes blue and they
   failed the colour test. Ink is now brightness clear of the cell's own
   background, and only the right-aligned run of glyphs is kept.
3. *A small classifier* trained on synthetic digits in the game's font,
   distorted the way real frames are, for counts and for the level on a
   cog's plate.
4. *Menu memory.* Counts cannot change while the menu is open, so every
   poll votes on each cell and a doubtful read takes the cell's settled
   value.

**Result.**

| Step | Menu frames accepted of 45 | Notes |
|---|---|---|
| Before | 25 | Most of them wrong: totals of 107 and 113 for a 40-gag pouch, cells read as 62 and 81 |
| 1. Refuse on doubt | 3 | Those 3 are confidently misread |
| 2 and 3. New cropping and classifier | 38 | Every one consistent with a pouch that only falls, every checked one right |
| 4. Menu memory | 42 | The 3 refused are a menu's first frame with the cursor on a digit |

| Benchmark of 168 cells | Correct |
|---|---|
| Old reader | 151 |
| New cropping | 166 |
| New cropping and classifier | 167 |

The one miss is the mouse cursor sitting on a digit; a glyph outside the
counts' fixed size band is now treated as doubtful whatever the
classifier says.

Cog levels: a clear "Level 6" plate with the cog's head behind it had
read 6 at 0.691 over 8 at 0.679 and was refused, which blocks the whole
board. With the classifier every real plate on hand reads at full
confidence, including all 57 battle plates in the recorded run. Those
are levels 5 and 6 only. Other levels rest on the synthetic hold-out
(99.9%) and unchanged confidence gates. A level picker on the panel
lets the player state a level the reader cannot settle.

**Conclusion.** The readers refuse a frame they are unsure of, and the
panel retries. One apparent error of the memory step turned out to be
an error in the hand count.

### 2026-10-05 The hover card of the gag menu as a third check

**Outcome:** not shipped. The card's count reads; naming which gag the card describes does not.

**Question.** Hovering a gag replaces the "Total gags" label with that
gag's card, whose "N / M" line states the hovered gag's count exactly.
Can that check the cell under the cursor, the one most likely misread?

**Setup.** The recorded building run from the previous entry (a running
game).

**Result.** Reading the card's count worked ("7 / 7", "4 / 10",
"0 / 20") once ink was taken by brightness, fragments were joined by
column, and the line was split clear of the gag's picture. Identifying
which cell the card describes did not: matching the card's picture
against every cell's picture, with backgrounds painted out, won by
margins of 0.002 to 0.11 and named the wrong cell on most frames (the
Safe as the level 5 Throw gag, or a level 1 Throw gag the toon did not
carry). The card's capacity alone is ambiguous whenever two gags share a
carry limit.

**Conclusion.** A reader that names the wrong cell would overwrite a
good count with another gag's. Menu memory already resolves the cursor
case on 42 of 45 recorded menu frames, and the rest are a menu's first
frame, which the panel's retry covers. A future attempt needs a better
way to name the gag: the card's title text, or the cursor's position.

### 2026-10-05 Valuing the pouch when a playout stops at the floor

**Outcome:** kept at weight 2. It changes which gag is advised and no measurable outcome.

**Question.** A playout in a building ends with the floor on screen,
and the gags left over were worth nothing. So on a lone Tightwad at 32
of 56 HP the Playout row chose Foghorn (95%) over Whole Cream Pie (90%),
spending one of two Foghorns. The maintainer threw the pie: "using it
on a single cog is inherently wasteful since Foghorn COULD do 50 to all
cogs" `[OWNER]`. Should the remaining pouch have a value?

**Setup.** When a playout stops before the fight does, its score adds
the remaining pouch's worth as a fraction of its worth at the decision,
weighted by `POUCH_WEIGHT` cogs. Two versions were measured on 600
paired buildings each (commits 2c3c050, 0d068ea). In the first a gag is
priced as the search prices a throw, its k-th last copy at (1 + 1/k) of
that, and a group gag at twice. In the second a gag's worth is the
damage it could deal later: damage per cog times the cogs it can expect
to hit, 1 for a single-target gag and `GROUP_REACH` = 2.5 for a group
gag. The 2.5 is the maintainer's figure `[OWNER]` and is not measured.

**Result.** The maintainer's toon (54 laff, 40-gag pouch) in Daisy
Gardens buildings, buildings cleared of 600:

| Weight | First version | Second version (damage-based) |
|---|---|---|
| 0 | 413 | 413 |
| 1 | | 412 |
| 1.5 | | 414 |
| 2 | | 411 |
| 3 | 422 (+18/-9, p=0.12) | 407 |
| 6 | 421 | 378 (p<0.001) |
| 10 | 417 | |

Generic solo buildings, first version at weight 3: 55 against 52
(+4/-7, p=0.55). In the first version, without the group premium and
the last-copy term, no weight up to 6 moved anything.

The flat "group counts twice" rule got a second case backwards: on a
cog with 1 HP the cheapest kill is an Aoogah, and doubling its price
made it dearer than a Safe. With the damage-based worth, on the
maintainer's pouch a Foghorn is 4.5% of the pouch's worth, a Safe 2.8%,
the last Aoogah 2.0%, a Whole Cream Pie 1.6% and a Seltzer 0.75%, which
gives the pie on a lone 32 HP cog and the Aoogah or Seltzer before the
Safe on a 1 HP one.

**Conclusion.** Set at 2: just past the roughly 1.7 that turns the
lone-Tightwad Foghorn into a Cream Pie, and inside the range that is
harmless. At 6 it hoards and loses. It buys advice that spends the gag
an experienced player would, not more clears, because in the simulator
buildings are decided by laff.

### 2026-10-05 Boss rounds sized by who came

**Outcome:** kept. Exposed a gap between the model and the maintainer's experience on a one-toon VP side that is still open.

**Question.** The simulator gave a two-toon VP side the solo fight's
20 + 20 cogs. The maintainer's account `[OWNER]`: a VP is twenty cogs a
round in all; alone you face all of it, and with company the toons
split across the two sides and each side faces ten. The CEO's first
battle is twenty per side, so forty alone ("I think"). What do the
engines score at the right sizes?

**Setup.** Round sizes now depend on the toons in the whole fight
(`vp.side_rounds`, `ceo.round_one_for`), read by both the training
environment and the boss tracker. Paired sweeps (commit 2ab8724).

**Result.**

| Fight | PPO row (climb) | Playout row |
|---|---|---|
| Four-player VP side (2 toons, 10 + 10) | 40 of 40 | 40 of 40 |
| Two-player VP side (1 toon, 10 + 10, light SOS deck) | 6 of 60 | 33 of 60 |
| CEO side (2 toons) | 9 of 30 | 11 of 30 |

A check on the loadout the next day (commit bc57d2c): restocking the
toon with the maintainer's own VP pouch (`vp.OWNER_VP_POUCH`) instead
of a level-first fill changed little.

| Fight | Level-first pouch | Maintainer's pouch |
|---|---|---|
| Two-player VP side, climb | 6 of 60 | 9 of 60 |
| Two-player VP side, playouts | 33 of 60 | 33 of 60 |
| Solo VP, playouts | 52 of 100 | 57 of 100 (+21/-16, p=0.51) |

**Conclusion.** The wrong size was why party VPs had looked
unwinnable. The one-toon side disagrees with the maintainer, who calls
that fight trivial. Every traced loss dies to the skelecogs with 65 to
78 gags unthrown, which points at cog damage or attack rate in the
model and not at the search. The loadout is not the cause. One toon on
screen cannot tell a solo VP from one side of a two-player VP, so the
TTR panel takes the number of toons in the fight from the player.

*Note, 2026-10-06:* part of this gap was a simulator bug that discarded
Unites. See the next part. The gap without Unites remains and is listed
in [roadmap.md](roadmap.md).

---

## Part 4. Tuning the Playout engine

Entries from 2026-10-06 to 2026-10-08. From here on "the maintainer's
pouch" is `vp.OWNER_VP_POUCH`, the maintainer's own solo VP loadout
without Toon-Up, and five Unites is the maintainer's own budget for a
solo VP.

### 2026-10-06 Expert iteration round 2 for the rollout network

**Outcome:** not shipped. A 5-point lead that 300 paired fights could not separate from chance.

**Question.** The rollout network imitates climb. Does it play out
fights better if it also learns the Playout engine's own moves?

**Setup.** 1,000 solo fights (VP, building, street) labelled by the
Playout engine, 27,449 decisions, mixed at three times the weight into
the shipped network's 345,693 climb-labelled rows. Same architecture
(384 hidden units, 20 epochs). Held-out agreement was 70.4%, which is
not comparable with the shipped network's 79% because the held-out rows
now include playout labels, which are harder to copy. Paired solo VPs,
with playouts played on by each network.

**Result.**

| Seeds | Shipped network | Candidate | Paired |
|---|---|---|---|
| 100000 to 100099 | 52 | 61 | +28/-19 |
| 100100 to 100299 | 123 | 129 | +46/-40 |
| All 300 | 175 | 190 | +74/-59, p=0.22 |

Used alone, as an instant answer with no playouts, neither network is
usable: 6 of 100 and 5 of 100.

**Conclusion.** Not shipped. If tried again the labels are the lever:
27 thousand playout decisions against 346 thousand climb ones may be
too few to move the network off climb.

*Note, 2026-10-11:* a later round with more playout labels, soft
targets and inputs for what is still to come did ship. See
[2026-10-11 Expert iteration for the rollout network shipped](#2026-10-11-expert-iteration-for-the-rollout-network-shipped).

### 2026-10-06 Unites were never spent in simulation

**Outcome:** bug fixed. Every VP figure before this date was measured with Unites unusable, and Unites decide VPs.

**Question.** Why did no simulated fight ever spend a Unite?

**Setup.** Climb applies the Unite it chooses to the board it is
handed. Every playout, sweep and data tool handed it a copy, so the
Unite landed on the copy and the round was played with the gag alone.
The fix (commits 9f634a2, 598bfd9) carries the Unite on the plan,
applies it in the real fight, offers climb's move both with and without
it, and keeps plans that need gags only a restock would supply off the
menu. Paired sweeps with playouts and the maintainer's pouch.

**Result.**

| Fight | No Unites | Five Unites | Paired |
|---|---|---|---|
| Two-player VP side, 60 fights | 33 | 55 (92%) | +22/-0 |
| Solo VP, 100 fights | 57 | 94 (94%) | +38/-1 |

The solo regime also carries three pink slips and a ten-card SOS deck.

**Conclusion.** This is the first figure back above 90% since an older
VP model with 12 cogs, two toons and full information, and with Unites
the maintainer's "a two-player VP is trivial" matches the model. Every
earlier VP figure, including the solo VP range of 55 to 70% that the
Playout engine was tuned against, was measured with Unites unusable.
The search for the gap had already ruled out the loadout (+5 solo,
p=0.51) and Lure accuracy (70 to 95% against level 8 to 12 skelecogs by
the wiki's formula). Laff was always the binding constraint, since
losses ended with 65 to 78 gags unthrown, and Unites are the laff.

### 2026-10-07 A rollout network that sees and uses Unites

**Outcome:** stronger alone, no better inside the playouts and slower. Shipped anyway the same day on the maintainer's reasoning; see the next entry.

**Question.** The rollout network could not open a round with a Unite,
so a playout valued holding one at nothing. Does a network with Unite
inputs and a Unite output head make the playouts better?

**Setup.** Commit 2731e4e added the inputs and the head. The network
was trained on 354 thousand new climb-labelled decisions with Unites in
hand (one DAgger round) plus the old 345 thousand rows padded with "no
Unites". Agreement with climb: 82.8% on gags (the earlier network 79%),
96% on Unites (about 80% of which are "none"). Paired, the maintainer's
pouch and five Unites.

**Result.**

| Fight | Earlier network | Unite-aware network | Paired |
|---|---|---|---|
| Solo VP, playouts | 94 of 100 | 93 of 100 | +6/-7, p=1.00 |
| Two-player VP side, playouts | 55 of 60 | 49 of 60 | +2/-8, p=0.11 |
| Solo VP, network alone | 6 of 100 | 22 of 100 | |
| Two-player VP side, network alone | 9 of 60 | 24 of 60 | |

**Conclusion.** Alone it is far stronger, because it heals itself. As
the playouts' rollout player it is no better and 40% slower (the extra
head, and a board copy whenever it uses a Unite). A guess at why: the
playouts' job is to rank first moves, and a continuation that spends
Unites on every candidate's behalf narrows the differences the ranking
reads. Weights without a Unite head never use one.

### 2026-10-07 Groups with Unites and the Unite-aware network re-checked

**Outcome:** the Unite-aware network shipped on realism against a non-significant dip; modelling teammates' Unites changes little.

**Question.** In a group, does it matter whether the engine assumes
teammates will use their Unites? And does the Unite-aware network hold
up on a larger sample?

**Setup.** Every toon holds five Unites. In the fight itself teammates
always use what they hold; the arms differ only in whether the engine
assumes so. Then 200 fresh two-player VP sides for the network.

**Result.**

| Fight | Engine ignores teammates' Unites | Engine models them | Paired |
|---|---|---|---|
| CEO side, coordinated, 40 | 37 | 37 | +3/-3 |
| Party building, pickup, 100 | 64 | 68 | +5/-1, p=0.22 |

| Two-player VP sides | Earlier network | Unite-aware network | Paired |
|---|---|---|---|
| 200 fresh | 167 | 163 | +18/-22, p=0.64 |
| With the first 60 | 222 of 260 | 212 of 260 | +20/-30, p=0.20 |

**Conclusion.** The CEO side had been 11 of 30 for the playouts before
Unites could be spent at all; with them it is 37 of 40 either way.
Modelling the teammates' Unites changes the engine's choices little. It
is the Unites themselves that decide group fights, as they did solo.
The Unite-aware network is within noise of the earlier one, slightly
behind, and 55% slower per decision (1.88 s against 1.21 s). It was
shipped (commit d3c18f4) on the maintainer's call, on realism `[OWNER]`:
with the earlier network no rollout ever spent a Unite, so the playouts
valued every Unite held past the current round at nothing. The earlier
weights remain in git history.

### 2026-10-07 The preset of the panel in the playouts

**Outcome:** kept. Presets do what they say; none beats Balanced on wins.

**Question.** The panel's preset reached only the Search row. If it
also shapes the Playout row, what does each preset do to results?

**Setup.** Commit bfc7fe2: each preset scales the playouts' laff
weight, pouch weight and a per-round charge by its own numbers relative
to Balanced, so Balanced is exactly the measured engine. Paired sweeps.

**Result.**

| Fight | Balanced | Conserve | Survive | Speedrun | Glass Cannon |
|---|---|---|---|---|---|
| `my-building`, 200 | 149 | 147 | 142 | 141 | 140 (p=0.08 at worst) |
| Solo VP, 60, maintainer's pouch and five Unites | 57 (46.5 rounds) | 57 | 55 | 53 (38.4 rounds) | 56 |

**Conclusion.** Speedrun shortens a VP by 17% in rounds for 4 more
losses in 60. Conserve is identical to Balanced in a VP, as it must be:
the pouch is valued only where a fight continues past the playout.
Balanced is the measured setting and the others trade wins for what
they ask for.

### 2026-10-08 Open-loop tree search over your own decisions

**Outcome:** not better than flat playouts at any setting, and no better with two or four times the budget. Kept as a module, not wired into the panel.

**Question.** Flat playouts judge only the first move. Does a tree over
sequences of your own plans (Monte Carlo tree search, MCTS) do better
on the same budget?

**Setup.** `solver/search/mcts.py`. The tree holds sequences of your
plans. Each iteration draws its own future, descends by the PUCT rule
(the root's menu is `wide_candidates` with uniform priors; deeper menus
are the fast network's top 4 with its probabilities), expands one node
and lets the network play on. Same budget as flat playouts (168
playouts); on a sample VP board the tree grew 12 decisions deep and
took 2.8 s against 2.3 s. Paired, maintainer's pouch, no Unites. `c` is
the exploration constant.

**Result.**

| Fight | Flat | c=0.7 | c=1.5 | c=3 | c=6 |
|---|---|---|---|---|---|
| Two-player VP side, 100 | 52 | 38 | 49 | 42 | 46 |
| Solo VP, 100 | 61 | 51 | 56 | not run | not run |

With each method given 1x, 2x and 4x the playouts on the same 100
two-player VP sides (flat halving stages 8/16/32, 16/32/64, 32/64/128,
which is 168, 336 and 672 playouts; MCTS iterations to match):

| Method | 1x | 2x | 4x |
|---|---|---|---|
| Flat | 52 | 63 | 60 |
| MCTS | 49 | 51 | 49 |

MCTS against flat at 2x: p=0.05 and p=0.02.

**Conclusion.** No setting beats flat, and c=0.7 is significantly worse
(p=0.04). MCTS stays near 50 whatever its budget while flat improves,
so the tree is not underfed. The likely causes are structural. A tree
splits the same playouts across many nodes, so the root's estimates get
noisier. Below the root, PUCT picks among the network's top 4 by
design, so the in-tree follow-up is deliberately worse than the
network's own play, and the network's prior is peaked (82% on one move
is common). An open-loop tree also blends futures with different dice
into one node. A retry needs chance nodes and the network's own top
choice below the root until a node is well visited.

The other finding: flat playouts gained 11 wins from twice the budget
on two-player VP sides, so cheaper playouts are strength. That is what
a value network that cuts rollouts short would buy; see
[2026-10-09 Shortened playouts with a value network](#2026-10-09-shortened-playouts-with-a-value-network).
(On 2026-10-02, doubling the rollouts on solo VPs had not paid: 146
against 139 of 200, p=0.46. The two sweeps are different fights, and
here 4x was no better than 2x.)

### 2026-10-08 A network model of teammates

**Outcome:** no measurable difference in what the engine assumes; `SensiblePrior` stays the default.

**Question.** In pickup mode the engine's rollouts draw teammates'
moves from `SensiblePrior`. Is the fast network, playing from each
teammate's own seat and spread over its top 4 moves
(`party.NetTeammate`), a better model?

**Setup.** The sweep separates how teammates actually play in the fight
(`truth`) from what the engine assumes (`assume`). 200 party buildings.

**Result.** Wins of 200:

| | Engine assumes the prior | Engine assumes the network |
|---|---|---|
| Teammates play the prior | 96 | 93 |
| Teammates play the network | 101 | 101 |

**Conclusion.** What the engine assumes makes no measurable difference;
network teammates simply play a little better. `SensiblePrior` stays
the default and is about 45% faster per decision.

---

## Part 5. The exact search and learned values

Entries from 2026-10-08 and 2026-10-09. "Fully exact" means expectimax
over every chance outcome. "Collapse" replaces the cogs' attack
distribution with its mean (`exact_plies=0`), which the panel already
used. `tools/search_bench.py` has three modes (depth, agree, fight).
Benchmark positions: a maxed toon with the maintainer's pouch partly
spent, 30 to 137 laff, 1 to 4 cogs of level 6 to 12 at random health,
street battles. `|dv|` is the absolute difference in the value returned.

### 2026-10-08 Squeezing depth out of the exact search

**Outcome:** 1.5x exact from profiling; a beam of 6 agrees with exact search and is not switched on because it is unmeasured in play.

**Question.** How deep can the exact search go per decision, and what
buys more depth without changing the answer?

**Setup.** Time per decision, fully exact, before any change:

| Cogs | Depth 1 | Depth 2 | Depth 3 | Depth 4 |
|---|---|---|---|---|
| 1 | 0.01 s | 0.24 s | 6 s | over 60 s |
| 2 | 0.02 s | 2.8 s | over 60 s | |
| 3 | 0.07 s | 22 s | over 60 s | |
| 4 | 0.11 s | 42 s | over 60 s | |

**Result.**

| Change | Exact? | Effect |
|---|---|---|
| Profiled hot spots: `can_still_damage` (a third of a search) checks the common case first; `features` caches its pouch-only answers per toon | Yes, 60 of 60 answers identical | 1.5x |
| A memo kept across a fight's rounds | Yes | Barely helps: median 6.5 s to 4.7 s, mean unchanged, because the new board's next level was never searched before |
| Cog-order symmetry | Not done | Permuted boards only collide when the cogs are identical, which the key already merges |
| `expectimax.BEAM`: below the root, only the top k moves by a one-round look-ahead, at depth 3 | No | 1 cog, k=6: 100% same move, \|dv\| 0.003, 1.75x. 1 cog, k=4: 93%, 1.9x. 2 cogs, k=4 and k=6: 100%, \|dv\| 0.000, 2x |
| Collapse plus k=6, against fully exact at depth 3 | No | 1 cog: 100% same move, \|dv\| 0.004, 86 s to 4.6 s. 2 cogs: 100% same move, \|dv\| 0.005, 534 s to 6.4 s |

Keeping the first ply exact was no more accurate and 4 to 13 times
slower. Depth reached, mean of 3 positions, 60 s cap:

| Cogs | Collapse only: depth 3 / 4 / 5 | Collapse and k=6: depth 3 / 4 / 5 |
|---|---|---|
| 1 | 0.3 s / 1.9 s / 9.6 s | 0.2 s / 0.8 s / 3.0 s |
| 2 | 1.0 s / 5.5 s / 27 s | 1.0 s / 4.0 s / 13 s |
| 3 | 2.9 s / 14 s / over 60 s | 2.9 s / 10 s / 30 s |
| 4 | 6.7 s / 35 s / over 60 s | 7.1 s / 23 s / about 55 s |

**Conclusion.** The panel already collapses (depth cap 4, 15 s budget),
so live it reaches depth 4 at two cogs and depth 3 at three or four.
k=6 would put three cogs at depth 4 and two at depth 5 inside the same
budget. It is not switched on: agreement is measured and play is not,
and an older measurement (extra depth changed nothing over 42 three-cog
battles) says depth alone may not show up as wins.

### 2026-10-08 The chosen move stops changing at depth 4

**Outcome:** in a single battle the panel is already at the tactical plateau.

**Question.** Is depth 5 enough?

**Setup.** `search_bench.py stable`: the move chosen at each depth
(collapse and k=6) on the same street positions.

**Result.** Share of positions where the move changed on going to each
depth:

| Cogs | Positions | Depth 2 | Depth 3 | Depth 4 | Deeper | Depth 4 equals the deepest searched |
|---|---|---|---|---|---|---|
| 1 | 20 | 50% | 15% | 5% | 0% at depths 5 to 7 | 100% (deepest 7) |
| 2 | 10 | 10% | 0% | 40% | 0% at depths 5 and 6 | 100% (deepest 6) |
| 3 | 6 | 33% | 17% | 0% | 0% at depth 5 | 100% (deepest 5) |

**Conclusion.** In a single battle with nothing arriving, depth 4 gives
the deepest search's move on every position. The panel reaches depth 4
at two cogs and depth 3 at three or four, where depth 3 matched depth 5
on 6 of 6. Stability is not correctness, since a biased leaf can be
shared by every depth, and nothing here covers the horizon past the
battle (a VP's waves, a building's floors), which no depth reaches. The
gain left is in the leaf.

### 2026-10-08 Pruning and move ordering in the exact search

**Outcome:** best-first ordering is exact and on by default; pruning itself is worth 9.2x.

**Question.** `*`-minimax pruning (star1 and star2, the analogue of
alpha-beta for chance nodes) was already on. What is it worth, and does
ordering moves best-first add to it?

**Setup.** Agree mode; every row chose the same move on 100% of
positions with |dv| 0.000.

**Result.**

| Configuration | Change | Time |
|---|---|---|
| Depth 4, collapse and k=6, 2 to 3 cogs | pruning turned off | 89 s to 823 s (9.2x slower) |
| Depth 3, fully exact, 1 to 2 cogs | ordering turned on | 641 s to 518 s (1.24x) |
| Depth 4, collapse and k=6, 2 to 3 cogs | ordering turned on | 85 s to 80 s (1.06x) |

**Conclusion.** `expectimax.ORDER` (best-first by the one-round
look-ahead, every move kept) is exact and never slower, so it is on.
The other half of star1 is its bounds: the floor is depth-aware and the
ceiling is always a win (+100). A tighter ceiling would help mostly in
losing positions, where the leaf is already low. Not tried.

### 2026-10-08 Tighter bounds and a hint from the shallower pass

**Outcome:** tighter static bounds bought no pruning and were removed; reusing the shallower pass's move is exact and 1.4x to 1.85x faster.

**Question.** Can `*`-minimax itself be made to cut more?

**Setup.** Two changes, each checked against exhaustive search on a
two-cog depth-3 position and on the benchmark.

**Result.**

*Tighter star1 bounds.* The fitted leaf's floor was the loss value
minus the toon's maximum laff (-237) at every node, so star1 saw each
unseen branch somewhere in roughly [-280, +100] while nodes really took
values within about 25 points (at depth 1: 75 to 98). A jointly
minimised, provably admissible horizon bound on the linear evaluator
lifted the leaf floor to between 17 and 85 and passed every
admissibility check (exhaustive values inside the bounds; more than 200
random-playout leaves inside the range; pruned equal to exhaustive). It
searched exactly the same 1,134,228 nodes and cost 186 s in bound
arithmetic against 7 s. Fully exact went from 447 s to 1,784 s; with
collapse and k=6, from 76 s to 96 s.

*The shallower pass's move as a hint.* Memo entries are keyed by depth,
so iterative deepening's main benefit, trying the previous pass's best
move first, reached only the root. `HINT_FROM_SHALLOWER` falls back to
the entry one depth shallower for move ordering and for star2's probe
move. On the two-cog position: 1,134,228 nodes to 509,131, 66 s to
36 s, same value and move.

| Benchmark (100% same move, \|dv\| 0.000) | Before | After |
|---|---|---|
| Fully exact, depth 3, 16 positions | 512 s | 361 s (1.42x) |
| Collapse and k=6, depth 4, 12 positions | 83 s | 76 s (1.09x) |

Collapse, k=6 and the hint, mean of 3 positions:

| Cogs | Depth 4 | Depth 5 | Depth 6 |
|---|---|---|---|
| 1 | 0.5 s | 1.7 s (was 3.0 s) | 4.5 s |
| 2 | 3.0 s | 9.5 s (was 12.9 s) | 23.5 s |
| 3 | 8.1 s | 26 s (was 30.5 s) | about 56 s |
| 4 | 22 s | about 53 s | |

**Conclusion.** The tighter bounds cut nothing because star2 probes
each child with a real search and raises the floor to the probed value,
which is always at least as tight as any static floor. A static floor
matters only where probes do not run, one ply above the leaves. The
ceiling stayed at +100 because a win inside the horizon is almost
always possible. The bound code was removed. The hint is on by default.

### 2026-10-09 A learned leaf for the Search row

**Outcome:** three tries, none better in play. The comparison also showed the Search row far behind the Playout row wherever a fight has more than one wave.

**Question.** The search's move is stable by depth 4, so the gain left
is in the leaf. Does a value network as the leaf
(`solver/search/valuenet.py`) beat the fitted linear leaf?

**Setup.** Judged by the `search` arm of `tools/sweep.py` at 2 s per
decision against the fitted leaf, paired.

**Result.**

*1. Labels from deep search.* 27,667 boards from streets, solo
buildings, the maintainer's buildings and solo VPs, labelled by search
at depth 5, 4, 4 and 3 (for one to four cogs) with collapse and k=6.
Held-out error 11.5 against the fitted leaf's 36.6, 3.2 times better (1 cog: 6.9 against
14.9; 4 cogs: 10.4 against 40.6).

| Fight | Fitted leaf | Network leaf | Paired |
|---|---|---|---|
| `my-building`, 200 | 146 | 145 | +3/-4 |
| `solo-building`, 200 | 21 | 16 | +1/-6, p=0.13 |
| Two-player VP side, 60 | 6 | 8 | +6/-4 |

A move-agreement check against the deep search was biased in the
fitted leaf's favour (the reference used that leaf, and for 4-cog
boards it was the depth-3 fitted search), so it is not evidence either
way.

*2. Labels from whole fights.* 68,030 boards labelled by the reward
collected to the end of the fight under the fast network, 6
continuations each (`tools/gen_value_outcomes.py`; 20,000 episodes in
about 10 minutes).

| Fight | Fitted leaf | Network leaf | Notes |
|---|---|---|---|
| Two-player VP side, 60 | 7 | 4 | fights lasted 8.1 rounds against 15.8 |
| `my-building`, 200 | 146 | 138 | +3/-11, p=0.06 |
| `solo-building`, 200 | 21 | 21 | 4.3 rounds against 5.7 |

*3. The same with a lost fight valued at 1000.* Still worse:
two-player VP side 8 against 3 (+0/-5, p=0.06, 9.5 rounds),
`my-building` 144 against 140.

**Conclusion.**

- In try 1, lower absolute error did not buy better choices. Picking a
  move needs the differences between sibling boards, often under a
  point, against a median error of 3.7.
- In try 2, fights ended sooner. In the search's units (1 per point of
  laff, 100 for a lost fight) a long fight's damage outweighs losing,
  so dying early scores better. Whole-fight values reach far below the
  fitted leaf's floor (a solo VP board can be worth -560), so
  `valuenet.py` clamps at a low floor to keep star1's bounds admissible;
  that costs little because star2's probes set the floors that prune
  (see the previous entry).
- Try 3 showed the units were not the whole story. The labels describe
  the fast network's play, which loses most VPs alone and so makes most
  boards look alike, and six noisy continuations cannot rank sibling
  moves.
- **The Search row is far weaker than the Playout row in fights with
  several waves.** Two-player VP sides: Search 6 to 8 of 60, Playout 33
  of 60 (+28/-1). Buildings: level (146 against 149 of 200). The search
  sees only the cogs on the field, so labels from it carry the same
  blind spot. Depth already settles single battles by 4.

The learned leaf is off. This comparison is why the Playout row leads
in the panel; see
[2026-10-11 The Playout row leads in every fight](#2026-10-11-the-playout-row-leads-in-every-fight).

### 2026-10-09 Shortened playouts with a value network

**Outcome:** shipped. Level or better on wins in 28% less time per decision on solo VPs, once the value network could see how many cogs were still to come.

**Question.** Cheaper playouts are strength (see the tree-search entry
of 2026-10-08). Can a value network in the playouts' own units stop
each playout after a few rounds and score the rest, so that twice as
many playouts fit in the same time?

**Setup.** 68,030 boards labelled with cogs defeated from the board to
the end of the fight plus the laff weight times laff left, under the
fast network, 6 continuations each. Each playout stops after k rounds
(`playout.ROLLOUT_DEPTH`) and asks the network for the rest, with twice
the playouts. "Full" is a playout to the end. Times are per decision.

**Result.**

*First network: the board as the panel shows it.* Held-out error 1.37
cogs (median 0.99).

| Fight | Full | k=4 | k=8 |
|---|---|---|---|
| Two-player VP side, 60 | 33 (1.04 s) | 31 (0.95 s) | 28 (1.38 s) |
| Solo VP, 60 | 37 (2.53 s) | 19 (1.21 s), +1/-19 against full | 30 (1.89 s) |

*Second network: the count of cogs waiting to walk into this wave and
the count in later waves added as inputs*
(`gen_value_outcomes --extras`). Held-out error barely moved (1.34
against 1.37 cogs). Play did:

| Solo VP | Full | k=8 | k=4 |
|---|---|---|---|
| 60 fights | 37 (2.54 s) | 41 (1.94 s), +15/-11, p=0.56 | 30 (1.13 s); 19 without the counts |
| 200 fresh fights | 126 (2.61 s) | 134 (1.88 s), +41/-33, p=0.42 | |
| All 260 | 163 | 175, +56/-44, p=0.27 | |

*After shipping (commit 03ef267):* two-player VP sides, 57 against 52
of 100 for shortened against full playouts, and slower there, because
short fights save less than the extra playouts cost.

**Conclusion.** The first network was worse, and worse the earlier the
cut, which is a bias that more playouts cannot average away. The cause
was a missing input. The panel's view of the board drops the cogs still
waiting to enter, which in a VP swings from 16 to 0, so the network
could not tell sixteen cogs to come from none. A full playout plays
every one of them. With the counts as inputs, k=8 is level or better on
wins and never shown worse, in 28% less time per decision. The gain on
wins is not established (p=0.27 over 260 fights).

Shipped on by default on 2026-10-09: after 8 rounds the value network
(`solver/rl/playout_value.json`) scores the rest of a playout, and the
halving schedule doubles to 16, 32 and 64 rollouts. Without numpy or
the weights file, playouts are played in full as before.

---

## Part 6. What live play turned up

Entries from 2026-10-09 and 2026-10-10, reconstructed from commit
messages and the maintainer's working notes. Several of them start from
a running game: a logged boss fight on Toontown Realms, or the TTR
client observed directly. Each entry says which of its results are
observations of a running game and which are simulated sweeps.

### 2026-10-09 The TTR panel plans around the Unites the player states

**Outcome:** kept. No new measurement; it applies the 2026-10-06 result to the live panel.

**Question.** Nothing on screen or in the Local API reports Unites on
TTR, so every board reached the solver holding none. Given that Unites
decide VPs, what should the TTR panel do?

**Setup.** The panel's Unites box had been inert. Its count now lands
on the board the engines plan with (commit d070355). The kind of Unite
is unknown, which the solver already treats as "any".

**Result.** None measured here. By the 2026-10-06 sweeps, the playouts
were planning a one-toon VP side as the 33-of-60 case and not the
55-of-60 one.

**Conclusion.** SOS cards stay inert on TTR: a count without names
cannot say whether a card heals, restocks or deals damage.

### 2026-10-10 Two logged Realms VPs and what the engines got wrong

**Outcome:** a running game was observed. The engines matched the maintainer's move on 12 to 29% of boards, and the logs exposed several bugs, all fixed.

**Question.** How does each engine's advice compare with what an
experienced player actually did in a real boss fight?

**Setup.** The Realms panel logs every board with each engine's
proposal and the move the player made. Two solo VPs played by the
maintainer on Toontown Realms were logged. The second, 34 boards long,
was compared move by move (commits b56ef45, dbde204, 9fa1d6b, 570a35d).

**Result.** Share of the 34 boards on which the engine's move matched
the maintainer's:

| Engine | Matched |
|---|---|
| PPO row | 29% |
| Search row | 12% |
| Playout row | 14% |

Faults found from the two logs and from auditing the code for the same
classes of bug:

| Fault | Effect |
|---|---|
| An engine was handed the live board. Climb applies its Unite in place, and both panels passed it the board that the Search row, the explanations and the log then read. | A Toon-Up Unite that the PPO row merely considered turned 12 laff into 92, and a Gag-Up invented gags that two rows then planned with. |
| A cog at 0 HP was treated as alive. | 14 of 34 boards had one, and every engine aimed group gags and SOS cards at cogs that were already dying. |
| Rounds were counted per network message, and every message arrives twice. | Every Lure aged two rounds per round. |
| A Lure or Trap was looked up only when exactly one battle existed. A VP has two, one per side. | Every Lure in a boss fight read as unseen and the panel stopped advising the moment a cog was lured. |
| A budget of five SOS calls reached the solver as five of each of sixteen cards. | The Playout row called an SOS card on 13 of 28 boards. See the next entry. |
| Unites were never on the Playout row's menu. Climb proposes one only past a price of 200, against about 2 per point of laff healed. | At 33 of 100 laff with five Unites held, none was offered. The menu now adds climb's move opened with the largest worthwhile Toon-Up Unite and with a Gag-Up; the playouts charge no price and judge them by outcome. The menu cap went from 10 to 12. |
| The panel charged its budget for every SOS card, Unite and slip it suggested. | The SOS budget emptied within a few rounds with no card called. Realms reads real holdings, so spending is now what actually left the toon. |
| "The Toons Hit" and "The Cogs Miss" cards were not certain. | On Realms they are certain for the one turn after the call `[OWNER]`. The cogs-miss effect had also done nothing in a party round or in the exact search. |

The first log could not say how many cogs the VP's first round held (32
entered before the log ended), so each logged board now records which
battle, side and round it came from.

**Conclusion.** The low agreement is a measurement of the engines with
those bugs in place, on one fight. It has not been repeated since the
fixes, and repeating it is an open item in [roadmap.md](roadmap.md).
Agreement with one player's move is also not the same as being right:
several moves can be equally good. The rule that came out of it is that
an engine is always given a copy of the board, never the live one.

### 2026-10-10 SOS cards as one pool and a price per call that lost

**Outcome:** the pool is kept; a price per call was refuted and is zero.

**Question.** After the logged VP showed an SOS card called on 13 of 28
boards, should the playouts charge something for each call?

**Setup.** The cause of the over-calling was the budget being read as
five of every card. `ToonState.sos_calls` makes it one pool: five calls
in all, whichever cards they are. On top of that, a price per call
(`playout.SOS_CALL_PRICE`), in cogs, was swept on 100 simulated solo VPs
in the `realms-vp` regime (100 laff, no pink slips, a five-call SOS
budget, five Unites).

**Result.**

| Price per call (cogs) | Wins of 100 |
|---|---|
| 0 | 43 |
| 0.5 | 38 |
| 1 | 30 (against 0: p=0.035) |

Every arm still spent about 4.3 of its 5 calls.

**Conclusion.** Pricing calls only delayed them, and lost. The price is
0. The fix was the pool.

### 2026-10-10 Wasted reach charged by all three engines

**Outcome:** kept as a stated preference `[OWNER]`. It costs no wins and gains none.

**Question.** The engines sometimes advised a hit-all gag or card on
cogs it could not reach: Drop on lured cogs, Lure on cogs already
lured, Trap on cogs already trapped, or a group Trap that wakes lured
cogs. The maintainer's view is that this is waste even when it costs
nothing in the model. Does charging for it cost wins?

**Setup.** `simulator.wasted_reach` measures the share of a hit-all
move's reach that is thrown away. The playouts charge up to half a cog
for a card's wasted share (`SOS_REACH_PRICE` 0.5) and a small nudge for
a group gag (`GAG_REACH_PRICE` 0.1), since a gag's cost is already in
the pouch term. The PPO and Search rows charge it in their own units.
100 simulated `realms-vp` fights, with and without.

**Result.** 43 and 43 of 100 (+2/-2).

**Conclusion.** A preference, measured only to confirm it is harmless.
This supersedes the 2026-08-31 decision not to penalise a group gag on
one cog, which was made on frequency (two cases in about 3,500 throws)
for the PPO row alone.

### 2026-10-10 Three implementations of a round held against each other

**Outcome:** tool kept; it found one more rule that one path was missing.

**Question.** The project has three implementations of a battle round:
the exact outcome distribution used by the search, the solo simulator,
and the party simulator. The cogs-miss fault above lived in two of
them. Do they agree elsewhere?

**Setup.** `tools/round_parity.py` draws random positions and moves,
computes the expected outcome under each implementation, and reports
any difference beyond sampling error.

**Result.** Over 348 position-move pairs it found one more drift: the
party round re-capped Realms' certain hit at 95%. Fixed.

**Conclusion.** Run it after touching a rule.
`tests/test_round_parity.py` is a small fixed-seed version that runs in
the suite.

### 2026-10-10 A rule and two tie-breaks from live play

**Outcome:** kept. One legal-move correction and two small preferences.

**Question.** Three pieces of advice seen in play looked wrong. What
was each one?

**Setup.** Observed on the panel during play (commit 5c8f192).

**Result.**

| Seen | Cause | Change |
|---|---|---|
| A group Trap (Railroad) offered over a lone lured cog. | A group Trap needs one unlured cog to be placed `[OWNER]`; with every cog lured it cannot be. | `legal_actions` no longer offers it. The behaviour lock moved on exactly one position (8 legal moves to 7). |
| The Search row called a restock SOS card beside a cog one pie from dead. | An SOS card has no track, so the preset's gag price charged nothing for it. | `Objective.sos_cost` of 10 per call, a chosen preference, about twice Balanced's price for a level 7 gag. |
| The playouts rated a wasted round level with the move that ended the fight. | Every playout on such a board wins, so every move scored the same cogs and nearly the same laff. | `ROUND_TIEBREAK`: a thousandth of a cog per round, which separates only moves that tie on cogs and laff. |

**Conclusion.** None of the three was measured in a sweep. The first is
a rule of the game; the other two are preferences sized so they cannot
outweigh a cog or a point of laff.

### 2026-10-10 The pass on the menu of the Playout row

**Outcome:** kept. A lone toon is offered a pass only when nothing else is productive. Neutral on wins.

**Question.** The Playout row sometimes told a lone toon to "pass and
let the lure lapse" while it had gags to throw. Why, and does removing
the pass from the menu cost anything?

**Setup.** A pass is legal almost everywhere (whenever a cog is lured,
and otherwise a limited number of times), and the playouts' menu added
one to every board. On a lured board a pass costs no laff and no gag
this round. What it throws away, a round of the Lure and its knockback
bonus, is small next to playout noise, so the pass sometimes won by
luck. A lone toon's menu now offers it only when nothing else is
productive, which is the wait between a Trap and its Lure
(`playout.PASS_ON_MENU`). Party plans keep it, because that is how a
toon conserves gags while a teammate covers `[OWNER]`. 100 simulated
`realms-vp` fights (commit 50db8a4).

**Result.** 41 with the change against 43 without, differing on 2
fights (p=0.5).

**Conclusion.** Neutral on wins, and it removes advice that is never
the right move. The wording also changed: every pass had read "wait for
the lure to lapse" whatever the reason, and now reads "pass this
round".

> **Note, 2026-10-12.** This change was half a fix, which is why the two
> arms differed on only 2 fights. See
> [The pass still reached the menu another way](#2026-10-12-the-pass-still-reached-the-menu-another-way).

### 2026-10-10 Budgets for slips, Unites and SOS cards as a session total

**Outcome:** kept. A design change after two failures of per-fight budgets; no sweep.

**Question.** The panel tracked what the player had left per fight.
What marks the boundary of a fight?

**Setup.** Seen on a running game. The per-fight baseline broke twice:
a second VP in the same session inherited the first one's spending
(two SOS calls and no Unites left, by the panel's books), and the
intermission between a VP's two rounds read as the fight ending and
reset the budget and the count of cogs defeated.

**Result.** The boxes on the panel are now a session budget
(commits b51be40, 21f8f88, d1fa15a). Every spend ticks its box down,
both the number on screen and what the engines may plan with, and the
player raises it when it runs out. Nothing resets. On Realms a box
ticks down by what really left the toon. TTR cannot see spending, so it
charges the move it showed when the round ends, on the box itself where
the player can correct it.

**Conclusion.** With no reset there is no fight boundary to detect and
none to get wrong `[OWNER]`. Resetting between a VP's rounds would also
have made the fight trivial.

### 2026-10-10 Detecting the VP on TTR and reading pink slips held

**Outcome:** a running game was observed. The VP is detected from the log file the game writes; pink slips are read from the Local API.

**Question.** The Local API cannot tell a VP from the courtyard of
Sellbot HQ, so the boss had to be picked by hand. Is there another
source the game itself provides?

**Setup.** Observed on a running TTR client on 2026-10-10
(commit 706318a).

**Result.**

- The game writes a log file. On entering a place it writes a line of
  the form `enter(requestStatus={... 'where': 'CogHQBossBattle',
  'hoodId': 11000})`, and hood 11000 is Sellbot HQ.
  `solver/live/ttr_log.py` reads the newest log file incrementally. It
  reads a file the game writes; it does not read the game's memory or
  touch its process.
- The Local API documents `/pinkslips.json`, `/sos.json` and
  `/unites.json`, each on its own endpoint. Pink slips are a bare
  count, confirmed on the running game. The toon that was read held no
  SOS cards and no Unites, so the names used by those two endpoints are
  unseen and they are not parsed.
- Neither the Local API ("Cog Building") nor the log gives a building's
  floor count. See the next entry.

**Conclusion.** Only the VP's room is mapped
(`boss.TTR_BOSS_PLACES`). The CFO, CJ and CEO stay on the manual picker
until each is seen: the same line with another hood number is the
obvious guess, and a guessed key would quietly name the wrong fight.
The slip box now ticks down by what really leaves the toon and never
offers more slips than are held.

### 2026-10-10 Reading the floors of a building through the Discord relay

**Outcome:** a running game was observed. Floors can be read if the relay starts before Discord; a Discord already holding the pipe cannot be displaced.

**Question.** The game publishes "In a Four Story Sellbot Building" and
"Floor 2 of 4" only to Discord's Rich Presence. Rich Presence travels
over a local pipe named `discord-ipc-N`, and a client connects to the
first one that exists. Can the panel read the floor from there without
touching the game?

**Setup.** `solver/live/discord_relay.py` listens on `discord-ipc-0`.
With Discord closed it answers the game's handshake itself. Started
before Discord, Discord settles on `discord-ipc-1` and the relay passes
every byte through unchanged, keeping a copy of each status on the way.
It uses the standard library only: Windows named pipes, and Unix
sockets elsewhere. It was tested on Windows against a stand-in Discord
and a stand-in game, and then against the running game and the real
Discord on 2026-10-10 (commits 0cc6027, 3311798, b2c9569).

**Result.**

*Can a running Discord be displaced?* No. With 1, 4 or 16 extra
listeners on `discord-ipc-0` beside Discord's own, Windows gave all 54
new connections to Discord's.

*Can the game be moved to another pipe while running?* TTR's
`settings.json` has a `"discord-pipe-number"` entry. Three tests on a
running game:

| Test | Result |
|---|---|
| Edit the setting while the game runs | The game kept pipe 0 |
| Edit the setting, then toggle the Discord integration | The game kept pipe 0 |
| Toggle the integration off, edit, toggle it on | The game kept pipe 0, and toggling rewrote the file from memory over the edit |

The game reads the setting only at launch.

*Does the flow work end to end?* With Discord quit, the game
reconnected to the relay within 3 seconds and published "In a One Story
Lawbot Building" and "Floor 1 of 1". Discord, restarted, took
`discord-ipc-1`. At the game's next status the relay handed the game
over (it replays the game's opening message to Discord, discards
Discord's reply, and forwards everything after) and the player's
Discord status came back.

**Conclusion.** The working order is: open the panel, which retries the
pipe every few seconds, then restart Discord. The panel offers that as
a button, shown on TTR while Discord holds the pipe, and asks before
restarting because a restart drops the player from any voice call. The
panel shows the floor only while the Local API says the toon is in a
cog building, only the observed wording is parsed, and a story count
that disagrees with "of N" is not trusted. The relay reads what the
game publishes and nothing else. The Unix transport and the macOS and
Linux restart commands follow the reference library and each
platform's usual controls, and have not run on a real machine.

---

## Part 7. Expert iteration, the gag economy and teammates

Entries from 2026-10-11, reconstructed from commit messages and the
maintainer's working notes.

### 2026-10-11 Expert iteration for the rollout network shipped

**Outcome:** shipped. Playouts using the new rollout network won 65 against 44 and 68 against 37 of 100 solo VPs; buildings level.

**Question.** The fast network that plays out the rest of each fight
imitated climb, which judges one round at a time. The Playout engine
sees the rest of the fight. Does a rollout network trained on the
Playout engine's own choices make the playouts stronger? This is expert
iteration: the search labels positions, the network learns them, and
the search then uses the better network. Round 2 on 2026-10-06 had
tried it with too few labels and found a lead that was not significant.

**Setup.** Four changes went into the shipped round (commits dc8c70d,
a4abd97, fdad689, 447639c, 457aadd):

- *The student can see what is still to come.* `fastplayer.horizon`
  adds three inputs: cogs waiting to walk in, cogs in the waves or
  floors after, and SOS calls left. The playouts' value network had
  been useless until it saw the first two, and a policy imitating the
  playouts needs them for the same reason.
- *Soft targets.* In a dry run the student copied climb's held-out
  moves 56% of the time but the Playout engine's only 31% (25% when
  trained on those alone). The playouts' picks are full of near-ties (a
  Storm Cloud over a Safe by 0.0004 cogs), so the winner alone is close
  to a coin flip to copy. The data tool now records the playouts' mean
  score for every move they tried, and the trainer fits the network to
  a softmax of those scores (`--temp`), as AlphaZero trains on its
  search's visit counts.
- *Solo CEO fights in the mix,* at the maintainer's suggestion: one
  toon against 40 cogs in the first round `[OWNER]`.
- *Sweeps report cogs defeated,* because a lone toon never wins a solo
  CEO and wins say nothing there.

The shipped network was trained on 1,350 simulated fights (VP,
building, street, solo CEO) labelled by the Playout engine, about
47,000 decisions, half of them with the playouts' score for every move
tried, plus 77,000 climb labels for the basics. 512 hidden units.
Paired sweeps on seeds never seen in training compare playouts using
the new network with playouts using the previous one.

**Result.**

| Fight | Previous network | New network | Paired |
|---|---|---|---|
| Solo VP, 100 | 44 | 65 | +31/-10, p=0.001 |
| Solo VP, 100 fresh seeds | 37 | 68 | +35/-4, p<0.001 |
| Solo CEO, cogs defeated | 8.9 | 9.8 | a lone toon never wins |
| Solo buildings, 1,000 | 128 | 121 | +15/-22, p=0.32 |

Decisions take about 15% longer. Played alone, with no playouts, the
new network hoards in buildings: 108 against 155 of 2,000. It agrees
with climb on 63% of decisions, where the previous network agreed on
83%.

**Conclusion.** Shipped. The lower agreement with climb is the point:
it learned the playouts' choices where they differ. Its teacher prices
gags, so alone it hoards; it is a rollout player and not a standalone
engine. It plays one seat, so groups are still played on by climb.

### 2026-10-11 Later rounds of expert iteration did not beat the shipped network

**Outcome:** not shipped. Three candidates, none clearly better. One lead (playout labels only, on buildings, p=0.064) was not followed up.

**Question.** Does another round of expert iteration, with the shipped
network inside the playouts that produce the labels, improve on the
shipped network?

**Setup.** Paired sweeps of the Playout engine with the shipped rollout
network against the same engine with a candidate network. Three
candidates: *round two*, trained on a further round of Playout labels
with soft targets; round two *fine-tuned* from the shipped weights (the
trainer's `--init` option, commit 51c3fc0) instead of trained from
random; and round two trained on *Playout labels only*, without the
climb labels. Round two was run on seeds from 400000 and the two
variants on seeds from 2000000. These figures are from the maintainer's
notes of the day; they are not in a commit message.

**Result.** Each cell is shipped against candidate.

| Candidate | Solo buildings, 1,000 | Solo VP, 100 | Solo CEO, 100, cogs defeated |
|---|---|---|---|
| Round two | 104 against 106 (+8/-6, p=0.79) | 67 against 58 (+10/-19, p=0.14) | 9.4 against 9.6; no wins either way |
| Fine-tuned from the shipped weights | 103 against 106 (+11/-8, p=0.65) | 70 against 71 (+26/-25, p=1.0) | 8.7 against 9.2 |
| Playout labels only | 103 against 113 (+17/-7, p=0.064) | 70 against 66 (+20/-24, p=0.65) | 8.7 against 8.9 |

**Conclusion.** None beat the shipped network clearly, so it stayed.
Round two was, if anything, behind on the VP. The playout-labels-only
result on buildings is the one lead worth a larger sample.

### 2026-10-11 Charging the playouts for the gags they spend

**Outcome:** kept, at twice the preset's exchange rate. No wins lost; it changes which gag is advised.

**Question.** The PPO and Search rows price every gag through the
panel's preset and pick the smallest sure kill. The Playout row scored
cogs, laff and rounds and, outside a building, nothing for what was
spent. On a level 5 cog a Storm Cloud tied a Safe and won by noise
(1.4980 against 1.4976 cogs). Should the playouts charge for gags
`[OWNER]`?

**Setup.** Every gag a playout spends, in its first move and in the
rollout after, costs the preset's own price at the preset's own rate of
exchange between gags and laff: one price unit is worth 1/`laff_weight`
points of laff, as the Search row trades it, and a point of laff is
worth `LAFF_WEIGHT`/maximum laff cogs in the playouts
(`playout.economy`). Under Balanced a Storm Cloud costs about two
points of laff and a Safe about one; Glass Cannon charges nothing and
Conserve more. Simulated paired sweeps checked that it costs no wins.
Its strength (`ECONOMY_WEIGHT`) was then set against a board from a
running TTR game: a toon without Lure facing a level 5 Glad Hander at
42 of 42 HP (commits 1a7cf35, 92b5f91).

**Result.**

| Simulated sweep | Charge off | Charge on (weight 1) | Paired |
|---|---|---|---|
| `realms-vp`, 100 | 41 | 42 | +4/-3 |
| Solo buildings, 200 | 21 | 22 | +1/-0 |

| Simulated sweep | Weight 1 | Weight 2 | Paired |
|---|---|---|---|
| Solo VP, 100 | 75 | 73 | +5/-7, p=0.77 |
| Solo buildings, 1,000 | 104 | 104 | |

On the board from the running game, the Safe's lead over the Storm
Cloud in the playouts' estimate:

| Weight | Lead of the Safe (cogs) |
|---|---|
| 1 | 0.0026 +/- 0.0021 |
| 2 | 0.0085 +/- 0.0025 |

**Conclusion.** At the plain exchange rate the Safe's lead on a real
board was a coin flip and the panel showed the Storm Cloud. At weight 2
the Safe leads clearly, with no wins lost in simulation. Like the pouch
value of 2026-10-05, this term decides which of several winning moves
is advised; it is not a measured gain in wins.

### 2026-10-11 The Search row restarted before it could finish

**Outcome:** fixed. Seen in a recorded run of a running game; no sweep.

**Question.** In a recorded building run the Search row flipped between
"Thinking..." and "waiting for a readable board" every 2 to 4 seconds
and never answered, while the Playout row refined its pick. Why?

**Setup.** Traced through the recording (commit 3aceb0c).

**Result.** Three causes. The gag menu dropped out of the reader's view
for a frame now and then; that frame failed to build a board, and the
retry two seconds later started the 12 to 15 second search again.
Battle events restarted it for an unchanged board. And a superseded
search kept running in the single child process, so each new one queued
behind it for a full budget.

**Conclusion.** A resubmission of the same position (cogs, laff, gags,
rejected moves, preset) now keeps the running search or its answer. An
unreadable frame keeps a running search, or a standing answer that no
battle event has questioned. A new board ends the abandoned search's
process instead of waiting behind it. The Playout row was unaffected
because it posts an answer after every chunk of rollouts.

### 2026-10-11 The Playout row leads in every fight

**Outcome:** kept, on the maintainer's judgement `[OWNER]` and the 2026-10-09 comparison.

**Question.** Which engine's move should the panel show first?

**Setup.** On 2026-10-09 the Playout row was made the lead in boss
fights (commit 03ef267), on the simulated result that on one-toon VP
sides the Search row won 6 of 60 and the Playout row 33 of 60. It
handed back to the PPO row when the boss fight ended. In simulated
buildings the Search and Playout rows are level (146 against 149 of
200).

**Result.** After a recorded building run on a running game, the
maintainer's verdict: "I prefer playout's choice, I think it's the best
in all instances" `[OWNER]`. No sweep was run for this change.

**Conclusion.** The Playout row leads by default in every fight
(commit 3a0f44a). A player's own choice of engine overrides it, and the
PPO row's instant answer shows until the playouts post their first. The
panel's header, which could name only two engines and labelled the
Playout row's move "Search", became a three-way toggle
(commit fec308a).

### 2026-10-11 A new fight read fresh and advice recomputed on a corrected reading

**Outcome:** fixed. Seen in a recorded run of a running game; no sweep.

**Question.** In a recorded building run a level 6 Mover & Shaker
walked in before the gag menu came up and was labelled with the
previous fight's level 5 Mover & Shaker (42 of 42 HP). The advice
stayed on that board for about 20 seconds. Why?

**Setup.** Traced through the recording (commit 28088fb).

**Result.** Two causes. The reader reuses its last readings while the
line-up of cogs holds and the menu is down. That is right in the middle
of a fight, where it stops attack animations from flickering the
readings, and wrong across fights, where it handed the new cog the old
one's level. And a reading corrected in place, with the same number of
plates but a level or department read anew, produced no event, so
nothing asked for new advice.

**Conclusion.** The reset at a fight's start or end now drops the
reused readings. A corrected reading is now an event that triggers a
recompute. Naming a previously unidentified cog is deliberately not
such an event: an unidentified cog builds no board, and the retry
already asks again once it is named.

### 2026-10-11 Stand-in teammates for the TTR Playout row

**Outcome:** shelved. Guessing teammates is worth nothing or less; knowing them is worth about 11 wins in 300, all of it in what they hold.

**Question.** TTR shows the client one toon, so the panel's "Toon
Party" selector, a count, was all the Playout row knew of a party. It
used the count only to thin the cogs' attacks and planned as if you had
to beat every cog alone, so "a teammate covers this, save the gag"
could not be found. Would stand-in teammates help?

**Setup.** `party.assumed_teammates` builds stand-ins like you: your
training, a full pouch of your size, full laff, no SOS cards, Unites or
slips. They are a guess about people, like `SensiblePrior`, and
labelled as one. All sweeps are 300 simulated party buildings
(`tools/sweep.py --regime party-building`) in which the real teammates
play `SensiblePrior` and only what the Playout row is told about them
varies (the arm options `see=`, `keep=`, `redraw=`, `street=`). The
work is in commits 8dc80ca, 47c0159 and c5947c6.

**Result.**

| The Playout row sees | Won of 300 |
|---|---|
| The count alone (shipped) | 120 |
| One fixed set of stand-ins | 110 |
| Stand-ins redrawn in every rollout, from the board's true street | 120 |
| Stand-ins redrawn in every rollout, from a street whose laff band holds yours (all TTR can know) | 119 |
| The real teammates | 131 (p=0.04) |
| Stand-ins given the real teammates' laff only | 114 |
| Stand-ins given the real teammates' pouch and training | 129 |

The first sweep of fixed stand-ins, before redrawing existed, was
recorded as 111 in pickup mode (+13/-22, p=0.18) and 106 in coordinated
mode (+9/-23, p=0.02) against the same 120.

**Conclusion.**

- One fixed guess lost. It is a specific wrong teammate that the
  playouts plan around.
- Redrawing the guess in every rollout ties the count. Averaging over
  unseen teammates is what the count already does.
- Knowing the real teammates is worth about 11 wins in 300, and copying
  parts of them onto stand-ins shows it is all pouch and training. Real
  laff adds about nothing.
- The stand-ins are switched off in the panel
  (`Worker.stand_in_teammates`) and its Strangers / My party toggle is
  hidden. The only lever left is evidence of what these teammates
  hold, which is not built. [roadmap.md](roadmap.md) describes that
  unbuilt half and its open problems.

### 2026-10-12 The pass still reached the menu another way

**Question.** The change of 2026-10-10 was meant to stop the Playout row
telling a lone toon to pass while it had something to throw. Did it?

**Setup.** It gated the explicit pass entry at the end of the menu and
nothing else. `climb` scores a pass whenever one is legal, a pass counts
as a kind of move, and the menu takes `climb`'s own pick, the scorer's
top entries, the policy network's top two and the best move of each
kind. Sixty toons were drawn for a street with three cogs all lured,
under four conditions (full pouch, low laff, a pouch 70% drained, and
both), keeping the boards where something productive could be thrown.

**Result.** The pass was still on the menu on 6 of 60 full-pouch boards
and 11 of 54 drained ones. Every board where `climb` had scored a pass
carried it onto the menu. The menu now refuses a bare pass in every slot
for a lone toon unless nothing else is productive; the same boards then
hold none. The old behaviour is kept as `PASS_ON_MENU = "kinds"`, and a
paired sweep of old against new on simulated fights gave:

| Regime | Old (`kinds`) | New (`needed`) | Paired |
|---|---|---|---|
| 1,000 solo buildings | 97 | 96 | +2 / -3, p = 1.0 |
| 100 solo VPs | 71 | 68 | +8 / -11, p = 0.65 |

VP fights averaged 44.9 rounds with the new rule against 54.2 with the
old.

**Conclusion.** Kept. No measurable change in wins, shorter fights, and
the advice no player should follow is gone. The earlier tests checked
the helper that decides whether a pass is needed and never the menu,
which is how the gap survived; the new test builds the menu. Parties
are unchanged.

### 2026-10-12 A pink slip was free to the Search row

**Question.** The exact search charges for a gag, 10 for an SOS card and
200 for a Unite. What does it charge for a pink slip?

**Setup.** One slip held by a maxed toon, against boards of rising
difficulty, in the Balanced and Conserve presets. The Search row's entry
point at depth 2, with and without the slip.

**Result.** Nothing was charged: a fire has no track, so the gag price
was zero, and unlike a card it had never been given a price of its own.

| Board | With a slip, before | With a slip, after | Without a slip |
|---|---|---|---|
| One level 1 cog, Balanced | Fire (99.0) | Whole Cream Pie (97.87) | Whole Cream Pie (97.87) |
| One level 5 cog, Balanced | Fire (99.0) | Safe (97.75) | Safe (97.75) |
| Four level 12 cogs, Balanced | 65.26 | 60.57 | 45.78 |

Conserve behaved the same way. `Objective.fire_cost` is now 4.8.

**Conclusion.** Kept, tagged `[ASSUMED]`. The figure is derived and not
measured: the scorer prices a slip's floor at 120 and an SOS call at 250,
and a card costs the exact search 10, so a slip takes the same ratio.
The Search row now keeps its slip on a cog any gag beats, and a held
slip is still worth about 15 points on the board where it matters. No
sweep was run, because the Search row does not lead and this is a
preference about spending, like the SOS and Unite prices.

