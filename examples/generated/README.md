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

## README gallery (`gallery/`)

The clips embedded in the top-level README are rendered straight from the shipping codec, so they double as a smoke test of the animation path:

```bash
coolled anim examples/downloaded/nian.gif \
  --fit contain --key-color auto --dither none \
  --preview examples/generated/gallery/nian.preview.gif

coolled anim examples/downloaded/sonic-the-hedgehog.gif \
  --fit contain --key-color auto --dither none \
  --preview examples/generated/gallery/sonic-the-hedgehog.preview.gif

# Stills use --dither none for crisp pixel art; the Matrix poster is a gradient,
# so ordered dithering shows the channel overlap (green/yellow/white).
coolled image examples/generated/matrix_still.png \
  --fit cover --dither ordered \
  --preview examples/generated/gallery/matrix-still.png

# Dither comparison. colorbar.source.png is a synthesized full-spectrum hue
# sweep (colorsys HSV, S=V=1) — checked in so the three renders reproduce.
for d in none ordered floyd; do
  coolled image examples/generated/gallery/colorbar.source.png \
    --fit fill --dither "$d" \
    --preview "examples/generated/gallery/colorbar.$d.png"
done
```

`--preview` skips BLE, so these are safe to regenerate without a panel.
