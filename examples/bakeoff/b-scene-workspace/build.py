"""Assemble scene.json from the background brushes and the hand-drawn sprites in hand/.

A hand sprite file looks like:

    at 120 190          (one or more placements)
    z 4                 (stacking: sky 0, stars 1, mountains 2, forest 3, lake 5, snow 8)
    shadow yes          (optional: the sprite throws a moon shadow on the snow)
    note the cabin
    ---
    ..rows..

Tone letters (see lib.TONES) are expanded into dithered colours at the
placement's canvas position.
"""

import sys
from pathlib import Path

import bg
import numpy as np
from lib import HERE, H, W, bbox, expand_tones, rows_of, save_json

Z_BG = {"bg_sky": 0, "bg_mountains": 2, "bg_forest": 3, "bg_lake": 5, "bg_snow": 8, "bg_rocks": 8.5,
        "bg_grass": 8.6}


def read_hand(path):
    head, _, body = path.read_text().partition("\n---\n")
    spec = {"ats": [], "z": 9.0, "note": None, "colors": {"K": "black"}, "shadow": False}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition(" ")
        if key == "at":
            spec["ats"].append(tuple(int(v) for v in val.split()))
        elif key == "z":
            spec["z"] = float(val)
        elif key == "note":
            spec["note"] = val
        elif key == "shadow":
            spec["shadow"] = val.strip() == "yes"
        elif key == "reflect":
            spec["reflect"] = val.strip() == "yes"
        elif key == "colors":
            for pair in val.split():
                k, _, v = pair.partition("=")
                spec["colors"][k] = v
    rows = [r for r in body.split("\n") if r.strip() != ""]
    width = max(len(r) for r in rows)
    spec["rows"] = [r.ljust(width, ".") for r in rows]
    return spec


def main():
    hand = [(p.stem, read_hand(p)) for p in sorted((HERE / "hand").glob("*.txt"))]
    caster = np.zeros((H, W), bool)
    reflect = []  # (z, letter grid, x, y) of sprites that also show in the lake
    for _, spec in hand:
        for ax, ay in spec["ats"]:
            rows = expand_tones(spec["rows"], ax, ay)
            if spec.get("reflect"):
                reflect.append((spec["z"], rows, ax, ay))
            if spec["shadow"]:
                for ry, row in enumerate(rows):
                    for rx, ch in enumerate(row):
                        if ch != "." and 0 <= ax + rx < W and 0 <= ay + ry < H:
                            caster[ay + ry, ax + rx] = True
    reflect.sort(key=lambda r: r[0])
    letters, layers, stars, _ = bg.make(caster if caster.any() else None, [r[1:] for r in reflect])
    sprites = {}
    placed = []  # (z, order, item)
    order = 0
    for name, mask, note in layers:
        x0, y0, x1, y1 = bbox(mask)
        sprites[name] = rows_of(letters, mask, x0, y0, x1, y1)
        placed.append((Z_BG[name], order, {"sprite": name, "at": [x0, y0], "colors": {"K": "black"},
                                           "note": note}))
        order += 1
    sprites.update(bg.STAR_SPRITES)
    for x, y, kind, name in stars:
        spr = bg.KIND_SPRITE[kind]
        off = 1 if spr in ("star_plus", "star_dim_plus") else 0
        item = {"sprite": spr, "at": [x - off, y - off]}
        if name:
            item["note"] = name
        placed.append((1, order, item))
        order += 1
    # the brighter stars low in the sky glimmer in the still water too
    lake = next(mask for name, mask, _ in layers if name == "bg_lake")
    for x, y, kind, _name in stars:
        if kind not in ("W", "C", "Y", "plus"):
            continue
        ry = 2 * bg.YW - 1 - y
        rx = x + (1 if (x * 7 + y) % 3 == 0 else 0)
        if bg.YW <= ry < H and rx < W and lake[ry, rx] and letters[ry, rx] in ("K", "B"):
            spr = {"W": "star_c", "plus": "star_c", "C": "star_b", "Y": "star_y"}[kind]
            placed.append((5.4, order, {"sprite": spr, "at": [rx, ry], "note": "star in the lake"}))
            order += 1
    for base, spec in hand:
        for k, (ax, ay) in enumerate(spec["ats"]):
            name = base if len(spec["ats"]) == 1 else f"{base}_{k}"
            sprites[name] = expand_tones(spec["rows"], ax, ay)
            item = {"sprite": name, "at": [ax, ay], "colors": spec["colors"]}
            if spec["note"]:
                item["note"] = spec["note"]
            placed.append((spec["z"], order, item))
            order += 1
    placed.sort(key=lambda p: (p[0], p[1]))
    scene = {"size": [384, 384], "sprites": sprites, "items": [p[2] for p in placed]}
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "scene.json"
    save_json(out, scene)
    print(f"wrote {out}: {len(sprites)} sprites, {len(scene['items'])} items")


if __name__ == "__main__":
    main()
