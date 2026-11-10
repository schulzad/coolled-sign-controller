"""Foreground brush: near snow with drifts, the fox's boulder, a shore rock,
fox tracks, cast shadows and frost sparkles.  Values are on the cool ramp
(black - blue - cyan - white) and posterised to quarter steps between colours.
"""

import numpy as np
from lib import XX, YY, H, W, cool, fbm, line_pts, poly_mask, smoothstep

HZ = 206.0
F = 332.0
HC = 1.2

MOUNDS = [  # cx, cy, sx, sy, height (screen-space drifts)
    (40, 352, 150, 34, 12), (215, 392, 120, 24, 7), (330, 390, 90, 16, 5), (150, 318, 90, 12, 3),
]

BOULDER = [(257, 358), (259, 347), (263, 337), (270, 328), (281, 321), (295, 316.5), (311, 314.5),
           (326, 315), (339, 318), (349, 323.5), (355.5, 331), (358.5, 341), (358.5, 353), (356, 367),
           (353, 380), (257, 380)]
# the snowy top seen from above, down to the lip where it turns into the front face
B_FRONT = [(256, 357.5), (262, 350), (270, 345), (281, 341.5), (294, 339.5), (308, 339), (322, 339.5),
           (335, 341.5), (346, 345.5), (353, 350.5), (358, 356)]
B_DRIPS = [(276, 342, 2), (299, 339, 1), (321, 340, 2), (338, 342, 1), (350, 348, 2)]
B_RIDGE = [(305, 340), (308, 352), (311, 365), (313, 380)]
B_CREASE = [(343, 344), (346, 356), (347, 368), (347, 380)]
TOP_H = 0.3     # height of the boulder's top above the snow, m
FOX_Z = 2.25    # depth of the fox sitting on it, m
B_CRACKS = [[(268, 360), (276, 361), (284, 360), (291, 364)], [(321, 353), (328, 356), (334, 355)],
            [(290, 347), (294, 352), (293, 357)], [(330, 365), (337, 368)]]

SHORE_ROCK = [(65, 307), (68, 303), (73, 300.5), (80, 299), (88, 299), (94, 300.5), (98, 303.5), (100, 307)]
SR_CAP = [(68, 303), (73, 300.5), (80, 299), (88, 299), (94, 300.5), (98, 303.5), (92, 302.5), (84, 302),
          (76, 302.5)]
SR_RIDGE = [(84, 299), (86, 307)]

TRACK = [(-1.95, 3.15), (-0.55, 2.80), (0.42, 2.47)]  # quadratic path in world X, Z (m)


def x_at(ridge, y):
    ry = np.array([p[1] for p in ridge], float)
    rx = np.array([p[0] for p in ridge], float)
    return np.interp(y, ry, rx)


def top_edge(mask):
    """First row of the mask in each column (H where empty)."""
    any_ = mask.any(axis=0)
    first = np.argmax(mask, axis=0)
    return np.where(any_, first, H)


def project_shadow(mask, zf, plane_h):
    """Moon shadow of a flat cut-out standing at depth zf, thrown onto a level plane."""
    ys, xs = np.nonzero(mask)
    X = (xs + 0.5 - 192) * zf / F
    Yr = np.clip(HC - (ys + 0.5 - HZ) * zf / F - plane_h, 0, None)
    Xs = X - 0.62 * Yr
    Zs = zf + 0.85 * Yr
    sx = np.round(192 + F * Xs / Zs - 0.5).astype(int)
    sy = np.round(HZ + F * (HC - plane_h) / Zs - 0.5).astype(int)
    out = np.zeros((H, W), bool)
    ok = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
    out[sy[ok], sx[ok]] = True
    grown = out.copy()
    grown[1:, :] |= out[:-1, :]
    grown[:, 1:] |= out[:, :-1]
    return grown & ~mask


def fox_shadow_on_top(caster):
    return project_shadow(caster, FOX_Z, TOP_H)


