# SeedScript-to-Python module map

## CoolLEDHardwareProbe

| SeedScript component | Python implementation |
|---|---|
| `/scan_panels` | `opensign.hardware_probe.scanner.scan_panels` |
| `/inspect_gatt` | `opensign.hardware_probe.gatt.inspect_gatt` |
| `/record_hardware` | `EvidenceStore.record_hardware` and `evidence/hardware/` |
| `/capture_ble_session` | `EvidenceStore.record_capture_provenance`; capture acquisition remains platform-specific |
| `classify_panel` | `opensign.hardware_probe.profile.classify_panel` |
| `diff_ble_sessions` | `hardware_probe.analysis.diff_ble_sessions` for normalized traces |
| `rank_chipset_candidates` | `hardware_probe.analysis.rank_chipset_candidates`; scores only supplied catalogs |
| `PanelDiscoveryFlow` | `CoolLEDHardwareProbe.scan_and_profile` |

## CoolLEDProtocol

| SeedScript component | Python implementation |
|---|---|
| `/load_device_profile` | `DeviceProfile.load` and `CoolLEDProtocol` constructor |
| `/connect_panel` | `BleakTransport.connect` |
| `/send_control` | `ProtocolRuntime.send_control` |
| `/upload_frame_bundle` | `ProtocolRuntime.upload_frame_bundle` |
| `select_codec` | `protocol.codec.select_codec` |
| `build_packet` | Restricted profile templates in `ProfileLiteralCodec` |
| `chunk_payload` | `protocol.packet.chunk_payload` |
| `verify_transfer` | `TransferResult` and notification capture |

## PixelAnimationStudio

| SeedScript component | Python implementation |
|---|---|
| `/create_scene` | `PixelAnimationStudio` dimensions and render helpers |
| `/load_asset` | `render.load_and_fit_image` |
| `/add_effect` | Test, checker, two-frame, and text generators |
| `/compile_timeline` | `PixelAnimationStudio.compile_images` |
| `render_scene` | Functions in `animation.render` |
| `quantize_frame` | `apply_orientation` and RGB frame normalization |
| `encode_animation` | `FrameBundle.from_images` |

## OpenSignSDK

| SeedScript component | Python implementation |
|---|---|
| `/register_panel` | `OpenSignRuntime.register_panel` |
| `/play` | `OpenSignRuntime.play_bundle`, `play_text`, `play_image` |
| `/serve_api` | `sdk.api.create_app` and `opensign-api` |
| `/schedule_scene` | `InProcessScheduler` |
| `/publish_mqtt` | Explicit integration interface; implementation pending |
| `validate_request` | Contract validation and API models |
| `select_playback_plan` | Render-only versus profile codec/transport selection |
| `get_status` | `OpenSignRuntime.get_status` |
| `/track_breadcrumbs` | `TraceStore` |
