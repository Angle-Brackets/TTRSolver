"""Train the gag-count digit reader on synthetic digits.

    python tools/train_digits.py            # writes solver/live/count_digits.json

Renders counts 0-30 in the game's interface font (read from the player's
own install by `ttr_assets`, never shipped) as white digits on cells like
the gag menu's -- blue, grey, dark grey, with icon-like clutter -- then
distorts them the way real frames are: downscaling, blur, the 4:2:0
colour bleed of video, JPEG blocks, a few pixels of shift. Each image is
cut by `gagpanel._count_glyphs`, the live reader's own cropping, and an
image whose glyph count does not match its number is dropped -- so the
network learns exactly what that code hands it at play time.

torch for training only; `solver.live.digits` runs the result in numpy.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def corner(rng, number, font_path):
    """One synthetic count corner, as an int16 RGB array."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    H = rng.randint(28, 48)
    W = int(H * rng.uniform(0.9, 1.1))
    up = 4
    kind = rng.random()
    if kind < 0.55:
        base = (rng.randint(15, 70), rng.randint(110, 175), rng.randint(190, 255))
    elif kind < 0.85:
        g = rng.randint(95, 150)
        base = (g - rng.randint(0, 15), g, g + rng.randint(0, 20))
    else:
        g = rng.randint(45, 90)
        base = (g, g, g + rng.randint(0, 15))
    img = Image.new("RGB", (W * up, H * up), base)
    draw = ImageDraw.Draw(img)
    tilt = rng.choice((-1, 1))
    for y in range(H * up):
        f = 1.0 + 0.25 * (y / (H * up) - 0.5) * tilt
        draw.line([(0, y), (W * up, y)],
                  fill=tuple(int(min(255, c * f)) for c in base))
    for _ in range(rng.randint(0, 4)):
        x = rng.randint(-W, int(W * 0.55)) * up
        y = rng.randint(-H // 2, int(H * 0.8)) * up
        r = rng.randint(3, 14) * up
        col = tuple(rng.randint(0, 255) for _ in range(3))
        if rng.random() < 0.3:
            col = tuple(rng.randint(200, 255) for _ in range(3))
        if rng.random() < 0.5:
            draw.ellipse((x, y, x + r * 2, y + r), fill=col)
        else:
            draw.line((x, y, x + r * 2, y + rng.randint(-r, r)), fill=col,
                      width=rng.randint(1, 3) * up)
    font = ImageFont.truetype(font_path,
                              int(H * rng.uniform(0.40, 0.52) * up * 1.35))
    text = str(number)
    stroke = rng.choice((0, 1, 1, 2)) * up // 2
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw, th = box[2] - box[0], box[3] - box[1]
    right = W * up - rng.randint(3, 9) * up
    bottom = int(H * up * rng.uniform(0.55, 0.62))
    white = rng.randint(225, 255)
    draw.text((right - tw - box[0], bottom - th - box[1]), text, font=font,
              fill=(white, white, white), stroke_width=stroke,
              stroke_fill=(rng.randint(0, 40), rng.randint(0, 50),
                           rng.randint(30, 90)))
    img = img.resize((W, H), Image.LANCZOS)
    if rng.random() < 0.6:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.1, 0.8)))
    if rng.random() < 0.5:
        y_, cb, cr = img.convert("YCbCr").split()
        half = (max(1, W // 2), max(1, H // 2))
        cb = cb.resize(half, Image.BILINEAR).resize((W, H), Image.BILINEAR)
        cr = cr.resize(half, Image.BILINEAR).resize((W, H), Image.BILINEAR)
        img = Image.merge("YCbCr", (y_, cb, cr)).convert("RGB")
    if rng.random() < 0.5:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(35, 95))
        img = Image.open(buf).convert("RGB")
    return np.asarray(img).astype(np.int16)


def samples(job):
    """`n` labelled glyph vectors from seed `seed`."""
    n, seed = job
    import numpy as np

    from solver.live import digits, gagpanel, ttr_assets

    font_path = str(ttr_assets.interface_font())
    rng = random.Random(seed)
    X, Y = [], []
    while len(Y) < n:
        number = rng.choice(list(range(10)) * 3 + list(range(10, 31)))
        glyphs = gagpanel._count_glyphs(corner(rng, number, font_path),
                                        region=(0, 0, 1, 1))
        text = str(number)
        if len(glyphs) != len(text):
            continue
        for (_mask, gray), ch in zip(glyphs, text):
            X.append(digits.glyph_vector(gray))
            Y.append(int(ch))
    return np.array(X[:n], dtype=np.float32), np.array(Y[:n])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=60000)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--export", default="solver/live/count_digits.json")
    args = ap.parse_args()

    from concurrent.futures import ProcessPoolExecutor

    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    chunks = 20
    with ProcessPoolExecutor() as pool:
        parts = list(pool.map(samples, [(args.samples // chunks, s)
                                        for s in range(chunks)]))
    X = np.concatenate([p[0] for p in parts])
    Y = np.concatenate([p[1] for p in parts])
    print(f"  {len(Y)} synthetic digits, per digit {np.bincount(Y).tolist()}")

    rng = np.random.default_rng(0)
    order = rng.permutation(len(Y))
    cut = int(0.95 * len(Y))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    Xt = torch.tensor(X[order[:cut]], device=dev)
    Yt = torch.tensor(Y[order[:cut]], device=dev)
    Xv = torch.tensor(X[order[cut:]], device=dev)
    Yv = torch.tensor(Y[order[cut:]], device=dev)
    torch.manual_seed(0)
    net = nn.Sequential(nn.Linear(X.shape[1], 128), nn.ReLU(),
                        nn.Linear(128, 64), nn.ReLU(),
                        nn.Linear(64, 10)).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-5)
    for epoch in range(args.epochs):
        perm = torch.randperm(len(Yt), device=dev)
        for s in range(0, len(Yt), 512):
            i = perm[s:s + 512]
            noisy = Xt[i] + 0.03 * torch.randn_like(Xt[i])
            loss = F.cross_entropy(net(noisy), Yt[i])
            opt.zero_grad()
            loss.backward()
            opt.step()
        if epoch % 10 == 9 or epoch == args.epochs - 1:
            with torch.no_grad():
                acc = (net(Xv).argmax(-1) == Yv).float().mean().item()
            print(f"  epoch {epoch + 1}: held-out synthetic accuracy "
                  f"{100 * acc:.2f}%")

    layers = [m for m in net if isinstance(m, nn.Linear)]
    payload = {"layers": [[m.weight.detach().cpu().T.tolist(),
                           m.bias.detach().cpu().tolist()] for m in layers],
               "samples": len(Y), "epochs": args.epochs}
    Path(args.export).write_text(json.dumps(payload), encoding="utf-8")
    print(f"  exported to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
