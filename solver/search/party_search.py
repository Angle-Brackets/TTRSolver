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

WHY THIS PLAYOUTS_PER_PLAN INSTEAD OF ENUMERATING
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

from .. import data
from .. import mechanics
from .. import outcomes as outcomes_mod
from .. import party as party_mod
from .. import simulator
from .. import sos as sos_mod
from ..party import Mode, TeammateModel
from ..data import gags as gags_mod
from ..data.gags import POUCH_EXEMPT_LEVEL
from ..state import Action, BattleState, Track
from . import expectimax
from . import features as features_mod
from . import objective as objective_mod
from . import policy
from . import weights


# ---------------------------------------------------------------------
# Enumerating candidate plans
# ---------------------------------------------------------------------

def candidates(state: BattleState, toon_index: int,
               per_track: int = weights.CANDIDATES_PER_TRACK) -> List[Action]:
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
          per_track: int = weights.CANDIDATES_PER_TRACK,
          max_plans: int = weights.MAX_PLANS) -> List[Sequence[Optional[Action]]]:
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
    # This is the same lesson as CANDIDATES_PER_TRACK, learned again one level up.
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
    # Keep the arithmetically best QUICK_SCORED_PER_TRACK per stratum, NOT the
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

    # STRATIFY BY TRACK SIGNATURE, then take each family's own best.
    #
    # The per-family floor is the point. Any shortlist is a reduction and
    # can silently delete the right answer -- four of this project's five
    # silent-deletion bugs lived in this function -- and giving every
    # combination of tracks its own bucket means a family can only be
    # lost by being empty, never by being out-scored wholesale.
    #
    # `_cheap_score` is a weak ranker for this: measured on 375 held-out
    # positions by regret@6, it scores 9.93 against 12.09 for choosing at
    # random. A trained ranker did far better in isolation (3.22) and
    # still lost in search; see docs/scoring.md, which keeps the numbers
    # and the label-noise diagnosis. The stratification is what stops the
    # weak ranker being fatal.
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
        cheap.setdefault(signature, []).append((arith[index], combo))

    buckets: Dict[tuple, List] = {}
    for signature, rows in cheap.items():
        by_arith = sorted(rows, key=lambda row: -row[0])
        buckets[signature] = [row[1] for row in by_arith[:weights.QUICK_SCORED_PER_TRACK]]

    # Order within a stratum by the real scorer. `_cheap_score` chose
    # which plans got in; `_quick_score` decides what order they leave
    # in, because it is the one that simulates the round.
    strata: Dict[tuple, List] = {}
    for signature, bucket in buckets.items():
        rows = [(_quick_score(state, combo), combo) for combo in bucket]
        strata[signature] = sorted(rows, key=lambda row: -row[0])

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


# ---------------------------------------------------------------------
# Reading a board
# ---------------------------------------------------------------------

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

    return outcomes_mod.expected_hit_damage(cog)


def latent_incoming(state: BattleState) -> float:
    """What the field threatens once the sleepers WAKE.

    `expected_incoming` skips a lured cog because it skips its attack,
    which is right for "what lands next round" and wrong for "am I going
    to survive this fight". A LURE IS A REPRIEVE, NOT SAFETY: the cogs
    are still there and still swinging in three rounds' time.

    This exists for `survival_rounds`, where the difference decided
    something real. With the whole field asleep, incoming reads 0, and a
    ratio of laff to zero saturated the term at `SURVIVAL_CAP` -- so 120
    laff and 4 laff both scored 4.00 and the one term that can see a
    toon about to die was blind exactly during the window where healing
    is safe. [OWNER] "you want the cogs lured and then you want to heal";
    the solver could not tell the difference.
    """
    return sum(_cog_threat(cog) for cog in state.active_cogs())


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


