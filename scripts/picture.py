"""Render a drawing or a scene file to one picture, the one coolled-verbs' render returns.

Every frame as the panel lights it, each LED drawn several pixels wide on a grid, the
frames stacked top to bottom. It is how an agent without the MCP server, or a person,
looks at a drawing before sending it: write it, render the picture, look, fix.

SOURCE is a scene file (.json, as in examples/scenes, which may carry its own frame_ms)
or a drawing (any other file): frames written one character per pixel, '.' off, '#'
the foreground, R G B C M Y W a colour, and a blank line between frames. A mistake is
reported by where it is, such as "frame 1: row 2 is 63 wide but row 1 is 64".

Usage:
    uv run python scripts/picture.py examples/scenes/night-skyline.json skyline.png
    uv run python scripts/picture.py examples/scenes/pacman-chomp.txt chomp.png --scale 12
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opensign.animation.preview import contact_sheet
from opensign.animation.scene import compile_drawing, compile_scene
from opensign.protocol.codecs.coolledx import PIXEL_BYTES_MAX


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a drawing or a scene file to one picture.")
    parser.add_argument("source", type=Path, help="A scene (.json) or a drawing (text).")
    parser.add_argument("output", type=Path, help="Where to write the picture (.png).")
    parser.add_argument("--scale", type=int, default=8, help="Pixels each LED is drawn (default 8).")
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=16)
    parser.add_argument("--foreground", default="white", help="The colour '#' lights in a drawing.")
    parser.add_argument("--frame-ms", type=int, default=200, help="Hold per frame when the source names none.")
    args = parser.parse_args()
    budget = PIXEL_BYTES_MAX // (args.width * args.height * 3 // 8)
    try:
        text = args.source.read_text(encoding="utf-8")
        if args.source.suffix == ".json":
            scene = json.loads(text)
            bundle = compile_scene(scene, args.width, args.height,
                                   frame_ms=scene.get("frame_ms", args.frame_ms), max_frames=budget)
        else:
            bundle = compile_drawing(text, args.width, args.height, foreground=args.foreground,
                                     frame_ms=args.frame_ms, max_frames=budget)
    except (OSError, ValueError) as exc:
        print(f"picture: {args.source}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet(bundle.to_images(), scale=args.scale).save(args.output)
    print(f"{args.source}: {len(bundle.frames)} frame(s) -> {args.output}")


if __name__ == "__main__":
    main()
