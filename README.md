# OpenSign / CoolLED 2.3 scaffold

A Python repository scaffold for the four modules in the **OpenSign / CoolLED SeedScript Module Pack 2.3**:

1. `CoolLEDHardwareProbe` → `opensign.hardware_probe`
2. `CoolLEDProtocol` → `opensign.protocol`
3. `PixelAnimationStudio` → `opensign.animation`
4. `OpenSignSDK` → `opensign.sdk`

The implementation keeps the intended boundary intact:

```text
Hardware evidence -> Device profile
Scene description -> Rendered frames
Device profile + frames -> BLE delivery
API/scheduler -> Orchestration
```

## Current status

This is an executable research scaffold, not a claim that the CoolLED protocol is known. It deliberately contains **no guessed UUIDs, command bytes, encryption keys, or chipset identity**.

Working now:

- BLE advertisement scanning and candidate ranking.
- GATT service, characteristic, descriptor, and safe-read inspection.
- Evidence-backed `device_profile.json` generation.
- 48x12 test-pattern, two-frame, checker, image, and scrolling-text rendering.
- Enlarged PNG/GIF previews and transport-neutral frame-bundle JSON.
- Profile-driven packet templates, chunking, dry-run transfer plans, and guarded BLE writes.
- Local FastAPI endpoints for `/text`, `/image`, `/brightness`, `/power`, and `/status`.
- In-memory scheduling primitives and cross-module trace records.

Blocked by device evidence:

- A confirmed control command.
- A confirmed static-frame or animation packet schema.
- Verified pixel order, color mode, cache behavior, pacing, and acknowledgement semantics.

## Install

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[api,dev]'
```

The project targets Python 3.11 or newer. Core dependencies are Bleak and Pillow. FastAPI and Uvicorn are optional API dependencies.

## 1. Scan for panels

```bash
opensign-scan scan \
  --names CoolLEDX CoolLEDM \
  --timeout 10 \
  --output evidence/advertisements/scan.json
```

Include every nearby device when the advertised name is unknown:

```bash
opensign-scan scan --include-unknown --output evidence/advertisements/all.json
```

Inspect a selected platform identifier and create a profile candidate:

```bash
opensign-scan inspect '<device-address-or-platform-id>' \
  --output evidence/gatt/panel.json \
  --profile-out device_profile.local.json
```

No characteristic is promoted from “candidate” to active automatically. Use `--select-singletons` only after reviewing the GATT evidence; the selection is recorded as an operator decision, not protocol proof.

## 2. Preview a 48x12 animation

```bash
opensign-preview \
  --pattern two-frame \
  --width 48 \
  --height 12 \
  --scale 16 \
  --grid \
  --output examples/generated/two-frame.gif \
  --bundle-out examples/generated/two-frame.bundle.json
```

Other patterns:

```bash
opensign-preview --pattern test --output examples/generated/test-pattern.png
opensign-preview --pattern checker --frames 8 --output examples/generated/checker.gif
opensign-preview --pattern text --text 'OPEN SIGN' --output examples/generated/text.gif
```

The bundle remains transport-neutral. Raw frame bytes are RGB888 and base64-encoded in JSON unless a later profile-specific compiler is added.

## 3. Dry-run a protocol command

The default profile uses the `capture_required` codec, so a command intentionally fails until verified evidence is added. Once a command is represented by a verified `profile_literal` entry, inspect its exact packet plan without touching Bluetooth:

```bash
opensign-send control \
  --profile device_profile.local.json \
  --command brightness \
  --value 50
```

Real writes require both a verified profile and an explicit flag:

```bash
opensign-send control \
  --profile device_profile.local.json \
  --command brightness \
  --value 50 \
  --execute
```

## 4. Run the local API

The API defaults to render-only mode and binds to localhost:

```bash
opensign-api --profile device_profile.json
```

Example request:

```bash
curl -X POST http://127.0.0.1:8124/text \
  -H 'content-type: application/json' \
  -d '{"panel_id":"desk-sign","text":"HELLO","scroll":true,"fps":12}'
```

Enable physical BLE delivery only after the profile is verified:

```bash
opensign-api --profile device_profile.local.json --execute
```

## Repository map

```text
src/opensign/
  contracts.py                Shared device/profile/playback contracts
  hardware_probe/             Discovery, GATT inspection, profile generation
  protocol/                   Codec registry, packet templates, chunking, BLE transport
  animation/                  Rendering, frame bundles, previews
  sdk/                        Registry, API, scheduler, orchestration, trace state
schema/                       JSON Schemas for stable contracts
protocol.md                   Evidence ledger and promotion process
evidence/                     Captures and provenance directories
examples/generated/           Reproducible preview outputs
```

See `docs/module-map.md` for a direct mapping from SeedScript directives and functions to Python modules.

## Safety and evidence rules

- The API listens on `127.0.0.1` unless explicitly changed.
- BLE writes require `--execute`; dry-run is the default.
- A command or frame schema must be marked `verified` before the built-in codec will use it.
- Session-dependent transforms are rejected unless a codec plugin implements them.
- Never commit private keys, pairing data, device-owner identifiers, or captures containing unrelated personal traffic.
- Keep the renderer independent from Bleak and packet framing.

## Tests

```bash
make test
```

The tests cover contracts, classification, rendering, frame-bundle round trips, packet templates, chunking, scheduler behavior, and render-only SDK orchestration. Hardware tests are intentionally separate because they require a physical panel and reviewed evidence.
