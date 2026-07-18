from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.worker import ContinuousWorker, WorkerOptions


@pytest.mark.asyncio
async def test_recovers_stale_running_job(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)
    job_id = await queue.enqueue("publish_youtube", {"path": "clip.mp4"}, approved=True)

    stale_lock = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    async with aiosqlite.connect(database_path) as conn:
        await conn.execute(
            "UPDATE jobs SET status='running', locked_at=? WHERE id=?",
            (stale_lock, job_id),
        )
        await conn.commit()

    recovered = await queue.recover_stale(
        stale_after_seconds=60,
        kind="publish_youtube",
    )
    job = await queue.get(job_id)

    assert recovered == 1
    assert job is not None
    assert job["status"] == "queued"
    assert job["locked_at"] is None


@pytest.mark.asyncio
async def test_worker_stops_gracefully(tmp_path) -> None:
    database = Database(tmp_path / "social.db")
    await database.initialize()
    queue = JobQueue(database)
    stop_event = asyncio.Event()
    calls = 0

    async def process_once() -> int:
        nonlocal calls
        calls += 1
        stop_event.set()
        return 0

    worker = ContinuousWorker(
        queue,
        process_once,
        options=WorkerOptions(poll_seconds=0.01, stale_after_seconds=60),
        stop_event=stop_event,
    )
    await asyncio.wait_for(worker.run(), timeout=1)

    assert calls == 1


def test_worker_options_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        WorkerOptions(poll_seconds=0).validate()
    with pytest.raises(ValueError):
        WorkerOptions(stale_after_seconds=-1).validate()
