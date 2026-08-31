"""Searching a battle with more than one toon in it.

Structurally the same expectimax the solo solver uses -- MAX over what
you choose, CHANCE over what you do not -- with the party question
answered at the MAX node rather than bolted on:

    Mode.COORDINATED   MAX ranges over the whole team's joint action
    Mode.PICKUP        MAX ranges over YOUR action; the teammates are
                       part of the chance node, sampled from a
                       TeammateModel

That difference is the whole design. Searching teammates as choices you
do not have produces advice that assumes an agreement nobody made;
treating a coordinated team as a distribution throws away the reason
they coordinated. See `solver/party.py`.

WHY THIS SAMPLES INSTEAD OF ENUMERATING
---------------------------------------
The solo search enumerates its chance nodes exactly, which is what makes
`solve()` exact. A party round cannot be: the outcome space is the
accuracy rolls (one per track per target), times each cog's choice of
attack, times its choice of *whom* to hit, times the teammates' actions
in pickup mode. Enumerating that is hopeless, so each chance node is
estimated from `samples` playouts of the round.

The consequence is worth stating plainly: **this is an estimate, and
values from it are not comparable with `expectimax.solve`'s**. Nothing
here is exact and nothing should be labelled as though it were.

WHERE THE WEIGHTS LIVE
----------------------
Three tables price overlapping concepts on three scales: `QUICK_W` and
`GREEDY_W` below, and `search/objective.Objective`, which neither fast
scorer can read. `docs/scoring.md` is the inventory -- every term, which
system defines it, which code paths read it, and where two of them price
the same thing differently. Consult it before adding or moving a term;
the audit exists because a weight was added by hand once and fitted
against another term that was itself wrong.

COST, AND WHY THE DEFAULTS ARE SMALL
------------------------------------
A coordinated plan is a multiset of actions over four toons, so the
branching is brutal even after the reductions in `plans()`. Depth 1 with
a modest `samples` is affordable; depth 2 multiplies by the branching
again. The defaults are set where a real position answers in seconds,
not where the search is strongest.
"""
from __future__ import annotations

import itertools
import random
from typing import Dict, List, Optional, Sequence, Tuple

from .. import party as party_mod
from .. import simulator
from ..party import Mode, TeammateModel
from ..data import gags as gags_mod
from ..state import Action, BattleState, Track
from . import expectimax
from . import objective as objective_mod
from . import policy

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

# Whether the trained policy ranks the candidate pool. OFF, and the
# measurement is why.
#
# The policy is a better RANKER than the arithmetic -- regret@6 of 3.22
# against 9.93 on 375 held-out positions, with random at 12.09. But
# wired in here it made the search WORSE: over four seeds on a real
# battered-party position, mean +88.39 against +89.72 with it off, and
# a 50% slower shortlist build.
#
# The reason is a wiring mistake rather than a bad model. The policy
# currently only decides which plans enter the pool that `_quick_score`
# then ranks, and the final `max_plans` cut is made on `_quick_score`
# alone -- so the policy's ordering is computed and then discarded. All
# the union achieves at that point is to displace plans the arithmetic
# would have picked with plans it rates lower, which is exactly the
# regression observed.
#
# The wiring bug IS fixed -- the policy score now orders plans within a
# stratum as well as choosing bucket membership, so it reaches the final
# cut. It still loses, at every width tried:
#
#     width   policy OFF   policy ON
#         8      +88.06      +87.29
#        16      +89.34      +87.29
#        30      +89.34      +87.29
#        60      +89.72      +88.29
#
# So the model, not the plumbing. The cause is in the LABELS. The
# teacher estimated each plan from 16 samples of a per-round spread of
# about 31, giving a standard error near 7.8 -- while the median value
# gap between the best plan and the sixth is 3.54. The labels are
# noisier than the distinctions they are meant to teach, so the
# teacher's ordering among good plans is mostly noise and the policy
# learned it faithfully.
#
# That also explains why the offline metric looked so good. regret@6
# scored the policy against those same noisy values: when the top twenty
# plans sit within noise of each other, almost any six of them score a
# low regret. It measured "avoids obviously bad plans", which the policy
# genuinely does better than `_quick_score`, and could not see "picks
# the actually best plan", which is what the search needs.
#
# The fix is more samples per plan in the teacher, not a bigger network
# -- 16 to 128 or more, at eight times the generation cost. Off until
# then.
USE_POLICY = False

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
    "survive": 0.0,        # CHARGED, per standing toon a round could sink
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


def candidates(state: BattleState, toon_index: int,
               per_track: int = PER_TRACK) -> List[Action]:
    """A few actions per track for one toon, ranked within each track.

    Per *track* rather than overall, so no track is squeezed out by
    another being generally stronger -- Sound gets the same slots as
    Drop. Ranking inside a track uses `SensiblePrior`, which is a guess
    about play and only decides which levels of a track make the
    shortlist, never which track wins.

    Letting `greedy_plan` supply `_cheap_score` as the within-track
    ranking instead was tried and reverted. It saved rotating the state
    and running the prior -- 9.6s to 8.8s on the profile -- and then
    bought NOTHING on the wall clock of either study position, while
    dropping the battered position's depth-1 values by about 0.4. The
    prior orders the levels of a track better than damage arithmetic
    does, which is exactly the job it is still here for.
    """
    rotated = party_mod._as_actor(state, toon_index)
    prior = party_mod.SensiblePrior()
    order = {(a.track, a.level, a.target_index): i
             for i, a in enumerate(prior._candidates(rotated, 0))}
    key = lambda a: order.get((a.track, a.level, a.target_index), 10 ** 6)

    by_track: Dict[Track, List[Action]] = {}
    for action in simulator.legal_actions(rotated):
        if action.is_pass:
            # DROPPED, and it is not the omission it looks like. A party
            # can already decline: `plans` leaves a toon's slot None
            # when the joint plan gives them nothing, and measured over
            # 20 buildings that is 19.2% of all plan slots against 80.8%
            # throwing a gag.
            #
            # Adding the pass here as well was tried and is inert -- an
            # explicit pass was chosen 0 times in 543 slots, because it
            # scores 0.0 in `_cheap_score` and a None slot achieves the
            # same thing without competing for one. It also needed three
            # separate crash fixes to survive the price loops, so the
            # redundant encoding is a liability rather than a spare
            # wheel.
            #
            # The overkill this was meant to cure therefore has another
            # cause: at 10 wasted damage a round the party is choosing
            # to double up, not being forced to.
            continue
        by_track.setdefault(action.track, []).append(action)

    out: List[Action] = []
    for actions in by_track.values():
        actions.sort(key=key)
        out.extend(actions[:per_track])
    return out


