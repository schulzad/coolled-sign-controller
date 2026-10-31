from __future__ import annotations

import asyncio
import base64
import io
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from opensign.animation.preview import image_from_text, text_preview

pytest.importorskip("mcp.server.fastmcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from mcp.types import CallToolResult  # noqa: E402

from opensign.animation.studio import PixelAnimationStudio  # noqa: E402
from opensign.contracts import DeviceProfile, default_device_profile  # noqa: E402
from opensign.protocol import runtime as protocol_runtime  # noqa: E402
from opensign.protocol.transport import DryRunTransport  # noqa: E402
from opensign.sdk import verbs_mcp as verbs  # noqa: E402

STARTER = Path(__file__).resolve().parents[1] / "device_profile.json"


@pytest.fixture(autouse=True)
def starter_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verbs, "_profile_path", STARTER)
    monkeypatch.setattr(verbs, "_execute", False)
    monkeypatch.setattr(verbs, "_upload", None)
    monkeypatch.setattr(verbs, "_plans", OrderedDict())


@pytest.fixture
def panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A profiled 64x16 CoolLEDX panel, which the codec can encode for."""
    data = default_device_profile()
    data["dimensions"] = {"width": 64, "height": 16, "source": "test", "verified": True}
    data["write_characteristic"] = "0000fff1-0000-1000-8000-00805f9b34fb"
    data["notify_characteristic"] = "0000fff1-0000-1000-8000-00805f9b34fb"
    data["connection"] = {"mtu": 247, "maximum_chunk_size": 240, "inter_chunk_delay_ms": 0}
    data["protocol"] = {
        "codec": "coolledx",
        "status": "verified",
        "encryption": {"mode": "none"},
        "frame_transfer": {
            "status": "verified",
            "mode": "coolledx_bitplanes",
            "input_color_mode": "rgb888",
            "chunk_ack": {"requires_per_chunk_wait": True, "timeout_seconds": 0.1},
        },
    }
    path = tmp_path / "panel.json"
    DeviceProfile(data).save(path)
    monkeypatch.setattr(verbs, "_profile_path", path)
    return path


@pytest.fixture
def radio(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Stand in for BLE: a real send's packets are recorded, after an optional delay."""
    log = SimpleNamespace(written=[], delay=0.0)

    class Radio(DryRunTransport):
        def __init__(self, profile: DeviceProfile, *, timeout_seconds: float = 15.0) -> None:
            super().__init__(profile)

        async def send_packets(self, packets, **options):
            await asyncio.sleep(log.delay)
            packets = [bytes(packet) for packet in packets]
            log.written.extend(packets)
            result = await super().send_packets(packets, **options)
            result.dry_run = False
            return result

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr(protocol_runtime, "BleakTransport", Radio)
    return log


def tool(name: str):
    fn = getattr(verbs, name)
    return getattr(fn, "fn", fn)


def error(result) -> dict:
    assert isinstance(result, CallToolResult) and result.isError, result
    return result.structuredContent


def shown(result) -> dict:
    """A successful result's JSON, whether or not a picture came with it."""
    if isinstance(result, CallToolResult):
        assert not result.isError, result
        return result.structuredContent
    return result


def render(**arguments) -> dict:
    return shown(tool("render")(**arguments))


def plan(**arguments) -> dict:
    return shown(asyncio.run(tool("plan")(**arguments)))


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
    assert [n["noun"] for n in tool("describe")()["nouns"]] == ["panel", "legend", "upload"]
    content = ["text", "draw", "scene", "pattern", "image", "animation", "bundle"]
    assert [n["noun"] for n in render()["nouns"]] == content
    assert [n["noun"] for n in plan()["nouns"]] == content
    assert asyncio.run(tool("accept")())["args"] == "plan_id [arguments]"
    assert "nouns" in error(tool("render")(noun="video"))
    assert "nouns" in error(asyncio.run(tool("plan")(noun="video")))


def test_describe_panel_reads_the_profile() -> None:
    panel = tool("describe")(noun="panel")
    assert (panel["width"], panel["height"]) == (64, 16)
    assert set(tool("describe")(noun="legend")["color"]) == set(".RGBCMYW")


def test_render_text_matches_the_compiled_bundle() -> None:
    out = render(noun="text", value="HELLO")
    assert (out["width"], out["height"], out["frame_count"]) == (64, 16, 1)
    rows = out["frames"][0]["text"].splitlines()
    assert len(rows) == 16 and all(len(row) == 64 for row in rows)
    expected = PixelAnimationStudio(64, 16).create_text_bundle("HELLO", scroll=False)
    assert out["frames"][0]["text"] == text_preview(expected.to_images()[0])


