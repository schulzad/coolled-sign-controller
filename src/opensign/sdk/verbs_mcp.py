"""
coolled-verbs: an MCP surface for the panel, as verbs that take nouns.

Modelled on smdl-factory's smdl-verbs spike: a verb called with no noun returns
its nouns, failures come back flagged isError with the usage, and every path
must be absolute. describe reads the panel; render compiles content through the
same PixelAnimationStudio the CLI and API use and returns each frame as text,
one character per pixel, and its draw noun reads frames written that way back.
plan compiles the same content into the packets a send would write and names
them with a plan_id; accept sends a plan_id's packets, and only when the server
was started with --execute. Without --execute nothing here connects or writes.

Run:
    opensign-verbs --profile device_profile.local.json [--execute]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from PIL import Image, ImageChops
from pydantic import Field

from opensign.animation.cache import default_render_cache_dir
from opensign.animation.preview import TEXT_LEGEND, TEXT_STYLES, contact_sheet, text_preview
from opensign.animation.render import parse_color, render_static_text, render_wide_text
from opensign.animation.scene import compile_drawing, compile_scene
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, FrameBundle
from opensign.protocol.codec import CodecError
from opensign.protocol.codecs.coolledx import (
    MODE_LEFT,
    PIXEL_BYTES_MAX,
    USER_SCROLL_SPEED_MAX,
    USER_SCROLL_SPEED_MIN,
)
from opensign.protocol.runtime import ProtocolRuntime
from opensign.protocol.transport import ProgressCallback

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
# accept replaces what the panel shows, and sending one plan twice leaves it the same.
SENDS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
)

# The most frames one render returns as text; a longer clip is paged with frame.
MAX_FRAMES_PER_CALL = 8

# The widest native-scroll banner a plan shows as text; the panel still gets all of it.
MAX_BANNER_PREVIEW = 256

# A picture draws each LED this many pixels wide, and leaves this gap between frames.
PICTURE_SCALE = 8
PICTURE_GAP = 6

# How long accept waits on an upload before leaving it to finish in the background,
# kept well inside the time an MCP client gives one call.
ACCEPT_WAIT_SECONDS = 25.0

# How many recent plans accept can find from a plan_id alone.
MAX_REMEMBERED_PLANS = 32

DEFAULT_PROFILE = Path("device_profile.local.json")
STARTER_PROFILE = Path("device_profile.json")

READ_ONLY_BLOCKER = (
    "this server was started without --execute, so accept will not send; "
    "add --execute to its arguments to let it"
)

logging.getLogger("mcp").setLevel(logging.ERROR)

mcp = FastMCP(
    "coolled-verbs",
    instructions=(
        "A render and send surface for a CoolLEDX LED panel. Call a verb with no noun "
        "to see its nouns and their arguments. describe panel gives the geometry and "
        "colours; render compiles text, a drawing, a scene, a pattern, an image, an "
        "animation or a frame bundle exactly as the panel would show it, and returns "
        "each frame as a picture and as text, one character per pixel: '.' is off, and "
        "either '#' marks a lit pixel (mono) or a letter names its colour (describe "
        "legend). The draw noun reads whole frames written that way; the scene noun "
        "places small sprites written that way at x,y, which is easier to get right "
        "than whole frames. plan compiles content into the packets a send would write, "
        "without sending, and returns a plan_id; accept sends a plan_id, and only when "
        "the server was started with --execute (describe panel says whether it was). "
        "Every path must be absolute."
    ),
)

# plan noun -> (the arguments it reads, the first one required; what it sends)
PLANS: dict[str, tuple[tuple[str, ...], str]] = {
    "text": (
        ("value", "scroll", "speed", "foreground", "background"),
        "text as a still, or with scroll as one wide banner the panel's own firmware scrolls",
    ),
    "draw": (
        ("value", "foreground", "frame_ms"),
        "frames drawn as text, read the way render draw reads them",
    ),
    "scene": (
        ("scene", "frame_ms"),
        "sprites placed at x,y, as a still or one frame per entry of frames",
    ),
    "pattern": (("value",), "a built-in pattern: test, checker or two-frame"),
    "image": (("path", "fit", "dither"), "an image fitted and quantized to the panel"),
    "animation": (
        ("path", "fit", "dither", "key_color", "scroll", "background"),
        "an animated GIF, WebP or APNG, in place or side-scrolling",
    ),
    "bundle": (("path",), "a saved frame bundle (.json)"),
}

# The value each plan argument takes when a plan's arguments leave it out.
PLAN_DEFAULTS: dict[str, Any] = {
    "value": "",
    "path": "",
    "scroll": False,
    "speed": 8,
    "foreground": "white",
    "background": "black",
    "fit": "contain",
    "dither": "",
    "key_color": "",
    "frame_ms": 200,
    "scene": {},
}

# verb -> noun -> (arguments, what it returns)
NOUNS: dict[str, dict[str, tuple[str, str]]] = {
    "describe": {
        "panel": ("", "the panel's id, geometry, colour mode, capability statuses, "
                      "and whether accept sends"),
        "legend": ("", "the character each panel colour renders as, which draw reads back"),
        "upload": ("", "the upload accept started last: its progress, then how it ended"),
    },
    "render": {
        "text": ("value [scroll] [foreground] [background] [frame] [style]",
                 "text as the panel shows it, static or as a host-side scroll"),
        "draw": ("value [foreground] [frame_ms] [frame] [style]",
                 "frames drawn as text, one character per pixel, each centred on the "
                 "panel; a blank line starts the next frame"),
        "scene": ("scene [frame_ms] [frame] [style]",
                  "small sprites drawn as text and placed at x,y, recoloured per copy; "
                  "a still, or one frame per entry of frames"),
        "pattern": ("value [frame] [style]", "a built-in pattern: test, checker or two-frame"),
        "image": ("path [fit] [dither] [style]", "an image fitted and quantized to the panel"),
        "animation": ("path [fit] [dither] [key_color] [scroll] [background] [frame] [style]",
                      "an animated GIF, WebP or APNG as the panel plays it, in place or "
                      "side-scrolling"),
        "bundle": ("path [frame] [style]", "a saved frame bundle (.json)"),
    },
    "plan": {
        noun: (" ".join([names[0], *(f"[{name}]" for name in names[1:])]), sends)
        for noun, (names, sends) in PLANS.items()
    },
}

ACCEPT_USAGE: dict[str, str] = {
    "verb": "accept",
    "args": "plan_id [arguments]",
    "returns": "the upload: sent, failed, or still uploading in the background "
               "(describe upload follows it)",
    "how": "plan first, then pass its plan_id; arguments are only needed for a plan "
           "the server no longer remembers",
}

PATTERNS = ("test", "checker", "two-frame")
FIT_MODES = {"contain": "contain", "cover": "cover", "fill": "stretch", "stretch": "stretch"}
DITHERS = ("none", "ordered", "floyd")

# Arguments render and plan share.
Value = Annotated[str, Field(description="text: the message. pattern: test, checker or two-frame. draw: the frames, one character per pixel (describe legend), at most the panel's size; a blank line starts the next frame.")]
FilePath = Annotated[str, Field(description="image, animation or bundle: the file, as an absolute path.")]
Foreground = Annotated[str, Field(description="text: a colour name or #rrggbb. draw: the colour '#' lights.")]
Background = Annotated[str, Field(description="text or animation: a colour name or #rrggbb.")]
Fit = Annotated[str, Field(description="image or animation: contain, cover or fill (stretch is an alias).")]
Dither = Annotated[str, Field(description="image or animation: none, ordered or floyd; omit for none on an image and ordered on an animation.")]
KeyColor = Annotated[str, Field(description="animation only: a colour to knock out to black, or auto to sample it from the frame border.")]
FrameMs = Annotated[int, Field(description="draw or scene: how long each frame shows, in milliseconds.")]
Scene = Annotated[dict[str, Any] | None, Field(description='scene only: {"sprites": {"name": ["rows", ...]}, "items": [{"sprite": "name", "at": [x, y], "colors": {"X": "cyan"}}], "frames": [[placements], ...]}. A sprite is a small drawing in the legend where "." is transparent, and any other letter, such as X, takes the colour each placement gives it (a placement may recolour legend letters too). at is the sprite\'s top-left corner on the panel and may hang off its edges; later placements draw on top. items appear in every frame, and each entry of frames adds its own placements on top of them.')]


def _noun(verb: str, description: str) -> Any:
    """The noun argument, its schema enumerating the verb's nouns; "" lists them."""
    return Field(description=description, json_schema_extra={"enum": ["", *NOUNS[verb]]})


