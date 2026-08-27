"""Measure how long a Lure actually lasts in Realms.

    python -m solver.live.realms_lurewatch --seconds 240

WHY THIS EXISTS. Two claims got made about lure and only one of them is
evidenced.

  1. NOTHING IN THE DC CARRIES LURE DURATION. This is solid: the whole
     165KB file contains no field named for lure anywhere outside
     `setMembers`' untyped slots, and `DistributedSuitBase` publishes
     only DNA, level, HP, skelecog, revives and virtual. Grep-checked,
     not remembered.

  2. So the remaining rounds are COUNTED -- the gag that landed, minus
     the rounds since. That arithmetic rests on two things nobody has
     checked: that entering `PlayMovie` is exactly one round, and that
     a Lure's duration in Realms matches the number in OUR table.

The second is doubtful on its face. `CLAUDE.md` records that the
QED1224 guide was caught wrong on Lure durations specifically, because
TTR rebalanced them -- and Realms is the OTHER branch of that split, so
it plausibly still has the pre-rebalance numbers. Computing "TTR
duration minus rounds elapsed" in a Realms fight would then be wrong in
Realms, and wrong in the optimistic direction half the time.

This measures it instead. It watches a battle, counts movies, and
reports how many rounds each cog spent in `suits_lured` after a Lure of
a known level landed on it. That is the duration, observed.

WHAT THE ANSWER MAY AND MAY NOT BE USED FOR. It is a measurement of
Realms, so it may make the Realms harness self-consistent and it may
NOT go anywhere near `solver/data/` -- see `docs/realms.md`. If it
disagrees with our table that is a fact about the two games, not a bug
in the table.
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, Optional

from . import realms as realms_mod


def _describe_lure(level: Optional[int]) -> str:
    if level is None:
        return "unknown Lure"
    try:
        from ..data import gags as gags_mod
        from ..state import Track

        gag = gags_mod.gag(Track.LURE, level)
        return f"{gag.display} (Lure {level}, {gag.rounds()} rounds in TTR)"
    except Exception:                   # pragma: no cover
        return f"Lure {level}"


def main(argv=None) -> int:             # pragma: no cover - needs a game
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=float, default=240.0)
    parser.add_argument("--dir", help="Realms install directory")
    args = parser.parse_args(argv)

    try:
        index = realms_mod.DCIndex(override=args.dir)
        listener = realms_mod.RealmsListener(index=index)
        listener.connect()
    except realms_mod.RealmsError as exc:
        print(f"  {exc}")
        return 1
    listener.start()
    print(f"  attached {realms_mod.MD_HOST}:{realms_mod.MD_PORT}")
    print("  go and Lure a cog; every round is reported\n")

    # The stream carries CHANGES, so anything generated before attaching
    # has never been described. Ask once up front, then keep asking: a
    # battle starting later brings cogs that have been walking the
    # street since before we connected.
    time.sleep(3.0)
    listener.refresh_all()
    listener.refresh_battle_members()
    next_refresh = time.time() + 5.0

    # cog doId -> (level, round it landed, rounds seen lured)
    watching: Dict[int, list] = {}
    last_round = -1
    last_lured = set()
    end = time.time() + args.seconds

    heartbeat = 0.0
    while time.time() < end:
        if time.time() >= next_refresh:
            listener.refresh_all()
            listener.refresh_battle_members()
            next_refresh = time.time() + 5.0

        battles = listener.battles()
        if len(battles) != 1:
            # SAY SOMETHING WHILE WAITING. A tool that prints nothing is
            # indistinguishable from a broken one, which is exactly how
            # the missing `DistributedBattleBase` presented: no output,
            # no error, and no way to tell which of the two it was.
            if time.time() >= heartbeat:
                heartbeat = time.time() + 5.0
                note = "  (walk into a cog)" if not battles else ""
                print(f"  waiting: {len(battles)} battles, "
                      f"{len(listener.store)} objects, "
                      f"{listener.datagrams} datagrams{note}")
            time.sleep(0.4)
            continue
        battle = battles[0]
        members = realms_mod.parse_members(battle.get("setMembers"))
        if members is None:
            time.sleep(0.4)
            continue

        rounds = listener.battle_rounds.get(battle.do_id, 0)
        lured = set(members.lured_suits())

        if rounds != last_round or lured != last_lured:
            state = battle.get("setState")
            name = state[0] if isinstance(state, (tuple, list)) else state
            print(f"  round {rounds:<3} state={name!r:<16} "
                  f"lured={sorted(lured)} traps={members.suit_traps!r}")

            for do_id in lured - last_lured:
                age = listener.lure_age(do_id)
                level = None if age is None else age[0]
                watching[do_id] = [level, rounds, 0]
                print(f"    -> cog {do_id} asleep on {_describe_lure(level)}")

            for do_id in list(watching):
                if do_id in lured:
                    watching[do_id][2] = rounds - watching[do_id][1]
                elif do_id in last_lured:
                    level, started, _ = watching.pop(do_id)
                    lasted = rounds - started
                    expected = ""
                    if level is not None:
                        try:
                            from ..data import gags as gags_mod
                            from ..state import Track
                            ours = gags_mod.gag(Track.LURE, level).rounds()
                            verdict = "AGREES" if lasted == ours else "DIFFERS"
                            expected = (f"  [our table says {ours} -> "
                                        f"{verdict}]")
                        except Exception:
                            pass
                    print(f"    <- cog {do_id} woke after {lasted} "
                          f"round(s){expected}")

            last_round, last_lured = rounds, set(lured)
        time.sleep(0.3)

    listener.close()
    print(f"\n  {listener.datagrams} datagrams, "
          f"{listener.undecoded} undecoded")
    return 0


if __name__ == "__main__":              # pragma: no cover
    raise SystemExit(main())
