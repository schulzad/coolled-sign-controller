from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensign-api",
        description="Run the localhost OpenSign API. BLE writes require --execute.",
    )
    parser.add_argument("--profile", type=Path, default=Path("device_profile.json"))
    parser.add_argument("--panel-id")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/api"))
    parser.add_argument("--no-artifacts", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        import uvicorn

        from .api import create_app

        app = create_app(
            profile_path=args.profile,
            panel_id=args.panel_id,
            execute=args.execute,
            artifact_dir=None if args.no_artifacts else args.artifact_dir,
        )
        uvicorn.run(app, host=args.host, port=args.port)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except ImportError as exc:
        print(
            "opensign-api requires the API extra: python -m pip install -e '.[api]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"opensign-api: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