def test_render_pages_long_scrolls() -> None:
    out = render(noun="text", value="HI", scroll=True)
    assert out["frame_count"] > verbs.MAX_FRAMES_PER_CALL
    assert len(out["frames"]) == verbs.MAX_FRAMES_PER_CALL
    page = render(noun="text", value="HI", scroll=True, frame="10-12")
    assert [f["index"] for f in page["frames"]] == [10, 11, 12]
    assert "page" in error(tool("render")(noun="text", value="HI", scroll=True, frame="all"))["error"]
    assert "outside" in error(tool("render")(noun="text", value="HI", frame="3"))["error"]


def test_render_pattern_and_usage_errors() -> None:
    out = render(noun="pattern", value="test", style="color")
    assert out["frames"][0]["text"].splitlines()[1].startswith("WRRR")
    assert "usage" in error(tool("render")(noun="pattern", value="plasma"))
    assert "usage" in error(tool("render")(noun="text"))
    assert "absolute" in error(tool("render")(noun="image", path="logo.png"))["error"]


def test_render_image_and_bundle_from_paths(tmp_path: Path) -> None:
    source = tmp_path / "red.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(source)
    out = render(noun="image", path=str(source), fit="stretch")
    assert set(out["frames"][0]["text"]) == {"#", "\n"}

    bundle = PixelAnimationStudio(64, 16).create_two_frame_bundle()
    saved = bundle.save(tmp_path / "two.json")
    out = render(noun="bundle", path=str(saved), frame="all")
    assert [f["index"] for f in out["frames"]] == [0, 1]
    assert "not found" in error(tool("render")(noun="bundle", path=str(tmp_path / "x.json")))["error"]


def _clip(path: Path, frames: int) -> Path:
    images = []
    for i in range(frames):
        image = Image.new("RGB", (16, 8))
        image.putpixel((i % 16, 0), (255, 255, 255))
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
    return path


def test_render_animation_in_place_and_scrolling(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "clip.gif", frames=4)
    out = render(noun="animation", path=str(clip), frame="all")
    assert (out["width"], out["height"], out["frame_count"]) == (64, 16, 4)
    scrolled = render(noun="animation", path=str(clip), scroll=True)
    assert 4 < scrolled["frame_count"] <= verbs._frame_budget(verbs._profile())
    assert "absolute" in error(tool("render")(noun="animation", path="clip.gif"))["error"]


def test_render_trims_scrolls_and_animations_to_the_frame_budget(tmp_path: Path) -> None:
    budget = verbs._frame_budget(verbs._profile())
    assert budget == 79  # the 30 KiB 0x04 payload limit, header included, at 64x16
    long_clip = _clip(tmp_path / "long.gif", frames=120)
    assert render(noun="animation", path=str(long_clip))["frame_count"] == budget
    message = "A MESSAGE FAR TOO LONG TO SCROLL WITHIN ONE UPLOAD"
    assert render(noun="text", value=message, scroll=True)["frame_count"] == budget


def test_render_fit_takes_the_cli_name_fill(tmp_path: Path) -> None:
    source = tmp_path / "red.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(source)
    fill = render(noun="image", path=str(source), fit="fill")
    stretch = render(noun="image", path=str(source), fit="stretch")
    assert fill["frames"] == stretch["frames"]
    assert "usage" in error(tool("render")(noun="image", path=str(source), fit="zoom"))


def test_render_over_mcp() -> None:
    async def call():
        async with create_connected_server_and_client_session(verbs.mcp._mcp_server) as client:
            tools = await client.list_tools()
            result = await client.call_tool("render", {"noun": "text", "value": "OK"})
            return tools, result

    tools, result = asyncio.run(call())
    read_only = {t.name: t.annotations.readOnlyHint for t in tools.tools}
    assert read_only == {"describe": True, "render": True, "plan": True, "accept": False}
    assert not result.isError
    assert "#" in result.structuredContent["frames"][0]["text"]


def test_image_from_text_reads_back_what_text_preview_writes() -> None:
    grid = "R.G\n.BW\nCMY"
    assert text_preview(image_from_text(grid), style="color") == grid
    drawn = image_from_text("  r#.  \n  ..#  ", foreground=(0, 0, 255))
    assert (drawn.size, drawn.getpixel((0, 0)), drawn.getpixel((1, 0))) == (
        (3, 2), (255, 0, 0), (0, 0, 255)
    )
    with pytest.raises(ValueError, match="row 2 is 2 wide"):
        image_from_text("RGB\nRG")
    with pytest.raises(ValueError, match="row 1, column 2"):
        image_from_text("R?B")


def test_render_draw_centres_each_frame_on_the_panel() -> None:
    out = render(noun="draw", value="R.\n.R\n\nG.\n.G", frame="all", style="color")
    assert (out["frame_count"], out["duration_ms"]) == (2, 400)
    rows = out["frames"][0]["text"].splitlines()
    assert (len(rows), len(rows[0])) == (16, 64)
    assert (rows[7][31:33], rows[8][31:33]) == ("R.", ".R")
    assert out["frames"][1]["text"].count("G") == 2


