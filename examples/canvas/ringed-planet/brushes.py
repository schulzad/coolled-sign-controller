#!/usr/bin/env python3
"""Throwaway brushes for the first drawing. A brush bakes plain rows into the scene
file and leaves: the rows are kept, the brush is not, and what it adds carries a
note naming the brush, its version, its seed and its settings.

    brushes.py blockin SCENE                       the coarse layers, in draw order
    brushes.py crater  SCENE NAME W H              one crater sprite, to place by hand
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

VERSION = "0.1"
W, H = 384, 384
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]

# One planet, one ring plane and one sun, shared by every brush so the shadows agree.
CX, CY, R = 238, 210, 112
TILT = math.radians(12)   # the ring plane's slant in the picture, left end up
OPEN = math.radians(12)   # how far the north pole leans toward us
_L = (0.60, 0.05, 0.80)  # toward the sun: right, level, mostly toward us
LIGHT = tuple(v / math.sqrt(sum(c * c for c in _L)) for v in _L)
COS_T, SIN_T, COS_I, SIN_I = math.cos(TILT), math.sin(TILT), math.cos(OPEN), math.sin(OPEN)
POLE = (COS_I * SIN_T, -COS_I * COS_T, SIN_I)
GROUND_C, GROUND_R = (192, 1230), 948  # the horizon is this circle's top edge

BANDS = [  # lower bound of sin(latitude), colour, second colour, share of the second
    (0.86, "C", "B", 0.50), (0.74, "W", "C", 0.30), (0.62, "Y", "W", 0.30), (0.53, "R", "Y", 0.50),
    (0.36, "W", "Y", 0.25), (0.28, "R", "R", 0.00), (0.17, "Y", "R", 0.25), (-0.04, "W", "Y", 0.50),
    (-0.12, "M", "R", 0.50), (-0.30, "Y", "R", 0.50), (-0.38, "W", "Y", 0.25), (-0.50, "M", "R", 0.50),
    (-0.70, "Y", "W", 0.25), (-1.01, "R", "M", 0.50),
]
RINGS = [  # inner and outer radius in planet radii, colour, second colour, share, coverage
    (1.22, 1.45, "B", "C", 0.35, 0.50), (1.45, 1.78, "W", "Y", 0.20, 1.00),
    (1.86, 2.05, "Y", "W", 0.45, 1.00), (2.10, 2.12, "W", "W", 0.00, 0.60),
]
GAPS = []


def on(x, y, share):
    return BAYER[y & 3][x & 3] < share * 16


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def ring_at(rho):
    if any(lo <= rho < hi for lo, hi in GAPS):
        return None
    return next((band for band in RINGS if band[0] <= rho < band[1]), None)


def noise(seed):
    cache = {}

    def grid(i, j):
        if (i, j) not in cache:
            cache[(i, j)] = random.Random(f"{seed}:{i}:{j}").random()
        return cache[(i, j)]

    def at(x, y):
        i, j = math.floor(x), math.floor(y)
        fx, fy = x - i, y - j
        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = grid(i, j) + (grid(i + 1, j) - grid(i, j)) * sx
        bottom = grid(i, j + 1) + (grid(i + 1, j + 1) - grid(i, j + 1)) * sx
        return top + (bottom - top) * sy

    return at


def layer(paint, x0, y0, x1, y1):
    """Rows for the box, from paint(x, y) -> a character, trimmed to what it paints."""
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    rows = ["".join(paint(x, y) for x in range(x0, x1)) for y in range(y0, y1)]
    keep = [j for j, r in enumerate(rows) if r.strip(".")]
    if not keep:
        return None
    rows = rows[keep[0]:keep[-1] + 1]
    left = min(len(r) - len(r.lstrip(".")) for r in rows if r.strip("."))
    right = max(len(r.rstrip(".")) for r in rows)
    return [r[left:right] for r in rows], [x0 + left, y0 + keep[0]]


def surface(x, y):
    """The planet's surface point under a pixel, or None off the disc."""
    dx, dy = x - CX, y - CY
    if dx * dx + dy * dy > (R + 0.5) ** 2:
        return None
    return (dx, dy, math.sqrt(max(0.0, R * R - dx * dx - dy * dy)))


