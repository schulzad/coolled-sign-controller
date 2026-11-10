#!/usr/bin/env python3
"""Night train on a stone viaduct under the aurora.

384x384, the eight corners of the RGB cube only. This script is the source of
truth for final.png: every pixel is placed here, rerun to regenerate.

Brief
  palette  K B G C R M Y W (hard budget 8, given)
  light    moonlight from the upper left (out of frame); aurora glow overhead;
           warm practicals: carriage windows, firebox, headlamp
  depth    sky (aurora, stars) / mountains + forest / viaduct + train / lake
  outline  none on the landscape (value contrast carries it); black is the
           darkest shade of every dark material
"""
import os
import sys

sys.path.insert(0, "/Users/adamschulz/source/hacking/pixel-bakeoff/tools/pixel-art-studio/scripts")
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pixelstudio import BAYER4, BAYER8, Sprite  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
W = H = 384

# palette index = r<<2 | g<<1 | b
K, B, G, C, R, M, Y, WH = range(8)
RGB = np.array([[255 * ((i >> 2) & 1), 255 * ((i >> 1) & 1), 255 * (i & 1)]
                for i in range(8)], np.uint8)
HEX = ["#{:02x}{:02x}{:02x}".format(*(int(v) for v in c)) for c in RGB]

YY, XX = np.mgrid[0:H, 0:W]
T4 = (np.array(BAYER4)[YY % 4, XX % 4] + 0.5) / 16.0
T8 = (np.array(BAYER8)[YY % 8, XX % 8] + 0.5) / 64.0
CHECK = (XX + YY) % 2 == 0

COOL = [K, B, C, WH]
WARM = [K, R, Y, WH]
MAROON = np.where(CHECK, R, K).astype(np.uint8)

# layout
YR = 250          # rail level, top of the viaduct cornice
YB = 298          # waterline at the piers
YF = 290          # far shore; far water starts below it
RA, YS = 17, 284  # arch radius, springline
ARCH_CX = [24 + 48 * k for k in range(8)]
EYE = (192.0, 300.0)
BACK = 0.955      # barrel depth as a perspective scale toward EYE
LOCO_X = 254
CARS = (54, 99, 144, 189)


# ------------------------------------------------------------------ helpers
def ramp(t, cols, T=T4):
    cols = np.asarray(cols)
    n = len(cols) - 1
    pos = np.clip(t, 0.0, 1.0) * n
    i = np.minimum(np.floor(pos).astype(int), n - 1)
    f = pos - i
    return np.where(f > T, cols[i + 1], cols[i]).astype(np.uint8)


def stack(layers, base=K, T=T4):
    """Ordered multi-colour dither: each layer claims its density of the threshold range."""
    out = np.full((H, W), base, np.uint8)
    acc = np.zeros((H, W))
    free = np.ones((H, W), bool)
    for col, d in layers:
        acc = acc + np.clip(d, 0.0, 1.0)
        hit = free & (T < acc)
        out[hit] = col
        free &= ~hit
    return out


def smooth_curve(pts, xs, passes=3, k=9):
    px = np.array([p[0] for p in pts], float)
    py = np.array([p[1] for p in pts], float)
    y = np.interp(xs, px, py)
    for _ in range(passes):
        yp = np.pad(y, k, mode="edge")
        y = np.convolve(yp, np.ones(k) / k, mode="same")[k:-k]
    return y


