# CoolLED protocol research ledger

## Scope

This document records what is observed, inferred, tested, and verified for a specific physical sign. It is not a generic statement about every device advertised as `CoolLEDX`, `CoolLEDM`, or used by a similarly named application.

The repository starts with all device-specific protocol fields unknown. UUIDs, command identifiers, checksums, transforms, encryption, pixel order, color encoding, and controller identity remain profile-driven until evidence supports them.

## Evidence states

| State | Meaning | Allowed runtime behavior |
|---|---|---|
| `unverified` | A user assertion or plausible hypothesis with no repeatable device test. | Documentation only. |
| `experimental` | Supported by one or more captures but not isolated or repeated sufficiently. | Dry-run and explicitly opted-in research code only. |
| `verified` | Repeated, controlled experiments reproduce the result on the profiled device. | May be used by guarded runtime paths. |
| `rejected` | Contradicted by later evidence. | Preserved in history, never selected. |

A “verified” command should identify the physical panel, application version, capture source, test variables, packet direction, characteristic, result, and repeat count.

## Device identity

| Field | Current value | State | Evidence |
|---|---|---|---|
| Panel ID | `desk-sign` | local label | User-provided scaffold name |
| Physical dimensions | 48x12 | unverified | SeedScript acceptance target |
| Advertised name | unknown | unverified | Scan required |
| BLE identifier | unknown | unverified | Scan required |
| PCB revision | unknown | unverified | Board photographs required |
| MCU / BLE radio | unknown | unverified | Direct marking or strong hardware evidence required |

## GATT map

Populate this table from `opensign-scan inspect` output. Do not infer purpose from UUID shape alone.

| Service UUID | Characteristic UUID | Properties | Observed traffic | Hypothesized role | State |
|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | write channel | unverified |
| TBD | TBD | TBD | TBD | notify/ack channel | unverified |

## Controlled capture matrix

Capture each scenario at least twice. Change one variable at a time.

| Scenario | Controlled variables | Repeats | Capture IDs | Result |
|---|---|---:|---|---|
| Connect only | Same phone, panel, distance | 2+ | TBD | Establish session noise baseline |
| Clear screen | No other setting changes | 2+ | TBD | Isolate clear command |
| Brightness low/high | Only brightness changes | 2+ each | TBD | Locate value and transform fields |
| Static solid colors | Black, red, green, blue, white | 2+ each | TBD | Infer channel order and frame payload |
| Single lit pixel | Coordinate moved systematically | 2+ each | TBD | Infer orientation and pixel order |
| Two-frame asset | Frame timing only | 2+ | TBD | Infer animation metadata and storage |
| Repeat same asset | Identical bytes, new session | 2+ | TBD | Detect hashes, cache IDs, or nonces |

## Capture provenance record

Store a sidecar JSON file next to each capture:

```json
{
  "capture_id": "2026-07-13-clear-01",
  "panel_id": "desk-sign",
  "scenario": "clear_screen",
  "capture_source": "android_hci",
  "application": {
    "package": null,
    "version": null
  },
  "test_variables": {},
  "started_at": null,
  "ended_at": null,
  "sha256": null,
  "notes": []
}
```

## Packet hypothesis table

| Capture group | Direction | Characteristic | Constant regions | Variable regions | Candidate interpretation | State |
|---|---|---|---|---|---|---|
| TBD | write | TBD | TBD | TBD | command / length / payload / checksum | unverified |
| TBD | notify | TBD | TBD | TBD | acknowledgement / status | unverified |

## Profile-driven codec contract

The built-in `profile_literal` codec exists to encode evidence already confirmed elsewhere. It does not discover protocol semantics.

A fixed command may be represented as:

```json
{
  "protocol": {
    "codec": "profile_literal",
    "status": "verified",
    "encryption": {"mode": "none"},
    "commands": {
      "clear": {
        "status": "verified",
        "replay_safe": true,
        "payload_hex": "",
        "evidence": ["capture-id-goes-here"]
      }
    }
  }
}
```

A value-bearing command may use a restricted template after its field location and scale are verified:

```json
{
  "status": "verified",
  "replay_safe": true,
  "template_hex": "AA {value_u8} 55",
  "value_scale": {
    "input_min": 0,
    "input_max": 100,
    "output_min": 0,
    "output_max": 255
  },
  "checksum": {"algorithm": "none"},
  "evidence": ["capture-id-goes-here"]
}
```

The byte values above are illustrative placeholders, not CoolLED protocol claims. Do not mark such an entry verified until the real bytes are supported by repeated evidence.

Supported template placeholders include integer encodings such as `{value_u8}`, `{value_u16le}`, frame fields such as `{frame_index_u8}`, `{frame_length_u16le}`, and byte fields such as `{frame_hex}`. Unsupported transforms must be implemented as an explicit codec plugin rather than hidden in constants.

## Frame-transfer promotion checklist

Before changing `protocol.frame_transfer.status` to `verified`:

1. Confirm the write characteristic and write mode.
2. Establish the input frame color mode.
3. Establish orientation and pixel order using single-pixel tests.
4. Isolate frame index, frame count, payload length, and timing fields.
5. Determine whether whole-frame packets are chunked only by BLE or by an additional device protocol.
6. Determine whether checksums, hashes, cache identifiers, nonces, or session transforms are present.
7. Repeat the same frame in new sessions and after power cycling.
8. Verify successful display behavior at least three times.
9. Record failure behavior for malformed length, omitted chunks, and slower pacing.
10. Preserve the captures and the exact profile revision used for each test.

## Transfer verification

A successful `write_gatt_char` call proves only that the host stack accepted a write request. Stronger verification may include:

- A matching notification or indication.
- A stable acknowledgement sequence.
- A read-back state where supported.
- Repeatable visible display behavior documented by an operator or camera.
- A frame hash or cache response linked to the transmitted asset.

The runtime records host-level success separately from display-level confidence.

## Known unknowns

- Whether the panel requires pairing, bonding, a session key, or application-level encryption.
- Whether an upload is streamed directly, stored as an asset, or cached by hash.
- Whether frame timing is encoded per frame, globally, or controlled by a separate speed command.
- Whether brightness and power settings are volatile or persistent.
- Whether multiple hardware revisions share the same advertised name.
- Whether the controller uses row-major, column-major, serpentine, tiled, or transformed pixel order.

## Change discipline

Every profile edit that introduces device-specific bytes should include:

- Evidence references.
- Confidence/state.
- Device and application versions.
- A reproducible test command.
- Expected notification or display result.
- A rollback note if the hypothesis fails.
