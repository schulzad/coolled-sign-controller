# Generated previews

These files are reproducible outputs from the checked-in previewer:

```bash
opensign-preview --pattern test --width 48 --height 12 --scale 16 --grid --fps 1 \
  --output examples/generated/test-pattern.png \
  --bundle-out examples/generated/test-pattern.bundle.json

opensign-preview --pattern two-frame --width 48 --height 12 --scale 16 --grid --fps 2 \
  --output examples/generated/two-frame.gif \
  --bundle-out examples/generated/two-frame.bundle.json

opensign-preview --pattern text --text 'OPEN SIGN' --width 48 --height 12 --scale 12 --fps 12 \
  --output examples/generated/scroll-text.gif \
  --bundle-out examples/generated/scroll-text.bundle.json
```

Frame-bundle timestamps and hashes are regenerated from the new run; image pixels are deterministic for the same inputs and dependency behavior.