def noise1d(x, knots, seed, lo=0.0, hi=1.0):
    """Smooth deterministic 1-D value noise over x (array), knot spacing `knots`."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    x0 = np.floor(x.min() / knots) - 1
    n = int(np.ceil(x.max() / knots) - x0) + 3
    vals = rng.uniform(lo, hi, n)
    u = x / knots - x0
    i = np.floor(u).astype(int)
    f = u - i
    f = f * f * (3 - 2 * f)
    return vals[i] * (1 - f) + vals[i + 1] * f


def noise2d(u, v, seed):
    """Smooth deterministic 2-D value noise, lattice spacing 1 in (u, v)."""
    rng = np.random.default_rng(seed)
    u0 = np.floor(u).astype(int)
    v0 = np.floor(v).astype(int)
    fu = u - u0
    fv = v - v0
    fu = fu * fu * (3 - 2 * fu)
    fv = fv * fv * (3 - 2 * fv)
    iu = u0 - u0.min()
    iv = v0 - v0.min()
    grid = rng.random((iv.max() + 2, iu.max() + 2))
    a_ = grid[iv, iu]
    b_ = grid[iv, iu + 1]
    c_ = grid[iv + 1, iu]
    d_ = grid[iv + 1, iu + 1]
    return (a_ * (1 - fu) + b_ * fu) * (1 - fv) + (c_ * (1 - fu) + d_ * fu) * fv


def blur(img, sigma):
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, img)
    return np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, out)


def poly_mask(pts):
    im = Image.new("L", (W, H), 0)
    ImageDraw.Draw(im).polygon([(float(x), float(y)) for x, y in pts], fill=255)
    return np.array(im) > 0


def mpd(p0, p1, rough, depth, rng):
    """Midpoint displacement between two points (perpendicular jitter)."""
    pts = [np.array(p0, float), np.array(p1, float)]
    for _ in range(depth):
        nxt = [pts[0]]
        for a, b in zip(pts[:-1], pts[1:], strict=True):
            d = b - a
            L = float(np.hypot(d[0], d[1])) + 1e-9
            n = np.array([-d[1], d[0]]) / L
            nxt += [(a + b) / 2 + n * rng.normal() * rough * L, b]
        pts = nxt
    return [(float(p[0]), float(p[1])) for p in pts]


def jag(pts, rough, seed, depth=3):
    rng = np.random.default_rng(seed)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        out += mpd(a, b, rough, depth, rng)[1:]
    return out


def disc(cx, cy, r):
    return (XX - cx) ** 2 + (YY - cy) ** 2 <= r * r


def put(c, a, mask, col):
    if np.isscalar(col):
        c[mask] = col
    else:
        c[mask] = col[mask]
    a |= mask


def box(c, a, x0, y0, x1, y1, col):
    m = np.zeros((H, W), bool)
    m[max(0, y0):max(0, y1 + 1), max(0, x0):max(0, x1 + 1)] = True
    put(c, a, m, col)


# ------------------------------------------------------------------ sky
def streaks(xr, seed):
    """Quasi-random vertical ray pattern, equalised to a uniform 0..1 distribution."""
    rng = np.random.default_rng(seed)
    waves = [(P, amp, rng.uniform(0, 2 * np.pi)) for P, amp in
             ((3.7, .25), (6.1, .4), (10.3, .55), (17.9, .7), (33.0, .7), (71.0, .5))]

    def raw(x):
        return sum(amp * np.sin(2 * np.pi * x / P + ph) for P, amp, ph in waves)

    ref = np.sort(raw(np.arange(-3000.0, 3000.0, 0.37)))
    return np.interp(raw(xr), ref, np.linspace(0, 1, ref.size))


def ribbon(Gf, Mf, yb_pts, h_pts, b_pts, lean, seed, hem=1.0):
    xs = np.arange(W, dtype=float)
    yb = smooth_curve(yb_pts, xs)
    yb = yb + 1.6 * np.sin(xs / 7.0 + seed) + 1.0 * np.sin(xs / 3.3 + 2 * seed)
    h = smooth_curve(h_pts, xs)
    b = smooth_curve(b_pts, xs) * (0.7 + 0.6 * noise1d(xs, 38.0, seed + 5))
    d = yb[None, :] - YY
    xr = XX + d * lean
    ray = streaks(xr, seed) ** 2.2
    L = h[None, :] * (0.25 + 1.0 * ray)
    dpos = np.maximum(d, 0.0)
    body = (0.03 + 1.1 * ray) * np.exp(-dpos / L)
    band = hem * (0.8 + 0.3 * ray) * np.exp(-dpos / 4.0)
    edge = np.where(d < 0, np.exp(d / 0.9), 1.0)
    Gf += b[None, :] * (body + band) * edge
    # pink nitrogen fringe under the brightest stretches of the hem
    Mf += np.clip((b[None, :] - 0.8) * 2.5, 0, 1) * np.exp(-((d + 1.8) / 1.0) ** 2) * hem
    return yb


def build_sky():
    Gf = np.zeros((H, W))
    Mf = np.zeros((H, W))
    ribbon(Gf, Mf,
           yb_pts=[(-30, 40), (40, 70), (100, 96), (150, 110), (190, 106), (236, 86),
                   (290, 72), (340, 76), (420, 94)],
           h_pts=[(-30, 115), (140, 92), (260, 60), (420, 40)],
           b_pts=[(-30, .55), (60, .72), (140, 1.0), (190, .92), (240, .74), (320, .6), (420, .5)],
           lean=0.2, seed=3, hem=1.0)
    ribbon(Gf, Mf,
           yb_pts=[(180, 134), (260, 124), (330, 120), (420, 128)],
           h_pts=[(180, 30), (420, 26)],
           b_pts=[(180, 0.0), (240, .4), (330, .5), (420, .4)],
           lean=0.12, seed=9, hem=0.7)
    blue = 0.02 + 0.26 * np.clip((YY - 70) / 190.0, 0, 1) ** 1.3
    Gc = np.clip((Gf - 0.07) / 0.93, 0, 1.8)
    white = np.clip((Gc - 1.05) / 0.75, 0, 1) * 0.8
    green = np.clip(Gc, 0, 1) - white
    mag = np.clip(Mf, 0, 0.6)
    blue = blue * np.clip(1 - green * 2.5, 0, 1)
    sky = stack([(WH, white), (G, green), (M, mag), (B, blue)])

    rng = np.random.default_rng(11)
    for _ in range(600):
        x = int(rng.integers(2, W - 2))
        y = int((rng.random() ** 1.2) * 230) + 2
        if Gf[y, x] > 0.08:
            continue
        r = rng.random()
        if r < 0.45:
            sky[y, x] = B
        elif r < 0.75:
            sky[y, x] = C
        elif r < 0.97:
            sky[y, x] = WH
        else:
            sky[y, x] = WH
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                sky[y + dy, x + dx] = B
    return sky, Gf


# ------------------------------------------------------------------ mountains
def mountain(c, a, left, right, ridge, seed, lit, shade, snowline,
             rock_lit=0.42, rock_shade=0.2, rockiness=0.5):
    """left: base->peak, right: peak->base, ridge: peak->down. Light from the left."""
    lf = jag(left, 0.05, seed)
    rt = jag(right, 0.05, seed + 1)
    rg = jag(ridge, 0.06, seed + 2)
    sil = poly_mask(lf + rt[1:] + [(rt[-1][0], H + 2), (lf[0][0], H + 2)])
    lface = poly_mask(lf + rg[1:] + [(rg[-1][0], H + 2), (lf[0][0] - 2, H + 2)]) & sil
    px, py = left[-1]
    depth = np.clip((YY - py) / max(1.0, snowline - py), 0, 1.4)
    t = np.where(lface, lit[0] + (lit[1] - lit[0]) * np.minimum(depth, 1),
                 shade[0] + (shade[1] - shade[0]) * np.minimum(depth, 1))
    # radial couloirs: rocky streaks fanning down from the summit
    phi = np.arctan2(XX - px, np.maximum(YY - py, 0.5))
    dist = np.hypot(XX - px, YY - py)
    t = t + 0.07 * (noise1d(phi, 0.16, seed + 9) - 0.5)
    phi = phi + 0.025 * np.sin(dist / 14.0 + 9 * noise1d(phi, 0.3, seed + 10))
    n1 = noise1d(phi, 0.035, seed + 7)
    n2 = noise1d(phi, 0.06, seed + 8, 0.05, 0.9)
    thr = 1.0 - rockiness * (0.35 + 0.65 * np.minimum(depth, 1))
    rock = (n1 > thr) & (depth > n2)
    t = np.where(rock, np.where(lface, rock_lit, rock_shade), t)
    put(c, a, sil, ramp(t, COOL))


def build_mountains():
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    far_lit, far_sh = (.54, .48), (.40, .36)
    mountain(c, a, [(-40, 250), (0, 168), (30, 148)], [(30, 148), (54, 162), (96, 214)],
             [(30, 148), (36, 180), (30, 230)], 31, far_lit, far_sh, 230, .44, .3, 0.35)
    mountain(c, a, [(150, 240), (176, 160), (198, 140)], [(198, 140), (214, 150), (240, 170), (290, 220)],
             [(198, 140), (204, 170), (200, 230)], 32, far_lit, far_sh, 230, .44, .3, 0.35)
    mountain(c, a, [(296, 240), (330, 156), (354, 138)], [(354, 138), (374, 152), (420, 190)],
             [(354, 138), (348, 168), (354, 230)], 33, far_lit, far_sh, 230, .44, .3, 0.35)

    m_lit, m_sh = (.92, .74), (.47, .38)
    mountain(c, a,
             [(-6, 206), (14, 194), (30, 182), (44, 174), (58, 158), (70, 150), (80, 136),
              (89, 130), (97, 118), (104, 113), (110, 102), (116, 96)],
             [(116, 96), (121, 103), (127, 105), (134, 114), (140, 119), (146, 118), (151, 124),
              (158, 135), (169, 146), (181, 158), (194, 165), (210, 175), (232, 190)],
             [(116, 96), (120, 116), (114, 134), (121, 156), (115, 182), (122, 214)],
             5, m_lit, m_sh, 214)
    mountain(c, a,
             [(250, 200), (270, 178), (284, 168), (296, 156), (306, 150), (314, 140), (320, 138),
              (327, 131)],
             [(327, 131), (333, 137), (340, 139), (348, 148), (358, 153), (370, 165), (384, 170),
              (404, 182)],
             [(327, 131), (323, 150), (329, 168), (323, 190), (328, 214)],
             7, (.84, .70), (.44, .36), 212)
    mountain(c, a,
             [(184, 206), (198, 172), (208, 166), (218, 156), (228, 150), (236, 139), (245, 133),
              (253, 123), (259, 120), (266, 113)],
             [(266, 113), (271, 120), (277, 122), (284, 131), (292, 136), (300, 148), (311, 156),
              (325, 172), (342, 182), (366, 198), (404, 214)],
             [(266, 113), (262, 134), (268, 153), (261, 175), (267, 214)],
             6, m_lit, m_sh, 212)
    return c, a


# ------------------------------------------------------------------ forest
def pine_mask(m, cx, ybase, h, wratio=0.46):
    top = ybase - h
    for y in range(max(0, top), min(H, ybase + 1)):
        f = (y - top) / max(1, h)
        tier = ((y - top) % 4) / 3.0
        half = (0.12 + f) * h * wratio * 0.5 * (0.65 + 0.35 * tier)
        x0 = int(round(cx - half))
        x1 = int(round(cx + half))
        if x1 >= 0 and x0 < W:
            m[y, max(0, x0):min(W, x1 + 1)] = True


def build_forest():
    """Forested foothills veiled by valley mist, darker shore pines in front."""
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    xs = np.arange(W, dtype=float)
    rng = np.random.default_rng(21)
    hill = 205 + 6 * np.sin(xs / 37.0 + 0.5) + 4 * np.sin(xs / 13.0 + 1.0)
    m = YY >= hill[None, :]
    x = -4
    while x < W + 4:
        base = int(hill[min(W - 1, max(0, x))]) + 5
        pine_mask(m, x, base, int(rng.integers(8, 19)))
        x += int(rng.integers(3, 6))
    m &= YY <= YF
    base_d = np.clip((YY - 222) / 66.0, 0, 1) ** 1.4
    wisp = noise2d(XX / 34.0, YY / 4.0, 23) - 0.5
    dens = np.clip(base_d + 0.35 * wisp * np.clip(base_d * 3, 0, 1), 0, 1)
    put(c, a, m, ramp(dens * 0.8, COOL))
    rng2 = np.random.default_rng(22)
    lit = m & ~np.roll(m, 1, axis=1) & (rng2.random((H, W)) < 0.4) & (dens < 0.12)
    put(c, a, lit, B)
    sp = np.zeros((H, W), bool)
    x = 2
    rng3 = np.random.default_rng(24)
    while x < W:
        if rng3.random() < 0.55:
            pine_mask(sp, x, YF - 1, int(rng3.integers(10, 30)), wratio=0.4)
        x += int(rng3.integers(4, 12))
    put(c, a, sp & (YY < YF - 1), ramp(np.clip(dens * 0.8 - 0.42, 0, 1), COOL))
    bank = (YY >= YF - 1) & (YY <= YF)
    put(c, a, bank, ramp(np.where(YY == YF - 1, 0.9, 0.66), COOL))
    cabin(c, a, CABIN_X, YF - 2, dens)
    return c, a


CABIN_X = 113


def cabin(c, a, x0, yb, dens):
    """A woodcutter's cabin on the far shore, seen through the third arch."""
    clear = (XX >= x0 - 3) & (XX <= x0 + 14) & (YY >= yb - 22) & (YY <= yb)
    under = ramp(dens * 0.8, COOL)
    c[clear] = under[clear]
    box(c, a, x0, yb - 5, x0 + 11, yb, K)
    for k in range(6):                      # gable roof, snow along its edges
        xl, xr = x0 - 1 + k, x0 + 12 - k
        box(c, a, xl, yb - 6 - k, xr, yb - 6 - k, K)
        c[yb - 6 - k, xl] = WH
        c[yb - 6 - k, xr] = C
    box(c, a, x0 + 5, yb - 11, x0 + 6, yb - 11, WH)
    box(c, a, x0 - 1, yb - 6, x0 + 12, yb - 6, B)
    c[yb - 6, x0 - 1] = WH
    box(c, a, x0 + 8, yb - 12, x0 + 9, yb - 8, K)
    c[yb - 12, x0 + 8] = WH
    box(c, a, x0 + 2, yb - 3, x0 + 4, yb - 2, Y)
    box(c, a, x0 + 8, yb - 3, x0 + 9, yb, R)
    c[yb - 3, x0 + 8] = Y
    for dx, dy in ((0, -14), (0, -15), (-1, -17), (-1, -18), (-2, -20), (-3, -22)):
        c[yb + dy, x0 + 8 + dx] = B
        a[yb + dy, x0 + 8 + dx] = True
    c[yb + 1, x0 + 1:x0 + 6:2] = Y
    c[yb + 1, x0 + 8] = Y


