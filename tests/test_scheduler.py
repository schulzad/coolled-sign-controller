import asyncio
from datetime import UTC, datetime, timedelta

from opensign.sdk.scheduler import InProcessScheduler


def test_scheduler_runs_due_jobs_and_reschedules_interval() -> None:
    scheduler = InProcessScheduler()
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    once = scheduler.add_at("desk-sign", {"type": "text", "value": "once"}, now)
    recurring = scheduler.add_interval(
        "desk-sign",
        {"type": "text", "value": "repeat"},
        60,
        start_at=now - timedelta(seconds=120),
    )

    async def run() -> list[dict]:
        return await scheduler.run_due(lambda job: {"ran": job.job_id}, now=now)

    results = asyncio.run(run())
    assert len(results) == 2
    assert scheduler.jobs[once.job_id].enabled is False
    assert scheduler.jobs[recurring.job_id].next_run > now