def _listing(verb: str) -> dict[str, Any]:
    return {
        "verb": verb,
        "nouns": [
            {"noun": noun, "args": args, "returns": returns}
            for noun, (args, returns) in NOUNS[verb].items()
        ],
    }


def _fail(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))],
        structuredContent=payload,
        isError=True,
    )


def _unknown(verb: str, noun: str) -> CallToolResult:
    return _fail({"error": f"unknown noun {noun!r} for {verb}", **_listing(verb)})


def _usage(verb: str, noun: str, problem: str) -> CallToolResult:
    args, _ = NOUNS[verb][noun]
    return _fail({"error": f"{verb} {noun}: {problem}", "usage": f"{verb} {noun} {args}".strip()})


_profile_path: Path = DEFAULT_PROFILE
_execute: bool = False


def _profile() -> DeviceProfile:
    """The configured profile, read on each call so a re-profiled panel shows up;
    the checked-in starter stands in when the default local profile is absent."""
    path = _profile_path
    if path == DEFAULT_PROFILE and not path.exists() and STARTER_PROFILE.exists():
        path = STARTER_PROFILE
    return DeviceProfile.load(path)


def _frame_budget(profile: DeviceProfile) -> int:
    """The most frames one 0x04 upload holds at the panel's geometry."""
    return PIXEL_BYTES_MAX // max(1, profile.width * profile.height * 3 // 8)


