"""
Cross-check solver/data/ against Toontown Online's own source arrays.

    python tools/verify_against_tto.py

Compares every cog attack row we hold against `SuitAttributes` in
SuitBattleGlobals.py from Open Toontown (<https://github.com/open-toontown>),
an open-source continuation carrying the original Toontown Online data.

WHAT THIS DOES AND DOESN'T PROVE
--------------------------------
This is *not* a TTR source. It is the pre-rebalance ancestor of the values
the QED1224 strategy guide gave us, so it cannot tell us what TTR changed.
What it does is separate two failure modes that otherwise look identical:

  - a value we transcribed wrong  ->  shows up here as a mismatch
  - a value TTR rebalanced        ->  shows up here as a mismatch too, BUT
                                      the wiki will already have flagged it

So a row that matches TTO and matches the wiki is solid. A row that differs
from TTO exactly where the wiki said TTR changed it is confirmation from
both ends. A row that differs from TTO *without* a wiki explanation would be
a transcription bug -- and at the time of writing there are none.

It also settles questions the wiki can't, because the wiki publishes no cog
frequency or accuracy at all: those columns are pure TTO, and this verifies
we hold them faithfully even though TTR has since moved them.

Requires network on first run; caches the download next to this file.
"""
import argparse
import ast
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from solver import data  # noqa: E402

SOURCE_URL = ("https://raw.githubusercontent.com/open-toontown/open-toontown/"
              "master/toontown/battle/SuitBattleGlobals.py")
CACHE = pathlib.Path(__file__).with_name(".tto_SuitBattleGlobals.py")

# Toontown Online suit key -> (department, our cog_type).
SUIT_KEYS = {
    "f": ("bossbot", "flunky"), "p": ("bossbot", "pencil_pusher"),
    "ym": ("bossbot", "yesman"), "mm": ("bossbot", "micromanager"),
    "ds": ("bossbot", "downsizer"), "hh": ("bossbot", "head_hunter"),
    "cr": ("bossbot", "corporate_raider"), "tbc": ("bossbot", "the_big_cheese"),
    "cc": ("sellbot", "cold_caller"), "tm": ("sellbot", "telemarketer"),
    "nd": ("sellbot", "name_dropper"), "gh": ("sellbot", "glad_hander"),
    "ms": ("sellbot", "mover_and_shaker"), "tf": ("sellbot", "two_face"),
    "m": ("sellbot", "the_mingler"), "mh": ("sellbot", "mr_hollywood"),
    "sc": ("cashbot", "short_change"), "pp": ("cashbot", "penny_pincher"),
    "tw": ("cashbot", "tightwad"), "bc": ("cashbot", "bean_counter"),
    "nc": ("cashbot", "number_cruncher"), "mb": ("cashbot", "money_bags"),
    "ls": ("cashbot", "loan_shark"), "rb": ("cashbot", "robber_baron"),
    "bf": ("lawbot", "bottom_feeder"), "b": ("lawbot", "bloodsucker"),
    "dt": ("lawbot", "double_talker"), "ac": ("lawbot", "ambulance_chaser"),
    "bs": ("lawbot", "backstabber"), "sd": ("lawbot", "spin_doctor"),
    "le": ("lawbot", "legal_eagle"), "bw": ("lawbot", "big_wig"),
}


def snake(camel: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower().replace("-", "_")


def fetch_source(refresh: bool = False) -> str:
    if CACHE.exists() and not refresh:
        return CACHE.read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCE_URL) as resp:
        text = resp.read().decode("utf-8")
    CACHE.write_text(text, encoding="utf-8")
    return text


def parse_suit_attributes(text: str) -> dict:
    """Pull SuitAttributes out with `ast` -- the module can't be imported,
    it needs panda3d and TTLocalizer. Only literal fields are read."""
    tree = ast.parse(text)
    node = next(n.value for n in tree.body
                if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "SuitAttributes")
    out = {}
    for key_node, val in zip(node.keys, node.values):
        entry = {}
        for k, v in zip(val.keys, val.values):
            field = ast.literal_eval(k)
            if field in ("hp", "def", "acc", "freq"):
                entry[field] = list(ast.literal_eval(v))
            elif field == "level":       # a bare int, not a tuple
                entry[field] = ast.literal_eval(v)
            elif field == "attacks":
                entry["attacks"] = {
                    snake(ast.literal_eval(a.elts[0])): {
                        "damage": list(ast.literal_eval(a.elts[1])),
                        "accuracy": list(ast.literal_eval(a.elts[2])),
                        "freq": list(ast.literal_eval(a.elts[3])),
                    }
                    for a in v.elts
                }
        out[ast.literal_eval(key_node)] = entry
    return out


def compare(src: dict):
    stats = {"match": 0, "differ": 0, "ours_todo": 0}
    notes = []
    for suit, (dept, cog_type) in sorted(SUIT_KEYS.items(), key=lambda kv: kv[1]):
        theirs = src[suit]["attacks"]
        ours = data.COG_DEPARTMENTS[dept][cog_type]

        for extra in sorted(set(theirs) - set(ours["freq"])):
            notes.append(f"ROSTER  {dept}/{cog_type}: TTO has '{extra}', we don't")
        for extra in sorted(set(ours["freq"]) - set(theirs)):
            notes.append(f"ROSTER  {dept}/{cog_type}: we have '{extra}', TTO doesn't")

        for attack in sorted(set(ours["freq"]) & set(theirs)):
            for field in ("damage", "accuracy", "freq"):
                mine, yours = list(ours[field][attack]), theirs[attack][field]
                if all(v is None for v in mine):
                    stats["ours_todo"] += 1
                    notes.append(f"TODO    {dept}/{cog_type}/{attack}.{field}"
                                 f" -- TTO has {yours}")
                elif mine == yours:
                    stats["match"] += 1
                else:
                    stats["differ"] += 1
                    notes.append(f"DIFFER  {dept}/{cog_type}/{attack}.{field}"
                                 f"\n          ours {mine}\n          TTO  {yours}")
    return stats, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="re-download instead of using the cached copy")
    args = parser.parse_args()

    src = parse_suit_attributes(fetch_source(args.refresh))
    stats, notes = compare(src)

    total = stats["match"] + stats["differ"]
    print(f"{stats['match']}/{total} cog attack rows match Toontown Online")
    print(f"  {stats['differ']} differ, {stats['ours_todo']} still [TODO] here\n")
    for note in notes:
        print(note)

    print("\nDerived tables:")
    print(f"  flunky 'def'  {src['f']['def']}  vs our rank-1 tgtDef "
          f"{[-data.TGT_DEF_RANK_1[l] for l in range(1, 6)]}")
    print(f"  flunky 'hp'   {src['f']['hp']}  vs our cog_max_hp "
          f"{[data.cog_max_hp(l) for l in range(1, 6)]}")
    print("\nEvery DIFFER above should be explained by a wiki-sourced TTR "
          "rebalance.\nAn unexplained one is a transcription bug.")


if __name__ == "__main__":
    main()
