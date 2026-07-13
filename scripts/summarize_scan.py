"""Pretty-print an opensign-scan discovery report, flagging CoolLED candidates.

Usage:
    uv run python scripts/summarize_scan.py evidence/advertisements/scan2.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "evidence/advertisements/scan.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    devices = data.get("devices", [])
    print(f"file: {path}")
    print(f"device_count: {data.get('device_count', len(devices))}\n")

    for dev in devices:
        adv = dev["advertisement"]
        cls = dev["classification"]
        name = adv.get("name")
        local = adv.get("local_name")
        haystack = f"{name or ''} {local or ''}".lower()
        flagged = "coolled" in haystack or "df7d" in haystack
        tag = "  <-- CoolLED" if flagged else ""
        print(
            f"{cls['confidence']:>5}  rssi={adv.get('rssi')}  "
            f"name={name!r}  local={local!r}  fam={cls['protocol_family']}{tag}"
        )
        print(
            f"        id={adv.get('device_id')}  "
            f"svc_uuids={adv.get('service_uuids')}  "
            f"mfg={list(adv.get('manufacturer_data', {}).keys())}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
