from __future__ import annotations

import asyncio
import base64
import io
import json
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from opensign.animation.preview import LABEL_HEIGHT, image_from_text, text_preview

pytest.importorskip("mcp.server.fastmcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from mcp.types import CallToolResult  # noqa: E402

from opensign.animation.studio import PixelAnimationStudio  # noqa: E402
from opensign.contracts import DeviceProfile, default_device_profile  # noqa: E402
from opensign.protocol import runtime as protocol_runtime  # noqa: E402
from opensign.protocol.transport import DryRunTransport  # noqa: E402
from opensign.sdk import verbs_mcp as verbs  # noqa: E402

STARTER = Path(__file__).resolve().parents[1] / "device_profile.json"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


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
    usage = {n["noun"]: n["args"] for n in plan()["nouns"]}
    assert usage["scene"] == "scene|path [frame_ms] [frame]"
    assert usage["image"] == "path [fit] [dither] [frame]"
    assert asyncio.run(tool("accept")())["args"] == "plan_id [arguments]"
    assert "nouns" in error(tool("render")(noun="video"))
    assert "nouns" in error(asyncio.run(tool("plan")(noun="video")))


def test_describe_panel_reads_the_profile() -> None:
    panel = tool("describe")(noun="panel")
    assert (panel["width"], panel["height"]) == (64, 16)
    assert set(tool("describe")(noun="legend")["color"]) == set(".RGBCMYW")


def test_describe_panel_says_how_many_frames_one_upload_holds() -> None:
    budget = tool("describe")(noun="panel")["frames_per_upload"]
    assert budget == 79
    dot = {"sprites": {"dot": ["W"]}, "items": [{"sprite": "dot", "at": [0, 0]}]}
    assert render(noun="scene", scene={**dot, "length": budget})["frame_count"] == budget
    over = tool("render")(noun="scene", scene={**dot, "length": budget + 1})
    assert f"the {budget} one upload holds" in error(over)["error"]


def test_describe_legend_says_spaces_do_not_pad_a_row() -> None:
    assert "pad with '.'" in tool("describe")(noun="legend")["rows"]
    spaced = {"sprites": {"ring": ["W.W", " W "]}, "items": [{"sprite": "ring", "at": [0, 0]}]}
    refused = error(tool("render")(noun="scene", scene=spaced))["error"]
    assert "row 2 is 1 wide but row 1 is 3" in refused
    dotted = {"sprites": {"ring": ["W.W", ".W."]}, "items": [{"sprite": "ring", "at": [0, 0]}]}
    assert render(noun="scene", scene=dotted)["frame_count"] == 1


def test_describe_legend_says_legend_letters_keep_their_colors() -> None:
    assert "legend letters keep their own colors" in tool("describe")(noun="legend")["scene"]
    flag = {"sprites": {"flag": ["RGB"]}, "items": [{"sprite": "flag", "at": [0, 0]}]}
    assert render(noun="scene", scene=flag, style="color")["frames"][0]["text"].startswith("RGB.")
    white = {**flag, "items": [{"sprite": "flag", "at": [0, 0], "colors": {"G": "white"}}]}
    assert render(noun="scene", scene=white, style="color")["frames"][0]["text"].startswith("RWB.")
    unmapped = {"sprites": {"flag": ["RXB"]}, "items": [{"sprite": "flag", "at": [0, 0]}]}
    refused = error(tool("render")(noun="scene", scene=unmapped))["error"]
    assert "uses X, which needs a color" in refused


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


def test_sample_frames_spreads_a_long_loop_and_keeps_a_short_one_whole() -> None:
    assert verbs.sample_frames(40) == [0, 5, 10, 15, 20, 25, 30, 35]
    assert verbs.sample_frames(79) == [0, 9, 19, 29, 39, 49, 59, 69]
    assert verbs.sample_frames(8) == list(range(8))
    assert verbs.sample_frames(1) == [0]


def test_select_frames_reads_lists_and_ranges_in_the_order_given() -> None:
    assert verbs.select_frames("0,8,16,24,32", 40) == [0, 8, 16, 24, 32]
    assert verbs.select_frames("32, 0, 3-5", 40) == [32, 0, 3, 4, 5]
    assert verbs.select_frames("", 40) == verbs.sample_frames(40)
    assert verbs.select_frames("all", 3) == [0, 1, 2]
    for frame, problem in [
        ("0-8", "names 9 frames, more than the 8"),
        ("all", "names 40 frames"),
        ("40", "frame 40 is outside 0-39"),
        ("5-3", "runs backwards; write 3-5"),
        ("x", "comma-separated list"),
        ("1,,2", "comma-separated list"),
        ("-1", "comma-separated list"),
    ]:
        with pytest.raises(ValueError) as refused:
            verbs.select_frames(frame, 40)
        assert problem in str(refused.value), frame


MARCH = {
    "sprites": {"dot": ["W"]},
    "items": [{"sprite": "dot", "at": [0, 0], "move": [1, 0]}],
    "length": 40,
}


def test_render_spreads_a_long_loop_and_takes_a_list_of_beats() -> None:
    spread = render(noun="scene", scene=MARCH)
    assert [f["index"] for f in spread["frames"]] == [0, 5, 10, 15, 20, 25, 30, 35]
    assert spread["frames"][1]["text"].splitlines()[0].index("#") == 5
    beats = render(noun="scene", scene=MARCH, frame="0,8,16,24,32")
    assert [f["index"] for f in beats["frames"]] == [0, 8, 16, 24, 32]
    backwards = tool("render")(noun="scene", scene=MARCH, frame="9-2")
    assert "runs backwards" in error(backwards)["error"]


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


def test_render_draw_centers_each_frame_on_the_panel() -> None:
    out = render(noun="draw", value="R.\n.R\n\nG.\n.G", frame="all", style="color")
    assert (out["frame_count"], out["duration_ms"]) == (2, 400)
    rows = out["frames"][0]["text"].splitlines()
    assert (len(rows), len(rows[0])) == (16, 64)
    assert (rows[7][31:33], rows[8][31:33]) == ("R.", ".R")
    assert out["frames"][1]["text"].count("G") == 2


def _sheet(result) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(result.content[1].data)))


