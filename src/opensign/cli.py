"""Unified ``coolled`` command line.

A thin umbrella over the focused entry points. Discovery, preview, and service
commands delegate to their existing CLIs; ``text``/``image``/``animation`` are
one-shot render-and-send helpers built on the animation studio and the protocol
runtime. These send to the panel by default; pass ``--dry-run`` to build the
transfer plan (and any preview/bundle) without touching Bluetooth, and ``-v`` to
print the full plan/result JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

import opensign.protocol  # noqa: F401  (registers bundled device codecs)
from opensign.animation.cache import RenderBundleCache, default_render_cache_dir
from opensign.animation.preview import save_preview
from opensign.animation.render import render_wide_text
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, FrameBundle
from opensign.protocol.codec import CodecError
from opensign.protocol.codecs.coolledx import (
    MODE_LEFT,
    PIXEL_BYTES_MAX,
    USER_SCROLL_SPEED_MAX,
    USER_SCROLL_SPEED_MIN,
    map_user_scroll_speed,
)
from opensign.protocol.runtime import ProtocolRuntime

DEFAULT_PROFILE = Path("device_profile.local.json")
STARTER_PROFILE = Path("device_profile.json")


def _load_profile(args: argparse.Namespace) -> DeviceProfile:
    """Load the requested profile, falling back to the checked-in starter.

    ``--profile`` defaults to the git-ignored ``device_profile.local.json`` that a
    user generates for their own panel. A fresh clone does not have one yet, so
    when the default is requested but absent we fall back to the checked-in
    ``device_profile.json`` starter (codec-valid 64x16) with a note, letting
    ``--preview``/``--dry-run`` work off the bat. An explicit ``--profile`` path
    is always honoured as-is.
    """
    path = args.profile
    if path == DEFAULT_PROFILE and not path.exists() and STARTER_PROFILE.exists():
        print(
            f"note: {DEFAULT_PROFILE} not found; using the checked-in starter "
            f"{STARTER_PROFILE}. Run 'coolled inspect <id> --profile-out "
            f"{DEFAULT_PROFILE}' to profile your own panel.",
            file=sys.stderr,
        )
        path = STARTER_PROFILE
    return DeviceProfile.load(path)

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
        help="Build the transfer plan (and preview/bundle) without any BLE writes; add -v to print it.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also print the full transfer plan/result as JSON on stdout (every packet's bytes).",
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


def _timing_line(transfer: Mapping[str, Any], elapsed_s: float | None) -> str | None:
    """Actual upload timing, or None for a dry run (nothing was sent).

    ``total`` is the whole call including finding and connecting to the panel;
    ``transfer`` is only the bytes moving. ``per_packet`` appears only when every
    packet landed, so a stopped transfer never reports a misleading rate.
    """
    duration_ms = transfer.get("duration_ms")
    if duration_ms is None:
        return None
    parts = [] if elapsed_s is None else [f"total={elapsed_s:.1f}s"]
    parts.append(f"transfer={duration_ms / 1000:.1f}s")
    packets = transfer.get("packet_count") or 0
    if transfer.get("success") and packets:
        parts.append(f"per_packet={duration_ms / packets:.0f}ms")
    return " ".join(parts)


def _print_transfer_summary(result: dict, *, elapsed_s: float | None = None) -> None:
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
    timing = _timing_line(transfer, elapsed_s)
    if timing:
        lines.append(timing)
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


def _print_native_text_summary(result: dict, *, elapsed_s: float | None = None) -> None:
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
    timing = _timing_line(banner_xfer, elapsed_s)
    if timing:
        lines.append(timing)
    print("\n".join(lines), file=sys.stderr)


# The panel acks its first ~30 chunks fast, then settles to a slower steady rate a few
# seconds in (measured 2026-10-29: 153 ms, then about 220 ms). Only an upload long enough
# for its second half to sit past that warm-up may teach the remembered rate.
_MIN_PACKETS_TO_LEARN_RATE = 60


class _UploadProgress:
    """Redraw one stderr line while packets go out, e.g. ``uploading 112/238 (47%), ~29 s left``.

    Time left uses ``seconds_per_packet`` -- the panel's steady rate remembered from an
    earlier upload -- when known, because an upload's own early chunks are acked faster
    than the rest and would undershoot; otherwise it extrapolates the average so far.
    Timing is tracked even off a terminal so ``steady_seconds_per_packet`` can be learned,
    but the line only draws on one, so piped or logged stderr stays clean. Redraws use a
    carriage return plus space padding rather than ANSI escapes, so any console renders it.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        seconds_per_packet: float | None = None,
    ):
        self.stream = sys.stderr if stream is None else stream
        self.clock = clock
        self.seconds_per_packet = seconds_per_packet
        self.enabled = self.stream.isatty()
        self._started: float | None = None
        self._halfway: tuple[int, float] | None = None
        self._finished: tuple[int, float] | None = None
        self._width = 0

    def __call__(self, sent: int, total: int) -> None:
        if total <= 0:
            return
        now = self.clock()
        if self._started is None:
            self._started = now
        if self._halfway is None and sent * 2 >= total:
            self._halfway = (sent, now)
        if sent >= total:
            self._finished = (sent, now)
        if self.enabled:
            self._draw(sent, total, now - self._started)

    @property
    def steady_seconds_per_packet(self) -> float | None:
        """Per-packet time over the second half of a finished upload; None if it was too short."""
        if self._halfway is None or self._finished is None:
            return None
        (half_sent, half_at), (end_sent, end_at) = self._halfway, self._finished
        if end_sent < _MIN_PACKETS_TO_LEARN_RATE or end_sent <= half_sent:
            return None
        return (end_at - half_at) / (end_sent - half_sent)

    def _draw(self, sent: int, total: int, elapsed: float) -> None:
        if sent >= total:
            tail = f"done in {elapsed:.1f} s"
        elif self.seconds_per_packet:
            tail = f"~{math.ceil(self.seconds_per_packet * (total - sent))} s left"
        elif sent:
            tail = f"~{math.ceil(elapsed / sent * (total - sent))} s left"
        else:
            tail = "starting"
        line = f"uploading {sent}/{total} ({sent * 100 // total}%), {tail}"
        self.stream.write("\r" + line.ljust(self._width))
        self.stream.flush()
        self._width = len(line)

    def __enter__(self) -> _UploadProgress:
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._width:
            self.stream.write("\n")
            self.stream.flush()
            self._width = 0


