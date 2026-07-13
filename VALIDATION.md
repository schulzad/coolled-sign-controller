# Validation report

Validation environment: Python 3.13.5 on Linux.

Completed checks:

- `python -m compileall` completed for every package module.
- 24 automated tests passed.
- FastAPI smoke calls returned successful responses for `/status`, `/text`, and `/brightness` in render-only mode.
- Editable installation completed with local build isolation disabled for the offline validation environment.
- A universal Python wheel built successfully.
- Console entry-point help completed for `opensign-scan`, `opensign-preview`, `opensign-send`, and `opensign-api`.
- Generated 48x12 test-pattern, two-frame, and scrolling-text previews and frame-bundle JSON files.
- All checked-in JSON files parsed successfully.

Not validated here:

- BLE discovery against a physical CoolLED sign.
- GATT enumeration on the target sign.
- Any control or frame packet on real hardware.
- Pixel order, native color mode, acknowledgement semantics, throughput, or display-level verification.

Those items require the specific sign and evidence workflow described in `protocol.md`.