def planet(x, y):
    p = surface(x, y)
    if p is None:
        return "."
    s = dot(p, POLE) / R
    u = (p[0] * COS_T + p[1] * SIN_T) / R
    s += 0.018 * math.sin(5.0 * u + 9.0 * s) + 0.008 * math.sin(13.0 * u + 4.0 * s + 1.3)
    _, first, second, share = next(b for b in BANDS if s >= b[0])
    return second if on(x, y, share) else first


def night(x, y):
    p = surface(x, y)
    if p is None:
        return "."
    lit = max(0.0, min(1.0, (dot(p, LIGHT) / R - 0.03) / 0.20))
    return "." if on(x, y, lit) else "K"


def ring_shadow(x, y):
    """Where the rings stand between the sun and the planet's face."""
    p = surface(x, y)
    if p is None or dot(p, LIGHT) <= 0:
        return "."
    s = -dot(p, POLE) / dot(LIGHT, POLE)
    if s <= 0:
        return "."
    q = (p[0] + s * LIGHT[0], p[1] + s * LIGHT[1], p[2] + s * LIGHT[2])
    band = ring_at(math.sqrt(dot(q, q)) / R)
    if band is None:
        return "."
    return "K" if on(x + 2, y + 1, band[5]) else "."


def ring(front):
    def paint(x, y):
        dx, dy = x - CX, y - CY
        u = dx * COS_T + dy * SIN_T
        v = -dx * SIN_T + dy * COS_T
        if (v > 0) != front:
            return "."
        rho = math.hypot(u, v / SIN_I) / R
        band = ring_at(rho)
        if band is None or not on(x + 1, y + 2, band[5]):
            return "."
        q = (dx, dy, v * COS_I / SIN_I)
        along = dot(q, LIGHT)
        if along < 0 and dot(q, q) - along * along < R * R:
            return "K" if band[5] >= 1 else "."
        return band[3] if on(x, y, band[4]) else band[2]
    return paint


def horizon(x):
    return GROUND_C[1] - math.sqrt(GROUND_R ** 2 - (x - GROUND_C[0]) ** 2)


def grain(seed, x, y):
    return random.Random(f"{seed}:{x}:{y}").random()


def ground(seed):
    coarse, fine = noise(seed), noise(seed + 1)

    def paint(x, y):
        depth = y - horizon(x)
        if depth < 0:
            return "."
        if depth < 1.2:
            return "W" if grain(seed, x, y) < 0.8 else "K"
        far = 300 / (depth + 4)
        across = (x - GROUND_C[0]) * far / 60
        n = 0.65 * coarse(across / 9, far / 2.5) + 0.35 * fine(across / 2, far / 0.8)
        near = min(1.0, depth / 60)
        clump = 2 if depth > 45 else 1
        g = grain(seed + 2, x // clump, y // clump)
        white = (0.03 + 0.20 * n ** 3) * (1 - 0.6 * near) + 0.14 * max(0.0, 1 - depth / 14)
        if g < white:
            return "W"
        return "B" if g < white + (0.05 + 0.10 * (1 - n)) * (1 - 0.65 * near) else "K"
    return paint


def glow(w, h, seed):
    """A pool of light on the ground: dense next to its source, thinning to nothing."""
    rows = []
    for j in range(h):
        row = []
        for i in range(w):
            nx, ny = (i + 0.5 - w / 2) / (w / 2), (j + 0.5 - h / 2) / (h / 2)
            light = max(0.0, 1 - math.hypot(nx, ny)) ** 1.3
            row.append("Y" if on(i, j, light * 0.85) else ".")
        rows.append("".join(row))
    return rows


def sphere(r, lit, shade, seed):
    """A small moon in the scene's one light: lit colour, a second colour for texture, night on the dark side."""
    rows = []
    for j in range(2 * r + 1):
        row = []
        for i in range(2 * r + 1):
            dx, dy = i - r, j - r
            if dx * dx + dy * dy > (r + 0.5) ** 2:
                row.append(".")
                continue
            z = math.sqrt(max(0.0, r * r - dx * dx - dy * dy))
            b = (dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]) / r
            share = max(0.0, min(1.0, (b - 0.03) / 0.25))
            if not on(i, j, share):
                row.append("K")
            else:
                row.append(shade if grain(seed, i, j) < 0.22 else lit)
        rows.append("".join(row))
    return rows


