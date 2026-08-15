from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(slots=True)
class EvidenceNode:
    node_id: str
    kind: str
    data: dict[str, Any]
    parents: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "data": self.data,
            "parents": self.parents,
            "created_at": self.created_at,
        }


class EvidenceStore:
    """JSON evidence records and a small provenance graph under the repository evidence tree."""

    def __init__(self, root: str | Path = "evidence") -> None:
        self.root = Path(root)
        self.graph_path = self.root / "breadcrumbs.json"

    def _write(self, directory: str, identifier: str, data: Mapping[str, Any]) -> Path:
        target = self.root / directory / f"{identifier}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(data), indent=2) + "\n", encoding="utf-8")
        return target

    def record_hardware(
        self,
        panel_id: str,
        *,
        pcb_markings: list[str] | None = None,
        image_references: list[str] | None = None,
        observations: Mapping[str, Any] | None = None,
    ) -> Path:
        return self._write(
            "hardware",
            panel_id,
            {
                "schema_version": "2.3",
                "type": "hardware_record",
                "panel_id": panel_id,
                "pcb_markings": list(pcb_markings or []),
                "image_references": list(image_references or []),
                "observations": dict(observations or {}),
                "created_at": _now(),
            },
        )

    def record_capture_provenance(
        self,
        capture_id: str,
        *,
        panel_id: str,
        scenario: str,
        capture_source: str,
        test_variables: Mapping[str, Any] | None = None,
        capture_path: str | Path | None = None,
        application: Mapping[str, Any] | None = None,
        notes: list[str] | None = None,
    ) -> Path:
        checksum = None
        if capture_path is not None and Path(capture_path).exists():
            checksum = sha256_file(capture_path)
        return self._write(
            "captures",
            capture_id,
            {
                "$schema": "../../schema/capture_provenance.schema.json",
                "schema_version": "2.3",
                "capture_id": capture_id,
                "panel_id": panel_id,
                "scenario": scenario,
                "capture_source": capture_source,
                "application": dict(application or {}),
                "test_variables": dict(test_variables or {}),
                "capture_path": str(capture_path) if capture_path is not None else None,
                "sha256": checksum,
                "started_at": None,
                "ended_at": None,
                "recorded_at": _now(),
                "notes": list(notes or []),
            },
        )

    def add_breadcrumb(
        self,
        node_id: str,
        *,
        kind: str,
        data: Mapping[str, Any],
        parents: list[str] | None = None,
    ) -> None:
        graph = self._load_graph()
        graph[node_id] = EvidenceNode(
            node_id=node_id,
            kind=kind,
            data=dict(data),
            parents=list(parents or []),
        ).to_dict()
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

    def breadcrumb_path(self, node_id: str, max_depth: int = 10) -> list[dict[str, Any]]:
        graph = self._load_graph()
        output: list[dict[str, Any]] = []
        queue: list[tuple[str, int]] = [(node_id, 0)]
        visited: set[str] = set()
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            node = graph.get(current)
            if node is None:
                output.append({"node_id": current, "missing": True, "depth": depth})
                continue
            item = dict(node)
            item["depth"] = depth
            output.append(item)
            queue.extend((parent, depth + 1) for parent in node.get("parents", []))
        return output

    def _load_graph(self) -> dict[str, Any]:
        if not self.graph_path.exists():
            return {}
        try:
            return json.loads(self.graph_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
