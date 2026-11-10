# Notes

## What I made

A night scene, 384x384, in the eight 3-bit colours only. A steam train crosses a stone
viaduct over a still lake under the northern lights, with snowy peaks, a forested foothill
belt, and valley mist that makes the arches glow. Below that sit mirror reflections, a lit
cabin on the far shore seen through the third arch, and a semaphore signal at the end of the
viaduct.

- Source: `build.py`. It draws every pixel with numpy masks, ordered (Bayer 4x4) dithering
  along edges of the RGB cube, and cel-shaded puffs. It renders through the pixel-art-studio
  `Sprite` for the preview, stats and the 1x export.
- `zoom.py` makes the inspection crops (`zoom_*.png`). `preview.png` is the 2x working view.
- `final.png` is 384x384 RGB at 1x. `check.py` prints `ok`.

## How many times I looked

32 times: the 2x preview 14 times, the 1x final twice, and magnified crops 16 times.

## What I changed after looking

1. **First render.** The mountains read as blobby icebergs, the bridge and its reflection
   were a loud flat blue band, the smoke was a dotted ribbon and the magenta haze was too
   strong. I redrew the mountains from hand-placed ridge points with only light jitter. I
   darkened the stone to a navy dither with mortar joints, dimmed the reflection, and cut
   back the magenta.
2. **The lower half was a big empty dark band.** I moved the viaduct down to the lower
   third so its reflection fills the water. The straight gully lines looked like scratches,
   so I replaced them with radial couloirs that fan down from each summit. I dropped the
   wireframe-looking foreground pines.
3. **The locomotive vanished black-on-black against the forest.** I lowered the forest,
   added moonlit rim highlights (boiler crown, cab roof, chimney, wheel rims, coupling rod),
   and added a headlamp with a dithered beam and lit snow ahead.
4. **The mountains ran down to the rails like a backdrop wall.** I added forested foothills
   and a valley mist that thickens toward the water. This silhouettes the train and lights
   up every arch with pine silhouettes inside.
5. **Smoke.** It took four tries. The blurred-normal version came out as a dark stain, then
   a cyan icicle; the vertical column looked like a drill bit. The final version is a low
   plume of cel-shaded billows streaming back over the carriages in front of the dark trees.
   It loses light as it thins instead of dithering into a grey checkerboard, and has a few
   sparks at the chimney.
6. **Aurora.** Low-density green, magenta and blue dots made confetti noise in the upper
   sky. I equalised the ray pattern so rays are distinct streaks with dark gaps, cut the
   faint floor, made the hem a continuous bright band, and put a thin pink fringe under its
   brightest stretch.
7. **Mountains, second pass.** I made the right peak a two-summit massif so the peaks
   aren't twins. I pushed the far range darker so it recedes, and toned down the couloir
   wiggle.
8. **Water.** Per-row wobble and a vertical smear turned the reflected windows into jagged
   glyphs. I switched to a smooth low-frequency ripple and a half-step dim, removed the
   smear, kept the headlamp beam out of the reflection, and added sparse ripple glints.
9. **Train windows.** I removed the passenger silhouettes I had added, because they made
   the window rows look glitchy.
10. **Details.** I added window light and firebox glow on the snowy cornice, icicles, snow
    on the pier footings, and ice collars.
11. **Cabin.** Its snowy roof first disappeared into the bright mist. I redrew it as a dark
    silhouette with snow only along the roof edges.
12. **Signal.** I added a semaphore with a green lamp to balance the empty left end.
13. **Reeds.** I tried them twice as a foreground plane. Both times the stems vanished into
    the dark water and only the cattail heads floated, so I removed them.
14. **Masonry.** I gave each stone a slight tone variation so the face reads as hand-laid
    blocks rather than wallpaper.
