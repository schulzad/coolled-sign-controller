"""
coolled-verbs: a read-only MCP render surface for the panel, as verbs that take nouns.

Modelled on smdl-factory's smdl-verbs spike: a verb called with no noun returns
its nouns, failures come back flagged isError with the usage, and every path
must be absolute. describe reads the panel; render compiles content through the
same PixelAnimationStudio the CLI and API use and returns each frame as text,
one character per pixel. Nothing here encodes, connects or writes: the panel
never lights from this server.

Run:
    opensign-verbs --profile device_profile.local.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from opensign.animation.preview import TEXT_LEGEND, TEXT_STYLES, text_preview
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, FrameBundle

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

# The most frames one render returns as text; a longer clip is paged with frame.
MAX_FRAMES_PER_CALL = 8

DEFAULT_PROFILE = Path("device_profile.local.json")
STARTER_PROFILE = Path("device_profile.json")

logging.getLogger("mcp").setLevel(logging.ERROR)

mcp = FastMCP(
    "coolled-verbs",
    instructions=(
        "A read-only render surface for a CoolLEDX LED panel. Call a verb with no noun "
        "to see its nouns and their arguments. describe panel gives the geometry and "
        "colours; render compiles text, a pattern, an image or a frame bundle exactly as "
        "the panel would show it and returns each frame as text, one character per "
        "pixel: '.' is off, and either '#' marks a lit pixel (mono) or a letter names "
        "its colour (describe legend). Nothing is sent to the panel. Every path must be "
        "absolute."
    ),
)

# verb -> noun -> (arguments, what it returns)
NOUNS: dict[str, dict[str, tuple[str, str]]] = {
    "describe": {
        "panel": ("", "the panel's id, geometry, colour mode and capability statuses"),
        "legend": ("", "the character each panel colour renders as"),
    },
    "render": {
        "text": ("value [scroll] [foreground] [background] [frame] [style]",
                 "text as the panel shows it, static or as a host-side scroll"),
        "pattern": ("value [frame] [style]", "a built-in pattern: test, checker or two-frame"),
        "image": ("path [fit] [dither] [style]", "an image fitted and quantized to the panel"),
        "bundle": ("path [frame] [style]", "a saved frame bundle (.json)"),
    },
}

PATTERNS = ("test", "checker", "two-frame")
FITS = ("contain", "cover", "stretch")
DITHERS = ("none", "ordered", "floyd")


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


def _profile() -> DeviceProfile:
    """The configured profile, read on each call so a re-profiled panel shows up;
    the checked-in starter stands in when the default local profile is absent."""
    path = _profile_path
    if path == DEFAULT_PROFILE and not path.exists() and STARTER_PROFILE.exists():
        path = STARTER_PROFILE
    return DeviceProfile.load(path)


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


def _rendered(noun: str, bundle: FrameBundle, frame: str, style: str) -> dict[str, Any] | CallToolResult:
    indexes, problem = _frames(bundle, frame)
    if problem:
        return _usage("render", noun, problem)
    images = bundle.to_images()
    return {
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


@mcp.tool(annotations=READ_ONLY)
def describe(
    noun: Annotated[str, _noun("describe", "What to describe; omit to list the nouns.")] = "",
) -> dict[str, Any]:
    """CoolLED panel: read the panel this server renders for, or the text
    legend. Call with no noun for the list of nouns."""
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
        }
    profile = _profile()
    return {
        "noun": noun,
        "panel_id": profile.panel_id,
        "advertised_name": profile.advertised_name,
        "width": profile.width,
        "height": profile.height,
        "colors": 8,
        "capabilities": profile.get("capabilities", {}),
    }


@mcp.tool(annotations=READ_ONLY)
def render(
    noun: Annotated[str, _noun("render", "What to render; omit to list the nouns.")] = "",
    value: Annotated[str, Field(description="text: the message. pattern: test, checker or two-frame.")] = "",
    path: Annotated[str, Field(description="image or bundle: the file, as an absolute path.")] = "",
    scroll: Annotated[bool, Field(description="text only: a host-side scroll instead of one static frame.")] = False,
    foreground: Annotated[str, Field(description="text only: a colour name or #rrggbb.")] = "white",
    background: Annotated[str, Field(description="text only: a colour name or #rrggbb.")] = "black",
    fit: Annotated[str, Field(description="image only: contain, cover or stretch.")] = "contain",
    dither: Annotated[str, Field(description="image only: none, ordered or floyd.")] = "none",
    frame: Annotated[str, Field(description=f"Which frames: N, N-M or all; omit for the first {MAX_FRAMES_PER_CALL}.")] = "",
    style: Annotated[str, Field(description="auto, color (a letter per colour) or mono (# for lit).")] = "auto",
) -> dict[str, Any]:
    """CoolLED panel: compile content exactly as the panel would show it and
    return each frame as text, one character per pixel. Never sends to the
    panel. Call with no noun for the list of nouns and their arguments."""
    if not noun:
        return _listing("render")
    if noun not in NOUNS["render"]:
        return _unknown("render", noun)
    if style not in TEXT_STYLES:
        return _usage("render", noun, f"style must be one of {', '.join(TEXT_STYLES)}")
    profile = _profile()
    studio = PixelAnimationStudio(profile.width, profile.height)
    try:
        if noun == "text":
            if not value:
                return _usage("render", noun, "needs value")
            bundle = studio.create_text_bundle(
                value, scroll=scroll, foreground=foreground, background=background
            )
        elif noun == "pattern":
            if value not in PATTERNS:
                return _usage("render", noun, f"value must be one of {', '.join(PATTERNS)}")
            bundle = {
                "test": studio.create_test_pattern_bundle,
                "checker": studio.create_checker_bundle,
                "two-frame": studio.create_two_frame_bundle,
            }[value]()
        else:
            if not path:
                return _usage("render", noun, "needs path")
            if not Path(path).is_absolute():
                return _usage("render", noun, f"path must be absolute, not {path!r}")
            if not Path(path).exists():
                return _fail({"error": f"File not found: {path}"})
            if noun == "bundle":
                bundle = FrameBundle.load(path)
            else:
                if fit not in FITS:
                    return _usage("render", noun, f"fit must be one of {', '.join(FITS)}")
                if dither not in DITHERS:
                    return _usage("render", noun, f"dither must be one of {', '.join(DITHERS)}")
                bundle = studio.create_image_bundle(path, fit_mode=fit, dither=dither)
    except (ValueError, OSError) as exc:
        return _fail({"error": f"render {noun}: {exc}"})
    return _rendered(noun, bundle, frame, style)


def main() -> None:
    global _profile_path
    parser = argparse.ArgumentParser(description="coolled-verbs: a read-only MCP render surface.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    _profile_path = parser.parse_args().profile
    mcp.run()


if __name__ == "__main__":
    main()
