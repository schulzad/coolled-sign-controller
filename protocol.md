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

The checked-in starter (`device_profile.json`) begins with everything unverified.
The values below are for the characterized reference panel (recorded in
`device_profile.local.json`).

| Field | Current value | State | Evidence |
|---|---|---|---|
| Panel ID | `desk-sign` | local label | User-provided scaffold name |
| Physical dimensions | 64x16 | verified | Advertisement manufacturer data (2026-07-13); corrects the earlier 48x12 target |
| Colour mode | 7-colour (mode 1) | verified | Manufacturer-data colour byte |
| Advertised name | `CoolLEDX` (suffix DF7D) | verified | Scan after power-cycle (name broadcast only briefly at power-on) |
| BLE identifier | MAC `ff:00:00:06:6f:82` (platform id `2810750F-…` on macOS) | verified | Scan + manufacturer data |
| Firmware | 6 | verified | Manufacturer-data firmware byte |
| PCB revision | unknown | unverified | Board photographs required |
| MCU / BLE radio | unknown | unverified | Direct marking or strong hardware evidence required |

## GATT map

Populated from `opensign-scan inspect`. The panel exposes a single vendor service
(`FFF0`) with one characteristic (`FFF1`) used for **both** writes and
notifications; do not infer purpose from UUID shape alone.

| Service UUID | Characteristic UUID | Properties | Observed traffic | Hypothesized role | State |
|---|---|---|---|---|---|
| `0000fff0-…` | `0000fff1-…` | write-without-response, notify, read (max WWR 244; CCCD `0x2902`) | framed control + frame-transfer writes | write channel | verified |
| `0000fff0-…` | `0000fff1-…` | notify | per-chunk ack notifications | notify/ack channel | verified (arrival + `0x00` ack decoded); `0x06` NAK path not yet hardware-exercised |

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
| brightness / image / animation | write | `FFF1` | `0x01` start, `0x03` end, `0x02` escape | length, opcode, payload | `0x01 \|\| escape(len_be16 \|\| opcode \|\| args) \|\| 0x03`; frame-transfer chunks add an XOR checksum | verified |
| per-chunk ack | notify | `FFF1` | leading opcode + `0x00` | chunk index, status byte | ack status `0x00` = success, `0x06` = checksum error | decoded in software (`decode_coolledx_ack`); `0x06` NAK re-send not yet hardware-exercised |

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

## Resolved on the reference panel

- No pairing, bonding, or session key is required for the observed commands; framing
  uses `0x02` byte-stuffing with no application-level encryption (`encryption.mode = none`).
- Uploads are store-and-loop, not streamed; there is no real-time frame-streaming
  mechanism (`frame_streaming` is rejected). Hash/asset caching is not implemented.
- Animation timing is a single global speed (per-frame hold time in ms, smaller =
  faster); native text-scroll rate is a separate `SPEED` command (`0x07`, higher =
  faster — opposite polarity).
- Pixel order is column-major, 1 bit per R/G/B plane, MSB = top pixel.

## Still unknown

- Whether brightness and power settings are volatile or persistent.
- Whether multiple hardware revisions share the same advertised name.
- Whether the `0x06` checksum-error NAK actually fires on this panel. The decoder
  (`decode_coolledx_ack`) and per-packet re-send are wired into the transport, but
  only `0x00` (success) acks have been seen so far, so the NAK/re-send path is
  unexercised on hardware.

## Change discipline

Every profile edit that introduces device-specific bytes should include:

- Evidence references.
- Confidence/state.
- Device and application versions.
- A reproducible test command.
- Expected notification or display result.
- A rollback note if the hypothesis fails.
