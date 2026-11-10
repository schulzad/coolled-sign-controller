"""Background brush: sky, aurora, stars, mountains, far forest, lake, near snow.

Everything is computed as continuous RGB, then ordered-dithered once with a
canvas-aligned threshold, and cut into sprites by layer masks.  Magenta in the
aurora is dithered on the inverted threshold so it interleaves with the green
instead of turning it white.
"""

import math

import fg
import numpy as np
from lib import (
    RGB,
    THR,
    THR8,
    XX,
    YY,
    H,
    W,
    blur,
    catmull,
    cool,
    dither,
    expand_tones,
    fbm,
    smoothstep,
    vnoise,
)

HZ = 206.0   # horizon row
YW = 209     # first lake row (far waterline)
F = 332.0    # focal length in pixels
HC = 1.2     # camera height, m
LIGHT = np.array([0.55, 0.5, -0.67])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

# ---------------------------------------------------------------- sky + aurora

CURTAIN_A = [  # x, lower edge y, height, gain   (near curtain sweeping up-left)
    (-60, 10, 150, 0.5), (-10, 33, 150, 0.68), (40, 58, 140, 0.92), (90, 86, 128, 1.05),
    (135, 111, 110, 1.1), (175, 132, 92, 1.18), (210, 145, 74, 1.12), (240, 152, 60, 0.55),
    (262, 156, 50, 0.0), (300, 160, 40, 0.0),
]
CURTAIN_B = [  # far curtain, behind A, rising off to the right behind the peak
    (150, 120, 50, 0.0), (180, 127, 54, 0.5), (210, 132, 58, 0.85), (245, 131, 58, 0.95),
    (280, 124, 54, 0.9), (320, 115, 48, 0.85), (360, 108, 42, 0.75), (420, 100, 36, 0.6),
]


def curtain(ctrl, seed):
    xs = np.arange(W) + 0.5
    ylow = catmull(xs, [(c[0], c[1]) for c in ctrl])
    hgt = catmull(xs, [(c[0], c[2]) for c in ctrl])
    gain = np.clip(catmull(xs, [(c[0], c[3]) for c in ctrl]), 0, None)
    X = XX + 0.5
    Y = YY + 0.5
    d = ylow[None, :] - Y
    dp = np.clip(d, 0, None)
    f = dp / (ylow[None, :] + 520.0)
    u = X + (192.0 - X) * f
    r = fbm(u / 4.2, dp / 38.0 + seed * 3.1, seed, octaves=3)
    r = 0.12 + 0.88 * np.clip((r - 0.22) / 0.62, 0, 1) ** 1.15
    hm = 0.45 + 0.95 * fbm(u / 12.0, 5.0 + seed, seed + 9, octaves=2)
    hh = hgt[None, :] * hm
    above = np.exp(-dp / (0.42 * hh))
    edge = np.exp(-dp / 2.4)
    below = np.exp(np.clip(d, None, 0) / 1.1)
    g = gain[None, :] * below
    inten = g * (r * above + (0.5 + 0.5 * r) * 0.55 * edge)
    rel = dp / hh
    P = g * r * smoothstep(0.6, 1.05, rel) * (1 - smoothstep(1.1, 1.8, rel))
    return inten, P


def sky_and_aurora():
    rgb = np.zeros((H, W, 3))
    y = YY + 0.5
    s = 0.33 * np.clip(y / HZ, 0, 1) ** 1.8
    IA, PA = curtain(CURTAIN_A, 1)
    IB, PB = curtain(CURTAIN_B, 2)
    inten = 1.12 * IA + 0.95 * IB
    glow = blur(np.clip(inten, 0, 1.2), 7)
    mag = np.clip(0.27 * PA + 0.1 * PB, 0, 0.26)
    white = np.clip((inten - 1.0) * 0.8, 0, 0.4)
    rgb[..., 0] = white
    rgb[..., 1] = np.clip(inten + 0.14 * glow, 0, 1)
    rgb[..., 2] = s * (1 - 0.8 * np.clip(inten, 0, 1)) + white
    return np.clip(rgb, 0, 1), mag, inten


# ---------------------------------------------------------------- mountains (2D, faceted)