def _frames(bundle: FrameBundle, frame: str) -> tuple[list[int], str | None]:
    """The frame indexes to return, or what is wrong with frame."""
    count = len(bundle.frames)
    if frame == "":
        return list(range(min(count, MAX_FRAMES_PER_CALL))), None
    if frame == "all":
        if count > MAX_FRAMES_PER_CALL:
            return [], (f"the bundle has {count} frames, more than the {MAX_FRAMES_PER_CALL} "
                        "one call returns; page with frame=N or frame=N-M")
        return list(range(count)), None
    try:
        start, _, end = frame.partition("-")
        first, last = int(start), int(end or start)
    except ValueError:
        return [], f"frame must be N, N-M or all, not {frame!r}"
    if not 0 <= first <= last < count:
        return [], f"frame {frame} is outside 0-{count - 1}"
    if last - first + 1 > MAX_FRAMES_PER_CALL:
        return [], f"one call returns at most {MAX_FRAMES_PER_CALL} frames"
    return list(range(first, last + 1)), None


def _picture(images: list[Image.Image]) -> ImageContent:
    """Frames as the panel lights them, scaled up on a pixel grid and stacked top to bottom."""
    png = io.BytesIO()
    contact_sheet(images, scale=PICTURE_SCALE, gap=PICTURE_GAP).save(png, format="PNG")
    return ImageContent(type="image", data=base64.b64encode(png.getvalue()).decode("ascii"),
                        mimeType="image/png")


def _shown(payload: dict[str, Any], images: list[Image.Image]) -> dict[str, Any] | CallToolResult:
    """A result as JSON, followed by a picture of its frames when there are any."""
    if not images:
        return payload
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False)),
            _picture(images),
        ],
        structuredContent=payload,
    )


def _rendered(
    noun: str, bundle: FrameBundle, frame: str, style: str, picture: bool
) -> dict[str, Any] | CallToolResult:
    indexes, problem = _frames(bundle, frame)
    if problem:
        return _usage("render", noun, problem)
    images = bundle.to_images()
    payload = {
        "noun": noun,
        "width": bundle.width,
        "height": bundle.height,
        "frame_count": len(bundle.frames),
        "duration_ms": sum(bundle.frame_durations_ms),
        "loop_mode": bundle.loop_mode,
        "frames": [
            {
                "index": i,
                "duration_ms": bundle.frame_durations_ms[i],
                "text": text_preview(images[i], style=style),
            }
            for i in indexes
        ],
    }
    return _shown(payload, [images[i] for i in indexes] if picture else [])