def plans(state: BattleState, mode: Mode = Mode.PICKUP,
          per_track: int = PER_TRACK,
          max_plans: int = MAX_PLANS) -> List[Sequence[Optional[Action]]]:
    """The team plans worth considering from this position.

    In pickup mode a "plan" is just your own action with the teammates
    left as None -- they are sampled during the rollout, not chosen.

    In coordinated mode it is every toon's action. Two reductions keep
    that enumerable, and both are approximations rather than facts:

    * Plans are taken as multisets when the toons are interchangeable,
      because {Sound, Sound, Throw} is one plan and not six. Toons with
      different pouches are not interchangeable, so the multiset is
      then only an approximation and the assignment is checked for
      legality when it is applied.
    * `max_plans` truncates what is left.
    """
    if mode is Mode.PICKUP:
        blanks = [None] * (len(state.toons) - 1)
        return [[action] + blanks for action in candidates(state, 0,
                                                           per_track)]

    # HOLDING THIS ROUND is a real option for a party and has to be
    # offered, because the alternative is forcing a toon with nothing
    # useful to do to waste a gag. It did exactly that: asked a
    # four-toon position where three actions already won the fight, the
    # search had the fourth toon throw Toon-Up at a teammate on FULL
    # LAFF, because a cheap wasted heal was the least bad thing it was
    # allowed to say.
    #
    # It is spelt as the PASS action, not as a bare `None`. Those were
    # two names for one thing -- the comment here used to argue they
    # differed because `legal_actions` only offered a pass while a cog
    # was lured, and that narrowness is gone. Keeping both left `None`
    # meaning "holds" in coordinated mode and "will be sampled" in
    # pickup mode, which is one word for two ideas in a module that
    # switches between them.
    #
    # `None` now means only the pickup thing.
    #
    # This handles the gag that achieves NOTHING: `round_reward` already
    # charges `gag_price` for what is spent, so once holding is on the
    # menu a useless gag is strictly worse than it, with no extra
    # penalty needed.
    #
    # It does NOT handle the gag that achieves something and throws most
    # of it away -- a Railroad into a five-hit-point cog kills it and
    # discards the rest, and holding is plainly worse than that. That is
    # a separate charge; see `waste_penalty`.
    hold = Action(track=None, level=0, target_index=None)
    per_toon = [candidates(state, i, per_track) + [hold]
                for i in range(len(state.toons))]
    if not any(any(not a.is_pass for a in row) for row in per_toon):
        return []

    identical = all(t.gag_counts == state.toons[0].gag_counts
                    for t in state.toons)
    if identical:
        combos = itertools.combinations_with_replacement(
            per_toon[0], len(state.toons))
    else:
        combos = itertools.product(*per_toon)

    # Rank before truncating. Taking a prefix of the enumeration is not
    # a filter, it is an alphabetical accident: `combinations_with_
    # replacement` starts with the first candidate repeated, so the
    # first 60 plans were every arrangement of Trap on one cog and the
    # search never saw a Sound plan at all. It then reported a
    # coordinated value BELOW the pickup value, which cannot happen when
    # coordinated may choose strictly more -- the tell that the plan
    # list, not the search, was broken.
    #
    # Ranking is one deterministic all-hit round: damage that lands,
    # minus what it costs. Crude, and only deciding which plans are
    # worth sampling properly.
    # Stratify the slots by which tracks the plan uses, then fill from
    # the best of each stratum, rather than taking a global top-N.
    #
    # This is the same lesson as PER_TRACK, learned again one level up.
    # `_quick_score` plays one round with everything HITTING, so a
    # Trap+Lure plan is scored as though the lure never misses and is
    # paid nothing for the risk. On a maxed four-toon position it ranked
    # every such plan at 1081-1089 and the known-best Sound line at 988,
    # and with a global cut the 60 surviving plans contained 59 Lure+Trap
    # combos and NOT ONE all-Sound plan. The best line was not outranked,
    # it was deleted before it could be sampled.
    #
    # Stratifying does not make `_quick_score` any less optimistic -- it
    # just stops one track family monopolising the shortlist, so the
    # real sampled evaluation gets to see each family's best offering
    # and decide between them on merit.
    # Collect first, score second, and cap how many combos in each
    # stratum are worth a simulated `_quick_score`. Scoring every
    # playable combo meant ~50k round simulations on a real position,
    # which was 28% of the whole search -- and all but a handful of
    # those scores were thrown away by the truncation below anyway.
    #
    # The cap is per stratum, not global, for the same reason the
    # truncation is: a global budget would be spent entirely on whichever
    # family the enumeration happens to reach first. Within a stratum the
    # order is the prior-ranked candidate order, so the first entries are
    # the plausible ones rather than an arbitrary slice.
    # Keep the arithmetically best SCORE_BUDGET per stratum, NOT the
    # first ones enumerated.
    #
    # Taking the first N was a lexicographic prefix, which is the same
    # bug as the one `max_plans` had, reintroduced one level down while
    # optimising -- and it deleted the same line. On the maxed position
    # `combinations_with_replacement` reaches every combo built from
    # Sound 7 before it reaches [Foghorn, Foghorn, Aoogah, Aoogah], so
    # the Sound stratum's budget was spent entirely on level 7 plans and
    # the known-best line was never scored. It was not outranked; it was
    # not a candidate, and no objective term could reach it -- a
    # `rare_gag_premium` that correctly took the level 7 plan from +92.70
    # to +72.70 changed the chosen plan not at all.
    #
    # `_cheap_score` is pure arithmetic, so ranking every combo with it
    # costs no simulations, and only the survivors get a simulated
    # `_quick_score`.
    playable = []
    for combo in combos:
        if _playable(state, combo):
            playable.append(list(combo))

    # Rank with the trained policy when it is available, and with the
    # arithmetic otherwise. Measured on 375 held-out positions by
    # regret@6 -- the value given up by searching only the top six --
    # the policy scores 3.22 against `_quick_score`'s 9.93, with random
    # at 12.09. The hand-written ranking is barely better than random at
    # this job, which is also why four of this project's five
    # silent-deletion bugs lived here.
    #
    # The stratification below is NOT bypassed when the policy loads. A
    # learned ranker is still a reduction and can still delete the right
    # answer, more confidently and less legibly than a heuristic; the
    # per-family floor is what makes a bad policy degrade to today's
    # behaviour rather than to silence.
    scores = None
    if USE_POLICY and policy.available():
        from . import features as features_mod

        try:
            scores = policy.rank(state, playable,
                                 features_mod.extract(state))
        except (NotImplementedError, ValueError):
            scores = None

    # BOTH rankings, interleaved -- not the policy instead of the
    # arithmetic.
    #
    # Ranking by the policy alone was tried and it deleted the right
    # answer on the very first position checked: on the maxed board it
    # dropped 2 Foghorn + 2 Aoogah, the known-best line, off the
    # shortlist entirely in favour of Sound plans with holds. Per-family
    # stratification did not save it, because the loss happened WITHIN
    # the Sound family.
    #
    # So a plan survives if EITHER ranker rates it highly. The policy
    # wins on average (regret@6 3.22 against 9.93) and the arithmetic
    # covers what the policy has not learned; a plan has to be missed by
    # both to be lost. That costs a little shortlist room and buys the
    # property this project has repeatedly wished it had -- no single
    # reduction can silently delete a correct plan.
    cheap: Dict[tuple, List] = {}
    arith = [sum(_cheap_score(state, i, a)
                 for i, a in enumerate(combo) if a is not None)
             for combo in playable]
    for index, combo in enumerate(playable):
        # A hold has no track, so it contributes nothing to the
        # signature -- two plans differing only in who holds belong in
        # the same stratum.
        signature = tuple(sorted(
            {a.track for a in combo if a is not None and not a.is_pass},
            key=lambda t: t.name))
        cheap.setdefault(signature, []).append(
            (arith[index], scores[index] if scores is not None else None,
             combo))

    buckets: Dict[tuple, List] = {}
    for signature, rows in cheap.items():
        by_arith = sorted(rows, key=lambda row: -row[0])
        if rows[0][1] is None:
            buckets[signature] = [r[2] for r in by_arith[:SCORE_BUDGET]]
            continue

        # UNION of each ranker's own top-N, not an interleave of the
        # two. Interleaving was the obvious version and it is wrong: it
        # halves each ranker's depth, so the arithmetic lost the slot it
        # had been giving 2 Foghorn + 2 Aoogah and the plan vanished
        # again -- the same deletion, now caused by the fix for it.
        #
        # A union costs a larger bucket and guarantees what the whole
        # arrangement is for: a plan has to be missed by BOTH rankers to
        # be lost.
        by_policy = sorted(rows, key=lambda row: -row[1])
        picked, seen = [], set()
        for row in list(by_policy[:SCORE_BUDGET]) + list(
                by_arith[:SCORE_BUDGET]):
            if id(row[2]) not in seen:
                seen.add(id(row[2]))
                picked.append(row[2])
        buckets[signature] = picked

    # Order WITHIN a stratum by both rankers, not by `_quick_score`
    # alone.
    #
    # This is where the policy was being thrown away. It chose which
    # plans entered the bucket and then this line re-sorted the bucket on
    # `_quick_score`, so the learned ordering never reached the final
    # `max_plans` cut. All the policy achieved was to displace plans the
    # arithmetic would have kept -- which is why turning it on made the
    # search worse (mean +88.39 against +89.72) despite ranking three
    # times better in isolation.
    #
    # Alternating the two orderings gives each ranker an equal share of
    # the final list, and keeps the property the union was for: a plan
    # has to be missed by both to be lost.
    policy_of = {}
    if scores is not None:
        for index, combo in enumerate(playable):
            policy_of[id(combo)] = scores[index]

    strata: Dict[tuple, List] = {}
    for signature, bucket in buckets.items():
        rows = [(_quick_score(state, combo), combo) for combo in bucket]
        by_quick = sorted(rows, key=lambda row: -row[0])
        if not policy_of:
            strata[signature] = by_quick
            continue
        by_pol = sorted(rows, key=lambda row: -policy_of.get(id(row[1]), 0.0))
        merged, seen = [], set()
        for a, b in zip(by_pol, by_quick):
            for row in (a, b):
                if id(row[1]) not in seen:
                    seen.add(id(row[1]))
                    merged.append(row)
        strata[signature] = merged or by_quick

    out: List[Sequence[Optional[Action]]] = []
    order = sorted(strata, key=lambda sig: -strata[sig][0][0])
    depth_in_stratum = 0
    while len(out) < max_plans and order:
        progressed = False
        for signature in order:
            rows = strata[signature]
            if depth_in_stratum < len(rows):
                out.append(rows[depth_in_stratum][1])
                progressed = True
                if len(out) >= max_plans:
                    break
        if not progressed:
            break
        depth_in_stratum += 1

    # HOLD-VARIANTS WERE TRIED HERE AND DO NOT PAY, which is worth
    # recording because the overkill looks like a bug and is not.
    #
    # 53% of planned rounds contain overkill. Most of it is gag
    # granularity -- a group Sound that overkills a weak cog while being
    # needed for the strong ones has no better alternative -- but 17% is
    # avoidable: a hold-variant of the chosen plan scores strictly
    # better on `_quick_score`, and the stratified cut above had removed
    # it before anything could evaluate it.
    #
    # Generating those variants after the cut removed exactly that 17%,
    # waste falling from 10.1 a round to 8.4. Outcomes got WORSE:
    # floors cleared 2.07 to 1.83 over 30 identical buildings. Holding
    # buys the cogs another round, and a round of four cogs attacking
    # costs more than the gag it saves.
    #
    # So the search is right to double up, and the waste penalty should
    # not be strengthened either. Left out rather than left in.
    return out


def remaining_hp(cog) -> int:
    """Health this cog still has to lose, BOTH layers of a Version 2.0.

    A v2.0 carries its hp again behind the one on show, so a suited cog
    at 90 has 180 left to give. Every scorer that measures progress as a
    drop in hp needs this instead of `cog.hp`, because breaking a suit
    takes hp from 90 to... 90: the Skelecog steps out at full health and
    the naive difference reads ZERO.

    That is not "undervalued", it is invisible. A gag that stripped a 90
    hp suit scored nothing at all and every 1-damage poke outranked it,
    which is precisely backwards on the one fight built out of 2.0s.
    """
    if cog.status.is_dead:
        return 0
    return cog.hp + (cog.max_hp if cog.status.suited else 0)


def _cog_threat(cog) -> float:
    """Expected damage one cog deals in a round, if it is awake."""
    from .. import outcomes as outcomes_mod

    return sum(p * dmg for p, _name, dmg, hit
               in outcomes_mod.cog_attack_outcomes(cog) if hit)


def expected_incoming(state: BattleState) -> float:
    """Laff the cogs are expected to take off the party next round.

    THIS IS HOW THE COG PHASE REACHES THE FAST SCORERS, and it does not
    involve simulating it. `outcomes.cog_attack_outcomes` is already
    cached on (department, type, level), so this is a sum over live
    cogs -- a flunky at level 2 threatens 1.3 a round, a Legal Eagle at
    9 threatens 11.6.

    It matters because every defensive effect was invisible by
    construction. `_quick_score` and `_greedy_score` simulate the TOON
    phase only, so a plan that lures three cogs looked exactly as safe
    as one that lured none, and Lure was compensated with a flat
    `25 x cogs lured` that has no relation to what those cogs were
    about to do. Healing had the same hole and Trap had it too; three
    hand-tuned constants standing in for one quantity nobody computed.

    A lured cog contributes nothing: it skips its attack.
    """
    total = 0.0
    for cog in state.active_cogs():
        if cog.status.lured:
            continue
        total += _cog_threat(cog)
    return total


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


PER_COG_REACH = True
"""Stagger the lure horizon per sleeper instead of one number for all.

`reach` gives every sleeper `asleep / standing` rounds of credit. You
do not reach them all at once: the first is woken next round and the
last after all of them. Ordered by remaining health, since that is the
order they get worked through -- finish the cheap ones, leave the
Mr. Hollywood asleep.

Measured below alongside `LURE_IS_SPENT_ON_SLEEPERS`.
"""


