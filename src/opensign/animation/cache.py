from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import __version__ as PILLOW_VERSION

from opensign.contracts import FrameBundle

# Bump this whenever a rendering algorithm changes in a way that should
# invalidate bundles produced by an older release.
RENDER_CACHE_VERSION = 1


def default_render_cache_dir() -> Path:
    """Return the user-level cache directory, honoring the usual overrides."""
    configured = os.environ.get("OPENSIGN_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()
    return base / "opensign-coolled" / "renders"


def _json_value(value: Any) -> Any:
    """Normalize common option values into a stable JSON representation."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_cache_key(
    source: str | Path,
    *,
    kind: str,
    parameters: Mapping[str, Any],
) -> str:
    """Hash source bytes and every rendering input into one cache key."""
    source_path = Path(source)
    identity = {
        "cache_version": RENDER_CACHE_VERSION,
        "pillow_version": PILLOW_VERSION,
        "kind": kind,
        "source_sha256": _file_sha256(source_path),
        "parameters": _json_value(parameters),
    }
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderCacheResult:
    bundle: FrameBundle
    key: str
    path: Path
    hit: bool
    write_error: str | None = None


class RenderBundleCache:
    """Persistent cache of fully rendered, transport-neutral frame bundles."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser() if root is not None else default_render_cache_dir()

    def get_or_create(
        self,
        source: str | Path,
        *,
        kind: str,
        parameters: Mapping[str, Any],
        render: Callable[[], FrameBundle],
    ) -> RenderCacheResult:
        key = render_cache_key(source, kind=kind, parameters=parameters)
        path = self.root / f"{kind}-{key}.json"
        if path.is_file():
            try:
                return RenderCacheResult(FrameBundle.load(path), key, path, hit=True)
            except Exception:
                # A truncated/stale cache entry is disposable; rebuild it below.
                try:
                    path.unlink()
                except OSError:
                    pass

        bundle = render()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                bundle.save(temporary)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as exc:
            return RenderCacheResult(bundle, key, path, hit=False, write_error=str(exc))
        return RenderCacheResult(bundle, key, path, hit=False)
