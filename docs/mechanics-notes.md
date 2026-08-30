# Mechanics notes

`solver/mechanics.py`, `solver/state.py` and `solver/outcomes.py` carry a
short docstring or comment at each rule: what it does, the number a reader
must not lose, and a pointer here. This file is where the discovery
narrative, the failed alternatives, and the measurements that back each
number live. Nothing here is new information — it is the story the code
used to tell inline, kept rather than deleted.

## mechanics.py

### Solo-toon simplifications (module docstring)

1. PrevHits ("stun") is mostly a same-ROUND bonus between different
   toons' (or a multi-target attack's) sequential hits. A solo toon takes
   one action per round, so that half has nothing to inherit from and
   stays 0 until there are other toons.

   TRAP IS THE EXCEPTION, and this said otherwise for a long time. The
   wiki is explicit that Lure's PrevHits from Trap "remain across
   multiple rounds, as long as Trap is present", so a solo toon that
   traps and then lures collects +10 — see `calc_prev_hits_bonus`. That
   is the commonest solo line there is and it was being rolled ten
   points short of what the game gives it.

   The OTHER half of the `bonus` term, luredRatio, is not a same-round
   effect and does apply to a solo toon — see `calc_lured_ratio_bonus`.

2. Trap+Lure combo damage (the classic burst combo) is NOT the same
   thing as the PrevHits bonus above. It's a persistent, cross-round
   trigger: trap sits on a cog until a Lure knocks that cog onto it.
   That part IS modeled (see `simulator._resolve_toon_action`'s LURE
   branch).

3. Cog target selection is trivial for a single toon (there's only one
   toon to target), so `pick_cog_target` is a stub that always returns
   the lone toon. The proportional-damage weighting algorithm from the
   source doc is noted in a comment for when you add toons.

### `calc_tgt_def` — the rank-1 branch bug

tgtDef depends on the cog's RANK as well as its level: the wiki's table
marks levels 4 and 5 with a second value used by rank-1 cogs. The code
previously always took the rank-1 branch, which understated the defense
of every non-rank-1 cog at those two levels by 3 and 5 points — a
level-4 Micromanager was scored -12 instead of -15.

### `calc_prev_hits_bonus` — the solo case is not always zero

This said otherwise for a long time. The same-round part is: a solo
toon acts once per round, so there is no previous attack this round to
inherit a bonus from, and that half stays 0 until there are other
toons.

