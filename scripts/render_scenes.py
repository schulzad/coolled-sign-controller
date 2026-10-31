"""Render every scene in examples/scenes to a preview and a playable frame bundle.

A scene file is what coolled-verbs' scene noun takes (sprites, items, and frames)
plus the frame_ms it plays at. Each examples/scenes/NAME.json becomes, in
examples/generated/scenes/:

    NAME.gif           its frames as the panel lights them, each LED 8 px wide
                       (NAME.png for a one-frame scene)
    NAME.bundle.json   the compiled frames, which coolled send plays on the panel

Usage:
    uv run python scripts/render_scenes.py
    uv run python scripts/render_scenes.py examples/scenes/night-skyline.json

    # then play one on the panel
    coolled send examples/generated/scenes/night-skyline.bundle.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opensign.animation.preview import save_preview
from opensign.animation.scene import compile_scene
from opensign.protocol.codecs.coolledx import PIXEL_BYTES_MAX

REPO = Path(__file__).resolve().parents[1]
SCENES = REPO / "examples" / "scenes"
GENERATED = REPO / "examples" / "generated" / "scenes"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render scene files to previews and frame bundles.")
    parser.add_argument("scenes", nargs="*", type=Path, help="Scene files; default every examples/scenes/*.json.")
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=16)
    parser.add_argument("--out", type=Path, default=GENERATED)
    args = parser.parse_args()
    budget = PIXEL_BYTES_MAX // (args.width * args.height * 3 // 8)
    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.scenes or sorted(SCENES.glob("*.json")):
        scene = json.loads(path.read_text(encoding="utf-8"))
        bundle = compile_scene(
            scene, args.width, args.height, frame_ms=scene.get("frame_ms", 200), max_frames=budget
        )
        suffix = ".gif" if len(bundle.frames) > 1 else ".png"
        preview = save_preview(bundle, args.out / f"{path.stem}{suffix}", scale=8)
        saved = bundle.save(args.out / f"{path.stem}.bundle.json")
        print(f"{path.name}: {len(bundle.frames)} frame(s) -> {preview}, {saved}")


if __name__ == "__main__":
    main()
