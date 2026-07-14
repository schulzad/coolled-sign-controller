from pathlib import Path

from PIL import Image

from opensign.animation.preview import save_preview
from opensign.animation.render import apply_levels, render_test_pattern, temporal_dither_frames
from opensign.animation.studio import PixelAnimationStudio


def _write_gif(path: Path, *, frames: int, size: tuple[int, int] = (16, 8), duration: int = 120) -> Path:
    images = []
    for i in range(frames):
        image = Image.new("RGB", size, (0, 0, 0))
        image.putpixel((i % size[0], 0), (255, 255, 255))
        images.append(image)
    images[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        disposal=2,
    )
    return path


def test_test_pattern_contains_orientation_markers() -> None:
    image = render_test_pattern(48, 12)
    assert image.size == (48, 12)
    assert image.getpixel((1, 1))[0] > 0
    assert image.getpixel((46, 1))[1] > 0
    assert image.getpixel((1, 10))[2] > 0


def test_two_frame_bundle_and_preview(tmp_path: Path) -> None:
    studio = PixelAnimationStudio(48, 12)
    bundle = studio.create_two_frame_bundle(frames_per_second=4)
    assert len(bundle.frames) == 2
    assert bundle.frame_hashes[0] != bundle.frame_hashes[1]
    output = save_preview(bundle, tmp_path / "preview.gif", scale=4, grid=True)
    assert output.exists()
    assert output.stat().st_size > 0


def test_scroll_text_compiles() -> None:
    studio = PixelAnimationStudio(48, 12)
    bundle = studio.create_text_bundle("HELLO", frames_per_second=12)
    assert len(bundle.frames) > 10
    assert bundle.width == 48
    assert bundle.height == 12


def test_create_gif_bundle_reads_frames_and_durations(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "clip.gif", frames=4, duration=120)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(gif)
    assert len(bundle.frames) == 4
    assert (bundle.width, bundle.height) == (64, 16)
    assert bundle.frame_durations_ms == [120, 120, 120, 120]
    assert bundle.metadata["pattern"] == "gif"
    # authoritative wire-speed key honoured by the codec's _animation_speed()
    assert bundle.metadata["coolledx_speed"] == 120


def test_create_gif_bundle_fps_override_forces_uniform_timing(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "clip.gif", frames=3, duration=500)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(gif, fps=10)
    assert bundle.frame_durations_ms == [100, 100, 100]


def test_create_gif_bundle_subsamples_long_clips(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "clip.gif", frames=30, duration=40)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(gif, max_frames=10)
    assert len(bundle.frames) == 10


def test_create_gif_bundle_subsample_preserves_runtime(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "clip.gif", frames=30, duration=40)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(gif, max_frames=10)
    # dropped frames' hold times fold into survivors, so the clip keeps its run time
    assert sum(bundle.frame_durations_ms) == 30 * 40


def test_create_gif_bundle_ordered_dither_binarizes_channels(tmp_path: Path) -> None:
    path = tmp_path / "gray.gif"
    Image.new("RGB", (64, 16), (128, 128, 128)).save(path, format="GIF")
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(path)  # dither defaults to ordered
    channels = set(bundle.frames[0])
    assert channels <= {0, 255}  # every channel is on or off
    assert 0 in channels and 255 in channels  # flat grey dithers to a mix, not one band


def test_create_gif_bundle_dither_none_keeps_midtones(tmp_path: Path) -> None:
    path = tmp_path / "gray.gif"
    Image.new("RGB", (64, 16), (128, 128, 128)).save(path, format="GIF")
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(path, dither="none")
    assert 128 in set(bundle.frames[0])


def test_create_gif_bundle_single_frame_source(tmp_path: Path) -> None:
    gif = _write_gif(tmp_path / "one.gif", frames=1, duration=200)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(gif)
    assert len(bundle.frames) == 1


def test_temporal_dither_frames_binarize_channels() -> None:
    src = Image.new("RGB", (16, 16), (128, 64, 200))
    frames = temporal_dither_frames(src, subframes=4)
    assert len(frames) == 4
    for frame in frames:
        assert set(frame.tobytes()) <= {0, 255}  # panel can only do on/off


