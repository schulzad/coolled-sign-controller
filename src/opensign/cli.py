"""Unified ``coolled`` command line.

A thin umbrella over the focused entry points. Discovery, preview, and service
commands delegate to their existing CLIs; ``text``/``image``/``animation`` are
one-shot render-and-send helpers built on the animation studio and the protocol
runtime. These send to the panel by default; pass ``--dry-run`` to build the
transfer plan (and any preview/bundle) without touching Bluetooth.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import opensign.protocol  # noqa: F401  (registers bundled device codecs)
from opensign.animation.cache import RenderBundleCache
from opensign.animation.preview import save_preview
from opensign.animation.render import render_wide_text
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, FrameBundle
from opensign.protocol.codecs.coolledx import (
    MODE_LEFT,
    PIXEL_BYTES_MAX,
    USER_SCROLL_SPEED_MAX,
    USER_SCROLL_SPEED_MIN,
    map_user_scroll_speed,
)
from opensign.protocol.runtime import ProtocolRuntime

DEFAULT_PROFILE = Path("device_profile.local.json")

# command -> (module providing main(), optional inner subcommand to prepend)
_DELEGATED: dict[str, tuple[str, str | None]] = {
    "scan": ("opensign.hardware_probe.cli", "scan"),
    "inspect": ("opensign.hardware_probe.cli", "inspect"),
    "preview": ("opensign.animation.preview", None),
    "control": ("opensign.protocol.cli", "control"),
    "send": ("opensign.protocol.cli", "bundle"),
    "serve": ("opensign.sdk.api_cli", None),
}

_HELP = """coolled - CoolLED sign control

Usage: coolled <command> [options]

Discovery (read-only):
  scan                 Scan for CoolLED panels and rank candidates
  inspect <id>         Inspect one device's GATT and draft a profile

Render + send (writes to the panel; --dry-run to preview):
  text "MESSAGE"       Native scroll text by default (--speed 0-10); --no-scroll for static
  image <path>         Fit an image to the panel and send
  animation <path>     Render an animated GIF/WebP/APNG and send (aliases: anim, gif)
  send <bundle.json>   Send a prepared frame bundle
  control ...          Send a control command (brightness/power/...)

Preview (no hardware):
  preview ...          Render a pattern to a local .gif/.png

Service:
  serve                Run the localhost API