def prevented(before: BattleState, after: BattleState) -> float:
    """Incoming damage a round removed, by luring or by killing.

    REMODELLED because the rule underneath it changed: a landed attack
    wakes a lured cog (`mechanics.LURE_ENDS_ON_DAMAGE`), so a Lure buys
    quiet only on the cogs the party does not get round to hitting, not
    `lure_rounds_remaining` rounds on all of them. The old version
    multiplied the whole difference by one mean `lure_rounds_remaining`,
    defensible only while a lured cog stayed asleep through damage.

    (Three earlier corrections to the old version were measured under
    that stale lure rule, where the mean multiplier was roughly right
    and each correction really was noise -- that evidence is void now;
    this remodel ships together with a retrain and refit, which is what
    the old note required before trying again.)

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
    # PER-COG HORIZON: `reach` is one number for every sleeper, but the
    # first is woken next round and the last after `asleep / standing`
    # rounds. Staggering credits a four-cog lure for 1+2+3+4 rounds of
    # quiet rather than 4+4+4+4 -- less generous in total and better
    # shaped, since the cog about to die was never staying asleep.
    # Ordered by remaining health (finish the cheap ones, leave the Mr.
    # Hollywood asleep). `SLEEPERS_WAKE_IN_TURN` turns it off.
    order = {}
    if weights.SLEEPERS_WAKE_IN_TURN:
        sleepers = sorted(
            (c for c in after.active_cogs() if c.status.lured),
            key=lambda c: c.hp + (c.max_hp if c.status.suited else 0))
        for rank, cog in enumerate(sleepers, start=1):
            order[id(cog)] = max(1.0, rank / float(standing))

    if not weights.LURE_IS_SPENT_ON_SLEEPERS:
        # LEAVING THEM ASLEEP IS THE STRATEGY, not a failure to get
        # round to them: [OWNER] lure the field with a Presentation,
        # never touch the sleepers, and fight the cogs that walk in to
        # replace the ones you kill -- three cogs out of the fight for
        # the whole duration. `reach` prices the opposite plan (working
        # through the sleepers yourself), undercrediting the gag a solo
        # VP is built around to about a quarter of what it delivers.
        #
        # STILL PLAYS WORSE, measured: solo VP, 200 runs/cell, five
        # slips, capped vs full at 8/12/20 cogs a round -- 81.5% vs
        # 67.0% (p<0.001), 20.0% vs 16.5% (p=0.32), 0.0% vs 0.0%.
        # Fourteen points worse where there's signal, so the cap stays;
        # what's refuted is this crude removal of it, not the owner's
        # strategy. The two don't conflict: `reach = inf` over-credits
        # EVERY lure, including cogs the plan is about to attack itself,
        # because a one-round scorer can't distinguish "left alone" from
        # "next" -- that needs the plan's own targets, which neither
        # setting reads. Drawing that distinction properly is open.
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
            if not (weights.LURED_KILL_SILENCES_NOTHING and old.status.lured):
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
        elif (weights.WAKE_COSTS_PREVENTED and old.status.lured
                and not new.status.lured):
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


def survival_rounds(state: BattleState, incoming=None) -> float:
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

    Capped at `SURVIVAL_CAP` rounds: uncapped, a maxed toon on a quiet
    board scores enormous survival and drowns every other term, and a
    plan buying a fifth round of survival over a fourth is no longer a
    life-or-death choice.

    `incoming` OVERRIDES what the board says is coming, and the caller
    in `_quick_score` always passes the PRE-PLAN figure. Measured, solo
    buildings, 200 runs a cell on two seed blocks: letting it move with
    the plan cost 26.0% -> 10.0% and 27.0% -> 14.5% at weight 400,
    p<0.001 both blocks, because killing or luring a cog lowers incoming
    and so this term rewarded it a second time. `prevented` and the
    damage terms already price exactly that. Held fixed, the term varies
    only with LAFF, which is the one thing no other term can see, so it
    cannot reorder gag choices while still making a heal visible.
    """
    standing = [t for t in state.toons if t.laff > 0]
    if not standing:
        return 0.0
    incoming = expected_incoming(state) if incoming is None else incoming
    if incoming <= 0 and weights.LURE_IS_A_REPRIEVE:
        # Asleep is not safe -- see `latent_incoming`. Measured against
        # what wakes up, so a dying toon under a lure still reads as
        # dying. Only a board with nothing left alive falls through to
        # the cap.
        incoming = latent_incoming(state)
    if incoming <= 0:
        # Nothing is swinging -- every plan survives, so this cannot
        # discriminate and should not be allowed to dominate.
        return weights.SURVIVAL_CAP
    laff = min(t.laff for t in standing)
    return min(weights.SURVIVAL_CAP, laff / incoming)