MOUNTAINS = [
    dict(name="distant", seed=61, fade=0.3, snowiness=0.72, light=[0.55, 0.85],
         sky=[(96, 190), (112, 184), (126, 181), (140, 177), (152, 179), (163, 176), (176, 172),
              (188, 175), (201, 171), (214, 175), (228, 172), (244, 176), (262, 180)],
         ridges=[dict(pts=[(176, 172), (178, 190), (180, 209)], ext=-1)]),
    dict(name="hills", seed=62, fade=0.0, snowiness=0.12, light=[0.15],
         sky=[(118, 196), (134, 191), (150, 188), (166, 190), (182, 186), (198, 188), (214, 184),
              (230, 187), (246, 183), (262, 186)],
         ridges=[]),
    dict(name="left", seed=63, fade=0.18, snowiness=0.62, light=[0.32, 0.86, 0.6],
         sky=[(-4, 171), (10, 164), (22, 160), (34, 156), (44, 151), (52, 149), (58, 146), (63, 148),
              (69, 152), (74, 155), (80, 154), (86, 158), (94, 164), (104, 170), (116, 175),
              (128, 181), (142, 186), (156, 190), (170, 194)],
         ridges=[dict(pts=[(58, 146), (60, 160), (62, 176), (63, 192), (64, 209)], ext=0),
                 dict(pts=[(80, 154), (84, 170), (88, 188), (90, 209)], ext=1)]),
    dict(name="peak", seed=64, fade=0.08, snowiness=0.66, light=[0.24, 0.36, 0.9, 0.62],
         sky=[(178, 196), (190, 192), (200, 188), (210, 184), (220, 179), (230, 174), (238, 170),
              (246, 164), (253, 159), (260, 152), (266, 146), (272, 140), (278, 134), (284, 128),
              (289, 123), (294, 118), (298, 115), (301, 117), (305, 121), (310, 127), (315, 132),
              (320, 135), (325, 134), (329, 133), (334, 138), (341, 145), (350, 150), (360, 154),
              (372, 158), (388, 161)],
         ridges=[dict(pts=[(266, 146), (264, 162), (261, 180), (258, 209)], ext=-1),
                 dict(pts=[(298, 115), (296, 130), (293, 146), (291, 162), (289, 180), (288, 209)], ext=0),
                 dict(pts=[(329, 133), (326, 150), (322, 172), (319, 209)], ext=1)]),
]


def mountains():
    rgb = np.zeros((H, W, 3))
    mask = np.zeros((H, W), bool)
    xs = np.arange(W) + 0.5
    ys = np.arange(H) + 0.5
    for m in MOUNTAINS:
        sx = np.array([p[0] for p in m["sky"]], float)
        sy = np.array([p[1] for p in m["sky"]], float)
        top = np.interp(xs, sx, sy)
        top = top + 1.6 * (fbm(xs / 2.5, 3.0 + 0 * xs, m["seed"], 3) - 0.5)
        inside_x = (xs >= sx[0]) & (xs <= sx[-1])
        body = (ys[:, None] >= top[None, :]) & inside_x[None, :] & (ys[:, None] < YW)
        apex_y = sy.min()
        # face index from the ridges
        face = np.zeros((H, W), int)
        for rd in m["ridges"]:
            ry = np.array([p[1] for p in rd["pts"]], float)
            rx = np.array([p[0] for p in rd["pts"]], float)
            xr = np.interp(ys, ry, rx) + 1.3 * (fbm(ys / 3.0, 7.0 + 0 * ys, m["seed"] + 3, 2) - 0.5)
            if rd["ext"] < 0:
                xr = np.where(ys < ry[0], -1e9, xr)
            elif rd["ext"] > 0:
                xr = np.where(ys < ry[0], 1e9, xr)
            face += (xs[None, :] > xr[:, None])
        light = np.array(m["light"], float)[np.clip(face, 0, len(m["light"]) - 1)]
        X, Y = XX + 0.5, YY + 0.5
        left_of_main = light < 0.5
        shear = np.where(left_of_main, 0.38, -0.38)
        u = X + (Y - apex_y) * shear
        rel = np.clip((Y - apex_y) / max(YW - apex_y, 1), 0, 1)
        n = fbm(u / 2.3, Y / 15.0, m["seed"] + 5, 3)
        thr = (1 - m["snowiness"]) + 0.32 * rel - 0.12
        snow = n > thr
        v_snow = 0.1 + 0.55 * light ** 1.4 + 0.09 * np.clip((n - thr) / 0.25, 0, 1) * light
        v_rock = 0.03 + 0.14 * light
        v = np.where(snow, v_snow, v_rock)
        forest = Y > YW - 8 - 4 * fbm(X / 6.0, 2.0 + 0 * X, m["seed"] + 8, 2)
        v = np.where(forest, 0.05 + 0.05 * light, v)
        v = v * (1 - m["fade"]) + 0.133 * m["fade"]
        v = np.round(v * 12) / 12
        col = cool(v)
        rgb[body] = col[body]
        mask |= body
    return rgb, mask


# ---------------------------------------------------------------- far forest

