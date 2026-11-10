"""Frames written as text: whole drawings, and scenes of small sprites placed by coordinate.

A drawing is frames written one character per pixel in the legend ``text_preview``
writes, a blank line between frames. A scene is ``{"sprites": {name: rows}, "items":
[placement, ...], "frames": [[placement, ...], ...]}``. A sprite is a small drawing in
that legend, except that ``.`` is transparent, ``K`` paints off over whatever lies
beneath it, and any letter outside the legend takes the color each placement gives
it. A placement is ``{"sprite": name, "at": [x, y], "colors": {letter: color}}``,
``at`` being the sprite's top-left corner; it may hang off the panel, ``"mirror": "x"``
or ``"y"`` flips it, and later placements draw on top. ``items`` appear in every frame,
and each entry of ``frames`` adds its own placements on top of them.

An item can also change from frame to frame: ``"sprite"`` may list names and
``"cycle"`` positions, one per frame and repeating, and ``"move": [dx, dy]`` steps it
that far each frame, coming back in at the opposite edge with ``"wrap": true``. A scene
runs for its ``"length"``, or else for the least common multiple of its frames list,
every list an item repeats, and every wrapping item's trip round the panel.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageOps

from opensign.contracts import FrameBundle

from .preview import TEXT_LEGEND, image_from_text, mask_from_text
from .render import parse_color
from .studio import PixelAnimationStudio

_LETTER_RGB = {
    char: tuple(255 if on else 0 for on in key) for key, char in TEXT_LEGEND.items() if char != "."
}
_LETTER_RGB["K"] = (0, 0, 0)
_MIRRORS = {"x": ImageOps.mirror, "y": ImageOps.flip}


def compile_drawing(
    text: str,
    width: int,
    height: int,
    *,
    foreground: str = "white",
    frame_ms: int = 200,
    max_frames: int | None = None,
) -> FrameBundle:
    """A drawing's frames, each centered on the panel; ``#`` lights ``foreground``.

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
    """A color given as a legend letter, a color name or #rrggbb."""
    if isinstance(value, str) and value.upper() in _LETTER_RGB:
        return _LETTER_RGB[value.upper()]
    try:
        return parse_color(value)[:3]
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{where}: {value!r} is not a color; "
                         "give a legend letter, a color name or #rrggbb") from exc


