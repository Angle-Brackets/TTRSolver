"""Pick a front end and start it: `python run.py`

Every UI in this repo is a module you can already run by hand -- this
just lists them, says which will actually work on this machine, and
starts the one you pick. It is standard library only, so it runs even
when none of the optional extras are installed; that is the point,
since its job is partly to tell you what is missing.

    python run.py              choose from the menu
    python run.py 3            start entry 3 straight away
    python run.py 3 --once     anything after the number is passed on
    python run.py --list       print the menu and exit
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from typing import NamedTuple, Sequence


class Entry(NamedTuple):
    label: str
    module: str
    needs: Sequence[str]
    blurb: str


# Grouped the way you'd choose: what am I doing, then which client.
GROUPS: Sequence[tuple] = (
    ("Live advice", (
        Entry("TTR overlay", "solver.live.panel", ("webview", "numpy", "PIL", "mss"),
              "always-on-top panel over Toontown Rewritten, read off the screen"),
        Entry("TTR overlay (Tk)", "solver.live.overlay", ("numpy", "PIL", "mss"),
              "the same worker in a plain Tk window; no webview needed"),
        Entry("TTR advice in the terminal", "solver.live.advise",
              ("numpy", "PIL", "mss"),
              "one line of advice per round, no window at all"),
        Entry("Realms panel", "solver.live.realms_panel", ("webview", "panda3d"),
              "reads Toontown Realms' Astron cluster -- knows your slips, "
              "unites and SOS cards"),
    )),
    ("Try it without a game", (
        Entry("Narrated solo fight", "solver.search.demo", (),
              "the exact search plays a battle and explains each move"),
        Entry("Random-policy demo", "solver.demo", (),
              "a baseline run, for comparison"),
        Entry("Browser visualizer", "visualizer.serve", (),
              "serves the page and runs the solver in Pyodide"),
    )),
    ("Diagnostics", (
        Entry("Read one screenshot", "solver.live.read_battle",
              ("numpy", "PIL"),
              "identify the cogs in a single frame, and label new ones"),
        Entry("Watch the screen", "solver.live.watch", ("numpy", "PIL", "mss"),
              "follow a battle frame by frame, printing what it sees"),
        Entry("Probe the TTR Local API", "solver.live.ttr_local", (),
              "what the official API reports: laff, tracks, organic, location"),
    )),
)

EXTRAS = {
    "numpy": "requirements-vision.txt",
    "PIL": "requirements-vision.txt",
    "mss": "requirements-vision.txt",
    "panda3d": "requirements-realms.txt",
    "webview": "pip install pywebview",
}


def missing(entry: Entry) -> list:
    """Which of an entry's third-party imports are absent."""
    return [m for m in entry.needs if importlib.util.find_spec(m) is None]


def _flat() -> list:
    return [e for _title, entries in GROUPS for e in entries]


def show() -> None:
    n = 0
    for title, entries in GROUPS:
        print("\n  " + title)
        print("  " + "-" * len(title))
        for entry in entries:
            n += 1
            gap = missing(entry)
            mark = "   " if not gap else " ! "
            print("  %s%2d. %-28s %s" % (mark, n, entry.label, entry.blurb))
            if gap:
                print("         needs %s" % ", ".join(gap))
                for fix in sorted({EXTRAS.get(m, "pip install " + m)
                                   for m in gap}):
                    print("           %s" % (fix if fix.startswith("pip")
                                             else "pip install -r " + fix))
    print("\n  ! = an optional dependency is missing; everything else will run.\n")


def launch(entry: Entry, extra: Sequence[str]) -> int:
    gap = missing(entry)
    if gap:
        print("  %s needs %s, which is not installed."
              % (entry.label, ", ".join(gap)))
        for m in gap:
            fix = EXTRAS.get(m, "pip install " + m)
            print("    %s" % (fix if fix.startswith("pip")
                              else "pip install -r " + fix))
        return 1
    print("  starting %s  (python -m %s%s)\n"
          % (entry.label, entry.module,
             " " + " ".join(extra) if extra else ""))
    # Same interpreter, same console, so Ctrl-C reaches it and a
    # traceback lands where you can read it.
    return subprocess.call([sys.executable, "-m", entry.module, *extra])


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    entries = _flat()

    if argv and argv[0] in ("-l", "--list"):
        show()
        return 0
    if argv and argv[0].isdigit():
        choice = int(argv[0])
        if not 1 <= choice <= len(entries):
            print("  no entry %d; there are %d." % (choice, len(entries)))
            return 1
        return launch(entries[choice - 1], argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    print(__doc__.strip().split("\n")[0])
    show()
    try:
        raw = input("  number (or blank to quit): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    if not raw:
        return 0
    if not raw.isdigit() or not 1 <= int(raw) <= len(entries):
        print("  not one of the numbers.")
        return 1
    return launch(entries[int(raw) - 1], [])


if __name__ == "__main__":
    raise SystemExit(main())
