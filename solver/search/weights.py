"""Every tuned number the party search uses, in one place.

WHY THESE LIVE TOGETHER. They were spread through 2400 lines of
`party_search.py`, next to the code each governs, which made the tuning
surface impossible to see whole. The measurement that justifies each one
travels with it -- these comments are the record, and docs/scoring.md is
the inventory that says where the three scorers disagree.

**READ THEM AS `weights.NAME`, NEVER `from .weights import NAME`.** The
second form binds a copy, so patching `weights.FIRE_FLOOR` would stop
reaching the reader -- silently, and only in the tests and sweeps that
do exactly that. `tests/test_fires.py` patches `FIRE_PRICE` and
`FIRE_FLOOR`, and `tools/fit_scorer.py` rebinds `QUICK_W` wholesale.

The cost of the attribute lookup was measured before this move: 24.4ns
against 21.3ns for a plain global, ten lookups per `_quick_score` call,
so 31ns on a 35,600ns call. Nine hundredths of one percent.
"""
from __future__ import annotations

from typing import Optional

from ..state import Track

# ---------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------
# Every number below was MEASURED; most carry the measurement in their
# own comment. docs/scoring.md is the inventory of where the three
# scorers disagree -- read it before changing one.

# Candidate actions kept per track per toon. Two was not enough and the
# mistake is recorded in docs/party-strategy.md: at two, Sound offered
# only levels 7 and 6, so every mixed-level Sound plan -- including the
# best one available -- was unreachable, and the search reported the
# wrong answer with total confidence.
CANDIDATES_PER_TRACK = 4


# Plans considered at a MAX node, after ranking them cheaply. The joint
# space is far larger than this; the cap is what makes the search
# finish, and it is the first thing to raise when an answer looks wrong.
MAX_PLANS = 60


# Playouts per plan at a chance node.
PLAYOUTS_PER_PLAN = 8


# How many candidate plans in each track family get a simulated
# `_quick_score`. Everything past this is dropped unscored -- see
# `plans`. Scoring every playable combo was 28% of the search and its
# results were almost entirely discarded by the truncation.
QUICK_SCORED_PER_TRACK = 40


