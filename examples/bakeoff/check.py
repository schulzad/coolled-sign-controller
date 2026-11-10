#!/usr/bin/env python3
"""Check that a final is a 384x384 still, fully opaque, in the panel's eight colours.

    check.py FINAL.png [FINAL.png ...]
"""

import sys
from collections import Counter

from PIL import Image

SIZE = (384, 384)
EIGHT = {
    (0, 0, 0): "black", (255, 0, 0): "red", (0, 255, 0): "green", (0, 0, 255): "blue",
    (0, 255, 255): "cyan", (255, 0, 255): "magenta", (255, 255, 0): "yellow", (255, 255, 255): "white",
}


def check(path):
    img = Image.open(path)
    problems = []
    if getattr(img, "n_frames", 1) > 1:
        problems.append(f"{img.n_frames} frames, not a still")
    if img.size != SIZE:
        problems.append(f"{img.width}x{img.height}, not {SIZE[0]}x{SIZE[1]}")
    rgba = img.convert("RGBA")
    see_through = sum(1 for *_, a in rgba.getdata() if a < 255)
    if see_through:
        problems.append(f"{see_through} pixels not fully opaque")
    colours = Counter((r, g, b) for r, g, b, _ in rgba.getdata())
    stray = {c: n for c, n in colours.items() if c not in EIGHT}
    if stray:
        worst = ", ".join(f"#{r:02x}{g:02x}{b:02x} x{n}" for (r, g, b), n in Counter(stray).most_common(5))
        problems.append(f"{len(stray)} colours outside the eight ({worst})")
    used = ", ".join(f"{EIGHT[c]} {n * 100 / (img.width * img.height):.1f}%"
                     for c, n in colours.most_common() if c in EIGHT)
    print(f"{path}: {'ok' if not problems else 'FAIL: ' + '; '.join(problems)}")
    print(f"  uses {used}")
    return not problems


if __name__ == "__main__":
    results = [check(p) for p in sys.argv[1:]]
    sys.exit(0 if results and all(results) else 1)
