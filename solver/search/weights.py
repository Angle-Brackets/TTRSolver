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
#
# Every number below was MEASURED, and most carry the measurement in
# their own comment. docs/scoring.md is the inventory and records
# where the three scorers disagree. Read it before changing one.
# 
# They stay module-level and next to the code they govern rather
# than collected at the top: `_fire_price` reads them at call time
# so a test can patch `party_search.FIRE_FLOOR`, and tests and
# tools/fit_scorer.py do exactly that.

# Candidate actions kept per track per toon. Two was not enough and the
# mistake is recorded in docs/party-strategy.md: at two, Sound offered
# only levels 7 and 6, so every mixed-level Sound plan -- including the
# best one available -- was unreachable, and the search reported the
# wrong answer with total confidence.
PER_TRACK = 4


# Plans considered at a MAX node, after ranking them cheaply. The joint
# space is far larger than this; the cap is what makes the search
# finish, and it is the first thing to raise when an answer looks wrong.
MAX_PLANS = 60


# Playouts per plan at a chance node.
SAMPLES = 8


# How many candidate plans in each track family get a simulated
# `_quick_score`. Everything past this is dropped unscored -- see
# `plans`. Scoring every playable combo was 28% of the search and its
# results were almost entirely discarded by the truncation.
SCORE_BUDGET = 40


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
    # PER COG KILLED, REGARDLESS OF WHICH, AND NOTHING CHARGES FOR
    # OVERKILL. Those two facts together are a known defect rather than
    # a simplification, and they are the explanation for a run of picks
    # the owner reported as absurd: a Storm Cloud at a lured level 1, a
    # Birthday Cake at a 20hp Name Dropper with a 196hp Mr. Hollywood
    # asleep beside it, Cakes into level 7s.
    #
    # Killing the smallest cog on the field scores exactly what killing
    # the largest does, so an organic Cake doing 165 into 20 hp is a
    # free 120 points. `objective.waste_weight` exists for precisely
    # this and is 20.0 in `balanced` -- but `_quick_score` takes no
    # objective, so the scorer that ranks the policy's proposals cannot
    # read it, and `hybrid.climb` cannot avoid overkill in principle.
    #
    # Not fixed here because a weight added by hand is how this table
    # got its worst entry: `prevent` sat at 2.0 for a long time because
    # it had been fitted against a term that was itself wrong. A waste
    # term needs sweeping and confirming on held-out seeds, and until
    # then the honest advice is `--engine search` with `balanced`, the
    # one preset that prices waste.
    "kill": 120.0,      # per cog killed, regardless of which
    "kill_threat": 0.0, # per point of threat the kills removed
    # 9.0, and the journey there is the point. It sat at 2.0, fitted
    # against a `prevented` that multiplied by the FULL lure duration
    # under a rule where a lured cog stayed asleep through damage. That
    # term wildly overstated Lure, so the fit crushed the weight down to
    # offset it -- two errors pointing opposite ways, and reading either
    # alone gave the wrong answer about the other.
    #
    # With the rule corrected and the term remodelled, swept and then
    # confirmed on untouched seeds at 200 sides a cell: CEO at zero
    # leftovers 9.0% -> 54.0% (+96/-6, p<0.0001), lure share 21% -> 37%,
    # buildings 66.0% -> 67.0% and VP unchanged. The largest confirmed
    # effect measured in this project.
    "prevent": 9.0,     # incoming damage removed, via `prevented`
    # CHARGED, for damage thrown past what a cog had left. SWEPT, AND
    # IT STAYS AT ZERO -- 0/20/60/150/400 over three regimes, common
    # random numbers throughout:
    #
    #   buildings d7   123/150 at zero, 120 at best, monotonically
    #                  WORSE with weight, p = 0.27-0.51
    #   buildings d9   0/150 everywhere; nothing solo clears one, so
    #                  the cell cannot discriminate and says nothing
    #   VP, 7 a round  47/120 at zero, 50 at 400, kills and rounds
    #                  identical to two decimals -- noise
    #
    # So overkill is real, visible, and costs nothing measurable. The
    # reason is worth keeping: a dead cog stops attacking, and with 80
    # gags in a pouch the binding constraint is LAFF, not gags. Paying
    # a scarcer gag to remove a threat one round sooner is a trade the
    # flat `kill` bonus makes correctly, even when the arithmetic looks
    # wasteful to a human watching it.
    #
    # THE FIRST SWEEP WAS INVALID and the correction is the useful part.
    # It ran 0-400, and the term's natural scale is ~0.06 against a
    # `kill` bonus of 120 -- so no weight in that range could change a
    # single decision, and "no effect" measured nothing at all.
    #
    # It also cannot work alone. `climb` offers each seat the policy's
    # top `width`=3 proposals, and on the board that started this the
    # policy's top three were all Birthday Cake. The scorer can only
    # rank what it is given, so no weight reaches the cheaper gag; at
    # 10000 the pick jumps straight to PASS, the only non-Cake option
    # on the list. The pair had to be swept as a pair, which is the
    # same trap `prevent` set: two things wrong at once, and reading
    # either alone gives the wrong answer about the other.
    #
    # Swept properly, width 12 with waste 2000 reaches the cheap kill
    # on the reported board. On the selection seeds it looked like a VP
    # gain: 72/150 -> 85/150, p=0.092, while costing buildings
    # 122 -> 114. ON 400 HELD-OUT SEEDS IT DID NOT CONFIRM -- VP
    # 186/400 -> 195/400 at p=0.448, buildings 313 -> 302 at p=0.266.
    #
    # So the overkill is real, visible, and still not worth fixing:
    # a dead cog stops attacking, and paying a scarcer gag to remove a
    # threat a round sooner is a trade the flat `kill` bonus makes
    # correctly. Charging for waste pushes the scorer onto gags that
    # do not quite kill, and buildings then use MORE gags (14.1 ->
    # 15.0), not fewer, because the cog survives to be hit again.
    #
    # Both stay as they are: `width` at 3, this at zero.
    #
    # It exists because `landed` is HP-capped, so overkill is neither
    # credited nor charged: killing a 72hp cog with a 165-damage Cake
    # and killing it with a 120-damage Storm Cloud score IDENTICALLY,
    # and the tie breaks arbitrarily. `price` cannot separate them
    # either, since it charges by gag level and carry limit rather than
    # by damage discarded.
    #
    # Uses `plan_waste`, the same measure `objective.waste_penalty`
    # already scales -- weight x wasted_fraction x scarcity -- so a gag
    # that is the ONLY thing that kills pays almost nothing while the
    # same gag into a nearly-dead cog pays nearly in full.
    "waste": 0.0,
    "risk": 0.0,
    # Rounds of incoming the party's laff covers, capped. The only term
    # that reads laff LEVEL rather than a delta.
    #
    # IT DOES NOTHING FOR GAG CHOICE AND EVERYTHING FOR UNITES, which
    # is what `survival_rounds` predicts and what the sweep shows.
    # Solo VP, 80 runs a cell:
    #
    #   weight   unites   8 cogs   12 cogs   20 cogs   unites/run @20
    #        0      off    80.0%     23.8%      0.0%             0.0
    #     1600      off    77.5%     21.2%      0.0%             0.0
    #        0       on    83.8%     18.8%      0.0%             0.3
    #      200       on    88.8%     43.8%      0.0%             1.3
    #      800       on    96.2%     78.8%      0.0%             3.3
    #     1600       on    96.2%     81.2%      0.0%             5.0
    #
    # With unites OFF the term is flat to slightly negative at every
    # weight -- laff level cannot move a choice that does not change
    # laff. With them ON it is worth sixty points at 12 cogs, and every
    # one of those points is a unite being spent: 5.0 a run at the top.
    #
    # SO THIS IS A PREFERENCE, NOT A TUNING. The owner holds unites as
    # an absolute last resort because spending them freely "trivializes
    # a lot of stuff", and a weight that wins by spending five a fight
    # is buying wins with a currency farmed from whole CFO runs. Left
    # at 0.0 for the owner to set against how dearly they hold them.
    #
    # AND IT DOES NOT REACH THE REAL FIGHT. A 20-cog solo VP stays at
    # 0.0% at every weight and every unite budget tried, though it
    # survives 16.1 rounds against 30.2. The wall is somewhere else.
    # 400, swept. See docs/scoring.md. Two seed blocks of 200 runs a
    # cell: solo buildings are BIT-IDENTICAL at every weight from 0 to
    # 800 (26.0% and 27.0%, +0/-0), because with `incoming` pinned this
    # term is constant across the whole action menu and cannot reorder
    # it. Solo VP at 12 cogs with unites goes 35.0% -> 95.0% and
    # 31.5% -> 92.5%; with a bounded book of SOS cards, 27.0% -> 52.5%
    # and 24.5% -> 49.0%. The unite curve plateaus from 200, SOS climbs
    # to about 600 because `SOS_PRICE` is double `UNITE_PRICE`; 400 sits
    # mid-plateau for one and near peak for the other.
    #
    # Inert until `OFFER_UNITES` or `OFFER_SOS` is turned on: with
    # neither, nothing can change a toon's laff mid-plan, so this
    # contributes the same constant to every candidate.
    "survive": 400.0,      # CHARGED, per standing toon a round could sink
    "price": 1.0,       # gags spent
}


