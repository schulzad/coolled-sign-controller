"""Fox brush: the sitting fox as cel-shaded shapes.  Each region is a polygon,
ellipse or tube painted with one tone letter, later regions over earlier ones;
an aurora rim (upper left) is traced round the outline.  Writes hand/fox.txt.
After the first run the rows there are refined by hand.

    python3 fox.py [--write]
"""

import sys

import numpy as np
from lib import HERE, poly_mask
from scipy import ndimage

X0, Y0, BW, BH = 266, 254, 98, 104   # sprite box on the canvas
YS, XS = np.mgrid[0:BH, 0:BW]
GX = XS + X0 + 0.5
GY = YS + Y0 + 0.5


def ellipse(cx, cy, rx, ry):
    return (((GX - cx) / rx) ** 2 + ((GY - cy) / ry) ** 2) < 1


def poly(pts):
    return poly_mask([(px - X0, py - Y0) for px, py in pts], (BH, BW))


def tube(centre, radii):
    m = np.zeros((BH, BW), bool)
    for (ax, ay), (bx, by), ra, rb in zip(centre, centre[1:], radii, radii[1:], strict=False):
        for t in np.linspace(0, 1, 16):
            cx, cy, r = ax + (bx - ax) * t, ay + (by - ay) * t, ra + (rb - ra) * t
            m |= (GX - cx) ** 2 + (GY - cy) ** 2 < r * r
    return m


def below(pts):
    """Pixels under a polyline given left to right."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return GY > np.interp(GX, xs, ys)


def left_of(pts):
    """Pixels left of a polyline given top to bottom."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return GX < np.interp(GY, ys, xs)


# ------------------------------------------------------------------ shapes

HEAD = poly([(274.5, 274), (276, 272.6), (279, 272), (282.5, 271.5), (286, 270.8), (288.5, 269.8),
             (291, 268.6), (294.5, 267.8), (298.5, 267.8), (302, 268.8), (305.5, 270.5), (308.5, 273),
             (309.6, 277), (308.8, 281), (306.8, 284.5), (304.5, 287.5), (302, 290.2), (298, 292.2),
             (294, 293), (291, 292), (289, 289.5), (287, 286), (284.5, 282.5), (281, 279.8), (278, 278.2),
             (275.5, 276.8), (274.3, 275.5)])
NEAR_EAR = poly([(298.5, 269.5), (301, 265.5), (304, 261.5), (306.5, 258.5), (308.2, 256.6), (309.2, 257),
                 (309.7, 261), (310, 266), (309.8, 271.5), (306, 272.5)])
FAR_EAR = poly([(290, 269.8), (292, 265.8), (294.5, 262), (296.8, 259.3), (297.9, 258.9), (298.7, 261),
                (299.1, 265), (298.6, 269.5)])
TORSO = poly([(299, 280), (305.5, 280), (307, 286), (308.5, 292), (310.5, 298), (313, 304), (316.5, 309),
              (318, 314), (312, 339.5), (289, 339.5), (288, 333),
              (287.5, 326), (287, 318), (286, 310), (286, 302), (287.5, 296), (289.5, 291)])
BIB = TORSO & left_of([(294, 288), (296, 297), (296, 306), (294, 313), (291.5, 318), (289.5, 324),
                       (288.5, 332), (288, 340)])
HAUNCH = ellipse(317, 326.5, 13, 13) & (GY < 339.5)
NEAR_LEG = poly([(287, 312), (293, 312), (293, 330), (292.8, 336), (294, 339.5), (284, 339.5),
                 (286.5, 336), (287, 330)])
FAR_LEG = poly([(294, 316), (299, 316), (299.5, 339.5), (294, 339.5)])
HIND_FOOT = poly([(298, 335.5), (309, 335.5), (312, 337.5), (311.5, 339.5), (296.5, 339.5)])
TAIL = tube([(321, 334.5), (331, 335), (340, 336.5), (347, 340), (352, 345.5), (355, 351), (356, 355)],
            [5.6, 6.2, 6.2, 5.8, 5.0, 4.0, 2.8])