def stars(seed, count=220, glints=8):
    rnd = random.Random(seed)
    placed = []
    while len(placed) < count + glints:
        x, y = rnd.randrange(2, W - 2), rnd.randrange(2, 290)
        if y >= horizon(x) - 2 or math.hypot(x - CX, y - CY) < R + 3:
            continue
        if any(abs(x - px) < 3 and abs(y - py) < 3 for _, px, py in placed):
            continue
        if len(placed) < glints:
            name = "glint"
        else:
            name = rnd.choices(["star", "star_c", "star_y", "star_b"], [80, 8, 6, 6])[0]
        placed.append((name, x - (1 if name == "glint" else 0), y - (1 if name == "glint" else 0)))
    return placed


def crater(w, h):
    a, b = w / 2, h / 2
    rows = []
    for j in range(h):
        row = []
        for i in range(w):
            nx, ny = (i + 0.5 - a) / a, (j + 0.5 - b) / b
            rr = nx * nx + ny * ny
            if rr > 1:
                row.append(".")
            elif rr > 0.62:
                row.append("W" if nx > 0.05 or on(i, j, 0.25) else "K")
            else:
                row.append("W" if on(i, j, max(0.0, min(0.6, 0.15 - 0.55 * nx))) else "K")
        rows.append("".join(row))
    return rows


def write_scene(path, scene):
    lines = ["{"]
    for key in ("size", "frame_ms", "notes"):
        if key in scene:
            lines.append(f'  "{key}": {json.dumps(scene[key], ensure_ascii=False)},')
    lines.append('  "items": [')
    items = scene["items"]
    lines += ["    " + json.dumps(it, ensure_ascii=False) + ("," if n < len(items) - 1 else "")
              for n, it in enumerate(items)]
    lines.append("  ],")
    lines.append('  "sprites": {')
    names = list(scene["sprites"])
    for n, name in enumerate(names):
        rows = scene["sprites"][name]
        lines.append(f"    {json.dumps(name)}: [")
        lines += [f"      {json.dumps(r)}" + ("," if m < len(rows) - 1 else "") for m, r in enumerate(rows)]
        lines.append("    ]" + ("," if n < len(names) - 1 else ""))
    lines += ["  }", "}"]
    Path(path).write_text("\n".join(lines) + "\n")


def note(brush, seed, settings):
    return f"baked by brushes.py {brush} v{VERSION}, seed {seed}, {settings}; the rows are the painter's now"