def _compile(
    verb: str,
    noun: str,
    profile: DeviceProfile,
    *,
    value: str = "",
    path: str = "",
    scroll: bool = False,
    foreground: str = "white",
    background: str = "black",
    fit: str = "contain",
    dither: str = "",
    key_color: str = "",
    frame_ms: int = 200,
    scene: Mapping[str, Any] | None = None,
) -> FrameBundle | CallToolResult:
    """The bundle a noun's content compiles to: what render shows and plan sends."""
    dither = dither or ("ordered" if noun == "animation" else "none")
    studio = PixelAnimationStudio(profile.width, profile.height)
    budget = _frame_budget(profile)
    try:
        if noun == "text":
            if not value:
                return _usage(verb, noun, "needs value")
            return studio.create_text_bundle(
                value,
                scroll=scroll,
                foreground=foreground,
                background=background,
                max_frames=budget if scroll else None,
            )
        if noun == "draw":
            if not value.strip():
                return _usage(verb, noun, "needs value, the frames drawn as text")
            if frame_ms <= 0:
                return _usage(verb, noun, "frame_ms must be positive")
            return compile_drawing(value, profile.width, profile.height, foreground=foreground,
                                   frame_ms=frame_ms, max_frames=_frame_budget(profile))
        if noun == "scene":
            if not isinstance(scene, Mapping) or not scene:
                return _usage(verb, noun, "needs scene: its sprites and where to place them")
            if frame_ms <= 0:
                return _usage(verb, noun, "frame_ms must be positive")
            return compile_scene(scene, profile.width, profile.height, frame_ms=frame_ms,
                                 max_frames=_frame_budget(profile))
        if noun == "pattern":
            if value not in PATTERNS:
                return _usage(verb, noun, f"value must be one of {', '.join(PATTERNS)}")
            return {
                "test": studio.create_test_pattern_bundle,
                "checker": studio.create_checker_bundle,
                "two-frame": studio.create_two_frame_bundle,
            }[value]()
        if not path:
            return _usage(verb, noun, "needs path")
        if not Path(path).is_absolute():
            return _usage(verb, noun, f"path must be absolute, not {path!r}")
        if not Path(path).exists():
            return _fail({"error": f"File not found: {path}"})
        if noun == "bundle":
            return FrameBundle.load(path)
        if fit not in FIT_MODES:
            return _usage(verb, noun, f"fit must be one of {', '.join(FIT_MODES)}")
        if dither not in DITHERS:
            return _usage(verb, noun, f"dither must be one of {', '.join(DITHERS)}")
        if noun == "image":
            return studio.create_image_bundle(path, fit_mode=FIT_MODES[fit], dither=dither)
        if scroll:
            return studio.create_scrolling_gif_bundle(
                path,
                max_frames=budget,
                background=background,
                dither=dither,
                key_color=key_color or None,
            )
        return studio.create_gif_bundle(
            path,
            max_frames=budget,
            fit_mode=FIT_MODES[fit],
            background=background,
            dither=dither,
            key_color=key_color or None,
        )
    except (ValueError, OSError) as exc:
        return _fail({"error": f"{verb} {noun}: {exc}"})


@mcp.tool(annotations=READ_ONLY)
def describe(
    noun: Annotated[str, _noun("describe", "What to describe; omit to list the nouns.")] = "",
) -> dict[str, Any]:
    """CoolLED panel: read the panel this server renders for, the text legend,
    or the last upload. Call with no noun for the list of nouns."""
    if not noun:
        return _listing("describe")
    if noun not in NOUNS["describe"]:
        return _unknown("describe", noun)
    if noun == "legend":
        names = ("black", "red", "green", "blue", "cyan", "magenta", "yellow", "white")
        return {
            "noun": noun,
            "color": {char: name for char, name in zip(TEXT_LEGEND.values(), names, strict=True)},
            "mono": {".": "off", "#": "lit, any colour"},
            "auto": "mono when a frame lights at most one colour, color otherwise",
            "draw": "reads the same characters, either case; '#' lights its foreground",
            "scene": "sprites use them too, but '.' is transparent and any other letter "
                     "takes the colour its placement gives it",
        }
    if noun == "upload":
        if _upload is None:
            return {"noun": noun, "state": "idle",
                    "note": "nothing has been accepted since this server started"}
        return {"noun": noun, **_upload.report()}
    profile = _profile()
    return {
        "noun": noun,
        "panel_id": profile.panel_id,
        "advertised_name": profile.advertised_name,
        "width": profile.width,
        "height": profile.height,
        "colors": 8,
        "capabilities": profile.get("capabilities", {}),
        "accept_sends": _execute,
    }