LURE_IS_SPENT_ON_SLEEPERS = True
"""Whether a lure's value is capped by when you would wake the cog.

True caps it at `reach`: quiet you are going to spend yourself is not
quiet you can bank. That reasoning describes a plan which works through
the sleepers.

THE OWNER SAYS THAT IS NOT THE PLAN A SOLO VP IS WON WITH, and they are
right about the game. You lure the field with a Presentation, LEAVE the
sleepers alone, and fight the cogs that walk in to replace the ones you
kill -- three cogs simply out of the fight for the whole duration.
Under that plan the lure delivers every round it promises and `reach`
prices it at about a quarter.

VALUING IT IN FULL STILL PLAYS WORSE. Solo VP, 200 runs a cell, five
slips, paired:

    cogs a round   capped    full     paired
               8    81.5%   67.0%   +13/-42  p<0.001
              12    20.0%   16.5%   +15/-22  p=0.32
              20     0.0%    0.0%   +0/-0

Fourteen points worse where there is signal. So the cap stays, and what
was refuted is this crude removal of it rather than the strategy.

WHY THEY DO NOT CONTRADICT. `reach = inf` values EVERY lure at its full
duration, including the cogs the plan is about to attack -- and it
lures with about half its actions at every size measured. The strategy
depends on a distinction this scorer cannot draw: which sleepers are
being left alone and which are next. A one-round scorer sees no such
intent, so "full duration" here means "always over-credit" rather than
"credit the ones you will not touch".

Drawing that distinction properly is the open problem. It wants the
plan's own targets -- a cog nobody in the plan attacks is left asleep,
one being hit is woken this round -- which is knowable from the plan
and is not what either setting does.
"""


LURED_KILL_SILENCES_NOTHING = True
"""Whether killing an already-lured cog credits `prevented` nothing.

It should, and the flag exists to measure it rather than to leave the
choice open. See the branch in `prevented`.
"""


def prevented(before: BattleState, after: BattleState) -> float:
    """Incoming damage a round removed, by luring or by killing.

    REMODELLED, because the rule underneath it changed. A landed attack
    wakes a lured cog -- see `mechanics.LURE_ENDS_ON_DAMAGE` -- so a Lure
    does not buy `lure_rounds_remaining` rounds of quiet. It buys quiet
    on the cogs the party does not get round to hitting, for as long as
    it does not get round to them.

    The old version multiplied the whole difference by one mean
    `lure_rounds_remaining`, which was defensible only while a lured cog
    stayed asleep through damage. It does not.

    WHY THE OLD REFUTATIONS DO NOT APPLY. This docstring used to record
    three corrections, all mechanically right and all losing 2-3 points,
    and concluded the term should stay wrong until somebody refit the
    evaluator as a whole. Every one of those was measured under the old
    lure rule, where the multiplier was roughly correct and a correction
    really was noise. That evidence is void. This change is made
    together with a retrain and a refit, which is the condition the old
    note set.

    THREE PARTS, EACH COUNTED FOR WHAT IT ACTUALLY BUYS:

      * A KILL removes a cog's threat permanently, and is counted once.
        `QUICK_W["kill"]` prices removal separately, so this is only the
        damage-per-round it silences.
      * A NEWLY LURED cog is quiet until somebody hits it or the lure
        runs out, whichever comes first. `reach` estimates the former:
        with `k` toons standing and `n` cogs asleep, the party works
        through them in about `n / k` rounds.
      * AN ALREADY-LURED cog buys nothing new. It was paid for when the
        lure landed, and paying again every round it stays asleep is how
        a plan that does nothing scores well.

    Per cog rather than a mean over them, which was the other standing
    [TODO]: a cog with one round left no longer drags down the
    multiplier for one just put to sleep for four.
    """
    standing = max(1, len(before.active_toons()))
    asleep = sum(1 for c in after.active_cogs() if c.status.lured)
    # How many rounds before the party gets round to any given sleeper.
    reach = max(1.0, asleep / float(standing))
    # PER-COG HORIZON. `reach` is one number for every sleeper, but you
    # do not reach them all at the same time: the first is woken next
    # round, the last after `asleep / standing` rounds. Staggering it
    # credits a four-cog lure for 1 + 2 + 3 + 4 rounds of quiet rather
    # than 4 + 4 + 4 + 4, which is both less generous in total and
    # better shaped -- the cog you are about to kill was never going to
    # stay asleep, and the one at the back was.
    #
    # Ordered by remaining health, because that is the order a player
    # works through them: finish the cheap ones, leave the Mr.
    # Hollywood asleep. `PER_COG_REACH` turns it off.
    order = {}
    if PER_COG_REACH:
        sleepers = sorted(
            (c for c in after.active_cogs() if c.status.lured),
            key=lambda c: c.hp + (c.max_hp if c.status.suited else 0))
        for rank, cog in enumerate(sleepers, start=1):
            order[id(cog)] = max(1.0, rank / float(standing))

    if not LURE_IS_SPENT_ON_SLEEPERS:
        # LEAVING THEM ASLEEP IS THE STRATEGY, not a failure to get
        # round to them. The owner: lure the field with a Presentation,
        # never touch the sleepers, and fight the cogs that walk in to
        # replace the ones you kill. Three cogs are simply out of the
        # fight for the whole duration.
        #
        # `reach` prices the opposite plan -- that you will work through
        # the sleepers and wake each one yourself -- and so charges a
        # 15-round Presentation for about four rounds of quiet solo.
        # That is the gag a solo VP is built around, valued at a
        # quarter of what it delivers.
        reach = float("inf")

    total = 0.0
    for old, new in zip(before.cogs, after.cogs):
        if old.status.is_dead:
            continue
        threat = _cog_threat(old)
        if not threat:
            continue
        if new.status.is_dead:
            # KILLING AN ALREADY-LURED COG SILENCES NOTHING THIS ROUND,
            # and crediting it the full awake threat is what made the
            # panel spend a pink slip on a sleeping Mr. Hollywood while
            # an identical one stood awake beside it. Both fires scored
            # 484.9 -- exactly equal -- so the choice fell to whichever
            # the policy happened to rank first, and the scorer had no
            # opinion at all on the one question that mattered.
            #
            # This is the principle three paragraphs up, applied to the
            # branch that was missing it: "an already-lured cog buys
            # nothing new. It was paid for when the lure landed." A
            # lured cog is contributing zero already, so removing it
            # removes zero MORE per round.
            #
            # It does not make killing sleepers bad, and must not be
            # read that way. `QUICK_W["kill"]` prices removal
            # separately and permanently -- this term is only the
            # damage-per-round silenced, which its own docstring says.
            # What changes is that an awake cog is now the better
            # target when everything else is equal, which is the whole
            # of the complaint.
            if not (LURED_KILL_SILENCES_NOTHING and old.status.lured):
                total += threat                  # silenced for good
            else:
                # SCALED BY THE LURE LEFT, not zeroed. A cog asleep for
                # three more rounds is already silent for as long as the
                # party will reach it, so killing it silences nothing;
                # one about to wake is nearly as good a target as an
                # awake one, and a flat zero priced those two the same.
                #
                # Same `reach` horizon the crediting branches use, so
                # the three agree about how far ahead this term looks.
                left = min(float(old.status.lure_rounds_remaining), reach)
                total += threat * max(0.0, 1.0 - left / reach)
        elif new.status.lured and not old.status.lured:
            horizon = order.get(id(new), reach)
            rounds = min(float(new.status.lure_rounds_remaining), horizon)
            total += threat * max(0.0, rounds)
        elif WAKE_COSTS_PREVENTED and old.status.lured                 and not new.status.lured:
            # WOKEN, and this used to be free. The three cases above
            # credit quiet bought; nothing charged for quiet spent, so a
            # plan could hand four sleeping cogs their attacks back and
            # the term stayed at zero. Solo on a lured field the scorer
            # read `Foghorn -> all` at 142.8 against `Whole Cream Pie ->
            # c0` at 36.8 purely on damage dealt, while the Foghorn left
            # four cogs awake threatening 61.8 a round and the Cream Pie
            # left one threatening 13.4.
            #
            # Symmetric with the credit: the rounds of quiet the lure
            # would still have delivered, capped by `reach` for the same
            # reason.
            #
            # This does NOT make attacking a lured cog bad. It makes it
            # cost something, which is true -- knockback is paid for with
            # the lure -- and leaves the damage and kill terms to decide
            # whether the trade is worth taking.
            rounds = min(float(old.status.lure_rounds_remaining), reach)
            total -= threat * max(0.0, rounds)
    return total


def killed_threat(before: BattleState, after: BattleState) -> float:
    """Damage per round removed by killing, not just the count.

    `killed` is a flat count, so it pays the same for a Legal Eagle
    threatening 11.6 a round as for a Flunky threatening 1.3. No weight
    on a count can express which cog mattered -- that needs the threat
    itself, which `expected_incoming` already knows how to compute.
    """
    total = 0.0
    for old, new in zip(before.cogs, after.cogs):
        if new.status.is_dead and not old.status.is_dead:
            total += _cog_threat(old)
    return total


SURVIVAL_CAP = 4.0
"""Rounds of survival past which more laff stops mattering to a choice.

Uncapped, a maxed toon on a quiet board scores enormous survival and the
term drowns everything else. Four rounds is long enough that a plan
which buys a fifth is not choosing between life and death any more.
"""


def survival_rounds(state: BattleState) -> float:
    """How many rounds of incoming the party's laff currently covers.

    THE ONE THING NO SCORER COULD SEE. Every other term here is a DELTA
    across the round -- damage dealt, damage prevented, laff restored by
    a gag -- and `_score_leaf` simulates the toon phase only, so laff
    does not move within it. A term reading laff LEVEL is therefore
    constant across gag choices and cannot change which gag is picked.
    That is exactly why `QUICK_W["risk"]` was swept over 0/5/15/40 and
    changed not one game in 900: a constant cannot move an argmax.

    It is NOT constant across the other decision. "Use a unite, then
    throw" and "throw" differ by up to 80 laff, so this is the term
    that makes a unite visible -- and without it a unite scored exactly
    zero, measured: 329.40 before restoring 80 laff and 329.40 after.

    In ROUNDS rather than in laff, because laff alone is not
    comparable across boards. Thirty laff is comfortable against two
    Cold Callers and nearly dead against four level 12s, and it is the
    second that decides whether to spend a unite. Reading it against
    `expected_incoming` says so directly.

    Capped by `SURVIVAL_CAP`; see there.
    """
    standing = [t for t in state.toons if t.laff > 0]
    if not standing:
        return 0.0
    incoming = expected_incoming(state)
    if incoming <= 0:
        # Nothing is swinging -- every plan survives, so this cannot
        # discriminate and should not be allowed to dominate.
        return SURVIVAL_CAP
    laff = min(t.laff for t in standing)
    return min(SURVIVAL_CAP, laff / incoming)