# `kill_threat` and `risk` STAY AT ZERO, and `risk` has now been
# refuted twice -- but only the second refutation is worth anything, and
# the difference between them is the useful part of this comment.
#
# THE FIRST REFUTATION WAS MEASURING NOTHING. A (1+lambda) ES on
# 2026-08-17 ran 120 generations with both terms available and returned
# `kill_threat` 0.044 and `risk` 0.592, against a landed-damage term in
# the tens. Read as "the optimiser was handed the new directions and
# declined them". It could not have done anything else: `toons_at_risk`
# was returning 0.0 on every position in existence -- 0 of 2000 sampled
# facility starts -- because it divided an already-probability-weighted
# expectation by the party size and asked whether a toon could survive
# their share of the average. Sweeping the weight over 0, 2, 5 and 10
# changed not one decision in 900 paired games. No weight moves a
# constant. See `toons_at_risk` for the fix.
#
# THE SECOND ONE IS REAL, and it is also a lesson in how these numbers
# lie. With the feature fixed and non-zero in 39.4% of positions, a
# paired sweep over 900 positions looked convincing: monotone in the
# weight, +0.6/+0.8/+1.0% at 5/10/20, all three sets agreeing in sign,
# p = 0.012 at 20, and a PLATEAU across 10-40 rather than a spike at one
# lucky value. Every shape-based argument for believing it was present.
#
# It did not replicate. Confirming risk=20 on 1600 positions with seeds
# it had not been chosen on: +0.1%, 21 discordant games split near
# evenly, p = 1.000, mixed signs. The +1.0% was the maximum of six
# values measured on one sample, which is a selection and not a
# measurement, and the plateau was not the protection it appeared to be.
#
# So: 0.0, on evidence this time. What would change the answer is a
# distribution where the term bites -- it is the low-laff, one-group-
# attack-from-sad positions that carry it, and sampled facility starts
# are mostly not those. A 4-toon 22-laff position against level 12s
# ranks the correct defensive move 6th of 130 at risk=0 and 2nd at
# risk=20. That is a real improvement on a real position and it is worth
# nothing here, because tuning a weight until one hand-built case comes
# out right is how the first refutation happened.
#
# On 240 buildings used for neither fitting nor validation:
#
#     baseline (hand-tuned)           63.7%
#     fitted, all seven weights       63.7%
#     baseline + the two features     63.7%
#
# Identical, which says more than "no gain": these weights barely change
# WHICH PLAN gets picked. `kill` at 120 or at 86, `price` at 1.0 or 0.38,
# and the same buildings finish.
#
# Left in, behind zero weights that skip their computation, because the
# next person to look at these equations will notice the same two gaps.
#
# A third gap -- charging for the threat LEFT standing -- is deliberately
# not a term. `prevented` is already `incoming(before) - incoming(after)`
# and `before` is fixed while ranking one position's plans, so a
# residual-threat term would be the same ordering with the sign flipped.
GREEDY_W = {
    "heal": 2.0,
    "kill": 60.0,
    "prevent": 2.0,
    "price": 10.0,
    "waste": 0.25,
}