# ------------------------------------------------------------------ viaduct
def in_opening(x, y):
    out = np.zeros(np.shape(x), bool)
    for cx in ARCH_CX:
        dx = x - (cx - 0.5)
        semi = (dx * dx + (y - YS) ** 2 <= RA * RA) & (y <= YS)
        half = np.where(y >= YB - 6, RA - 2, RA)
        rect = (np.abs(dx) <= half) & (y > YS)
        out |= semi | rect
    return out


def build_bridge():
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    body = (YY >= YR) & (YY <= YB)
    front_open = in_opening(XX.astype(float), YY.astype(float)) & body
    qx = EYE[0] + (XX - EYE[0]) / BACK
    qy = EYE[1] + (YY - EYE[1]) / BACK
    back_open = in_opening(qx, qy)
    inner = front_open & ~back_open
    face = body & ~front_open

    wet = np.clip((YY - (YB - 14)) / 14.0, 0, 1)
    rel = YY - (YR + 6)
    course = rel // 5
    hj = (rel % 5 == 0) & (rel > 0)
    top_row = (rel % 5 == 1)
    stone = (XX + 5 * (course % 2)) // 10
    jitter = (((course * 97 + stone * 31) * 37) % 7 - 3) / 3.0 * 0.045
    face_t = 0.21 - 0.12 * wet + 0.07 * top_row + jitter * (rel > 0)
    put(c, a, face, ramp(face_t, COOL))
    vj = ((XX + 5 * (course % 2)) % 10 == 0) & (rel > 0)
    put(c, a, face & (hj | vj) & (YY < YB - 3), K)

    for cx in ARCH_CX:
        dx = XX - (cx - 0.5)
        dy = YY - YS
        r = np.sqrt(dx * dx + dy * dy)
        ring = face & (r > RA) & (r <= RA + 5) & (YY <= YS)
        put(c, a, ring, ramp(0.3, COOL))
        ang = np.degrees(np.arctan2(-dy, dx))
        joint = ring & (np.abs(((ang + 7.5) % 15.0) - 7.5) < 2.2)
        put(c, a, joint, K)
        put(c, a, face & (r > RA + 5) & (r <= RA + 6) & (YY <= YS), K)
        key = ring & (np.abs(dx) <= 2.5)
        put(c, a, key, ramp(0.42, COOL))

    for y, t in ((YR, 1.0), (YR + 1, 0.78), (YR + 2, 0.4), (YR + 3, 0.333), (YR + 4, 0.25), (YR + 5, 0.0)):
        put(c, a, body & (YY == y), ramp(np.full((H, W), t), COOL))
    rng = np.random.default_rng(41)
    x = int(rng.integers(0, 5))
    while x < W:
        ln = int(rng.choice([1, 1, 2, 2, 3, 4]))
        for k in range(ln):
            c[YR + 5 + k, x] = C if k < ln - 1 or ln == 1 else B
        x += int(rng.integers(3, 10))

    for cx in ARCH_CX:
        local = inner & (np.abs(XX - (cx - 0.5)) <= RA + 1)
        intr = local & (YY <= YS + 1)
        left_jamb = local & ~intr & (XX < cx)
        right_jamb = local & ~intr & (XX >= cx)
        put(c, a, intr, K)
        put(c, a, left_jamb, ramp(0.1, COOL))
        put(c, a, right_jamb, ramp(0.42, COOL))
        # snow on the footing step and an ice collar at the waterline
        for side in (-1, 1):
            fx = cx - 0.5 + side * (RA - 0.5)
            step = face & (YY == YB - 6) & (np.abs(XX - fx) <= 1.0)
            put(c, a, step, C)
        collar = face & (YY == YB) & (np.abs(XX - (cx - 0.5 + 24)) <= 7)
        put(c, a, collar, ramp(np.full((H, W), 0.6), COOL))
    # warm light from the carriage windows and the firebox on the snowy cornice
    for x0 in CARS:
        for wx in range(x0 + 4, x0 + 42 - 5, 5):
            put(c, a, (YY == YR) & (XX >= wx - 1) & (XX <= wx + 3) & (0.85 > T4), Y)
            put(c, a, (YY == YR + 1) & (XX >= wx) & (XX <= wx + 2) & (0.45 > T4), Y)
    put(c, a, (YY == YR) & (XX >= LOCO_X + 1) & (XX <= LOCO_X + 11) & (0.6 > T4), Y)
    put(c, a, (YY == YR + 1) & (XX >= LOCO_X + 2) & (XX <= LOCO_X + 10) & (0.5 > T4), R)
    return c, a


