"""Native text-scroll experiment for a CoolLEDX sign.

Hypothesis (yours): when something selects ``text`` we should use the device's
*native* scroll -- a single wide bitmap the firmware marches across the panel --
not a rasterized flipbook of panel-width frames (which is what blows past the
~30 KiB frame buffer).

What the reference driver (UpDryTwist/coolledx-driver) actually does, confirmed
by reading its ``render.py`` / ``commands.py`` / ``hardware.py``:

  * Text is rendered to ONE wide bitmap (natural width, panel height) and sent
    under the TEXT opcode 0x02. Image uses opcode 0x03.
  * The TEXT and IMAGE payloads are byte-for-byte identical EXCEPT the text
    payload inserts an 81-byte header right after the 24 reserved bytes:
        1-byte text length  ||  80-byte buffer (0x30 for each of the first N chars)
    (for text > 255 chars it is a 2-byte length + 79-byte buffer -- still 81 B).
  * Width is *implicit*: nothing in the header stores it; the device derives it
    from the pixel-byte count. So a wider-than-panel banner is simply "more
    pixel bytes" -- our existing image encoder already produces the correct
    bytes; the only reason it refuses is the ``width == panel`` guard.
  * Motion is a SEPARATE command: MODE opcode 0x06 with an arg from the Mode
    enum (STATIC=1, LEFT=2, RIGHT=3, UP=4, DOWN=5, ...), and SPEED opcode 0x07
    with a 0..255 byte. ``SetText`` never sets a mode itself.

So this script sends, over one connection, a guided sequence you can watch:

    1. brightness up            (make sure the panel is lit)
    2. upload a WIDE banner      (default: TEXT opcode 0x02)
    3. SPEED + MODE              (default: MODE.LEFT=2 -> scroll right-to-left)

then holds so you can observe. Nothing is written to flash; every step is
reversible and every byte + notification is printed.

Encoding reuses the project's *verified* primitives (``_pixel_bitplanes``,
``_chop_into_chunks``, framing, and ``encode_control`` for MODE/SPEED/brightness).
The only experimental variables are (a) banner width > panel and (b) the TEXT
opcode + 81-byte header -- both taken verbatim from the reference. That keeps
what you observe attributable to those two things and nothing else.

Usage:
    # render + print the exact bytes, no BLE (works with no device present):
    uv run python scripts/native_scroll_experiment.py --text "Heads down tails up" --dry-run

    # live: native text scroll to the left
    uv run python scripts/native_scroll_experiment.py --text "Heads down tails up"

    # live: send the SAME wide bitmap as an IMAGE (0x03) instead, to see whether
    # the firmware scrolls an image too or only a text object
    uv run python scripts/native_scroll_experiment.py --text "Heads down tails up" --send-as image

    # scroll the other way / change speed
    uv run python scripts/native_scroll_experiment.py --text HELLO --mode 3 --speed 16

    # live: hold each SPEED byte long enough to compare by eye
    # (verified 2026-07-14: higher = faster; 255 fast but readable)
    uv run python scripts/native_scroll_experiment.py --text "Heads down tails up" --speed-sweep

    # custom sweep + re-send MODE after each SPEED (in case the firmware latches)
    uv run python scripts/native_scroll_experiment.py --speed-sweep --speeds 0,1,32,128,255 --hold 8 --reassert-mode
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import opensign.protocol  # noqa: F401  (registers the coolledx codec)
from opensign.animation.render import parse_color
from opensign.contracts import DeviceProfile
from opensign.protocol.codec import select_codec
from opensign.protocol.codecs.coolledx import (
    OPCODE_IMAGE,
    OPCODE_TEXT,
    _chop_into_chunks,
    _pixel_bitplanes,
)

# Mode opcode (0x06) arguments, from the reference Mode enum.
MODE_NAMES = {1: "STATIC", 2: "LEFT", 3: "RIGHT", 4: "UP", 5: "DOWN", 6: "SNOWFLAKE", 7: "PICTURE", 8: "LASER"}

# Extremes + spaced mids. Hardware 2026-07-14: higher SPEED byte = faster scroll.
DEFAULT_SPEED_SWEEP = (0, 1, 8, 32, 64, 128, 200, 255)


def parse_speeds(raw: str | None) -> list[int]:
    """Parse a comma list of SPEED bytes (0..255), or fall back to the default sweep."""
    if not raw or not raw.strip():
        return list(DEFAULT_SPEED_SWEEP)
    speeds: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part, 0)  # allow 0xFF as well as 255
        if not 0 <= value <= 255:
            raise argparse.ArgumentTypeError(f"speed {value} out of range 0..255")
        speeds.append(value)
    if not speeds:
        raise argparse.ArgumentTypeError("need at least one speed value")
    return speeds


def render_wide_text(text: str, height: int, *, fg: str, bg: str, font_size: int) -> Image.Image:
    """Render ``text`` to a single wide RGB bitmap of the panel height.

    Natural width (however wide the glyphs need), vertically centred. This is
    the whole banner -- the firmware, not us, is responsible for marching it
    across the panel -- so unlike a scroll flipbook the cost is one image no
    matter how long the phrase.
    """
    try:
        font: ImageFont.ImageFont = ImageFont.load_default(size=font_size)  # Pillow >= 10
    except TypeError:  # pragma: no cover - older Pillow
        font = ImageFont.load_default()

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    text_width = max(1, right - left)

    image = Image.new("RGB", (text_width, height), parse_color(bg))
    draw = ImageDraw.Draw(image)
    y = (height - (bottom - top)) // 2 - top
    draw.text((-left, y), text, font=font, fill=parse_color(fg))
    return image


def build_banner_payload(frame_rgb: bytes, width: int, height: int, *, as_text: bool, text: str) -> bytearray:
    """Build the un-chunked payload for a wide banner.

    Mirrors the reference ``create_image_output``: 24 reserved bytes, then (text
    only) the 81-byte text header, then a 2-byte pixel length and the R||G||B
    column-major planes produced by our verified ``_pixel_bitplanes``.
    """
    plane_r, plane_g, plane_b = _pixel_bitplanes(frame_rgb, width, height)
    pixel_bits = bytes(plane_r + plane_g + plane_b)

    raw = bytearray(24)  # reserved header (purpose unconfirmed; zero-filled like the reference)
    if as_text:
        count = len(text)
        if count <= 0xFF:
            raw += count.to_bytes(1, "big")
            buffer = bytearray(80)
        else:
            raw += count.to_bytes(2, "big")
            buffer = bytearray(79)
        for i in range(min(count, len(buffer))):
            buffer[i] = 0x30  # reference fills the char buffer with '0'; the bitmap is what renders
        raw += buffer
    raw += len(pixel_bits).to_bytes(2, "big")
    raw += pixel_bits
    return raw


def describe_plan(
    args: argparse.Namespace,
    banner: Image.Image,
    raw: bytearray,
    packets: list[bytes],
    panel_w: int,
    panel_h: int,
    speeds: list[int],
) -> None:
    opcode = OPCODE_TEXT if args.send_as == "text" else OPCODE_IMAGE
    per_frame = max(1, panel_w * panel_h * 3 // 8)
    flip_frames = banner.width + panel_w  # off-right -> off-left, 1 px/frame
    flip_bytes = flip_frames * per_frame
    print("Plan")
    print(f"  text            : {args.text!r}")
    print(f"  panel           : {panel_w}x{panel_h}")
    print(f"  banner bitmap   : {banner.width}x{banner.height} ({'wider than panel' if banner.width > panel_w else 'NOT wider than panel -- nothing to scroll'})")
    print(f"  send as         : {args.send_as} (opcode {opcode:#04x})")
    print(f"  payload         : 24 reserved + {'81 text-header + ' if args.send_as == 'text' else ''}2 len + {len(raw) - (24 + (81 if args.send_as == 'text' else 0) + 2)} pixel = {len(raw)} B in {len(packets)} framed chunk(s)")
    if args.speed_sweep:
        total = args.hold * len(speeds)
        print(f"  motion          : MODE {args.mode} ({MODE_NAMES.get(args.mode, '?')}), SPEED SWEEP {speeds}")
        print(f"  sweep hold      : {args.hold:.0f}s each ({total:.0f}s total); reassert_mode={args.reassert_mode}")
        print("  watch for       : faster / slower / same vs previous step (higher 0x07 = faster)")
    else:
        print(f"  motion          : MODE {args.mode} ({MODE_NAMES.get(args.mode, '?')}), SPEED {args.speed}")
    print(f"  native vs flip  : one {len(raw)} B banner  vs  ~{flip_frames} flipbook frames ({flip_bytes} B, {'OVER' if flip_bytes > 30 * 1024 else 'under'} the 30 KiB buffer)")


async def run(args: argparse.Namespace) -> int:
    profile = DeviceProfile.load(args.profile)
    panel_w, panel_h = profile.dimensions
    banner = render_wide_text(args.text, panel_h, fg=args.fg, bg=args.bg, font_size=args.font_size or panel_h)
    speeds = parse_speeds(args.speeds) if args.speed_sweep else [args.speed]

    raw = build_banner_payload(banner.tobytes(), banner.width, panel_h, as_text=(args.send_as == "text"), text=args.text)
    packets = _chop_into_chunks(bytes(raw), OPCODE_TEXT if args.send_as == "text" else OPCODE_IMAGE)

    if args.preview:
        preview_path = Path(args.preview)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        banner.save(preview_path)
        print(f"Banner preview saved -> {preview_path}")

    describe_plan(args, banner, raw, packets, panel_w, panel_h, speeds)

    if banner.width <= panel_w:
        print("\nNote: the banner is not wider than the panel, so even a correct native scroll")
        print("      has nothing to move. Use a longer --text to actually see scrolling.")

    if args.dry_run:
        print("\n--dry-run: not connecting. First framed chunk:")
        print(f"  {packets[0].hex()}")
        if args.speed_sweep:
            print("Speed sweep packets (opcode 0x07):")
            for speed in speeds:
                print(f"  speed={speed:<3}  would send control SPEED byte {speed:#04x}")
        return 0

    from opensign.protocol.transport import BleakTransport

    codec = select_codec(profile, allow_experimental=True)
    transport = BleakTransport(profile, timeout_seconds=args.timeout)

    async def send_control(command: str, value: object) -> None:
        encoded = codec.encode_control(command, value)
        result = await transport.send_packets(encoded.packets, retry_limit=2)
        notes = [n["hex"] for n in result.notifications]
        print(f"  {command}={value!r}  {encoded.packets[0].hex()}  ok={result.success}  notify={notes}", flush=True)

    print(f"\nConnecting to {profile.device_id} ...", flush=True)
    await transport.connect()
    print(f"Connected. write char: {profile.write_characteristic}", flush=True)
    try:
        print("\n[1] brightness", flush=True)
        await send_control("brightness", args.brightness)

        if args.mode_first and not args.speed_sweep:
            print("\n[mode-first] SPEED then MODE before upload", flush=True)
            await send_control("speed", args.speed)
            await send_control("mode", args.mode)

        print(f"\n[2] upload wide banner as {args.send_as} ({len(packets)} chunk(s), await ack)", flush=True)
        result = await transport.send_packets(packets, retry_limit=2, await_ack=True, ack_timeout=args.ack_timeout)
        print(
            f"  ok={result.success} bytes={result.bytes_sent} acks={result.acks_received} "
            f"timeouts={result.ack_timeouts} notify={[n['hex'] for n in result.notifications]}",
            flush=True,
        )

        if args.speed_sweep:
            print(
                f"\n[3] SPEED sweep ({len(speeds)} steps x {args.hold:.0f}s) — note faster/slower/same each step",
                flush=True,
            )
            # Start motion once with the first speed, then only change SPEED unless asked to reassert MODE.
            await send_control("speed", speeds[0])
            await send_control("mode", args.mode)
            print(f"\n--- SPEED {speeds[0]} (0x{speeds[0]:02x}) — watch {args.hold:.0f}s ---", flush=True)
            await asyncio.sleep(args.hold)
            for i, speed in enumerate(speeds[1:], start=2):
                print(f"\n--- SPEED {speed} (0x{speed:02x})  step {i}/{len(speeds)} — watch {args.hold:.0f}s ---", flush=True)
                await send_control("speed", speed)
                if args.reassert_mode:
                    await send_control("mode", args.mode)
                await asyncio.sleep(args.hold)
            print("\nSweep done. Expected: higher SPEED byte = faster scroll (verified 2026-07-14).", flush=True)
        else:
            if not args.mode_first:
                print("\n[3] SPEED then MODE (start the scroll)", flush=True)
                await send_control("speed", args.speed)
                await send_control("mode", args.mode)

            print(f"\nHolding {args.hold:.0f}s -- watch the panel. Ctrl-C to stop early.", flush=True)
            await asyncio.sleep(args.hold)
    finally:
        await transport.disconnect()
        print("Disconnected.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Native CoolLEDX text-scroll experiment.")
    parser.add_argument("--profile", default="device_profile.local.json")
    parser.add_argument("--text", default="Heads down tails up")
    parser.add_argument("--send-as", choices=("text", "image"), default="text", help="Opcode: text=0x02 (native), image=0x03.")
    parser.add_argument("--mode", type=int, default=2, help="MODE arg: 1=static,2=left,3=right,4=up,5=down,7=picture.")
    parser.add_argument("--speed", type=int, default=32, help="SPEED byte 0..255 for a single-shot run (higher=faster; ignored by --speed-sweep).")
    parser.add_argument(
        "--speed-sweep",
        action="store_true",
        help="After upload, walk a list of SPEED bytes and hold each so you can compare scroll rate by eye (higher=faster).",
    )
    parser.add_argument(
        "--speeds",
        default=None,
        help=f"Comma list of SPEED bytes for --speed-sweep (default: {','.join(map(str, DEFAULT_SPEED_SWEEP))}). Accepts 0xFF.",
    )
    parser.add_argument(
        "--reassert-mode",
        action="store_true",
        help="With --speed-sweep, re-send MODE after every SPEED (tests whether the firmware latches speed only on mode start).",
    )
    parser.add_argument("--brightness", type=int, default=100)
    parser.add_argument("--fg", default="white")
    parser.add_argument("--bg", default="black")
    parser.add_argument("--font-size", type=int, default=0, help="0 = panel height.")
    parser.add_argument(
        "--hold",
        type=float,
        default=8.0,
        help="Seconds to watch (per SPEED step when sweeping; whole run otherwise). Default 8.",
    )
    parser.add_argument("--mode-first", action="store_true", help="Set MODE/SPEED before the upload instead of after (single-shot only).")
    parser.add_argument("--ack-timeout", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--preview", default="examples/generated/native-scroll-banner.png")
    parser.add_argument("--dry-run", action="store_true", help="Render + print bytes only; do not connect.")
    args = parser.parse_args()
    if args.speeds is not None and not args.speed_sweep:
        parser.error("--speeds requires --speed-sweep")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
