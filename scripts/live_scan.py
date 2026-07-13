"""Continuous BLE scanner that captures transient advertisement names.

Unlike a one-shot discover(), this keeps a detection callback running and
records the *best* (most informative) name ever seen for each device, so a
name that only appears briefly at power-on (e.g. "CoolLEDX-DF7D") is not lost
when the device later re-advertises without it.

Usage:
    uv run python scripts/live_scan.py --seconds 30 --match coolled df7d
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime

from bleak import BleakScanner


def _now() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


async def run(seconds: float, matches: list[str]) -> None:
    seen: dict[str, dict] = {}
    match_lower = [m.lower() for m in matches]

    def callback(device, adv) -> None:
        addr = device.address
        name = adv.local_name or (device.name if device.name else None)
        entry = seen.get(addr)
        if entry is None:
            entry = {
                "address": addr,
                "name": name,
                "rssi": adv.rssi,
                "svc": list(adv.service_uuids or []),
                "mfg": list((adv.manufacturer_data or {}).keys()),
                "first_seen": _now(),
                "hits": 0,
            }
            seen[addr] = entry
        entry["hits"] += 1
        entry["rssi"] = adv.rssi
        # Keep the most informative name we ever observe for this device.
        if name and not entry.get("name"):
            entry["name"] = name
        if name and any(m in name.lower() for m in match_lower):
            print(f"[{_now()}] MATCH  {addr}  name={name!r}  rssi={adv.rssi}  "
                  f"svc={list(adv.service_uuids or [])}  mfg={list((adv.manufacturer_data or {}).keys())}",
                  flush=True)
        elif name and entry["hits"] == 1:
            print(f"[{_now()}] named  {addr}  name={name!r}  rssi={adv.rssi}", flush=True)

    print(f"[{_now()}] scanning for {seconds:.0f}s  (matching: {matches}) -- power-cycle the sign NOW", flush=True)
    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await scanner.stop()

    print(f"\n[{_now()}] === summary (sorted by rssi) ===", flush=True)
    for entry in sorted(seen.values(), key=lambda e: e["rssi"] or -999, reverse=True):
        name = entry.get("name")
        flag = "  <-- MATCH" if name and any(m in name.lower() for m in match_lower) else ""
        print(f"  rssi={entry['rssi']:>4}  name={name!r}  hits={entry['hits']}  "
              f"first={entry['first_seen']}  addr={entry['address']}  "
              f"svc={entry['svc']}  mfg={entry['mfg']}{flag}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuous BLE scanner capturing transient names.")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--match", nargs="+", default=["coolled", "df7d"])
    args = parser.parse_args()
    asyncio.run(run(args.seconds, args.match))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
