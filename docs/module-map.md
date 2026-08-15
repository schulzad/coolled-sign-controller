# SMDL-to-Python module map

Maps the design modules in `specs/*.smdl` (SMDL 2.3) to their Python
implementation. `pending` marks a spec directive/function the implementation has
not yet caught up to, or one that collapsed into a different symbol than the spec
sketched — the specs deliberately run a little ahead of the code.

## CoolLEDXDiscovery → `opensign.hardware_probe`

| SMDL component | Python implementation |
|---|---|
| `/scan_panels` | `hardware_probe.scanner.scan_panels` (CLI: `opensign-scan scan`) |
| `/inspect_device` | `hardware_probe.gatt.inspect_gatt` + `hardware_probe.profile.build_device_profile` (CLI: `opensign-scan inspect`) |
| `capture_transient_names` | continuous detection-callback scan in `hardware_probe.scanner.scan_panels` |
| `classify_advertisement` | `hardware_probe.scanner.classify_advertisement` |
| `decode_manufacturer_data` | manufacturer-data decode inside `hardware_probe.profile.build_device_profile` |
| `enumerate_gatt` | `hardware_probe.gatt.inspect_gatt` (+ `find_device`) |
| `build_device_profile` | `hardware_probe.profile.build_device_profile` / `classify_panel` |

## DeviceProfileLedger → `opensign.contracts` (+ `device_profile*.json`, `schema/`)

| SMDL component | Python implementation |
|---|---|
| `/load_profile` | `contracts.DeviceProfile.load` |
| `/promote_claim` | manual profile edit; `hardware_probe.evidence.EvidenceStore` records evidence — a promotion helper is **pending** |
| `/select_codec_gate` | `protocol.codec.select_codec(allow_experimental=…)` |
| `validate_schema` | `contracts.DeviceProfile` construction + `schema/device_profile.schema.json` |
| `enforce_status_gate` | gate inside `protocol.codec.select_codec` |
| `capability_matrix` | `capabilities` block in the profile JSON; derive-from-claim-status is **pending** |
| `derive_display_palette` | collapsed into `animation.render.quantize_to_panel` (fixed 8-colour gamut); explicit `color_mode`→palette derivation is **pending** |
| `resolve_characteristics` | `hardware_probe.profile.build_device_profile` (`--select-singletons`) |

## CoolLEDXProtocol → `opensign.protocol.codecs.coolledx`

| SMDL component | Python implementation |
|---|---|
| `/encode_control` | `CoolLEDXCodec.encode_control` |
| `/encode_frame_bundle` | `CoolLEDXCodec.encode_frame_bundle` |
| `/encode_text_banner` | `CoolLEDXCodec.encode_text_banner` |
| `/transfer` | `protocol.runtime.ProtocolRuntime._deliver` (hand-off to GuardedTransport) |
| `select_codec` | `protocol.codec.select_codec` |
| `build_control_payload` / `escape_stream` / `frame_payload` / `xor_checksum` / `pixel_bitplanes` / `chop_into_chunks` / `preflight_frame_bundle` | internal helpers in `protocol.codecs.coolledx` |

## GuardedTransport → `opensign.protocol.transport` (+ `packet.py`)

| SMDL component | Python implementation |
|---|---|
| `/plan_delivery` | `transport.DryRunTransport.send_packets` |
| `/deliver` | `transport.BleakTransport.send_packets` |
| `choose_chunk_size` | `transport.conservative_chunk_size` / `BleakTransport._chunk_size` |
| `chunk_packets` | `protocol.packet.chunk_packets` (+ `chunk_payload`) |
| `connect_and_subscribe` | `BleakTransport.connect` |
| `await_ack` | `BleakTransport._await_notification` |
| `send_packets` | `transport.{DryRun,Bleak}Transport.send_packets` (per-packet, with NAK re-send + `naks`/`nak_retries` telemetry) |
| `match_ack` | `transport._classify_ack` + codec-supplied `codecs.coolledx.decode_coolledx_ack` (`0x00` success / `0x06` NAK). NAK re-send is wired; the `0x06` path is not yet hardware-exercised |
| `disconnect` | `BleakTransport.disconnect` |

## PixelFramePipeline → `opensign.animation`

| SMDL component | Python implementation |
|---|---|
| `/compile_scene` | `animation.studio.PixelAnimationStudio.create_text_bundle` / `create_image_bundle` |
| `/compile_animation` | `PixelAnimationStudio.create_gif_bundle` (spec name `create_animation_bundle` is **pending**) |
| `/compile_temporal_still` | `PixelAnimationStudio.create_temporal_image_bundle` |
| `render_scene` | `animation.render.render_static_text` / `render_scroll_text` / `render_wide_text` |
| `decode_animated_source` | bounded PIL `ImageSequence` decode inside `create_gif_bundle` |
| `fit_and_orient` | `animation.render.fit_image` + `apply_orientation` |
| `resample_timeline` | `animation.render.normalize_frames` (+ studio timeline handling) |
| `quantize_frame` | `animation.render.quantize_to_panel` |
| `apply_levels` | `animation.render.apply_levels` (+ `compute_auto_levels`) |
| `temporal_dither_still` | `animation.render.temporal_dither_frames` |
| `choose_fused_speed` | collapsed into `PixelAnimationStudio.create_temporal_image_bundle` |
| `build_frame_bundle` | `contracts.FrameBundle.from_images` |
| `compile_diagnostics` | bundle `metadata` from the studio; structured report is partial |

## SignControlService → `opensign.sdk`

| SMDL component | Python implementation |
|---|---|
| `/register_panel` | `sdk.runtime.OpenSignRuntime.register_panel` |
| `/play_text` | `OpenSignRuntime.play_text` |
| `/play_image` | `OpenSignRuntime.play_image` / `play_image_base64` (static, or a `temporal` FRC loop + levels) |
| `/play_animation` | `OpenSignRuntime.play_animation_base64` (decodes + compiles a base64 GIF/APNG, then plays); API route `/animation` |
| `/play_bundle` | `OpenSignRuntime.play_bundle` (API routes `/bundle`, `/scene`) |
| `/set_brightness` | `OpenSignRuntime.set_brightness` |
| `/set_power` | `OpenSignRuntime.set_power` |
| `/status` | `OpenSignRuntime.get_status` |
| `resolve_execute` | execute gate in `OpenSignRuntime` (global `execute` vs per-call override) |
| `store_artifacts` | `OpenSignRuntime._store_artifacts` |
| `record_trace` | `sdk.trace.TraceStore` |
| HTTP endpoints | `sdk.api.create_app` (CLI: `opensign-api`) |
| scheduler / integrations | `sdk.scheduler.InProcessScheduler` / `sdk.integrations.IntegrationRegistry` |
