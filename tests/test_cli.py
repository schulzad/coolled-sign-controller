import argparse
from pathlib import Path

from opensign import cli
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile


def test_preview_writes_file_without_hardware_execution(
    tmp_path: Path, monkeypatch
) -> None:
    observed: dict[str, bool] = {}

    class FakeRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, _bundle, *, execute: bool, **_options):
            observed["execute"] = execute
            return {
                "encoded": {"metadata": {"opcode": 3, "frame_count": 1, "payload_bytes": 1}},
                "transfer": {
                    "success": True,
                    "dry_run": not execute,
                    "packet_count": 1,
                    "acks_received": 0,
                    "ack_timeouts": 0,
                    "notifications": [],
                    "errors": [],
                },
            }

    monkeypatch.setattr(cli, "ProtocolRuntime", FakeRuntime)
    preview = tmp_path / "preview.png"
    args = argparse.Namespace(
        preview=preview,
        bundle_out=None,
        dry_run=False,
        retry_limit=3,
        timeout=15.0,
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    cli._finish(DeviceProfile.blank(width=8, height=8), bundle, args)

    assert preview.exists()
    assert observed["execute"] is False


def test_fit_modes_use_standard_names_and_keep_stretch_alias() -> None:
    parser = argparse.ArgumentParser()
    cli._add_fit_argument(parser)

    assert parser.parse_args([]).fit == "contain"
    assert parser.parse_args(["--fit", "cover"]).fit == "cover"
    assert parser.parse_args(["--fit", "fill"]).fit == "stretch"
    assert parser.parse_args(["--fit", "stretch"]).fit == "stretch"