# How many of a toon's candidate actions get a simulated `_greedy_score`
# during a rollout. The rest are ranked by arithmetic alone -- see
# `greedy_plan`.
#
# Swept on the battered position. Rollout quality came out at 74.88 for
# EVERY value from 1 to 6, and search values stayed inside their own
# seed-to-seed spread, while the cost fell steadily:
#
#     shortlist   rollout quality   search    time
#             1             74.88   +91.84   3.51s
#             2             74.88   +91.49   4.12s
#             4             74.88   +91.53   5.25s
#             6             74.88   +91.32   6.30s
#
# Measured separately, `_cheap_score`'s pick agrees with the
# simulation's on 288 of 328 decisions (88%). So the simulation is
# mostly confirming the arithmetic, and 2 keeps a second opinion for the
# 12% at a fifth off the cost.
#
# NOT dropped to 1, and checking that on more positions is what settled
# it. The flat 74.88 above was an artefact of a position where the
# shortlist never changes the plan at all. Across four positions, with
# how often the plan differs between k=1 and k=4:
#
#     position           plans differ    k=1     k=2     k=4     k=6
#     maxed vs 4 big            0/6    87.17   87.17   87.17   87.17
#     midgame vs 3              9/14   75.35   74.49   74.49   74.49
#     weak vs 2 (long)          0/17   88.35   88.35   88.35   88.35
#     mixed cog hp              5/5    91.88   93.42   93.42   93.42
#
# k >= 2 is identical everywhere, so nothing above 2 is worth paying
# for. But k=1 loses 1.54 on the mixed-hp position, where the plan
# differs every single time -- uneven cog health is exactly where
# choosing between two similar-damage options matters, and where the
# arithmetic that cannot see knockback or trap triggers goes wrong.
#
# So the simulation earns its keep, on the positions that discriminate,
# and one position showing it flat was not evidence that it does not.
# The sweep above is GREEDY_SHORTLIST's, not this constant's; the two
# comment blocks were adjacent and ran together. See `GREEDY_SHORTLIST`.
#
# What a restored point of laff is worth against a point of cog damage,
# for a scorer that has no `objective` to read. Mirrors
# `objective.laff_weight` in INTENT, which is what `round_reward`
# charges for laff LOST, so the shortlist and the reward agree on what
# laff is for -- not in magnitude: `laff_weight` is 1.0 in every preset
# but SURVIVE (3.0) and GLASS_CANNON (0.25).
#
# READ BY ONE SCORER, `_cheap_score`, and there for two different
# things: the Toon-Up branch uses it as a heal weight, and the Trap
# branch uses it as a PREVENTION weight (`forgone = HEAL_VALUE * threat
# * rounds`). The other two scorers price laff restored through
# `QUICK_W["heal"]` and `GREEDY_W["heal"]`, which both happen to equal
# this. Three constants, one number, no link between them --
# docs/scoring.md.
# Swept over 45 identical buildings, AFTER the reinforcement-slot fix:
#
#     HEAL_VALUE   floors   finished
#     0.0 (blind)    2.44      62.2%
#     0.5            2.51      64.4%
#     1.0            2.62      66.7%
#     2.0            2.67      68.9%
#     3.0            2.58      64.4%
#
# An earlier sweep of the same values came back perfectly flat --
# 15.6% finished at every setting, the same seven buildings each time --
# because 42% of runs were then locked in a pass loop by the
# reinforcement bug, which no healing policy could affect. That flatness
# was the clue that something else was wrong, not evidence that healing
# does not matter.
#
# Differences of a few points across 45 seeds are noise; what the sweep
# supports is that healing is worth something and that 3.0 overcorrects.
HEAL_VALUE = 2.0


