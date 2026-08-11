"""
Download gag icons, cog portraits and department emblems from the TTR wiki.

    python tools/fetch_icons.py

Writes into visualizer/assets/, which is gitignored: these are Toontown
Rewritten's own artwork, fetched for a local tool the same way a browser
fetches them to render the wiki. They are not this project's to redistribute,
so the repo carries the fetcher rather than the files. Run it once; the
visualizer degrades to text labels without it.

Naming, all derivable from the data rather than listed here:
  gags     File:<display> Icon.png          e.g. "Small Magnet Icon.png"
  cogs     File:Cog-<dept>-<key>.png        underscores stripped from the key
  emblems  File:<Dept>.png                  e.g. "Bossbot.png"

One cog breaks the pattern: Mover & Shaker's file drops the "and"
(movershaker, not moverandshaker), so it is special-cased below.
"""
import argparse
import json
import pathlib
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from solver import data  # noqa: E402

API = "https://toontownrewritten.wiki/api.php"
UA = {"User-Agent": "TTRSolver/dev (local visualizer; contact via repo)"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "visualizer" / "assets"

# The wiki's filename doesn't match the pattern for this one cog.
COG_FILE_OVERRIDES = {("sellbot", "mover_and_shaker"): "Cog-sellbot-movershaker.png"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=60) as resp:
        return resp.read()


def _api(**params) -> dict:
    params.setdefault("format", "json")
    return json.loads(_get(f"{API}?{urllib.parse.urlencode(params)}"))


def cog_file(cog) -> str:
    override = COG_FILE_OVERRIDES.get((cog.department, cog.key))
    return override or f"Cog-{cog.department}-{cog.key.replace('_', '')}.png"


def wanted() -> dict:
    """{wiki file title: local filename}"""
    out = {}
    for gag in data.GAGS:
        out[f"File:{gag.display} Icon.png"] = \
            f"gag-{gag.track.value}-{gag.level}.png"
    for cog in data.all_cogs():
        out[f"File:{cog_file(cog)}"] = f"cog-{cog.department}-{cog.key}.png"
    for dept in sorted(data.COG_DEPARTMENTS):
        out[f"File:{dept.title()}.png"] = f"dept-{dept}.png"
    return out


def resolve(titles):
    """Wiki file titles -> direct upload URLs, in batches the API accepts."""
    urls, missing = {}, []
    titles = list(titles)
    for i in range(0, len(titles), 40):
        pages = _api(action="query", titles="|".join(titles[i:i + 40]),
                     prop="imageinfo", iiprop="url")["query"]["pages"]
        for page in pages.values():
            if "imageinfo" in page:
                urls[page["title"]] = page["imageinfo"][0]["url"]
            else:
                missing.append(page["title"])
    return urls, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="re-download files that are already present")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    targets = wanted()
    print(f"{len(targets)} icons wanted")

    urls, missing = resolve(targets)
    for title in missing:
        print(f"  MISSING on the wiki: {title}")

    fetched = skipped = 0
    for title, local in sorted(targets.items()):
        if title not in urls:
            continue
        dest = OUT / local
        if dest.exists() and not args.force:
            skipped += 1
            continue
        dest.write_bytes(_get(urls[title]))
        fetched += 1

    print(f"downloaded {fetched}, already had {skipped}, "
          f"{len(missing)} unavailable")
    print(f"-> {OUT}")

    manifest = {local: title for title, local in targets.items()
                if title in urls}
    (OUT / "index.json").write_text(json.dumps(manifest, indent=1,
                                               sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT / 'index.json'} (local name -> wiki source)")


if __name__ == "__main__":
    main()