# WEIGHTS FOR THE TWO PLAN SCORERS, kept apart on purpose.
#
# They were one set of constants and that was wrong: `_quick_score`
# ranks candidate plans while `_greedy_score` plays the rollouts every
# plan is graded against, and the two want different numbers. Raising
# the shared heal weight to 12 gained the hybrid a point and cost the
# search two to three, because it made the SIMULATED FUTURE passive
# rather than the search careful -- see `prevented`.
#
# Fitted by `tools/fit_scorer.py` against buildings finished, which is
# the only ground truth a party position has: exact `solve()` cannot
# reach one, and both attempts to manufacture labels from a stronger
# search (the P0 ranking head, expert iteration) lost end to end.
QUICK_W = {
    "heal": 2.0,        # laff restored, capped at headroom
    "armed": 1.0,       # trap laid this round, via `armed_credit`
    # PER COG KILLED, REGARDLESS OF WHICH, WITH NO OVERKILL CHARGE. A
    # known defect, not a simplification: an organic Cake doing 165 into
    # a 20hp cog scores the same free 120 points as killing a 196hp one
    # (the owner reported picks this produced as absurd). `objective.
    # waste_weight` (20.0 in `balanced`) exists for exactly this, but
    # `_quick_score` has no objective to read it from, so `hybrid.climb`
    # cannot avoid overkill in principle.
    #
    # Unfixed here: a hand-fitted waste weight is how `prevent` got its
    # worst entry for a long time, so a real one needs sweeping and
    # confirming on held-out seeds first. Until then, `--engine search`
    # with `balanced` is the preset that actually prices waste.
    "kill": 120.0,      # per cog killed, regardless of which
    "kill_threat": 0.0, # per point of threat the kills removed
    # 9.0. Was 2.0, fitted against a buggy `prevented` that overstated
    # Lure (crediting the FULL lure duration under a rule where a lured
    # cog stayed asleep through damage) -- two errors pointing opposite
    # ways, each reading wrong alone. Corrected and reswept, confirmed on
    # untouched seeds at 200 sides/cell: CEO at zero leftovers 9.0% ->
    # 54.0% (p<0.0001, the largest confirmed effect in this project),
    # lure share 21% -> 37%, buildings 66.0% -> 67.0%, VP unchanged.
    "prevent": 9.0,     # incoming damage removed, via `prevented`
    # CHARGED for damage thrown past what a cog had left. SWEPT, STAYS AT
    # ZERO: flat-to-worse for every weight tried, 0-400, across buildings
    # (d7: 123/150 at zero vs 120 at best, p=0.27-0.51; d9: 0/150
    # everywhere, can't discriminate) and VP (47/120 at zero vs 50 at
    # 400, noise). A first pass over that range used a weight scale 2000x
    # too small to change a single decision; corrected and paired with
    # `width`=12 (the policy's offered proposals otherwise all being
    # Birthday Cake, so no weight reaches the cheaper gag), it looked
    # like a VP gain on selection seeds (72/150 -> 85/150, p=0.092) but
    # did NOT confirm on 400 held-out seeds (186/400 -> 195/400, p=0.448;
    # buildings 313 -> 302, p=0.266).
    #
    # Overkill is real and visible, but not worth fixing: a dead cog
    # stops attacking, and paying a scarcer gag to end a threat a round
    # sooner is a trade `kill`'s flat bonus already makes correctly.
    # Charging for waste instead pushes the scorer onto gags that don't
    # quite kill, so buildings use MORE gags (14.1 -> 15.0), not fewer.
    # `width` stays at 3, this at zero.
    #
    # `landed` is HP-capped, so overkill is neither credited nor charged:
    # a 72hp cog dying to a 165-damage Cake or a 120-damage Storm Cloud
    # score identically, and `price` can't separate them either (it
    # charges by gag level and carry limit, not damage discarded).
    #
    # Uses `plan_waste` (same measure `objective.waste_penalty` scales):
    # weight x wasted_fraction x scarcity, so a gag that is the only
    # thing that kills pays almost nothing.
    "waste": 0.0,
    # Toons a round of the WOKEN field would knock out. [OWNER]: "if the
    # expected incoming ... is greater than the current HP ... we should
    # heal or kill" -- `past_the_death_line` implements exactly that (a
    # toon on 25 facing 84 incoming must heal; one on 60 may kill two
    # cogs instead and drop the woken round under their laff).
    #
    # SHIPPED AT 0.0: changes nothing measurable (solo VP, 20/round, 15
    # runs/cell, weight 0 vs 300: bare 21.7 -> 21.9 rounds, cards
    # 8.0 -> 8.0, cleared 0.0% everywhere) -- flat while the toon is
    # healthy, like `risk` below for the same reason. Kept, wired and
    # tested rather than deleted: a rule the scorer couldn't express
    # before, not one proven wrong.
    "deadline": 0.0,
    "risk": 0.0,
    # Rounds of incoming the party's laff covers, capped -- the only term
    # reading laff LEVEL rather than a delta.
    #
    # DOES NOTHING FOR GAG CHOICE, EVERYTHING FOR UNITES (`survival_rounds`
    # predicts this, the sweep confirms it). Solo VP, 80 runs/cell, win
    # rate at 12 cogs: unites off, weight 0 -> 1600 gives 23.8% -> 21.2%
    # (flat-to-negative, can't move a choice that doesn't change laff);
    # unites on, 0 -> 1600 gives 18.8% -> 81.2% (worth sixty points, all
    # of it unites spent: 5.0/run at the top).
    #
    # A PREFERENCE, NOT A TUNING: the owner holds unites as a last resort
    # since spending them freely "trivializes a lot of stuff", and a
    # weight that wins by spending five a fight buys wins with a currency
    # farmed from whole CFO runs. Left at 0.0 for the owner to set.
    #
    # Does not reach a full 20-cog VP: 0.0% at every weight and unite
    # budget tried (survives 16.1 rounds of the 30.2 needed) -- the wall
    # there is elsewhere. Solo buildings are bit-identical at every
    # weight 0-800 (26.0%/27.0%, +0/-0) since `incoming` pinned makes the
    # term constant across the menu; 12-cog VP with unites climbs
    # 35.0% -> 95.0%, with a bounded SOS book 27.0% -> 52.5%, plateauing
    # from 200 for unites and ~600 for SOS (`SOS_PRICE` is double
    # `UNITE_PRICE`); 400 sits mid-plateau for one, near peak for the
    # other.
    #
    # Inert until `OFFER_UNITES` or `OFFER_SOS` is on: with neither,
    # nothing changes a toon's laff mid-plan, so this is a constant
    # across the whole menu.
    "survive": 400.0,      # CHARGED, per standing toon a round could sink
    # RE-SWEPT on a VP that actually finishes -- two earlier bugs (a dead
    # `unites.tick_cooldown` caller, and a VP floor truncated at 20
    # rounds) had hidden whether husbanding a pouch pays, since the fight
    # could end before it bound. [OWNER] reported a level 7 spent where a
    # 5 would do, confirmed by the exact search preferring the cheaper
    # gag on the same board.
    #
    # Solo VP, 20/round, fires+unites+SOS, 10 runs/cell, paired against
    # 1.0: price 2.0/4.0/8.0 cleared 50%/60%/0% (vs 80% at 1.0, +0/-3,
    # +0/-2, +0/-8), with mean gag level and sevens-used both falling as
    # the weight intends. The thrift is real and it loses -- not one win
    # gained in any cell, thirteen lost. Third time this project has
    # reached that answer: a cheaper gag doesn't quite kill, the cog
    # swings again, and laff is what runs out.
    "price": 1.0,       # gags spent, from the pouch
    # CONSUMABLES, priced separately from the pouch. Slips and cards used
    # to ride on `price`, so lowering that to loosen gag thrift also made
    # them free and cancelled FIRE_PRICE, FIRE_FLOOR and SOS_PRICE.
    # Split so each can be tuned without the other; 1.0 reproduces the
    # old arithmetic exactly, which the refactor lock confirms.
    "spend": 1.0,
}


