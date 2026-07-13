"""Measure the CoolLEDX panel's temporal-dither ceiling (flicker-fusion probe).

Temporal dithering / frame-rate control fakes extra colours by alternating two
native colours fast enough that the eye time-averages them (black<->white => grey,
red<->green => yellow, ...). Whether that works on THIS panel depends entirely on
how fast the firmware actually advances frames -- an unmeasured claim. This script
finds out empirically.

For each colour pair it uploads a 2-frame loop (frame A, frame B) and steps the
per-frame hold time from slow to fast. You watch the sign and note, per pair, the
speed at which it stops flickering and fuses into the target colour (and the speed
below which it just strobes). Report those numbers back and we size the real
spatiotemporal still-quantizer around them.

Requested per-frame hold ``ms`` implies an alternation of ~1000/(2*ms) Hz for a
given pixel; the firmware may clamp very small values, which is part of what we
are measuring (requested vs perceived).

Usage:
    # dry run: print the plan, touch no hardware
    uv run python scripts/flicker_probe.py

    # deploy and sweep on the real sign (BLE writes)
    uv run python scripts/flicker_probe.py --execute
    uv run python scripts/flicker_probe.py --execute --pairs white_black,red_green
    uv run python scripts/flicker_probe.py --execute --dwell 4 --brightness 60
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from PIL import Image

import opensign.protocol  # noqa: F401  (registers the coolledx codec)
from opensign.contracts import DeviceProfile, FrameBundle
from opensign.protocol.codec import select_codec

FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"

# name -> (colour A, colour B, what it should look like once fused)
PAIRS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], str]] = {
    "white_black": ((255, 255, 255), (0, 0, 0), "flat 50% grey"),
    "red_green": ((255, 0, 0), (0, 255, 0), "yellow"),
    "red_black": ((255, 0, 0), (0, 0, 0), "dim/50% red"),
    "blue_cyan": ((0, 0, 255), (0, 255, 255), "blue-cyan blend (low contrast, easiest)"),
}
DEFAULT_SPEEDS = [100, 50, 33, 20, 12, 8, 5, 3, 2, 1]


def _solid(width: int, height: int, colour: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (width, height), colour)


def _checker(width: int, height: int, a: tuple[int, int, int], b: tuple[int, int, int], invert: bool) -> Image.Image:
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            on = ((x + y) % 2 == 0) ^ invert
            px[x, y] = a if on else b
    return img


def _build_bundle(width: int, height: int, frame_a: Image.Image, frame_b: Image.Image, ms: int) -> FrameBundle:
    # coolledx_speed metadata is the authoritative ms/frame the codec honours.
    return FrameBundle.from_images(
        [frame_a, frame_b],
        [ms, ms],
        loop_mode="loop",
        metadata={"coolledx_speed": ms, "pattern": "flicker_probe"},
    )


def _plan(pairs: list[str], speeds: list[int]) -> list[tuple[str, int]]:
    return [(name, ms) for name in pairs for ms in speeds]


def _hz(ms: int) -> float:
    return 1000.0 / (2 * ms)


def _print_header(pairs: list[str], speeds: list[int], width: int, height: int, execute: bool) -> None:
    mode = "EXECUTE (BLE writes)" if execute else "DRY RUN (no hardware)"
    print(f"Flicker probe -- {mode} -- panel {width}x{height}", flush=True)
    print(f"pairs:  {', '.join(pairs)}", flush=True)
    print(f"speeds: {', '.join(f'{ms}ms(~{_hz(ms):.0f}Hz)' for ms in speeds)}", flush=True)
    print("For each pair, note the slowest speed that still looks fully fused (no flicker).", flush=True)
    print("-" * 72, flush=True)


async def _send_bundle(client, notify_event: asyncio.Event, packets: list[bytes], *, response: bool, ack_timeout: float, gap: float) -> None:
    for packet in packets:
        notify_event.clear()
        await client.write_gatt_char(FFF1, packet, response=response)
        try:
            await asyncio.wait_for(notify_event.wait(), timeout=ack_timeout)
        except TimeoutError:
            pass
        await asyncio.sleep(gap)


def _frames_for(pair: str, width: int, height: int) -> tuple[Image.Image, Image.Image]:
    if pair == "checker_wb":
        return (
            _checker(width, height, (255, 255, 255), (0, 0, 0), invert=False),
            _checker(width, height, (255, 255, 255), (0, 0, 0), invert=True),
        )
    colour_a, colour_b, _ = PAIRS[pair]
    return _solid(width, height, colour_a), _solid(width, height, colour_b)


async def main_async(args: argparse.Namespace) -> int:
    profile = DeviceProfile.load(args.profile)
    width, height = profile.dimensions

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    known = set(PAIRS) | {"checker_wb"}
    unknown = [p for p in pairs if p not in known]
    if unknown:
        print(f"Unknown pair(s): {unknown}. Choose from: {sorted(known)}", flush=True)
        return 2
    speeds = [int(s) for s in str(args.speeds).split(",") if s.strip()]

    _print_header(pairs, speeds, width, height, args.execute)

    codec = select_codec(profile, allow_experimental=True)

    if not args.execute:
        for name, ms in _plan(pairs, speeds):
            target = "spatiotemporal 50% grey" if name == "checker_wb" else PAIRS[name][2]
            encoded = codec.encode_frame_bundle(_build_bundle(width, height, *_frames_for(name, width, height), ms))
            print(
                f"  {name:12s} @ {ms:3d}ms (~{_hz(ms):5.0f}Hz)  chunks={len(encoded.packets)}  "
                f"speed={encoded.metadata['animation_speed']}  -> expect {target}",
                flush=True,
            )
        print("-" * 72, flush=True)
        print("Dry run only. Re-run with --execute to sweep on the sign.", flush=True)
        return 0

    from bleak import BleakClient, BleakScanner  # imported lazily so dry runs need no BLE stack

    device_id = profile.device_id
    print(f"Locating {device_id} ...", flush=True)
    device = await BleakScanner.find_device_by_address(device_id, timeout=args.scan_timeout)
    if device is None:
        print("Device not found while scanning.", flush=True)
        return 2

    notify_event = asyncio.Event()

    def on_notify(_sender, _data: bytearray) -> None:
        notify_event.set()

    async with BleakClient(device, timeout=20.0) as client:
        print("Connected.", flush=True)
        await client.start_notify(FFF1, on_notify)

        if args.brightness is not None:
            bpacket = codec.encode_control("brightness", args.brightness).packets[0]
            await client.write_gatt_char(FFF1, bpacket, response=args.response)
            await asyncio.sleep(0.3)
            print(f"Set brightness -> {args.brightness}", flush=True)

        for name, ms in _plan(pairs, speeds):
            target = "spatiotemporal 50% grey" if name == "checker_wb" else PAIRS[name][2]
            bundle = _build_bundle(width, height, *_frames_for(name, width, height), ms)
            packets = list(codec.encode_frame_bundle(bundle).packets)
            print(
                f"\n>> {name} @ {ms}ms/frame (~{_hz(ms):.0f} Hz)  -> should look like: {target}",
                flush=True,
            )
            await _send_bundle(
                client,
                notify_event,
                packets,
                response=args.response,
                ack_timeout=args.ack_timeout,
                gap=args.gap,
            )
            if args.dwell and args.dwell > 0:
                await asyncio.sleep(args.dwell)
            else:
                await asyncio.get_event_loop().run_in_executor(None, input, "   [enter] next, ctrl-c to stop ")

        await asyncio.sleep(0.3)
        await client.stop_notify(FFF1)

    print("\nDone. Report per pair: slowest ms that stayed fused, and the ms where it started to flicker.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CoolLEDX temporal-dither / flicker-fusion probe.")
    parser.add_argument("--profile", type=Path, default=Path("device_profile.local.json"))
    parser.add_argument("--execute", action="store_true", help="Perform physical BLE writes (otherwise dry run).")
    parser.add_argument(
        "--pairs",
        default=",".join(PAIRS),
        help="Comma list from: " + ", ".join(sorted(set(PAIRS) | {'checker_wb'})),
    )
    parser.add_argument("--speeds", default=",".join(str(s) for s in DEFAULT_SPEEDS), help="Comma list of ms/frame.")
    parser.add_argument("--dwell", type=float, default=0.0, help="Seconds to hold each step (0 = wait for Enter).")
    parser.add_argument("--brightness", type=int, default=None, help="Optional 0-100 brightness set first.")
    parser.add_argument("--response", action="store_true", help="Write-with-response instead of write-without-response.")
    parser.add_argument("--ack-timeout", type=float, default=1.5)
    parser.add_argument("--gap", type=float, default=0.12)
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
