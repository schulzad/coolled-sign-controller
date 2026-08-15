from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class ScheduledJob:
    panel_id: str
    content: Any
    next_run: datetime
    interval_seconds: float | None = None
    priority: int = 0
    enabled: bool = True
    job_id: str = field(default_factory=lambda: str(uuid4()))
    last_run: datetime | None = None
    run_count: int = 0

    def __post_init__(self) -> None:
        if self.next_run.tzinfo is None:
            self.next_run = self.next_run.replace(tzinfo=UTC)
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "panel_id": self.panel_id,
            "content": self.content,
            "next_run": self.next_run.isoformat(),
            "interval_seconds": self.interval_seconds,
            "priority": self.priority,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
        }


class InProcessScheduler:
    """Small scheduler primitive; durable storage and cron parsing are extension points."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}

    def add_at(
        self,
        panel_id: str,
        content: Any,
        when: datetime,
        *,
        priority: int = 0,
    ) -> ScheduledJob:
        job = ScheduledJob(panel_id=panel_id, content=content, next_run=when, priority=priority)
        self.jobs[job.job_id] = job
        return job

    def add_interval(
        self,
        panel_id: str,
        content: Any,
        interval_seconds: float,
        *,
        start_at: datetime | None = None,
        priority: int = 0,
    ) -> ScheduledJob:
        job = ScheduledJob(
            panel_id=panel_id,
            content=content,
            next_run=start_at or (utc_now() + timedelta(seconds=interval_seconds)),
            interval_seconds=interval_seconds,
            priority=priority,
        )
        self.jobs[job.job_id] = job
        return job

    def remove(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None

    def due(self, now: datetime | None = None) -> list[ScheduledJob]:
        current = now or utc_now()
        return sorted(
            [job for job in self.jobs.values() if job.enabled and job.next_run <= current],
            key=lambda job: (-job.priority, job.next_run),
        )

    async def run_due(
        self,
        callback: Callable[[ScheduledJob], Any | Awaitable[Any]],
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or utc_now()
        results: list[dict[str, Any]] = []
        for job in self.due(current):
            outcome = callback(job)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            job.last_run = current
            job.run_count += 1
            if job.interval_seconds is None:
                job.enabled = False
            else:
                while job.next_run <= current:
                    job.next_run += timedelta(seconds=job.interval_seconds)
            results.append({"job": job.to_dict(), "result": outcome})
        return results

    def snapshot(self) -> list[dict[str, Any]]:
        return [job.to_dict() for job in sorted(self.jobs.values(), key=lambda item: item.next_run)]