def test_render_shows_its_frames_as_a_picture() -> None:
    result = tool("render")(noun="draw", value="R\n\nG", frame="all")
    picture = result.content[1]
    assert picture.mimeType == "image/png"
    sheet = Image.open(io.BytesIO(base64.b64decode(picture.data)))
    scale, gap = verbs.PICTURE_SCALE, verbs.PICTURE_GAP
    assert sheet.size == (64 * scale, 2 * 16 * scale + gap)
    x, y = 31 * scale + scale // 2, 7 * scale + scale // 2
    assert sheet.getpixel((x, y)) == (255, 0, 0)
    assert sheet.getpixel((x, 16 * scale + gap + y)) == (0, 255, 0)
    assert isinstance(tool("render")(noun="draw", value="R", picture=False), dict)


def test_render_draw_says_what_is_wrong_with_a_drawing() -> None:
    assert "row 2 is 1 wide" in error(tool("render")(noun="draw", value="RR\nR"))["error"]
    assert "frame 1: row 1, column 1" in error(tool("render")(noun="draw", value="R\n\nX"))["error"]
    assert "larger than the 64x16 panel" in error(tool("render")(noun="draw", value="." * 65))["error"]
    assert "usage" in error(tool("render")(noun="draw"))


GHOST = [".XXX.", "XWXWX", "XXXXX", "X.X.X"]


def test_render_scene_places_recoloured_sprites() -> None:
    scene = {
        "sprites": {"ghost": GHOST, "bar": ["BBBBB"], "dot": ["W"]},
        "items": [
            {"sprite": "bar", "at": [0, 0]},
            {"sprite": "ghost", "at": [0, 0], "colors": {"X": "C"}},
            {"sprite": "dot", "at": [1, 3]},
            {"sprite": "ghost", "at": [10, 2], "colors": {"X": "magenta"}},
            {"sprite": "ghost", "at": [62, 14], "colors": {"x": "#ff0000"}},
        ],
    }
    rows = render(noun="scene", scene=scene, style="color")["frames"][0]["text"].splitlines()
    assert [rows[0][:5], rows[1][:5], rows[3][:5]] == ["BCCCB", "CWCWC", "CWC.C"]
    assert rows[2][10:15] == ".MMM."
    assert (rows[14][62:], rows[15][62:]) == (".R", "RW")


def test_render_scene_frames_add_to_its_items() -> None:
    scene = {
        "sprites": {"open": ["Y."], "shut": ["YY"], "dot": ["W"]},
        "items": [{"sprite": "dot", "at": [5, 0]}],
        "frames": [[{"sprite": "open", "at": [0, 0]}], [{"sprite": "shut", "at": [0, 0]}]],
    }
    out = render(noun="scene", scene=scene, frame_ms=150, frame="all", style="color")
    assert (out["frame_count"], out["duration_ms"]) == (2, 300)
    assert [frame["text"].splitlines()[0][:6] for frame in out["frames"]] == ["Y....W", "YY...W"]


def test_render_scene_says_what_is_wrong() -> None:
    def problem(scene: dict) -> str:
        return error(tool("render")(noun="scene", scene=scene))["error"]

    ghost = {"ghost": GHOST}
    assert "needs scene" in error(tool("render")(noun="scene"))["error"]
    assert "needs sprites" in problem({"items": []})
    assert "sprite 'ghost': row 2 is 4 wide" in problem({"sprites": {"ghost": [".XXX.", "XWXW"]}})
    unknown = problem({"sprites": ghost, "items": [{"sprite": "ghots"}]})
    assert "items[0]: sprite 'ghots' is not one of 'ghost'" in unknown
    assert "uses X, which needs a colour" in problem({"sprites": ghost, "items": [{"sprite": "ghost"}]})
    off_grid = {"sprite": "ghost", "at": [1.5, 0], "colors": {"X": "R"}}
    assert "at must be [x, y]" in problem({"sprites": ghost, "items": [off_grid]})
    plaid = {"sprite": "ghost", "colors": {"X": "plaid"}}
    assert "not a colour" in problem({"sprites": ghost, "items": [plaid]})
    assert "frames[1][0]" in problem({"sprites": ghost, "frames": [[], ["ghost"]]})


def test_plan_and_accept_a_scene_by_its_plan_id(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verbs, "_execute", True)
    heart = {"heart": [".R.R.", "RRRRR", ".RRR.", "..R.."]}
    scene = {"sprites": heart, "items": [{"sprite": "heart", "at": [30, 6]}]}
    result = asyncio.run(tool("plan")(noun="scene", scene=scene))
    assert result.content[1].mimeType == "image/png"
    planned = result.structuredContent
    assert planned["summary"].startswith("Show the scene on")
    sent = asyncio.run(tool("accept")(plan_id=planned["plan_id"]))
    assert sent["state"] == "sent" and radio.written


