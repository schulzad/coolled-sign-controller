from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from opensign.contracts import DeviceProfile, FrameBundle

from .runtime import OpenSignRuntime


class TextRequest(BaseModel):
    panel_id: str = "desk-sign"
    text: str = Field(min_length=1, max_length=512)
    scroll: bool = True
    fps: float = Field(default=12.0, gt=0, le=60)
    foreground: str = "white"
    background: str = "black"


class ImageRequest(BaseModel):
    panel_id: str = "desk-sign"
    image_base64: str = Field(min_length=1)
    fit_mode: str = Field(default="contain", pattern="^(contain|cover|stretch)$")
    background: str = "black"
    duration_ms: int = Field(default=1000, ge=1, le=600000)


class BrightnessRequest(BaseModel):
    panel_id: str = "desk-sign"
    percent: int = Field(ge=0, le=100)


class PowerRequest(BaseModel):
    panel_id: str = "desk-sign"
    power: bool


class BundleRequest(BaseModel):
    panel_id: str = "desk-sign"
    frame_bundle: dict[str, Any]


def create_app(
    *,
    profile_path: str | Path = "device_profile.json",
    panel_id: str | None = None,
    execute: bool = False,
    artifact_dir: str | Path | None = "artifacts/api",
) -> FastAPI:
    runtime = OpenSignRuntime(execute=execute, artifact_dir=artifact_dir)
    profile = DeviceProfile.load(profile_path)
    runtime.register_panel(profile, panel_id=panel_id)

    app = FastAPI(
        title="OpenSign local API",
        version="0.1.0",
        description=(
            "Local orchestration for profile-driven LED sign rendering and guarded BLE delivery. "
            "Physical writes are disabled unless the server is started with --execute."
        ),
    )
    app.state.runtime = runtime

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": "OpenSign local API",
            "version": "0.1.0",
            "execute_enabled": runtime.execute,
            "routes": ["/text", "/image", "/animation", "/brightness", "/power", "/status"],
        }

    @app.get("/status")
    async def status(
        requested_panel_id: str | None = Query(default=None, alias="panel_id"),
        diagnostics: bool = False,
    ) -> dict[str, Any]:
        try:
            return runtime.get_status(requested_panel_id, include_diagnostics=diagnostics)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/text")
    async def text(request: TextRequest) -> dict[str, Any]:
        try:
            return await runtime.play_text(
                request.panel_id,
                request.text,
                scroll=request.scroll,
                frames_per_second=request.fps,
                foreground=request.foreground,
                background=request.background,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/image")
    async def image(request: ImageRequest) -> dict[str, Any]:
        try:
            return await runtime.play_image_base64(
                request.panel_id,
                request.image_base64,
                fit_mode=request.fit_mode,
                background=request.background,
                duration_ms=request.duration_ms,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/animation")
    @app.post("/scene")
    async def animation(request: BundleRequest) -> dict[str, Any]:
        try:
            bundle = FrameBundle.from_json_dict(request.frame_bundle)
            return await runtime.play_bundle(request.panel_id, bundle)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/brightness")
    async def brightness(request: BrightnessRequest) -> dict[str, Any]:
        try:
            return await runtime.set_brightness(request.panel_id, request.percent)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/power")
    async def power(request: PowerRequest) -> dict[str, Any]:
        try:
            return await runtime.set_power(request.panel_id, request.power)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
