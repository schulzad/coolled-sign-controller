# Notes

## What I made

A night scene: the northern lights over a mountain lake. A red fox sits on a snow-capped
boulder at the water's edge, looking up at the aurora. Across the lake, a small cabin has lit
windows, a thin plume of chimney smoke and a reflection. A pyramid peak and a lower massif
frame a gap where the aurora dips lowest, with a pale distant ridge between them. The still
lake mirrors all of it, and a few stars show in the water too. In the foreground the fox's
single-file tracks cross the snow to the boulder, and dry grass pokes through near the corner.
The Big Dipper sits in the upper right in its autumn-evening orientation, low and upright
with the handle drooping.

Source: `scene.json`, which `build.py` assembles from the brushes `bg.py` (sky, aurora,
mountains, forest, lake, smoke, stars), `fg.py` (snow, boulder, shore rock, tracks, moon
shadows, grass) and `fox.py`, plus the hand sprites in `hand/` (cabin, window glints in the
water, and the fox rows that `fox.py` writes). `lib.py` holds the noise, the ordered dither
and the tone letters. The brushes work in continuous RGB and dither once with a
canvas-aligned Bayer threshold (8x8 for the sky and water, 4x4 elsewhere). Because the eight
colours are the corners of the RGB cube, every pixel lands on one of them. The aurora's
magenta is dithered on the inverted threshold so that it sits beside the green instead of
turning it white. `final.png` comes from `ws render scene.json final.png`, and `check.py`
prints `ok`. `hidden` reports 0 buried placements.

## Looks

I read a picture of the work 38 times: 12 overviews, 23 region looks and 3 views of
`final.png` at 1:1. They are kept in `looks/`, and every snapshot is in `versions/`.

## What I changed after looking

- First overview: the mountains were smooth domes with crater-like rock patches, so I
  replaced the voxel terrain with faceted 2D mountains that have a lit face and a shadowed
  face, ridge lines and snow gullies. The aurora's upper rays turned into white and pink
  noise, so I put the magenta on the inverted threshold. The foreground was a flat blue
  carpet, so I rebuilt it as snow.
- Later overviews: I toned the mountains and the sky down for night, darkening the sky
  gradient and turning the shadow faces navy. I dimmed the aurora in the top-left corner and
  thinned the magenta. I tried noisy drifts and blobby mounds on the snow, then settled on a
  smooth rolling field with a lit lip at the shore.
- The fox took the most rounds. In the first region look its white chest disappeared
  against the snow, so I curved the shoreline down behind it and put dark water there.
  The pose read as a diagonal wedge, so I made it upright, gave it a concave back and a
  rounded haunch, and swapped the dome shading for cel-shaded regions. I cut the yellow down
  to a few highlights. I let the tail drape over the rock with its white tip showing, after
  finding that the sprite box had cut it off.
- The black legs and ear tips vanished against the night. I added aurora rim lights, gave
  the legs orange with black paws and gave the ears red bases. The boulder also got a snowy
  top seen from above, which is correct for the camera height and puts snow behind the paws.
  Its first snow cap had wrapped round its sides like a tyre, so that went.
- The cabin first read as a red barn, so I darkened the walls to log-dark with glowing
  windows. The hand-drawn smoke looked like a cyan antenna, so I replaced it with a soft
  plume brush and added window glints in the water.
- The grass first came out as red blobs, so I redrew it as thin fanned stalks. The distant
  ridge and the centre hills had matched the sky, so I made the ridge pale and the hills
  dark. Finally I dropped the random cross-shaped stars, so the Big Dipper reads as the
  brightest pattern.
