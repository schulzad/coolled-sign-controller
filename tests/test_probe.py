from opensign.hardware_probe.profile import build_device_profile, classify_panel
from opensign.hardware_probe.scanner import AdvertisementRecord, classify_advertisement


def test_classify_known_advertisement() -> None:
    record = AdvertisementRecord(
        device_id="AA:BB",
        name="CoolLEDX",
        local_name="CoolLEDX",
        rssi=-42,
        manufacturer_data={"1": "0102"},
    )
    confidence, family, evidence, matched = classify_advertisement(record)
    assert confidence >= 0.55
    assert family == "coolledx_candidate"
    assert matched == "CoolLEDX"
    assert "advertised_name_exact:CoolLEDX" in evidence


def test_gatt_evidence_adds_candidates_without_auto_selection() -> None:
    advertisement = {
        "device_id": "platform-id",
        "name": "CoolLEDM",
        "local_name": "CoolLEDM",
        "rssi": -55,
        "manufacturer_data": {},
        "service_data": {},
        "service_uuids": [],
    }
    gatt = {
        "services": [{"uuid": "service"}],
        "characteristics": [
            {
                "service_uuid": "service",
                "uuid": "write-char",
                "properties": ["write-without-response"],
            },
            {
                "service_uuid": "service",
                "uuid": "notify-char",
                "properties": ["notify"],
            },
        ],
        "negotiated": {"mtu": 64},
    }
    classified = classify_panel(advertisement, gatt)
    assert classified["confidence"] > 0.55
    profile = build_device_profile(advertisement, gatt)
    assert profile.write_characteristic is None
    assert profile.notify_characteristic is None
    assert profile.connection["mtu"] == 64
    assert profile.to_dict()["characteristic_candidates"]["write"][0]["uuid"] == "write-char"


def test_explicit_singleton_selection_is_recorded() -> None:
    advertisement = {
        "device_id": "platform-id",
        "name": "CoolLEDX",
        "local_name": "CoolLEDX",
        "rssi": -50,
    }
    gatt = {
        "characteristics": [
            {"service_uuid": "s", "uuid": "w", "properties": ["write"]},
            {"service_uuid": "s", "uuid": "n", "properties": ["notify"]},
        ]
    }
    profile = build_device_profile(advertisement, gatt, select_singletons=True)
    assert profile.write_characteristic == "w"
    assert profile.notify_characteristic == "n"
    claims = [item["claim"] for item in profile.to_dict()["evidence"]]
    assert any("Selected sole writable" in claim for claim in claims)
