from __future__ import annotations

from datetime import datetime, timezone

import pytest

from social_bot.dashboard import load_dashboard_data, render_dashboard
from social_bot.dashboard_control import (
    QueueActionError,
    approve_job,
    cancel_job,
    create_youtube_job,
    retry_job,
)
from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.observability import ObservabilityStore


async def test_dashboard_loads_worker_and_queue(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)
    await queue.enqueue("publish_youtube", {"path": "clip.mp4", "title": "Clip"})

    observability = ObservabilityStore(database)
    await observability.initialize()
    await observability.heartbeat("youtube-publisher", state="idle", pid=321)

    data = load_dashboard_data(database_path, "youtube-publisher")

    assert data["worker"]["status"] == "idle"
    assert data["worker"]["pid"] == 321
    assert data["queue"]["queued"] == 1
    assert data["jobs"][0]["title"] == "Clip"


def test_dashboard_renders_safe_mobile_html() -> None:
    data = {
        "worker": {
            "name": "youtube-publisher",
            "status": "idle",
            "age_seconds": 3,
        },
        "queue": {"queued": 1, "running": 0, "done": 2, "failed": 0, "cancelled": 0},
        "jobs": [],
        "failed_jobs": [],
        "publications": [
            {
                "id": 1,
                "platform": "youtube",
                "status": "dry_run",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "local_path": "<clip>.mp4",
            }
        ],
        "metrics": [],
    }

    page = render_dashboard(data, controls_enabled=True)

    assert "Compliant Social Bot" in page
    assert "viewport" in page
    assert "Queue manager" in page
    assert "Queue for approval" in page
    assert "&lt;clip&gt;.mp4" in page
    assert "refresh" in page


async def test_dashboard_queue_actions(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"owned video")

    job_id, created = create_youtube_job(
        database_path,
        {
            "path": str(video),
            "title": "Owned clip",
            "caption": "Test",
            "privacy": "unlisted",
            "run_after": "2026-07-20T18:00:00+05:30",
        },
    )
    duplicate_id, duplicate_created = create_youtube_job(
        database_path,
        {
            "path": str(video),
            "title": "Owned clip",
            "caption": "Test",
            "privacy": "unlisted",
            "run_after": "",
        },
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate_id == job_id

    approve_job(database_path, job_id)
    job = await JobQueue(database).get(job_id)
    assert job is not None
    assert job["approved"] == 1

    await JobQueue(database).fail(job_id, "network", retry=False)
    retry_job(database_path, job_id)
    job = await JobQueue(database).get(job_id)
    assert job is not None
    assert job["status"] == "queued"
    assert job["last_error"] is None

    cancel_job(database_path, job_id)
    job = await JobQueue(database).get(job_id)
    assert job is not None
    assert job["status"] == "cancelled"


def test_dashboard_queue_rejects_invalid_input(tmp_path) -> None:
    with pytest.raises(QueueActionError, match="Video file not found"):
        create_youtube_job(
            tmp_path / "social.db",
            {"path": str(tmp_path / "missing.mp4"), "title": "Missing"},
        )
