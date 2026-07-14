from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps


def parse_color(value: str | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, tuple):
        if len(value) != 3:
            raise ValueError("RGB colors must contain three values")
        return tuple(max(0, min(255, int(item))) for item in value)
    return ImageColor.getrgb(value)


def render_test_pattern(width: int = 48, height: int = 12) -> Image.Image:
    """Render corner colors, center axes, ticks, and a right-pointing orientation arrow."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline="white")

    block = max(1, min(3, width // 8 or 1, height // 3 or 1))
    draw.rectangle((1, 1, min(width - 2, block), min(height - 2, block)), fill="red")
    draw.rectangle(
        (max(1, width - block - 1), 1, width - 2, min(height - 2, block)),
        fill="green",
    )
    draw.rectangle(
        (1, max(1, height - block - 1), min(width - 2, block), height - 2),
        fill="blue",
    )
    draw.rectangle(
        (max(1, width - block - 1), max(1, height - block - 1), width - 2, height - 2),
        fill="yellow",
    )

    center_x = width // 2
    center_y = height // 2
    if width > 2:
        draw.line((1, center_y, width - 2, center_y), fill=(0, 160, 255))
    if height > 2:
        draw.line((center_x, 1, center_x, height - 2), fill=(255, 0, 180))

    for x in range(4, max(4, width - 1), 4):
        if 0 <= x < width:
            draw.point((x, 0), fill=(255, 128, 0))
            draw.point((x, height - 1), fill=(255, 128, 0))
    for y in range(4, max(4, height - 1), 4):
        if 0 <= y < height:
            draw.point((0, y), fill=(0, 255, 128))
            draw.point((width - 1, y), fill=(0, 255, 128))

    arrow_start = min(max(2, width // 6), max(2, width - 3))
    arrow_end = max(arrow_start, width - max(4, width // 8))
    draw.line((arrow_start, center_y, arrow_end, center_y), fill="white")
    if width >= 8 and height >= 5:
        draw.line((arrow_end, center_y, arrow_end - 3, center_y - 2), fill="white")
        draw.line((arrow_end, center_y, arrow_end - 3, center_y + 2), fill="white")
    return image


def render_two_frame_animation(width: int = 48, height: int = 12) -> list[Image.Image]:
    base = render_test_pattern(width, height)
    first = base.copy()
    second = base.copy()
    draw_first = ImageDraw.Draw(first)
    draw_second = ImageDraw.Draw(second)

    for x in range(2, max(2, width - 2), 4):
        draw_first.rectangle((x, max(1, height - 3), min(width - 2, x + 1), height - 2), fill="cyan")
    for x in range(4, max(4, width - 2), 4):
        draw_second.rectangle(
            (x, max(1, height - 3), min(width - 2, x + 1), height - 2), fill="magenta"
        )

    cursor_y = max(1, height // 2 - 1)
    first_x = max(2, width // 3)
    second_x = min(width - 3, max(2, (2 * width) // 3))
    draw_first.rectangle((first_x, cursor_y, min(width - 2, first_x + 1), min(height - 2, cursor_y + 1)), fill="lime")
    draw_second.rectangle((second_x, cursor_y, min(width - 2, second_x + 1), min(height - 2, cursor_y + 1)), fill="orange")
    return [first, second]


def render_checker_animation(
    width: int = 48,
    height: int = 12,
    *,
    frame_count: int = 8,
    foreground: str = "#00E5FF",
    background: str = "#071A2B",
) -> list[Image.Image]:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    foreground_rgb = parse_color(foreground)
    background_rgb = parse_color(background)
    frames: list[Image.Image] = []
    for phase in range(frame_count):
        image = Image.new("RGB", (width, height), background_rgb)
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                if ((x + y + phase) // 2) % 2 == 0:
                    pixels[x, y] = foreground_rgb
        frames.append(image)
    return frames


def _default_font() -> ImageFont.ImageFont:
    return ImageFont.load_default()


def render_scroll_text(
    text: str,
    width: int = 48,
    height: int = 12,
    *,
    foreground: str = "white",
    background: str = "black",
    pixels_per_frame: int = 1,
    dwell_frames: int = 2,
) -> list[Image.Image]:
    if not text:
        raise ValueError("text cannot be empty")
    if pixels_per_frame <= 0:
        raise ValueError("pixels_per_frame must be positive")
    font = _default_font()
    probe = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(probe)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = max(1, right - left)
    text_height = max(1, bottom - top)
    y = max(0, (height - text_height) // 2 - top)
    positions = list(range(width, -text_width - 1, -pixels_per_frame))
    if not positions:
        positions = [0]
    positions = [positions[0]] * max(0, dwell_frames) + positions + [positions[-1]] * max(0, dwell_frames)

    frames: list[Image.Image] = []
    for x in positions:
        image = Image.new("RGB", (width, height), parse_color(background))
        frame_draw = ImageDraw.Draw(image)
        frame_draw.text((x, y), text, font=font, fill=parse_color(foreground))
        frames.append(image)
    return frames


def render_static_text(
    text: str,
    width: int = 48,
    height: int = 12,
    *,
    foreground: str = "white",
    background: str = "black",
) -> Image.Image:
    if not text:
        raise ValueError("text cannot be empty")
    image = Image.new("RGB", (width, height), parse_color(background))
    draw = ImageDraw.Draw(image)
    font = _default_font()
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (width - (right - left)) // 2 - left
    y = (height - (bottom - top)) // 2 - top
    draw.text((x, y), text, font=font, fill=parse_color(foreground))
    return image


def _pick_resample(source: Image.Image, width: int, height: int) -> Image.Resampling:
    """Choose a resampling filter by direction.

    Downscaling with NEAREST keeps just one source pixel per target pixel and
    aliases badly (most of a 500x500 GIF is thrown away going to 64x16), so
    area-style LANCZOS is used whenever either axis shrinks. Upscaling (e.g.
    blowing pixel art up to fill the panel) stays on NEAREST to keep edges crisp.
    """
    if source.width > width or source.height > height:
        return Image.Resampling.LANCZOS
    return Image.Resampling.NEAREST


def fit_image(
    source: Image.Image,
    width: int,
    height: int,
    *,
    fit_mode: str = "contain",
    background: str = "black",
    resample: Image.Resampling | None = None,
) -> Image.Image:
    image = source.convert("RGB")
    if resample is None:
        resample = _pick_resample(image, width, height)
    target_size = (width, height)
    if fit_mode == "stretch":
        return image.resize(target_size, resample=resample)
    if fit_mode == "cover":
        return ImageOps.fit(image, target_size, method=resample, centering=(0.5, 0.5))
    if fit_mode != "contain":
        raise ValueError("fit_mode must be contain, cover, or stretch")
    contained = ImageOps.contain(image, target_size, method=resample)
    canvas = Image.new("RGB", target_size, parse_color(background))
    x = (width - contained.width) // 2
    y = (height - contained.height) // 2
    canvas.paste(contained, (x, y))
    return canvas


def apply_orientation(
    image: Image.Image,
    *,
    rotation: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
    preserve_size: bool = True,
) -> Image.Image:
    rotation = rotation % 360
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("rotation must be 0, 90, 180, or 270")
    original_size = image.size
    result = image
    if rotation == 90:
        result = result.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        result = result.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        result = result.transpose(Image.Transpose.ROTATE_270)
    if flip_horizontal:
        result = ImageOps.mirror(result)
    if flip_vertical:
        result = ImageOps.flip(result)
    if preserve_size and result.size != original_size:
        result = result.resize(original_size, resample=Image.Resampling.NEAREST)
    return result


def load_and_fit_image(
    source: str | Path | Image.Image,
    width: int,
    height: int,
    *,
    fit_mode: str = "contain",
    background: str = "black",
    resample: Image.Resampling | None = None,
) -> Image.Image:
    if isinstance(source, Image.Image):
        image = source
    else:
        with Image.open(source) as opened:
            image = opened.convert("RGB")
    return fit_image(
        image, width, height, fit_mode=fit_mode, background=background, resample=resample
    )


def image_from_base64(value: str) -> Image.Image:
    payload = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    try:
        raw = base64.b64decode(payload, validate=True)
    except ValueError as exc:
        raise ValueError("image_base64 is not valid base64") from exc
    try:
        with Image.open(io.BytesIO(raw)) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise ValueError("image_base64 does not contain a supported image") from exc


def normalize_frames(
    frames: Iterable[Image.Image],
    width: int,
    height: int,
    *,
    rotation: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
) -> list[Image.Image]:
    normalized: list[Image.Image] = []
    for frame in frames:
        fitted = fit_image(frame, width, height, fit_mode="stretch")
        normalized.append(
            apply_orientation(
                fitted,
                rotation=rotation,
                flip_horizontal=flip_horizontal,
                flip_vertical=flip_vertical,
            )
        )
    return normalized


def composite_frame(
    frame: Image.Image, background: tuple[int, int, int] = (0, 0, 0)
) -> Image.Image:
    """Flatten a possibly-transparent animation frame onto a solid background.

    ``ImageSequence`` yields frames in their native mode (often palette "P" with
    a transparent index, or "RGBA"). Converting straight to "RGB" bakes in the
    transparent index's colour (usually black) and ignores the requested
    background, so composite through RGBA instead.
    """
    rgba = frame.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (background[0], background[1], background[2], 255))
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def _bayer_matrix(order: int) -> list[list[int]]:
    """Recursive Bayer threshold matrix of side ``order`` (a power of two)."""
    matrix = [[0]]
    size = 1
    while size < order:
        size *= 2
        half = size // 2
        previous = matrix
        matrix = [[0] * size for _ in range(size)]
        for y in range(half):
            for x in range(half):
                base = previous[y][x] * 4
                matrix[y][x] = base
                matrix[y][x + half] = base + 2
                matrix[y + half][x] = base + 3
                matrix[y + half][x + half] = base + 1
    return matrix


_ORDERED_CACHE: dict[tuple[int, int, int], list[int]] = {}


def _ordered_thresholds(width: int, height: int, order: int = 4) -> list[int]:
    """Per-pixel 0-255 threshold in ``Image.getdata`` (row-major) order."""
    key = (width, height, order)
    cached = _ORDERED_CACHE.get(key)
    if cached is not None:
        return cached
    matrix = _bayer_matrix(order)
    n = len(matrix)
    denom = float(n * n)
    tile = [[int((matrix[y][x] + 0.5) / denom * 255) for x in range(n)] for y in range(n)]
    flat = [tile[y % n][x % n] for y in range(height) for x in range(width)]
    _ORDERED_CACHE[key] = flat
    return flat


def apply_levels(
    image: Image.Image, *, black_point: int = 0, white_point: int = 255
) -> Image.Image:
    """Contrast-stretch RGB so [black_point, white_point] maps to [0, 255].

    Channel values at or below ``black_point`` clip to 0 and values at or above
    ``white_point`` clip to 255. This is the fix for "dark background washes out"
    on the panel: a source whose background is dark grey (not true black) gets
    faithfully rendered as a dim glow by dithering -- especially temporal
    dithering with many subframes -- so raising ``black_point`` above that grey
    crushes it to off, while lowering ``white_point`` lifts muted foregrounds.
    """
    if not 0 <= black_point < white_point <= 255:
        raise ValueError("require 0 <= black_point < white_point <= 255")
    if black_point == 0 and white_point == 255:
        return image.convert("RGB")
    span = white_point - black_point
    lut = [max(0, min(255, round((value - black_point) * 255 / span))) for value in range(256)]
    bands = [band.point(lut) for band in image.convert("RGB").split()]
    return Image.merge("RGB", bands)


def quantize_to_panel(image: Image.Image, mode: str = "ordered") -> Image.Image:
    """Reduce an RGB image to the panel's 8-colour gamut (1 bit per channel).

    The CoolLEDX panel only shows each channel on or off, so continuous-tone
    content must be dithered before the codec's hard ``>127`` threshold or it
    collapses into a few flat bands. Modes:

    - ``"ordered"``: Bayer ordered dithering. The threshold depends on pixel
      position rather than neighbouring error, so stationary regions render
      identically every frame (no temporal shimmer). Best default for animation.
    - ``"floyd"``: per-channel Floyd-Steinberg. Best detail on a single still,
      but re-diffuses error each frame, which shimmers on animation.
    - ``"none"``: no dithering; rely on the codec's hard threshold. Crisp for
      synthetic art (text, patterns) already near the channel extremes.

    Output channels are always 0 or 255, so the codec's threshold passes them
    through unchanged.
    """
    rgb = image.convert("RGB")
    if mode == "none":
        return rgb
    if mode == "floyd":
        bands = [band.convert("1").convert("L") for band in rgb.split()]
        return Image.merge("RGB", bands)
    if mode != "ordered":
        raise ValueError("dither mode must be 'ordered', 'floyd', or 'none'")
    thresholds = _ordered_thresholds(rgb.width, rgb.height)
    quantized = [
        (255 if r > t else 0, 255 if g > t else 0, 255 if b > t else 0)
        for (r, g, b), t in zip(rgb.getdata(), thresholds, strict=False)
    ]
    out = Image.new("RGB", rgb.size)
    out.putdata(quantized)
    return out


_BAYER_UNIT_CACHE: dict[tuple[int, int, int], list[float]] = {}


def _bayer_unit(width: int, height: int, order: int = 4) -> list[float]:
    """Per-pixel Bayer threshold in [0, 1), row-major (``Image.getdata`` order)."""
    key = (width, height, order)
    cached = _BAYER_UNIT_CACHE.get(key)
    if cached is not None:
        return cached
    matrix = _bayer_matrix(order)
    n = len(matrix)
    denom = float(n * n)
    tile = [[(matrix[y][x] + 0.5) / denom for x in range(n)] for y in range(n)]
    flat = [tile[y % n][x % n] for y in range(height) for x in range(width)]
    _BAYER_UNIT_CACHE[key] = flat
    return flat


def _even_spread_order(n: int) -> list[int]:
    """Permutation of 0..n-1 ordered by the base-2 van der Corput sequence.

    Playing subframes in this order spreads each pixel's "on" frames as evenly
    as possible through the loop, pushing the perceived flicker to the highest
    frequency the frame count allows (for powers of two this is the classic
    bit-reversal order, e.g. n=4 -> [0, 2, 1, 3]).
    """
    if n <= 1:
        return [0] * max(n, 0) or [0]

    def radical_inverse(i: int) -> float:
        value, denom = 0.0, 1.0
        while i:
            denom *= 2.0
            value += (i & 1) / denom
            i >>= 1
        return value

    return sorted(range(n), key=radical_inverse)


def temporal_dither_frames(
    image: Image.Image, *, subframes: int = 2, order: int = 4
) -> list[Image.Image]:
    """Expand one still into ``subframes`` binarized frames for temporal colour.

    The panel shows each channel only on or off, but if it can advance frames
    faster than the eye's flicker-fusion threshold (measured ~62 Hz on this
    hardware), a fast N-frame loop makes each pixel's *duty cycle* read as an
    intermediate level: black<->white averages to grey, red<->green to yellow,
    and so on. This yields ``subframes + 1`` temporal levels per channel, which
    combined with the spatial Bayer mask below fills in the colours between.

    Implementation is a single spatiotemporal ordered-dither: for subframe
    ``t`` the per-pixel threshold is ``(order_seq[t] + bayer(x, y)) / N``. The
    Bayer term dithers spatially (so neighbouring pixels round opposite ways),
    while ``order_seq`` from :func:`_even_spread_order` distributes each pixel's
    on-frames evenly in time to maximise the flicker frequency. Output channels
    are 0 or 255, so the codec's hard threshold passes them through unchanged.

    Caveats worth knowing: duty cycle couples to brightness (a 50% level is
    ~half luminance), and channels are not perceptually matched (on this panel
    red<->green fused slightly green), so the reachable gamut is a
    luminance-limited volume rather than the full cube.
    """
    if subframes < 2:
        raise ValueError("temporal dithering needs at least 2 subframes")
    rgb = image.convert("RGB")
    width, height = rgb.size
    bayer = _bayer_unit(width, height, order)
    sequence = _even_spread_order(subframes)
    source = list(rgb.getdata())
    frames: list[Image.Image] = []
    for step in sequence:
        frame_pixels = [
            (
                255 if r * subframes > step * 255 + b * 255 else 0,
                255 if g * subframes > step * 255 + b * 255 else 0,
                255 if bl * subframes > step * 255 + b * 255 else 0,
            )
            for (r, g, bl), b in zip(source, bayer, strict=False)
        ]
        frame = Image.new("RGB", (width, height))
        frame.putdata(frame_pixels)
        frames.append(frame)
    return frames