# ------------------------------------------------------------------ train
def carriage(c, a, x0, L=42):
    x1 = x0 + L - 1
    top, bot = YR - 17, YR - 6
    for bx in (x0 + 4, x1 - 11):
        box(c, a, bx, YR - 4, bx + 7, YR - 3, K)
        for wx in (bx + 1, bx + 5):
            box(c, a, wx, YR - 2, wx + 1, YR - 1, K)
    box(c, a, x0 + 1, YR - 5, x1 - 1, YR - 5, K)
    m = np.zeros((H, W), bool)
    m[top:bot + 1, x0:x1 + 1] = True
    put(c, a, m, MAROON)
    box(c, a, x0, top, x0, bot, K)
    box(c, a, x1, top, x1, bot, K)
    box(c, a, x0, bot, x1, bot, K)
    box(c, a, x0 + 1, YR - 8, x1 - 1, YR - 8, R)
    for wx in range(x0 + 4, x1 - 4, 5):
        box(c, a, wx, YR - 14, wx + 2, YR - 10, Y)
    box(c, a, x0, top - 1, x1, top - 1, K)
    box(c, a, x0 + 1, top - 2, x1 - 1, top - 2, K)
    box(c, a, x0 + 3, top - 3, x1 - 3, top - 3, WH)


def tender(c, a, x0):
    box(c, a, x0, YR - 16, x0 + 17, YR - 5, K)
    box(c, a, x0, YR - 15, x0, YR - 6, B)
    for i, hh in enumerate([1, 2, 3, 3, 2, 3, 2, 2, 1]):
        box(c, a, x0 + 1 + 2 * i, YR - 16 - hh, x0 + 2 + 2 * i, YR - 17, K)
        box(c, a, x0 + 1 + 2 * i, YR - 16 - hh, x0 + 1 + 2 * i, YR - 16 - hh, C if i % 3 else WH)
    box(c, a, x0, YR - 16, x0 + 17, YR - 16, B)
    for wx in (x0 + 3, x0 + 9, x0 + 15):
        put(c, a, disc(wx, YR - 3, 2.2), K)
        c[YR - 5, wx - 1] = B


