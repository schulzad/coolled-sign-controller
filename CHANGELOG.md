# Changelog

## Unreleased

- Added **side-scrolling animations**: a GIF/WebP/APNG can travel across the panel as a sprite (scaled to panel height, transparency preserved, own animation still playing) instead of playing in place. New `render_scroll_animation` + `alpha_key` in `animation.render`, `PixelAnimationStudio.create_scrolling_gif_bundle`, and `coolled animation --scroll [--scroll-px N] [--direction left|right]`. The scroll is faked host-side because native firmware scroll (opcode 0x02) can only march a single static bitmap; a full pass is thinned to the frame budget, so it obeys the ~79-frame / 30 KiB limit.
- Brought the HTTP API to **parity with the CLI**: `/animation` gains `scroll`/`scroll_px`/`direction` (side-scroll) plus `key_color`/`key_tolerance`, and `/text` now uses the device-native firmware scroll by default (`native=true`, with `speed`/`mode`), falling back to the host flipbook with `native=false`. Added `OpenSignRuntime.play_native_text`, extended `play_animation_base64`, capped the `/text` flipbook to the frame budget, and made the animation route tolerate a `data:` URI prefix.
- Made the toolkit usable **off a fresh clone**: the checked-in starter `device_profile.json` and the probe/profile defaults are now the codec-valid **64x16** (a multiple-of-8 height the bitplane codec accepts; corrects the stale 48x12 scaffold). The direct CLIs fall back to the starter when `device_profile.local.json` is absent, and `--preview`/`--dry-run` degrade gracefully (with a note) when a profile has no codec that can build a transfer plan, so a preview always renders.
- Wired per-chunk **ack decoding + NAK re-send** into `GuardedTransport`: the CoolLEDX codec now supplies an ack decoder (`decode_coolledx_ack`; status `0x00` success / `0x06` checksum error), `send_packets` is per-packet and re-sends a NAKed packet up to `nak_retry_limit`, and `TransferResult` gains `naks` / `nak_retries`. Backward compatible: with no decoder any notification still counts as an ack. The `0x06` path is not yet exercised on hardware.
- Brought the HTTP API up to the SignControlService spec: `/animation` now compiles a bounded base64 GIF/APNG server-side (subsampled to the device frame buffer), `/image` accepts `temporal` (FRC loop) plus `dither`/levels, and a dedicated `/bundle` route (with `/scene` alias) plays a pre-rendered frame bundle. Added `OpenSignRuntime.play_animation_base64` and extended `play_image_base64`.
- Refreshed the docs (`README`, `protocol.md`, `docs/module-map.md`, `VALIDATION.md`, `ROADMAP.md`) to match the implemented behaviour and the verified reference panel (64x16).
- Flipped the send activation trigger: the `coolled` and `opensign-send` CLIs and `scripts/flicker_probe.py` now write to the panel by default and take `--dry-run` to build a plan without BLE writes (replaces the old opt-in `--execute`). The `opensign-api` server is unchanged and stays render-only until started with `--execute`.
- Transmitting via `ProtocolRuntime` no longer requires a `verified` profile; `experimental` profiles may be written live (a controlled live test is how evidence is promoted), matching the `live_*` scripts.
- Added `scripts/native_scroll_experiment.py` to test the device's native text scroll (wide bitmap under the TEXT opcode + MODE/SPEED) instead of a rasterized flipbook.
- Extended `native_scroll_experiment.py` with `--speed-sweep` / `--speeds` / `--reassert-mode` to hunt 0x07 scroll-rate semantics by eye.
- Verified native-scroll SPEED (`0x07`): higher byte = faster; 255 is fast but readable (2026-07-14 speed sweep). Promoted `protocol.commands.speed` and `mode` to verified in the local profile. Opposite polarity from animation `coolledx_speed` (ms/frame).
- `coolled text` now uses native firmware scroll by default with `--speed 0..10` (maps to device byte 0..255). Added codec `encode_text_banner`, `ProtocolRuntime.play_native_text`, and `--flipbook` / `--no-scroll` escape hatches.

## 0.1.0 - scaffold

- Added four-package architecture matching SeedScript Module Pack 2.3.
- Added BLE scanner, GATT inspector, and device-profile builder.
- Added 48x12 renderer, GIF/PNG previewer, and frame-bundle compiler.
- Added profile-driven literal codec, guarded BLE transport, and dry-run CLI.
- Added local API, scheduler primitives, trace state, schemas, tests, and evidence ledger.