def test_render_shows_its_frames_as_a_picture_each_labeled_with_its_index() -> None:
    result = tool("render")(noun="draw", value="R\n\nG", frame="all")
    assert result.content[1].mimeType == "image/png"
    sheet = _sheet(result)
    scale, gap, label = verbs.PICTURE_SCALE, verbs.PICTURE_GAP, LABEL_HEIGHT
    assert sheet.size == (64 * scale, 2 * (label + 16 * scale) + gap)
    assert sheet.crop((0, 0, 64 * scale, label)).getextrema()[0][1] > 64  # lettered
    x, y = 31 * scale + scale // 2, label + 7 * scale + scale // 2
    assert sheet.getpixel((x, y)) == (255, 0, 0)
    assert sheet.getpixel((x, label + 16 * scale + gap + y)) == (0, 255, 0)
    still = _sheet(tool("render")(noun="draw", value="R"))
    assert still.size == (64 * scale, 16 * scale)
    assert isinstance(tool("render")(noun="draw", value="R", picture=False), dict)


def test_render_draw_says_what_is_wrong_with_a_drawing() -> None:
    assert "row 2 is 1 wide" in error(tool("render")(noun="draw", value="RR\nR"))["error"]
    assert "frame 1: row 1, column 1" in error(tool("render")(noun="draw", value="R\n\nX"))["error"]
    assert "larger than the 64x16 panel" in error(tool("render")(noun="draw", value="." * 65))["error"]
    assert "usage" in error(tool("render")(noun="draw"))


GHOST = [".XXX.", "XWXWX", "XXXXX", "X.X.X"]


def test_render_scene_places_recolored_sprites() -> None:
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
    assert "uses X, which needs a color" in problem({"sprites": ghost, "items": [{"sprite": "ghost"}]})
    off_grid = {"sprite": "ghost", "at": [1.5, 0], "colors": {"X": "R"}}
    assert "at must be [x, y]" in problem({"sprites": ghost, "items": [off_grid]})
    plaid = {"sprite": "ghost", "colors": {"X": "plaid"}}
    assert "not a color" in problem({"sprites": ghost, "items": [plaid]})
    assert "frames[1][0]" in problem({"sprites": ghost, "frames": [[], ["ghost"]]})


HEART = {"heart": [".R.R.", "RRRRR", ".RRR.", "..R.."]}


def test_a_scene_file_plans_the_same_packets_as_the_scene_inline(
    panel: Path, tmp_path: Path
) -> None:
    path = EXAMPLES / "scenes" / "pacman-chomp.json"
    chomp = json.loads(path.read_text(encoding="utf-8"))
    from_file = plan(noun="scene", path=str(path))
    inline = plan(noun="scene", scene=chomp, frame_ms=chomp["frame_ms"])
    assert from_file["plan_id"] == inline["plan_id"]
    assert from_file["summary"].startswith("Play pacman-chomp.json on")
    assert render(noun="scene", path=str(path))["duration_ms"] == 4 * chomp["frame_ms"]
    slower = plan(noun="scene", path=str(path), frame_ms=300)
    assert slower["plan_id"] == plan(noun="scene", scene=chomp, frame_ms=300)["plan_id"]
    assert slower["plan_id"] != from_file["plan_id"]
    plain = tmp_path / "heart.json"
    plain.write_text(json.dumps({"sprites": HEART, "items": [{"sprite": "heart", "at": [30, 6]}]}))
    assert render(noun="scene", path=str(plain))["duration_ms"] == verbs.FRAME_MS


