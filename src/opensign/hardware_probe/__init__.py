"""Hardware discovery, GATT inspection, and evidence-backed profile generation."""

from .analysis import diff_ble_sessions, rank_chipset_candidates
from .evidence import EvidenceStore
from .probe import CoolLEDHardwareProbe
from .profile import build_device_profile, classify_panel
from .scanner import ScanResult, scan_panels

__all__ = [
    "CoolLEDHardwareProbe",
    "EvidenceStore",
    "ScanResult",
    "build_device_profile",
    "diff_ble_sessions",
    "classify_panel",
    "rank_chipset_candidates",
    "scan_panels",
]
