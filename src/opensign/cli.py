"""Unified ``coolled`` command line.

A thin umbrella over the focused entry points. Discovery, preview, and service
commands delegate to their existing CLIs; ``text``/``image``/``gif`` are one-shot
render-and-send helpers built on the animation studio and the protocol runtime.
Physical BLE writes always require an explicit ``--execute`` flag.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

import opensign.protocol  # noqa: F401  (registers bundled device codecs)
from opensign.animation.preview import save_preview
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile
from opensign.protocol.codecs.coolledx import PIXEL_BYTES_MAX
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

Render + send (BLE writes require --execute):
  text "MESSAGE"       Render text (scrolling by default) and send
  image <path>         Fit an image to the panel and send
  gif <path>           Render a GIF at its own frame rate and send
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
    parser.add_argument("--execute", action="store_true", help="Perform physical BLE writes.")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument("--preview", type=Path, help="Also write a scaled preview (.gif/.png).")
    parser.add_argument("--bundle-out", type=Path, help="Also write the frame bundle JSON.")
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15.0)


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
    if distinct:
        lines.append(f"device notifications ({len(notifications)} total, "
                     f"{len(distinct)} distinct):")
        for hexval, count in distinct.most_common(6):
            lines.append(f"  {hexval or '<empty>'} x{count}")
    print("\n".join(lines), file=sys.stderr)


def _finish(profile: DeviceProfile, bundle, args: argparse.Namespace) -> None:
    if args.preview:
        save_preview(bundle, args.preview, scale=8)
    if args.bundle_out:
        bundle.save(args.bundle_out)
    result = asyncio.run(
        ProtocolRuntime(profile).upload_frame_bundle(
            bundle,
            execute=args.execute,
            retry_limit=args.retry_limit,
            timeout_seconds=args.timeout,
        )
    )
    print(json.dumps(result, indent=2))
    _print_transfer_summary(result)


def _cmd_text(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="coolled text", description="Render text and send it.")
    parser.add_argument("text")
    parser.add_argument("--no-scroll", action="store_true", help="Render a single static frame.")
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--foreground", default="white")
    parser.add_argument("--background", default="black")
    _add_common_send_arguments(parser)
    args = parser.parse_args(argv)
    profile = DeviceProfile.load(args.profile)
    studio = PixelAnimationStudio(profile.width, profile.height)
    bundle = studio.create_text_bundle(
        args.text,
        scroll=not args.no_scroll,
        frames_per_second=args.fps,
        foreground=args.foreground,
        background=args.background,
        rotation=args.rotate,
        flip_horizontal=args.flip_horizontal,
        flip_vertical=args.flip_vertical,
    )
    _finish(profile, bundle, args)


def _cmd_image(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="coolled image", description="Fit an image and send it.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--fit", choices=["contain", "cover", "stretch"], default="contain")
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
    _add_common_send_arguments(parser)
    args = parser.parse_args(argv)
    profile = DeviceProfile.load(args.profile)
    studio = PixelAnimationStudio(profile.width, profile.height)
    if args.temporal and args.temporal >= 2:
        bundle = studio.create_temporal_image_bundle(
            args.path,
            subframes=args.temporal,
            fit_mode=args.fit,
            background=args.background,
            black_point=args.black_level,
            white_point=args.white_level,
            rotation=args.rotate,
            flip_horizontal=args.flip_horizontal,
            flip_vertical=args.flip_vertical,
        )
    else:
        bundle = studio.create_image_bundle(
            args.path,
            fit_mode=args.fit,
            background=args.background,
            duration_ms=args.duration_ms,
            dither=args.dither,
            black_point=args.black_level,
            white_point=args.white_level,
            rotation=args.rotate,
            flip_horizontal=args.flip_horizontal,
            flip_vertical=args.flip_vertical,
        )
    _finish(profile, bundle, args)


def _cmd_gif(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="coolled gif", description="Render a GIF and send it.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--fps", type=float, default=None, help="Force a uniform rate (default: the GIF's own timing).")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Evenly subsample longer clips (default: the panel's frame-buffer budget).",
    )
    parser.add_argument("--fit", choices=["contain", "cover", "stretch"], default="contain")
    parser.add_argument("--background", default="black")
    parser.add_argument(
        "--dither",
        choices=["ordered", "floyd", "none"],
        default="ordered",
        help="Colour reduction to the panel's 8-colour gamut (default: ordered, best for animation).",
    )
    _add_common_send_arguments(parser)
    args = parser.parse_args(argv)
    profile = DeviceProfile.load(args.profile)
    studio = PixelAnimationStudio(profile.width, profile.height)
    per_frame = max(1, profile.width * profile.height * 3 // 8)
    frame_budget = PIXEL_BYTES_MAX // per_frame
    max_frames = args.max_frames if args.max_frames is not None else frame_budget
    bundle = studio.create_gif_bundle(
        args.path,
        fps=args.fps,
        max_frames=max_frames,
        fit_mode=args.fit,
        background=args.background,
        dither=args.dither,
        rotation=args.rotate,
        flip_horizontal=args.flip_horizontal,
        flip_vertical=args.flip_vertical,
    )
    _finish(profile, bundle, args)


_DIRECT = {"text": _cmd_text, "image": _cmd_image, "gif": _cmd_gif}


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