def _is_xy(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(type(part) is int for part in value)


def _names(item: Mapping[str, Any]) -> list[Any]:
    """Every sprite an item shows: the names it lists, or its one name."""
    names = item.get("sprite")
    return list(names) if isinstance(names, list) else [names]


def _extent(item: Mapping[str, Any], sprites: Mapping[str, str]) -> tuple[int, int]:
    """The width of an item's widest sprite and the height of its tallest: the box that wraps."""
    sizes = [mask_from_text(sprites[name]).size for name in _names(item)]
    return max(width for width, _ in sizes), max(height for _, height in sizes)


def _check_placement(item: Any, where: str, sprites: Mapping[str, str], *, every_frame: bool) -> None:
    """Refuse a malformed placement before any frame is stamped: a misspelled colors key,
    or a malformed change from frame to frame."""
    if not isinstance(item, Mapping):
        raise ValueError(f'{where} must be a placement like {{"sprite": "name", "at": [x, y]}}')
    if "colours" in item:
        raise ValueError(f'{where}: the key is "colors", not "colours"')
    listed = isinstance(item.get("sprite"), list)
    changes = [key for key in ("move", "wrap", "cycle") if key in item]
    if listed:
        changes.append("a list of sprites")
    if not changes:
        return
    if not every_frame:
        raise ValueError(f"{where}: {changes[0]} belongs on items, which appear in every frame")
    if listed and not item["sprite"]:
        raise ValueError(f'{where}: sprite must name one sprite or list several, like ["open", "shut"]')
    for name in _names(item):
        if not isinstance(name, str) or name not in sprites:
            raise ValueError(f"{where}: sprite {name!r} is not one of {', '.join(map(repr, sprites))}")
    if "cycle" in item:
        cycle = item["cycle"]
        if not (isinstance(cycle, list) and cycle and all(_is_xy(at) for at in cycle)):
            raise ValueError(f"{where}: cycle must list positions in whole pixels, like [[10, 3], [10, 2]]")
        if "at" in item:
            raise ValueError(f"{where}: give at or cycle, not both")
    elif not _is_xy(item.get("at", [0, 0])):
        raise ValueError(f"{where}: at must be [x, y], whole pixels from the panel's top-left corner")
    if "move" in item and not _is_xy(item["move"]):
        raise ValueError(f"{where}: move must be [dx, dy], whole pixels per frame")
    if "wrap" in item and not (isinstance(item["wrap"], bool) and "move" in item):
        raise ValueError(f"{where}: wrap must be true or false, and needs move")


def _trip(item: Mapping[str, Any], sprites: Mapping[str, str], width: int, height: int) -> int:
    """Frames a wrapping item takes to come back to where it started."""
    box_width, box_height = _extent(item, sprites)
    dx, dy = item["move"]
    trips = [
        (panel + box) // math.gcd(abs(step), panel + box)
        for step, panel, box in ((dx, width, box_width), (dy, height, box_height))
        if step
    ]
    return math.lcm(*trips) if trips else 1


def _listed(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _frame_count(
    scene: Mapping[str, Any],
    items: list[Any],
    frames: list[Any],
    sprites: Mapping[str, str],
    width: int,
    height: int,
    max_frames: int | None,
) -> int:
    """How many frames a scene compiles to, refused over max_frames before any is stamped."""
    repeats = [(len(frames), "the frames list")] if frames else []
    for i, item in enumerate(items):
        if isinstance(item.get("sprite"), list):
            repeats.append((len(item["sprite"]), f"items[{i}]'s sprites"))
        if "cycle" in item:
            repeats.append((len(item["cycle"]), f"items[{i}]'s cycle"))
    length = scene.get("length")
    if length is not None:
        if type(length) is not int or length < 1:
            raise ValueError("length must be a whole number of frames, at least 1")
        for count, what in repeats:
            if length < count:
                raise ValueError(f"length {length} is shorter than {what} ({count})")
        count, why = length, ""
    else:
        for i, item in enumerate(items):
            if item.get("wrap"):
                repeats.append((_trip(item, sprites, width, height), f"items[{i}]'s trip round the panel"))
        counts: dict[int, str] = {}
        for repeat, what in repeats:
            counts.setdefault(repeat, what)
        count = math.lcm(*counts) if counts else 1
        why = ""
        if len(counts) > 1:
            parts = [f"{repeat} ({what})" for repeat, what in sorted(counts.items())]
            why = f", the least common multiple of {_listed(parts)},"
    if max_frames is not None and count > max_frames:
        raise ValueError(f"{count} frames{why} is more than the {max_frames} one upload holds")
    return count


def _place(item: Any, index: int, sprites: Mapping[str, str], width: int, height: int) -> Any:
    """The placement an item makes in frame ``index``: the sprite its list gives that frame,
    at the position its cycle gives, stepped on by its motion and, when it wraps, folded so
    that a sprite leaving one edge comes back in at the opposite one."""
    names, cycle, move = item.get("sprite"), item.get("cycle"), item.get("move")
    if not (isinstance(names, list) or cycle or move):
        return item
    sprite = names[index % len(names)] if isinstance(names, list) else names
    x, y = cycle[index % len(cycle)] if cycle else item.get("at", [0, 0])
    if move:
        x, y = x + index * move[0], y + index * move[1]
        if item.get("wrap"):
            box_width, box_height = _extent(item, sprites)
            if move[0]:
                x = (x + box_width) % (width + box_width) - box_width
            if move[1]:
                y = (y + box_height) % (height + box_height) - box_height
    return {**item, "sprite": sprite, "at": [x, y]}


def _stamp(canvas: Image.Image, sprites: Mapping[str, str], item: Any, where: str) -> None:
    """Draw one placed sprite onto a frame, recolored and flipped as the placement says:
    its letters draw on top, K as off, and ``.`` leaves what lies beneath showing."""
    if not isinstance(item, Mapping):
        raise ValueError(f'{where} must be a placement like {{"sprite": "name", "at": [x, y]}}')
    name = item.get("sprite")
    if name not in sprites:
        raise ValueError(f"{where}: sprite {name!r} is not one of {', '.join(map(repr, sprites))}")
    at = item.get("at", [0, 0])
    if not _is_xy(at):
        raise ValueError(f"{where}: at must be [x, y], whole pixels from the panel's top-left corner")
    mirror = item.get("mirror")
    if mirror is not None and (not isinstance(mirror, str) or mirror not in _MIRRORS):
        raise ValueError(f'{where}: mirror must be "x" (left to right) or "y" (top to bottom)')
    given = item.get("colors") or {}
    if not isinstance(given, Mapping):
        raise ValueError(f'{where}: colors must map letters to colors, like {{"X": "cyan"}}')
    colors = {"K": _LETTER_RGB["K"]} | {
        str(letter).upper(): _color(value, f"{where}: colors[{letter!r}]")
        for letter, value in given.items()
    }
    text = sprites[name]
    missing = sorted({char.upper() for char in text if char.isalpha()} - set(_LETTER_RGB) - set(colors))
    if missing:
        raise ValueError(f"{where}: sprite {name!r} uses {', '.join(missing)}, which needs a color, "
                         f'such as "colors": {{"{missing[0]}": "cyan"}}')
    image = image_from_text(text, foreground=colors.get("#", (255, 255, 255)), colors=colors)
    mask = mask_from_text(text)
    if mirror:
        image, mask = _MIRRORS[mirror](image), _MIRRORS[mirror](mask)
    canvas.paste(image, (at[0], at[1]), mask)


def compile_scene(
    scene: Mapping[str, Any],
    width: int,
    height: int,
    *,
    frame_ms: int = 200,
    max_frames: int | None = None,
) -> FrameBundle:
    """A scene's frames: its sprites stamped where its placements say, later ones on top.

    The frame count is settled before anything is stamped, and refused when it is more
    than ``max_frames``. Raises ValueError naming what is wrong and where it is, as in
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
    for i, item in enumerate(items):
        _check_placement(item, f"items[{i}]", texts, every_frame=True)
    for f, extra in enumerate(extras):
        for i, item in enumerate(extra):
            _check_placement(item, f"frames[{f}][{i}]", texts, every_frame=False)
    count = _frame_count(scene, items, frames or [], texts, width, height, max_frames)
    if count == 1:
        for i, item in enumerate(items):
            dx, dy = item.get("move", [0, 0])
            if dx or dy:
                box_width, box_height = _extent(item, texts)
                steps = math.ceil((width + box_width) / abs(dx) if dx else (height + box_height) / abs(dy))
                raise ValueError(f'items[{i}] moves, but the scene has one frame; give it a length, '
                                 f'such as "length": {steps} to cross the panel once')
    images = []
    for index in range(count):
        canvas = Image.new("RGB", (width, height))
        for i, item in enumerate(items):
            _stamp(canvas, texts, _place(item, index, texts, width, height), f"items[{i}]")
        f = index % len(extras)
        for i, item in enumerate(extras[f]):
            _stamp(canvas, texts, item, f"frames[{f}][{i}]")
        images.append(canvas)
    return PixelAnimationStudio(width, height).compile_images(
        images,
        frame_durations_ms=[frame_ms] * len(images),
        frames_per_second=1000 / frame_ms,
        metadata={"pattern": "scene"},
    )
