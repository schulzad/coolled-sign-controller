from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageSequence

from opensign.contracts import FrameBundle, utc_now_iso

from .render import (
    apply_levels,
    composite_frame,
    fit_image,
    image_from_base64,
    load_and_fit_image,
    normalize_frames,
    parse_color,
    quantize_to_panel,
    render_checker_animation,
    render_scroll_text,
    render_static_text,
    render_test_pattern,
    render_two_frame_animation,
    temporal_dither_frames,
)

# Flicker-fusion ceiling measured on the reference panel (2026-07-13): a 2-frame
# inverse loop fused into a flat tone at ~62 Hz per-pixel alternation. Temporal
# subframes are timed so the slowest-pulsing pixel (on 1 of N frames) still beats
# this, i.e. loop_period = N * speed_ms <= 1000 / TARGET_FUSION_HZ.
TARGET_FUSION_HZ = 62.0


class PixelAnimationStudio:
    """Facade matching the PixelAnimationStudio SeedScript module."""

    def __init__(self, width: int = 48, height: int = 12):
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        self.width = width
        self.height = height

    @staticmethod
    def _resample_for(dither: str) -> Image.Resampling | None:
        """Pick a resampling filter that matches the colour-reduction intent.

        ``dither="none"`` relies on the codec's hard ``>127`` threshold, so a
        smoothing filter (LANCZOS/box) is actively harmful: it manufactures grey
        edge pixels that the threshold then snaps unpredictably into scatter.
        NEAREST keeps synthetic art / pixel-perfect sources crisp. Dithered modes
        keep the size-aware default (``None`` -> LANCZOS downscale) since they can
        represent the intermediate tones a smooth filter produces.
        """
        return Image.Resampling.NEAREST if dither == "none" else None

    def compile_images(
        self,
        images: Iterable[Image.Image],
        *,
        frame_durations_ms: Iterable[int],
        frames_per_second: float | None = None,
        loop_mode: str = "loop",
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
        dither: str = "none",
        metadata: Mapping[str, Any] | None = None,
    ) -> FrameBundle:
        normalized = normalize_frames(
            list(images),
            self.width,
            self.height,
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
        )
        if dither != "none":
            normalized = [quantize_to_panel(frame, dither) for frame in normalized]
        bundle_metadata = {
            "created_by": "PixelAnimationStudio",
            "compiler_version": "0.1.0",
            "created_at": utc_now_iso(),
            "dither": dither,
            **dict(metadata or {}),
        }
        return FrameBundle.from_images(
            normalized,
            frame_durations_ms,
            frames_per_second=frames_per_second,
            loop_mode=loop_mode,
            metadata=bundle_metadata,
        )

    def create_test_pattern_bundle(
        self,
        *,
        duration_ms: int = 1000,
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        image = render_test_pattern(self.width, self.height)
        return self.compile_images(
            [image],
            frame_durations_ms=[duration_ms],
            frames_per_second=1000 / duration_ms,
            loop_mode="loop",
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            metadata={"pattern": "test"},
        )

    def create_two_frame_bundle(
        self,
        *,
        frames_per_second: float = 2.0,
        loop_mode: str = "loop",
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        if frames_per_second <= 0:
            raise ValueError("frames_per_second must be positive")
        duration = max(1, round(1000 / frames_per_second))
        frames = render_two_frame_animation(self.width, self.height)
        return self.compile_images(
            frames,
            frame_durations_ms=[duration] * len(frames),
            frames_per_second=frames_per_second,
            loop_mode=loop_mode,
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            metadata={"pattern": "two-frame"},
        )

    def create_checker_bundle(
        self,
        *,
        frame_count: int = 8,
        frames_per_second: float = 8.0,
        foreground: str = "#00E5FF",
        background: str = "#071A2B",
        loop_mode: str = "loop",
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        if frames_per_second <= 0:
            raise ValueError("frames_per_second must be positive")
        frames = render_checker_animation(
            self.width,
            self.height,
            frame_count=frame_count,
            foreground=foreground,
            background=background,
        )
        duration = max(1, round(1000 / frames_per_second))
        return self.compile_images(
            frames,
            frame_durations_ms=[duration] * len(frames),
            frames_per_second=frames_per_second,
            loop_mode=loop_mode,
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            metadata={"pattern": "checker"},
        )

    def create_text_bundle(
        self,
        text: str,
        *,
        scroll: bool = True,
        frames_per_second: float = 12.0,
        foreground: str = "white",
        background: str = "black",
        pixels_per_frame: int = 1,
        loop_mode: str = "loop",
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        if frames_per_second <= 0:
            raise ValueError("frames_per_second must be positive")
        frames = (
            render_scroll_text(
                text,
                self.width,
                self.height,
                foreground=foreground,
                background=background,
                pixels_per_frame=pixels_per_frame,
            )
            if scroll
            else [
                render_static_text(
                    text,
                    self.width,
                    self.height,
                    foreground=foreground,
                    background=background,
                )
            ]
        )
        duration = max(1, round(1000 / frames_per_second))
        return self.compile_images(
            frames,
            frame_durations_ms=[duration] * len(frames),
            frames_per_second=frames_per_second,
            loop_mode=loop_mode,
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            metadata={"pattern": "text", "text": text, "scroll": scroll},
        )

    def create_image_bundle(
        self,
        source: str | Path | Image.Image,
        *,
        duration_ms: int = 1000,
        fit_mode: str = "contain",
        background: str = "black",
        dither: str = "none",
        black_point: int = 0,
        white_point: int = 255,
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        image = load_and_fit_image(
            source,
            self.width,
            self.height,
            fit_mode=fit_mode,
            background=background,
            resample=self._resample_for(dither),
        )
        image = apply_levels(image, black_point=black_point, white_point=white_point)
        return self.compile_images(
            [image],
            frame_durations_ms=[duration_ms],
            frames_per_second=1000 / duration_ms,
            loop_mode="loop",
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            dither=dither,
            metadata={"pattern": "image", "fit_mode": fit_mode},
        )

    def create_base64_image_bundle(self, value: str, **options: Any) -> FrameBundle:
        image = image_from_base64(value)
        return self.create_image_bundle(image, **options)

    def create_temporal_image_bundle(
        self,
        source: str | Path | Image.Image,
        *,
        subframes: int = 2,
        target_hz: float = TARGET_FUSION_HZ,
        speed_ms: int | None = None,
        fit_mode: str = "contain",
        background: str = "black",
        black_point: int = 0,
        white_point: int = 255,
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ) -> FrameBundle:
        """Render a *still* as a fast N-frame loop that temporally dithers colour.

        Turns one image into ``subframes`` binarized frames whose per-pixel duty
        cycle averages, to the eye, into intermediate colours the panel cannot
        show in a single frame (see :func:`temporal_dither_frames`). Only useful
        for stills: the loop *is* the picture, so it must not carry motion.

        The playback speed defaults to the fastest hold time that keeps the
        worst-case (1-of-N) pixel above ``target_hz`` -- i.e. ``speed_ms =
        floor(1000 / (target_hz * subframes))`` -- so N=2 lands on the ~8 ms/62 Hz
        operating point measured on hardware. Pass ``speed_ms`` to override.
        """
        if subframes < 2:
            raise ValueError("subframes must be >= 2 (use create_image_bundle for a single frame)")
        image = load_and_fit_image(
            source,
            self.width,
            self.height,
            fit_mode=fit_mode,
            background=background,
        )
        image = apply_levels(image, black_point=black_point, white_point=white_point)
        frames = temporal_dither_frames(image, subframes=subframes)
        if speed_ms is None:
            speed_ms = max(1, int(1000 / (target_hz * subframes)))
        return self.compile_images(
            frames,
            frame_durations_ms=[speed_ms] * len(frames),
            frames_per_second=1000 / speed_ms,
            loop_mode="loop",
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            dither="none",
            metadata={
                "pattern": "temporal_image",
                "fit_mode": fit_mode,
                "temporal_subframes": subframes,
                "coolledx_speed": speed_ms,
                "loop_hz": round(1000 / (speed_ms * len(frames)), 1),
                "black_point": black_point,
                "white_point": white_point,
            },
        )

    def create_gif_bundle(
        self,
        source: str | Path,
        *,
        fps: float | None = None,
        max_frames: int = 120,
        fit_mode: str = "contain",
        background: str = "black",
        dither: str = "ordered",
        loop_mode: str = "loop",
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
        default_frame_ms: int = 100,
    ) -> FrameBundle:
        """Render an animated GIF (or any multi-frame image) into a FrameBundle.

        Each frame is composited onto ``background`` (so transparent GIFs do not
        turn black), fitted to the panel, and dithered to the panel's 8-colour
        gamut (``dither="ordered"`` by default to avoid temporal shimmer).

        Per-frame GIF durations become the bundle's ``frame_durations_ms``. The
        CoolLEDX device plays at a single global speed, so the median hold time is
        recorded as the authoritative ``coolledx_speed`` (ms/frame); pass ``fps``
        to force a uniform rate instead.

        Long clips are evenly subsampled to ``max_frames`` to respect the device
        frame budget; each dropped frame's hold time is folded into the surviving
        frame so the clip keeps its original run time (subsampling no longer
        silently speeds the animation up).
        """
        background_rgb = parse_color(background)
        frames: list[Image.Image] = []
        durations: list[int] = []
        with Image.open(source) as animated:
            for frame in ImageSequence.Iterator(animated):
                frames.append(composite_frame(frame, background_rgb))
                raw = frame.info.get("duration", default_frame_ms)
                durations.append(int(raw) if raw and int(raw) > 0 else default_frame_ms)
        if not frames:
            raise ValueError("source contains no frames")

        if max_frames > 0 and len(frames) > max_frames:
            step = len(frames) / max_frames
            keep = sorted({min(len(frames) - 1, int(i * step)) for i in range(max_frames)})
            merged: list[int] = []
            for position, index in enumerate(keep):
                nxt = keep[position + 1] if position + 1 < len(keep) else len(frames)
                merged.append(sum(durations[index:nxt]))
            frames = [frames[i] for i in keep]
            durations = merged

        if fps is not None:
            if fps <= 0:
                raise ValueError("fps must be positive")
            durations = [max(1, round(1000 / fps))] * len(frames)

        resample = self._resample_for(dither)
        fitted = [
            fit_image(
                frame,
                self.width,
                self.height,
                fit_mode=fit_mode,
                background=background,
                resample=resample,
            )
            for frame in frames
        ]
        median_ms = sorted(durations)[len(durations) // 2]
        return self.compile_images(
            fitted,
            frame_durations_ms=durations,
            frames_per_second=(1000 / median_ms) if median_ms else None,
            loop_mode=loop_mode,
            rotation=rotation,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            dither=dither,
            metadata={
                "pattern": "gif",
                "source": str(source),
                "gif_frames": len(fitted),
                "coolledx_speed": median_ms,
                "fit_mode": fit_mode,
            },
        )
