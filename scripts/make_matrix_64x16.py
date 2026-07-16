from pathlib import Path
from PIL import Image, ImageDraw
import random
import math

OUT = Path(__file__).resolve().parent.parent / "examples" / "generated" / "anim"
W, H = 64, 16
FRAME_COUNT = 64
FRAME_MS = 65
SCALE = 8
SEED = 50568

# The rain falls along H. The original look was hand-tuned for a 64px-tall
# column, so every vertical measurement is expressed relative to H. This keeps
# trail length, spacing and fade proportional at any resolution (and reproduces
# the original constants exactly when H == 64).
REF_H = 64
GAP = max(1, round(3 * H / REF_H))                       # px between glyphs in a trail
FADE_PX = H / 6                                          # brightness -> 1/e over this many px
TRAIL_MIN = max(2, round(18 * H / REF_H) // GAP + 1)     # shortest trail (in glyphs)
TRAIL_MAX = max(TRAIL_MIN + 1, round(39 * H / REF_H) // GAP + 1)
BG_STEP = max(2, round(17 * H / REF_H))                  # spacing of faint background dots

rng = random.Random(SEED)
streams = []
for x in range(0, W, 2):
    streams.append({
        "x": x,
        "start": rng.randrange(H),
        "speed": rng.choice([1, 1, 1, 2]),
        "trail": rng.randrange(TRAIL_MIN, TRAIL_MAX + 1),
        "phase": rng.randrange(10000),
    })

def glyph_bits(stream_phase: int, code_index: int) -> tuple[bool, bool, bool]:
    n = (stream_phase * 1103515245 + code_index * 12345) & 0x7FFFFFFF
    return bool(n & 1), bool(n & 2), bool(n & 4)

frames = []
for t in range(FRAME_COUNT):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    for x in range(0, W, 2):
        for y in range((x * 7) % 11, H, BG_STEP):
            if ((x * 31 + y * 17) % 5) == 0:
                draw.point((x, y), fill=(0, 9, 2))

    for s in streams:
        head_y = (s["start"] + s["speed"] * t) % H

        # Draw tail first, head last, so the bright head always stays on top
        # even when GAP is small enough for glyphs to overlap.
        for d in range(s["trail"] - 1, -1, -1):
            y = (head_y - d * GAP) % H
            fade = math.exp(-(d * GAP) / FADE_PX)

            if d == 0:
                color = (205, 255, 215)
            elif d == 1:
                color = (70, 255, 105)
            else:
                color = (
                    max(0, int(14 * fade)),
                    max(8, int(210 * fade)),
                    max(0, int(30 * fade)),
                )

            code_index = ((s["start"] + s["speed"] * t) // GAP - d) % 97
            right, lower_left, lower_right = glyph_bits(s["phase"], code_index)

            draw.point((s["x"], y), fill=color)
            if right and s["x"] + 1 < W:
                draw.point((s["x"] + 1, y), fill=color)
            if lower_left:
                draw.point((s["x"], (y + 1) % H), fill=color)
            if lower_right and s["x"] + 1 < W:
                draw.point((s["x"] + 1, (y + 1) % H), fill=color)

    frames.append(img)

name = f"matrix_code_{W}x{H}"
OUT.mkdir(parents=True, exist_ok=True)

frames[0].save(
    OUT / f"{name}.gif",
    save_all=True,
    append_images=frames[1:],
    duration=FRAME_MS,
    loop=0,
    disposal=2,
    optimize=False,
)

preview_frames = [
    frame.resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
    for frame in frames
]
preview_frames[0].save(
    OUT / f"{name}_preview.gif",
    save_all=True,
    append_images=preview_frames[1:],
    duration=FRAME_MS,
    loop=0,
    disposal=2,
    optimize=False,
)
