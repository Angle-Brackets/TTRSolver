"""A learned reader for the small digits on screen.

Matching each glyph against one clean font rendering fails once a frame
isn't perfect -- a "5" read as 4, 7, 1 or "62" on a recorded run. Most of
that was cropping (see `gagpanel._count_glyphs`); the rest was shape
confusion (5/6, 4/3) a single template can't settle.

Trained on SYNTHETIC digits: the game's own font rendered at on-screen
sizes, distorted like real frames (blur, compression bleed, JPEG blocks,
icon clutter, pixel shift), and cut out by the same cropping the live
reader uses. `tools/train_digits.py` regenerates the data and weights.

Hand-labelled benchmark (168 cells): template matcher 151/168 (old
cropping) -> 166/168 (new cropping); this classifier 167/168. The one
miss scored a margin of 0.145; the lowest correct read was 0.882, so the
0.5 doubt threshold below flags only the miss.

numpy only at play time, like the rest of `solver.live.vision`. Without
the weights file, `count_classifier()` is None and callers keep the
template matcher.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

COUNT_WEIGHTS = Path(__file__).resolve().with_name("count_digits.json")
LEVEL_WEIGHTS = Path(__file__).resolve().with_name("level_digits.json")

# The classifier's input: a glyph scaled into a 20x14 box, intensities
# stretched to 0-1, plus its width/height ratio.
GLYPH_H, GLYPH_W = 20, 14

# How far the best digit's probability must beat the runner-up's before
# a read is trusted. Calibrated on the benchmark above: wrong 0.145,
# lowest correct 0.882.
NET_DOUBT = 0.5


def otsu(values: np.ndarray) -> int:
    """The threshold that best splits `values` (0-255) into two classes."""
    v = np.clip(np.asarray(values), 0, 255).astype(np.int64).ravel()
    hist = np.bincount(v, minlength=256).astype(float)
    total = hist.sum()
    cum = np.cumsum(hist)
    mean = np.cumsum(hist * np.arange(256))
    best, threshold = -1.0, 128
    for k in range(1, 255):
        w0, w1 = cum[k], total - cum[k]
        if w0 == 0 or w1 == 0:
            continue
        m0, m1 = mean[k] / w0, (mean[-1] - mean[k]) / w1
        between = w0 * w1 * (m0 - m1) ** 2
        if between > best:
            best, threshold = between, k
    return threshold


def glyph_vector(gray: np.ndarray) -> np.ndarray:
    """One glyph as the classifier reads it."""
    from PIL import Image

    g = np.asarray(gray, dtype=float)
    lo, hi = g.min(), g.max()
    g = (g - lo) / (hi - lo + 1e-6)
    h, w = g.shape
    scale = min(GLYPH_H / h, GLYPH_W / w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    img = Image.fromarray((g * 255).astype(np.uint8)).resize((nw, nh),
                                                             Image.BILINEAR)
    canvas = np.zeros((GLYPH_H, GLYPH_W))
    y0, x0 = (GLYPH_H - nh) // 2, (GLYPH_W - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = np.asarray(img, dtype=float) / 255.0
    return np.concatenate([canvas.ravel(), [w / float(h)]])


class Classifier:
    """A small MLP over `glyph_vector`, ReLU between layers."""

    def __init__(self, layers: List[Tuple[np.ndarray, np.ndarray]]):
        self.layers = layers

    @classmethod
    def load(cls, path: Path) -> Optional["Classifier"]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            layers = [(np.array(w, dtype=float), np.array(b, dtype=float))
                      for w, b in payload["layers"]]
        except Exception:                       # noqa: BLE001 -- fall back
            return None
        if layers[0][0].shape[0] != GLYPH_H * GLYPH_W + 1:
            return None
        return cls(layers)

    def probabilities(self, gray: np.ndarray) -> np.ndarray:
        h = glyph_vector(gray)
        for i, (w, b) in enumerate(self.layers):
            h = h @ w + b
            if i < len(self.layers) - 1:
                h = np.maximum(h, 0.0)
        e = np.exp(h - h.max())
        return e / e.sum()

    def classify(self, gray: np.ndarray) -> Tuple[int, float]:
        """(digit, margin): margin is best minus runner-up probability."""
        p = self.probabilities(gray)
        order = np.argsort(p)[::-1]
        return int(order[0]), float(p[order[0]] - p[order[1]])


_COUNT: Optional[Classifier] = None
_TRIED = False


def count_classifier() -> Optional[Classifier]:
    """The gag-count digit reader, or None if its weights are missing."""
    global _COUNT, _TRIED
    if not _TRIED:
        _TRIED = True
        _COUNT = Classifier.load(COUNT_WEIGHTS)
    return _COUNT


_LEVEL: Optional[Classifier] = None
_LEVEL_TRIED = False


def level_classifier() -> Optional[Classifier]:
    """The cog-plate level digit reader, or None if its weights are missing."""
    global _LEVEL, _LEVEL_TRIED
    if not _LEVEL_TRIED:
        _LEVEL_TRIED = True
        _LEVEL = Classifier.load(LEVEL_WEIGHTS)
    return _LEVEL