def boulder(seed=71, caster=None):
    m = poly_mask(BOULDER)
    x = XX + 0.5
    y = YY + 0.5
    ridge = x_at(B_RIDGE, y)
    crease = x_at(B_CREASE, y)
    # left face toward the aurora is darkest; the front-right face takes the moon
    v = np.where(x < ridge, 0.083, np.where(x < crease, 0.25, 0.167))
    tex = fbm(x / 3.5, y / 2.5, seed, 3)
    v = v + np.where(tex > 0.64, 0.083, 0) - np.where(tex < 0.33, 0.083, 0)
    v = np.where((x < ridge) & (y > 368), v - 0.083, v)
    for crack in B_CRACKS:
        for cx, cy in line_pts(crack):
            v[cy, cx] = 0.0
            v[cy + 1, cx] = max(v[cy + 1, cx], 0.25)
    for cx, cy in line_pts(B_RIDGE):
        v[cy, cx + 1] = max(v[cy, cx + 1], 0.333)
    fx = np.array([p[0] for p in B_FRONT], float)
    fy = np.array([p[1] for p in B_FRONT], float)
    lip = np.interp(x, fx, fy)
    cap = m & (y < lip)
    for dx, dy, n in B_DRIPS:
        for k in range(n + 1):
            cap[dy + k, dx] = True
            if k < n:
                cap[dy + k, dx + 1] = True
    cap &= m
    # snow on the top: brighter toward the moon (right) and toward the lip, a soft rim at the far edge
    top = top_edge(m)
    rel = np.clip((y - top[None, :]) / np.maximum(lip - top[None, :], 1), 0, 1)
    cap_v = 0.6 + 0.07 * (x - 300) / 50 + 0.05 * rel
    cap_v = np.where(YY <= top[None, :] + 1, 0.5, cap_v)
    cap_v = np.where((y > lip - 1.5) & (y < lip), cap_v + 0.08, cap_v)
    if caster is not None:
        cap_v = np.where(fox_shadow_on_top(caster), cap_v - 0.09, cap_v)
        near = np.zeros_like(caster)
        for dy in (1, 2):
            for dx in (-1, 0, 1, 2):
                near |= np.roll(np.roll(caster, dy, axis=0), -dx, axis=1)
        cap_v = np.where(near & ~caster & (y > lip - 4), np.minimum(cap_v, 0.5), cap_v)
    v = np.where(cap, np.round(cap_v * 12) / 12, v)
    # a dark seam where the snow overhangs the rock
    seam = m & ~cap & np.roll(cap, 1, axis=0)
    v = np.where(seam, 0.0, v)
    # a faint aurora rim down the left edge
    left = m & ~np.roll(m, 1, axis=1) & ~cap & (y < 372)
    v = np.where(left, 0.333, v)
    return m, np.clip(v, 0, 1)


def shore_rock():
    m = poly_mask(SHORE_ROCK)
    x = XX + 0.5
    y = YY + 0.5
    ridge = x_at(SR_RIDGE, y)
    v = np.where(x < ridge, 0.083, 0.25)
    cap = poly_mask(SR_CAP) & m
    v = np.where(cap, np.where(x < 78, 0.583, 0.75), v)
    seam = m & ~cap & np.roll(cap, 1, axis=0)
    v = np.where(seam, 0.0, v)
    return m, v


TUFTS = [  # base x, base y, stalk count, tallest stalk (px)
    (16, 374, 6, 22), (34, 380, 4, 14), (55, 368, 5, 15), (5, 354, 3, 12), (247, 378, 4, 12),
]


def grass(rng):
    """Dry grass stalks poking out of the snow: one-pixel lines fanning from each tuft's root,
    red-brown low down and straw-yellow where the moon catches the tips."""
    out = {}
    for bx, by, n, tall in TUFTS:
        for k in range(n):
            spread = (k - (n - 1) / 2) / max(n - 1, 1)
            h = tall * (1.0 - 0.55 * abs(spread)) * rng.uniform(0.8, 1.05)
            lean = 0.75 * spread + rng.uniform(-0.08, 0.08)
            droop = 0.35 * spread
            x0 = bx + 2.0 * spread
            last = None
            for i in range(int(h) * 3 + 1):
                t = i / (h * 3)
                x = x0 + lean * h * t + droop * h * t * t
                y = by - h * t + droop * h * t * t * 0.6
                p = (int(round(x)), int(round(y)))
                if p == last:
                    continue
                last = p
                lit = spread > -0.1
                if t > 0.7:
                    out[p] = "Y" if lit else "R"
                elif t > 0.3:
                    out[p] = "R" if lit else "d"
                else:
                    out[p] = "e"
    return out