def past_the_death_line(state: BattleState) -> float:
    """Standing toons that one round of the WOKEN field would knock out.

    [OWNER] "if the expected incoming from the cogs, assuming they are
    all unlured, is greater than the current HP, shouldn't we heal" --
    and "we should heal or kill". This is that test, and it is a
    deadline rather than a danger: the lure is running out, and when it
    does, this toon dies to one round.

    `toons_at_risk` deliberately SKIPS a lured cog, because it answers
    "does this plan stop me dying next round" and luring is one of the
    ways to make that true. Both questions are worth asking and they
    give opposite answers on a sleeping field, so this is a second
    function rather than a flag on that one.

    Post-plan, which is what makes it "heal OR kill": healing lifts the
    toon over the line, and killing or firing enough cogs drops the line
    under the toon. A gag that does neither leaves it standing, which is
    the plan the owner is objecting to.
    """
    standing = [t for t in state.toons if t.laff > 0]
    if not standing:
        return 0.0
    worst = 0
    for cog in state.active_cogs():
        try:
            worst += outcomes_mod.worst_case_damage(cog)
        except NotImplementedError:      # a [TODO] attack table
            pass
    return sum(1.0 for t in standing if t.laff <= worst)


def toons_at_risk(state: BattleState) -> float:
    """Standing toons a round of incoming damage could knock out.

    RE-SWEPT after the fix below; the weight stays 0.0, but for a
    different and more useful reason. Solo VP, 200 runs/cell: risk
    weight 0/5/15/40 all read 29.0%/0.0% at 12/20 cogs a round -- not
    one game changed, +0/-0 on identical seeds.

    The function is NOT dead this time (non-zero in 61 of 168 sampled
    VP positions, discriminating cleanly between plans), it just arrives
    too late to matter: risk is zero for every candidate while laff is
    healthy, so it's a constant that can't move an argmax, and it only
    separates plans once the toon is already low -- by which point a
    solo VP is lost regardless of the pick. Flat in the winnable region,
    decisive in the lost one, changes nothing about the outcome.

    That points at prevention instead: `QUICK_W["prevent"]` values
    removing incoming damage the same at 100 laff as at 20, when the
    second is worth far more. Scaling prevention by how close to death
    the toon is would act early, while the game is still winnable --
    the thing to try next. Nothing in any scorer charges for losing a
    toon outright (their whole pouch leaves the run, every later floor
    in a building), only indirectly through prevention they no longer
    contribute.

    The earlier zero was a measurement bug, not a result: this used to
    divide an already-probability-weighted `expected_incoming` again by
    toons standing, asking whether a toon could survive their SHARE of
    the average -- which was non-zero in 0 of 2000 sampled facility
    starts (zero even in a hand-built position where every toon is one
    group attack from sad), so a 0/2/5/10 sweep moved nothing because no
    weight moves a constant. The old ES result that zeroed
    `QUICK_W["risk"]` was evidence about this function, not about risk.

    Fixed to the rule `features.one_hit_from_death` already uses:
    `outcomes.worst_case_damage` per cog, summed, against the smallest
    laff -- except a LURED cog is skipped, since it doesn't swing, so
    luring visibly lowers the count and the scorer can finally see it.
    """

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
    the cog has left, discounted by weights.TRAP_DISCOUNT, and only when
    somebody is holding a Lure to spring it. A trap with nothing behind
    it really is a wasted gag and should still score zero.

    Deliberately NOT netting off the lure it will consume, which
    `_cheap_score` does. There the trap is being compared against
    attacking that cog directly; here the plan has already been played
    and the question is only what the board is now worth.
    """

    holds_lure = any(key[0] == Track.LURE and count > 0
                     for toon in after.toons if toon.laff > 0
                     for key, count in toon.gag_counts.items())
    if not holds_lure:
        return 0.0

    total = 0.0
    for old, new in zip(before.cogs, after.cogs):
        if new.status.is_dead or not new.status.trapped:
            continue
        if old.status.trapped:
            continue          # already armed before this round
        if new.status.trap_level is None and new.status.trap_damage is None:
            continue
        if new.status.trap_damage is not None:
            damage = int(new.status.trap_damage)   # an SOS trap
        else:
            try:
                damage = mechanics.calc_toon_damage(
                    Track.TRAP, new.status.trap_level,
                    organic=new.status.trap_organic)
            except (NotImplementedError, ValueError, KeyError):
                continue
        total += weights.TRAP_DISCOUNT * float(min(damage, max(0, new.hp)))
    return total


# ---------------------------------------------------------------------
# The fast scorer
# ---------------------------------------------------------------------
#
# `_quick_score` is what `hybrid.climb` judges a plan with, and what
# every offline evaluation in this project actually runs.

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


def _gag_units(track, level: int, unlocked: int, held=None) -> float:
    """What one gag costs the two fast scorers, in their own units.

    `level + weights.SCARCITY_UNITS / carry_limit` -- a level term plus a
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
    if weights.SCARCITY_USES_HELD_COUNT and held:
        limit = max(1, min(int(held), limit))
    units = float(level) + weights.SCARCITY_UNITS / limit
    if weights.LAST_COPY_UNITS and limit <= 1:
        # The only one you have. Keyed on the SAME `limit` the scarcity
        # term uses, so it follows `SCARCITY_USES_HELD_COUNT`: with that
        # on it means "last one in the pouch", with it off "a gag you
        # can only ever carry one of".
        units += weights.LAST_COPY_UNITS
    return units


