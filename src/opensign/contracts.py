from __future__ import annotations

import base64
import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ContractError(ValueError):
    """Raised when a shared OpenSign contract is invalid."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def stable_frame_hash(frame: bytes) -> str:
    return hashlib.sha256(frame).hexdigest()


def default_device_profile(panel_id: str = "desk-sign", width: int = 48, height: int = 12) -> dict[str, Any]:
    """Return a conservative profile with no device-specific protocol claims."""
    return {
        "$schema": "schema/device_profile.schema.json",
        "schema_version": "2.3",
        "panel_id": panel_id,
        "device_id": None,
        "advertised_name": None,
        "protocol_family": "unknown",
        "confidence": 0.0,
        "dimensions": {
            "width": width,
            "height": height,
            "source": "user_asserted",
            "verified": False,
        },
        "advertisement": {
            "rssi": None,
            "manufacturer_data": {},
            "service_data": {},
            "service_uuids": [],
        },
        "services": [],
        "characteristics": [],
        "write_characteristic": None,
        "notify_characteristic": None,
        "characteristic_candidates": {"write": [], "notify": []},
        "connection": {
            "mtu": None,
            "maximum_chunk_size": None,
            "inter_chunk_delay_ms": 0,
            "write_with_response": False,
            "reconnect_policy": "on_failure",
        },
        "capabilities": {
            "brightness": False,
            "power": False,
            "static_image": False,
            "stored_animation": False,
            "frame_streaming": False,
            "asset_cache": False,
        },
        "protocol": {
            "codec": "capture_required",
            "status": "unverified",
            "encryption": {"mode": "unknown", "evidence": []},
            "commands": {},
            "frame_transfer": {"status": "unverified", "mode": "unknown"},
        },
        "hardware": {
            "pcb_revision": None,
            "markings": [],
            "chipset_candidates": [],
            "image_references": [],
        },
        "evidence": [],
        "unknowns": [
            "BLE device identifier",
            "GATT write and notify characteristics",
            "packet framing and command identifiers",
            "session transforms or encryption behavior",
            "pixel order and native color encoding",
            "safe transfer pacing and cache behavior",
        ],
        "timestamps": {"created_at": None, "updated_at": None},
    }


class DeviceProfile:
    """Validated mapping wrapper that preserves profile-specific extension fields."""

    def __init__(self, data: Mapping[str, Any]):
        self._data = copy.deepcopy(dict(data))
        self.validate()

    @classmethod
    def load(cls, path: str | Path) -> DeviceProfile:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContractError(f"Device profile not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ContractError(f"Invalid JSON in device profile {source}: {exc}") from exc
        return cls(data)

    @classmethod
    def blank(cls, panel_id: str = "desk-sign", width: int = 48, height: int = 12) -> DeviceProfile:
        return cls(default_device_profile(panel_id=panel_id, width=width, height=height))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._data.setdefault("timestamps", {})["updated_at"] = utc_now_iso()
        if not self._data["timestamps"].get("created_at"):
            self._data["timestamps"]["created_at"] = self._data["timestamps"]["updated_at"]
        target.write_text(json.dumps(self._data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        return target

    def validate(self) -> None:
        required = (
            "schema_version",
            "panel_id",
            "protocol_family",
            "confidence",
            "dimensions",
            "connection",
            "capabilities",
            "protocol",
            "evidence",
            "unknowns",
        )
        missing = [key for key in required if key not in self._data]
        if missing:
            raise ContractError(f"Device profile is missing required fields: {', '.join(missing)}")

        panel_id = self._data["panel_id"]
        if not isinstance(panel_id, str) or not panel_id.strip():
            raise ContractError("panel_id must be a non-empty string")

        dimensions = self._data["dimensions"]
        if not isinstance(dimensions, Mapping):
            raise ContractError("dimensions must be an object")
        for key in ("width", "height"):
            value = dimensions.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractError(f"dimensions.{key} must be a positive integer")

        confidence = self._data["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ContractError("confidence must be between 0 and 1")

        connection = self._data["connection"]
        if not isinstance(connection, Mapping):
            raise ContractError("connection must be an object")
        max_chunk = connection.get("maximum_chunk_size")
        if max_chunk is not None and (
            not isinstance(max_chunk, int) or isinstance(max_chunk, bool) or max_chunk <= 0
        ):
            raise ContractError("connection.maximum_chunk_size must be null or a positive integer")
        delay = connection.get("inter_chunk_delay_ms", 0)
        if not isinstance(delay, (int, float)) or isinstance(delay, bool) or delay < 0:
            raise ContractError("connection.inter_chunk_delay_ms must be non-negative")
        if not isinstance(connection.get("write_with_response", False), bool):
            raise ContractError("connection.write_with_response must be boolean")

        protocol = self._data["protocol"]
        if not isinstance(protocol, Mapping):
            raise ContractError("protocol must be an object")
        if not isinstance(protocol.get("codec"), str) or not protocol.get("codec"):
            raise ContractError("protocol.codec must be a non-empty string")
        status = protocol.get("status")
        if status not in {"unverified", "experimental", "verified", "rejected"}:
            raise ContractError("protocol.status must be unverified, experimental, verified, or rejected")
        if status == "verified" and protocol.get("codec") == "capture_required":
            raise ContractError("A verified protocol cannot use the capture_required codec")

        for key in ("services", "characteristics", "evidence", "unknowns"):
            if not isinstance(self._data.get(key, []), list):
                raise ContractError(f"{key} must be an array")

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = copy.deepcopy(value)
        self.validate()

    @property
    def panel_id(self) -> str:
        return str(self._data["panel_id"])

    @property
    def device_id(self) -> str | None:
        value = self._data.get("device_id")
        return str(value) if value else None

    @property
    def advertised_name(self) -> str | None:
        value = self._data.get("advertised_name")
        return str(value) if value else None

    @property
    def width(self) -> int:
        return int(self._data["dimensions"]["width"])

    @property
    def height(self) -> int:
        return int(self._data["dimensions"]["height"])

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def protocol(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["protocol"])

    @property
    def connection(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["connection"])

    @property
    def write_characteristic(self) -> str | None:
        value = self._data.get("write_characteristic")
        return str(value) if value else None

    @property
    def notify_characteristic(self) -> str | None:
        value = self._data.get("notify_characteristic")
        return str(value) if value else None

    def require_device_id(self) -> str:
        if not self.device_id:
            raise ContractError("device_id is not configured in the device profile")
        return self.device_id

    def require_write_characteristic(self) -> str:
        if not self.write_characteristic:
            raise ContractError("write_characteristic is not configured in the device profile")
        return self.write_characteristic


@dataclass(slots=True)
class FrameBundle:
    width: int
    height: int
    frames: list[bytes]
    frame_durations_ms: list[int]
    color_mode: str = "rgb888"
    frames_per_second: float | None = None
    loop_mode: str = "loop"
    codec_hint: str = "profile_native"
    metadata: dict[str, Any] = field(default_factory=dict)
    frame_hashes: list[str] = field(default_factory=list)
    schema_version: str = "2.3"

    def __post_init__(self) -> None:
        self.frames = [bytes(frame) for frame in self.frames]
        if not self.frame_hashes:
            self.frame_hashes = [stable_frame_hash(frame) for frame in self.frames]
        self.validate()

    @classmethod
    def from_images(
        cls,
        images: Iterable[Any],
        frame_durations_ms: Iterable[int],
        *,
        frames_per_second: float | None = None,
        loop_mode: str = "loop",
        codec_hint: str = "profile_native",
        metadata: Mapping[str, Any] | None = None,
    ) -> FrameBundle:
        image_list = list(images)
        if not image_list:
            raise ContractError("At least one image is required")
        normalized = [image.convert("RGB") for image in image_list]
        width, height = normalized[0].size
        if any(image.size != (width, height) for image in normalized):
            raise ContractError("All images in a frame bundle must have identical dimensions")
        frames = [image.tobytes() for image in normalized]
        return cls(
            width=width,
            height=height,
            frames=frames,
            frame_durations_ms=list(frame_durations_ms),
            color_mode="rgb888",
            frames_per_second=frames_per_second,
            loop_mode=loop_mode,
            codec_hint=codec_hint,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> FrameBundle:
        if data.get("frame_encoding") != "base64":
            raise ContractError("Only base64 frame-bundle JSON is supported")
        try:
            frames = [base64.b64decode(item, validate=True) for item in data["frames"]]
        except (KeyError, ValueError) as exc:
            raise ContractError("Invalid base64 frames in frame bundle") from exc
        return cls(
            schema_version=str(data.get("schema_version", "2.3")),
            width=int(data["width"]),
            height=int(data["height"]),
            color_mode=str(data.get("color_mode", "rgb888")),
            frames=frames,
            frame_hashes=[str(item) for item in data.get("frame_hashes", [])],
            frame_durations_ms=[int(item) for item in data["frame_durations_ms"]],
            frames_per_second=(
                float(data["frames_per_second"]) if data.get("frames_per_second") is not None else None
            ),
            loop_mode=str(data.get("loop_mode", "loop")),
            codec_hint=str(data.get("codec_hint", "profile_native")),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> FrameBundle:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContractError(f"Frame bundle not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ContractError(f"Invalid frame-bundle JSON {source}: {exc}") from exc
        return cls.from_json_dict(data)

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ContractError("Frame-bundle dimensions must be positive")
        if self.color_mode != "rgb888":
            raise ContractError("The scaffold currently stores transport-neutral frames as rgb888")
        if not self.frames:
            raise ContractError("Frame bundle must contain at least one frame")
        expected = self.width * self.height * 3
        for index, frame in enumerate(self.frames):
            if len(frame) != expected:
                raise ContractError(
                    f"Frame {index} contains {len(frame)} bytes; expected {expected} for {self.width}x{self.height} RGB888"
                )
        if len(self.frame_durations_ms) != len(self.frames):
            raise ContractError("frame_durations_ms length must match frames length")
        if any(duration <= 0 for duration in self.frame_durations_ms):
            raise ContractError("Every frame duration must be positive")
        if len(self.frame_hashes) != len(self.frames):
            raise ContractError("frame_hashes length must match frames length")
        calculated = [stable_frame_hash(frame) for frame in self.frames]
        if calculated != self.frame_hashes:
            raise ContractError("One or more frame hashes do not match the frame bytes")
        if self.frames_per_second is not None and self.frames_per_second <= 0:
            raise ContractError("frames_per_second must be positive when provided")
        if self.loop_mode not in {"once", "loop", "ping_pong"}:
            raise ContractError("loop_mode must be once, loop, or ping_pong")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "$schema": "schema/frame_bundle.schema.json",
            "schema_version": self.schema_version,
            "width": self.width,
            "height": self.height,
            "color_mode": self.color_mode,
            "frame_encoding": "base64",
            "frames": [base64.b64encode(frame).decode("ascii") for frame in self.frames],
            "frame_hashes": list(self.frame_hashes),
            "frame_durations_ms": list(self.frame_durations_ms),
            "frames_per_second": self.frames_per_second,
            "loop_mode": self.loop_mode,
            "codec_hint": self.codec_hint,
            "metadata": copy.deepcopy(self.metadata),
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_json_dict(), indent=2) + "\n", encoding="utf-8")
        return target

    def to_images(self) -> list[Any]:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("Pillow is required to convert frame bundles to images") from exc
        return [Image.frombytes("RGB", (self.width, self.height), frame) for frame in self.frames]

    def summary(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "frames": len(self.frames),
            "bytes_per_frame": self.width * self.height * 3,
            "total_frame_bytes": sum(len(frame) for frame in self.frames),
            "duration_ms": sum(self.frame_durations_ms),
            "frames_per_second": self.frames_per_second,
            "loop_mode": self.loop_mode,
            "color_mode": self.color_mode,
        }


@dataclass(slots=True)
class PlaybackRequest:
    panel_id: str
    content: dict[str, Any]
    playback_mode: str = "replace"
    duration_seconds: float = 0.0
    priority: int = 0
    render_options: dict[str, Any] = field(default_factory=dict)
    delivery_options: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.request_id:
            raise ContractError("request_id is required")
        if not self.panel_id:
            raise ContractError("panel_id is required")
        if not isinstance(self.content, dict) or "type" not in self.content or "value" not in self.content:
            raise ContractError("content must contain type and value")
        if self.playback_mode not in {"replace", "queue", "overlay", "priority"}:
            raise ContractError("Invalid playback_mode")
        if self.duration_seconds < 0:
            raise ContractError("duration_seconds cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": "schema/playback_request.schema.json",
            "request_id": self.request_id,
            "panel_id": self.panel_id,
            "content": copy.deepcopy(self.content),
            "playback_mode": self.playback_mode,
            "duration_seconds": self.duration_seconds,
            "priority": self.priority,
            "render_options": copy.deepcopy(self.render_options),
            "delivery_options": copy.deepcopy(self.delivery_options),
        }