# `kill_threat` and `risk` STAY AT ZERO -- `risk` refuted twice, and only
# the second refutation is real.
#
# FIRST: measured nothing. `toons_at_risk` returned 0.0 on every one of
# 2000 sampled positions (it divided an already-probability-weighted
# expectation by party size, a feature bug since fixed), so an ES run
# and a 0/2/5/10 sweep could not have moved a single decision either way.
#
# SECOND: looked real on a selection sweep (900 positions, monotone,
# p=0.012 at weight 20, a plateau across 10-40 rather than a spike) and
# did not replicate on 1600 held-out positions (+0.1%, p=1.000, mixed
# signs). The plateau looked like protection and wasn't -- a lesson in
# how convincing a selection sweep can be.
#
# On 240 buildings used for neither fitting nor validation, baseline,
# fitted (all seven weights), and baseline+these-two-features all score
# 63.7% -- identical, meaning these weights barely change WHICH PLAN
# gets picked.
#
# Left in, behind zero weights that skip their computation, because the
# next person to look will notice the same two gaps. A third gap
# (charging for threat LEFT standing) is deliberately not a term:
# `prevented` is already before-minus-after with `before` fixed while
# ranking one position's plans, so it would just flip the ordering's
# sign.
GREEDY_W = {
    "heal": 2.0,
    "kill": 60.0,
    "prevent": 2.0,
    "price": 10.0,
    "waste": 0.25,
}


# What a restored point of laff is worth against a point of cog damage,
# for a scorer that has no `objective` to read. Mirrors
# `objective.laff_weight` in INTENT -- what `round_reward` charges for
# laff LOST -- but not in magnitude: `laff_weight` is 1.0 in every
# preset but SURVIVE (3.0) and GLASS_CANNON (0.25).
#
# Read by `_cheap_score` only: a heal weight on the Toon-Up branch, a
# PREVENTION weight on the Trap branch (`forgone = LAFF_POINT_VALUE *
# threat * rounds`). `QUICK_W["heal"]` and `GREEDY_W["heal"]` price
# healing separately and happen to equal this -- three constants, one
# number, no link between them (docs/scoring.md).
#
# Swept on 45 buildings after the reinforcement-slot fix: 0.0/0.5/1.0/
# 2.0/3.0 -> 62.2%/64.4%/66.7%/68.9%/64.4% finished. (An earlier,
# perfectly flat sweep was a red herring: 42% of runs were then locked
# in a pass loop by a reinforcement bug, independent of healing.)
# Differences of a few points on 45 seeds are noise; what holds up is
# that healing matters and 3.0 overcorrects.
LAFF_POINT_VALUE = 2.0