def wheel(c, a, cx, cy, r):
    put(c, a, disc(cx, cy, r + 0.3), K)
    rim = disc(cx, cy, r + 0.3) & ~disc(cx, cy, r - 0.7)
    put(c, a, rim & (YY <= cy + r - 1), B)
    put(c, a, rim & (XX - cx + YY - cy < -r * 0.9), C)
    c[cy, cx] = B


def loco(c, a, x0):
    box(c, a, x0, YR - 10, x0 + 47, YR - 10, K)
    box(c, a, x0 + 12, YR - 9, x0 + 46, YR - 8, R)
    # boiler, moonlit along its crown
    box(c, a, x0 + 12, YR - 19, x0 + 41, YR - 11, K)
    box(c, a, x0 + 13, YR - 19, x0 + 41, YR - 19, C)
    box(c, a, x0 + 13, YR - 18, x0 + 41, YR - 18, B)
    for bx in (x0 + 20, x0 + 33):
        box(c, a, bx, YR - 18, bx, YR - 12, B)
    # smokebox
    box(c, a, x0 + 42, YR - 20, x0 + 47, YR - 11, K)
    box(c, a, x0 + 42, YR - 20, x0 + 46, YR - 20, B)
    # chimney
    box(c, a, x0 + 43, YR - 25, x0 + 46, YR - 21, K)
    box(c, a, x0 + 43, YR - 25, x0 + 43, YR - 21, B)
    box(c, a, x0 + 42, YR - 26, x0 + 47, YR - 26, K)
    box(c, a, x0 + 42, YR - 26, x0 + 45, YR - 26, C)
    # dome + safety valve
    box(c, a, x0 + 26, YR - 22, x0 + 31, YR - 20, K)
    box(c, a, x0 + 27, YR - 23, x0 + 30, YR - 23, K)
    box(c, a, x0 + 27, YR - 23, x0 + 29, YR - 23, C)
    box(c, a, x0 + 26, YR - 22, x0 + 26, YR - 21, B)
    box(c, a, x0 + 16, YR - 21, x0 + 17, YR - 20, K)
    c[YR - 21, x0 + 16] = C
    # cab
    box(c, a, x0, YR - 24, x0 + 12, YR - 10, K)
    box(c, a, x0, YR - 23, x0, YR - 11, B)
    box(c, a, x0 - 1, YR - 25, x0 + 13, YR - 25, K)
    box(c, a, x0 - 1, YR - 25, x0 + 11, YR - 25, C)
    m = np.zeros((H, W), bool)
    m[YR - 21:YR - 15, x0 + 3:x0 + 9] = True
    put(c, a, m, ramp(0.5, WARM))
    box(c, a, x0 + 3, YR - 21, x0 + 8, YR - 21, Y)
    # running gear
    for wx in (x0 + 17, x0 + 27, x0 + 37):
        wheel(c, a, wx, YR - 5, 4)
    wheel(c, a, x0 + 44, YR - 3, 2)
    wheel(c, a, x0 + 6, YR - 3, 2)
    box(c, a, x0 + 17, YR - 5, x0 + 37, YR - 5, C)
    box(c, a, x0 + 39, YR - 9, x0 + 46, YR - 5, K)
    box(c, a, x0 + 39, YR - 9, x0 + 45, YR - 9, B)
    box(c, a, x0 + 47, YR - 9, x0 + 48, YR - 6, R)
    # headlamp
    box(c, a, x0 + 47, YR - 19, x0 + 48, YR - 17, K)
    box(c, a, x0 + 48, YR - 18, x0 + 49, YR - 18, WH)
    c[YR - 17, x0 + 49] = Y
    c[YR - 19, x0 + 49] = Y
    a[YR - 19:YR - 16, x0 + 49] = True


