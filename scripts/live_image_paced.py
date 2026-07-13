"""Push a static frame to a CoolLEDX sign with per-chunk notification pacing.

This mirrors the reference driver's handshake: subscribe to notifications on
FFF1, send each framed chunk, and wait for the device to acknowledge before
sending the next. Prints every notification so we can learn the ack/handshake
semantics. Uses bleak directly for fine-grained control, but reuses the
coolledx codec for encoding.

Usage:
    uv run python scripts/live_image_paced.py --text HELLO
    uv run python scripts/live_image_paced.py --text HI --mode 7 --response
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from bleak import BleakClient, BleakScanner

import opensign.protocol  # noqa: F401  (registers the coolledx codec)
from opensign.animation.preview import save_preview
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile
from opensign.protocol.codec import select_codec
from opensign.protocol.codecs.coolledx import OPCODE_MODE, frame_payload

FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"


async def main_async(args: argparse.Namespace) -> int:
    profile = DeviceProfile.load(args.profile)
    width, height = profile.dimensions
    studio = PixelAnimationStudio(width, height)
    bundle = studio.create_text_bundle(args.text, scroll=False, foreground=args.fg, background=args.bg)
    preview_path = save_preview(bundle, Path(args.preview), scale=12, grid=True)
    print(f"Rendered {width}x{height} {args.text!r}; preview -> {preview_path}", flush=True)

    codec = select_codec(profile, allow_experimental=True)
    encoded = codec.encode_frame_bundle(bundle)
    packets = list(encoded.packets)
    print(f"opcode={encoded.metadata['opcode']:#04x} payload={encoded.metadata['payload_bytes']}B chunks={len(packets)}", flush=True)

    device_id = profile.device_id
    print(f"Locating {device_id} ...", flush=True)
    device = await BleakScanner.find_device_by_address(device_id, timeout=20.0)
    if device is None:
        print("Device not found while scanning.", flush=True)
        return 2

    notify_event = asyncio.Event()
    notifications: list[str] = []

    def on_notify(_sender, data: bytearray) -> None:
        notifications.append(bytes(data).hex())
        print(f"    <- notify {bytes(data).hex()}", flush=True)
        notify_event.set()

    async with BleakClient(device, timeout=20.0) as client:
        print("Connected.", flush=True)
        await client.start_notify(FFF1, on_notify)

        # Optionally set a display mode first (e.g. 7 = PICTURE, 1 = STATIC).
        if args.mode is not None:
            mode_packet = frame_payload(bytes([OPCODE_MODE, args.mode & 0xFF]))
            print(f"  set mode {args.mode} -> {mode_packet.hex()}", flush=True)
            await client.write_gatt_char(FFF1, mode_packet, response=args.response)
            await asyncio.sleep(0.3)

        for index, packet in enumerate(packets):
            notify_event.clear()
            print(f"  chunk {index+1}/{len(packets)} ({len(packet)}B) -> {packet[:16].hex()}...", flush=True)
            await client.write_gatt_char(FFF1, packet, response=args.response)
            try:
                await asyncio.wait_for(notify_event.wait(), timeout=args.ack_timeout)
            except TimeoutError:
                print("    (no notification within timeout; continuing)", flush=True)
            await asyncio.sleep(args.gap)

        await asyncio.sleep(0.5)
        await client.stop_notify(FFF1)
    print(f"Done. notifications={notifications}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paced CoolLEDX frame push with notify handshake.")
    parser.add_argument("--profile", default="device_profile.local.json")
    parser.add_argument("--text", default="HELLO")
    parser.add_argument("--fg", default="white")
    parser.add_argument("--bg", default="black")
    parser.add_argument("--preview", default="examples/generated/live-frame.png")
    parser.add_argument("--mode", type=int, default=None, help="Optional Mode opcode arg to send first (7=picture,1=static).")
    parser.add_argument("--response", action="store_true", help="Write with response instead of write-without-response.")
    parser.add_argument("--ack-timeout", type=float, default=1.5)
    parser.add_argument("--gap", type=float, default=0.15)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