def toons_at_risk(state: BattleState) -> float:
    """Standing toons a round of incoming damage could knock out.

    RE-SWEPT AFTER THE FIX BELOW, and the weight stays 0.0 -- but for a
    different reason than the one that zeroed it first, and the new
    reason is worth having. Solo VP, 200 runs a cell:

        risk weight    12 a round    20 a round
                  0         29.0%          0.0%
                  5         29.0%          0.0%
                 15         29.0%          0.0%
                 40         29.0%          0.0%

    Not one game changed at any weight, +0/-0 on identical seeds.

    The function is NOT dead this time: it reads non-zero in 61 of 168
    sampled VP positions, and it discriminates cleanly between plans.
    On a toon at 35 laff facing 53 incoming from four awake cogs,
    Presentation and Hypno-goggles leave risk at 0.000 while Foghorn,
    Birthday Cake and a pink slip all leave it at 1.000.

    It arrives too late to matter. Risk is zero for every candidate
    while laff is healthy, so the term is a constant that cannot move
    an argmax; it only separates plans once the toon is already low,
    and by then a solo VP is lost whatever it picks. A term that is
    flat in the winnable region and decisive in the lost one changes
    nothing about the outcome.

    That points at prevention rather than risk: `QUICK_W["prevent"]`
    values removing incoming damage the SAME at 100 laff and at 20,
    when the second is worth far more. Scaling prevention by how close
    to death the toon is would act early, where the game is still
    winnable, and is the thing to try next.
    Nothing in any scorer charged for losing a toon. A sad toon takes
    their whole pouch out of the run -- in a building that is every
    later floor -- and the only way it registered was indirectly,
    through prevention they no longer contribute.

    THIS RETURNED ZERO EVERYWHERE and that is why the feature read as
    worthless. It used to take `expected_incoming` -- already
    probability-weighted -- and divide it again by the number of toons
    standing, asking whether a toon could survive their share of the
    AVERAGE. Nothing goes sad to an average. Measured over 2000 sampled
    facility starts it was non-zero in exactly none of them, and it was
    zero in a hand-built position of four toons on 22 laff facing four
    level 12s, where every toon is one group attack from sad. A sweep
    of the weight over 0, 2, 5, 10 changed not one decision in 900
    games, because no weight moves a constant.

    So the old ES result that zeroed `QUICK_W["risk"]` was never
    evidence about risk. It was evidence about this function.

    What sinks a toon is one bad ROUND, not a share of an expectation,
    which is the rule `features.one_hit_from_death` already uses:
    `outcomes.worst_case_damage` per cog, summed, against the smallest
    laff. Same rule here, with one difference that is the whole point of
    the term -- a LURED cog is skipped, because it does not swing, so
    luring visibly lowers the count and the scorer can finally see that
    it does.
    """
    from .. import outcomes as outcomes_mod

    standing = [t for t in state.toons if t.laff > 0]
    if not standing:
        return 0.0
    worst = 0
    for cog in state.active_cogs():
        if cog.status.lured:
            continue
        try:
            worst += outcomes_mod.worst_case_damage(cog)
        except NotImplementedError:      # a [TODO] attack table
            pass
    return sum(1.0 for t in standing if t.laff <= worst)


def armed_credit(before: BattleState, after: BattleState) -> float:
    """Damage a trap laid this round will deal when a lure springs it.

    ONE ROUND OF FUTURE VISION, and the narrowest useful kind. This
    scorer plays a single all-hit round, so a trap -- which deals
    nothing until a lure arrives -- scored zero and every plan
    containing one ranked below every plan that attacked. Measured: with
    trap actions explicitly offered to the hybrid climb, trap use moved
    1.0% to 1.2% and the finish rate got WORSE, because the option was
    being offered and this function was declining it.

    Priced like `_cheap_score` does: the trap's damage capped at what
    the cog has left, discounted by TRAP_DISCOUNT, and only when
    somebody is holding a Lure to spring it. A trap with nothing behind
    it really is a wasted gag and should still score zero.

    Deliberately NOT netting off the lure it will consume, which
    `_cheap_score` does. There the trap is being compared against
    attacking that cog directly; here the plan has already been played
    and the question is only what the board is now worth.
    """
    from .. import data
    from .. import mechanics

    holds_lure = any(key[0] == Track.LURE and count > 0
                     for toon in after.toons if toon.laff > 0
                     for key, count in toon.gag_counts.items())
    if not holds_lure:
        return 0.0

    total = 0.0
    for old, new in zip(before.cogs, after.cogs):
        if new.status.is_dead or not new.status.trapped:
            continue
        if old.status.trapped or new.status.trap_level is None:
            continue          # already armed before this round
        try:
            damage = mechanics.calc_toon_damage(
                Track.TRAP, new.status.trap_level,
                organic=new.status.trap_organic)
        except (NotImplementedError, ValueError, KeyError):
            continue
        total += TRAP_DISCOUNT * float(min(damage, max(0, new.hp)))
    return total


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
FIRE_FLOOR = 20.0


# A branch this unlikely is not worth a probe. The pruned mass is
# renormalised away, so this trades a little accuracy in the tail for
# skipping leaves that cannot move a ranking.
MIN_LEAF_PROB = 1e-3


def _restored(healed, toons) -> float:
    """Laff a round actually put back, capped at each toon's headroom.

    Shared by `_score_leaf` and `_greedy_score`, which measured it with
    the same four lines apiece. Overhealing must not look like value,
    and a sad toon is not healed at all.
    """
    total = 0.0
    for amount, before in zip(healed, toons):
        if amount > 0 and before.laff > 0:
            total += min(amount, before.max_laff - before.laff)
    return total


def _landed(before_cogs, after_cogs) -> int:
    """Hit points a round took off, counting BOTH layers of a v2.0.

    See `remaining_hp` for why `cog.hp` alone reads zero when a suit
    breaks. Shared by `_score_leaf` and `_greedy_score`.
    """
    return sum(remaining_hp(before) - remaining_hp(after)
               for before, after in zip(before_cogs, after_cogs))


def _killed(before_cogs, after_cogs) -> int:
    """Cogs this round removed. Shared by `_score_leaf` and
    `_greedy_score`."""
    return sum(1 for before, after in zip(before_cogs, after_cogs)
               if not before.status.is_dead and after.status.is_dead)


def _gag_units(track, level: int, unlocked: int) -> float:
    """What one gag costs the two fast scorers, in their own units.

    `level + SCARCITY_UNITS / carry_limit` -- a level term plus a
    scarcity term, which is `Objective.gag_cost` and
    `Objective.scarcity_cost` in a different currency with the ratio
    between them fixed. Neither scorer takes an objective, so neither
    can read those fields; this is the stand-in. The disagreement is
    catalogued in docs/scoring.md, not resolved here.

    One definition because `_score_leaf` and `_cheap_score` each spelt
    it out, with the same literal 20.0 and the same fallback.
    """
    try:
        limit = gags_mod.carry_limit(track, level, unlocked) or 1
    except (NotImplementedError, ValueError):
        limit = 1
    return float(level) + SCARCITY_UNITS / limit


def _fire_price(cogs_remaining: int, floor: bool = False) -> float:
    """What a pink slip costs a scorer, per cog still to come.

    `floor=True` adds `FIRE_FLOOR`, which only `_score_leaf` charges --
    see `FIRE_FLOOR` for why the callers differ. Reads the module
    globals at call time, so a test that patches `FIRE_PRICE` or
    `FIRE_FLOOR` still reaches every scorer.
    """
    return FIRE_PRICE * float(cogs_remaining) + (FIRE_FLOOR if floor
                                                 else 0.0)


def _roll_groups(plan) -> Dict[int, tuple]:
    """Toon index -> the shared die that toon's gag resolves on.

    Accuracy is rolled per track per target, so two toons throwing the
    same track at the same cog land or miss TOGETHER. That correlation
    is the whole reason this mapping exists rather than a per-toon hit
    probability: treating the two rolls as independent lets a plan hedge
    in a way the game does not allow, and overvalues stacking a track on
    one target -- the error `apply_party_round` was written to avoid.

    Fires and passes never roll, so they are absent.
    """
    groups: Dict[int, tuple] = {}
    for index, action in enumerate(plan):
        if action is None or action.is_pass or action.fire:
            continue
        groups[index] = (action.track, action.target_index)
    return groups


