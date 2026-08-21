import argparse
from pathlib import Path

from opensign import cli
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, default_device_profile
from opensign.protocol.codec import CodecError


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


def test_animation_command_keeps_anim_and_gif_aliases() -> None:
    assert cli._DIRECT["animation"] is cli._cmd_animation
    assert cli._DIRECT["anim"] is cli._cmd_animation
    assert cli._DIRECT["gif"] is cli._cmd_animation


def test_load_profile_falls_back_to_starter_when_local_missing(
    tmp_path: Path, monkeypatch
) -> None:
    starter = tmp_path / "device_profile.json"
    DeviceProfile(default_device_profile()).save(starter)
    missing_local = tmp_path / "device_profile.local.json"
    monkeypatch.setattr(cli, "DEFAULT_PROFILE", missing_local)
    monkeypatch.setattr(cli, "STARTER_PROFILE", starter)

    profile = cli._load_profile(argparse.Namespace(profile=missing_local))

    # A fresh clone with no local profile still resolves to the codec-valid 64x16
    # starter instead of crashing on a missing file.
    assert profile.dimensions == (64, 16)


def test_finish_soft_fails_when_codec_cannot_encode(tmp_path: Path, monkeypatch) -> None:
    class NoCodecRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, _bundle, **_options):
            raise CodecError("No verified frame codec is configured for this device profile.")

    monkeypatch.setattr(cli, "ProtocolRuntime", NoCodecRuntime)
    preview = tmp_path / "preview.png"
    args = argparse.Namespace(
        preview=preview,
        bundle_out=None,
        dry_run=False,
        retry_limit=3,
        timeout=15.0,
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    # Preview is written and the codec-less profile fails softly (no exception).
    cli._finish(DeviceProfile.blank(width=8, height=8), bundle, args)

    assert preview.exists()
