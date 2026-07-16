from __future__ import annotations

import base64
import binascii
import copy
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from opensign.animation.preview import save_preview
from opensign.animation.render import image_from_base64
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import ContractError, DeviceProfile, FrameBundle, utc_now_iso
from opensign.protocol.codec import CodecError
from opensign.protocol.codecs.coolledx import PIXEL_BYTES_MAX
from opensign.protocol.runtime import ProtocolRuntime

from .integrations import IntegrationRegistry
from .scheduler import InProcessScheduler
from .trace import TraceStore


@dataclass(slots=True)
class PanelState:
    profile: DeviceProfile
    default_settings: dict[str, Any] = field(default_factory=dict)
    brightness_percent: int | None = None
    power: bool | None = None
    active_playback: dict[str, Any] | None = None
    last_delivery: dict[str, Any] | None = None
    last_trace_id: str | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self, *, include_profile: bool = False) -> dict[str, Any]:
        data = {
            "panel_id": self.profile.panel_id,
            "device_id": self.profile.device_id,
            "advertised_name": self.profile.advertised_name,
            "dimensions": {"width": self.profile.width, "height": self.profile.height},
            "protocol_family": self.profile.get("protocol_family"),
            "protocol_status": self.profile.protocol.get("status"),
            "codec": self.profile.protocol.get("codec"),
            "confidence": self.profile.get("confidence"),
            "brightness_percent": self.brightness_percent,
            "power": self.power,
            "active_playback": copy.deepcopy(self.active_playback),
            "last_delivery": copy.deepcopy(self.last_delivery),
            "last_trace_id": self.last_trace_id,
            "updated_at": self.updated_at,
        }
        if include_profile:
            data["profile"] = self.profile.to_dict()
        return data


