from pathlib import Path

from PIL import Image

from opensign.animation.cache import RenderBundleCache, render_cache_key
from opensign.contracts import FrameBundle


def _bundle(color: tuple[int, int, int] = (255, 0, 0)) -> FrameBundle:
    return FrameBundle.from_images(
        [Image.new("RGB", (2, 1), color)],
        [100],
        frames_per_second=10,
    )


def test_render_cache_reuses_bundle_for_same_source_and_parameters(tmp_path: Path) -> None:
    source = tmp_path / "source.gif"
    source.write_bytes(b"source-v1")
    calls = 0

    def render() -> FrameBundle:
        nonlocal calls
        calls += 1
        return _bundle()

    cache = RenderBundleCache(tmp_path / "cache")
    first = cache.get_or_create(
        source,
        kind="gif",
        parameters={"width": 64, "fit": "cover"},
        render=render,
    )
    second = cache.get_or_create(
        source,
        kind="gif",
        parameters={"fit": "cover", "width": 64},
        render=render,
    )

    assert calls == 1
    assert first.hit is False
    assert second.hit is True
    assert first.key == second.key
    assert second.bundle.frames == first.bundle.frames


def test_render_cache_key_changes_with_source_or_parameters(tmp_path: Path) -> None:
    source = tmp_path / "source.gif"
    source.write_bytes(b"source-v1")
    base = render_cache_key(source, kind="gif", parameters={"fit": "cover"})
    changed_parameters = render_cache_key(source, kind="gif", parameters={"fit": "contain"})

    source.write_bytes(b"source-v2")
    changed_source = render_cache_key(source, kind="gif", parameters={"fit": "cover"})

    assert changed_parameters != base
    assert changed_source != base


def test_render_cache_rebuilds_corrupt_entry(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    calls = 0

    def render() -> FrameBundle:
        nonlocal calls
        calls += 1
        return _bundle((0, 255, 0))

    cache = RenderBundleCache(tmp_path / "cache")
    first = cache.get_or_create(source, kind="image", parameters={}, render=render)
    first.path.write_text("{not-json", encoding="utf-8")
    rebuilt = cache.get_or_create(source, kind="image", parameters={}, render=render)

    assert calls == 2
    assert rebuilt.hit is False
    assert FrameBundle.load(rebuilt.path).frames == rebuilt.bundle.frames