def test_describe_panel_says_whether_accept_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    assert tool("describe")(noun="panel")["accept_sends"] is False
    monkeypatch.setattr(verbs, "_execute", True)
    assert tool("describe")(noun="panel")["accept_sends"] is True
    assert tool("describe")(noun="upload")["state"] == "idle"


def test_plan_is_blocked_when_the_profile_cannot_encode() -> None:
    planned = plan(noun="text", value="HI")
    assert (planned["plan_id"], planned["next"]) == (None, None)
    assert "cannot encode" in planned["blockers"][0]


def test_plan_previews_the_send_and_names_its_packets(panel: Path) -> None:
    planned = plan(noun="text", value="HI")
    assert planned["blockers"] == [verbs.READ_ONLY_BLOCKER] and planned["next"] is None
    rendered = render(noun="text", value="HI")["frames"][0]["text"]
    assert planned["preview"]["first_frame"] == rendered
    assert [step["step"] for step in planned["transfer"]["steps"]] == ["frames", "mode"]
    assert plan(noun="text", value="HI")["plan_id"] == planned["plan_id"]
    assert plan(noun="text", value="HO")["plan_id"] != planned["plan_id"]


def test_plan_scrolls_text_with_the_panel_firmware(panel: Path) -> None:
    planned = plan(noun="text", value="HELLO WORLD", scroll=True, speed=5)
    assert [step["step"] for step in planned["transfer"]["steps"]] == ["banner", "speed", "mode"]
    assert planned["preview"]["width"] > 64
    too_fast = asyncio.run(tool("plan")(noun="text", value="HI", scroll=True, speed=11))
    assert "speed must be 0-10" in error(too_fast)["error"]


def test_plan_warns_when_a_still_cuts_text_off(panel: Path) -> None:
    assert "cuts it off" in plan(noun="text", value="HELLO WORLD")["warnings"][0]
    assert plan(noun="text", value="HI")["warnings"] == []


def test_accept_sends_exactly_the_planned_packets(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verbs, "_execute", True)
    planned = plan(noun="draw", value="R.R\n.G.\nB.B")
    assert planned["blockers"] == []
    assert planned["next"]["arguments"] == {"plan_id": planned["plan_id"]}
    sent = asyncio.run(tool("accept")(**planned["next"]["arguments"]))
    assert sent["state"] == "sent" and [step["step"] for step in sent["steps"]] == ["frames", "mode"]
    dry = asyncio.run(verbs._prepare(verbs._plans[planned["plan_id"]]).deliver(False, None))
    assert radio.written == [
        bytes.fromhex(packet) for step in verbs._steps(dry) for packet in step["encoded"]["packets_hex"]
    ]
    assert tool("describe")(noun="upload")["plan_id"] == planned["plan_id"]


def test_accept_refuses_without_execute_or_once_the_content_changed(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "red.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(source)
    planned = plan(noun="image", path=str(source))
    assert "--execute" in error(asyncio.run(tool("accept")(plan_id=planned["plan_id"])))["error"]

    monkeypatch.setattr(verbs, "_execute", True)
    Image.new("RGB", (8, 8), (0, 255, 0)).save(source)
    changed = error(asyncio.run(tool("accept")(plan_id=planned["plan_id"])))
    assert "review" in changed["error"] and changed["plan"]["plan_id"] != planned["plan_id"]
    arguments = {"noun": "image", "path": str(source), "fit": "contain", "dither": ""}
    given = error(asyncio.run(tool("accept")(plan_id=planned["plan_id"], arguments=arguments)))
    assert "review" in given["error"]
    forgotten = asyncio.run(tool("accept")(plan_id="0123456789abcdef"))
    assert "plan again" in error(forgotten)["error"]
    extra = asyncio.run(tool("accept")(plan_id="x", arguments={**arguments, "speed": 3}))
    assert "does not take speed" in error(extra)["error"]
    assert radio.written == []


def test_a_long_upload_carries_on_after_accept_returns(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verbs, "_execute", True)
    monkeypatch.setattr(verbs, "ACCEPT_WAIT_SECONDS", 0.01)
    radio.delay = 0.2

    async def run():
        planned = shown(await tool("plan")(noun="pattern", value="checker"))
        started = await tool("accept")(**planned["next"]["arguments"])
        busy = await tool("accept")(**planned["next"]["arguments"])
        await verbs._upload.task
        return started, busy

    started, busy = asyncio.run(run())
    assert started["state"] == "uploading"
    assert started["next"] == {"verb": "describe", "arguments": {"noun": "upload"}}
    assert "still running" in error(busy)["error"]
    assert tool("describe")(noun="upload")["state"] == "sent"
