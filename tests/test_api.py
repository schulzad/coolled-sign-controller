from pathlib import Path

import pytest

from opensign.contracts import DeviceProfile, default_device_profile


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
