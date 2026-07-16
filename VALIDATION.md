# Validation report

## Software validation (this environment)

Environment: Python 3.12.2 on macOS (Darwin 25.5.0).

- `PYTHONPATH=src python -m pytest` — **64 tests pass** across `tests/` (contracts,
  advertisement classification, rendering, frame-bundle round trips, packet
  framing/chunking, codec encoding, ack decode + NAK re-send, scheduler, and
  render-only orchestration incl. server-side GIF/temporal compile).
- Console entry points expose `--help`: `coolled`, `opensign-scan`,
  `opensign-preview`, `opensign-send`, `opensign-api`.
- Reproducible previews and frame-bundle JSON are checked in under
  `examples/generated/` (both the original 48x12 samples and 64x16 `hello`/`cool`
  bundles).
- All checked-in JSON files parse successfully.

## Hardware validation (reference panel)

Verified against **CoolLEDX, 64x16, 7-colour, firmware 6** (BLE MAC
`ff:00:00:06:6f:82`); evidence is recorded in `device_profile.local.json` and
`protocol.md`.

- Read-only discovery: advertisement + manufacturer-data decode (64x16, 7-colour,
  fw6) and GATT enumeration (single `FFF0` service, one `FFF1` write/notify/read
  characteristic).
- Brightness (`0x08`), static image (`0x03`), and stored animation (`0x04`, pinning
  the 30 KiB / 80-frame buffer) displayed on hardware (2026-07-13).
- Native text scroll (`0x02` wide banner) with mode (`0x06`) and speed (`0x07`,
  higher = faster) verified 2026-07-14.
- Per-chunk ack pacing on `FFF1` (`acks_received=4/4` on a 4-chunk frame).
- Flicker-fusion ceiling observed ~62 Hz (single session, uncalibrated).

## Not yet validated

- The `0x06` checksum-error **NAK re-send** on hardware. The ack-status decoder
  (`0x00`/`0x06`) and per-packet re-send are implemented and unit-tested, but only
  `0x00` (success) acks have been observed on a real panel, so the NAK path is
  unexercised on hardware.
- Power on/off isolation on this panel (mapping is reference-driver-derived,
  `experimental`).
- BLE throughput measurement, API authentication/rate-limiting, and multi-panel
  fan-out.

The hardware items above require the specific sign and the evidence workflow in
`protocol.md`.
