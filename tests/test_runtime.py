import asyncio
from pathlib import Path

from opensign.contracts import DeviceProfile, default_device_profile
from opensign.sdk.runtime import OpenSignRuntime


def test_render_only_runtime_preserves_unknown_protocol_boundary(tmp_path: Path) -> None:
    runtime = OpenSignRuntime(execute=False, artifact_dir=tmp_path)
    runtime.register_panel(DeviceProfile(default_device_profile()))

    result = asyncio.run(runtime.play_text("desk-sign", "HELLO", frames_per_second=12))
    assert result["delivery_status"] == "rendered_only"
    assert Path(result["artifacts"]["frame_bundle"]).exists()
    assert Path(result["artifacts"]["preview"]).exists()

    status = runtime.get_status("desk-sign", include_diagnostics=True)
    assert status["panels"][0]["active_playback"]["bundle"]["frames"] > 1
    assert status["recent_trace_events"]


def test_brightness_is_simulated_when_command_is_unknown() -> None:
    runtime = OpenSignRuntime(execute=False)
    runtime.register_panel(DeviceProfile(default_device_profile()))
    result = asyncio.run(runtime.set_brightness("desk-sign", 75))
    assert result["delivery_status"] == "simulated"
    assert runtime.get_status("desk-sign")["panels"][0]["brightness_percent"] == 75


def test_play_native_text_is_render_only_and_saves_banner(tmp_path: Path) -> None:
    runtime = OpenSignRuntime(execute=False, artifact_dir=tmp_path)
    runtime.register_panel(DeviceProfile(default_device_profile()))

    result = asyncio.run(runtime.play_native_text("desk-sign", "HELLO", speed=8))

    # The starter profile has no verified codec, so native scroll degrades to a
    # rendered-only result rather than raising, and there is no FrameBundle.
    assert result["delivery_status"] == "rendered_only"
    assert result["native_text"]["banner_width"] > 0
    assert "bundle" not in result
    assert Path(result["artifacts"]["banner"]).exists()
