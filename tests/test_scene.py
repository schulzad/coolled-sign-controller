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