# How much of a trap's damage to credit before it has been sprung. Less
# than one because the payoff is conditional on a lure landing later and
# on the cog surviving until then, but nowhere near the flat 20 it used
# to score.
TRAP_DISCOUNT = 0.6


# How many extra candidates `greedy_plan` simulates purely to give
# unrepresented tracks a hearing. Costs simulation in the rollout hot
# path; buys the guarantee that no track is cut by arithmetic alone.
TRACK_PROBES = 3


# How many of a toon's candidate actions `greedy_plan` simulates. The
# sweep that settled it at 2 -- and the four-position table showing k=1
# losing 1.54 on the mixed-hp board -- is the comment block above
# `HEAL_VALUE`, where it ran together with that constant's own note.
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


# Charge a plan for waking cogs it had asleep. ON, measured.
#
# The fourth correction to `prevented` and the first to survive. The
# three before it were arithmetic refinements to the CREDIT -- how many
# rounds a lure buys, how to average them -- and each lost 2-3 points.
# This adds a term that was absent: nothing charged for quiet SPENT, so
# a plan could hand four sleeping cogs their attacks back for free.
#
# Paired, 200 sides a cell:
#
#     cell             off      on
#     buildings      64.5%   67.0%
#     buildings      68.5%   71.5%   p=0.031
#     CEO 0          69.5%   73.0%
#     CEO 2          54.5%   61.5%   p=0.038
#     CEO 4          31.0%   36.5%
#     VP             98.5%   98.5%   at the ceiling
#     pooled         76 up / 33 down, p<0.0001
#
# The weight did NOT need rescaling, which was the obvious guess and was
# wrong: sweeping `prevent` with this on, 9.0 beats 4, 2, 1 and 0.5
# monotonically and significantly.
WAKE_COSTS_PREVENTED = True