def _fire_price(cogs_remaining: int, floor: bool = False) -> float:
    """What a pink slip costs a scorer, per cog still to come.

    `floor=True` adds `FIRE_FLOOR`, which only `_score_leaf` charges --
    see `FIRE_FLOOR` for why the callers differ. Reads the module
    globals at call time, so a test that patches `FIRE_PRICE` or
    `FIRE_FLOOR` still reaches every scorer.
    """
    return weights.FIRE_PRICE * float(cogs_remaining) + (weights.FIRE_FLOOR if floor
                                                 else 0.0)


def _roll_groups(plan) -> Dict[int, tuple]:
    """Toon index -> the shared die that toon's gag resolves on.

    Accuracy is rolled per track per target, so two toons throwing the
    same track at the same cog land or miss TOGETHER. That correlation
    is the whole reason this mapping exists rather than a per-toon hit
    probability: treating the two rolls as independent lets a plan hedge
    in a way the game does not allow, and overvalues stacking a track on
    one target -- the error `apply_party_round` was written to avoid.

    Fires, passes and SOS calls never roll, so they are absent.

    THE SOS EXEMPTION IS NOT COSMETIC. An SOS cannot miss, and its
    accuracy is independent of the party's: call Moe Zart while another
    toon throws an Elephant Trunk and the Trunk may miss while Moe Zart
    does not, though both are Sound and both hit every cog. Keyed into
    the same group they would share a die, and the SOS would fail
    whenever the gag did.
    """
    groups: Dict[int, tuple] = {}
    for index, action in enumerate(plan):
        if (action is None or action.is_pass or action.fire
                or action.sos is not None):
            continue
        groups[index] = (action.track, action.target_index)
    return groups


