from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensign.animation.scene import compile_scene
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


def test_compile_scene_refuses_more_frames_than_one_upload_holds() -> None:
    scene = {"sprites": {"dot": ["W"]}, "frames": [[{"sprite": "dot"}]] * 3}
    with pytest.raises(ValueError, match="3 frames is more than the 2 one upload holds"):
        compile_scene(scene, 64, 16, max_frames=2)
    with pytest.raises(ValueError, match="frame_ms must be positive"):
        compile_scene(scene, 64, 16, frame_ms=0)
