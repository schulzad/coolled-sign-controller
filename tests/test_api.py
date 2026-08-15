import base64
import io
from pathlib import Path

import pytest

from opensign.contracts import DeviceProfile, FrameBundle, default_device_profile


def _tiny_gif_base64() -> str:
    from PIL import Image

    frames = [Image.new("RGB", (8, 8), (255, 0, 0)), Image.new("RGB", (8, 8), (0, 0, 255))]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return base64.b64encode(buffer.getvalue()).decode()


def _tiny_png_base64() -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_api_app_exposes_and_serves_initial_routes(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from opensign.sdk.api import create_app

    profile_path = DeviceProfile(default_device_profile()).save(tmp_path / "profile.json")
    app = create_app(profile_path=profile_path, artifact_dir=None)
    paths = {route.path for route in app.routes}
    assert {"/text", "/image", "/animation", "/brightness", "/status"}.issubset(paths)
    assert app.state.runtime.execute is False

    client = TestClient(app)
    status = client.get("/status")
    assert status.status_code == 200
    assert status.json()["execute_enabled"] is False

    text = client.post(
        "/text",
        json={"panel_id": "desk-sign", "text": "HELLO", "scroll": False, "fps": 12},
    )
    assert text.status_code == 200
    assert text.json()["delivery_status"] == "rendered_only"

    brightness = client.post(
        "/brightness",
        json={"panel_id": "desk-sign", "percent": 50},
    )
    assert brightness.status_code == 200
    assert brightness.json()["delivery_status"] == "simulated"


def test_api_animation_image_temporal_and_bundle(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from opensign.sdk.api import create_app

    profile = DeviceProfile(default_device_profile())
    profile_path = profile.save(tmp_path / "profile.json")
    app = create_app(profile_path=profile_path, artifact_dir=None)
    paths = {route.path for route in app.routes}
    assert {"/animation", "/bundle", "/scene"}.issubset(paths)

    client = TestClient(app)

    # /animation compiles a base64 GIF server-side into a multi-frame bundle.
    animation = client.post(
        "/animation",
        json={"panel_id": "desk-sign", "source_base64": _tiny_gif_base64()},
    )
    assert animation.status_code == 200
    assert animation.json()["bundle"]["frames"] >= 2

    # /image with temporal >= 2 expands a still into an N-subframe FRC loop.
    image = client.post(
        "/image",
        json={"panel_id": "desk-sign", "image_base64": _tiny_png_base64(), "temporal": 4},
    )
    assert image.status_code == 200
    assert image.json()["bundle"]["frames"] == 4

    # /bundle plays a pre-rendered frame bundle at the panel geometry.
    from PIL import Image

    frame_bundle = FrameBundle.from_images(
        [Image.new("RGB", (profile.width, profile.height), "white")],
        [200],
    )
    bundle = client.post(
        "/bundle",
        json={"panel_id": "desk-sign", "frame_bundle": frame_bundle.to_json_dict()},
    )
    assert bundle.status_code == 200
    assert bundle.json()["delivery_status"] == "rendered_only"

    # An invalid base64 animation source is a client error, not a crash.
    bad = client.post("/animation", json={"panel_id": "desk-sign", "source_base64": "not@@base64"})
    assert bad.status_code == 400
