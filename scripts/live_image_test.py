"""Render a static frame and push it to a CoolLEDX sign (image opcode 0x03).

Single connection: render text at the panel geometry, save a scaled preview of
what *should* appear, encode via the coolledx codec, and transfer it.

Usage:
    uv run python scripts/live_image_test.py --profile device_profile.local.json --text HELLO
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import opensign.protocol  # noqa: F401  (registers the coolledx codec)
from opensign.animation.preview import save_preview
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile
from opensign.protocol.codec import select_codec
from opensign.protocol.transport import BleakTransport


async def run(profile_path: str, text: str, fg: str, bg: str, preview: str) -> int:
    profile = DeviceProfile.load(profile_path)
    width, height = profile.dimensions
    studio = PixelAnimationStudio(width, height)
    bundle = studio.create_text_bundle(text, scroll=False, foreground=fg, background=bg)

    preview_path = save_preview(bundle, Path(preview), scale=12, grid=True)
    print(f"Rendered {width}x{height} frame for {text!r}; preview -> {preview_path}", flush=True)

    codec = select_codec(profile, allow_experimental=True)
    encoded = codec.encode_frame_bundle(bundle)
    print(
        f"Encoded image: opcode={encoded.metadata['opcode']:#04x}  "
        f"payload_bytes={encoded.metadata['payload_bytes']}  chunks={len(encoded.packets)}",
        flush=True,
    )

    transport = BleakTransport(profile, timeout_seconds=20.0)
    print(f"Connecting to {profile.device_id} ...", flush=True)
    await transport.connect()
    print("Connected. Transferring frame ...", flush=True)
    try:
        result = await transport.send_packets(encoded.packets, retry_limit=2)
        print(
            f"  ok={result.success}  packets={result.packet_count}  "
            f"ble_chunks={result.to_dict()['chunk_count']}  bytes={result.bytes_sent}",
            flush=True,
        )
        if result.errors:
            print("  errors:", result.errors, flush=True)
        if result.notifications:
            print("  notifications:", [n["hex"] for n in result.notifications], flush=True)
    finally:
        await transport.disconnect()
        print("Disconnected.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Push a static frame to a CoolLEDX sign.")
    parser.add_argument("--profile", default="device_profile.local.json")
    parser.add_argument("--text", default="HELLO")
    parser.add_argument("--fg", default="white")
    parser.add_argument("--bg", default="black")
    parser.add_argument("--preview", default="examples/generated/live-frame.png")
    args = parser.parse_args()
    return asyncio.run(run(args.profile, args.text, args.fg, args.bg, args.preview))


if __name__ == "__main__":
    raise SystemExit(main())