# How much of a trap's damage to credit before it has been sprung. Less
# than one because the payoff is conditional on a lure landing later and
# on the cog surviving until then, but nowhere near the flat 20 it used
# to score.
TRAP_DISCOUNT = 0.6


# How many extra candidates `greedy_plan` simulates purely to give
# unrepresented tracks a hearing. Costs simulation in the rollout hot
# path; buys the guarantee that no track is cut by arithmetic alone.
TRACK_PROBES = 3


# How many of a toon's candidate actions `greedy_plan` simulates during
# a rollout; the rest are ranked by arithmetic alone.
#
# Swept at 2: `_cheap_score`'s pick agrees with the simulated one on 288
# of 328 decisions (88%), so simulation mostly confirms arithmetic and 2
# keeps a second opinion for the rest at a fifth of the cost of going
# wider.
#
# NOT 1: across four test positions, k=1 loses 1.54 points on a
# mixed-cog-HP board where the plan differs on every decision -- exactly
# where choosing between similar-damage options matters and arithmetic
# (blind to knockback/trap triggers) goes wrong. k>=2 was identical
# everywhere else tested.
GREEDY_SHORTLIST = 2


# THE THIRD SCORER'S WEIGHTS. `_cheap_score` ranks single actions by
# arithmetic alone, and its terms used to be bare literals in the middle
# of the function -- which is why an audit of "how many places price a
# kill" kept missing one. Named here so they are greppable and can be
# compared with the two tables above. NO VALUE CHANGED when they were
# named; every number is what the literal was.
#
# docs/scoring.md is the inventory and records where these disagree with
# `QUICK_W` and `GREEDY_W`. Read it before changing one.

# Scarcity units in the fast scorers' own currency: a gag costs
# `level + SCARCITY_UNITS / carry_limit`. See `_gag_units`, which is the
# one definition of that price, and `Objective.scarcity_cost`, which
# expresses the same idea on the objective's scale and cannot be read
# from here.
SCARCITY_UNITS = 20.0


# ON, for a reason that is not a measurement. Prices a gag's scarcity by
# how many the toon actually HOLDS, not its carry limit -- [OWNER]:
# "shouldn't it be scaled by 9 not 15 for magnets, since that's how many
# magnets I actually have in the pouch." Nothing restocks mid-run, so
# held count is the opportunity cost that matches what the solver
# optimises; `carry_limit` can't express it.
#
# Composes with the scarcity term (few left) and
# `horizon_cost * cogs_remaining` below (much still to fight): dear when
# scarce and early, cheap when scarce but last.
#
# MEASURED NEUTRAL, shipped anyway: +0/-0 across facility play and solo
# VP at 12/16/20 cogs. Not inert (a last Big Magnet prices 24.00 vs
# 5.33) but the whole price term is a median 4.79% of `_quick_score` and
# this moves ~1.24% of it -- too short a lever to steer with, so the
# tie-break is which model is true.
#
# WATCH IF `QUICK_W["price"]` IS EVER RAISED: at a longer lever the
# hazard becomes real -- your last gag of a kind would cost nearly a
# Presentation, and an unspent gag is worth nothing.
SCARCITY_USES_HELD_COUNT = True