def _score_leaf(state: BattleState, plan, hits, record=None,
                objective=None) -> float:
    """Score one fixed outcome of the round -- who hit and who missed.

    `objective`, when given, adds `waste_penalty` on top of the fixed
    `QUICK_W` terms. See `_quick_score`.
    """

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
    if weights.HEAL_DISCOUNTS_INCOMING and restored > 0:
        # What the heal KEEPS, not what it pours in. See the weight.
        restored = max(0.0, restored - expected_incoming(state))
    landed = _landed(state.cogs, probe.cogs)
    killed = _killed(state.cogs, probe.cogs)
    # TWO PRICES, NOT ONE. `gag_price` is the pouch; `spend_price` is the
    # consumables. They used to share a running total and therefore a
    # single multiplier, so turning `QUICK_W["price"]` down to make the
    # solver freer with gags also made pink slips and SOS cards free and
    # nullified FIRE_PRICE, FIRE_FLOOR and SOS_PRICE in one move. That
    # is not a tuning knob, it is a trapdoor -- see docs/scoring.md.
    gag_price = 0.0
    for track, level, count, unlocked in _spent(state, probe):
        held = sum(t.gag_counts.get((track, level), 0) for t in state.toons)
        gag_price += count * _gag_units(track, level, unlocked, held=held)
    # Same horizon scaling the real reward applies. This decides which
    # plans are ever sampled, so ranking here at horizon 0 would drop
    # the conserving plan before anything could evaluate it -- the
    # shortlist-truncation bug this file has had three times already.
    gag_price *= 1.0 + objective_mod.Objective().horizon_cost * float(
        state.cogs_remaining)
    # The horizon scales the POUCH only, and always did: slips and cards
    # are added after it. Kept that way by splitting here rather than
    # earlier.
    spend_price = 0.0
    # A slip spent now is one not held for the cogs still to come, so it
    # costs what is still coming -- plus a floor, because "nothing is
    # coming" and "nobody told us what is coming" are different states
    # and this term could not tell them apart.
    #
    # THE PANEL USED TO NEVER SET `cogs_remaining`, so it was 0 on every
    # live board -- and a slip was therefore free in live play, always.
    # A boss fight now sets it (`solver.live.boss`); a building or a
    # facility still cannot, because its next floor is not something a
    # player can see. The owner watched it
    # spend one on a level 1 Cold Caller with 6 hp while holding a
    # pouch full of gags that would have killed it.
    #
    # The floor is what a slip is worth against the cog it could have
    # been saved for, rather than against the fight's remaining length,
    # so it applies even in a genuine last battle. `FIRE_FLOOR` at zero
    # restores the old behaviour exactly.
    spend_price += _fire_price(state.cogs_remaining,
                               floor=True) * _fires_spent(state, probe)
    # An SOS is charged the same way and far more dearly. [OWNER] a
    # last resort, or for a very good move -- which is what a price
    # says: the card has to beat the alternative BY MORE than this.
    #
    # Read off the PLAN rather than by diffing inventories, because
    # unlike a slip an SOS may be spent by any seat and the plan
    # already names which.
    sos_calls = sum(1 for a in plan
                    if a is not None and getattr(a, "sos", None))
    if sos_calls:
        spend_price += sos_mod.SOS_PRICE * sos_calls
    # REACH THROWN AWAY: the wasted share of a card's price, or of a
    # group gag's. See `simulator.wasted_reach`.
    for seat, action in enumerate(plan):
        waste = simulator.wasted_reach(state, action)
        if not waste:
            continue
        if action.sos:
            spend_price += sos_mod.SOS_PRICE * waste
        elif seat < len(state.toons):
            toon = state.toons[seat]
            gag_price += waste * _gag_units(
                action.track, action.level,
                toon.track_exp.get(action.track, 0),
                held=toon.gag_counts.get((action.track, action.level), 0))
    return (landed
            + weights.QUICK_W["heal"] * restored
            + weights.QUICK_W["armed"] * armed_credit(state, probe)
            + weights.QUICK_W["kill"] * killed
            + (weights.QUICK_W["kill_threat"] * killed_threat(state, probe)
               if weights.QUICK_W["kill_threat"] else 0.0)
            + weights.QUICK_W["prevent"] * prevented(state, probe)
            - (weights.QUICK_W["waste"] * _waste_fraction(state, plan)
               if weights.QUICK_W["waste"] else 0.0)
            - (waste_penalty(objective, state, plan)
               if objective is not None else 0.0)
            - (weights.QUICK_W["risk"] * toons_at_risk(probe)
               if weights.QUICK_W["risk"] else 0.0)
            - (weights.QUICK_W["deadline"] * past_the_death_line(probe)
               if weights.QUICK_W["deadline"] else 0.0)
            # `expected_incoming(state)`, not of `probe`: see
            # `survival_rounds`. With the board's own figure this term
            # double-counts damage prevention and reorders gag choice.
            + (weights.QUICK_W["survive"] * survival_rounds(
                probe, incoming=expected_incoming(state))
               if weights.QUICK_W["survive"] else 0.0)
            - weights.QUICK_W["price"] * gag_price
            - weights.QUICK_W["spend"] * spend_price)


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
        if guess < weights.MIN_LEAF_PROB:
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

    NO SHIPPED CALLER PASSES `objective`: `plans`, `hybrid._judge` (what
    `hybrid.climb` scores with) and `hybrid.best_plan` all call this with
    two arguments, so
    `_score_leaf`'s `waste_penalty` branch is unreachable in practice --
    overkill is charged only through `QUICK_W["waste"]` (0.0). Recorded
    in docs/scoring.md rather than fixed here, since turning it on
    changes numbers that were all measured as they stand.

    `objective` is optional and off by default on purpose, not by
    omission: it steers this ranker but not the policy that proposes to
    it, so `survive` and `glass cannon` would still shortlist the same
    moves and merely order them differently -- not worth it while the
    menu came only from the policy. `PROBE_CHEAPEST_KILL` now puts the
    cheap option there regardless, so a ranker using it could act on it.
    What it buys over `QUICK_W["waste"]`: `waste_penalty` scales by
    SCARCITY as well as wasted fraction, so burning one of three Grand
    Pianos into a 6hp cog costs far more than spilling a Seltzer there
    -- a flat fraction (swept and failed twice) can't say that.

    Used to play one ALL-HIT round, which is what lost the CEO: nearly
    true in a cog building (accuracy 70-95%, barely varying by track, so
    damage and expected damage agree), but against level 13-14 cogs
    (51-95% accuracy) the all-hit score prefers the biggest printed
    number, reliably the least likely to land. Measured on 200 CEO
    sides, 0 leftovers: 69.5% -> 75.0% cleared (+24/-13, p=0.049), cog
    buildings unchanged (where the weights were fitted).

    Still looks one step past the round for a trap, and only a trap --
    see `armed_credit`.
    """
    return _expected_over_rolls(
        state, plan,
        lambda hits, record: _score_leaf(state, plan, hits, record,
                                         objective))


# ---------------------------------------------------------------------
# Legality, waste and reward
# ---------------------------------------------------------------------

def _playable(state: BattleState, plan) -> bool:
    """Can each toon actually throw what the plan gives them?

    A multiset says what gets thrown, not who throws it, so the same
    gag can land on a toon who has none left -- or twice on a toon
    holding one.
    """

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
        if action.fire:
            continue          # spends a slip, not a gag
        if action.sos is not None:
            # Spends a CARD, not a gag. Without this an SOS looks like a
            # gag the toon holds none of -- no track, no level -- and
            # the plan is rejected as unplayable before it is ever
            # scored. Which is exactly what happened: every SOS came
            # back at -inf.
            if toon.sos_held(action.sos) <= 0:
                return False
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
        #
        # AN SOS CALL TOO, which this missed. It has no track and
        # `is_pass` is False for it, so it reached `calc_toon_damage(None,
        # 0)` and raised KeyError -- and `hybrid._judge` catches that and
        # falls back to its one-round score. So on any board where a card
        # was held, the lookahead silently never ran: `greedy_plan` would
        # consider calling one, this raised, and every plan was scored as
        # if nothing came after it. A card is priced by `SOS_PRICE`, not
        # by overkill, so there is nothing here to charge it for.
        if (action is None or action.is_pass or action.fire
                or getattr(action, "sos", None)
                or action.track in (Track.TOON_UP, Track.LURE,
                                    Track.TRAP)):
            continue
        try:
            dmg = mechanics.calc_toon_damage(
                action.track, action.level,
                organic=toon.is_organic(action.track, action.level))
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


def greedy_plan(state: BattleState, objective) -> List[Optional[Action]]:
    """A decent action for every toon, chosen rather than sampled.

    NOT `SensiblePrior`, which it used to be: that is a model of
    *people* (what a stranger is likely to throw), right for PICKUP
    teammates (you can't control them, so a distribution is the correct
    object) but wrong for the ROLLOUT continuation, which estimates the
    value of a position under *good* play, not average play. A
    stranger-model undervalues any line whose payoff needs
    follow-through -- every Lure strategy there is, and the mechanism
    behind "no Lure strategy ever appears" in docs/party-strategy.md --
    because the plan was scored on a continuation that would not carry
    it out.

    So this takes the best action it can see one round ahead under the
    *objective the search is actually optimising*: damage landed where
    needed, cogs killed, minus cost and waste. Greedy and myopic, and
    still a much better proxy for "played well from here" than a guess
    about strangers.

    Not free: a rollout now scans each toon's candidate list per round
    instead of one weighted draw, which is why `ROLLOUT_ROUNDS` stays
    modest.
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
        shortlist = pool[:weights.GREEDY_SHORTLIST]
        seen_tracks = {a.track for a in shortlist}
        for action in pool:
            if len(shortlist) >= weights.GREEDY_SHORTLIST + weights.TRACK_PROBES:
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

    live = [cog for cog in state.cogs if not cog.status.is_dead]
    if not live:
        return 0.0

    # A pass spends nothing and achieves nothing, so it scores zero --
    # below any productive action, above one that wastes a gag. That
    # ordering is the whole point of offering it. Checked before the
    # price lookup, which would ask `data.gag(None, 0)`.
    if action.is_pass:
        return 0.0

    if action.sos is not None:
        # Scored by playing it, since the shapes are too different to
        # price by formula -- a heal, a field lure and a mass trap have
        # no common currency. `_quick_score` does the same thing by
        # simulating the round.
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
        return removed + weights.QUICK_W["kill"] + _cog_threat(target) - held

    toon = state.toons[index]

    price = _gag_units(action.track, action.level,
                       toon.track_exp.get(action.track, 0),
                       held=toon.gag_counts.get(
                           (action.track, action.level), 0))

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
                1.0, organic=toon.is_organic(action.track, action.level))
        except (NotImplementedError, ValueError, KeyError, TypeError):
            return float("-inf")
        # Laff is worth more than a point of cog damage -- the objective
        # prices it at `laff_weight` -- and this scorer has no objective
        # to read, so LAFF_POINT_VALUE carries the same intent.
        return weights.LAFF_POINT_VALUE * float(min(missing, heal)) - price
    if action.track == Track.LURE:
        caught = (len(live) if action.target_index is None
                  else 1) if any(not c.status.lured for c in live) else 0
        return weights.CHEAP_LURE_VALUE * caught - price
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
                organic=toon.is_organic(action.track, action.level))
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
            forgone = weights.LAFF_POINT_VALUE * threat * float(rounds)
        return weights.TRAP_DISCOUNT * float(landed) - forgone - price

    try:
        damage = mechanics.calc_toon_damage(
            action.track, action.level, organic=toon.is_organic(action.track, action.level))
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
            score += weights.CHEAP_KILL_BONUS
    return score - price