def forest(rng):
    rgb = np.zeros((H, W, 3))
    mask = np.zeros((H, W), bool)
    x = -4.0
    trees = []
    while x < W + 6:
        if x < 95:
            hgt = rng.uniform(15, 28)
        elif x < 104:
            hgt = rng.uniform(9, 14)
        elif x < 142:
            hgt = rng.uniform(13, 22)   # stand of spruce behind the cabin
        elif x < 165:
            hgt = rng.uniform(10, 18)
        elif x < 255:
            hgt = rng.uniform(7, 15)
        else:
            hgt = rng.uniform(13, 25)
        if hgt > 4:
            trees.append((x, YW - 2 - rng.uniform(0.0, 2.0), hgt))
        x += rng.uniform(2.0, 4.6)
    trees.sort(key=lambda t: t[2])
    for cx, base, hgt in trees:
        top = base - hgt
        period = max(3.0, hgt / 6.0)
        for y in range(int(top), int(base) + 1):
            r = y - top
            if r < 0:
                continue
            frac = (r % period) / period
            w = 0.6 + r * 0.27 * (0.62 + 0.38 * frac)
            x0, x1 = int(round(cx - w)), int(round(cx + w))
            for xi in range(x0, x1 + 1):
                if 0 <= xi < W and 0 <= y < YW:
                    side = (xi - cx) / max(w, 0.8)
                    lit = smoothstep(0.2, 1.0, side) * (0.3 + 0.7 * frac)
                    v = 0.02 + 0.26 * lit * (0.6 + 0.4 * vnoise(xi * 0.9, y * 0.9, 21))
                    rgb[y, xi] = cool(v)
                    mask[y, xi] = True
    # thin, broken snow line along the far shore
    for xi in range(W):
        n = vnoise(xi / 2.5, 0.5, 4)
        y = YW - 1
        v = 0.3 + 0.35 * n if n > 0.3 else 0.06
        rgb[y, xi] = cool(v)
        mask[y, xi] = True
    return rgb, mask


# ---------------------------------------------------------------- lake

def shore_y():
    """Row where the near snow begins, per column."""
    xs = np.arange(W) + 0.5
    y = (301 + 3.0 * np.sin(xs / 29.0 + 0.7) + 2.2 * (fbm(xs / 10.0, 3.0 + 0 * xs, 8, 3) - 0.5)
         + 42 * smoothstep(150, 262, xs))
    return y


def lake(above, mag, shore):
    rgb = np.zeros((H, W, 3))
    lmag = np.zeros((H, W))
    mask = np.zeros((H, W), bool)
    src = blur(above, 1, passes=1)
    xs = np.arange(W) + 0.5
    for y in range(YW, H):
        depth = y - YW + 0.5
        k = depth / 90.0
        amp = 0.15 + 2.6 * k ** 2
        wob = np.sin(xs / (9 + 25 * k) + y * 1.7) * 0.5 + (vnoise(xs / 14.0, y / 2.2, 31) - 0.5) * 1.6
        sx = np.clip(np.round(xs - 0.5 + amp * wob), 0, W - 1).astype(int)
        jit = (vnoise(xs / 6.0, y / 1.3, 33) - 0.5) * 2.5 * k
        sy = np.clip(np.round(2 * YW - 1 - y + jit), 0, YW - 1).astype(int)
        dark = 0.66 - 0.25 * min(k, 1.2)
        col = src[sy, sx] * dark
        col[:, 2] = col[:, 2] + 0.07
        lip = np.clip(shore - y, 0, 9)
        col = col * (0.35 + 0.65 * smoothstep(0.5, 3.0, lip))[:, None]
        rows = y < shore
        rgb[y, rows] = col[rows]
        lmag[y, rows] = (mag[sy, sx] * dark)[rows]
        mask[y, rows] = True
    return np.clip(rgb, 0, 1), lmag, mask


# ---------------------------------------------------------------- near snow

# (the near snow, rocks and shadows live in fg.py)


# ---------------------------------------------------------------- stars

DIPPER = [  # name, RA hours, Dec degrees
    ("Dubhe", 11.062, 61.75), ("Merak", 11.031, 56.38), ("Phecda", 11.897, 53.69),
    ("Megrez", 12.257, 57.03), ("Alioth", 12.900, 55.96), ("Mizar", 13.399, 54.93),
    ("Alkaid", 13.792, 49.31),
]