But Trap's contribution is explicitly cross-round. [CONFIRMED] TTR wiki
(Accuracy#PrevHits):

1. "The first Trap gag that is placed grants +10 to PrevHits, but only
   for Lure."
2. "Further Trap gag placements grant an additional +5 to a group Lure
   gag."
3. "The PrevHits for Lure remain across multiple rounds, as long as
   Trap is present."

Point 3 is the one that makes this a solo rule. A toon who traps in one
round and lures in the next is the commonest solo line there is — it is
the line `simulator.legal_actions` offers the pass action for — and it
was being rolled at 10 points less accuracy than the game gives it.

Rule 4, "+50 PrevHits when Trap is activated by Lure", is left at 0: it
is a bonus to attacks landing *after* the trap goes off in the same
round, and a solo toon has none.

### `gets_lured_ratio` / `calc_lured_ratio_bonus`

[CONFIRMED] TTR wiki (Accuracy#luredRatio): given to all Sound gags, and
level 7 Throw or Squirt gags when there is a mixed set of lured and
un-lured Cogs. Narrower than the strategy guide's rule, which was
"everything except Lure, Toon-Up and Drop" — that wrongly handed the
bonus to ordinary single-target Throw/Squirt and to Trap.

Rounding: the source expresses this as a percentage and adds it to
atkAcc; it does not say how a non-integral ratio (e.g. 1 of 3 cogs lured
→ 33.33) is rounded. We truncate. Only ever a 1-point difference, and
only for cog counts that don't divide 100.

### `forced_accuracy` — the party round's three-way bug

This exists as one function because the party round had its own copy of
the decision and got it wrong in all three directions: it added stun to
the forced number and then capped the sum, which gave an always-hit
Trap a 5% miss, gave a guaranteed Throw a 5% miss, and gave a Drop that
"always misses on lured Cogs" a 25% chance to land whenever anything
else hit earlier in the round. Solo play was right the whole time,
which is what made it hard to see.

### `calc_toon_accuracy` — the 95 cap and the 4.3.3 soft cap

The 95 cap became a SOFT cap in 4.3.3: stun/Lure/Trap bonuses and Toons
Hit "can slightly push the final accuracy value higher". The wiki never
quantifies "slightly" or gives a replacement ceiling, so there is
nothing to model — this stays a hard cap, which is the pre-4.3.3 rule
and the closest defensible approximation. See `data.ACCURACY_CAP_IS_SOFT`;
revisit if a number ever surfaces.

### `lure_accuracy_before_bonus` — why the 95 cap is not applied here

[CONFIRMED]. The guide shows atkAccResult being written *before*
accuracy bonuses are added — "Because of this, wakeupChance cannot be
offset with accuracy bonuses, and is only affected by propAcc, trackExp,
and tgtDef."

THE 95 CAP IS DELIBERATELY NOT APPLIED HERE. Reading: the guide only
ever states the cap in the hit/miss section ("It's important to note,
however, that atkAcc is capped at 95"), describing the value compared
against randChoice — i.e. the post-bonus accuracy. atkAccResult is
snapshotted earlier, and nothing in the guide caps it. It is also moot
for the only consumer: wakeupChance = 100 - 2*acc is already ≤ 0 at
acc ≥ 50, so any pre-bonus accuracy that could reach the cap can never
wake a cog either way. Capping or not capping changes no outcome; we
don't cap because the source doesn't say to.

Worked example from the guide (Lureless toon, propAcc 70, level-12 cog):
70 + 0 + (-55) = 15 → wakeupChance 70.

### `lure_can_expire_early`

[CONFIRMED] TTR 3.3.0: "Lure gags with a base accuracy below 50% no
longer have a chance for Lure effects to expire early." In current TTR
this is False for every Lure gag — the lowest base accuracy in the game
is Small Magnet at 55%. So the wake-up roll is unreachable in practice,
and a lure reliably lasts its full duration. The threshold is coded
rather than hardcoded to False because it is a rebalancing knob: a
future patch that drops a gag under 50% would switch early expiry back
on for it.

### `LURE_ENDS_ON_DAMAGE` / `DROP_MISSES_LURED_COGS`

[CONFIRMED] by the owner from play: ANY attack gag that lands on a
lured cog wakes it immediately — not just Sound. The knockback bonus is
applied FIRST, so a Throw or Squirt still gets its +50% against the
sleeping cog, and only then does the lure end. If the cog survives it
attacks that same round, because by then it is awake.

Drop is the exception that proves it: it always MISSES a lured cog, so
it never lands and never wakes anything.

This was `None` — an unfilled gap — and only Sound cleared the lure, on
the reading that the wiki names Sound explicitly. The wiki naming one
track is not the wiki excluding the others. The cost of the gap was not
small: `prevented` multiplies by `lure_rounds_remaining`, so every lure
was paid for rounds it would never actually deliver once anybody hit
the cog, which made a lure-and-grind line look far stronger than it
plays.

### `MULTI_LURE_ACCURACY_BONUS` — the one [ASSUMED] value

Multiple Lure gags thrown in the same round raise each other's
accuracy. This IS modelled — `multi_lure_bonus`, applied in
`simulator.apply_party_round` to the shared roll. Two group Lure 6s go
from 80% to 95%, measured.

This comment used to say the opposite, and said it for long enough that
`docs/party-strategy.md` cited it to explain away a measurement it did
not like. Only the MAGNITUDE is open, and it is [ASSUMED] rather than
[TODO] — see below.

[CONFIRMED] that it exists. TTR wiki (Lure), opening paragraph: "Using
multiple Lure gags simultaneously increases the accuracy." The same
page's update notes give the shape: "Multiple Lure gags of the same
type used simultaneously now grant a bonus (20/15/10)% accuracy
depending on the gag level discrepancies of the additional Lure gags,
with the bonus being smaller if low-level Lure gags are used."

ELIGIBILITY is now [CONFIRMED] and implemented in `multi_lure_eligible`;
only the MAGNITUDE is still open. From the v4.0.0 patch notes, which
spell out what "of the same type" means:

    Group Lures paired with another Group Lure yield 'Lure Bonus'
    Dollar Bills paired with another Dollar Bill yield 'Lure Bonus'
    Group Lures and Dollar Bills used simultaneously do not grant
    'Lure Bonus'

So it is the targeting class that must match, not the gag: two group
Lures qualify, two Bills qualify, one of each does not. In this track's
tables the Bills are exactly the single-target gags (levels 1, 3, 5)
and the Magnets, Goggles and Presentation the group ones (2, 4, 6, 7),
so `Gag.group` already carries the distinction.

The same notes settle a neighbouring rule the model happens to get
right: "Organic Lure now shifts the base accuracy of Lure by an
additional 10% rather than being an additive bonus during the battle
calculation". `Gag.prop_accuracy(organic=True)` is a base-accuracy
shift of exactly +10 for all seven Lure gags, which is that rule — and
it matters beyond accuracy, because the notes add that the shift
"better determines who the overriding Lure Gag is".

The DIRECTION is now corroborated, the magnitudes still are not. A
player's reading is that the bonus is inversely proportional to the
level gap between the lures — same level pays most, a wide gap pays
least — and the wiki's own qualifier agrees in direction: "with the
bonus being smaller if low-level Lure gags are used". A cheap lure
added beside a dear one IS the wide-gap case, so both clauses point the
same way.

What that still does not give is which of 20/15/10 a given gap selects,
and the bucket boundaries are the whole content of the rule: gap 0/1/2+
is the natural guess and it is a guess. Also unresolved: whether "of
the same type" means the same gag, the same single/group class, or
merely both being Lure; and how this composes with the Trap+Lure bonus
in `calc_prev_hits_bonus`.

Sources chased and exhausted, so the next person need not repeat it:

- The Accuracy page names a "Lure bonus" term that may push past the
  95% soft cap, but gives no formula for it.
- Both cited rebalancing PDFs (v4.0.0 and December 2021) are
  image-based — their streams decompress to graphics, not text — so
  the numbers cannot be read out programmatically.
- OPEN TOONTOWN IS THE WRONG LEAD HERE, unusually. This is a TTR 4.0.0
  addition ("now grant"), so it postdates the Toontown Online code
  entirely and nothing in that lineage can confirm it.

[ASSUMED] — NOT [CONFIRMED], and the distinction is the point.

The project owner authorised filling this in on the balance of
evidence, having read the v4.0.0 patch notes directly. Three
independent statements point the same way:

- "depending on the gag level discrepancies of the additional Lure
  gags" — the gap is what indexes it;
- "with the bonus being smaller if lower leveled Lure gags are used" —
  a cheap Lure beside a dear one is the wide-gap case;
- the player's own reading, that it is inversely proportional to the
  gap.

Mapping the three published values onto gaps of 0, 1 and 2+ in that
order is the only assignment consistent with all three. It remains an
inference about bucket boundaries that no source states.

WHAT WOULD SETTLE IT: throwing two group Lures at known levels and
recording hit rates over enough trials to separate 20 from 15 from 10.
Until then treat any result that leans on this as resting on a guess,
and if measurement contradicts it, change these three numbers and
nothing else — that is why they are a table and not inlined.

One neighbouring rule from the same patch IS pinned, and the simulator
already obeyed it by inference rather than by citation. [CONFIRMED] TTR
wiki (Lure, 4.0.0 update changes): "High-level Lure gags override the
base accuracy of low-level Lure gags when used simultaneously." That is
exactly what `simulator.apply_party_round` does when it keys a shared
roll on (track, target) and takes `max(...)` of the group's accuracies
— see the `best[key]` line there, and
`test_a_strong_lure_carries_a_weak_one_on_the_same_cog`.

The search DOES allow stacked Lure (`party_search._playable` has no
rule against it). Rejecting it was a real bug: it made a genuine TTR
play unreachable. Undervalued and reachable beats correctly valued and
impossible.

### `pick_cog_target`

PROVENANCE, WHICH IS WEAKER THAN [CONFIRMED]. The wiki gives only a
direction — "It is more likely that a Cog's single attack may target a
Toon whose gags dealt the most damage to them, though this may not
always be the case" — and no numbers. The 75/25 split and the
proportional weighting come from Open Toontown's
`BattleCalculatorAI.__calcSuitTarget`, which is Toontown *Online* code,
the same lineage this project distrusts the QED1224 guide for. It is a
much better lead than a prose description, because it is the algorithm
rather than someone's account of it, and the wiki corroborates its
shape exactly. It is still not TTR.

TWO ODDITIES IN THAT SOURCE, DELIBERATELY NOT COPIED. What is
implemented is what the code evidently means.

`__rememberToonAttack` writes `self.SuitAttackers[suitId] = [toonId,
damage]` when a later hit is at least as large as an earlier one,
replacing the per-cog dictionary with a two-element list — which then
breaks the `.keys()` calls in the selector. That one looks simply
wrong.

The weights are `damage / totalDamage * 100`, and the file is Python 2
(it calls `has_key`). If those values are integers that is integer
division, every term with two or more attackers floors to zero, and
selection falls through to uniform random — but the operand types were
inferred from the arithmetic rather than traced, so treat that as a
reading and not a finding.

Either way this implements the intent, on the judgement that TTR has
most likely fixed anything of the sort in the twenty years since, and
that reproducing another implementation's accidents would be modelling
the accident rather than the game. The discrepancy is recorded so that
a future disagreement with observed play has somewhere obvious to
start.

### `calc_kb_bonus` — the mis-indexing bug, not modeled

NOT modeled: the long-standing kbBonus mis-indexing bug the guide
documents (bonus applied to the cog at the target's index in a
differently-ordered list). It needs >1 cog and a specific ordering
mismatch, is a bug rather than a mechanic, and TTR may have fixed it.

### `calc_hp_bonus` — per cog, not per round

This is the whole reason coordinating a party is worth anything, and it
returned 0 unconditionally until multi-toon work began. A search over
the old rules could not see any value in two toons hitting the same
cog, so it would have rated four toons stacking Throw exactly level
with four toons hitting four different cogs.

PER COG, NOT PER ROUND, and this is where Toontown Online had a bug
that must not be copied back in. The bonus counts the gags of one track
landing on THAT cog. A group Geyser plus a single Storm Cloud at one
cog gives that cog 105 + 80 = 185 and the 20% on top; the three cogs the
Geyser alone reached take a flat 105 with no bonus. Applying the
multiplier to every cog a group gag touched, because two same-track
gags were used somewhere in the round, is the TTO behaviour and is
[CONFIRMED] wrong for TTR by the owner from play. `simulator._apply_track_group`
keys its contributions by cog index for this reason, and a test asserts
two cogs do not combo.

ROUNDING IS NOT WIKI-CONFIRMED. The wiki says "a 20% damage bonus" and
does not say how it rounds; `ceil` comes from the QED1224 source doc,
which describes Toontown Online. It is kept because a bonus has to
resolve to a whole number of hit points somehow, and ceil is the only
reading with a source behind it — but it is the first thing to check if
party damage ever reads a point low.

### `DAMAGE_TRAINED_FRACTION`

The real game derives this from earned experience against per-gag
minE/maxE thresholds that are not transcribed, so it is a single global
stand-in (1.0 = fully trained, 0.0 = bottom of the range).

It is a knob so a search can be run against a PESSIMISTIC assumption
and the answers compared. That comparison is the only way to ask "how
much does this recommendation depend on everyone actually being
maxed", which is the question behind a player's preference for a wide
damage margin — see the note on `objective.risk_aversion`. Nothing
about outcome variance can answer it, because at a fixed fraction the
damage is deterministic.

## state.py

### `ALLOW_LEVEL_7` — the pouch-exemption knob

Level 7 gags are one per pouch and pouch-EXEMPT, so nothing in the
ordinary cost machinery restrains them: measured across a `price` sweep
of 1.0 / 0.5 / 0.25 / 0, level-7 use did not move at all (38 thrown
every time). What restrains them today is only that the policy rarely
proposes one. Set this False to forbid them outright.

IT MUST BE READ AT CALL TIME, not captured at import, so a caller can
toggle it between runs. Both `simulator.legal_actions` and
`BattleState.can_still_damage` consult it, and they have to agree:
`can_still_damage` keys on TRACKS and ignores levels, so a toon holding
nothing but Throw-7 would otherwise be judged able to damage a cog
while `legal_actions` offered it nothing — a position the search treats
as playable and cannot play, which breaks the termination argument in
`legal_actions`.

### `ToonState.pouch_capacity`

[CONFIRMED] 20 to 80, earned by ToonTask. It is not a property of where
the toon is standing, which an earlier version had it as, deriving
capacity from the street the building was on.

Deliberately NOT in `outcomes.state_key`: nothing restocks a pouch
mid-battle or between floors, so capacity cannot change any value the
search computes. It constrains how a toon is BUILT, not how a battle
goes. If restocking is ever modelled, it has to go in the key — that is
the `free_passes` lesson (see below).

### `ToonState.fires` — last field on purpose

`ToonState` is built positionally all over the tests and tools, so
inserting this between existing fields shifted every one after it —
`organic_tracks` landed in `fires` and 26 tests died on "frozenset >
int". A new field goes on the end unless every construction site is
keyword-only.

Defaults to 0, because a fire is strictly better than any gag against
any cog and a party holding them does not play the game. They come from
the CEO, two to six a run, cap 200.

### `CogStatus.apply_lure` — no refresh, no stack

**Re-luring an already-lured cog does NOT refresh its duration.** The
existing counter runs down on its original schedule and the new gag is
simply wasted on that cog. It doesn't stack either — TTR 3.0.0 "Removed
the Lure Stacking Rounds mechanic that allowed the accumulation of Lure
rounds ... if multiple Lure Gags are used simultaneously". Neither
refresh nor stack: an already-lured cog is untouchable by Lure until
its rounds run out.

This is a no-op rather than an illegal action on purpose. A group Lure
over a partly-lured battle has to be able to catch the un-lured cogs,
so it can't be rejected wholesale — it just leaves the already-lured
ones alone.

[UNVERIFIED] The no-refresh rule comes from play knowledge, not the
wiki: the wiki documents the simultaneous-stacking removal above and
says nothing about re-luring across rounds.

### `CogStatus.copy` — the suit flag that used to vanish

Omitting `suited` from the copy silently un-2.0'd every Version 2.0
after ONE round — the flag survived only until the first copy, so a
CEO's second battle, which is entirely 2.0s, was fought against
ordinary cogs with half the health. Same omission as `fires` in
`ToonState.clone`, found the same way: a marker that appeared on round
one and never again.

### `CogState.take_damage`

THE ONE RULE WORTH KNOWING: a hit that destroys the outer suit does NOT
carry the excess into the Skelecog form. TTR removed carryover damage
in the 3.0.0 rebalancing of December 2021, so a Toontanic into a 90 hp
suit wastes 90 of its 180.

That makes v2.0 the only cog in the game that rewards precision over
raw damage, and it cuts directly against how both agents play — they
favour group gags and heavy single hits, and a board full of v2.0s
punishes exactly that.

RETURNS THE FULL AMOUNT THROWN, not the part that fitted. Every scorer
and the reward function read this as "damage dealt", and returning the
clamped value silently redefined that for the whole project — a
180-damage TNT into a 42 hp cog reported 42, and three organic-damage
tests caught it. Overkill is a SCORER's concern (`plan_waste` already
charges for it) and must not be smuggled in here.

### `BattleState.cogs_remaining`

The solver has always optimised ONE battle, which is why
`objective.scarcity_cost` exists: a hand-tuned stand-in for "an
irreplaceable gag is worth more than this fight suggests, because the
cost lands in the next one". This is that quantity instead of a proxy
for it. Spending a Railroad on floor one of five is a different
decision from spending it on the last cog of the day, and nothing in
the state could previously tell the two apart.

Capped around 30, which is roughly a full building plus its boss.

### `BattleState.allies_standing` — present, not simulated

PRESENT, NOT SIMULATED, AND THE DISTINCTION IS THE WHOLE DESIGN.
Teammates are a count rather than entries in `toons` for two reasons,
both of which broke when tried the other way round.

`is_terminal` is "every toon sad". Teammates in `toons` that the search
cannot kill mean YOUR going sad no longer ends the battle, and the
search happily evaluates positions from beyond your own death. That is
the shape of bug that once scored a hopeless position at +47.6.

Their laff would have to come from somewhere, and IT IS ON THE SCREEN —
the battle UI prints every toon's meter along the bottom ("80/95",
"91/106", ...), not just yours, which is worth writing down because
this file previously implied otherwise. What is genuinely missing is
their GAGS: the box beside each meter is the gag they have chosen and
it stays a "?" until the round resolves. A toon whose pouch is unknown
cannot be searched as a toon, only counted — so counted is what this
is.

And `search/features.py` pools over `toons`. Solo feature vectors are
bit-identical today, which is what keeps the fitted weights valid;
putting stand-in toons in the list would change the vector for every
live party position and quietly invalidate them.

So what this buys is exactly one thing, and it is the one thing a COUNT
determines without knowing anything else about the people holding the
gags: a single-target cog attack now has somewhere else to land. See
`your_target_share`.

What it deliberately does NOT buy, because a count cannot know it:
teammate gags. No Trap set for someone else's Lure, no stacking a track
for `calc_hp_bonus`, no counting their damage toward the fight. The
advice still plans YOUR pouch alone and is correct to —
`solver/search/party_search.py` is the module that searches a party's
joint plan, and it needs their loadouts to do it.

### `BattleState.free_passes` — the widening that broke exact `solve()`

A pass is a real move — conserving a scarce gag, or in a party
declining to hit a cog because `mechanics.pick_cog_target` makes it
prefer whoever damaged it most, so attacking draws its next swing onto
you.

It is BUDGETED rather than free, and that is what keeps `solve()`
exact. Termination rests on a lexicographic measure that must strictly
decrease: (gags remaining, lure rounds remaining, free passes). An
unlured pass spends no gag and ticks no lure, so without a budget the
search could walk pass → pass → pass forever and the state graph would
stop being a DAG.

CURRENTLY UNUSED — `legal_actions` is back to the narrow rule.

The widening (pass as an ordinary choice: conserve a scarce gag, or
decline to attack because `pick_cog_target` aims a cog at whoever hurt
it) is right, and shipping it broke exact `solve()`. With a budget of 2
the solver valued a position at +88.85 and with 1 at +84.30, choosing
to pass in the first — but passing only costs laff and a turn, so it
cannot CREATE 4.55 points. Working the same node by hand gives ~79.9,
and enumerating its outcomes directly gives 84.59: three different
numbers for one value, which is a memo serving answers to the wrong
question.

Adding `free_passes` to `outcomes.state_key` was necessary and not
sufficient, so something else in the search caches across it. That has
to be found before this comes back: exact `solve()` is what the solo
results and every fitted label rest on, and a wrong answer there is
worth more than any strategic gain here.

A pass while lured does NOT draw on this, because a lured pass has its
own decreasing quantity in the lure timer — that is the trap-and-wait
line, which can need many rounds.

### `BattleState.clone`

Exists because `copy.deepcopy` dominated the solver's runtime — it was
91% of a depth-2 search, since expectimax copies a state per outcome
branch per node. This is ~20x faster for the same result. Extend it
whenever you add a mutable field to any battle dataclass.

Both `track_exp` and `gag_counts` are SHARED, not copied. Cloning is
the single most expensive thing the search does — 586,000 clones for
one three-cog depth-2 position — and copying these two was most of it.
`track_exp` is fixed for the whole battle so nothing mutates it.
`gag_counts` does change, but only in `simulator.apply_toon_action`,
which copies before writing. Sharing here plus copying there costs one
dict copy per action instead of one per outcome branch.

Pink slips (`fires`) are SPENT, so they must be carried. Omitting this
defaulted every clone to zero and the fires simply evaporated — a CEO
sweep reported "20 used every run" which was not usage at all, it was
the loss being read as spending. Anything mutable enough to be spent
has to appear in `clone`; the field list is not decoration.

### `BattleState.is_win`

The holdout check is belt and braces: `facility.reinforce` fills freed
slots during round resolution, so a state with a live holdout and an
empty field should not normally exist. Should one arise on a path that
skips reinforcement, calling it a win would end the floor early and
hand back a victory the toon has not had — expensive and silent, so it
is checked here too.

### `BattleState.your_target_share`

1/(1+allies): uniform among the toons standing. Group attacks are not
diluted at all — they hit everyone — so this is applied per attack by
name against `data.GROUP_ATTACKS`, never to a cog's damage as a whole.

WHY UNIFORM, WHEN `mechanics.pick_cog_target` IS NOT. That function
sends `REVENGE_CHANCE` (75%) of attacks at whoever damaged the cog,
weighted by how much, and only the remaining 25% uniformly. Uniform is
what that resolves to when everyone is throwing gags at roughly equal
rates, which is what a real group is doing — the damage weights are
then roughly equal and the revenge branch spreads like the uniform one.

IT IS OPTIMISTIC IN A SPECIFIC, KNOWABLE CASE, and this is the
limitation to hold in mind rather than a hidden one: if you are the one
dealing the damage — you dropped a Railroad on a cog your teammates
have not touched — revenge concentrates that cog's attacks on you, and
your real share is nearer 0.75 than 0.25. The model cannot see it,
because it would need each teammate's damage and nothing reports it.

The alternative was to assume the revenge branch always lands on you,
which is safe in that case and badly wrong in every other: at four
toons it gives a share of 0.81, so the dilution would be almost nil and
the count would not be worth reading.

## outcomes.py

### Module docstring — why the cog phase doesn't explode

Naively the cog phase is a joint over (which attack × hit/miss) for
every cog: (5 attacks × 2)^4 = 10,000 branches for four cogs. Two
things collapse it. First, the toon is solo, so a cog's attack choice
has no effect on the next state beyond the damage number — the joint
convolves down to a distribution over *total damage*, usually a few
dozen values. Second, the only per-cog state the phase can change is
whether a lured cog woke up, so the surviving joint is
(woken-subset × total-damage), not the full product. The visualizer's
`convolve()` does the same collapse in JS.

The toon phase is NOT reimplemented here — this module calls
`simulator.apply_toon_action(state, action, hit)`, the same
deterministic function `simulator.step` uses once it has rolled the
dice. So gag damage, kbBonus, trap detonation, and lure application can
only be written once.

The cog phase genuinely does exist twice: `simulator._resolve_cog_phase`
samples it, `cog_phase_outcomes` enumerates it. Enumerating is not a
transformation of sampling, so some duplication is unavoidable there.
Two things keep the pair honest — both go through `mechanics` and the
same data tables for every constant, and `tests/test_outcomes.py`'s
`test_matches_sampled_step` compares the enumerated distribution
against 8,000 samples of `step`, state by state and reward by reward.
If they ever drift, that test fails.

(Having `step` sample *from* this enumeration would remove even that
seam, but it would make every sampled step pay for building the full
distribution — far too slow for the rollout-heavy uses `step` exists
for — and it would make simulator and outcomes mutually recursive.)

### `cog_damage_distribution` / `_damage_distribution`

Cached because a three-cog depth-2 search asked for this 1.1 million
times, and the distribution depends only on the cog's department, type
and level. The returned dict is shared, not rebuilt per call — do not
mutate it.

### `_damage_distribution_shared`

SPLIT BY ATTACK, NOT APPLIED TO THE COG. This is why it cannot work off
`_damage_distribution`, which has already merged the attacks into
damage numbers and thrown the names away:

- a single-target attack picks one toon, so it reaches you with
  probability `share` and otherwise deals you nothing;
- a GROUP attack hits every toon standing, so it reaches you whatever
  the party size — it is not diluted at all.

Scaling a cog's whole distribution by `share` would quietly halve the
Lawbot group attacks that are exactly what makes a crowded battle
dangerous. `data.GROUP_ATTACKS` is [CONFIRMED] from the wiki's own two
categories, and being group is a property of the ATTACK rather than of
the cog throwing it.

A miss is already damage 0 and is left alone: it does not matter whose
face it missed.

### `worst_case_damage`

Cached on the same key as the distribution: the search's value bounds
ask for this once per node, which was 367,000 times on a three-cog
depth-2 position.

### `cog_phase_summary` — marginals, not the joint

The obvious thing for a UI would be the *joint* — every combination of
what all the cogs do — but that is combinatorial: three cogs produce
~430 distinct lines, so even the twelve most likely cover under a tenth
of the probability, and showing them would badly misrepresent the
round. The marginals are compact, exact, and answer the actual question
("what can this cog do to me, and how likely is each?"). The joint over
total damage is still available, merged, from `cog_phase_outcomes`.

### `collapse_damage`

A ply costs `actions × chance outcomes`, and the second factor is what
keeps the search shallow — 20 to 70 branches per action, almost all of
them the same events with a different damage total. Unlike the toon's
own hit roll, that number carries no decision: the cogs cannot kill
each other, cannot change what gags remain, and cannot alter anything
the next choice depends on except the laff figure.

So branches sharing a cog configuration collapse into one carrying the
probability-weighted mean laff. Outcomes per action drop to a handful,
which is worth one to two extra plies.

Two things are deliberately NOT merged. Branches whose cog states
differ at all — a gag hit rather than missed, a lure held rather than
ended — stay separate, because those do change the next decision. And a
branch where the toon died stays separate from one where it survived:
averaging a death into a survival is exactly the distortion that would
make the search cheerfully walk into a loss.

This is an approximation, and the only one here that touches the shape
of the tree rather than its tails. It makes the search risk-*neutral*
about damage, which is wrong near zero laff and wrong for an objective
that weights laff heavily, so callers should keep the plies nearest the
root exact — see `evaluate`'s `exact_plies`.

### `merge_key`

Deliberately omits the gag counts, which `state_key` includes. Every
outcome of a single action spent the same gag from the same pouch, so
the counts are identical across all of them and hashing a
twenty-element frozenset of them per outcome is pure overhead —
measured at 11.8 million generator steps on a three-cog depth-2 search,
for a value that never varies within the comparison.

`allies_standing` is deliberately NOT here, on this function's own
stated rule: every sibling being merged is an outcome of ONE action in
ONE state, so the party size is identical across all of them — the
same argument that keeps the gag counts out. It IS in `state_key`,
where states genuinely differ.

### `state_key`

This is the hottest function in the search — a depth-2 two-cog position
calls it 319,000 times — so two things here are deliberate and worth
keeping.

The track is used as-is rather than as `t.value`. `Track` subclasses
`str`, so the member is already a perfectly good key, and `.value` goes
through `DynamicClassAttribute` on every access: it accounted for 6.2
million enum lookups and a fifth of the whole search.

The gag counts are a frozenset rather than a sorted tuple. Both are
canonical, but a frozenset needs no comparisons, and this key is only
ever hashed — never ordered, never serialised.

`free_passes` is in the key because it changes `legal_actions`, so two
states differing only in it are genuinely different nodes. It was left
out when the field was added — with it collapsed, the memo answered a
position holding three passes with the value of one holding none. The
symptom was a search that liked passing MORE as its laff dropped, which
is backwards, and it was visible only because someone asked why it
would not throw.

Contrast `round_num`, which stays out: nothing in the mechanics reads
it, so including it would split identical nodes for nothing. The test
is whether a field can change what happens next, not whether it
changes.
