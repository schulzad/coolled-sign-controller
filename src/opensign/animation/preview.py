from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from opensign.contracts import FrameBundle

from .studio import PixelAnimationStudio


def scale_frame(image: Image.Image, *, scale: int = 16, grid: bool = False) -> Image.Image:
    if scale <= 0:
        raise ValueError("scale must be positive")
    enlarged = image.resize(
        (image.width * scale, image.height * scale),
        resample=Image.Resampling.NEAREST,
    )
    if grid and scale >= 3:
        draw = ImageDraw.Draw(enlarged)
        for x in range(0, enlarged.width + 1, scale):
            draw.line((x, 0, x, enlarged.height - 1), fill=(48, 48, 48))
        for y in range(0, enlarged.height + 1, scale):
            draw.line((0, y, enlarged.width - 1, y), fill=(48, 48, 48))
    return enlarged


def _expanded_loop(bundle: FrameBundle, images: list[Image.Image]) -> tuple[list[Image.Image], list[int]]:
    durations = list(bundle.frame_durations_ms)
    if bundle.loop_mode == "ping_pong" and len(images) > 2:
        return images + images[-2:0:-1], durations + durations[-2:0:-1]
    return images, durations


def save_preview(
    bundle: FrameBundle,
    path: str | Path,
    *,
    scale: int = 16,
    grid: bool = False,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    images = [scale_frame(image, scale=scale, grid=grid) for image in bundle.to_images()]
    images, durations = _expanded_loop(bundle, images)
    suffix = target.suffix.casefold()
    if suffix == ".gif":
        options = {
            "save_all": True,
            "append_images": images[1:],
            "duration": durations,
            "disposal": 2,
        }
        if bundle.loop_mode != "once":
            options["loop"] = 0
        images[0].save(target, format="GIF", **options)
    elif suffix == ".png":
        images[0].save(target, format="PNG")
    else:
        raise ValueError("Preview output must end in .gif or .png")
    return target


def terminal_preview(image: Image.Image) -> str:
    image = image.convert("RGB")
    lines: list[str] = []
    for y in range(image.height):
        line = []
        for x in range(image.width):
            red, green, blue = image.getpixel((x, y))
            line.append(f"\x1b[48;2;{red};{green};{blue}m  ")
        line.append("\x1b[0m")
        lines.append("".join(line))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensign-preview",
        description="Render and preview low-resolution OpenSign frame bundles.",
    )
    parser.add_argument(
        "--pattern",
        choices=["test", "two-frame", "checker", "text", "image"],
        default="two-frame",
    )
    parser.add_argument("--width", type=int, default=48)
    parser.add_argument("--height", type=int, default=12)
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--frames", type=int, default=8, help="Frame count for checker mode.")
    parser.add_argument("--text", default="OPEN SIGN")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--foreground", default="#00E5FF")
    parser.add_argument("--background", default="#071A2B")
    parser.add_argument("--fit-mode", choices=["contain", "cover", "stretch"], default="contain")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument("--scale", type=int, default=16)
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--no-loop", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("preview.gif"))
    parser.add_argument("--bundle-out", type=Path)
    parser.add_argument("--terminal", action="store_true")
    return parser


def _make_bundle(args: argparse.Namespace) -> FrameBundle:
    studio = PixelAnimationStudio(args.width, args.height)
    loop_mode = "once" if args.no_loop else "loop"
    common = {
        "rotation": args.rotate,
        "flip_horizontal": args.flip_horizontal,
        "flip_vertical": args.flip_vertical,
    }
    if args.pattern == "test":
        return studio.create_test_pattern_bundle(duration_ms=max(1, round(1000 / args.fps)), **common)
    if args.pattern == "two-frame":
        return studio.create_two_frame_bundle(
            frames_per_second=args.fps,
            loop_mode=loop_mode,
            **common,
        )
    if args.pattern == "checker":
        return studio.create_checker_bundle(
            frame_count=args.frames,
            frames_per_second=args.fps,
            foreground=args.foreground,
            background=args.background,
            loop_mode=loop_mode,
            **common,
        )
    if args.pattern == "text":
        return studio.create_text_bundle(
            args.text,
            scroll=True,
            frames_per_second=args.fps,
            foreground=args.foreground,
            background=args.background,
            loop_mode=loop_mode,
            **common,
        )
    if args.image is None:
        raise ValueError("--image is required when --pattern image is selected")
    return studio.create_image_bundle(
        args.image,
        duration_ms=max(1, round(1000 / args.fps)),
        fit_mode=args.fit_mode,
        background=args.background,
        **common,
    )


def main() -> None:
    args = build_parser().parse_args()
    try:
        bundle = _make_bundle(args)
        preview_path = save_preview(bundle, args.output, scale=args.scale, grid=args.grid)
        bundle_path = bundle.save(args.bundle_out) if args.bundle_out else None
        if args.terminal:
            print(terminal_preview(bundle.to_images()[0]))
        print(
            json.dumps(
                {
                    "preview": str(preview_path),
                    "frame_bundle": str(bundle_path) if bundle_path else None,
                    "summary": bundle.summary(),
                    "metadata": bundle.metadata,
                },
                indent=2,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"opensign-preview: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
