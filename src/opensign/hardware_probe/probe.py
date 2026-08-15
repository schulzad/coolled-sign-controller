from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from opensign.contracts import DeviceProfile

from .gatt import find_device, inspect_gatt
from .profile import build_device_profile
from .scanner import ScanResult, scan_panels


class CoolLEDHardwareProbe:
    """Facade matching the CoolLEDHardwareProbe SeedScript module."""

    async def scan(
        self,
        *,
        name_filters: Iterable[str] = ("CoolLEDX", "CoolLEDM"),
        timeout_seconds: float = 10.0,
        include_unknown_devices: bool = False,
    ) -> ScanResult:
        return await scan_panels(
            name_filters=name_filters,
            timeout_seconds=timeout_seconds,
            include_unknown_devices=include_unknown_devices,
        )

    async def inspect(
        self,
        identifier: str,
        *,
        timeout_seconds: float = 15.0,
        include_descriptors: bool = True,
        probe_reads: bool = True,
    ) -> dict:
        device = await find_device(identifier, timeout_seconds=timeout_seconds)
        if device is None:
            raise LookupError(f"BLE device not found: {identifier}")
        return await inspect_gatt(
            device,
            timeout_seconds=timeout_seconds,
            include_descriptors=include_descriptors,
            probe_reads=probe_reads,
        )

    async def scan_and_profile(
        self,
        identifier: str,
        *,
        panel_id: str = "desk-sign",
        width: int = 48,
        height: int = 12,
        timeout_seconds: float = 15.0,
        select_singletons: bool = False,
        profile_path: str | Path | None = None,
    ) -> DeviceProfile:
        scan = await self.scan(
            timeout_seconds=timeout_seconds,
            include_unknown_devices=True,
        )
        discovered = scan.find(identifier)
        device = discovered.bleak_device if discovered is not None else None
        if device is None:
            device = await find_device(identifier, timeout_seconds=timeout_seconds)
        if device is None:
            raise LookupError(f"BLE device not found: {identifier}")
        gatt = await inspect_gatt(device, timeout_seconds=timeout_seconds)
        advertisement = (
            discovered.advertisement
            if discovered is not None
            else {
                "device_id": str(getattr(device, "address", identifier)),
                "name": getattr(device, "name", None),
                "local_name": None,
                "rssi": None,
            }
        )
        profile = build_device_profile(
            advertisement,
            gatt,
            panel_id=panel_id,
            width=width,
            height=height,
            select_singletons=select_singletons,
        )
        if profile_path is not None:
            profile.save(profile_path)
        return profile
