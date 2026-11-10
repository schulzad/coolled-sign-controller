"""Shared helpers for the brushes: noise, ordered dither, sprite conversion."""

import json
from pathlib import Path

import numpy as np

W = H = 384
HERE = Path(__file__).resolve().parent

BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], float)
YY, XX = np.mgrid[0:H, 0:W]
THR = (BAYER4[YY % 4, XX % 4] + 0.5) / 16.0
BAYER8 = np.block([[4 * BAYER4, 4 * BAYER4 + 2], [4 * BAYER4 + 3, 4 * BAYER4 + 1]])
THR8 = (BAYER8[YY % 8, XX % 8] + 0.5) / 64.0

# R=4, G=2, B=1 bits -> palette letter; K is mapped to black at placement time
CODE = np.array(list("KBGCRMYW"))
RGB = {"K": (0, 0, 0), "R": (255, 0, 0), "G": (0, 255, 0), "B": (0, 0, 255),
       "C": (0, 255, 255), "M": (255, 0, 255), "Y": (255, 255, 0), "W": (255, 255, 255)}


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _hash(ix, iy, seed):
    ix = np.asarray(ix, np.int64)
    iy = np.asarray(iy, np.int64)
    with np.errstate(over="ignore"):
        n = (ix * 73856093) ^ (iy * 19349663) ^ np.int64(seed * 83492791 + 12345)
        n = (n ^ (n >> 13)) * np.int64(1274126177)
        n = n ^ (n >> 16)
    return (n & 0xFFFF) / 65535.0


def vnoise(x, y, seed=0):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = _hash(x0, y0, seed)
    b = _hash(x0 + 1, y0, seed)
    c = _hash(x0, y0 + 1, seed)
    d = _hash(x0 + 1, y0 + 1, seed)
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy


def fbm(x, y, seed=0, octaves=4, lac=2.0, gain=0.5):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * vnoise(x * lac ** o, y * lac ** o, seed + 101 * o)
        norm += amp
        amp *= gain
    return total / norm


def ridged(x, y, seed=0, octaves=5):
    total, amp, norm, weight = 0.0, 1.0, 0.0, 1.0
    for o in range(octaves):
        n = 1.0 - np.abs(2 * vnoise(x * 2 ** o, y * 2 ** o, seed + 57 * o) - 1)
        n = n * n * weight
        weight = np.clip(n * 1.6, 0, 1)
        total = total + amp * n
        norm += amp
        amp *= 0.5
    return total / norm


def cool(v):
    """Ramp black -> blue -> cyan -> white as continuous RGB."""
    v = np.asarray(v, float)
    return np.stack([np.clip(3 * v - 2, 0, 1), np.clip(3 * v - 1, 0, 1), np.clip(3 * v, 0, 1)], -1)


def warm(v):
    """Ramp black -> red -> yellow -> white."""
    v = np.asarray(v, float)
    return np.stack([np.clip(3 * v, 0, 1), np.clip(3 * v - 1, 0, 1), np.clip(3 * v - 2, 0, 1)], -1)


def dither(rgb, thr=None):
    """Per-channel ordered dither with one shared Bayer threshold -> letter array."""
    thr = THR if thr is None else thr
    on = rgb > thr[..., None]
    code = on[..., 0] * 4 + on[..., 1] * 2 + on[..., 2]
    return CODE[code]


def rows_of(letters, mask, x0, y0, x1, y1):
    """Rows for a sprite covering [x0,x1) x [y0,y1); '.' where mask is False."""
    sub = np.where(mask[y0:y1, x0:x1], letters[y0:y1, x0:x1], ".")
    return ["".join(r) for r in sub]


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def blur1d(a, r, axis):
    """Box blur of radius r along an axis, edge-clamped."""
    if r <= 0:
        return a
    k = 2 * r + 1
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis)
    c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(k, k + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / k


def blur(a, r, passes=3):
    for _ in range(passes):
        a = blur1d(blur1d(a, r, 0), r, 1)
    return a


def poly_mask(pts, shape=(H, W)):
    """Even-odd fill of a polygon given in pixel coordinates (pixel centres tested)."""
    px = np.array([p[0] for p in pts], float)
    py = np.array([p[1] for p in pts], float)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    x = xx + 0.5
    y = yy + 0.5
    inside = np.zeros(shape, bool)
    n = len(pts)
    for i in range(n):
        x1, y1, x2, y2 = px[i], py[i], px[(i + 1) % n], py[(i + 1) % n]
        if y1 == y2:
            continue
        cond = (y1 > y) != (y2 > y)
        xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (x < xc)
    return inside


def line_pts(pts):
    """Integer pixels along a polyline (Bresenham per segment)."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            out.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
    return out


def catmull(xq, pts):
    """Catmull-Rom through (x, v) control points, clamped at the ends."""
    px = np.array([p[0] for p in pts], float)
    pv = np.array([p[1] for p in pts], float)
    xq = np.asarray(xq, float)
    out = np.empty_like(xq)
    n = len(px)
    for i, x in np.ndenumerate(xq):
        if x <= px[0]:
            out[i] = pv[0]
            continue
        if x >= px[-1]:
            out[i] = pv[-1]
            continue
        k = np.searchsorted(px, x) - 1
        p0 = pv[max(k - 1, 0)]
        p1, p2 = pv[k], pv[k + 1]
        p3 = pv[min(k + 2, n - 1)]
        t = (x - px[k]) / (px[k + 1] - px[k])
        out[i] = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                        + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
    return out


TONES = {
    # tone letters for hand sprites: (colour where the Bayer threshold is under the
    # fraction, colour elsewhere, fraction)
    "o": ("Y", "R", 0.5),    # orange
    "q": ("Y", "R", 0.25),   # deep orange
    "p": ("Y", "R", 0.75),   # light orange
    "d": ("R", "K", 0.5),    # dark red
    "e": ("R", "K", 0.25),   # very dark red
    "n": ("B", "K", 0.5),    # navy
    "v": ("B", "K", 0.25),   # deep navy
    "u": ("C", "B", 0.5),    # mid ice
    "i": ("C", "B", 0.25),   # dark ice
    "j": ("C", "B", 0.75),   # light ice
    "s": ("W", "C", 0.5),    # snow
    "t": ("W", "C", 0.25),   # shaded snow
    "g": ("W", "K", 0.5),    # grey
    "h": ("Y", "W", 0.5),    # pale yellow
    "a": ("Y", "K", 0.5),    # dim yellow
    "b": ("M", "K", 0.5),    # plum
    "c": ("M", "R", 0.5),    # rose
}


def expand_tones(rows, ax, ay):
    """Replace tone letters with concrete letters using the canvas-aligned threshold."""
    out = []
    for ry, row in enumerate(rows):
        chars = []
        for rx, ch in enumerate(row):
            if ch in TONES:
                hi, lo, f = TONES[ch]
                x, y = ax + rx, ay + ry
                t = (BAYER4[y % 4, x % 4] + 0.5) / 16.0
                chars.append(hi if t < f else lo)
            else:
                chars.append(ch)
        out.append("".join(chars))
    return out


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, separators=(",", ":")))
