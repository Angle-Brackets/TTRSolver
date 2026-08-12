"""The department emblem atlas is in a non-obvious order.

`ttr_t_ara_gen_cogIcons.jpg` is a 2x2 grid, and its order is neither
alphabetical nor the c/l/m/s the Local API uses for cog suits:

    Sellbot, Cashbot, Lawbot, Bossbot

This was wrong for several commits because the tiles were assigned by
looking at them and guessing what each depicted, which swapped the
rising bar chart (a *sales* chart -- Sellbot) with the necktie (the
boss's tie -- Bossbot). A real Bossbot plate then read as Sellbot with a
margin of 0.43, far above the confidence floor, so nothing flagged it.
Worse than the label: the wrong department narrows the head library to
the wrong five cogs, so the cog actually on screen is not even offered
when labelling, and answering anyway writes a wrong entry that persists.

The check needs the game installed and the wiki icons fetched
(`tools/fetch_icons.py`), and skips when either is absent -- but where
it can run, it is pinned to a source that names each department rather
than to anyone's reading of a picture.
"""
import unittest
from pathlib import Path

try:
    import numpy as np
    from PIL import Image

    from solver.live import ttr_assets
except ImportError as exc:                   # numpy is an optional extra
    raise unittest.SkipTest(f"emblem check needs numpy: {exc}") from None

WIKI_ICONS = Path(__file__).resolve().parents[1] / "visualizer" / "assets"


def greyscale(path, size=64):
    with Image.open(path) as img:
        grey = np.asarray(img.convert("L").resize((size, size),
                                                  Image.LANCZOS), dtype=float)
    return (grey - grey.mean()) / (grey.std() or 1.0)


class EmblemOrderTest(unittest.TestCase):

    def setUp(self):
        try:
            self.atlas = ttr_assets.department_emblems()
        except ttr_assets.AssetError as exc:
            raise unittest.SkipTest(f"no Toontown installation: {exc}")
        self.wiki = {p.stem.split("-")[1]: p
                     for p in WIKI_ICONS.glob("dept-*.png")}
        if len(self.wiki) < 4:
            raise unittest.SkipTest(
                "wiki department icons not fetched; run tools/fetch_icons.py")

    def test_every_department_is_present_exactly_once(self):
        self.assertEqual(sorted(ttr_assets.EMBLEM_ORDER),
                         ["bossbot", "cashbot", "lawbot", "sellbot"])

    def test_each_atlas_tile_matches_its_named_wiki_icon(self):
        """Correlate each extracted tile against every wiki icon; the
        best match must be the department the tile is filed under."""
        for dept, path in self.atlas.items():
            tile = greyscale(path)
            scores = {name: float((tile * greyscale(icon)).mean())
                      for name, icon in self.wiki.items()}
            best = max(scores, key=scores.get)
            with self.subTest(dept=dept):
                self.assertEqual(
                    best, dept,
                    f"atlas tile filed as {dept} looks most like "
                    f"{best} (scores {scores})")

    def test_bossbot_and_sellbot_are_not_swapped(self):
        """The specific error that shipped, called out by name."""
        order = ttr_assets.EMBLEM_ORDER
        self.assertEqual(order.index("sellbot"), 0,
                         "top-left is the rising bar chart: Sellbot")
        self.assertEqual(order.index("bossbot"), 3,
                         "bottom-right is the necktie: Bossbot")


if __name__ == "__main__":
    unittest.main()
