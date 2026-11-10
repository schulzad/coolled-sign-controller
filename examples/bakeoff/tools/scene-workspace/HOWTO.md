# Scene workspace

You paint by writing a scene file: small text sprites placed by coordinate on a canvas. The workspace composes the scene exactly and gives you pictures and text to look at. Every command runs through `ws`:

    /Users/adamschulz/source/hacking/pixel-bakeoff/tools/scene-workspace/ws <command> ...

## The scene file

```json
{
  "size": [384, 384],
  "sprites": {
    "moon": ["..WW..", ".WWWW.", "WWWWWW", ".WWWW.", "..WW.."],
    "crater": ["KK", "KK"]
  },
  "items": [
    {"sprite": "moon", "at": [40, 30], "note": "the small moon"},
    {"sprite": "crater", "at": [42, 32], "colors": {"K": "black"}}
  ]
}
```

- A sprite is rows of text, one character per pixel, every row the same width. `.` is transparent.
- These letters paint their own colour: `R` red, `G` green, `B` blue, `C` cyan, `M` magenta, `Y` yellow, `W` white.
- Any other letter takes the colour its placement gives it in `colors`: one of the letters above, a colour name, or `#rrggbb` from the eight colours. That is how you paint black: map a letter to `"black"`. A placement can also recolour the letters above.
- `at` is the sprite's top-left corner on the canvas. Sprites may hang off the edges and are clipped there. Later items draw on top of earlier ones, and anything left unpainted is black.
- An item's optional `note` shows up in `trace` and `outline`, so you can tell placements apart later.

## Brushes

Large areas are slow to type by hand. Write small Python scripts of your own, brushes, that compute rows and write them into the scene file as sprites and items: a gradient made with an ordered dither, a textured surface, a shape from a formula. Once a brush has written its rows they are yours: refine them by editing the rows or by painting small sprites on top. Give each brush its own sprite names, so re-running one never overwrites your hand work. Run brushes with `python3`, which has Pillow.

The scene file can grow large. You don't need to read it whole: `outline`, `trace` and a text search for a sprite's name find what you need.

## Commands

| Command | What it gives you |
|---|---|
| `ws overview scene.json look.png [--tiles 128] [--box X,Y,W,H] [--lines]` | The whole canvas, with a labelled tile grid (A1, B2, ...) in the margin. `--box` outlines a region; `--lines` draws the grid across the picture. |
| `ws region scene.json look.png X Y W H [--margin 16] [--px N]` | One rectangle enlarged, with coordinate rulers, a pixel grid and a margin of its surroundings. |
| `ws trace scene.json X Y` | Which placement and sprite cell painted that pixel, and everything beneath it. |
| `ws outline scene.json [X Y W H]` | The placements that touch a region. |
| `ws hidden scene.json` | Placements that show nowhere because later paint covers them. |
| `ws snap scene.json` | Saves a numbered copy in `versions/` next to the scene. |
| `ws diff OLD.json NEW.json diff.png` | How many pixels changed between two versions, where, and a before-and-after picture. |
| `ws render scene.json final.png` | The scene at one image pixel per canvas pixel. |

Read a PNG to look at it.

## The loop

Work coarse to fine, the way a painter blocks in a picture:

1. Decide on the whole picture before the first look.
2. Block in the big shapes, brushes helping, and take an overview.
3. An overview of a 384x384 canvas shows about 2 screen pixels per canvas pixel. That is enough to judge composition, but not single pixels or dither patterns, which read from about 4 screen pixels per canvas pixel up. Judge detail in region looks: a tile from the overview's grid, or a box drawn round one subject.
4. When a look shows something wrong and you can't tell why, trace a pixel or two before changing anything. Seeing a flaw and diagnosing it are separate steps.
5. Snap before an edit and diff after it, to confirm the edit changed only what you meant.
6. Step back to an overview now and then to keep the whole together. Before finishing, clear the buried paint `hidden` finds.