def _upload_rates_path(cache_dir: Path | None) -> Path:
    return (cache_dir if cache_dir is not None else default_render_cache_dir()) / "upload-rates.json"


def _load_upload_rate(panel: str | None, cache_dir: Path | None = None) -> float | None:
    """The steady per-packet upload time remembered for ``panel``, in seconds."""
    if not panel:
        return None
    try:
        rates = json.loads(_upload_rates_path(cache_dir).read_text(encoding="utf-8"))
        rate = float(rates[panel])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rate if rate > 0 else None


def _remember_upload_rate(
    panel: str | None, seconds_per_packet: float | None, cache_dir: Path | None = None
) -> None:
    """Fold a measured steady rate into ``panel``'s remembered one, averaged with the last.

    Averaging keeps one unusually slow or fast upload from swinging the next estimate. It
    only tunes an ETA, so a cache that cannot be read or written is ignored.
    """
    if not panel or not seconds_per_packet or seconds_per_packet <= 0:
        return
    path = _upload_rates_path(cache_dir)
    try:
        rates = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rates, dict):
            rates = {}
    except (OSError, ValueError):
        rates = {}
    previous = rates.get(panel)
    if isinstance(previous, (int, float)) and previous > 0:
        seconds_per_packet = (previous + seconds_per_packet) / 2
    rates[panel] = seconds_per_packet
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rates, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _finish(profile: DeviceProfile, bundle, args: argparse.Namespace) -> None:
    if args.preview:
        save_preview(bundle, args.preview, scale=8)
    if args.bundle_out:
        bundle.save(args.bundle_out)
    execute = _should_execute(args)
    action = "uploading to panel" if execute else "building no-send transfer plan"
    print(f"{action}: {len(bundle.frames)} frame(s)", file=sys.stderr)
    started = time.monotonic()
    cache_dir = getattr(args, "cache_dir", None)
    remembered = _load_upload_rate(profile.device_id, cache_dir)
    try:
        with _UploadProgress(seconds_per_packet=remembered) as progress:
            result = asyncio.run(
                ProtocolRuntime(profile).upload_frame_bundle(
                    bundle,
                    execute=execute,
                    retry_limit=args.retry_limit,
                    timeout_seconds=args.timeout,
                    progress=progress,
                )
            )
    except CodecError as exc:
        # A starter/unprofiled device has no verified codec, so it cannot build a
        # wire plan -- but preview/bundle output above does not need one. Fail
        # softly for preview/dry-run; a real send still errors.
        if execute:
            raise
        print(
            f"note: this profile has no codec that can build a transfer plan "
            f"({exc}). Preview/bundle output was still written. Profile your panel "
            f"with 'coolled inspect' to enable --dry-run plans and sending.",
            file=sys.stderr,
        )
        return
    elapsed = time.monotonic() - started
    if args.verbose:
        print(json.dumps(result, indent=2))
    _print_transfer_summary(result, elapsed_s=elapsed)
    transfer = result.get("transfer", {})
    if not transfer.get("success", False):
        detail = "; ".join(transfer.get("errors", [])) or "device transfer failed"
        raise RuntimeError(detail)
    _remember_upload_rate(profile.device_id, progress.steady_seconds_per_packet, cache_dir)


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

    profile = _load_profile(args)

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
    started = time.monotonic()
    with _UploadProgress(seconds_per_packet=_load_upload_rate(profile.device_id)) as progress:
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
                progress=progress,
            )
        )
    elapsed = time.monotonic() - started
    if args.verbose:
        print(json.dumps(result, indent=2))
    _print_native_text_summary(result, elapsed_s=elapsed)
    if result.get("transfer", {}).get("success"):
        _remember_upload_rate(profile.device_id, progress.steady_seconds_per_packet)


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
    profile = _load_profile(args)
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
    parser.add_argument(
        "--scroll",
        action="store_true",
        help=(
            "Scroll the animation across the panel instead of playing in place: "
            "the sprite (scaled to panel height) enters one edge, exits the other, "
            "then loops, while its own animation keeps playing. Faked host-side, "
            "so it obeys the frame budget (see --scroll-px)."
        ),
    )
    parser.add_argument(
        "--scroll-px",
        type=int,
        default=2,
        metavar="N",
        help=(
            "Pixels moved per frame when --scroll (higher=faster and fewer frames; "
            "one pass costs about (panel_width+sprite_width)/N frames). Default 2."
        ),
    )
    parser.add_argument(
        "--direction",
        choices=["left", "right"],
        default="left",
        help="Scroll direction (only with --scroll; default left).",
    )
    _add_common_send_arguments(parser)
    _add_render_cache_arguments(parser)
    args = parser.parse_args(argv)
    profile = _load_profile(args)
    studio = PixelAnimationStudio(profile.width, profile.height)
    per_frame = max(1, profile.width * profile.height * 3 // 8)
    frame_budget = PIXEL_BYTES_MAX // per_frame
    max_frames = args.max_frames if args.max_frames is not None else frame_budget
    if args.scroll:
        scroll_fps = args.fps if args.fps is not None else 20.0
        bundle = _render_cached(
            args,
            kind="gif-scroll",
            source=args.path,
            parameters={
                "width": profile.width,
                "height": profile.height,
                "pixels_per_frame": args.scroll_px,
                "fps": scroll_fps,
                "direction": args.direction,
                "max_frames": max_frames,
                "background": args.background,
                "dither": args.dither,
                "key_color": args.key_color,
                "key_tolerance": args.key_tolerance,
                "rotation": args.rotate,
                "flip_horizontal": args.flip_horizontal,
                "flip_vertical": args.flip_vertical,
            },
            render=lambda: studio.create_scrolling_gif_bundle(
                args.path,
                pixels_per_frame=args.scroll_px,
                fps=scroll_fps,
                direction=args.direction,
                max_frames=max_frames,
                background=args.background,
                dither=args.dither,
                key_color=args.key_color,
                key_tolerance=args.key_tolerance,
                rotation=args.rotate,
                flip_horizontal=args.flip_horizontal,
                flip_vertical=args.flip_vertical,
            ),
        )
    else:
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