def _score_leaf(state: BattleState, plan, hits, record=None,
                objective=None) -> float:
    """Score one fixed outcome of the round -- who hit and who missed.

    `objective`, when given, adds `waste_penalty` on top of the fixed
    `QUICK_W` terms. See `_quick_score`.
    """
    from .. import data

    probe = state.clone()
    try:
        healed = simulator.apply_party_round(
            probe, list(plan), hits=hits, record=record)
    except (NotImplementedError, ValueError, KeyError):
        return float("-inf")
    # Healing counts here too. This ranks which PLANS get sampled at
    # all, so a plan containing a heal scored strictly below the same
    # plan attacking and was truncated before evaluation -- the
    # shortlist-deletion failure this file has had three times.
    restored = _restored(healed, state.toons)
    landed = _landed(state.cogs, probe.cogs)
    killed = _killed(state.cogs, probe.cogs)
    price = 0.0
    for track, level, count, unlocked in _spent(state, probe):
        price += count * _gag_units(track, level, unlocked)
    # Same horizon scaling the real reward applies. This decides which
    # plans are ever sampled, so ranking here at horizon 0 would drop
    # the conserving plan before anything could evaluate it -- the
    # shortlist-truncation bug this file has had three times already.
    price *= 1.0 + objective_mod.Objective().horizon_cost * float(
        state.cogs_remaining)
    # A slip spent now is one not held for the cogs still to come, so it
    # costs what is still coming -- plus a floor, because "nothing is
    # coming" and "nobody told us what is coming" are different states
    # and this term could not tell them apart.
    #
    # THE PANEL NEVER SETS `cogs_remaining`. Nothing in
    # `realms_session.build_state` can know how many cogs a VP or a
    # building still has, so it is 0 on every live board -- and a slip
    # was therefore free in live play, always. The owner watched it
    # spend one on a level 1 Cold Caller with 6 hp while holding a
    # pouch full of gags that would have killed it.
    #
    # The floor is what a slip is worth against the cog it could have
    # been saved for, rather than against the fight's remaining length,
    # so it applies even in a genuine last battle. `FIRE_FLOOR` at zero
    # restores the old behaviour exactly.
    price += _fire_price(state.cogs_remaining,
                         floor=True) * _fires_spent(state, probe)
    return (landed
            + QUICK_W["heal"] * restored
            + QUICK_W["armed"] * armed_credit(state, probe)
            + QUICK_W["kill"] * killed
            + (QUICK_W["kill_threat"] * killed_threat(state, probe)
               if QUICK_W["kill_threat"] else 0.0)
            + QUICK_W["prevent"] * prevented(state, probe)
            - (QUICK_W["waste"] * _waste_fraction(state, plan)
               if QUICK_W["waste"] else 0.0)
            - (waste_penalty(objective, state, plan)
               if objective is not None else 0.0)
            - (QUICK_W["risk"] * toons_at_risk(probe)
               if QUICK_W["risk"] else 0.0)
            + (QUICK_W["survive"] * survival_rounds(probe)
               if QUICK_W["survive"] else 0.0)
            - QUICK_W["price"] * price)


def _expected_over_rolls(state: BattleState, plan, leaf) -> float:
    """Average `leaf` over every way this round's dice can fall.

    `leaf(hits, record)` scores ONE fixed outcome of the round and must
    pass `record` through to `apply_party_round`, which fills it with the
    accuracy each roll group was actually resolved against.

    Enumerated, not sampled. A party is at most four toons and each rolls
    at most one die, so at most 16 branches -- few enough to take
    exactly, and exact means a ranking cannot wobble between two calls on
    the same position, which a sampled score does. Branching over ROLL
    GROUPS rather than over toons gets the correlated dice right for
    free: two toons throwing one track at one cog land or miss together,
    so a plan cannot hedge by stacking a track on a target.

    The probabilities come from the simulator's own `record` rather than
    being recomputed here, and they are read PER BRANCH, because accuracy
    is conditional and the conditions are not small: a landed Throw lifts
    a following Drop from 54% to 79%, a second Lure lifts the pair from
    79% to 95%, a trapped target lifts a Lure from 79% to 95%. A table of
    per-gag accuracies would get all three wrong. Reading the simulator's
    own numbers also means the two cannot drift apart -- a second
    implementation of the accuracy rules is what put a 5% miss on an
    always-hit Trap.

    One function rather than one per scorer for that same reason.
    """
    groups = _roll_groups(plan)
    keys = list(dict.fromkeys(groups.values()))
    if not keys:
        # Nothing rolls -- fires and passes only. One branch, and `hits`
        # is never consulted for either.
        return leaf([True] * len(plan), None)

    # The all-hit branch first. It doubles as the accuracy estimate that
    # decides which branches are worth a probe at all, and it IS one of
    # the branches, so it is scored once and reused rather than replayed.
    all_hit_bits = (1 << len(keys)) - 1
    seed_record: List = []
    all_hit = leaf([True] * len(plan), seed_record)
    if all_hit == float("-inf"):
        return all_hit
    approx = {(track, key): min(max(accuracy, 0), 100) / 100.0
              for track, key, accuracy in seed_record}

    total = mass = 0.0
    for bits in range(1 << len(keys)):
        landed = {key: bool(bits >> i & 1) for i, key in enumerate(keys)}
        guess = 1.0
        for key, hit in landed.items():
            chance = approx.get(key, 1.0)
            guess *= chance if hit else 1.0 - chance
        if guess < MIN_LEAF_PROB:
            continue
        if bits == all_hit_bits:
            score, record = all_hit, seed_record
        else:
            hits = [landed.get(groups.get(i), True) for i in range(len(plan))]
            record = []
            score = leaf(hits, record)
        if score == float("-inf"):
            continue
        # Chain rule: each group's accuracy is the one THIS branch
        # resolved it against, so conditioning on earlier hits is already
        # baked in.
        chance = 1.0
        for track, key, accuracy in record:
            hit = landed.get((track, key))
            if hit is None:
                continue
            landed_p = min(max(accuracy, 0), 100) / 100.0
            chance *= landed_p if hit else 1.0 - landed_p
        total += chance * score
        mass += chance
    if mass <= 0.0:
        return all_hit
    # Renormalise: pruning above removes a little mass, and a plan must
    # not score lower merely because more of its branches were skipped.
    return total / mass


def _quick_score(state: BattleState, plan, objective=None) -> float:
    """Expected value of the round over every way the dice can fall.

    NO SHIPPED CALLER PASSES `objective`. `plans` (this module),
    `hybrid._judge` (which is what `hybrid.climb` scores with) and
    `hybrid.best_plan`, plus `tools/train_heads.py`, all call this with
    two arguments, so the
    `waste_penalty` branch in `_score_leaf` is unreachable in practice
    and overkill is charged only through `QUICK_W["waste"]`, which is
    0.0. That is the defect docs/scoring.md was written to make
    visible; it is recorded there rather than fixed here, because
    turning it on changes numbers and every number in this file was
    measured.

    `objective` is OPTIONAL and off by default, which is not laziness --
    the setting only half-applies. It steers this ranker but not the
    policy that proposes to it, so with it on, `survive` and `glass
    cannon` still shortlist the same moves and merely order them
    differently. That was reason enough to leave it out while the menu
    came only from the policy; `PROBE_CHEAPEST_KILL` now puts the cheap
    option there regardless, so the ranker can act on it.

    What it buys that `QUICK_W["waste"]` cannot: `waste_penalty` scales
    by SCARCITY as well as by wasted fraction, so burning one of three
    Grand Pianos into a 6hp cog costs far more than spilling a Seltzer
    there. A flat fraction cannot say that, and a flat fraction is what
    was swept and failed -- twice.

    This used to play ONE ALL-HIT round, and that assumption is what lost
    the CEO. In a cog building it is nearly true -- accuracy runs 70-95%
    and hardly varies by track -- so ranking by damage and ranking by
    expected damage pick the same gag. Against level 13-14 cogs accuracy
    spans 51% (a level 7 Drop) to 95% and they stop agreeing: the all-hit
    score prefers the biggest number printed on the gag, which is
    reliably the least likely one to arrive.

    Measured on 200 CEO sides with common random numbers, 0 leftovers:
    69.5% -> 75.0% cleared, +24 won against 13 lost, sign test p=0.049.
    Cog buildings unchanged, which is the result that mattered -- the
    weights were fitted there.

    It still looks one step past the round for a trap, and only a trap:
    see `armed_credit`.
    """
    return _expected_over_rolls(
        state, plan,
        lambda hits, record: _score_leaf(state, plan, hits, record,
                                         objective))


def _playable(state: BattleState, plan) -> bool:
    """Can each toon actually throw what the plan gives them?

    A multiset says what gets thrown, not who throws it, so the same
    gag can land on a toon who has none left -- or twice on a toon
    holding one.
    """
    from .. import data

    # Everyone holding is legal but cannot win, and it is the one plan a
    # rollout can spin on. Nothing restocks a pouch, so a round where
    # the whole team passes only feeds the cogs a free turn.
    if all(action is None or action.is_pass for action in plan):
        return False

    trapped = set()
    for toon, action in zip(state.toons, plan):
        # A hold throws nothing, so there is no gag to check for.
        if action is None or action.is_pass:
            continue
        if toon.gag_counts.get((action.track, action.level), 0) <= 0:
            return False
        if toon.track_exp.get(action.track, 0) <= 0:
            return False
        # A cog takes one trap, so a second on the same cog is a wasted
        # gag rather than a strategy.
        #
        # NOTE there is deliberately no matching rule for Lure. There
        # was one, and it was WRONG. [CONFIRMED] TTR wiki (Lure):
        # "Using multiple Lure gags simultaneously increases the
        # accuracy", and the update notes: "Multiple Lure gags of the
        # same type used simultaneously now grant a bonus (20/15/10)%
        # accuracy depending on the gag level discrepancies of the
        # additional Lure gags". Stacking Lure is a real TTR play and
        # the search must be allowed to find it.
        #
        # That bonus IS modelled -- `mechanics.multi_lure_bonus`,
        # applied to the shared roll in `apply_party_round`. Its
        # MAGNITUDE is [ASSUMED]; its existence and eligibility are
        # [CONFIRMED]. This comment used to claim the bonus was missing
        # entirely, which made a stacked Lure look like pure cost.
        if action.track == Track.TRAP:
            if action.target_index in trapped:
                return False
            trapped.add(action.target_index)

    # Cogs that will be lured by the time Drop resolves: already lured,
    # plus anything this plan's Lures catch. ATTACK_ORDER puts Lure
    # before Drop, so a Drop aimed at one of them is a guaranteed miss.
    lured_after = {i for i, cog in enumerate(state.cogs)
                   if cog.status.lured and not cog.status.is_dead}
    has_lure = has_sound = False
    for action in plan:
        if action is None:
            continue
        if action.track == Track.LURE:
            has_lure = True
            if action.target_index is None:
                lured_after.update(
                    i for i, cog in enumerate(state.cogs)
                    if not cog.status.is_dead)
            else:
                lured_after.add(action.target_index)
        elif action.track == Track.SOUND:
            has_sound = True

    # ... unless something in the same round WAKES the cog first.
    # [CONFIRMED] TTR wiki (Lure): "Lured Cogs are awakened by Sound
    # gags", and ATTACK_ORDER puts SOUND before DROP -- so a Sound this
    # round un-lures the cog in time for the Drop to land on it. Every
    # Sound gag is a group gag, so one anywhere in the plan covers every
    # cog.
    #
    # That makes Sound-then-Drop a real play rather than a wasted gag,
    # and this rule must not ban it. It is a gamble, not a guarantee --
    # a Sound that misses leaves the cog lured and the Drop still misses
    # -- but `_playable` exists to refuse things that CANNOT work, not
    # things that might not.
    if not has_sound:
        for action in plan:
            if action is None or action.track != Track.DROP:
                continue
            # [CONFIRMED] TTR wiki (Lure): "Drop gags always miss on
            # lured Cogs." The simulator already resolves this
            # correctly; the search was still spending plan slots
            # proposing it, and a verified example had the Drop and the
            # toon doing NOTHING give an identical board.
            if action.target_index is None:
                if all(i in lured_after for i, cog in enumerate(state.cogs)
                       if not cog.status.is_dead):
                    return False
            elif action.target_index in lured_after:
                return False

    # A heal with nobody to heal. [CONFIRMED] TTR wiki (Toon-Up):
    # "Toons cannot use Toon-Up gags to restore their own laff" -- so if
    # every OTHER standing toon is already at full laff, the gag is spent
    # for literally nothing, exactly like a Drop on a lured cog.
    #
    # This is what kept a healthy party opening with Toon-Up, and it
    # survived three fixes aimed at it. Holding was added, which made a
    # no-op heal merely equal to holding rather than worse; the
    # heal/damage clamp was corrected, which does not bite when nobody
    # is hurt; and the heal was redirected to teammates, which on a
    # full-laff party is one no-op replacing another -- the position's
    # value did not move by so much as 0.01 across any of them. A no-op
    # has to be refused outright, not merely priced.
    for index, action in enumerate(plan):
        if action is None or action.track != Track.TOON_UP:
            continue
        healable = [other for i, other in enumerate(state.toons)
                    if i != index and other.laff > 0
                    and other.laff < other.max_laff]
        if not healable:
            return False

    # [CONFIRMED] TTR wiki (Lure): "Lured Cogs are awakened by Sound
    # gags without a damage bonus." Luring in the same round as Sound
    # therefore buys nothing -- the Sound wakes what the Lure just
    # caught, and does not even collect the lured damage bonus for it.
    # There are niche uses, but the plan is dominated by joining the
    # Sound or throwing an attack gag instead, so it does not earn a
    # slot on a shortlist this narrow.
    if has_lure and has_sound:
        return False

    return True