# How far ahead a lure's quiet is credited, per cog
# rather than as a mean over them.
#
# THE REASONING IS IN `party_search.prevented`, not here. These four
# flags are read inside that one function and its docstring argues
# each of them with its measurement; splitting the prose from the
# code that acts on it would help nobody. Follow the pointer.
PER_COG_REACH = True


# Whether an already-lured cog buys
# anything more. It does not: it was paid for when the lure landed.
#
# THE REASONING IS IN `party_search.prevented`, not here. These four
# flags are read inside that one function and its docstring argues
# each of them with its measurement; splitting the prose from the
# code that acts on it would help nobody. Follow the pointer.
LURE_IS_SPENT_ON_SLEEPERS = True


# Whether killing a sleeping cog counts
# as silencing it. It does not -- it was already quiet.
#
# THE REASONING IS IN `party_search.prevented`, not here. These four
# flags are read inside that one function and its docstring argues
# each of them with its measurement; splitting the prose from the
# code that acts on it would help nobody. Follow the pointer.
LURED_KILL_SILENCES_NOTHING = True


# The ceiling on `survival_rounds`, in rounds. Argued in `party_search.survival_rounds`,
# which is the only reader.
SURVIVAL_CAP = 4.0


# What one pink slip costs the scorers, PER COG STILL TO COME. A slip is finite and nothing restocks it, so it is
# the same kind of resource as a gag and belongs in the same term --
# `_cheap_score` used to say outright that "scarcity across a whole
# fight belongs to the objective's price, which charges nothing for a
# fire", and left it there.
#
# Measured, not guessed: with slips free the party spent all ten on the
# waiter battle and arrived at the Big Cheese holding 0.3 of 10, which
# is why the CEO sat at 0% for ten banquet leftovers. Battle two alone
# from full resources clears 93% there, so the fight was never the
# problem -- arriving disarmed was.
#
# PROPORTIONAL TO WHAT IS LEFT, with no constant term, and that shape is
# the point rather than a detail. A flat price was tried first and it
# helped at five leftovers (38.0% -> 49.5%, p=0.008) while HURTING at
# zero (88.5% -> 82.0%, p=0.021), because it also suppressed slips in
# the last battle -- and a slip carried out of the fight unspent is
# worth exactly nothing. Scaling by `cogs_remaining` makes the price
# fall to zero once there is nothing left to save for, so the rule
# reads: hoard while cogs are still coming, spend freely at the end.
#
# 20 is directionally supported rather than proven, and the distinction
# is worth keeping: across 200 CEO sides it is neutral at zero leftovers
# (88.5% -> 88.0%, p=0.50) and positive but not significant at five
# (38.0% -> 41.5%, p=0.22). What it clearly does is unstick ten
# leftovers from exactly 0%, at every non-zero price tried. A 40-side
# sweep said +7.5 there and 200 sides said +3.5; trust the larger one.
FIRE_PRICE = 20.0


