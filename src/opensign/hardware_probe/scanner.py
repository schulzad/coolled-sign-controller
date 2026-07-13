from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


class BleakUnavailableError(RuntimeError):
    """Raised when the optional runtime cannot import Bleak."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hex_map(mapping: Any) -> dict[str, str]:
    output: dict[str, str] = {}
    if not mapping:
        return output
    for key, value in dict(mapping).items():
        try:
            output[str(key)] = bytes(value).hex()
        except (TypeError, ValueError):
            output[str(key)] = repr(value)
    return output


@dataclass(slots=True)
class AdvertisementRecord:
    device_id: str
    name: str | None
    local_name: str | None
    rssi: int | None
    manufacturer_data: dict[str, str] = field(default_factory=dict)
    service_data: dict[str, str] = field(default_factory=dict)
    service_uuids: list[str] = field(default_factory=list)
    tx_power: int | None = None
    platform_data: list[str] = field(default_factory=list)

    @property
    def effective_name(self) -> str:
        return self.local_name or self.name or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "local_name": self.local_name,
            "rssi": self.rssi,
            "manufacturer_data": dict(self.manufacturer_data),
            "service_data": dict(self.service_data),
            "service_uuids": list(self.service_uuids),
            "tx_power": self.tx_power,
            "platform_data": list(self.platform_data),
        }


@dataclass(slots=True)
class DiscoveredDevice:
    advertisement: AdvertisementRecord
    confidence: float
    protocol_family: str
    evidence: list[str]
    matched_name_filter: str | None = None
    bleak_device: Any = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "advertisement": self.advertisement.to_dict(),
            "classification": {
                "confidence": self.confidence,
                "protocol_family": self.protocol_family,
                "evidence": list(self.evidence),
                "matched_name_filter": self.matched_name_filter,
            },
        }


@dataclass(slots=True)
class ScanResult:
    started_at: str
    completed_at: str
    timeout_seconds: float
    name_filters: list[str]
    include_unknown_devices: bool
    devices: list[DiscoveredDevice]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "2.3",
            "type": "ble_discovery_report",
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "timeout_seconds": self.timeout_seconds,
            "name_filters": list(self.name_filters),
            "include_unknown_devices": self.include_unknown_devices,
            "device_count": len(self.devices),
            "devices": [device.to_dict() for device in self.devices],
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return target

    def find(self, identifier: str) -> DiscoveredDevice | None:
        identifier_lower = identifier.casefold()
        for device in self.devices:
            record = device.advertisement
            candidates = [record.device_id, record.name or "", record.local_name or ""]
            if any(candidate.casefold() == identifier_lower for candidate in candidates if candidate):
                return device
        return None


def classify_advertisement(
    record: AdvertisementRecord,
    name_filters: Iterable[str] = ("CoolLEDX", "CoolLEDM"),
) -> tuple[float, str, list[str], str | None]:
    filters = [item for item in name_filters if item]
    name = record.effective_name
    name_folded = name.casefold()
    confidence = 0.0
    evidence: list[str] = []
    protocol_family = "unknown"
    matched_filter: str | None = None

    for candidate in filters:
        candidate_folded = candidate.casefold()
        if name_folded == candidate_folded:
            confidence = max(confidence, 0.55)
            matched_filter = candidate
            protocol_family = f"{candidate.lower()}_candidate"
            evidence.append(f"advertised_name_exact:{candidate}")
            break
        if candidate_folded and candidate_folded in name_folded:
            confidence = max(confidence, 0.42)
            matched_filter = candidate
            protocol_family = f"{candidate.lower()}_candidate"
            evidence.append(f"advertised_name_contains:{candidate}")

    if record.manufacturer_data:
        confidence += 0.03
        evidence.append("manufacturer_data_present")
    if record.service_data:
        confidence += 0.03
        evidence.append("service_data_present")
    if record.service_uuids:
        confidence += 0.02
        evidence.append("service_uuids_present")

    return min(round(confidence, 3), 0.95), protocol_family, evidence, matched_filter


async def scan_panels(
    *,
    name_filters: Iterable[str] = ("CoolLEDX", "CoolLEDM"),
    timeout_seconds: float = 10.0,
    include_unknown_devices: bool = False,
) -> ScanResult:
    """Scan for BLE advertisements and rank panel candidates without writing to them."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise BleakUnavailableError(
            "Bleak is required for scanning. Install the project with `python -m pip install -e .`."
        ) from exc

    filters = list(name_filters)
    started_at = _now()
    raw = await BleakScanner.discover(timeout=timeout_seconds, return_adv=True)
    completed_at = _now()

    if isinstance(raw, dict):
        pairs = list(raw.values())
    else:  # Compatibility fallback for a scanner backend returning only devices.
        pairs = [(device, None) for device in raw]

    discovered: list[DiscoveredDevice] = []
    for device, advertisement in pairs:
        device_id = str(getattr(device, "address", None) or getattr(device, "name", None) or repr(device))
        name = getattr(device, "name", None)
        local_name = getattr(advertisement, "local_name", None) if advertisement is not None else None
        rssi = getattr(advertisement, "rssi", None) if advertisement is not None else None
        if rssi is None:
            rssi = getattr(device, "rssi", None)
        record = AdvertisementRecord(
            device_id=device_id,
            name=str(name) if name else None,
            local_name=str(local_name) if local_name else None,
            rssi=int(rssi) if isinstance(rssi, int) else None,
            manufacturer_data=_hex_map(
                getattr(advertisement, "manufacturer_data", {}) if advertisement is not None else {}
            ),
            service_data=_hex_map(
                getattr(advertisement, "service_data", {}) if advertisement is not None else {}
            ),
            service_uuids=[
                str(item)
                for item in (
                    getattr(advertisement, "service_uuids", []) if advertisement is not None else []
                )
            ],
            tx_power=(
                int(getattr(advertisement, "tx_power", 0))
                if advertisement is not None and isinstance(getattr(advertisement, "tx_power", None), int)
                else None
            ),
            platform_data=[
                repr(item)
                for item in (
                    getattr(advertisement, "platform_data", ()) if advertisement is not None else ()
                )
            ],
        )
        confidence, family, evidence, matched_filter = classify_advertisement(record, filters)
        if not include_unknown_devices and matched_filter is None:
            continue
        discovered.append(
            DiscoveredDevice(
                advertisement=record,
                confidence=confidence,
                protocol_family=family,
                evidence=evidence,
                matched_name_filter=matched_filter,
                bleak_device=device,
            )
        )

    discovered.sort(
        key=lambda item: (
            item.confidence,
            item.advertisement.rssi if item.advertisement.rssi is not None else -999,
        ),
        reverse=True,
    )
    return ScanResult(
        started_at=started_at,
        completed_at=completed_at,
        timeout_seconds=timeout_seconds,
        name_filters=filters,
        include_unknown_devices=include_unknown_devices,
        devices=discovered,
    )