def plan_waste(state: BattleState, plan) -> Tuple[float, float]:
    """(damage thrown away, gag price of the plan).

    Waste is damage aimed at hit points that are not there -- a Railroad
    into a five-hit-point cog kills it and discards the rest. The
    objective charged nothing for that: a gag cost its price whether it
    was needed or wasted, so nothing distinguished spending a level 7
    because it was the only thing that would kill the cog from spending
    it because it was in the pouch.

    Straight algebra: for each cog, the damage aimed at it minus the hit
    points it has, when that is positive. A cog's hp clamps at zero, so
    the excess is not readable from the resolved board -- but it does
    not need to be resolved at all, because both quantities are known
    before the round.

    The damage has to be totalled per (track, target) first rather than
    per gag, because `calc_hp_bonus` gives same-track gags on one cog a
    combo bonus on their combined total. Summing gags independently
    would understate the damage and so understate the waste.

    Computed from the plan and assuming it lands, so it measures the
    *choice* rather than the dice. Throwing a Railroad at a nearly-dead
    cog is the same decision whether or not it hits.
    """
    from .. import data
    from .. import mechanics

    live = [(i, cog) for i, cog in enumerate(state.cogs)
            if not cog.status.is_dead]
    if not live:
        return 0.0, 0.0
    toughest = max(cog.hp for _i, cog in live)

    # Single-target gags are grouped per (track, target); group gags are
    # grouped per track, and their waste is counted ONCE against the
    # toughest cog rather than per cog.
    #
    # THIS DISTINCTION IS THE WHOLE CORRECTNESS OF THE MEASURE, and the
    # first version got it wrong. A group gag's damage is uniform by
    # construction: the overkill it does to a weak cog is not a choice
    # anyone made, it is what a group gag IS. Charging for it per cog
    # meant 2 Foghorn + 2 Aoogah -- the known-best line on the maxed
    # position, sized within 3 damage of the toughest cog -- was billed
    # for 84 wasted damage and priced out of its own win.
    #
    # What a player actually chooses about a group gag is how big a one
    # to bring, and the binding constraint is the toughest cog it has to
    # kill. So the waste is `dealt - toughest`, once. 2 Foghorn + 2
    # Aoogah (159 against 156) now wastes 3; 4 Foghorn (240) wastes 84;
    # 4 Opera Singer (432) wastes 276. Which is the real ranking.
    singles: Dict[tuple, List[int]] = {}
    group: Dict[Track, List[int]] = {}
    for toon, action in zip(state.toons, plan):
        # A pass has no track, so it must be skipped here with the
        # other tracks that deal no damage -- `calc_toon_damage(None, 0)`
        # raises. It wastes nothing by definition.
        #
        # A FIRE is skipped for the same reason and a better one: it has
        # no track either, and it cannot waste anything. Overkill is the
        # thing this function charges for, and a pink slip removes the
        # cog whatever its hp -- there is no excess to spill.
        if (action is None or action.is_pass or action.fire
                or action.track in (Track.TOON_UP, Track.LURE,
                                    Track.TRAP)):
            continue
        try:
            dmg = mechanics.calc_toon_damage(
                action.track, action.level,
                organic=toon.is_organic(action.track))
        except (NotImplementedError, ValueError):
            continue
        if action.target_index is None:
            slot = group.setdefault(action.track, [0, 0])
        else:
            slot = singles.setdefault((action.track, action.target_index),
                                      [0, 0])
        slot[0] += dmg
        slot[1] += 1

    raw = 0
    useful = 0
    for (_track, index), (damage, count) in singles.items():
        total = damage + mechanics.calc_hp_bonus(damage, count)
        raw += total
        if 0 <= index < len(state.cogs):
            useful += min(total, max(0, state.cogs[index].hp))
    for _track, (damage, count) in group.items():
        total = damage + mechanics.calc_hp_bonus(damage, count)
        raw += total
        useful += min(total, toughest)

    price = 0.0
    for toon, action in zip(state.toons, plan):
        if action is None or action.is_pass:
            continue          # a pass costs no gag, so no scarcity
        try:
            limit = gags_mod.carry_limit(
                action.track, action.level,
                toon.track_exp.get(action.track, 0)) or 1
        except (NotImplementedError, ValueError, KeyError):
            limit = 1
        price += 1.0 / limit

    return max(0.0, float(raw - useful)), price


def _waste_charge(state: BattleState, plan, weight: float) -> float:
    """`weight x wasted_fraction x scarcity`, the one waste shape.

    Both charges for overkill are this expression: `_waste_fraction`
    calls it with a weight of 1 so `QUICK_W["waste"]` can scale the
    result, and `waste_penalty` calls it with `objective.waste_weight`.
    They were two copies of the arithmetic, which is part of how the
    same concept came to be priced twice -- see docs/scoring.md.
    """
    wasted, scarcity = plan_waste(state, plan)
    if wasted <= 0.0 or scarcity <= 0.0:
        return 0.0
    total = wasted + sum(cog.hp for cog in state.cogs
                         if not cog.status.is_dead)
    fraction = wasted / total if total > 0 else 0.0
    return weight * fraction * scarcity


def _waste_fraction(state: BattleState, plan) -> float:
    """`waste_penalty`'s shape without an objective's weight.

    Split out so `_quick_score` can charge for overkill. That scorer
    takes no objective -- it ranks the policy's proposals inside
    `hybrid.climb`, which has none to give it -- so it cannot call
    `waste_penalty`, and the weight lives in `QUICK_W` instead.

    Also read by `rl/env.py` as the `--precision` reward term, which is
    the third weight on this one quantity. See docs/scoring.md.
    """
    return _waste_charge(state, plan, 1.0)


def waste_penalty(objective, state: BattleState, plan) -> float:
    """What this plan is charged for damage it throws away.

    Scaled by the *scarcity* of what was spent, which is the whole
    point: wasting a level 7 (one per pouch) has to hurt far more than
    wasting a level 1 (thirty per pouch), and a flat per-damage charge
    would treat them alike.

    The shape is `weight x wasted_fraction x scarcity`, so a plan whose
    damage is all needed pays nothing however dear its gags -- which is
    exactly the "unless it is the only option" case. A level 7 that is
    the only gag that kills the cog wastes little and is barely touched;
    the same gag into a nearly-dead cog is charged nearly in full.

    `waste_weight` is a CHOSEN number, like every other weight in
    `objective` -- nothing in the game states it. It is not a [TODO]
    standing in for a fact, it is a preference about how to play.
    """
    weight = getattr(objective, "waste_weight", 0.0)
    if not weight:
        return 0.0
    return _waste_charge(state, plan, weight)


def round_reward(objective, laff_lost: int, spent, won: bool,
                 lost: bool, toons_lost: int = 0,
                 cogs_remaining: int = 0) -> float:
    """What one party round was worth.

    The team's laff and the team's gags, priced by the same objective
    the solo search uses, so a party line and a solo line are at least
    denominated in the same units.
    """
    from ..data.gags import POUCH_EXEMPT_LEVEL

    reward = -objective.laff_weight * float(laff_lost)
    for entry in spent:
        # `_spent` yields the holder's training level as a fourth field so
        # scarcity can be priced per toon. Callers that build `spent`
        # themselves still pass triples, and those price as a fully
        # trained track -- which is what this did for everyone before.
        track, level, count = entry[0], entry[1], entry[2]
        unlocked = entry[3] if len(entry) > 3 else 6
        reward -= count * objective.gag_price(track, level, cogs_remaining,
                                              unlocked)
        if level >= POUCH_EXEMPT_LEVEL:
            reward -= count * getattr(objective, "rare_gag_premium", 0.0)
    # A toon going sad is not just the laff they had left -- it is a
    # combatant, their pouch, and every action they would have taken.
    reward -= toons_lost * getattr(objective, "toon_lost_penalty", 0.0)
    reward -= objective.turn_cost
    if won:
        reward += objective.win_bonus
    elif lost:
        reward -= objective.loss_penalty
    return reward


def _spent(before: BattleState, after: BattleState):
    """(track, level, count, unlocked) per gag spent this round.

    `unlocked` is the training level of the toon who SPENT it, because a
    carry limit -- and so scarcity -- belongs to the holder rather than
    to the gag.
    """
    out = []
    for old, new in zip(before.toons, after.toons):
        for key, had in old.gag_counts.items():
            used = had - new.gag_counts.get(key, 0)
            if used > 0:
                out.append((key[0], key[1], used,
                            old.track_exp.get(key[0], 0)))
    return out