def build():
    L = np.full((BH, BW), ".", dtype="<U1")

    def paint(mask, tone):
        L[mask] = tone

    # back to front
    paint(FAR_EAR, "e")
    paint(FAR_EAR & left_of([(299, 259), (296.8, 262), (294.8, 265), (293.4, 268), (292.6, 270)]), "t")
    paint(FAR_EAR & (GY < 262.5), "K")
    paint(FAR_EAR & (GY > 268), "R")
    paint(TAIL, "o")
    paint(TAIL & ~tube([(321, 336), (331, 336.5), (340, 338), (347, 341.5), (352, 347), (355, 352.5)],
                       [5.6, 6.2, 6.2, 5.8, 5.0, 4.0]), "p")
    paint(TAIL & tube([(323, 340), (333, 341.5), (342, 342.5), (347, 346)], [2.6, 2.8, 2.6, 1.8]), "R")
    paint(TAIL & tube([(326, 341.5), (335, 342.5)], [1.6, 1.6]), "d")
    paint(TAIL & (GY > 346.5) & (GX > 349), "s")
    paint(TAIL & (GY > 351.5) & (GX > 351), "W")

    paint(TORSO, "o")
    paint(TORSO & ~left_of([(305.5, 282), (306.5, 288), (307.5, 293), (309.5, 299), (312, 305), (315, 310),
                            (317, 315)]), "p")
    paint(TORSO & left_of([(298.5, 288), (300.5, 298), (300.5, 310), (299.5, 322), (298.5, 334)]), "q")
    paint(TORSO & left_of([(295.5, 288), (297, 298), (297, 310), (296, 322), (295, 334)]), "R")
    paint(BIB, "s")
    paint(BIB & left_of([(290, 290), (289, 298), (288.5, 306), (289, 314), (289.5, 322), (289, 330)]), "t")
    paint(BIB & (GY > 316), "t")
    # belly in shadow between the forelegs and the haunch, then the far foreleg
    paint(TORSO & (GY > 333) & (GX > 293), "e")
    paint(FAR_LEG, "R")
    paint(FAR_LEG & (GX < 295.5), "d")
    paint(FAR_LEG & (GY > 334), "K")
    paint(FAR_LEG & (GX > 297.5) & (GY > 334) & (GY < 338.5), "n")

    paint(HAUNCH, "o")
    paint(HAUNCH & ellipse(322, 319.5, 4.6, 3.6), "p")
    paint(HAUNCH & ~ellipse(318.6, 324.8, 12.8, 12.8), "q")
    paint(HAUNCH & ~ellipse(319.4, 323.8, 12.8, 13.1) & (GX < 314), "R")
    paint(HAUNCH & ~ellipse(320.0, 323.2, 12.8, 13.3) & (GX < 310) & (GY > 322), "d")

    paint(HIND_FOOT, "K")
    paint(HIND_FOOT & (GY < 337.5), "e")
    paint(HIND_FOOT & (GY < 336.5) & (GX > 302), "d")

    paint(NEAR_LEG, "o")
    paint(NEAR_LEG & (GX < 289), "q")
    paint(NEAR_LEG & (GX > 291.5) & (GY < 332), "p")
    paint(NEAR_LEG & (GY > 333), "K")
    paint(NEAR_LEG & (GY > 333) & (GX > 290.5) & (GY < 338), "n")
    paint(NEAR_LEG & (GY > 333) & (GY < 335), "v")

    paint(HEAD, "o")
    paint(HEAD & ~below([(274, 273.6), (281, 273), (288, 271.6), (294, 269.8), (300, 269.8), (306, 272)]), "p")
    muzzle = HEAD & below([(275, 276.2), (279, 277.2), (283, 278.6), (288, 280.6), (293, 282.8),
                           (298, 284.6), (303, 286), (307, 286.5), (311, 286.5)])
    paint(muzzle, "s")
    paint(muzzle & below([(283, 284), (288, 287.5), (293, 290.5), (299, 291.5)]), "t")
    back = ~left_of([(301.5, 268), (303.5, 272), (304.5, 277), (304, 282), (302.5, 286), (300, 290)])
    paint(HEAD & ~muzzle & back, "q")
    paint(HEAD & ~muzzle & ~left_of([(305, 270), (307, 274), (307.5, 279), (306.5, 284)]), "R")

    paint(NEAR_EAR, "q")
    paint(NEAR_EAR & (GY < 271), "R")
    paint(NEAR_EAR & (GY < 268), "e")
    paint(NEAR_EAR & (GY < 262), "K")
    paint(NEAR_EAR & left_of([(307.8, 257.5), (304.6, 261.5), (302, 265), (300, 268), (299, 270)]), "s")
    paint(NEAR_EAR & ~left_of([(308.7, 257), (309.1, 262), (309.3, 266), (309.3, 271)]) & (GY > 259), "d")

    # face details
    def put(pts, t):
        for x, y in pts:
            L[y - Y0, x - X0] = t
    put([(274, 274), (275, 274), (276, 274), (274, 275), (275, 275), (276, 273)], "K")   # nose
    put([(277, 274)], "e")
    put([(277, 276), (278, 276), (279, 277), (280, 277), (281, 278)], "e")                # mouth line
    put([(286, 273), (287, 273), (288, 273), (289, 273), (287, 274), (288, 274), (289, 274)], "K")  # eye
    put([(288, 273)], "Y")                                                                # amber glint
    put([(285, 274), (285, 275), (284, 276)], "e")                                        # tear line
    put([(290, 272)], "e")                                                                # eye corner
    # cheek ruff tufts pointing back and down
    put([(306, 287), (307, 288), (305, 289), (306, 290), (303, 291), (304, 292), (300, 293)], "s")
    put([(307, 289), (305, 291)], "t")
    # chest fluff along the bib's leading edge
    put([(286, 297), (285, 301), (285, 305), (285, 309)], "s")
    put([(286, 298), (285, 302), (285, 306), (285, 310)], "t")

    whole = L != "."
    outline = whole & ~ndimage.binary_erosion(whole)
    d = ndimage.distance_transform_edt(np.pad(whole, 2))[2:-2, 2:-2]
    gy, gx = np.gradient(ndimage.gaussian_filter(d, 1.2))
    nrm = np.hypot(gx, gy) + 1e-6
    # outward normal = -gradient; the aurora sits up and to the left
    facing = ((gx / nrm) * 0.62 + (gy / nrm) * 0.78)
    rim = outline & (((facing > 0.5) & (GY < 296)) | ((facing > 0.8) & (GY < 312))
                     | ((facing > 0.3) & (GY > 333) & (GX < 295)))
    for y, x in zip(*np.nonzero(rim), strict=True):
        t = L[y, x]
        if t in "stW":
            L[y, x] = "W"
        elif t in "Kvn":
            L[y, x] = "u"
        else:
            L[y, x] = "C"
    return L


def main():
    L = build()
    rows = ["".join(r) for r in L]
    text = "\n".join([f"at {X0} {Y0}", "z 9", "shadow yes", "note the fox", "---"] + rows) + "\n"
    if "--write" in sys.argv:
        (HERE / "hand").mkdir(exist_ok=True)
        (HERE / "hand" / "fox.txt").write_text(text)
        print("wrote hand/fox.txt")
    else:
        print(text)


if __name__ == "__main__":
    main()
