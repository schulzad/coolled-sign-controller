from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from opensign.animation.preview import contact_sheet
from opensign.animation.scene import compile_drawing, compile_scene
from opensign.contracts import FrameBundle

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SCENES = sorted((EXAMPLES / "scenes").glob("*.json"))


@pytest.mark.parametrize("path", SCENES, ids=[path.stem for path in SCENES])
def test_saved_scenes_still_compile_to_their_bundles(path: Path) -> None:
    scene = json.loads(path.read_text(encoding="utf-8"))
    bundle = compile_scene(scene, 64, 16, frame_ms=scene["frame_ms"], max_frames=79)
    saved = FrameBundle.load(EXAMPLES / "generated" / "scenes" / f"{path.stem}.bundle.json")
    assert (bundle.frame_hashes, bundle.frame_durations_ms) == (
        saved.frame_hashes, saved.frame_durations_ms
    )


def test_the_hand_drawn_chomp_matches_its_scene() -> None:
    scene = json.loads((EXAMPLES / "scenes" / "pacman-chomp.json").read_text(encoding="utf-8"))
    drawing = (EXAMPLES / "scenes" / "pacman-chomp.txt").read_text(encoding="utf-8")
    by_hand = compile_drawing(drawing, 64, 16, frame_ms=scene["frame_ms"])
    from_sprites = compile_scene(scene, 64, 16, frame_ms=scene["frame_ms"])
    assert by_hand.frame_hashes == from_sprites.frame_hashes


def test_contact_sheet_stacks_frames_of_any_width() -> None:
    wide, narrow = Image.new("RGB", (8, 2), "red"), Image.new("RGB", (4, 2), "blue")
    sheet = contact_sheet([wide, narrow], scale=2, gap=1)
    assert sheet.size == (16, 9)
    assert [sheet.getpixel(xy) for xy in [(1, 1), (1, 6), (12, 6)]] == [
        (255, 0, 0), (0, 0, 255), (64, 64, 64)
    ]


def test_compile_scene_refuses_more_frames_than_one_upload_holds() -> None:
    scene = {"sprites": {"dot": ["W"]}, "frames": [[{"sprite": "dot"}]] * 3}
    with pytest.raises(ValueError, match="3 frames is more than the 2 one upload holds"):
        compile_scene(scene, 64, 16, max_frames=2)
    with pytest.raises(ValueError, match="frame_ms must be positive"):
        compile_scene(scene, 64, 16, frame_ms=0)


def test_the_chomp_written_with_cycles_compiles_to_its_frames() -> None:
    chomp = json.loads((EXAMPLES / "scenes" / "pacman-chomp.json").read_text(encoding="utf-8"))
    ghosts = [
        {"sprite": ["ghost_a", "ghost_b"], "at": [x, 3], "colors": {"X": color}}
        for x, color in ((0, "cyan"), (12, "magenta"), (24, "red"))
    ]
    pac = {"sprite": ["pac_open", "pac_half", "pac_shut", "pac_half"], "at": [37, 3]}
    cycled = {"sprites": chomp["sprites"], "items": [*chomp["items"], *ghosts, pac]}
    by_frame = compile_scene(chomp, 64, 16, frame_ms=150, max_frames=79)
    by_cycle = compile_scene(cycled, 64, 16, frame_ms=150, max_frames=79)
    assert (by_cycle.frame_hashes, by_cycle.frame_durations_ms) == (
        by_frame.frame_hashes, by_frame.frame_durations_ms
    )


def test_a_moving_item_equals_the_placements_it_replaces() -> None:
    sprites = {"pac": ["YY", "Y."]}
    moving = {"sprites": sprites, "length": 4,
              "items": [{"sprite": "pac", "at": [-2, 3], "move": [3, 1]}]}
    stepped = {"sprites": sprites,
               "frames": [[{"sprite": "pac", "at": [-2 + 3 * i, 3 + i]}] for i in range(4)]}
    assert compile_scene(moving, 64, 16).frame_hashes == compile_scene(stepped, 64, 16).frame_hashes


def test_a_wrapping_item_comes_back_in_at_the_opposite_edge() -> None:
    scene = {"sprites": {"dot": ["WW"]},
             "items": [{"sprite": "dot", "at": [60, 0], "move": [2, 0], "wrap": True}]}
    images = compile_scene(scene, 64, 16, max_frames=79).to_images()
    lit = [[x for x in range(64) if image.getpixel((x, 0)) != (0, 0, 0)] for image in images]
    assert len(lit) == 33
    assert lit[:5] == [[60, 61], [62, 63], [], [0, 1], [2, 3]]


