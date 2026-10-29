from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from opensign.animation.preview import text_preview

pytest.importorskip("mcp.server.fastmcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from mcp.types import CallToolResult  # noqa: E402

from opensign.animation.studio import PixelAnimationStudio  # noqa: E402
from opensign.sdk import verbs_mcp as verbs  # noqa: E402

STARTER = Path(__file__).resolve().parents[1] / "device_profile.json"


@pytest.fixture(autouse=True)
def starter_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verbs, "_profile_path", STARTER)


def tool(name: str):
    fn = getattr(verbs, name)
    return getattr(fn, "fn", fn)


def error(result) -> dict:
    assert isinstance(result, CallToolResult) and result.isError, result
    return result.structuredContent


def test_text_preview_styles() -> None:
    image = Image.new("RGB", (3, 2))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((2, 1), (200, 200, 200))
    assert text_preview(image, style="color") == "R..\n..W"
    assert text_preview(image, style="mono") == "#..\n..#"
    assert text_preview(image) == "R..\n..W"
    image.putpixel((0, 0), (255, 255, 255))
    assert text_preview(image) == "#..\n..#"
    with pytest.raises(ValueError):
        text_preview(image, style="ansi")


def test_verbs_with_no_noun_list_their_nouns() -> None:
    assert [n["noun"] for n in tool("describe")()["nouns"]] == ["panel", "legend"]
    assert [n["noun"] for n in tool("render")()["nouns"]] == ["text", "pattern", "image", "bundle"]
    assert "nouns" in error(tool("render")(noun="video"))


def test_describe_panel_reads_the_profile() -> None:
    panel = tool("describe")(noun="panel")
    assert (panel["width"], panel["height"]) == (64, 16)
    assert set(tool("describe")(noun="legend")["color"]) == set(".RGBCMYW")


def test_render_text_matches_the_compiled_bundle() -> None:
    out = tool("render")(noun="text", value="HELLO")
    assert (out["width"], out["height"], out["frame_count"]) == (64, 16, 1)
    rows = out["frames"][0]["text"].splitlines()
    assert len(rows) == 16 and all(len(row) == 64 for row in rows)
    expected = PixelAnimationStudio(64, 16).create_text_bundle("HELLO", scroll=False)
    assert out["frames"][0]["text"] == text_preview(expected.to_images()[0])


def test_render_pages_long_scrolls() -> None:
    out = tool("render")(noun="text", value="HI", scroll=True)
    assert out["frame_count"] > verbs.MAX_FRAMES_PER_CALL
    assert len(out["frames"]) == verbs.MAX_FRAMES_PER_CALL
    page = tool("render")(noun="text", value="HI", scroll=True, frame="10-12")
    assert [f["index"] for f in page["frames"]] == [10, 11, 12]
    assert "page" in error(tool("render")(noun="text", value="HI", scroll=True, frame="all"))["error"]
    assert "outside" in error(tool("render")(noun="text", value="HI", frame="3"))["error"]


def test_render_pattern_and_usage_errors() -> None:
    out = tool("render")(noun="pattern", value="test", style="color")
    assert out["frames"][0]["text"].splitlines()[1].startswith("WRRR")
    assert "usage" in error(tool("render")(noun="pattern", value="plasma"))
    assert "usage" in error(tool("render")(noun="text"))
    assert "absolute" in error(tool("render")(noun="image", path="logo.png"))["error"]


def test_render_image_and_bundle_from_paths(tmp_path: Path) -> None:
    source = tmp_path / "red.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(source)
    out = tool("render")(noun="image", path=str(source), fit="stretch")
    assert set(out["frames"][0]["text"]) == {"#", "\n"}

    bundle = PixelAnimationStudio(64, 16).create_two_frame_bundle()
    saved = bundle.save(tmp_path / "two.json")
    out = tool("render")(noun="bundle", path=str(saved), frame="all")
    assert [f["index"] for f in out["frames"]] == [0, 1]
    assert "not found" in error(tool("render")(noun="bundle", path=str(tmp_path / "x.json")))["error"]


def test_render_over_mcp() -> None:
    async def call():
        async with create_connected_server_and_client_session(verbs.mcp._mcp_server) as client:
            tools = await client.list_tools()
            result = await client.call_tool("render", {"noun": "text", "value": "OK"})
            return tools, result

    tools, result = asyncio.run(call())
    assert {t.name for t in tools.tools} == {"describe", "render"}
    assert all(t.annotations.readOnlyHint for t in tools.tools)
    assert not result.isError
    assert "#" in result.structuredContent["frames"][0]["text"]
