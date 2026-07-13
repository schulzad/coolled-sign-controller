from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class TraceEvent:
    trace_id: str
    stage: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "status": self.status,
            "data": dict(self.data),
        }


class TraceStore:
    def __init__(self, jsonl_path: str | Path | None = None):
        self.events: list[TraceEvent] = []
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None

    def new_trace(self) -> str:
        return str(uuid4())

    def add(
        self,
        trace_id: str,
        stage: str,
        status: str,
        **data: Any,
    ) -> TraceEvent:
        event = TraceEvent(trace_id=trace_id, stage=stage, status=status, data=data)
        self.events.append(event)
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return event

    def get(self, trace_id: str) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events if event.trace_id == trace_id]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events[-max(0, limit) :]]
