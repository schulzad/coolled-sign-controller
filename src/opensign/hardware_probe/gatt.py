from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .scanner import BleakUnavailableError


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_description(value: Any) -> str | None:
    description = getattr(value, "description", None)
    return str(description) if description else None


def _truncate_hex(value: bytes, limit: int = 128) -> tuple[str, bool]:
    truncated = len(value) > limit
    return value[:limit].hex(), truncated


async def find_device(identifier: str, timeout_seconds: float = 10.0) -> Any:
    """Resolve a platform BLE identifier or exact advertised name to a BLEDevice."""
    try:
        from bleak import BleakScanner
    except ImportError as exc:  # pragma: no cover
        raise BleakUnavailableError("Bleak is required for GATT inspection") from exc

    finder = getattr(BleakScanner, "find_device_by_address", None)
    if finder is not None:
        try:
            device = await finder(identifier, timeout=timeout_seconds)
            if device is not None:
                return device
        except Exception:
            # Some platforms use UUID-like identifiers or reject address lookup. Fall back to a scan.
            pass

    devices = await BleakScanner.discover(timeout=timeout_seconds)
    folded = identifier.casefold()
    for device in devices:
        candidates = [
            str(getattr(device, "address", "")),
            str(getattr(device, "name", "")),
        ]
        if any(candidate.casefold() == folded for candidate in candidates if candidate):
            return device
    return None


async def inspect_gatt(
    device: Any,
    *,
    timeout_seconds: float = 15.0,
    include_descriptors: bool = True,
    probe_reads: bool = True,
    read_limit_bytes: int = 128,
) -> dict[str, Any]:
    """Enumerate GATT state and perform only property-advertised reads."""
    try:
        from bleak import BleakClient
    except ImportError as exc:  # pragma: no cover
        raise BleakUnavailableError("Bleak is required for GATT inspection") from exc

    started_at = _now()
    report: dict[str, Any] = {
        "schema_version": "2.3",
        "type": "gatt_inspection_report",
        "started_at": started_at,
        "completed_at": None,
        "device_id": str(getattr(device, "address", device)),
        "device_name": getattr(device, "name", None),
        "connected": False,
        "negotiated": {},
        "services": [],
        "characteristics": [],
        "write_candidates": [],
        "notify_candidates": [],
        "errors": [],
    }

    async with BleakClient(device, timeout=timeout_seconds) as client:
        report["connected"] = bool(client.is_connected)
        try:
            report["negotiated"]["mtu"] = int(client.mtu_size)
        except Exception as exc:
            report["negotiated"]["mtu"] = None
            report["errors"].append(f"mtu_unavailable:{type(exc).__name__}:{exc}")

        services = client.services
        for service in services:
            service_item = {
                "uuid": str(service.uuid),
                "handle": getattr(service, "handle", None),
                "description": _safe_description(service),
                "characteristics": [],
            }
            for characteristic in service.characteristics:
                properties = [str(item) for item in characteristic.properties]
                char_item: dict[str, Any] = {
                    "service_uuid": str(service.uuid),
                    "uuid": str(characteristic.uuid),
                    "handle": getattr(characteristic, "handle", None),
                    "description": _safe_description(characteristic),
                    "properties": properties,
                    "max_write_without_response_size": None,
                    "read": None,
                    "descriptors": [],
                }
                try:
                    char_item["max_write_without_response_size"] = int(
                        characteristic.max_write_without_response_size
                    )
                except Exception:
                    pass

                if probe_reads and "read" in properties:
                    try:
                        raw = bytes(await client.read_gatt_char(characteristic))
                        hex_value, truncated = _truncate_hex(raw, read_limit_bytes)
                        char_item["read"] = {
                            "ok": True,
                            "hex": hex_value,
                            "length": len(raw),
                            "truncated": truncated,
                        }
                    except Exception as exc:
                        char_item["read"] = {
                            "ok": False,
                            "error": f"{type(exc).__name__}:{exc}",
                        }

                if include_descriptors:
                    for descriptor in characteristic.descriptors:
                        descriptor_item: dict[str, Any] = {
                            "uuid": str(descriptor.uuid),
                            "handle": getattr(descriptor, "handle", None),
                            "description": _safe_description(descriptor),
                            "read": None,
                        }
                        try:
                            raw = bytes(await client.read_gatt_descriptor(descriptor.handle))
                            hex_value, truncated = _truncate_hex(raw, read_limit_bytes)
                            descriptor_item["read"] = {
                                "ok": True,
                                "hex": hex_value,
                                "length": len(raw),
                                "truncated": truncated,
                            }
                        except Exception as exc:
                            descriptor_item["read"] = {
                                "ok": False,
                                "error": f"{type(exc).__name__}:{exc}",
                            }
                        char_item["descriptors"].append(descriptor_item)

                if "write" in properties or "write-without-response" in properties:
                    report["write_candidates"].append(
                        {
                            "uuid": str(characteristic.uuid),
                            "service_uuid": str(service.uuid),
                            "properties": properties,
                            "max_write_without_response_size": char_item[
                                "max_write_without_response_size"
                            ],
                        }
                    )
                if "notify" in properties or "indicate" in properties:
                    report["notify_candidates"].append(
                        {
                            "uuid": str(characteristic.uuid),
                            "service_uuid": str(service.uuid),
                            "properties": properties,
                        }
                    )

                service_item["characteristics"].append(char_item)
                report["characteristics"].append(char_item)
            report["services"].append(service_item)

    report["completed_at"] = _now()
    return report