# Charged for a slip WHATEVER the horizon, because `cogs_remaining` is 0
# on every board the panel builds -- it has no way to know what a VP or
# a building still holds -- and `FIRE_PRICE * cogs_remaining` is then
# zero, making a slip free. That is how a pink slip got spent on a 6hp
# level 1 Cold Caller in live play.
#
# Swept with `QUICK_W["waste"]`, because the two pull opposite ways:
# waste charges gags for overkill and skips fires by design, so raising
# it alone sends the same board back to firing. 150 runs a cell, then
# 250 on held-out seeds:
#
#     floor  waste   vp+5slips   slips spent   vp+0   buildings
#         0      0       85.6%          4.5   55.2%      23.6%
#        20      0       86.4%          3.7   55.2%      23.6%
#        60     30       81.2%          3.0   55.2%      24.0%
#
# 20 is free: +9/-7 (p=0.80) on the VP and eight tenths of a slip
# cheaper, and it is enough to stop the pick that prompted this -- a
# slip spent on a level 1 Cold Caller with 6 hp.
#
# Waste at 30 looked worth it on the selection set, +2.6 on buildings
# for -2 on the VP. Held out the building gain vanished (23.6 -> 24.0)
# and the VP cost grew to -4.4, +12/-23, p=0.09. So it stays at zero,
# and GAG overkill remains unfixed -- see `QUICK_W["waste"]`.
# RE-SWEPT once unites and SOS existed, and 20 no longer holds up. That
# sweep ran when a solo VP read about 86%; with consumables it reads 94%,
# and the headroom that appeared was enough to raise the floor for free.
# 150 runs a cell, then 200 on held-out seeds, everything available in
# every cell -- 5 slips, 5 unites, all 29 cards:
#
#     floor   d3 slips   d5 slips   d9 win    vp win   vp slips
#        20   .63 /.58  1.16 /1.12  63 / 66%  95 / 95%  4.89 /4.88
#        60   .00 /.00   .12 / .15  65 / 70%  94 / 94%  4.69 /4.66
#       120   .00 /.00   .03 / .05  65 / 67%  95 / 94%  3.96 /4.03
#       200   .00        .03        53%       85%       2.93
#
# 120 zeroes the slip spent on easy content -- the owner's rule is that
# standard play should not need one -- and spends nearly a whole slip
# LESS per VP at the same win rate, which is the point of keeping them.
# 200 is too far: d9 falls to 53% and the VP to 85%.
#
# d9 is within noise between 60 and 120 (65/70 against 65/67 across the
# two blocks); the economy is what separates them.
FIRE_FLOOR = 120.0


# A branch this unlikely is not worth a probe. The pruned mass is
# renormalised away, so this trades a little accuracy in the tail for
# skipping leaves that cannot move a ranking.
MIN_LEAF_PROB = 1e-3


# Rounds a rollout will play before giving up and calling the position
# unresolved. A real battle ends well inside this; the cap only stops a
# pathological position (mutual inability to finish) spinning forever.
# ---------------------------------------------------------------------
# The greedy scorer and rollouts
# ---------------------------------------------------------------------
#
# A THIRD scorer, ranking single actions by arithmetic alone. It
# does not share `QUICK_W`; `_gag_units` is the one price both
# agree on.

ROLLOUT_ROUNDS = 12
