#!/usr/bin/env python3
"""Inspection crops of final.png:  python3 zoom.py NAME X0 Y0 X1 Y1 [SCALE]"""
import os
import sys

sys.path.insert(0, "/Users/adamschulz/source/hacking/pixel-bakeoff/tools/pixel-art-studio/scripts")
from pixelstudio import Sprite  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
name, x0, y0, x1, y1 = sys.argv[1], *map(int, sys.argv[2:6])
scale = int(sys.argv[6]) if len(sys.argv) > 6 else 6
s = Sprite.from_png(os.path.join(HERE, "final.png"), scale=1)
s.zoom(os.path.join(HERE, f"zoom_{name}.png"), x0, y0, x1, y1, scale=scale, grid=False, bg="#000000")