class OpenSignRuntime:
    """Coordinates rendering, profile selection, guarded delivery, scheduling, and status."""

    def __init__(
        self,
        *,
        execute: bool = False,
        artifact_dir: str | Path | None = None,
        trace_jsonl: str | Path | None = None,
    ) -> None:
        self.execute = execute
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.panels: dict[str, PanelState] = {}
        self.traces = TraceStore(trace_jsonl)
        self.scheduler = InProcessScheduler()
        self.integrations = IntegrationRegistry()

    def register_panel(
        self,
        profile: DeviceProfile | Mapping[str, Any],
        *,
        panel_id: str | None = None,
        default_settings: Mapping[str, Any] | None = None,
    ) -> PanelState:
        active = profile if isinstance(profile, DeviceProfile) else DeviceProfile(profile)
        if panel_id and panel_id != active.panel_id:
            data = active.to_dict()
            data["panel_id"] = panel_id
            active = DeviceProfile(data)
        state = PanelState(profile=active, default_settings=dict(default_settings or {}))
        self.panels[active.panel_id] = state
        return state

    def register_profile_path(
        self,
        path: str | Path,
        *,
        panel_id: str | None = None,
        default_settings: Mapping[str, Any] | None = None,
    ) -> PanelState:
        return self.register_panel(
            DeviceProfile.load(path),
            panel_id=panel_id,
            default_settings=default_settings,
        )

    def _state(self, panel_id: str) -> PanelState:
        try:
            return self.panels[panel_id]
        except KeyError as exc:
            raise LookupError(f"Panel is not registered: {panel_id}") from exc

    @staticmethod
    def _orientation(state: PanelState) -> dict[str, Any]:
        render = state.default_settings.get("render", {})
        profile_render = state.profile.get("render", {})
        merged = {**profile_render, **render}
        return {
            "rotation": int(merged.get("rotation", 0)),
            "flip_horizontal": bool(merged.get("flip_horizontal", False)),
            "flip_vertical": bool(merged.get("flip_vertical", False)),
        }

    def _store_artifacts(self, panel_id: str, trace_id: str, bundle: FrameBundle) -> dict[str, str]:
        if self.artifact_dir is None:
            return {}
        directory = self.artifact_dir / panel_id / trace_id
        directory.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle.save(directory / "frame_bundle.json")
        preview_suffix = ".gif" if len(bundle.frames) > 1 else ".png"
        preview_path = save_preview(bundle, directory / f"preview{preview_suffix}", scale=12, grid=True)
        return {"frame_bundle": str(bundle_path), "preview": str(preview_path)}

    async def play_bundle(
        self,
        panel_id: str,
        bundle: FrameBundle,
        *,
        execute: bool | None = None,
        retry_limit: int = 3,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(panel_id)
        if bundle.width != state.profile.width or bundle.height != state.profile.height:
            raise ContractError(
                f"Bundle is {bundle.width}x{bundle.height}; panel profile is "
                f"{state.profile.width}x{state.profile.height}"
            )
        should_execute = self.execute if execute is None else execute
        trace_id = request_id or self.traces.new_trace()
        self.traces.add(
            trace_id,
            "validate_request",
            "ok",
            panel_id=panel_id,
            bundle=bundle.summary(),
            execute=should_execute,
        )
        artifacts = self._store_artifacts(panel_id, trace_id, bundle)
        if artifacts:
            self.traces.add(trace_id, "render_artifacts", "ok", **artifacts)

        runtime = ProtocolRuntime(state.profile)
        try:
            delivery = await runtime.upload_frame_bundle(
                bundle,
                execute=should_execute,
                retry_limit=retry_limit,
            )
            delivery_status = "transferred" if should_execute else "dry_run_packet_plan"
            self.traces.add(trace_id, "ble_delivery", "ok", mode=delivery_status)
        except CodecError as exc:
            if should_execute:
                self.traces.add(trace_id, "ble_delivery", "error", error=str(exc))
                raise
            delivery = {
                "status": "rendered_only",
                "reason": str(exc),
                "frame_bundle": bundle.summary(),
            }
            delivery_status = "rendered_only"
            self.traces.add(trace_id, "ble_delivery", "skipped", reason=str(exc))

        state.active_playback = {
            "trace_id": trace_id,
            "bundle": bundle.summary(),
            "metadata": copy.deepcopy(bundle.metadata),
            "delivery_status": delivery_status,
            "artifacts": artifacts,
        }
        state.last_delivery = copy.deepcopy(delivery)
        state.last_trace_id = trace_id
        state.updated_at = utc_now_iso()
        return {
            "trace_id": trace_id,
            "panel_id": panel_id,
            "bundle": bundle.summary(),
            "artifacts": artifacts,
            "delivery_status": delivery_status,
            "delivery": delivery,
        }

    async def play_text(
        self,
        panel_id: str,
        text: str,
        *,
        scroll: bool = True,
        frames_per_second: float = 12.0,
        foreground: str = "white",
        background: str = "black",
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(panel_id)
        studio = PixelAnimationStudio(state.profile.width, state.profile.height)
        bundle = studio.create_text_bundle(
            text,
            scroll=scroll,
            frames_per_second=frames_per_second,
            foreground=foreground,
            background=background,
            **self._orientation(state),
        )
        return await self.play_bundle(
            panel_id,
            bundle,
            execute=execute,
            request_id=request_id,
        )

    async def play_image(
        self,
        panel_id: str,
        image: Image.Image,
        *,
        fit_mode: str = "contain",
        background: str = "black",
        duration_ms: int = 1000,
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(panel_id)
        studio = PixelAnimationStudio(state.profile.width, state.profile.height)
        bundle = studio.create_image_bundle(
            image,
            fit_mode=fit_mode,
            background=background,
            duration_ms=duration_ms,
            **self._orientation(state),
        )
        return await self.play_bundle(
            panel_id,
            bundle,
            execute=execute,
            request_id=request_id,
        )

    async def play_image_base64(
        self,
        panel_id: str,
        value: str,
        *,
        fit_mode: str = "contain",
        background: str = "black",
        duration_ms: int = 1000,
        dither: str = "none",
        temporal: int = 0,
        auto_levels: bool = False,
        black_level: int = 0,
        white_level: int = 255,
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(panel_id)
        studio = PixelAnimationStudio(state.profile.width, state.profile.height)
        image = image_from_base64(value)
        if temporal and temporal >= 2:
            bundle = studio.create_temporal_image_bundle(
                image,
                subframes=temporal,
                fit_mode=fit_mode,
                background=background,
                auto_levels=auto_levels,
                black_point=black_level,
                white_point=white_level,
                **self._orientation(state),
            )
        else:
            bundle = studio.create_image_bundle(
                image,
                fit_mode=fit_mode,
                background=background,
                duration_ms=duration_ms,
                dither=dither,
                auto_levels=auto_levels,
                black_point=black_level,
                white_point=white_level,
                **self._orientation(state),
            )
        return await self.play_bundle(panel_id, bundle, execute=execute, request_id=request_id)

    async def play_animation_base64(
        self,
        panel_id: str,
        value: str,
        *,
        fps: float | None = None,
        max_frames: int | None = None,
        fit_mode: str = "contain",
        background: str = "black",
        dither: str = "ordered",
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Decode a base64 GIF/APNG, compile it to a bounded bundle, and play it.

        The frame count is clamped to the device frame-buffer budget (evenly
        subsampled, holds folded) so a long clip cannot blow the codec limit.
        """
        state = self._state(panel_id)
        studio = PixelAnimationStudio(state.profile.width, state.profile.height)
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"animation source is not valid base64: {exc}") from exc
        per_frame = max(1, state.profile.width * state.profile.height * 3 // 8)
        budget = max(1, PIXEL_BYTES_MAX // per_frame)
        limit = budget if max_frames is None else max_frames
        bundle = studio.create_gif_bundle(
            io.BytesIO(raw),
            fps=fps,
            max_frames=limit,
            fit_mode=fit_mode,
            background=background,
            dither=dither,
            **self._orientation(state),
        )
        return await self.play_bundle(panel_id, bundle, execute=execute, request_id=request_id)

    async def set_brightness(
        self,
        panel_id: str,
        percent: int,
        *,
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not 0 <= percent <= 100:
            raise ValueError("Brightness percent must be between 0 and 100")
        state = self._state(panel_id)
        should_execute = self.execute if execute is None else execute
        trace_id = request_id or self.traces.new_trace()
        runtime = ProtocolRuntime(state.profile)
        try:
            delivery = await runtime.send_control("brightness", percent, execute=should_execute)
            status = "transferred" if should_execute else "dry_run_packet_plan"
            self.traces.add(trace_id, "brightness", "ok", percent=percent, mode=status)
        except CodecError as exc:
            if should_execute:
                self.traces.add(trace_id, "brightness", "error", error=str(exc))
                raise
            delivery = {"status": "simulated", "reason": str(exc)}
            status = "simulated"
            self.traces.add(trace_id, "brightness", "simulated", percent=percent, reason=str(exc))
        state.brightness_percent = percent
        state.last_delivery = copy.deepcopy(delivery)
        state.last_trace_id = trace_id
        state.updated_at = utc_now_iso()
        return {
            "trace_id": trace_id,
            "panel_id": panel_id,
            "brightness_percent": percent,
            "delivery_status": status,
            "delivery": delivery,
        }

    async def set_power(
        self,
        panel_id: str,
        power: bool,
        *,
        execute: bool | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(panel_id)
        should_execute = self.execute if execute is None else execute
        trace_id = request_id or self.traces.new_trace()
        runtime = ProtocolRuntime(state.profile)
        try:
            delivery = await runtime.send_control("power", power, execute=should_execute)
            status = "transferred" if should_execute else "dry_run_packet_plan"
            self.traces.add(trace_id, "power", "ok", power=power, mode=status)
        except CodecError as exc:
            if should_execute:
                self.traces.add(trace_id, "power", "error", error=str(exc))
                raise
            delivery = {"status": "simulated", "reason": str(exc)}
            status = "simulated"
            self.traces.add(trace_id, "power", "simulated", power=power, reason=str(exc))
        state.power = bool(power)
        state.last_delivery = copy.deepcopy(delivery)
        state.last_trace_id = trace_id
        state.updated_at = utc_now_iso()
        return {
            "trace_id": trace_id,
            "panel_id": panel_id,
            "power": bool(power),
            "delivery_status": status,
            "delivery": delivery,
        }

    def get_status(
        self,
        panel_id: str | None = None,
        *,
        include_diagnostics: bool = False,
    ) -> dict[str, Any]:
        if panel_id is not None:
            states = [self._state(panel_id)]
        else:
            states = list(self.panels.values())
        result = {
            "execute_enabled": self.execute,
            "panels": [state.to_dict(include_profile=include_diagnostics) for state in states],
            "scheduled_jobs": self.scheduler.snapshot(),
        }
        if include_diagnostics:
            result["recent_trace_events"] = self.traces.recent(100)
            result["integrations"] = self.integrations.describe()
        return result


class OpenSignSDK(OpenSignRuntime):
    """SeedScript-compatible facade name."""
