import json
from pathlib import Path

from PIL import Image

from opensign.contracts import DeviceProfile, FrameBundle, PlaybackRequest, default_device_profile


def test_default_device_profile_is_conservative() -> None:
    profile = DeviceProfile(default_device_profile())
    assert profile.dimensions == (48, 12)
    assert profile.protocol["codec"] == "capture_required"
    assert profile.write_characteristic is None
    assert profile.notify_characteristic is None


def test_device_profile_save_and_load(tmp_path: Path) -> None:
    profile = DeviceProfile.blank(panel_id="test-panel", width=16, height=8)
    path = profile.save(tmp_path / "profile.json")
    loaded = DeviceProfile.load(path)
    assert loaded.panel_id == "test-panel"
    assert loaded.dimensions == (16, 8)
    assert loaded.to_dict()["timestamps"]["updated_at"] is not None


def test_frame_bundle_round_trip(tmp_path: Path) -> None:
    images = [Image.new("RGB", (4, 2), color) for color in ("red", "blue")]
    bundle = FrameBundle.from_images(
        images,
        [100, 150],
        frames_per_second=8.0,
        metadata={"scene_id": "round-trip"},
    )
    path = bundle.save(tmp_path / "bundle.json")
    loaded = FrameBundle.load(path)
    assert loaded.summary() == bundle.summary()
    assert loaded.frame_hashes == bundle.frame_hashes
    assert loaded.to_images()[1].getpixel((0, 0)) == (0, 0, 255)
    data = json.loads(path.read_text())
    assert data["frame_encoding"] == "base64"


def test_playback_request_contract() -> None:
    request = PlaybackRequest(
        panel_id="desk-sign",
        content={"type": "scene", "value": "system-monitor"},
    )
    assert request.to_dict()["playback_mode"] == "replace"
    assert request.request_id
