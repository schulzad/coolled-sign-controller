from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .gatt import find_device, inspect_gatt
from .profile import build_device_profile
from .scanner import scan_panels


def _common_scan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--names",
        nargs="+",
        default=["CoolLEDX", "CoolLEDM"],
        help="Advertised-name candidates.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Scan or connection timeout in seconds.")
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Include devices that do not match the name filters.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensign-scan",
        description="Discover and inspect CoolLED-compatible BLE panel candidates without writing to them.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan advertisements and rank candidates.")
    _common_scan_arguments(scan_parser)
    scan_parser.add_argument("--output", type=Path, help="Write the discovery report to JSON.")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one device's GATT database.")
    inspect_parser.add_argument("identifier", help="BLE address, platform UUID, or exact advertised name.")
    _common_scan_arguments(inspect_parser)
    inspect_parser.add_argument("--output", type=Path, help="Write the combined inspection report to JSON.")
    inspect_parser.add_argument("--profile-out", type=Path, help="Write a device-profile candidate.")
    inspect_parser.add_argument("--panel-id", default="desk-sign")
    inspect_parser.add_argument("--width", type=int, default=48)
    inspect_parser.add_argument("--height", type=int, default=12)
    inspect_parser.add_argument(
        "--no-descriptors",
        action="store_true",
        help="Skip descriptor enumeration and reads.",
    )
    inspect_parser.add_argument(
        "--no-probe-reads",
        action="store_true",
        help="Do not read characteristics that advertise the read property.",
    )
    inspect_parser.add_argument(
        "--select-singletons",
        action="store_true",
        help="Select a sole write/notify candidate as an explicit experimental operator decision.",
    )
    return parser


async def _run_scan(args: argparse.Namespace) -> int:
    result = await scan_panels(
        name_filters=args.names,
        timeout_seconds=args.timeout,
        include_unknown_devices=args.include_unknown,
    )
    data = result.to_dict()
    if args.output:
        result.save(args.output)
    print(json.dumps(data, indent=2))
    return 0


async def _run_inspect(args: argparse.Namespace) -> int:
    scan = await scan_panels(
        name_filters=args.names,
        timeout_seconds=args.timeout,
        include_unknown_devices=True,
    )
    discovered = scan.find(args.identifier)
    device = discovered.bleak_device if discovered is not None else None
    if device is None:
        device = await find_device(args.identifier, timeout_seconds=args.timeout)
    if device is None:
        print(f"Device not found: {args.identifier}", file=sys.stderr)
        return 2

    gatt = await inspect_gatt(
        device,
        timeout_seconds=args.timeout,
        include_descriptors=not args.no_descriptors,
        probe_reads=not args.no_probe_reads,
    )
    advertisement = (
        discovered.advertisement
        if discovered is not None
        else {
            "device_id": str(getattr(device, "address", args.identifier)),
            "name": getattr(device, "name", None),
            "local_name": None,
            "rssi": None,
            "manufacturer_data": {},
            "service_data": {},
            "service_uuids": [],
        }
    )
    profile = build_device_profile(
        advertisement,
        gatt,
        panel_id=args.panel_id,
        width=args.width,
        height=args.height,
        select_singletons=args.select_singletons,
    )
    combined = {
        "schema_version": "2.3",
        "type": "combined_panel_inspection",
        "scan": scan.to_dict(),
        "gatt": gatt,
        "profile_candidate": profile.to_dict(),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    if args.profile_out:
        profile.save(args.profile_out)
    print(json.dumps(combined, indent=2))
    return 0


async def _async_main(args: argparse.Namespace) -> int:
    if args.action == "scan":
        return await _run_scan(args)
    return await _run_inspect(args)


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_async_main(args)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"opensign-scan: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
