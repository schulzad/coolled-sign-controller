import argparse
import io
from pathlib import Path

import pytest
from PIL import Image

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
        verbose=False,
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
        verbose=False,
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    # Preview is written and the codec-less profile fails softly (no exception).
    cli._finish(DeviceProfile.blank(width=8, height=8), bundle, args)

    assert preview.exists()


def test_finish_hands_the_runtime_a_progress_callback(monkeypatch) -> None:
    received: dict[str, object] = {}

    class FakeRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, _bundle, *, progress, **_options):
            received["progress"] = progress
            progress(0, 1)
            progress(1, 1)
            return {"encoded": {}, "transfer": {"success": True, "notifications": [], "errors": []}}

    monkeypatch.setattr(cli, "ProtocolRuntime", FakeRuntime)
    args = argparse.Namespace(
        preview=None, bundle_out=None, dry_run=False, retry_limit=3, timeout=15.0, verbose=False
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    cli._finish(DeviceProfile.blank(width=8, height=8), bundle, args)

    assert callable(received["progress"])


@pytest.mark.parametrize("verbose", [False, True])
def test_finish_prints_the_json_dump_only_with_verbose(monkeypatch, capsys, verbose) -> None:
    class FakeRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, _bundle, **_options):
            return {"encoded": {"packets_hex": ["0100"]}, "transfer": {"success": True}}

    monkeypatch.setattr(cli, "ProtocolRuntime", FakeRuntime)
    args = argparse.Namespace(
        preview=None, bundle_out=None, dry_run=False, retry_limit=3, timeout=15.0, verbose=verbose
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    cli._finish(DeviceProfile.blank(width=8, height=8), bundle, args)

    out = capsys.readouterr()
    assert ('"packets_hex"' in out.out) is verbose
    assert "-- transfer summary --" in out.err


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_upload_progress_redraws_one_line_with_time_left() -> None:
    stream = _Terminal()
    ticks = iter([0.0, 10.0, 12.6, 13.0])

    with cli._UploadProgress(stream, clock=lambda: next(ticks)) as progress:
        progress(0, 4)
        progress(1, 4)
        progress(3, 4)
        progress(4, 4)

    # Time left rounds up (4.2 s reads ~5, never ~0 while work remains), and a
    # shorter redraw is space-padded over the longer line it replaces.
    assert stream.getvalue() == (
        "\ruploading 0/4 (0%), starting"
        "\ruploading 1/4 (25%), ~30 s left"
        "\ruploading 3/4 (75%), ~5 s left "
        "\ruploading 4/4 (100%), done in 13.0 s"
        "\n"
    )


def test_upload_progress_stays_silent_off_a_terminal() -> None:
    stream = io.StringIO()

    with cli._UploadProgress(stream) as progress:
        progress(0, 2)
        progress(2, 2)

    assert stream.getvalue() == ""


def test_transfer_summary_reports_actual_timing(capsys) -> None:
    cli._print_transfer_summary(
        {
            "encoded": {"metadata": {"opcode": 4, "frame_count": 12, "payload_bytes": 4635}},
            "transfer": {
                "success": True,
                "dry_run": False,
                "packet_count": 37,
                "duration_ms": 8600.0,
            },
        },
        elapsed_s=10.94,
    )
    assert "total=10.9s transfer=8.6s per_packet=232ms" in capsys.readouterr().err


def test_transfer_summary_reports_the_still_mode_step(capsys) -> None:
    mode = {"encoded": {"metadata": {"value_encoded": 1}}, "transfer": {"success": True}}
    cli._print_transfer_summary({"encoded": {}, "transfer": {"success": True}, "mode": mode})
    assert "then mode=1 (static) success=True" in capsys.readouterr().err
    cli._print_transfer_summary({"transfer": {}, "mode": {**mode, "transfer": None}})
    assert "then mode=1 (static) not sent" in capsys.readouterr().err


def test_timing_line_skips_dry_runs_and_rates_for_stopped_transfers() -> None:
    assert cli._timing_line({"duration_ms": None}, 0.1) is None
    stopped = {"success": False, "packet_count": 37, "duration_ms": 1200.0}
    assert cli._timing_line(stopped, 3.0) == "total=3.0s transfer=1.2s"


def test_upload_progress_uses_the_remembered_rate_from_the_first_packet() -> None:
    stream = _Terminal()
    ticks = iter([0.0, 2.0, 3.0])

    with cli._UploadProgress(
        stream, clock=lambda: next(ticks), seconds_per_packet=0.25
    ) as progress:
        progress(0, 40)
        progress(4, 40)
        progress(40, 40)

    # The average so far is 0.5 s/packet (it would read ~18 s); the remembered rate wins.
    assert stream.getvalue() == (
        "\ruploading 0/40 (0%), ~10 s left"
        "\ruploading 4/40 (10%), ~9 s left"
        "\ruploading 40/40 (100%), done in 3.0 s"
        "\n"
    )


def test_upload_progress_learns_the_steady_rate_past_the_warm_up() -> None:
    # 30 fast warm-up acks, then a steady 0.2 s, the way the panel behaves.
    times = [0.0]
    for packet in range(100):
        times.append(times[-1] + (0.1 if packet < 30 else 0.2))
    ticks = iter(times)
    progress = cli._UploadProgress(io.StringIO(), clock=lambda: next(ticks))  # not a terminal
    for sent in range(101):
        progress(sent, 100)
    assert progress.steady_seconds_per_packet == pytest.approx(0.2)

    short_ticks = iter([0.0, 1.0, 2.0])
    short = cli._UploadProgress(io.StringIO(), clock=lambda: next(short_ticks))
    for sent in range(3):
        short(sent, 2)
    assert short.steady_seconds_per_packet is None


def test_remembered_upload_rate_blends_runs_and_shrugs_off_a_bad_cache(tmp_path: Path) -> None:
    assert cli._load_upload_rate("panel", tmp_path) is None
    cli._remember_upload_rate("panel", 0.2, tmp_path)
    assert cli._load_upload_rate("panel", tmp_path) == pytest.approx(0.2)
    cli._remember_upload_rate("panel", 0.3, tmp_path)
    assert cli._load_upload_rate("panel", tmp_path) == pytest.approx(0.25)

    (tmp_path / "upload-rates.json").write_text("{not json", encoding="utf-8")
    assert cli._load_upload_rate("panel", tmp_path) is None
    cli._remember_upload_rate("panel", 0.2, tmp_path)
    assert cli._load_upload_rate("panel", tmp_path) == pytest.approx(0.2)


def test_finish_remembers_the_panel_rate_and_reuses_it(tmp_path: Path, monkeypatch) -> None:
    handed: list[float | None] = []

    class FakeRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, _bundle, *, progress, **_options):
            handed.append(progress.seconds_per_packet)
            for sent in range(101):
                progress(sent, 100)
            return {"encoded": {}, "transfer": {"success": True}}

    monkeypatch.setattr(cli, "ProtocolRuntime", FakeRuntime)
    data = default_device_profile(width=8, height=8)
    data["device_id"] = "panel-1"
    args = argparse.Namespace(
        preview=None,
        bundle_out=None,
        dry_run=False,
        retry_limit=3,
        timeout=15.0,
        verbose=False,
        cache_dir=tmp_path,
    )
    bundle = PixelAnimationStudio(8, 8).create_test_pattern_bundle()

    cli._finish(DeviceProfile(data), bundle, args)
    cli._finish(DeviceProfile(data), bundle, args)

    # The first upload has nothing to go on; the second starts from the first's rate.
    assert handed[0] is None
    assert handed[1] is not None and handed[1] > 0


def test_image_warns_when_the_temporal_loop_is_too_slow_but_still_sends(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    sent: list = []

    class FakeRuntime:
        def __init__(self, _profile: DeviceProfile):
            pass

        async def upload_frame_bundle(self, bundle, **_options):
            sent.append(bundle)
            return {"encoded": {}, "transfer": {"success": True, "dry_run": True}}

    monkeypatch.setattr(cli, "ProtocolRuntime", FakeRuntime)
    source = tmp_path / "grey.png"
    Image.new("RGB", (64, 16), (128, 128, 128)).save(source)
    profile = DeviceProfile(default_device_profile()).save(tmp_path / "profile.json")
    base = [str(source), "--profile", str(profile), "--dry-run", "--cache-dir", str(tmp_path)]

    cli._cmd_image([*base, "--temporal", "20"])
    assert len(sent[-1].frames) == 20  # warned, still sent
    assert "warning: 20 temporal subframes at 1 ms each repeat at 50 Hz" in capsys.readouterr().err

    cli._cmd_image([*base, "--temporal", "16"])
    assert "warning:" not in capsys.readouterr().err