def tracks():
    (x0, z0), (x1, z1), (x2, z2) = TRACK
    out = []
    for t in np.linspace(0, 1, 9)[:-1]:
        Xp = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t * t * x2
        Zp = (1 - t) ** 2 * z0 + 2 * (1 - t) * t * z1 + t * t * z2
        out.append((192 + F * Xp / Zp, HZ + F * HC / Zp, F * 0.055 / Zp))
    return out


def snow(shore, rng, caster=None):
    """caster: optional boolean mask of things standing on the snow (the fox),
    whose shadows are thrown up and to the left, away from the moon."""
    x = XX + 0.5
    y = YY + 0.5
    Z = F * HC / np.clip(y - HZ, 1, None)
    X = (x - 192.0) * Z / F
    # a gently rolling snowfield: soft swells parallel to the shore, compressed by distance
    swell = np.sin(Z * 5.5 + 1.1 * np.sin(X * 1.4 + 0.5) + 0.6 * np.sin(X * 3.1))
    edge = y - shore[None, :]
    depth = np.clip(edge / 75.0, 0, 1)
    v = 0.535 - 0.08 * depth + 0.045 * swell
    v = v + 0.09 * (1 - smoothstep(0.0, 2.5, edge))
    vign = (1 - 0.16 * np.clip((y - 318) / 66.0, 0, 1) ** 1.5
            - 0.14 * np.clip(np.abs(x - 192) / 192.0, 0, 1) ** 3)
    v = np.maximum(v * vign, 0.4)
    b_mask, b_v = boulder(caster=caster)
    r_mask, r_v = shore_rock()
    # snow drifted against the boulder's foot hides its base
    drift_top = 371 + 2.0 * np.sin(x / 6.0 + 1) + 1.5 * (fbm(x / 4.0, 2.0 + 0 * x, 75, 2) - 0.5)
    b_vis = b_mask & (y < drift_top)
    r_vis = r_mask & (y < 305 + 0 * x)
    # cast shadows: boulder (and caster) pushed away from the light
    shadow = project_shadow(b_vis & (y > 336), 2.3, 0.0) | project_shadow(r_vis, 3.94, 0.0)
    if caster is not None:
        shadow |= project_shadow(caster, FOX_Z, 0.0)
    src = b_vis | r_vis
    shadow &= ~src
    v = np.where(shadow, v - 0.1, v)
    for px, py, pw in tracks():
        hw, hh = pw / 2, max(pw * 0.24, 0.9)
        e = ((x - px) / hw) ** 2 + ((y - py) / hh) ** 2
        lip = ((x - px) / hw) ** 2 + ((y - py + 1.3) / hh) ** 2
        v = np.where(e < 1, v - 0.13, v)
        v = np.where((e >= 1) & (lip < 1), v + 0.08, v)
    v = np.round(v * 12) / 12
    land = y >= shore[None, :]
    vv = np.where(b_vis, b_v, np.where(r_vis, r_v, v))
    rock = b_vis | r_vis
    rgb = np.zeros((H, W, 3))
    mask = land | rock
    rgb[mask] = cool(vv)[mask]
    cand = np.argwhere(land & ~rock & ~shadow & (v >= 0.5) & (y > shore[None, :] + 3))
    sparkle = [(int(c[1]), int(c[0])) for c in cand[rng.choice(len(cand), 55, replace=False)]]
    tufts = {p: c for p, c in grass(rng).items() if 0 <= p[0] < W and 0 <= p[1] < H and land[p[1], p[0]]}
    return rgb, land & ~rock, rock, sparkle, shadow, tufts