def _greedy_score(state: BattleState, trial, objective) -> float:
    """One action's worth: damage, kills and HEALING, less cost and waste.

    Healing was missing, and it cost more than it sounds: this function
    scored only damage, kills and lures, so a Toon-Up came out at
    `-10 * price` (strictly negative) and `greedy_plan` accepts nothing
    at or below zero -- so greedy_plan could never choose a heal, and
    since `rollout_value` IS greedy_plan played forward, every position
    was valued as though the party never heals again. Measured over 30
    building runs before the fix: 653 decisions where the acting toon
    held a Toon-Up, 398 with the party under 60% laff, and 5 Toon-Ups
    thrown out of 743 gags. `_cheap_score` already credited Toon-Up
    explicitly; the shortlist was fine, the stage that decides threw the
    track away.

    Laff restored is priced at `GREEDY_W["heal"]` -- not shared with
    `LAFF_POINT_VALUE` (read only by `_cheap_score`) or `QUICK_W["heal"]`;
    the three constants merely hold the same number by choice. Sharing
    the weight for real was tried and refuted (raising it to 12 gained
    the hybrid a point and cost the search two to three). docs/scoring.md
    lists all three.

    Also used to play one ALL-HIT round, the same assumption that lost
    the CEO in `_quick_score`, and it matters more here: `rollout_value`
    IS `greedy_plan` played forward, so an all-hit rollout values every
    position as though the party never misses. A trial is one toon
    throwing one gag, so this is two branches, not sixteen.
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
                + weights.GREEDY_W["heal"] * restored
                + weights.GREEDY_W["kill"] * killed
                + weights.GREEDY_W["prevent"] * prevented(state, probe)
                - weights.GREEDY_W["price"] * price
                - weights.GREEDY_W["waste"] * wasted * scarcity)

    return _expected_over_rolls(state, trial, leaf)


def rollout_value(state: BattleState, objective, rng,
                  model: Optional[TeammateModel] = None,
                  max_rounds: int = weights.ROLLOUT_ROUNDS) -> float:
    """Value of `state` from playing it out, instead of estimating it.

    `expectimax.heuristic_value` cannot rank party positions: its
    features pool over the toons, so four maxed pouches pin
    `damage_budget_ratio` at its cap and everything scores near the
    ceiling. Measured over the successors of three plans on a maxed
    four-toon position, 60 rollouts each: leaf values of 98.03/98.96/
    96.73 span 2.3 points while the plans actually finish 87%/98%/95% of
    the time -- at depth 1 that leaf is constant, so ranking falls
    entirely to `round_reward` with no continuation visible, which is
    fatal for exactly the strategies worth searching for (Lure's whole
    payoff is in later rounds).

    A rollout can't saturate, because it doesn't estimate anything: it
    plays to the end and adds up what happened. The cost is noise, and
    it measures value *under the rollout policy* (`greedy_plan`) rather
    than best play -- a real limitation, but a noisy signal beats a
    constant.

    Needs no clamping either: `fitted.value` is clamped into
    `expectimax._value_bounds` to keep star1 admissible, but this search
    doesn't prune, so nothing is given up by letting the number run past
    +/-100.
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


# ---------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------

def evaluate(state: BattleState, depth: int = 1,
             mode: Mode = Mode.PICKUP,
             model: Optional[TeammateModel] = None,
             objective=None, samples: int = weights.PLAYOUTS_PER_PLAN,
             per_track: int = weights.CANDIDATES_PER_TRACK, max_plans: int = weights.MAX_PLANS,
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


