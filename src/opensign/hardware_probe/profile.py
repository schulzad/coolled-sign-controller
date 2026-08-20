from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from opensign.contracts import DeviceProfile, default_device_profile, utc_now_iso

from .scanner import AdvertisementRecord


def _properties(characteristic: Mapping[str, Any]) -> set[str]:
    return {str(item) for item in characteristic.get("properties", [])}


def classify_panel(
    advertisement: Mapping[str, Any] | AdvertisementRecord,
    gatt_map: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a confidence-scored classification from advertisement and GATT evidence."""
    gatt_map = gatt_map or {}
    if isinstance(advertisement, AdvertisementRecord):
        data = advertisement.to_dict()
        effective_name = advertisement.effective_name
    else:
        data = dict(advertisement)
        effective_name = str(data.get("local_name") or data.get("name") or "")

    name = effective_name.casefold()
    profile = {
        "device_id": data.get("device_id"),
        "advertised_name": effective_name or None,
        "rssi": data.get("rssi"),
        "protocol_family": "unknown",
        "confidence": 0.0,
        "evidence": [],
        "write_candidates": [],
        "notify_candidates": [],
    }

    if name == "coolledx":
        profile["protocol_family"] = "coolledx_candidate"
        profile["confidence"] += 0.55
        profile["evidence"].append("advertised_name:CoolLEDX")
    elif name == "coolledm":
        profile["protocol_family"] = "coolledm_candidate"
        profile["confidence"] += 0.55
        profile["evidence"].append("advertised_name:CoolLEDM")
    elif "coolled" in name:
        profile["protocol_family"] = "coolled_candidate"
        profile["confidence"] += 0.35
        profile["evidence"].append(f"advertised_name_contains:{effective_name}")

    characteristics = list(gatt_map.get("characteristics", []))
    for characteristic in characteristics:
        properties = _properties(characteristic)
        candidate = {
            "uuid": characteristic.get("uuid"),
            "service_uuid": characteristic.get("service_uuid"),
            "properties": sorted(properties),
        }
        if "write" in properties or "write-without-response" in properties:
            profile["write_candidates"].append(candidate)
        if "notify" in properties or "indicate" in properties:
            profile["notify_candidates"].append(candidate)

    if profile["write_candidates"]:
        profile["confidence"] += 0.12
        profile["evidence"].append("writable_characteristic_present")
    if profile["notify_candidates"]:
        profile["confidence"] += 0.08
        profile["evidence"].append("notifiable_characteristic_present")
    if gatt_map.get("services"):
        profile["confidence"] += 0.04
        profile["evidence"].append("gatt_database_enumerated")

    profile["confidence"] = min(round(float(profile["confidence"]), 3), 0.95)
    return profile


def build_device_profile(
    advertisement: Mapping[str, Any] | AdvertisementRecord,
    gatt_map: Mapping[str, Any] | None = None,
    *,
    panel_id: str = "desk-sign",
    width: int = 64,
    height: int = 16,
    select_singletons: bool = False,
) -> DeviceProfile:
    """Create a conservative profile candidate without inventing protocol behavior."""
    gatt_map = dict(gatt_map or {})
    classification = classify_panel(advertisement, gatt_map)
    data = default_device_profile(panel_id=panel_id, width=width, height=height)
    if isinstance(advertisement, AdvertisementRecord):
        adv = advertisement.to_dict()
    else:
        adv = copy.deepcopy(dict(advertisement))

    data["device_id"] = classification.get("device_id")
    data["advertised_name"] = classification.get("advertised_name")
    data["protocol_family"] = classification.get("protocol_family", "unknown")
    data["confidence"] = classification.get("confidence", 0.0)
    data["advertisement"] = {
        "rssi": adv.get("rssi"),
        "manufacturer_data": copy.deepcopy(adv.get("manufacturer_data", {})),
        "service_data": copy.deepcopy(adv.get("service_data", {})),
        "service_uuids": list(adv.get("service_uuids", [])),
    }
    data["services"] = copy.deepcopy(gatt_map.get("services", []))
    data["characteristics"] = copy.deepcopy(gatt_map.get("characteristics", []))
    data["characteristic_candidates"] = {
        "write": copy.deepcopy(classification["write_candidates"]),
        "notify": copy.deepcopy(classification["notify_candidates"]),
    }
    mtu = gatt_map.get("negotiated", {}).get("mtu")
    if isinstance(mtu, int) and mtu > 0:
        data["connection"]["mtu"] = mtu

    for item in classification["evidence"]:
        data["evidence"].append(
            {
                "type": "discovery",
                "claim": item,
                "status": "observed",
                "source": "opensign-scan",
            }
        )

    if select_singletons:
        write = classification["write_candidates"]
        notify = classification["notify_candidates"]
        if len(write) == 1:
            data["write_characteristic"] = write[0]["uuid"]
            data["evidence"].append(
                {
                    "type": "operator_selection",
                    "claim": f"Selected sole writable characteristic {write[0]['uuid']}",
                    "status": "experimental",
                    "source": "opensign-scan --select-singletons",
                }
            )
        if len(notify) == 1:
            data["notify_characteristic"] = notify[0]["uuid"]
            data["evidence"].append(
                {
                    "type": "operator_selection",
                    "claim": f"Selected sole notify/indicate characteristic {notify[0]['uuid']}",
                    "status": "experimental",
                    "source": "opensign-scan --select-singletons",
                }
            )

    data["timestamps"] = {"created_at": utc_now_iso(), "updated_at": utc_now_iso()}
    return DeviceProfile(data)
