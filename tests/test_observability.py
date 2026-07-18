from __future__ import annotations

import json

import pytest

from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.observability import ObservabilityStore
from social_bot.status import async_main


@pytest.mark.asyncio
async def test_status_reports_heartbeat_and_queue(tmp_path, capsys) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)
    await queue.enqueue("publish_youtube", {"path": "clip.mp4"})

    store = ObservabilityStore(database)
    await store.initialize()
    await store.heartbeat("youtube-publisher", state="idle", pid=123)

    result = await async_main(["--db", str(database_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["worker"]["status"] == "idle"
    assert payload["queue"]["queued"] == 1


@pytest.mark.asyncio
async def test_status_is_unhealthy_without_heartbeat(tmp_path, capsys) -> None:
    result = await async_main(["--db", str(tmp_path / "social.db"), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["worker"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_failed_job_inspection(tmp_path) -> None:
    database = Database(tmp_path / "social.db")
    await database.initialize()
    queue = JobQueue(database)
    job_id = await queue.enqueue("publish_youtube", {"path": "missing.mp4"})
    await queue.fail(job_id, "upload failed", retry=False)

    store = ObservabilityStore(database)
    await store.initialize()
    failed = await store.failed_jobs()

    assert failed[0]["id"] == job_id
    assert failed[0]["last_error"] == "upload failed"
