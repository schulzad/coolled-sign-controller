from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from opensign.contracts import DeviceProfile, FrameBundle

from .runtime import ProtocolRuntime


def _parse_value(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensign-send",
        description="Build a profile-driven transfer plan; physical BLE writes require --execute.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    control = subparsers.add_parser("control", help="Encode a control command.")
    control.add_argument("--profile", type=Path, required=True)
    control.add_argument("--command", required=True)
    control.add_argument("--value")
    control.add_argument("--execute", action="store_true")
    control.add_argument("--retry-limit", type=int, default=3)
    control.add_argument("--timeout", type=float, default=15.0)
    control.add_argument("--output", type=Path)

    bundle = subparsers.add_parser("bundle", help="Encode and transfer a frame bundle.")
    bundle.add_argument("--profile", type=Path, required=True)
    bundle.add_argument("--bundle", type=Path, required=True)
    bundle.add_argument("--execute", action="store_true")
    bundle.add_argument("--retry-limit", type=int, default=3)
    bundle.add_argument("--timeout", type=float, default=15.0)
    bundle.add_argument("--output", type=Path)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    profile = DeviceProfile.load(args.profile)
    runtime = ProtocolRuntime(profile)
    if args.action == "control":
        return await runtime.send_control(
            args.command,
            _parse_value(args.value),
            execute=args.execute,
            retry_limit=args.retry_limit,
            timeout_seconds=args.timeout,
        )
    frame_bundle = FrameBundle.load(args.bundle)
    return await runtime.upload_frame_bundle(
        frame_bundle,
        execute=args.execute,
        retry_limit=args.retry_limit,
        timeout_seconds=args.timeout,
    )


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(_run(args))
        rendered = json.dumps(result, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"opensign-send: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