def headlamp_beam(c, a, x0):
    lx, ly = x0 + 50, YR - 18
    t = XX - lx
    top = ly - 1 - 0.07 * t
    bot = ly + 1 + 0.26 * t
    cone = (t >= 0) & (YY >= top) & (YY <= bot) & (YY < YR)
    across = np.clip(1 - np.abs(YY - (top + bot) / 2) / np.maximum((bot - top) / 2, 1), 0, 1)
    dens = 0.55 * np.exp(-np.maximum(t, 0) / 40.0) * (0.35 + 0.65 * across)
    beam = cone & (dens > T4)
    put(c, a, beam, Y)
    halo = disc(lx - 1, ly, 3.2) & ~a & (0.6 > T4)
    put(c, a, halo, Y)
    lit_snow = (YY == YR) & (XX > lx) & (XX < lx + 60) & (np.exp(-(XX - lx) / 22.0) > T4)
    put(c, a, lit_snow, Y)


def build_train():
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    for x0 in CARS:
        carriage(c, a, x0)
    tender(c, a, 234)
    loco(c, a, LOCO_X)
    tx = CARS[0]
    box(c, a, tx - 2, YR - 10, tx - 1, YR - 9, R)
    c[YR - 10, tx - 2] = Y
    signal(c, a, 30)
    return c, a