def _fires_spent(before: BattleState, after: BattleState) -> int:
    """Pink slips used this round, across the party."""
    return sum(max(0, old.fires - new.fires)
               for old, new in zip(before.toons, after.toons))


# Rounds a rollout will play before giving up and calling the position
# unresolved. A real battle ends well inside this; the cap only stops a
# pathological position (mutual inability to finish) spinning forever.
ROLLOUT_ROUNDS = 12


def greedy_plan(state: BattleState, objective) -> List[Optional[Action]]:
    """A decent action for every toon, chosen rather than sampled.

    WHY THIS IS NOT `SensiblePrior`, WHICH IT USED TO BE
    ----------------------------------------------------
    `SensiblePrior` is a model of *people* -- what a stranger is likely
    to throw. That is exactly right for one job and wrong for another,
    and the two were sharing a policy:

      * PICKUP teammates -- you genuinely cannot control them, so the
        right object is a distribution over what they might do, and no
        amount of cleverness replaces it. `SensiblePrior` keeps this job.

      * The ROLLOUT continuation -- here nothing is being predicted. The
        rollout exists to *estimate the value of a position*, and the
        value of a position is what it is worth under good play, not
        under average play. Estimating it with a model of an average
        stranger systematically undervalues any line whose payoff needs
        follow-through -- which is every Lure strategy there is, and is
        the mechanism behind "no Lure strategy ever appears" in
        docs/party-strategy.md. The plan was scored on a continuation
        that would not carry it out.

    So this is deliberately not a people-model. It takes the best action
    it can see one round ahead under the *objective the search is
    actually optimising*: damage that lands somewhere it is needed, cogs
    killed, minus what it costs and what it throws away. Greedy and
    myopic, and still a much better proxy for "played well from here"
    than a guess about strangers.

    It is not free. A rollout now costs a scan of each toon's candidate
    list per round instead of one weighted draw, which is the reason
    `ROLLOUT_ROUNDS` stays modest.
    """
    plan: List[Optional[Action]] = [None] * len(state.toons)
    working = state.clone()
    for index, toon in enumerate(state.toons):
        if toon.laff <= 0:
            continue
        # Rank every candidate by arithmetic, then SIMULATE only the
        # best few. This was simulating a full round for every candidate
        # of every toon on every round of every rollout -- 117k
        # simulations on one depth-1 search, 46% of its runtime -- to
        # pick one action. The arithmetic gets the shortlist to roughly
        # the right handful; the simulation, which knows about knockback,
        # trap triggers and combo bonuses, still decides between them.
        # Memoised because an action can be scored more than once while
        # the pool is sorted.
        seen: Dict[tuple, float] = {}

        def score_of(action, _cache=seen, _index=index, _state=working):
            key = (action.track, action.level, action.target_index)
            if key not in _cache:
                _cache[key] = _cheap_score(_state, _index, action)
            return _cache[key]

        pool = candidates(working, index, per_track=3)
        pool.sort(key=lambda a: -score_of(a))
        # TRACK DIVERSITY, the same guarantee `plans()` gives the root.
        # `_cheap_score` sums a group gag's damage over every target, so
        # in a four-cog position the top of this list is group gags and
        # nothing else -- measured at 553/393/333 against 43 for the
        # best trap, rank 11. Taking the top two therefore simulated
        # only group attacks, and any track whose worth the arithmetic
        # does not capture was excluded before the simulation that
        # would have shown it. Trap was below the cut in 39 of 39
        # decisions.
        #
        # So: the best few overall, plus the best of each track not yet
        # represented. Bounded by the number of tracks, which is at most
        # seven.
        shortlist = pool[:GREEDY_SHORTLIST]
        seen_tracks = {a.track for a in shortlist}
        for action in pool:
            if len(shortlist) >= GREEDY_SHORTLIST + TRACK_PROBES:
                break
            if action.track not in seen_tracks:
                shortlist.append(action)
                seen_tracks.add(action.track)
        best, best_score = None, 0.0     # 0.0 => holding is the floor
        for action in shortlist:
            trial = [None] * len(state.toons)
            trial[index] = action
            score = _greedy_score(working, trial, objective)
            if score > best_score:
                best, best_score = action, score
        plan[index] = best
        if best is not None:
            # Later toons see the earlier ones' choices, so the team does
            # not pile four gags onto a cog the first one already killed.
            try:
                simulator.apply_party_round(
                    working, [a if i == index else None
                              for i, a in enumerate(plan)],
                    hits=[i == index and a is not None
                          for i, a in enumerate(plan)])
            except (NotImplementedError, ValueError, KeyError):
                pass
    return plan


def _cheap_score(state: BattleState, index: int, action: Action) -> float:
    """Rough worth of one action, by arithmetic and no simulation.

    Only ever used to pick which candidates deserve a real
    `_greedy_score`, so it may be crude -- but it must not be
    systematically blind to a track, or that track never reaches the
    shortlist. Hence Lure and Trap get explicit credit instead of
    scoring zero for dealing no damage, which is the mistake that would
    quietly delete the Lure strategies again.
    """
    from .. import data
    from .. import mechanics

    live = [cog for cog in state.cogs if not cog.status.is_dead]
    if not live:
        return 0.0

    # A pass spends nothing and achieves nothing, so it scores zero --
    # below any productive action, above one that wastes a gag. That
    # ordering is the whole point of offering it. Checked before the
    # price lookup, which would ask `data.gag(None, 0)`.
    if action.is_pass:
        return 0.0

    if action.fire:
        # A pink slip removes the target outright: unmissable, and it
        # takes both layers of a Version 2.0 with it. Scored as the kill
        # it is, plus the threat it silences, so it ranks above any gag
        # against the same cog -- which is the truth of it.
        #
        # It reaches this function at all only because `legal_actions`
        # offers it; before this branch existed, `_cheap_score` asked
        # `data.gag(None, 0)` and the whole search died with "no gag at
        # no track (a pass) level 0".
        #
        # NOT discounted for the turn it costs. Every action costs the
        # turn, so charging it here would only shift every score by a
        # constant. What is deliberately missing is any sense that slips
        # are FINITE -- this ranks one action, and scarcity across a
        # whole fight belongs to the objective's price, which charges
        # nothing for a fire because no gag leaves the pouch. A search
        # using this will therefore fire freely. That is close to right
        # for the CEO, where slips are the reward for the fight and
        # spending them is normal play, and wrong anywhere they are
        # precious.
        target_index = action.target_index
        if target_index is None or not (0 <= target_index < len(state.cogs)):
            return float("-inf")
        target = state.cogs[target_index]
        if target.status.is_dead:
            return float("-inf")
        removed = float(max(0, target.hp))
        if target.status.suited:
            removed += float(target.max_hp)     # the Skelecog goes too
        held = _fire_price(state.cogs_remaining)
        return removed + QUICK_W["kill"] + _cog_threat(target) - held

    toon = state.toons[index]

    price = _gag_units(action.track, action.level,
                       toon.track_exp.get(action.track, 0))

    if action.track == Track.TOON_UP:
        # What this gag can actually restore, not the party's whole
        # deficit and not a flat 40. The old cap sat below what any
        # attack scores -- damage alone runs 50-90 and a kill adds 60 --
        # so Toon-Up never reached the top `GREEDY_SHORTLIST` and was
        # cut before the stage that decides ever saw it.
        missing = sum(other.max_laff - other.laff
                      for i, other in enumerate(state.toons)
                      if i != index and other.laff > 0)
        try:
            heal = data.gag(action.track, action.level).heal_at(
                1.0, organic=toon.is_organic(action.track))
        except (NotImplementedError, ValueError, KeyError, TypeError):
            return float("-inf")
        # Laff is worth more than a point of cog damage -- the objective
        # prices it at `laff_weight` -- and this scorer has no objective
        # to read, so HEAL_VALUE carries the same intent.
        return HEAL_VALUE * float(min(missing, heal)) - price
    if action.track == Track.LURE:
        caught = (len(live) if action.target_index is None
                  else 1) if any(not c.status.lured for c in live) else 0
        return CHEAP_LURE_VALUE * caught - price
    if action.track == Track.TRAP:
        # A trap is worth the damage it will deal when something lures a
        # cog onto it -- conditional, but not small: a level 5 trap hits
        # for around 90.
        #
        # This was a flat 20.0, below what any attack scores, so the best
        # trap action ranked around 13th of the candidate pool while
        # `GREEDY_SHORTLIST` simulates the top 2. Measured: below the cut
        # in 39 of 39 decisions where a trap was held. Since
        # `greedy_plan` is also the rollout continuation, every position
        # was valued as though a trap would never be laid again -- the
        # same blindness Toon-Up had, and the thing the owner warned
        # about: undervalue Trap and you undervalue Lure with it.
        #
        # P(SPRING), rather than a flat discount. Three things have to
        # happen for a trap to pay, and all three are in the state:
        #
        #   * somebody holds a Lure -- otherwise the trap is a dead gag,
        #     and `can_still_damage` already treats the pair as one unit
        #   * that Lure lands, which is an accuracy number
        #   * the cog lives long enough to be lured onto it
        #
        # And the payoff is NOT the trap damage alone. [CONFIRMED] by
        # the owner: springing a trap knocks the cog OUT of the lure, so
        # the combo trades the rounds that cog would have spent asleep
        # for the trap's damage. That prevention is what `prevented`
        # prices elsewhere, so it is netted off here rather than
        # ignored -- a trap sprung on a cog that threatens little is
        # worth much more than one sprung on a Legal Eagle you could
        # have kept asleep.
        lure_levels = [key[1]
                       for other in state.toons if other.laff > 0
                       for key, count in other.gag_counts.items()
                       if key[0] == Track.LURE and count > 0]
        if not lure_levels:
            return -price
        try:
            damage = mechanics.calc_toon_damage(
                action.track, action.level,
                organic=toon.is_organic(action.track))
        except (NotImplementedError, ValueError):
            return 20.0 - price
        target = (state.cogs[action.target_index]
                  if action.target_index is not None
                  and 0 <= action.target_index < len(state.cogs)
                  else None)
        landed = min(damage, max(0, target.hp)) if target else damage
        # The lure this will consume, priced as the attacks that cog
        # would otherwise have skipped.
        forgone = 0.0
        if target is not None and not target.status.lured:
            threat = _cog_threat(target)
            # Rounds of sleep given up, from the lure that would spring
            # this trap. The CHEAPEST one the party holds, because that
            # is the one a sensible player spends on it: durations run
            # 2/2/3/3/4/4/8 by level, so springing a trap with a level 7
            # Presentation throws away eight rounds of a cog not
            # attacking, and nobody does that on purpose.
            #
            # This was a flat 2.0, which is right only for a level 1-2
            # lure and understates every other by up to four times.
            rounds = min(mechanics.lure_duration_rounds(level)
                         for level in lure_levels)
            forgone = HEAL_VALUE * threat * float(rounds)
        return TRAP_DISCOUNT * float(landed) - forgone - price

    try:
        damage = mechanics.calc_toon_damage(
            action.track, action.level, organic=toon.is_organic(action.track))
    except (NotImplementedError, ValueError):
        return float("-inf")

    targets = (live if action.target_index is None
               else [state.cogs[action.target_index]]
               if 0 <= action.target_index < len(state.cogs) else [])
    score = 0.0
    for cog in targets:
        if action.track == Track.DROP and cog.status.lured:
            continue        # always misses -- see `_playable`
        hit = damage
        if action.track in mechanics.KB_BONUS_TRACKS and cog.status.lured:
            hit += int(damage * mechanics.KB_BONUS_MULTIPLIER)
        score += min(hit, max(0, cog.hp))
        if hit >= cog.hp:
            score += CHEAP_KILL_BONUS
    return score - price