def blockin(a):
    geometry = f"planet at ({CX}, {CY}) radius {R}, rings tilted 12 and opened 12 degrees, sun from {_L}"
    scene = {
        "size": [W, H],
        "frame_ms": 1000,
        "notes": {
            "piece": "A ringed gas giant rising over the horizon of a small airless moon, seen from its surface.",
            "light": "The sun is low, off to the right and in front: every sphere is gibbous with its night side on the left, the rings throw a thin shadow on the planet, the planet's shadow cuts the back ring on the left, and ground shadows fall long to the left.",
            "layers": "Stars, back ring, planet, night side, ring shadow, front ring, ground; hand-painted detail goes on top.",
            "stars": note("stars", 11, "220 stars and 8 glints scattered above the horizon and off the planet") + "; any star can be moved or removed by hand.",
        },
        "items": [],
        "sprites": {"star": ["W"], "star_c": ["C"], "star_y": ["Y"], "star_b": ["B"], "glint": [".B.", "BWB", ".B."]},
    }
    scene["items"] += [{"sprite": name, "at": [x, y]} for name, x, y in stars(11)]
    span = int(2.13 * R) + 2
    layers = [
        ("ring_back", ring(False), (CX - span, CY - 80, CX + span, CY + 80), "ring", "the half of the rings behind the planet, the planet's shadow on them in K"),
        ("planet", planet, (CX - R - 1, CY - R - 1, CX + R + 2, CY + R + 2), "planet", "bands by latitude with wavy edges, " + geometry),
        ("night", night, (CX - R - 1, CY - R - 1, CX + R + 2, CY + R + 2), "night", "the planet's night side, dithered across the terminator"),
        ("ring_shadow", ring_shadow, (CX - R - 1, CY - R - 1, CX + R + 2, CY + R + 2), "ring_shadow", "where the rings shade the planet's face"),
        ("ring_front", ring(True), (CX - span, CY - 80, CX + span, CY + 80), "ring", "the half of the rings in front of the planet"),
        ("ground", ground(5), (0, int(horizon(GROUND_C[0])) - 1, W, H), "ground", f"regolith inside a circle at {GROUND_C} radius {GROUND_R}"),
    ]
    for name, paint, box, brush, settings in layers:
        rows, at = layer(paint, *box)
        scene["sprites"][name] = rows
        item = {"sprite": name, "at": at}
        if any("K" in r for r in rows):
            item["colors"] = {"K": "black"}
        item["note"] = note(brush, 5 if brush == "ground" else 0, settings)
        item["block_in"] = True
        scene["items"].append(item)
        print(f"{name}: {len(rows[0])}x{len(rows)} at {at}")
    write_scene(a.scene, scene)
    print(f"{a.scene}: {len(scene['items'])} placements, {len(scene['sprites'])} sprites")


def add_sprite(a, rows, settings):
    scene = json.loads(Path(a.scene).read_text())
    if a.name in scene["sprites"]:
        raise SystemExit(f"{a.name} is already a sprite; brushes only add")
    scene["sprites"][a.name] = rows
    scene.setdefault("notes", {})[a.name] = note(a.cmd, a.seed, settings) + "; placed by hand."
    write_scene(a.scene, scene)
    print("\n".join(rows))


def rebake(a):
    """Re-bake one block-in layer in place; refused once the layer is no longer a block-in."""
    scene = json.loads(Path(a.scene).read_text())
    item = next(it for it in scene["items"] if it["sprite"] == a.layer)
    if not item.get("block_in"):
        raise SystemExit(f"{a.layer} is no longer a block-in; it is the painter's now")
    if a.layer != "ground":
        raise SystemExit("only the ground re-bakes")
    rows, at = layer(ground(5), 0, int(horizon(GROUND_C[0])) - 1, W, H)
    scene["sprites"][a.layer], item["at"] = rows, at
    item["note"] = note("ground", 5, f"regolith inside a circle at {GROUND_C} radius {GROUND_R}, random grain, clumped near the viewer")
    write_scene(a.scene, scene)
    print(f"{a.layer}: {len(rows[0])}x{len(rows)} at {at}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("blockin")
    b.add_argument("scene")
    rb = sub.add_parser("rebake")
    rb.add_argument("scene")
    rb.add_argument("layer")
    for name in ("crater", "glow"):
        c = sub.add_parser(name)
        c.add_argument("scene")
        c.add_argument("name")
        c.add_argument("w", type=int)
        c.add_argument("h", type=int)
        c.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("sphere")
    s.add_argument("scene")
    s.add_argument("name")
    s.add_argument("r", type=int)
    s.add_argument("lit")
    s.add_argument("shade")
    s.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    if a.cmd == "blockin":
        if Path(a.scene).exists():
            raise SystemExit(f"{a.scene} exists; blockin starts a scene from nothing and would erase it")
        blockin(a)
    elif a.cmd == "rebake":
        rebake(a)
    elif a.cmd == "crater":
        add_sprite(a, crater(a.w, a.h), f"{a.w}x{a.h}, rim lit from the right")
    elif a.cmd == "glow":
        add_sprite(a, glow(a.w, a.h, a.seed), f"{a.w}x{a.h}, yellow in an ordered dither fading to nothing")
    else:
        add_sprite(a, sphere(a.r, a.lit, a.shade, a.seed), f"radius {a.r}, {a.lit} flecked {a.shade}, the scene's light")


if __name__ == "__main__":
    main()