def test_temporal_dither_time_average_tracks_input() -> None:
    # A flat mid-grey should average, over the loop, back to ~mid-grey per channel.
    src = Image.new("RGB", (16, 16), (128, 128, 128))
    frames = temporal_dither_frames(src, subframes=4)
    stacked = [list(frame.getdata()) for frame in frames]
    pixel_count = len(stacked[0])
    channel_avg = sum(stacked[t][0][0] for t in range(4)) / 4  # first pixel, R channel
    panel_avg = sum(px[0] for frame in stacked for px in frame) / (4 * pixel_count)
    assert 96 <= channel_avg <= 160  # single pixel lands on a temporal level near 128
    assert 118 <= panel_avg <= 138  # spatial dither tightens the panel-wide mean


def test_temporal_dither_preserves_extremes() -> None:
    frames = temporal_dither_frames(Image.new("RGB", (8, 8), (0, 0, 0)), subframes=3)
    assert all(set(frame.tobytes()) == {0} for frame in frames)  # black stays off
    frames = temporal_dither_frames(Image.new("RGB", (8, 8), (255, 255, 255)), subframes=3)
    assert all(set(frame.tobytes()) == {255} for frame in frames)  # white stays on


def test_apply_levels_crushes_dark_and_lifts_bright() -> None:
    # a dark-grey background pixel and a mid foreground pixel
    src = Image.new("RGB", (2, 1))
    src.putpixel((0, 0), (20, 20, 25))  # button background
    src.putpixel((1, 0), (65, 103, 67))  # muted green text
    out = apply_levels(src, black_point=30, white_point=180)
    assert out.getpixel((0, 0)) == (0, 0, 0)  # dark background crushed to off
    assert max(out.getpixel((1, 0))) > 103  # foreground lifted


def test_apply_levels_identity_is_noop() -> None:
    src = Image.new("RGB", (4, 4), (40, 80, 120))
    assert list(apply_levels(src).getdata()) == list(src.getdata())


def test_temporal_bundle_black_point_reduces_lit_pixels() -> None:
    src = Image.new("RGB", (64, 16), (22, 22, 26))  # uniform dark-grey background
    studio = PixelAnimationStudio(64, 16)
    without = studio.create_temporal_image_bundle(src, subframes=12)
    with_crush = studio.create_temporal_image_bundle(src, subframes=12, black_point=40)
    lit_without = sum(any(f) for f in without.frames)
    assert all(set(frame) == {0} for frame in with_crush.frames)  # fully black after crush
    assert lit_without > 0  # uncrushed background glows
    assert with_crush.metadata["black_point"] == 40


def test_create_temporal_image_bundle_defaults_to_fused_speed() -> None:
    src = Image.new("RGB", (64, 16), (100, 150, 60))
    bundle = PixelAnimationStudio(64, 16).create_temporal_image_bundle(src, subframes=2)
    assert len(bundle.frames) == 2
    assert bundle.metadata["pattern"] == "temporal_image"
    # N=2 -> speed_ms = floor(1000 / (62 * 2)) = 8ms, matching the ~62 Hz probe result
    assert bundle.metadata["coolledx_speed"] == 8
    assert bundle.frame_durations_ms == [8, 8]


def test_resample_for_matches_colour_reduction_intent() -> None:
    assert PixelAnimationStudio._resample_for("none") == Image.Resampling.NEAREST
    assert PixelAnimationStudio._resample_for("ordered") is None
    assert PixelAnimationStudio._resample_for("floyd") is None


def test_dither_none_uses_nearest_and_keeps_pixels_crisp() -> None:
    # 2x-oversized pixel art aligned to the panel grid. NEAREST recovers it
    # exactly; the old size-based LANCZOS default would blend the 2x2 blocks into
    # greys that the codec's >127 threshold scatters (the two-frame.gif glitch).
    studio = PixelAnimationStudio(8, 8)
    src = Image.new("RGB", (16, 16), (0, 0, 0))
    for y in range(8):
        for x in range(8):
            if (x + y) % 2 == 0:
                for dy in range(2):
                    for dx in range(2):
                        src.putpixel((x * 2 + dx, y * 2 + dy), (255, 0, 0))
    frame = Image.frombytes(
        "RGB", (8, 8), bytes(studio.create_image_bundle(src, dither="none").frames[0])
    )
    for y in range(8):
        for x in range(8):
            expected = (255, 0, 0) if (x + y) % 2 == 0 else (0, 0, 0)
            assert frame.getpixel((x, y)) == expected
