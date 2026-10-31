#!/usr/bin/env python3
"""Throwaway prototype of SceneCanvas.smdl's fit_pan: a 64x16 window travels a path
over the composed canvas, holding at both ends, and the frames are saved as a
frame bundle that coolled-verbs can plan and send as it is."""

from __future__ import annotations

import json
import math
from pathlib import Path

import workspace

from opensign.animation.studio import PixelAnimationStudio

PANEL = (64, 16)
BUDGET = 79
START, END = (46, 326), (236, 238)  # the lander and the astronaut; the storm above the ring
HOLD_START, HOLD_END, FRAME_MS = 10, 10, 100

canvas = workspace.compose(json.loads(Path("scene.json").read_text()))
moving = BUDGET - HOLD_START - HOLD_END
points = [START] * HOLD_START
for i in range(moving):
    t = i / (moving - 1)
    t = t * t * (3 - 2 * t)  # ease in and out
    points.append((round(START[0] + (END[0] - START[0]) * t), round(START[1] + (END[1] - START[1]) * t)))
points += [END] * HOLD_END
frames = [canvas.crop((x, y, x + PANEL[0], y + PANEL[1])) for x, y in points]
bundle = PixelAnimationStudio(*PANEL).compile_images(
    frames, frame_durations_ms=[FRAME_MS] * len(frames), frames_per_second=1000 / FRAME_MS,
    metadata={"pattern": "scene_tour", "path": [START, END]},
)
path = bundle.save("tour.bundle.json")
step = math.dist(START, END) / (moving - 1)
print(f"{len(frames)} frames at {FRAME_MS} ms ({len(frames) * FRAME_MS / 1000:.1f} s loop), "
      f"about {step:.1f} px per moving frame -> {path}")
