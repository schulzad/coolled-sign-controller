# Roadmap against the initial acceptance criteria

Reference panel: CoolLEDX, 64x16, 7-colour, firmware 6 (`ff:00:00:06:6f:82`).

| Criterion | Status |
|---|---|
| Discover sign and save advertisement/GATT profile | Implemented; verified on the reference panel |
| Connect without mobile application | Verified on hardware (guarded BLE transport) |
| Send one confirmed control command | Brightness (`0x08`) verified on hardware |
| Render an oriented test pattern | Implemented (default geometry now 64x16) |
| Send one static frame repeatably | Static image (`0x03`) verified on hardware |
| Compile and play a simple animation | Stored animation (`0x04`) verified on hardware (30 KiB / 80-frame buffer) |
| Play at measured BLE throughput | Ack-paced delivery verified; throughput profiling pending |
| Expose `/text`, `/image`, `/brightness`, `/status` | Implemented; API render-only until `--execute`. `/text` (native scroll or flipbook), `/image` (+temporal), and `/animation` (+side-scroll) all compile server-side |
| Preserve evidence for unverified conclusions | Implemented (evidence ledger + provenance format) |
| Keep renderer independent from Bleak/framing | Enforced by package boundaries and tests |

## Still open

- Exercise the `0x06` checksum-error NAK re-send on real hardware (decoded and wired; only `0x00` acks seen so far).
- Power on/off isolation, BLE throughput measurement, API auth/rate-limiting, and multi-panel fan-out.