def test_render_scene_from_a_file_says_what_is_wrong(tmp_path: Path) -> None:
    def problem(**arguments) -> str:
        return error(tool("render")(noun="scene", **arguments))["error"]

    chomp = EXAMPLES / "scenes" / "pacman-chomp.json"
    assert "absolute" in problem(path="examples/scenes/pacman-chomp.json")
    assert "File not found" in problem(path=str(tmp_path / "missing.json"))
    assert "give scene or path, not both" in problem(path=str(chomp), scene={"sprites": HEART})
    broken = tmp_path / "broken.json"
    broken.write_text('{"sprites": {"dot": ["W"]},}')
    assert "not JSON" in problem(path=str(broken))
    hasty = tmp_path / "hasty.json"
    hasty.write_text('{"sprites": {"dot": ["W"]}, "frame_ms": "fast"}')
    assert "frame_ms must be a whole number" in problem(path=str(hasty))
    assert "or path, a scene file" in problem()


def test_accept_refuses_a_scene_file_edited_since_its_plan(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(verbs, "_execute", True)
    path = tmp_path / "heart.json"
    path.write_text(json.dumps({"sprites": HEART, "items": [{"sprite": "heart", "at": [30, 6]}]}))
    planned = plan(noun="scene", path=str(path))
    path.write_text(json.dumps({"sprites": HEART, "items": [{"sprite": "heart", "at": [31, 6]}]}))
    changed = error(asyncio.run(tool("accept")(plan_id=planned["plan_id"])))
    assert "review" in changed["error"] and radio.written == []


def test_plan_pictures_the_frames_it_is_asked_for_and_sends_the_same(panel: Path) -> None:
    result = asyncio.run(tool("plan")(noun="scene", scene=MARCH, frame="0,8,16"))
    planned = result.structuredContent
    assert planned["preview"]["pictured_frames"] == [0, 8, 16]
    scale, gap = verbs.PICTURE_SCALE, verbs.PICTURE_GAP
    assert _sheet(result).height == 3 * (LABEL_HEIGHT + 16 * scale) + 2 * gap
    spread = plan(noun="scene", scene=MARCH)
    assert spread["preview"]["pictured_frames"] == [0, 5, 10, 15, 20, 25, 30, 35]
    assert spread["plan_id"] == planned["plan_id"]
    outside = asyncio.run(tool("plan")(noun="scene", scene=MARCH, frame="40"))
    assert "outside 0-39" in error(outside)["error"]
    banner = asyncio.run(tool("plan")(noun="text", value="HI", scroll=True, frame="0"))
    assert "frame does not apply" in error(banner)["error"]


def test_plan_and_accept_a_scene_by_its_plan_id(
    panel: Path, radio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verbs, "_execute", True)
    scene = {"sprites": HEART, "items": [{"sprite": "heart", "at": [30, 6]}]}
    result = asyncio.run(tool("plan")(noun="scene", scene=scene))
    assert result.content[1].mimeType == "image/png"
    planned = result.structuredContent
    assert planned["summary"].startswith("Show the scene on")
    sent = asyncio.run(tool("accept")(plan_id=planned["plan_id"]))
    assert sent["state"] == "sent" and radio.written


def test_a_chomp_written_with_cycles_plans_the_same_packets(panel: Path) -> None:
    chomp = json.loads((EXAMPLES / "scenes" / "pacman-chomp.json").read_text(encoding="utf-8"))
    ghosts = [
        {"sprite": ["ghost_a", "ghost_b"], "at": [x, 3], "colors": {"X": color}}
        for x, color in ((0, "cyan"), (12, "magenta"), (24, "red"))
    ]
    pac = {"sprite": ["pac_open", "pac_half", "pac_shut", "pac_half"], "at": [37, 3]}
    cycled = {"sprites": chomp["sprites"], "items": [*chomp["items"], *ghosts, pac]}

    def plan_id(scene: dict) -> str:
        result = asyncio.run(tool("plan")(noun="scene", scene=scene, frame_ms=150))
        return result.structuredContent["plan_id"]

    assert plan_id(cycled) == plan_id(chomp)


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
