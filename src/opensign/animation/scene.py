"""Frames written as text: whole drawings, and scenes of small sprites placed by coordinate.

A drawing is frames written one character per pixel in the legend ``text_preview``
writes, a blank line between frames. A scene is ``{"sprites": {name: rows}, "items":
[placement, ...], "frames": [[placement, ...], ...]}``. A sprite is a small drawing in
that legend, except that ``.`` is transparent and any letter outside the legend takes
the colour each placement gives it. A placement is ``{"sprite": name, "at": [x, y],
"colors": {letter: colour}}``, ``at`` being the sprite's top-left corner; it may hang
off the panel, and later placements draw on top. ``items`` appear in every frame, and
each entry of ``frames`` adds its own placements on top of them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from PIL import Image

from opensign.contracts import FrameBundle

from .preview import TEXT_LEGEND, image_from_text, mask_from_text
from .render import parse_color
from .studio import PixelAnimationStudio

_LETTER_RGB = {
    char: tuple(255 if on else 0 for on in key) for key, char in TEXT_LEGEND.items() if char != "."
}


def compile_drawing(
    text: str,
    width: int,
    height: int,
    *,
    foreground: str = "white",
    frame_ms: int = 200,
    max_frames: int | None = None,
) -> FrameBundle:
    """A drawing's frames, each centred on the panel; ``#`` lights ``foreground``.

    Raises ValueError naming what is wrong and where, as in ``frame 1: row 2 is 63
    wide but row 1 is 64; every row must be the same width``.
    """
    if frame_ms <= 0:
        raise ValueError("frame_ms must be positive")
    drawings = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    if max_frames is not None and len(drawings) > max_frames:
        raise ValueError(f"{len(drawings)} frames is more than the {max_frames} one upload holds")
    color = parse_color(foreground)
    frames = []
    for index, drawing in enumerate(drawings):
        where = f"frame {index}: " if len(drawings) > 1 else ""
        try:
            image = image_from_text(drawing, foreground=color)
        except ValueError as exc:
            raise ValueError(f"{where}{exc}") from exc
        if image.width > width or image.height > height:
            raise ValueError(f"{where}the drawing is {image.width}x{image.height}, "
                             f"larger than the {width}x{height} panel")
        frame = Image.new("RGB", (width, height))
        frame.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
        frames.append(frame)
    return PixelAnimationStudio(width, height).compile_images(
        frames,
        frame_durations_ms=[frame_ms] * len(frames),
        frames_per_second=1000 / frame_ms,
        metadata={"pattern": "draw"},
    )


def _color(value: Any, where: str) -> tuple[int, int, int]:
    """A colour given as a legend letter, a colour name or #rrggbb."""
    if isinstance(value, str) and value.upper() in _LETTER_RGB:
        return _LETTER_RGB[value.upper()]
    try:
        return parse_color(value)[:3]
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{where}: {value!r} is not a colour; "
                         "give a legend letter, a colour name or #rrggbb") from exc


def _stamp(canvas: Image.Image, sprites: Mapping[str, str], item: Any, where: str) -> None:
    """Draw one placed sprite onto a frame, recoloured as the placement says."""
    if not isinstance(item, Mapping):
        raise ValueError(f'{where} must be a placement like {{"sprite": "name", "at": [x, y]}}')
    name = item.get("sprite")
    if name not in sprites:
        raise ValueError(f"{where}: sprite {name!r} is not one of {', '.join(map(repr, sprites))}")
    at = item.get("at", [0, 0])
    if not (isinstance(at, list) and len(at) == 2 and all(type(value) is int for value in at)):
        raise ValueError(f"{where}: at must be [x, y], whole pixels from the panel's top-left corner")
    given = item.get("colors") or {}
    if not isinstance(given, Mapping):
        raise ValueError(f'{where}: colors must map letters to colours, like {{"X": "cyan"}}')
    colors = {str(letter).upper(): _color(value, f"{where}: colors[{letter!r}]")
              for letter, value in given.items()}
    text = sprites[name]
    missing = sorted({char.upper() for char in text if char.isalpha()} - set(_LETTER_RGB) - set(colors))
    if missing:
        raise ValueError(f"{where}: sprite {name!r} uses {', '.join(missing)}, which needs a colour, "
                         f'such as "colors": {{"{missing[0]}": "cyan"}}')
    image = image_from_text(text, foreground=colors.get("#", (255, 255, 255)), colors=colors)
    canvas.paste(image, (at[0], at[1]), mask_from_text(text))


def compile_scene(
    scene: Mapping[str, Any],
    width: int,
    height: int,
    *,
    frame_ms: int = 200,
    max_frames: int | None = None,
) -> FrameBundle:
    """A scene's frames: its sprites stamped where its placements say, later ones on top.

    Raises ValueError naming what is wrong and where it is, as in
    ``frames[1][0]: sprite 'ghots' is not one of 'ghost'``.
    """
    if frame_ms <= 0:
        raise ValueError("frame_ms must be positive")
    sprites = scene.get("sprites")
    if not isinstance(sprites, Mapping) or not sprites:
        raise ValueError('needs sprites, such as {"heart": [".R.R.", "RRRRR", ".RRR.", "..R.."]}')
    texts: dict[str, str] = {}
    for name, rows in sprites.items():
        if isinstance(rows, list) and all(isinstance(row, str) for row in rows):
            text = "\n".join(rows)
        elif isinstance(rows, str):
            text = rows
        else:
            raise ValueError(f"sprite {name!r} must be its rows of text")
        try:
            mask_from_text(text)
        except ValueError as exc:
            raise ValueError(f"sprite {name!r}: {exc}") from exc
        texts[name] = text
    items = scene.get("items", [])
    frames = scene.get("frames")
    if not isinstance(items, list):
        raise ValueError("items must be a list of placements")
    if frames is not None and not (
        isinstance(frames, list) and frames and all(isinstance(extra, list) for extra in frames)
    ):
        raise ValueError("frames must be a list holding one list of placements per frame")
    extras = frames or [[]]
    if max_frames is not None and len(extras) > max_frames:
        raise ValueError(f"{len(extras)} frames is more than the {max_frames} one upload holds")
    images = []
    for index, extra in enumerate(extras):
        canvas = Image.new("RGB", (width, height))
        placed = [(f"items[{i}]", item) for i, item in enumerate(items)]
        placed += [(f"frames[{index}][{i}]", item) for i, item in enumerate(extra)]
        for where, item in placed:
            _stamp(canvas, texts, item, where)
        images.append(canvas)
    return PixelAnimationStudio(width, height).compile_images(
        images,
        frame_durations_ms=[frame_ms] * len(images),
        frames_per_second=1000 / frame_ms,
        metadata={"pattern": "scene"},
    )