def signal(c, a, sx):
    """Semaphore at the end of the viaduct, arm raised, lamp showing clear."""
    top = YR - 32
    box(c, a, sx - 2, YR - 2, sx + 1, YR - 1, K)
    box(c, a, sx - 1, top, sx, YR - 3, K)
    box(c, a, sx - 1, top + 1, sx - 1, YR - 3, B)
    box(c, a, sx - 2, top - 1, sx + 1, top - 1, K)
    c[top - 1, sx - 2] = C
    c[top - 2, sx - 1] = K
    a[top - 2, sx - 1] = True
    for k, rise in enumerate((0, 1, 1, 2, 3, 3, 4)):   # arm raised: red with a white band
        ax, ay = sx - 2 - k, top + 5 - rise
        box(c, a, ax, ay, ax, ay + 1, WH if k == 4 else R)
    box(c, a, sx + 1, top + 6, sx + 2, top + 7, G)
    halo = disc(sx + 1.5, top + 6.5, 3.4) & ~a & (0.35 > T4)
    put(c, a, halo, G)
    for ry in range(top + 10, YR - 3, 4):    # ladder rungs
        c[ry, sx + 1] = B
        a[ry, sx + 1] = True


def build_beam():
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    headlamp_beam(c, a, LOCO_X)
    return c, a


# ------------------------------------------------------------------ smoke
def build_smoke():
    c = np.zeros((H, W), np.uint8)
    a = np.zeros((H, W), bool)
    rng = np.random.default_rng(5)
    Lv = np.array([-0.55, -0.7, 0.45])
    Lv = Lv / np.linalg.norm(Lv)
    x0, y0 = LOCO_X + 44.5, YR - 28
    puffs = []
    x, i = x0, 0
    while x > 96:
        d = x0 - x
        s = d / 200.0
        py = y0 - 2 - 12 * (1 - np.exp(-d / 11.0)) - 0.03 * d + rng.normal() * 0.8
        r = (2.8 + 6.0 * s ** 0.6) * rng.uniform(0.88, 1.1)
        px = x + rng.normal() * 0.6
        fade = float(np.clip((s - 0.3) / 0.62, 0, 1)) ** 1.2
        puffs.append((px, py, r, i, fade))
        if i > 0:
            for _ in range(2):
                if rng.random() < 0.85:
                    ang = rng.uniform(-2.5, -0.6)
                    rr = r * rng.uniform(0.5, 0.75)
                    puffs.append((px + np.cos(ang) * r * 0.75, py + np.sin(ang) * r * 0.75,
                                  rr, i + 0.5, fade))
        x -= r * rng.uniform(0.75, 1.0)
        i += 1
    puffs.sort(key=lambda p: -p[3])
    cover = np.zeros((H, W), bool)
    keep = np.zeros((H, W))
    level = np.zeros((H, W))
    fd = np.zeros((H, W))
    for px, py, r, _i, fade in puffs:
        dx = (XX - px) / r
        dy = (YY - py) / r
        q = 1 - dx * dx - dy * dy
        hit = q > 0
        nz = np.sqrt(np.clip(q, 0, 1))
        lam = np.clip(dx * Lv[0] + dy * Lv[1] + nz * Lv[2], 0, 1)
        # thinning smoke loses light: the cel level sinks as the puff fades
        lv = np.select([lam > 0.8, lam > 0.5, lam > 0.22], [3, 2, 1], 0) - 2.6 * fade
        level = np.where(hit, lv, level)
        keep = np.where(hit, 1.0 - max(0.0, fade - 0.55) * 2.2, keep)
        fd = np.where(hit, fade, fd)
        cover |= hit
    tone = np.select([level > 2.5, level > 1.5, level > 0.5], [WH, C, B], K).astype(np.uint8)
    m = cover & (keep > T4) & ((level > 0.5) | (fd < 0.15))
    put(c, a, m, tone)
    rs = np.random.default_rng(13)
    for k in range(11):
        sx = int(round(x0 + rs.normal() * 3.5 - k * 0.8))
        sy = int(round(y0 - 3 - rs.uniform(0, 16)))
        if not m[sy, sx]:
            c[sy, sx] = (Y, R, Y, WH)[k % 4]
            a[sy, sx] = True
    return c, a