def _greedy_score(state: BattleState, trial, objective) -> float:
    """One action's worth: damage, kills and HEALING, less cost and waste.

    Healing was missing, and it cost more than it sounds. This function
    scored only damage landed, kills and lures, so a Toon-Up came out at
    `-10 * price` -- strictly negative -- and `greedy_plan` accepts
    nothing at or below zero. So greedy_plan could never choose a heal
    under any circumstances, and since `rollout_value` IS greedy_plan
    played forward, every position was valued as though the party never
    heals again.

    Measured over 30 building runs before the fix: 653 decisions where
    the acting toon held a Toon-Up gag, 398 of them with the party under
    60% laff, and 5 Toon-Ups thrown out of 743 gags.

    `_cheap_score` already had this right -- it credits Toon-Up
    explicitly and its docstring says why: "it must not be
    systematically blind to a track, or that track never reaches the
    shortlist". The shortlist was fine. The stage that actually decides
    threw the same track away.

    Laff restored is priced at `GREEDY_W["heal"]`. This docstring used
    to say `HEAL_VALUE`, "shared with the other two scorers so there is
    one number for what laff is worth rather than three" -- it is not
    shared. `HEAL_VALUE` is read only by `_cheap_score`; the three
    constants merely hold the same number, and the note above `QUICK_W`
    records that sharing the heal weight WAS tried and refuted (raising
    it to 12 gained the hybrid a point and cost the search two to
    three). docs/scoring.md lists all three.

    It also used to play one ALL-HIT round, the same assumption that lost
    the CEO in `_quick_score`, and it matters more here than the branch
    count suggests: `rollout_value` IS `greedy_plan` played forward, so
    an all-hit rollout values every position as though the party never
    misses. A trial is one toon throwing one gag, so this is two
    branches, not sixteen.
    """
    # Neither depends on how the dice fall, so they are computed once
    # rather than once per branch.
    wasted, scarcity = plan_waste(state, trial)
    # Price the action directly. This called `_spent`, which diffs every
    # toon's whole gag dictionary against the probe's -- forty-odd
    # lookups to rediscover a fact the caller already had, on a trial
    # where exactly one toon throws exactly one gag.
    price = 0.0
    for action in trial:
        if action is None:
            continue
        if action.fire:
            price += _fire_price(state.cogs_remaining)
        else:
            price += objective.gag_price(action.track, action.level,
                                         state.cogs_remaining)

    def leaf(hits, record) -> float:
        probe = state.clone()
        try:
            healed = simulator.apply_party_round(
                probe, list(trial), hits=hits, record=record)
        except (NotImplementedError, ValueError, KeyError):
            return float("-inf")

        # Capped at the headroom actually available, so healing a toon
        # who is nearly full is worth what it really restores rather than
        # the gag's nominal value. Overhealing should not look like value.
        restored = _restored(healed, state.toons)
        landed = _landed(state.cogs, probe.cogs)
        killed = _killed(state.cogs, probe.cogs)
        return (landed
                + GREEDY_W["heal"] * restored
                + GREEDY_W["kill"] * killed
                + GREEDY_W["prevent"] * prevented(state, probe)
                - GREEDY_W["price"] * price
                - GREEDY_W["waste"] * wasted * scarcity)

    return _expected_over_rolls(state, trial, leaf)


def rollout_value(state: BattleState, objective, rng,
                  model: Optional[TeammateModel] = None,
                  max_rounds: int = ROLLOUT_ROUNDS) -> float:
    """Value of `state` from playing it out, instead of estimating it.

    WHY THIS EXISTS, AND WHY IT IS THE DEFAULT HERE
    ----------------------------------------------
    `expectimax.heuristic_value` cannot rank party positions. Its
    features pool over the toons, so four maxed pouches pin
    `damage_budget_ratio` at its cap and everything scores near the
    ceiling. Measured over the successor states of three plans on a
    maxed four-toon position, 60 rollouts each:

        2 trap + group lure + group throw   leaf 98.03   87% ended
        2 Foghorn + 2 Aoogah                leaf 98.96   98% ended
        4 Foghorn                           leaf 96.73   95% ended

    A 2.3-point spread across positions differing by eleven points of
    *did you actually win*. At depth 1 that leaf is a constant, so the
    ranking falls entirely to `round_reward` and no continuation is
    visible -- which is fatal for exactly the strategies worth searching
    for, since Lure's whole payoff is in later rounds.

    A rollout cannot saturate, because it does not estimate anything: it
    plays until the battle is over and adds up what happened. The cost
    is that it is noisy and it measures the value of the position *under
    the rollout policy* (`greedy_plan`) rather than under best play.
    That is a real limitation, but a noisy signal beats a constant.

    It also needs no clamping. `fitted.value` is clamped into
    `expectimax._value_bounds` to keep star1 admissible; this search does
    not prune, so there is nothing to keep admissible and nothing is
    given up by letting the number run past +/-100.
    """
    current = state
    total = 0.0
    for _ in range(max_rounds):
        if current.is_terminal():
            break
        joint = greedy_plan(current, objective)
        nxt, _healed, _done = party_mod.step(
            current, joint[0], mode=Mode.COORDINATED, joint=joint, rng=rng)
        laff_lost = sum(max(0, before.laff - after.laff)
                        for before, after in zip(current.toons, nxt.toons))
        total += round_reward(
            objective, laff_lost, _spent(current, nxt),
            won=nxt.is_win(),
            lost=nxt.is_terminal() and not nxt.is_win(),
            toons_lost=sum(1 for b, a in zip(current.toons, nxt.toons)
                           if b.laff > 0 and a.laff <= 0))
        current = nxt
    return total


def evaluate(state: BattleState, depth: int = 1,
             mode: Mode = Mode.PICKUP,
             model: Optional[TeammateModel] = None,
             objective=None, samples: int = SAMPLES,
             per_track: int = PER_TRACK, max_plans: int = MAX_PLANS,
             leaf: str = "rollout",
             rng=random) -> Tuple[float, Optional[Sequence]]:
    """Estimated value of `state`, and the plan that achieves it.

    Returns (value, plan). In pickup mode the plan's first entry is your
    action and the rest are None; in coordinated mode it is the whole
    team's.
    """
    objective = objective or objective_mod.DEFAULT
    if state.is_terminal():
        return 0.0, None
    if depth <= 0:
        if leaf == "learned":
            from . import features as features_mod

            learned = policy.value(state, features_mod.extract(state))
            if learned is not None:
                return learned, None
            # No weights or no numpy: fall through rather than fail.
        if leaf in ("rollout", "learned"):
            return rollout_value(state, objective, rng, model), None
        return expectimax.heuristic_value(state), None

    best_value, best_plan = float("-inf"), None
    for plan in plans(state, mode, per_track, max_plans):
        # Charged once per plan, not per sample: waste is a property of
        # the choice, not of how the dice fell.
        waste = waste_penalty(objective, state, plan)
        returns: List[float] = []
        for _ in range(samples):
            nxt, _healed, _done = party_mod.step(
                state, plan[0], mode=mode, model=model,
                joint=list(plan) if mode is Mode.COORDINATED else None,
                rng=rng)
            laff_lost = sum(
                max(0, before.laff - after.laff)
                for before, after in zip(state.toons, nxt.toons))
            went_sad = sum(1 for before, after in zip(state.toons, nxt.toons)
                           if before.laff > 0 and after.laff <= 0)
            reward = round_reward(
                objective, laff_lost, _spent(state, nxt),
                won=nxt.is_win(),
                lost=nxt.is_terminal() and not nxt.is_win(),
                toons_lost=went_sad,
                cogs_remaining=state.cogs_remaining)
            future, _p = evaluate(nxt, depth - 1, mode, model, objective,
                                  samples, per_track, max_plans, leaf, rng)
            returns.append(reward + future)
        # Mean, less a penalty for how widely the samples scatter. A
        # risk-neutral search cannot express "clears by 15 rather than
        # by 3" or "hedge in case the Lure misses" -- both are claims
        # about the spread, and averaging discards exactly that.
        mean = sum(returns) / len(returns)
        risk = getattr(objective, "risk_aversion", 0.0)
        if risk and len(returns) > 1:
            var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            mean -= risk * (var ** 0.5)
        value = mean - waste
        if value > best_value:
            best_value, best_plan = value, plan
    if best_plan is None:
        if leaf == "rollout":
            return rollout_value(state, objective, rng, model), None
        return expectimax.heuristic_value(state), None
    return best_value, best_plan


def best_plan(state: BattleState, **kwargs) -> Optional[Sequence]:
    return evaluate(state, **kwargs)[1]


def describe(plan) -> str:
    if not plan:
        return "(no plan)"
    return ", ".join("sit out" if a is None else a.describe() for a in plan)