Run 'coolled <command> --help' for a command's options.
"""


def _add_common_send_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the transfer plan (and preview/bundle) without any BLE writes.",
    )
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument(
        "--preview",
        type=Path,
        help="Write a scaled preview (.gif/.png) and skip BLE delivery.",
    )
    parser.add_argument("--bundle-out", type=Path, help="Also write the frame bundle JSON.")
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15.0)


def _add_fit_argument(parser: argparse.ArgumentParser) -> None:
    def fit_mode(value: str) -> str:
        modes = {
            "contain": "contain",
            "cover": "cover",
            "fill": "stretch",
            "stretch": "stretch",
        }
        try:
            return modes[value]
        except KeyError as exc:
            raise argparse.ArgumentTypeError(
                "choose contain, cover, or fill (stretch is also accepted as an alias)"
            ) from exc

    parser.add_argument(
        "--fit",
        type=fit_mode,
        metavar="{contain,cover,fill}",
        default="contain",
        help=(
            "Map the source onto the panel: contain keeps the whole image with padding; "
            "cover fills by cropping; fill distorts aspect ratio to fill "
            "(legacy alias: stretch)."
        ),
    )


def _should_execute(args: argparse.Namespace) -> bool:
    """Preview and dry-run modes are always hardware-safe."""
    return not args.dry_run and args.preview is None


def _add_render_cache_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Render from scratch instead of reusing a content-and-parameter keyed bundle.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Render cache directory (default: $OPENSIGN_CACHE_DIR or ~/.cache/opensign-coolled/renders).",
    )


def _render_cached(
    args: argparse.Namespace,
    *,
    kind: str,
    source: Path,
    parameters: Mapping[str, Any],
    render: Callable[[], FrameBundle],
) -> FrameBundle:
    if args.no_cache:
        print("render cache: disabled; rendering from source", file=sys.stderr)
        return render()

    def render_miss() -> FrameBundle:
        print("render cache: miss; rendering from source", file=sys.stderr)
        return render()

    cached = RenderBundleCache(args.cache_dir).get_or_create(
        source,
        kind=kind,
        parameters=parameters,
        render=render_miss,
    )
    if cached.hit:
        print(f"render cache: hit {cached.key[:12]}", file=sys.stderr)
    elif cached.write_error:
        print(f"render cache: could not store entry: {cached.write_error}", file=sys.stderr)
    else:
        print(f"render cache: stored {cached.key[:12]}", file=sys.stderr)
    return cached.bundle


def _print_transfer_summary(result: dict) -> None:
    """Human-readable digest on stderr so the JSON firehose stays parseable.

    Distinguishes the two silent-failure modes we care about: the device NAKed a
    chunk (a distinct notification payload appears) versus it accepted every chunk
    but still did not display (all acks in, zero timeouts -> a device-side
    capacity/ceiling issue rather than a transport error).
    """
    meta = result.get("encoded", {}).get("metadata", {})
    transfer = result.get("transfer", {})
    notifications = transfer.get("notifications", [])
    distinct = Counter(note.get("hex", "") for note in notifications)
    lines = [
        "-- transfer summary --",
        f"opcode={meta.get('opcode')} frames={meta.get('frame_count')} "
        f"payload={meta.get('payload_bytes')}B",
        f"success={transfer.get('success')} dry_run={transfer.get('dry_run')} "
        f"packets={transfer.get('packet_count')} acks={transfer.get('acks_received')} "
        f"timeouts={transfer.get('ack_timeouts')}",
    ]
    for error in transfer.get("errors", []):
        lines.append(f"error: {error}")
    if distinct:
        lines.append(f"device notifications ({len(notifications)} total, "
                     f"{len(distinct)} distinct):")
        for hexval, count in distinct.most_common(6):
            lines.append(f"  {hexval or '<empty>'} x{count}")
    print("\n".join(lines), file=sys.stderr)


def _print_image_diagnostics(bundle) -> None:
    """Surface levels + which channels can actually light, on stderr.

    Auto-levels picks values the user never sees otherwise, and a low-contrast
    source often can only render one colour (red/blue below the 1-bit threshold),
    which is the usual reason an image looks dim -- name it so the fix (auto/manual
    levels) is obvious.
    """
    meta = bundle.metadata
    levels = meta.get("levels")
    if levels and (levels.get("auto") or levels.get("black", 0) or levels.get("white", 255) != 255):
        tag = " (auto)" if levels.get("auto") else ""
        print(f"levels: black={levels.get('black')} white={levels.get('white')}{tag}", file=sys.stderr)
    reachable = meta.get("reachable_channels")
    if reachable is not None:
        dark = [c for c in ("red", "green", "blue") if c not in reachable]
        if dark:
            lit = ", ".join(reachable) if reachable else "nothing"
            print(
                f"note: on this panel this image can only light {lit}; "
                f"{', '.join(dark)} stay below the 1-bit threshold "
                f"(try --auto-levels, or raise --white-level)",
                file=sys.stderr,
            )


def _print_native_text_summary(result: dict) -> None:
    """Digest for native text scroll (banner + SPEED + MODE on one session)."""
    meta = result.get("native_text", {})
    banner_meta = result.get("encoded", {}).get("banner", {}).get("metadata", {})
    transfers = result.get("transfers", [])
    banner_xfer = next((t["transfer"] for t in transfers if t.get("step") == "banner"), {})
    lines = [
        "-- transfer summary --",
        f"opcode={banner_meta.get('opcode')} native_text "
        f"banner={meta.get('banner_width')}x{banner_meta.get('banner_height')} "
        f"payload={banner_meta.get('payload_bytes')}B",
        f"user_speed={meta.get('user_speed')} -> device_speed={meta.get('device_speed')} "
        f"mode={meta.get('mode')}",
        f"banner success={banner_xfer.get('success')} dry_run={banner_xfer.get('dry_run')} "
        f"packets={banner_xfer.get('packet_count')} acks={banner_xfer.get('acks_received')} "
        f"timeouts={banner_xfer.get('ack_timeouts')}",
    ]
    print("\n".join(lines), file=sys.stderr)


def _finish(profile: DeviceProfile, bundle, args: argparse.Namespace) -> None:
    if args.preview:
        save_preview(bundle, args.preview, scale=8)
    if args.bundle_out:
        bundle.save(args.bundle_out)
    execute = _should_execute(args)
    action = "uploading to panel" if execute else "building no-send transfer plan"
    print(f"{action}: {len(bundle.frames)} frame(s)", file=sys.stderr)
    result = asyncio.run(
        ProtocolRuntime(profile).upload_frame_bundle(
            bundle,
            execute=execute,
            retry_limit=args.retry_limit,
            timeout_seconds=args.timeout,
        )
    )
    print(json.dumps(result, indent=2))
    _print_transfer_summary(result)
    transfer = result.get("transfer", {})
    if not transfer.get("success", False):
        detail = "; ".join(transfer.get("errors", [])) or "device transfer failed"
        raise RuntimeError(detail)


def _cmd_text(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="coolled text",
        description="Send text to the panel. Scrolling uses the device's native scroll "
        "(one wide bitmap + SPEED/MODE); --no-scroll sends a single static frame.",
    )
    parser.add_argument("text")
    parser.add_argument("--no-scroll", action="store_true", help="Render a single static frame (image opcode).")
    parser.add_argument(
        "--speed",
        type=int,
        default=8,
        metavar="N",
        help=f"Native scroll speed {USER_SCROLL_SPEED_MIN}..{USER_SCROLL_SPEED_MAX} "
        f"(higher=faster; default 8). Ignored with --no-scroll / --flipbook.",
    )
    parser.add_argument(
        "--mode",
        type=int,
        default=MODE_LEFT,
        help="Native scroll MODE byte (default 2=left). Ignored with --no-scroll / --flipbook.",
    )
    parser.add_argument(
        "--flipbook",
        action="store_true",
        help="Use the host-side scroll flipbook (legacy) instead of native firmware scroll.",
    )
    parser.add_argument("--fps", type=float, default=12.0, help="Flipbook frame rate (only with --flipbook).")
    parser.add_argument("--foreground", default="white")
    parser.add_argument("--background", default="black")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Cap flipbook frames (only with --flipbook; default: panel frame-buffer budget).",
    )
    _add_common_send_arguments(parser)
    args = parser.parse_args(argv)
    if not args.no_scroll and not args.flipbook:
        if args.speed < USER_SCROLL_SPEED_MIN or args.speed > USER_SCROLL_SPEED_MAX:
            parser.error(f"--speed must be {USER_SCROLL_SPEED_MIN}..{USER_SCROLL_SPEED_MAX}")

    profile = DeviceProfile.load(args.profile)

    if args.no_scroll or args.flipbook:
        studio = PixelAnimationStudio(profile.width, profile.height)
        per_frame = max(1, profile.width * profile.height * 3 // 8)
        frame_budget = PIXEL_BYTES_MAX // per_frame
        max_frames = args.max_frames if args.max_frames is not None else frame_budget
        bundle = studio.create_text_bundle(
            args.text,
            scroll=not args.no_scroll,
            frames_per_second=args.fps,
            foreground=args.foreground,
            background=args.background,
            max_frames=None if args.no_scroll else max_frames,
            rotation=args.rotate,
            flip_horizontal=args.flip_horizontal,
            flip_vertical=args.flip_vertical,
        )
        _finish(profile, bundle, args)
        return

    # Native firmware scroll: one wide banner + SPEED + MODE.
    banner = render_wide_text(
        args.text,
        profile.height,
        foreground=args.foreground,
        background=args.background,
    )
    if args.rotate or args.flip_horizontal or args.flip_vertical:
        # Orientation applies to the banner bitmap before encode; 90/270 change
        # which axis is "wide", so refuse those for native scroll.
        if args.rotate in (90, 270):
            raise ValueError("native scroll does not support --rotate 90/270; use --no-scroll or --flipbook")
        from PIL import Image as _Image

        if args.rotate == 180:
            banner = banner.transpose(_Image.Transpose.ROTATE_180)
        if args.flip_horizontal:
            banner = banner.transpose(_Image.Transpose.FLIP_LEFT_RIGHT)
        if args.flip_vertical:
            banner = banner.transpose(_Image.Transpose.FLIP_TOP_BOTTOM)

    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        banner.save(args.preview)
    if args.bundle_out:
        print("note: --bundle-out is ignored for native scroll (no FrameBundle)", file=sys.stderr)

    device_speed = map_user_scroll_speed(args.speed)
    print(
        f"native scroll: banner {banner.width}x{banner.height}, "
        f"user_speed={args.speed} -> device_speed={device_speed}, mode={args.mode}",
        file=sys.stderr,
    )
    result = asyncio.run(
        ProtocolRuntime(profile).play_native_text(
            args.text,
            banner.tobytes(),
            banner.width,
            speed=args.speed,
            mode=args.mode,
            execute=_should_execute(args),
            retry_limit=args.retry_limit,
            timeout_seconds=args.timeout,
        )
    )
    print(json.dumps(result, indent=2))
    _print_native_text_summary(result)


def _cmd_image(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="coolled image", description="Fit an image and send it.")
    parser.add_argument("path", type=Path)
    _add_fit_argument(parser)
    parser.add_argument("--background", default="black")
    parser.add_argument("--duration-ms", type=int, default=1000)
    parser.add_argument(
        "--dither",
        choices=["ordered", "floyd", "none"],
        default="none",
        help=(
            "Colour reduction to the panel's 8-colour gamut. Default 'none' keeps "
            "logos/icons/UI crisp; use 'floyd' or 'ordered' for photographic images."
        ),
    )
    parser.add_argument(
        "--temporal",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Temporal colour: render the still as a fast N-subframe loop (N>=2) so "
            "duty cycle fakes intermediate colours. Relies on the panel's flicker "
            "fusion (~62 Hz); ignores --dither. 0 disables (default)."
        ),
    )
    parser.add_argument(
        "--black-level",
        type=int,
        default=0,
        metavar="V",
        help=(
            "Crush channel values <= V to off before dithering. Use this when a "
            "dark (but not truly black) background washes out to grey, especially "
            "with high --temporal. Try 30-50 for dark UI screenshots."
        ),
    )
    parser.add_argument(
        "--white-level",
        type=int,
        default=255,
        metavar="V",
        help="Lift channel values >= V to full on before dithering (boosts muted foregrounds).",
    )
    parser.add_argument(
        "--auto-levels",
        action="store_true",
        help=(
            "Auto contrast-stretch from the image's own histogram (crushes dark "
            "backgrounds, lifts muted foregrounds) so low-contrast art -- logos, "
            "UI badges, screenshots -- reads on the panel. Overrides "
            "--black-level/--white-level."
        ),
    )
    _add_common_send_arguments(parser)
    _add_render_cache_arguments(parser)
    args = parser.parse_args(argv)
    profile = DeviceProfile.load(args.profile)
    studio = PixelAnimationStudio(profile.width, profile.height)
    if args.temporal and args.temporal >= 2:
        bundle = _render_cached(
            args,
            kind="temporal-image",
            source=args.path,
            parameters={
                "width": profile.width,
                "height": profile.height,
                "subframes": args.temporal,
                "fit_mode": args.fit,
                "background": args.background,
                "auto_levels": args.auto_levels,
                "black_point": args.black_level,
                "white_point": args.white_level,
                "rotation": args.rotate,
                "flip_horizontal": args.flip_horizontal,
                "flip_vertical": args.flip_vertical,
            },
            render=lambda: studio.create_temporal_image_bundle(
                args.path,
                subframes=args.temporal,
                fit_mode=args.fit,
                background=args.background,
                auto_levels=args.auto_levels,
                black_point=args.black_level,
                white_point=args.white_level,
                rotation=args.rotate,
                flip_horizontal=args.flip_horizontal,
                flip_vertical=args.flip_vertical,
            ),
        )
    else:
        bundle = _render_cached(
            args,
            kind="image",
            source=args.path,
            parameters={
                "width": profile.width,
                "height": profile.height,
                "fit_mode": args.fit,
                "background": args.background,
                "duration_ms": args.duration_ms,
                "dither": args.dither,
                "auto_levels": args.auto_levels,
                "black_point": args.black_level,
                "white_point": args.white_level,
                "rotation": args.rotate,
                "flip_horizontal": args.flip_horizontal,
                "flip_vertical": args.flip_vertical,
            },
            render=lambda: studio.create_image_bundle(
                args.path,
                fit_mode=args.fit,
                background=args.background,
                duration_ms=args.duration_ms,
                dither=args.dither,
                auto_levels=args.auto_levels,
                black_point=args.black_level,
                white_point=args.white_level,
                rotation=args.rotate,
                flip_horizontal=args.flip_horizontal,
                flip_vertical=args.flip_vertical,
            ),
        )
    _print_image_diagnostics(bundle)
    _finish(profile, bundle, args)


def _cmd_animation(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="coolled animation",
        description="Render an animated GIF, WebP, APNG, or other Pillow-supported image and send it.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Force a uniform rate (default: the source animation's own timing).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Evenly subsample longer clips (default: the panel's frame-buffer budget).",
    )
    _add_fit_argument(parser)
    parser.add_argument("--background", default="black")
    parser.add_argument(
        "--dither",
        choices=["ordered", "floyd", "none"],
        default="ordered",
        help="Colour reduction to the panel's 8-colour gamut (default: ordered, best for animation).",
    )
    parser.add_argument(
        "--key-color",
        default=None,
        metavar="COLOR",
        help=(
            "Knock a background colour out to black so a bright, full-scene clip "
            "does not light the whole 1-bit panel (the subject keeps its colours). "
            "Pass a colour ('skyblue', '#87CEEB') or 'auto' to sample it from the "
            "frame border."
        ),
    )
    parser.add_argument(
        "--key-tolerance",
        type=int,
        default=96,
        metavar="D",
        help="How close (0-441 RGB distance) a pixel must be to --key-color to be removed (default 96).",
    )
    _add_common_send_arguments(parser)
    _add_render_cache_arguments(parser)
    args = parser.parse_args(argv)
    profile = DeviceProfile.load(args.profile)
    studio = PixelAnimationStudio(profile.width, profile.height)
    per_frame = max(1, profile.width * profile.height * 3 // 8)
    frame_budget = PIXEL_BYTES_MAX // per_frame
    max_frames = args.max_frames if args.max_frames is not None else frame_budget
    bundle = _render_cached(
        args,
        kind="gif",
        source=args.path,
        parameters={
            "width": profile.width,
            "height": profile.height,
            "fps": args.fps,
            "max_frames": max_frames,
            "fit_mode": args.fit,
            "background": args.background,
            "dither": args.dither,
            "key_color": args.key_color,
            "key_tolerance": args.key_tolerance,
            "rotation": args.rotate,
            "flip_horizontal": args.flip_horizontal,
            "flip_vertical": args.flip_vertical,
        },
        render=lambda: studio.create_gif_bundle(
            args.path,
            fps=args.fps,
            max_frames=max_frames,
            fit_mode=args.fit,
            background=args.background,
            dither=args.dither,
            key_color=args.key_color,
            key_tolerance=args.key_tolerance,
            rotation=args.rotate,
            flip_horizontal=args.flip_horizontal,
            flip_vertical=args.flip_vertical,
        ),
    )
    _finish(profile, bundle, args)


_DIRECT = {
    "text": _cmd_text,
    "image": _cmd_image,
    "animation": _cmd_animation,
    "anim": _cmd_animation,
    "gif": _cmd_animation,
}


def _delegate(main_name: str, prog: str, inner_argv: list[str]) -> None:
    module_name, inner = _DELEGATED[main_name]
    module = importlib.import_module(module_name)
    saved = sys.argv
    sys.argv = [prog, *(([inner] if inner else []) + inner_argv)]
    try:
        module.main()
    finally:
        sys.argv = saved


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_HELP)
        return
    command, rest = argv[0], argv[1:]
    if command in _DIRECT:
        try:
            _DIRECT[command](rest)
        except KeyboardInterrupt:
            raise SystemExit(130) from None
        except Exception as exc:  # noqa: BLE001 - present a friendly one-line error
            print(f"coolled {command}: {type(exc).__name__}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if command in _DELEGATED:
        _delegate(command, f"coolled {command}", rest)
        return
    print(f"coolled: unknown command {command!r}\n", file=sys.stderr)
    print(_HELP, file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