@mcp.tool(annotations=READ_ONLY)
def render(
    noun: Annotated[str, _noun("render", "What to render; omit to list the nouns.")] = "",
    value: Value = "",
    path: FilePath = "",
    scroll: Annotated[bool, Field(description="text or animation: scroll across the panel host-side instead of showing in place.")] = False,
    foreground: Foreground = "white",
    background: Background = "black",
    fit: Fit = "contain",
    dither: Dither = "",
    key_color: KeyColor = "",
    frame_ms: FrameMs = 200,
    scene: Scene = None,
    frame: Annotated[str, Field(description=f"Which frames: N, N-M or all; omit for the first {MAX_FRAMES_PER_CALL}.")] = "",
    style: Annotated[str, Field(description="auto, color (a letter per colour) or mono (# for lit).")] = "auto",
    picture: Annotated[bool, Field(description="Also return the frames as one picture, scaled up on a pixel grid and stacked top to bottom; turn off for a client that cannot show images.")] = True,
) -> dict[str, Any]:
    """CoolLED panel: compile content exactly as the panel would show it and
    return each frame as text, one character per pixel, and as a picture.
    Never sends to the panel. Call with no noun for the list of nouns and
    their arguments."""
    if not noun:
        return _listing("render")
    if noun not in NOUNS["render"]:
        return _unknown("render", noun)
    if style not in TEXT_STYLES:
        return _usage("render", noun, f"style must be one of {', '.join(TEXT_STYLES)}")
    bundle = _compile(
        "render",
        noun,
        _profile(),
        value=value,
        path=path,
        scroll=scroll,
        foreground=foreground,
        background=background,
        fit=fit,
        dither=dither,
        key_color=key_color,
        frame_ms=frame_ms,
        scene=scene,
    )
    if isinstance(bundle, CallToolResult):
        return bundle
    return _rendered(noun, bundle, frame, style, picture)


@dataclass(slots=True)
class _Prepared:
    """A plan's content compiled for the panel: what it shows and how it is delivered."""

    arguments: dict[str, Any]
    profile: DeviceProfile
    headline: str
    preview: dict[str, Any]
    images: list[Image.Image]
    deliver: Callable[[bool, ProgressCallback | None], Awaitable[dict[str, Any]]]
    warnings: list[str] = field(default_factory=list)


def _arguments(noun: str, given: Mapping[str, Any]) -> dict[str, Any] | CallToolResult:
    """A plan's arguments: its noun and every setting that noun reads, defaults filled in."""
    if noun not in PLANS:
        return _unknown("plan", noun)
    names = PLANS[noun][0]
    extra = sorted(set(given) - set(names))
    if extra:
        return _usage("plan", noun, f"does not take {', '.join(extra)}")
    arguments: dict[str, Any] = {"noun": noun}
    for name in names:
        value = given.get(name, PLAN_DEFAULTS[name])
        kind = type(PLAN_DEFAULTS[name])
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            return _usage("plan", noun, f"{name} must be a {kind.__name__}, not {value!r}")
        arguments[name] = value
    return arguments


def _still_text_width(text: str, profile: DeviceProfile, foreground: str, background: str) -> int:
    """How wide a static text frame's lettering is before the panel's edges cut it off."""
    probe = render_static_text(
        text,
        max(profile.width, 16 * len(text)),
        profile.height,
        foreground=foreground,
        background=background,
    )
    blank = Image.new("RGB", probe.size, parse_color(background))
    box = ImageChops.difference(probe, blank).getbbox()
    return 0 if box is None else box[2] - box[0]


def _bundle_preview(bundle: FrameBundle) -> dict[str, Any]:
    first = Image.frombytes("RGB", (bundle.width, bundle.height), bundle.frames[0])
    return {
        "width": bundle.width,
        "height": bundle.height,
        "frame_count": len(bundle.frames),
        "duration_ms": sum(bundle.frame_durations_ms),
        "first_frame": text_preview(first),
    }


def _banner_preview(banner: Image.Image) -> dict[str, Any]:
    """The banner the panel's firmware scrolls, as text, cut to MAX_BANNER_PREVIEW columns."""
    shown = banner.crop((0, 0, min(banner.width, MAX_BANNER_PREVIEW), banner.height))
    preview: dict[str, Any] = {
        "width": banner.width,
        "height": banner.height,
        "banner": text_preview(shown),
    }
    if shown.width < banner.width:
        preview["banner_shown"] = f"the first {shown.width} of {banner.width} columns"
    return preview