def stars(rng, inten, covered):
    out = []
    taken = set()

    def ok(x, y):
        return (0 <= x < W and 0 <= y < YW and not covered[y, x] and inten[y, x] < 0.18
                and all((x + dx, y + dy) not in taken for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)))
    k = 3.6
    x0, y0 = 356, 14
    for name, ra, dec in DIPPER:
        x = int(round(x0 - k * (ra - 11.062) * 15 * math.cos(math.radians(55.5))))
        y = int(round(y0 - k * (dec - 61.75)))
        kind = "dim_plus" if name == "Megrez" else "plus"
        out.append((x, y, kind, name))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                taken.add((x + dx, y + dy))
    n = 0
    tries = 0
    while n < 230 and tries < 20000:
        tries += 1
        x = int(rng.uniform(0, W))
        y = int(rng.uniform(0, YW))
        if rng.random() < y / YW * 0.8:
            continue
        if not ok(x, y):
            continue
        r = rng.random()
        if r < 0.004:
            kind = "dim_plus"
        elif r < 0.55:
            kind = "W"
        elif r < 0.78:
            kind = "C"
        elif r < 0.88:
            kind = "B"
        elif r < 0.96:
            kind = "Y"
        else:
            kind = "M"
        out.append((x, y, kind, None))
        taken.add((x, y))
        n += 1
    return out


STAR_SPRITES = {
    "star_w": ["W"],
    "star_c": ["C"],
    "star_b": ["B"],
    "star_y": ["Y"],
    "star_m": ["M"],
    "star_plus": [".C.", "CWC", ".C."],
    "star_dim_plus": [".B.", "BCB", ".B."],
}
KIND_SPRITE = {"W": "star_w", "C": "star_c", "B": "star_b", "Y": "star_y", "M": "star_m",
               "plus": "star_plus", "dim_plus": "star_dim_plus"}


# ---------------------------------------------------------------- assemble

def make(caster=None, reflect=()):
    """reflect: (rows, x, y) letter sprites standing above the water, mirrored in the lake."""
    rng = np.random.default_rng(7)
    sky, mag, inten = sky_and_aurora()
    m_rgb, m_mask = mountains()
    f_rgb, f_mask = forest(rng)
    above = sky.copy()
    above[m_mask] = m_rgb[m_mask]
    above[f_mask] = f_rgb[f_mask]
    # chimney smoke: a soft plume drifting right, thinning as it rises
    t = np.clip((189.0 - (YY + 0.5)) / 40.0, 0, 1)
    cx = 114.8 + 15 * t ** 1.6 + 1.2 * np.sin(t * 7.0)
    width = 0.8 + 4.5 * t
    plume = np.exp(-(((XX + 0.5 - cx) / width) ** 2)) * (1 - t) ** 1.3 * (YY < 189) * (YY > 145)
    plume = plume * (0.75 + 0.5 * fbm((XX + 0.5) / 3.0, (YY + 0.5) / 4.0, 91, 2))
    above = above + plume[..., None] * np.array([0.0, 0.36, 0.42])
    above = np.clip(above, 0, 1)
    h_mask = np.zeros((H, W), bool)
    for rows, ax, ay in reflect:
        for ry, row in enumerate(rows):
            for rx, ch in enumerate(row):
                x, y = ax + rx, ay + ry
                if ch != "." and 0 <= x < W and 0 <= y < YW:
                    above[y, x] = np.array(RGB[ch]) / 255.0
                    h_mask[y, x] = True
    amag = np.where(m_mask | f_mask | h_mask, 0.0, mag)
    shore = shore_y()
    l_rgb, l_mag, l_mask = lake(above, amag, shore)
    s_rgb, s_mask, r_mask, sparkle, _, tufts = fg.snow(shore, rng, caster)
    l_mask &= ~r_mask
    full = above.copy()
    full[l_mask] = l_rgb[l_mask]
    near = s_mask | r_mask
    full[near] = s_rgb[near]
    allmag = np.where(l_mask, l_mag, np.where(near, 0.0, amag))
    sky_mask = np.zeros((H, W), bool)
    sky_mask[:YW] = True
    sky_mask &= ~m_mask & ~f_mask
    fine = sky_mask | l_mask
    letters = np.where(fine, dither(full, THR8), dither(full, THR))
    inv = np.where(fine, 1.0 - THR8, 1.0 - THR)
    letters = np.where(inv < allmag, "M", letters)
    for sx_, sy_ in sparkle:
        letters[sy_, sx_] = "W"
    g_mask = np.zeros((H, W), bool)
    for (gx_, gy_), ch in tufts.items():
        letters[gy_, gx_] = expand_tones([ch], gx_, gy_)[0]
        g_mask[gy_, gx_] = True
    s_mask = s_mask & ~g_mask
    layers = [
        ("bg_sky", sky_mask, "night sky and aurora"),
        ("bg_mountains", m_mask & ~f_mask, "far mountains"),
        ("bg_forest", f_mask, "far shore forest"),
        ("bg_lake", l_mask, "lake reflection"),
        ("bg_snow", s_mask, "near snow"),
        ("bg_rocks", r_mask, "boulder and shore rock"),
        ("bg_grass", g_mask, "dry grass in the snow"),
    ]
    st = stars(rng, inten, m_mask | f_mask | h_mask)
    return letters, layers, st, {"I": inten, "shore": shore, "above": above, "full": full}
