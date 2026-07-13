"""Single-connection live control test for a CoolLEDX sign.

Connects once via the project's BleakTransport, then sends a short, fully
reversible sequence of control commands (a brightness sweep, optionally a
power toggle) so the effect is visible on the panel. Captures any notification
bytes the sign returns on the FFF1 channel.

Usage:
    uv run python scripts/live_control_test.py --profile device_profile.local.json
    uv run python scripts/live_control_test.py --profile device_profile.local.json --power-toggle
"""

from __future__ import annotations

import argparse
import asyncio

import opensign.protocol  # noqa: F401  (registers the coolledx codec)
from opensign.contracts import DeviceProfile
from opensign.protocol.codec import select_codec
from opensign.protocol.transport import BleakTransport


async def run(profile_path: str, *, power_toggle: bool) -> int:
    profile = DeviceProfile.load(profile_path)
    codec = select_codec(profile, allow_experimental=True)
    transport = BleakTransport(profile, timeout_seconds=20.0)

    steps: list[tuple[str, str, object]] = [
        ("brightness", "brightness", 100),
        ("brightness", "brightness", 5),
        ("brightness", "brightness", 100),
    ]
    if power_toggle:
        steps += [("power", "power", False), ("power", "power", True)]

    print(f"Connecting to {profile.device_id} ...", flush=True)
    await transport.connect()
    print("Connected. write char:", profile.write_characteristic, flush=True)
    try:
        for label, command, value in steps:
            encoded = codec.encode_control(command, value)
            packet_hex = encoded.packets[0].hex()
            result = await transport.send_packets(encoded.packets, retry_limit=2)
            acks = result.notifications
            print(
                f"  {label}={value!r:>5}  sent {packet_hex}  "
                f"ok={result.success}  bytes={result.bytes_sent}  "
                f"notifications={[n['hex'] for n in acks]}",
                flush=True,
            )
            await asyncio.sleep(1.5)
    finally:
        await transport.disconnect()
        print("Disconnected.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live CoolLEDX control test (single connection).")
    parser.add_argument("--profile", default="device_profile.local.json")
    parser.add_argument("--power-toggle", action="store_true", help="Also toggle power off/on at the end.")
    args = parser.parse_args()
    return asyncio.run(run(args.profile, power_toggle=args.power_toggle))


if __name__ == "__main__":
    raise SystemExit(main())