def _prepare(arguments: dict[str, Any]) -> _Prepared | CallToolResult:
    """Compile a plan's content for the configured panel."""
    noun = arguments["noun"]
    profile = _profile()
    runtime = ProtocolRuntime(profile)
    panel = profile.panel_id
    if noun == "text" and arguments["scroll"]:
        text, speed = arguments["value"], arguments["speed"]
        if not text:
            return _usage("plan", noun, "needs value")
        if not USER_SCROLL_SPEED_MIN <= speed <= USER_SCROLL_SPEED_MAX:
            return _usage("plan", noun,
                          f"speed must be {USER_SCROLL_SPEED_MIN}-{USER_SCROLL_SPEED_MAX}")
        try:
            banner = render_wide_text(
                text,
                profile.height,
                foreground=arguments["foreground"],
                background=arguments["background"],
            )
        except ValueError as exc:
            return _fail({"error": f"plan {noun}: {exc}"})

        def deliver_banner(execute: bool, progress: ProgressCallback | None):
            return runtime.play_native_text(
                text,
                banner.tobytes(),
                banner.width,
                speed=speed,
                mode=MODE_LEFT,
                execute=execute,
                progress=progress,
            )

        return _Prepared(
            arguments=arguments,
            profile=profile,
            headline=f"Scroll {text!r} on {panel} with the panel's own scroll at speed {speed}",
            preview=_banner_preview(banner),
            images=[banner.crop((0, 0, min(banner.width, MAX_BANNER_PREVIEW), banner.height))],
            deliver=deliver_banner,
        )

    settings = {name: value for name, value in arguments.items() if name not in ("noun", "speed")}
    bundle = _compile("plan", noun, profile, **settings)
    if isinstance(bundle, CallToolResult):
        return bundle

    def deliver_bundle(execute: bool, progress: ProgressCallback | None):
        return runtime.upload_frame_bundle(bundle, execute=execute, progress=progress)

    subject = {
        "text": repr(arguments.get("value")),
        "draw": "the drawing",
        "scene": "the scene",
        "pattern": f"the {arguments.get('value')} pattern",
    }.get(noun) or Path(arguments["path"]).name
    count = len(bundle.frames)
    headline = (
        f"Show {subject} on {panel} as a still"
        if count == 1
        else f"Play {subject} on {panel}, {count} frames in a "
             f"{sum(bundle.frame_durations_ms)} ms loop"
    )
    warnings = []
    if noun == "text":
        width = _still_text_width(
            arguments["value"], profile, arguments["foreground"], arguments["background"]
        )
        if width > profile.width:
            warnings.append(f"the text is {width} pixels wide but the panel is {profile.width}, "
                            "so a still cuts it off; scroll=true scrolls it instead")
    return _Prepared(
        arguments=arguments,
        profile=profile,
        headline=headline,
        preview=_bundle_preview(bundle),
        images=bundle.to_images()[:MAX_FRAMES_PER_CALL],
        deliver=deliver_bundle,
        warnings=warnings,
    )