def test_a_scene_runs_to_the_least_common_multiple_of_what_repeats() -> None:
    scene = {
        "sprites": {"a": ["R"], "b": ["G"], "c": ["B"]},
        "items": [{"sprite": ["a", "b"]}, {"sprite": "c", "cycle": [[0, 1], [1, 1], [2, 1]]}],
    }
    images = compile_scene(scene, 64, 16).to_images()
    assert len(images) == 6
    assert [image.getpixel((0, 0)) for image in images[:3]] == [(255, 0, 0), (0, 255, 0), (255, 0, 0)]
    assert [image.getpixel((x, 1)) for x, image in zip((0, 1, 2), images[3:], strict=True)] == [
        (0, 0, 255)
    ] * 3
    assert len(compile_scene({**scene, "length": 12}, 64, 16).frames) == 12


def test_a_mirrored_placement_equals_the_sprite_drawn_mirrored() -> None:
    rows = ["RG.", "B.."]
    for axis, by_hand in (("x", [row[::-1] for row in rows]), ("y", rows[::-1])):
        mirrored = {"sprites": {"s": rows}, "items": [{"sprite": "s", "at": [5, 5], "mirror": axis}]}
        drawn = {"sprites": {"s": by_hand}, "items": [{"sprite": "s", "at": [5, 5]}]}
        assert compile_scene(mirrored, 64, 16).frame_hashes == compile_scene(drawn, 64, 16).frame_hashes


def test_k_paints_off_over_earlier_placements_unless_recolored() -> None:
    scene = {"sprites": {"bar": ["WWWW"], "notch": [".K."]},
             "items": [{"sprite": "bar"}, {"sprite": "notch"}]}
    image = compile_scene(scene, 64, 16).to_images()[0]
    white, off = (255, 255, 255), (0, 0, 0)
    assert [image.getpixel((x, 0)) for x in range(4)] == [white, off, white, white]
    scene["items"][1]["colors"] = {"K": "cyan"}
    assert compile_scene(scene, 64, 16).to_images()[0].getpixel((1, 0)) == (0, 255, 255)


@pytest.mark.parametrize(
    ("scene", "message"),
    [
        ({"length": 80, "items": [{"sprite": "dot", "move": [1, 0]}]},
         "80 frames is more than the 79 one upload holds"),
        ({"items": [{"sprite": ["dot"] * 9}, {"sprite": ["dot"] * 10}]},
         r"90 frames, the least common multiple of 9 \(items\[0\]'s sprites\) and "
         r"10 \(items\[1\]'s sprites\), is more than the 79 one upload holds"),
        ({"items": [{"sprite": "dot", "move": [2, 0]}]},
         r'items\[0\] moves, but the scene has one frame; .*"length": 33'),
        ({"length": 2, "items": [{"sprite": ["dot", "pair", "dot"]}]},
         r"length 2 is shorter than items\[0\]'s sprites \(3\)"),
        ({"length": 0, "items": [{"sprite": "dot"}]}, "length must be a whole number of frames"),
        ({"frames": [[{"sprite": "dot", "move": [1, 0]}]]}, r"frames\[0\]\[0\]: move belongs on items"),
        ({"frames": [[{"sprite": ["dot", "pair"]}]]},
         r"frames\[0\]\[0\]: a list of sprites belongs on items"),
        ({"items": [{"sprite": "dot", "at": [0, 0], "cycle": [[1, 1]]}]}, "give at or cycle, not both"),
        ({"items": [{"sprite": "dot", "cycle": [[1.5, 1]]}]}, "cycle must list positions"),
        ({"items": [{"sprite": "dot", "wrap": True}]}, "wrap must be true or false, and needs move"),
        ({"items": [{"sprite": ["dot", "dto"]}]}, r"items\[0\]: sprite 'dto' is not one of 'dot', 'pair'"),
        ({"items": [{"sprite": "dot", "mirror": "z"}]}, 'mirror must be "x"'),
        ({"items": [{"sprite": "dot", "colours": {"W": "red"}}]}, 'the key is "colors", not "colours"'),
        ({"frames": [[{"sprite": "dot", "colours": {"W": "red"}}]]},
         r'frames\[0\]\[0\]: the key is "colors", not "colours"'),
    ],
)
def test_placements_say_what_is_wrong(scene: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        compile_scene({"sprites": {"dot": ["W"], "pair": ["WW"]}, **scene}, 64, 16, max_frames=79)
