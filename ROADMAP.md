# Roadmap against the initial acceptance criteria

| Criterion | Scaffold status |
|---|---|
| Discover sign and save advertisement/GATT profile | Implemented; hardware validation pending |
| Connect without mobile application | Transport implemented; device profile pending |
| Send one confirmed control command | Codec path implemented; confirmed bytes pending |
| Render oriented 48x12 test pattern | Implemented |
| Send one static frame repeatably | Transport path implemented; frame protocol pending |
| Compile a simple two-frame animation | Implemented |
| Play at measured BLE throughput | Planning hooks implemented; measurements pending |
| Expose `/text`, `/image`, `/brightness`, `/status` | Implemented in render-only mode; BLE delivery profile-dependent |
| Preserve evidence for unverified conclusions | Directory layout and provenance format implemented |
| Keep renderer independent from Bleak/framing | Enforced by package boundaries and tests |