# ------------------------------------------------------------------ water
DIM = np.array([K, K, G, B, R, B, Y, C], np.uint8)


def reflect(src, src_a, axis, y0, wob):
    out = np.zeros((H, W), np.uint8)
    oa = np.zeros((H, W), bool)
    xs = np.arange(W)
    for y in range(y0, H):
        sy = 2 * axis - y
        if sy < 0 or sy >= H:
            continue
        sx = np.clip(xs - wob[y], 0, W - 1)
        out[y] = src[sy, sx]
        oa[y] = src_a[sy, sx]
    return out, oa


def build_water(bg, near, near_a):
    ys = np.arange(H)
    dist = np.clip(ys - YF, 0, None).astype(float)
    amp = 0.3 + 1.9 * (dist / (H - YF))
    period = 7.0 + dist / 8.0
    wob = np.round(amp * np.sin(np.cumsum(2 * np.pi / period) + 0.8)).astype(int)
    spacing = 2.2 + dist / 24.0
    phase = np.cumsum(1.0 / spacing)
    gap = np.zeros(H, bool)
    gap[1:] = np.floor(phase[1:]) != np.floor(phase[:-1])

    full_a = np.ones((H, W), bool)
    r_bg, _ = reflect(bg, full_a, YF, YF + 1, wob)
    r_near, r_near_a = reflect(near, near_a, YB, YB + 1, wob)
    w = r_bg.copy()
    w[r_near_a] = r_near[r_near_a]
    # half-step dim: each colour keeps itself on half the pixels, drops a step on the rest
    dim = np.where(CHECK, w, DIM[w]).astype(np.uint8)
    dim[w == WH] = np.where(CHECK, C, C)[w == WH]
    rows = ys > YF
    dim[~rows] = K
    dim[gap & rows, :] = K
    rng = np.random.default_rng(31)
    # ripple glints catching the sky glow, sparser far away
    for _ in range(260):
        y = int(YF + 3 + (H - YF - 4) * rng.random() ** 0.7)
        x = int(rng.integers(0, W))
        ln = int(1 + rng.integers(1, 3) * (y - YF) / 40)
        seg = dim[y, x:x + ln]
        if seg.size and np.all(seg == K):
            dim[y, x:x + ln] = C if rng.random() < 0.25 else B
    return dim


# ------------------------------------------------------------------ compose
def compose():
    sky, Gf = build_sky()
    mc, ma = build_mountains()
    fc, fa = build_forest()
    bc, ba = build_bridge()
    sc, sa = build_smoke()
    lc, la = build_beam()
    tc, ta = build_train()

    bg = sky.copy()
    bg[ma] = mc[ma]
    bg[fa] = fc[fa]

    def layered(parts):
        cc_ = np.zeros((H, W), np.uint8)
        aa_ = np.zeros((H, W), bool)
        for cc, aa in parts:
            cc_[aa] = cc[aa]
            aa_ |= aa
        return cc_, aa_

    near, near_a = layered(((bc, ba), (sc, sa), (lc, la), (tc, ta)))
    refl, refl_a = layered(((bc, ba), (sc, sa), (tc, ta)))

    img = bg.copy()
    water = build_water(bg, refl, refl_a)
    img[YF + 1:] = water[YF + 1:]
    img[near_a] = near[near_a]
    return img


def to_sprite(img):
    s = Sprite(W, H, palette=HEX)
    rgba = np.dstack([RGB[img], np.full((H, W), 255, np.uint8)])
    s._img().paste(Image.fromarray(rgba, "RGBA"), (0, 0))
    return s


if __name__ == "__main__":
    img = compose()
    s = to_sprite(img)
    s.preview(os.path.join(OUT, "preview.png"), scale=2, bg="#000000", labels=False)
    final = os.path.join(OUT, "final.png")
    s.save_png(final)
    Image.open(final).convert("RGB").save(final)
    s.stats()