# Extra cost for spending your LAST copy of a gag, on top of scarcity.
# Zero is off.
#
# Without it, a 14-unit scarcity gap (Presentation 27 vs Hypno-goggles
# 12.67) loses to a 142-point score gap, so the scorer takes
# Presentation every time on accuracy alone (95% vs 80%) -- not duration,
# since `prevented` caps both lures at the same 113.1 by `reach`. The
# missing idea: a one-of-a-kind gag is categorically unlike one you hold
# three of, and `_quick_score` (one round) can't price keeping the
# option for a worse board later. This is the crude stand-in.
#
# Swept on the VP (where the problem shows; street/facility rarely rank
# a level 7 first): units 0/40/100/200 -> VP win 53.0%/57.5%/56.5%/
# 40.0%. 200 is thirteen points WORSE and significant (p=0.003) --
# priced that high, a last copy never gets thrown, even the only group
# lure left. 40 confirmed on a fresh seed base: 53.0% -> 60.3%, p=0.010.
LAST_COPY_UNITS = 40.0


# Credit for an action that finishes a cog. Note this is the GREEDY
# table's kill price (60.0) and not the QUICK table's (120.0), while the
# fire branch of this same function charges `QUICK_W["kill"]` -- so one
# function prices a gag kill and a pink-slip kill on two different
# scales. Recorded, not changed: see docs/scoring.md, "where two systems
# disagree".
CHEAP_KILL_BONUS = 60.0


# Credit per cog a Lure would catch. The flat term `expected_incoming`'s
# docstring describes as having "no relation to what those cogs were
# about to do" -- `prevented` replaced it in the two simulated scorers,
# and this shortlist ranker still uses it.
CHEAP_LURE_VALUE = 25.0


# Charge a plan for waking cogs it had asleep. ON, measured: the fourth
# correction to `prevented` and the first to survive (the previous three
# were arithmetic refinements to the CREDIT side and each lost 2-3
# points). This instead charges the SPEND side -- nothing previously
# charged for waking four sleeping cogs for free.
#
# Paired, 200 sides/cell, off -> on: buildings 64.5% -> 67.0% and
# 68.5% -> 71.5% (p=0.031), CEO-0 69.5% -> 73.0%, CEO-2 54.5% -> 61.5%
# (p=0.038), CEO-4 31.0% -> 36.5%, VP unchanged at ceiling. Pooled 76
# up / 33 down, p<0.0001.
#
# The weight did not need rescaling -- sweeping `prevent` with this on,
# 9.0 still beats 4, 2, 1 and 0.5 monotonically and significantly.
WAKE_COSTS_PREVENTED = True


# A lured cog is credited for the quiet it will ACTUALLY provide: four
# sleepers are worth 1+2+3+4 rounds of silence, not 4+4+4+4 -- the one
# about to die was never going to stay asleep, the one at the back was.
# Ordered by remaining health, the order a player actually clears them.
# (Was `PER_COG_REACH`, which named the variable, not the behaviour.)
#
# Argued and measured in `party_search.prevented`, which reads all four
# of these flags -- follow the pointer rather than duplicating the case
# for each here.
SLEEPERS_WAKE_IN_TURN = True


# Whether an already-lured cog buys anything more. It does not: it was
# paid for when the lure landed. See `party_search.prevented`.
LURE_IS_SPENT_ON_SLEEPERS = True


# Whether killing a sleeping cog counts as silencing it. It does not --
# it was already quiet. See `party_search.prevented`.
LURED_KILL_SILENCES_NOTHING = True


# The ceiling on `survival_rounds`, in rounds. Argued in `party_search.survival_rounds`,
# which is the only reader.
SURVIVAL_CAP = 4.0


# What one pink slip costs the scorers, PER COG STILL TO COME. A slip is
# finite and nothing restocks it, so it belongs in the same term as a
# gag's scarcity.
#
# Measured, not guessed: with slips free, the party spent all ten on the
# waiter battle and reached the Big Cheese holding 0.3 of 10 -- CEO sat
# at 0% for ten banquet leftovers, though battle two alone from full
# resources clears 93%, so arriving disarmed was the problem, not the
# fight.
#
# PROPORTIONAL TO WHAT'S LEFT, no constant term -- a flat price helped at
# five leftovers (38.0% -> 49.5%, p=0.008) but HURT at zero (88.5% ->
# 82.0%, p=0.021) by also suppressing slips in the last battle, where an
# unspent slip is worth nothing. Scaling by `cogs_remaining` falls to
# zero once nothing is left to save for: hoard while cogs are coming,
# spend freely at the end.
#
# 20 is directional, not proven: neutral at zero leftovers (p=0.50),
# positive but not significant at five (p=0.22) on 200 CEO sides. What
# it clearly does is unstick ten leftovers from exactly 0% at every
# non-zero price tried.
FIRE_PRICE = 20.0