def _steps(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Each payload a delivery writes, in order, with its transfer once it ran."""
    if "transfers" in result:
        encoded = result["encoded"]
        return [
            {"step": sent["step"], "encoded": encoded[sent["step"]], "transfer": sent["transfer"]}
            for sent in result["transfers"]
        ]
    steps = [{"step": "frames", "encoded": result["encoded"], "transfer": result["transfer"]}]
    steps += [
        {"step": label, **after}
        for label, after in result.items()
        if label not in ("encoded", "transfer")
    ]
    return steps


def _plan_id(profile: DeviceProfile, steps: list[dict[str, Any]]) -> str:
    """Name the exact bytes a send writes and the panel it writes them to."""
    packets = [[step["step"], step["encoded"]["packets_hex"]] for step in steps]
    payload = json.dumps([profile.panel_id, profile.device_id, packets])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _seconds_per_packet(profile: DeviceProfile) -> float | None:
    """The panel's steady upload rate the CLI remembers, if it has uploaded before."""
    try:
        rates = json.loads(
            (default_render_cache_dir() / "upload-rates.json").read_text(encoding="utf-8")
        )
        rate = float(rates[profile.device_id])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rate if rate > 0 else None


def _step_summary(step: dict[str, Any]) -> dict[str, Any]:
    meta = step["encoded"].get("metadata", {})
    summary: dict[str, Any] = {"step": step["step"], "packets": step["encoded"]["packet_count"]}
    if isinstance(meta.get("opcode"), int):
        summary["opcode"] = f"0x{meta['opcode']:02x}"
    if meta.get("frame_count"):
        summary["frames"] = meta["frame_count"]
    if meta.get("payload_bytes"):
        summary["payload_bytes"] = meta["payload_bytes"]
    if "command" in meta:
        summary["command"] = f"{meta['command']} {meta.get('value_encoded')}"
    return summary


def _transfer(profile: DeviceProfile, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """What a send writes, step by step, and about how long its packets take."""
    packets = sum(step["encoded"]["packet_count"] for step in steps)
    rate = _seconds_per_packet(profile)
    return {
        "steps": [_step_summary(step) for step in steps],
        "packets": packets,
        "bytes": sum(step["encoded"]["total_bytes"] for step in steps),
        "estimated_upload_seconds": max(1, round(packets * rate)) if rate else None,
    }


_plans: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _remember(plan_id: str, arguments: dict[str, Any]) -> None:
    """Keep a plan's arguments so accept can find them from its plan_id alone."""
    _plans[plan_id] = arguments
    _plans.move_to_end(plan_id)
    while len(_plans) > MAX_REMEMBERED_PLANS:
        _plans.popitem(last=False)


async def _planned(prepared: _Prepared) -> dict[str, Any]:
    """The plan for prepared content: a dry run of its delivery, named by plan_id."""
    blockers = [] if _execute else [READ_ONLY_BLOCKER]
    try:
        steps = _steps(await prepared.deliver(False, None))
    except CodecError as exc:
        steps = []
        blockers.insert(0, f"the profile cannot encode this: {exc}")
    plan_id = _plan_id(prepared.profile, steps) if steps else None
    if plan_id:
        _remember(plan_id, prepared.arguments)
    transfer = _transfer(prepared.profile, steps) if steps else None
    summary = prepared.headline
    if transfer:
        summary += f": {transfer['packets']} packets"
        if transfer["estimated_upload_seconds"]:
            summary += f", about {transfer['estimated_upload_seconds']} s to upload"
    return {
        "verb": "plan",
        "noun": prepared.arguments["noun"],
        "summary": summary,
        "blockers": blockers,
        "warnings": prepared.warnings,
        "preview": prepared.preview,
        "transfer": transfer,
        "plan_id": plan_id,
        "next": None if blockers else {"verb": "accept", "arguments": {"plan_id": plan_id}},
    }


@mcp.tool(annotations=READ_ONLY)
async def plan(
    noun: Annotated[str, _noun("plan", "What to send; omit to list the nouns.")] = "",
    value: Value = "",
    path: FilePath = "",
    scroll: Annotated[bool, Field(description="text: scroll it with the panel's own firmware scroll. animation: travel across the panel host-side.")] = False,
    speed: Annotated[int, Field(description=f"text with scroll: {USER_SCROLL_SPEED_MIN}-{USER_SCROLL_SPEED_MAX}, higher is faster.")] = 8,
    foreground: Foreground = "white",
    background: Background = "black",
    fit: Fit = "contain",
    dither: Dither = "",
    key_color: KeyColor = "",
    frame_ms: FrameMs = 200,
    scene: Scene = None,
    picture: Annotated[bool, Field(description="Also return what the panel would show as a picture; turn off for a client that cannot show images.")] = True,
) -> dict[str, Any]:
    """CoolLED panel: compile content into the exact packets a send would write,
    without sending. Returns what the panel would show (as a picture and as
    text), the transfer, any blockers and warnings, and a plan_id; next holds
    the accept call that sends it. Call with no noun for the list of nouns and
    their arguments."""
    if not noun:
        return _listing("plan")
    if noun not in PLANS:
        return _unknown("plan", noun)
    settings = {
        "value": value,
        "path": path,
        "scroll": scroll,
        "speed": speed,
        "foreground": foreground,
        "background": background,
        "fit": fit,
        "dither": dither,
        "key_color": key_color,
        "frame_ms": frame_ms,
        "scene": scene or {},
    }
    arguments = _arguments(noun, {name: settings[name] for name in PLANS[noun][0]})
    if isinstance(arguments, CallToolResult):
        return arguments
    prepared = _prepare(arguments)
    if isinstance(prepared, CallToolResult):
        return prepared
    return _shown(await _planned(prepared), prepared.images if picture else [])


@dataclass(slots=True)
class _Upload:
    """One accepted plan on its way to the panel."""

    plan_id: str
    summary: str
    started: float = field(default_factory=time.monotonic)
    delivered: int = 0
    total: int = 0
    finished: float | None = None
    outcome: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = None

    def progress(self, delivered: int, total: int) -> None:
        self.delivered, self.total = delivered, total

    def report(self) -> dict[str, Any]:
        elapsed = (self.finished or time.monotonic()) - self.started
        report = {"plan_id": self.plan_id, "summary": self.summary, "seconds": round(elapsed, 1)}
        if self.outcome is None:
            return {"state": "uploading", **report,
                    "packets_delivered": self.delivered, "packets_total": self.total}
        return {**self.outcome, **report}


_upload: _Upload | None = None


def _sent(step: dict[str, Any]) -> dict[str, Any]:
    """How one step of a real send went."""
    transfer = step["transfer"]
    if transfer is None:
        return {"step": step["step"], "success": False,
                "note": "not sent: the upload before it did not finish"}
    return {
        "step": step["step"],
        "success": transfer["success"],
        "packets": transfer["packet_count"],
        "acks": transfer["acks_received"],
        "ack_timeouts": transfer["ack_timeouts"],
        "errors": transfer["errors"],
    }


async def _send(upload: _Upload, prepared: _Prepared) -> None:
    """Deliver an accepted plan, keeping how it ended for describe upload."""
    try:
        steps = [_sent(step) for step in _steps(await prepared.deliver(True, upload.progress))]
        state = "sent" if all(step["success"] for step in steps) else "failed"
        upload.outcome = {"state": state, "steps": steps}
    except Exception as exc:  # an upload left running in the background has no caller to raise to
        upload.outcome = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        upload.finished = time.monotonic()


@mcp.tool(annotations=SENDS)
async def accept(
    plan_id: Annotated[str, Field(description="The plan_id a plan returned.")] = "",
    arguments: Annotated[dict[str, Any] | None, Field(description=f"Only for a plan this server no longer remembers (it keeps the last {MAX_REMEMBERED_PLANS} and forgets them on restart): the plan's noun and settings.")] = None,
) -> dict[str, Any]:
    """CoolLED panel: send a plan to the panel. Pass the plan_id from a plan's
    next: accept plans the same content again and refuses if the packets
    differ from the ones plan_id names, or if the server was started without
    --execute. A long upload carries on in the background, and describe upload
    follows it. Call with no arguments for this usage."""
    global _upload
    if not plan_id:
        if arguments:
            return _fail({"error": "accept needs the plan_id that plan returned", **ACCEPT_USAGE})
        return dict(ACCEPT_USAGE)
    if not _execute:
        return _fail({"error": READ_ONLY_BLOCKER})
    if arguments is None:
        arguments = _plans.get(plan_id)
        if arguments is None:
            return _fail({"error": f"this server has no plan {plan_id}: it keeps the last "
                                   f"{MAX_REMEMBERED_PLANS} and forgets them on restart, so plan again"})
    given = dict(arguments)
    planned_arguments = _arguments(str(given.pop("noun", "")), given)
    if isinstance(planned_arguments, CallToolResult):
        return planned_arguments
    prepared = _prepare(planned_arguments)
    if isinstance(prepared, CallToolResult):
        return prepared
    planned = await _planned(prepared)
    if planned["blockers"]:
        return _fail({"error": "the plan is blocked", "blockers": planned["blockers"]})
    if planned["plan_id"] != plan_id:
        return _fail({
            "error": f"these arguments now plan {planned['plan_id']}, not {plan_id}: something "
                     "changed since that plan, so review this one before accepting it",
            "plan": planned,
        })
    if _upload is not None and _upload.outcome is None:
        return _fail({"error": "another upload is still running; describe upload follows it",
                      "upload": _upload.report()})
    upload = _Upload(plan_id=plan_id, summary=planned["summary"])
    upload.task = asyncio.create_task(_send(upload, prepared))
    _upload = upload
    try:
        await asyncio.wait_for(asyncio.shield(upload.task), ACCEPT_WAIT_SECONDS)
    except TimeoutError:
        pass
    report = upload.report()
    if upload.outcome is None:
        return {**report, "next": {"verb": "describe", "arguments": {"noun": "upload"}}}
    return _fail(report) if report["state"] == "failed" else report


def main() -> None:
    global _profile_path, _execute
    parser = argparse.ArgumentParser(
        description="coolled-verbs: an MCP surface that renders for the panel and, "
        "with --execute, sends to it."
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Let accept send planned uploads to the panel over BLE; "
        "without it the server only renders and plans.",
    )
    args = parser.parse_args()
    _profile_path, _execute = args.profile, args.execute
    mcp.run()


if __name__ == "__main__":
    main()
