#!/usr/bin/env python3
"""Throwaway workspace for the first drawing, the prototype of SceneCanvas.smdl's
look_overview, look_region, outline_scene, trace_pixel, hidden_placements and
pixel_diff. It composes a scene file at its own "size" with opensign's
compile_scene and writes looks for the painter to read. It lives outside the
repository on purpose and is thrown away once the real ones exist.

    workspace.py overview SCENE OUT.png [--tiles N] [--box X,Y,W,H] [--lines]
    workspace.py region   SCENE OUT.png X Y W H [--margin N] [--px N]
    workspace.py outline  SCENE [X Y W H]
    workspace.py trace    SCENE X Y
    workspace.py hidden   SCENE
    workspace.py snap     SCENE
    workspace.py diff     OLD NEW OUT.png
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from opensign.animation.scene import compile_scene

BUDGET = 1024
MAX_PX = 16
GUIDE = (255, 136, 0)
GRID = (48, 48, 48)
BACK = (28, 28, 28)
NAMES = {
    (0, 0, 0): "black", (255, 0, 0): "red", (0, 255, 0): "green", (0, 0, 255): "blue",
    (0, 255, 255): "cyan", (255, 0, 255): "magenta", (255, 255, 0): "yellow", (255, 255, 255): "white",
}


def load(path):
    return json.loads(Path(path).read_text())


def size_of(scene):
    w, h = scene.get("size", [64, 16])
    return int(w), int(h)


def rows_of(sprite):
    return sprite.split("\n") if isinstance(sprite, str) else list(sprite)


def compose(scene):
    w, h = size_of(scene)
    bundle = compile_scene(scene, w, h, frame_ms=scene.get("frame_ms", 200))
    return bundle.to_images()[0].convert("RGB")


def font(n):
    try:
        return ImageFont.load_default(size=n)
    except TypeError:
        return ImageFont.load_default()


def enlarge(img, px, grid=True):
    big = img.resize((img.width * px, img.height * px), Image.Resampling.NEAREST)
    if grid and px >= 4:
        d = ImageDraw.Draw(big)
        for x in range(0, big.width, px):
            d.line((x, 0, x, big.height - 1), fill=GRID)
        for y in range(0, big.height, px):
            d.line((0, y, big.width - 1, y), fill=GRID)
    return big


def fit_px(w, h, room):
    return max(1, min(MAX_PX, (BUDGET - room) // max(w, h)))


def overview(a):
    scene = load(a.scene)
    img = compose(scene)
    w, h = img.size
    m = 30
    px = fit_px(w, h, 2 * m)
    big = enlarge(img, px)
    sheet = Image.new("RGB", (big.width + 2 * m, big.height + 2 * m), BACK)
    sheet.paste(big, (m, m))
    d = ImageDraw.Draw(sheet)
    f = font(15)
    t = a.tiles
    for i, x in enumerate(range(0, w, t)):
        X = m + x * px
        d.line((X, m - 9, X, m - 1), fill=GUIDE)
        d.line((X, m + big.height, X, m + big.height + 8), fill=GUIDE)
        d.text((X + min(t, w - x) * px // 2 - 5, 7), chr(65 + i), fill=GUIDE, font=f)
        if a.lines and x:
            d.line((X, m, X, m + big.height - 1), fill=GUIDE)
    for j, y in enumerate(range(0, h, t)):
        Y = m + y * px
        d.line((m - 9, Y, m - 1, Y), fill=GUIDE)
        d.line((m + big.width, Y, m + big.width + 8, Y), fill=GUIDE)
        d.text((9, Y + min(t, h - y) * px // 2 - 8), str(j + 1), fill=GUIDE, font=f)
        if a.lines and y:
            d.line((m, Y, m + big.width - 1, Y), fill=GUIDE)
    if a.box:
        x, y, bw, bh = (int(v) for v in a.box.split(","))
        d.rectangle((m + x * px - 1, m + y * px - 1, m + (x + bw) * px, m + (y + bh) * px), outline=GUIDE)
    sheet.save(a.out)
    print(f"overview of a {w}x{h} canvas at {px} px per pixel -> {a.out} ({sheet.width}x{sheet.height}); "
          f"tiles of {t}: columns A-{chr(64 + -(-w // t))}, rows 1-{-(-h // t)}")


def region(a):
    scene = load(a.scene)
    img = compose(scene)
    W, H = img.size
    x, y, w, h, m = a.x, a.y, a.w, a.h, a.margin
    ax0, ay0, ax1, ay1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
    area = img.crop((ax0, ay0, ax1, ay1))
    r = 46
    px = a.px or fit_px(area.width, area.height, r + 10)
    big = enlarge(area, px)
    sheet = Image.new("RGB", (big.width + r + 10, big.height + r + 10), BACK)
    sheet.paste(big, (r, r))
    d = ImageDraw.Draw(sheet)
    f = font(13)
    step = next((s for s in (1, 2, 4, 8, 16, 32, 64) if s * px >= 34), 64)
    for cx in range(-(-ax0 // step) * step, ax1 + 1, step):
        X = r + (cx - ax0) * px
        d.line((X, r - 7, X, r - 1), fill=GUIDE)
        d.text((X + 2, r - 22), str(cx), fill=GUIDE, font=f)
    for cy in range(-(-ay0 // step) * step, ay1 + 1, step):
        Y = r + (cy - ay0) * px
        d.line((r - 7, Y, r - 1, Y), fill=GUIDE)
        d.text((3, Y + 1), str(cy), fill=GUIDE, font=f)
    d.rectangle((r + (x - ax0) * px, r + (y - ay0) * px, r + (x + w - ax0) * px, r + (y + h - ay0) * px),
                outline=GUIDE)
    sheet.save(a.out)
    print(f"region x {x}-{x + w - 1}, y {y}-{y + h - 1} with a {m}-pixel margin at {px} px per pixel "
          f"-> {a.out} ({sheet.width}x{sheet.height}); rulers every {step}")


def revision(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def outline(a):
    scene = load(a.scene)
    W, H = size_of(scene)
    sprites = {k: rows_of(v) for k, v in scene["sprites"].items()}
    items = scene.get("items", [])
    box = (a.x, a.y, a.w, a.h) if a.w else (0, 0, W, H)
    print(f"{a.scene}: revision {revision(a.scene)}, {W}x{H}, {len(sprites)} sprites, {len(items)} placements")
    copies = Counter(item["sprite"] for item in items)
    inside = Counter()
    for i, item in enumerate(items):
        rows = sprites[item["sprite"]]
        ax, ay = item.get("at", [0, 0])
        sw, sh = len(rows[0]), len(rows)
        if ax < box[0] + box[2] and ax + sw > box[0] and ay < box[1] + box[3] and ay + sh > box[1]:
            inside[item["sprite"]] += 1
            extra = "".join(f" {k}={json.dumps(item[k])}" for k in ("colors", "note", "block_in") if k in item)
            if not a.quiet or item["sprite"] not in a.quiet.split(","):
                print(f"  items[{i}] {item['sprite']} [{ax},{ay},{sw},{sh}]{extra}")
    for name, n in sorted(inside.items()):
        if copies[name] > n:
            print(f"  sprite {name}: {n} here, {copies[name] - n} more outside this region")
    for name in sprites:
        if name not in inside:
            print(f"  elsewhere: {name} x{copies[name]}")


def trace(a):
    scene = load(a.scene)
    sprites = {k: rows_of(v) for k, v in scene["sprites"].items()}
    hits = []
    for i, item in enumerate(scene.get("items", [])):
        rows = sprites[item["sprite"]]
        ax, ay = item.get("at", [0, 0])
        cx, cy = a.x - ax, a.y - ay
        if 0 <= cy < len(rows) and 0 <= cx < len(rows[0]) and rows[cy][cx] != ".":
            hits.append((i, item, cx, cy, rows[cy][cx]))
    colour = compose(scene).getpixel((a.x, a.y))
    print(f"pixel ({a.x}, {a.y}) shows {NAMES.get(colour, colour)}")
    for n, (i, item, cx, cy, ch) in enumerate(reversed(hits)):
        note = f"  note: {item['note']}" if "note" in item else ""
        print(f"  {'shows' if n == 0 else 'beneath'}: items[{i}] {item['sprite']} at {item.get('at')}, "
              f"sprite cell ({cx}, {cy}) = {ch!r}{note}")


def hidden(a):
    scene = load(a.scene)
    W, H = size_of(scene)
    sprites = {k: rows_of(v) for k, v in scene["sprites"].items()}
    items = scene.get("items", [])
    owner = [-1] * (W * H)
    for i, item in enumerate(items):
        rows = sprites[item["sprite"]]
        ax, ay = item.get("at", [0, 0])
        for ry, row in enumerate(rows):
            yy = ay + ry
            if 0 <= yy < H:
                base = yy * W
                for rx, ch in enumerate(row):
                    xx = ax + rx
                    if ch != "." and 0 <= xx < W:
                        owner[base + xx] = i
    shown = Counter(owner)
    buried = [i for i in range(len(items)) if shown[i] == 0]
    for i in buried:
        print(f"items[{i}] {items[i]['sprite']} at {items[i].get('at')} shows nowhere")
    print(f"{len(buried)} of {len(items)} placements show nowhere")


def snap(a):
    path = Path(a.scene)
    folder = path.parent / "versions"
    folder.mkdir(exist_ok=True)
    dest = folder / f"{len(list(folder.glob('*.json'))):02d}.json"
    shutil.copy(path, dest)
    print(f"{dest} (revision {revision(path)})")


def diff(a):
    before, after = compose(load(a.old)), compose(load(a.new))
    if before.size != after.size:
        print(f"sizes differ: {before.size} and {after.size}")
        return
    W, H = before.size
    changed = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v else 0)
    count = sum(1 for v in changed.getdata() if v)
    c = 32
    cells = {(x, y) for y in range(0, H, c) for x in range(0, W, c) if changed.crop((x, y, x + c, y + c)).getbbox()}
    boxes, seen = [], set()
    for cell in sorted(cells):
        if cell in seen:
            continue
        stack, group = [cell], []
        seen.add(cell)
        while stack:
            x, y = stack.pop()
            group.append((x, y))
            for dx in (-c, 0, c):
                for dy in (-c, 0, c):
                    n = (x + dx, y + dy)
                    if n in cells and n not in seen:
                        seen.add(n)
                        stack.append(n)
        x0, y0 = min(g[0] for g in group), min(g[1] for g in group)
        x1, y1 = max(g[0] for g in group) + c, max(g[1] for g in group) + c
        bx = changed.crop((x0, y0, x1, y1)).getbbox()
        boxes.append((x0 + bx[0], y0 + bx[1], x0 + bx[2], y0 + bx[3]))
    print(f"{count} pixels changed, in {len(boxes)} box(es): " +
          ", ".join(f"x {b[0]}-{b[2] - 1} y {b[1]}-{b[3] - 1}" for b in boxes))
    if not boxes:
        return
    pairs = []
    for b in boxes[:6]:
        pad = (max(0, b[0] - 4), max(0, b[1] - 4), min(W, b[2] + 4), min(H, b[3] + 4))
        pairs.append((before.crop(pad), after.crop(pad)))
    widest = max(p[0].width for p in pairs)
    tallest = sum(p[0].height for p in pairs)
    px = max(1, min(MAX_PX, (BUDGET // 2 - 12) // widest, (BUDGET - 12 * len(pairs)) // tallest))
    sheet = Image.new("RGB", (2 * widest * px + 12, sum(p[0].height * px + 12 for p in pairs)), BACK)
    top = 0
    for old, new in pairs:
        sheet.paste(enlarge(old, px), (0, top))
        sheet.paste(enlarge(new, px), (widest * px + 12, top))
        top += old.height * px + 12
    sheet.save(a.out)
    print(f"before | after at {px} px per pixel -> {a.out}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("overview")
    o.add_argument("scene")
    o.add_argument("out")
    o.add_argument("--tiles", type=int, default=128)
    o.add_argument("--box")
    o.add_argument("--lines", action="store_true")
    r = sub.add_parser("region")
    r.add_argument("scene")
    r.add_argument("out")
    for k in ("x", "y", "w", "h"):
        r.add_argument(k, type=int)
    r.add_argument("--margin", type=int, default=16)
    r.add_argument("--px", type=int)
    ol = sub.add_parser("outline")
    ol.add_argument("scene")
    for k in ("x", "y", "w", "h"):
        ol.add_argument(k, type=int, nargs="?")
    ol.add_argument("--quiet", help="comma-separated sprites to leave out of the per-placement lines")
    t = sub.add_parser("trace")
    t.add_argument("scene")
    t.add_argument("x", type=int)
    t.add_argument("y", type=int)
    hd = sub.add_parser("hidden")
    hd.add_argument("scene")
    s = sub.add_parser("snap")
    s.add_argument("scene")
    df = sub.add_parser("diff")
    df.add_argument("old")
    df.add_argument("new")
    df.add_argument("out")
    a = p.parse_args()
    {"overview": overview, "region": region, "outline": outline, "trace": trace,
     "hidden": hidden, "snap": snap, "diff": diff}[a.cmd](a)


if __name__ == "__main__":
    main()