# Charged for a slip WHATEVER the horizon, because `cogs_remaining` is 0
# on every panel-built board (it can't know what a VP or building still
# holds), making `FIRE_PRICE * cogs_remaining` zero and slips free --
# how a pink slip got spent on a 6hp level 1 Cold Caller in live play.
#
# Swept against `QUICK_W["waste"]` (opposite pulls: waste charges gags
# for overkill but skips fires by design). First pass, 150 then 250
# held-out runs/cell: floor 0/20 -> VP 85.6%/86.4% (+9/-7, p=0.80, free)
# and 0.8 slip cheaper; waste 30 looked worth +2.6 buildings for -2 VP on
# the selection set but didn't hold out (23.6 -> 24.0, VP cost -4.4,
# p=0.09) -- stays at zero, gag overkill unfixed.
#
# RE-SWEPT once unites and SOS existed (solo VP had been ~86%, now ~94%,
# freeing headroom). 150 then 200 held-out runs/cell, everything
# available: floor 20/60/120/200 -> d9 win 63/66%, 65/70%, 65/67%, 53%;
# VP win 95/95%, 94/94%, 95/94%, 85%. 120 zeroes the slip spent on easy
# content (the owner's rule: standard play shouldn't need one) while
# spending nearly a whole slip LESS per VP at the same win rate. 200 is
# too far. d9 is noise between 60 and 120; the economy decides it.
FIRE_FLOOR = 120.0


# A branch this unlikely is not worth a probe. The pruned mass is
# renormalised away, so this trades a little accuracy in the tail for
# skipping leaves that cannot move a ranking.
MIN_LEAF_PROB = 1e-3


# ---------------------------------------------------------------------
# The greedy scorer and rollouts
# ---------------------------------------------------------------------
# A THIRD scorer, ranking single actions by arithmetic alone. It does
# not share `QUICK_W`; `_gag_units` is the one price both agree on.

# Rounds a rollout will play before giving up and calling the position
# unresolved. A real battle ends well inside this; the cap only stops a
# pathological position (mutual inability to finish) spinning forever.
ROLLOUT_ROUNDS = 12


# Is a heal worth less while the cogs are still swinging?
#
# [OWNER, from play]: "if cogs aren't lured, then healing is rather
# pointless because they'll just attack" -- laff put back under fire is
# handed straight back, so a heal is worth what SURVIVES the round. Lure
# the field (or land Cogs Miss) and the same heal keeps all of it.
#
# `_restored` already caps a heal at headroom (worth more when low);
# this is the independent other half -- headroom says how much CAN go
# in, this says how much STAYS in. Charged against the PRE-plan
# `expected_incoming(state)` (same figure `survival_rounds` reads) so a
# lure thrown the same round isn't credited twice, once here and once in
# `prevented`.
#
# NOT YET SWEPT -- a rule the owner states about the game, on by default
# for that reason. If ever measured to cost play, the fix is to turn it
# off here, not bury a compensating constant elsewhere.
HEAL_DISCOUNTS_INCOMING = True


# Does a sleeping cog still count against how long the party survives?
#
# [OWNER, from play]: the good play is to lure the field and heal INSIDE
# that window. Previously unexpressed: with everything asleep,
# `expected_incoming` is 0, so `survival_rounds` (laff / incoming)
# saturated at `SURVIVAL_CAP` and 120 laff scored the same as 4 -- blind
# to a toon about to die exactly when it was safe to help them.
#
# On: the survival term falls back to `latent_incoming` (sleepers
# counted) whenever nothing is swinging right now; off, it saturates as
# before. Does NOT touch `expected_incoming` itself -- a lured cog really
# does skip its attack, and `prevented` is built on that.
LURE_IS_A_REPRIEVE = True
