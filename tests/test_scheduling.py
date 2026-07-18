from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from social_bot.cli import async_main
from social_bot.db import Database
from social_bot.jobs import JobQueue


@pytest.mark.asyncio
async def test_duplicate_queue_requests_reuse_job(tmp_path, capsys) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"owned-media")
    database_path = tmp_path / "social.db"
    command = [
        "queue-youtube",
        str(video),
        "--title",
        "Same upload",
        "--db",
        str(database_path),
    ]

    await async_main(command)
    first = capsys.readouterr().out
    await async_main(command)
    second = capsys.readouterr().out

    assert "job_id=1" in first
    assert "created=true" in first
    assert "job_id=1" in second
    assert "created=false" in second

    async with aiosqlite.connect(database_path) as db:
        count = await (await db.execute("SELECT COUNT(*) FROM jobs")).fetchone()
    assert count == (1,)


@pytest.mark.asyncio
async def test_future_job_is_not_claimed(tmp_path, capsys) -> None:
    video = tmp_path / "future.mp4"
    video.write_bytes(b"owned-media")
    database_path = tmp_path / "social.db"
    run_after = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    await async_main(
        [
            "queue-youtube",
            str(video),
            "--title",
            "Tomorrow",
            "--run-after",
            run_after,
            "--db",
            str(database_path),
        ]
    )
    capsys.readouterr()
    await async_main(["approve-job", "1", "--db", str(database_path)])
    capsys.readouterr()
    await async_main(["run-youtube-publisher", "--db", str(database_path)])

    assert "processed=0" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_live_worker_respects_platform_cooldown(tmp_path, capsys) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"owned-media")
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    await database.record_publication(
        platform="youtube",
        local_path=video,
        remote_id="existing-video",
        remote_url="https://www.youtube.com/watch?v=existing-video",
        status="published",
        caption="Existing upload",
    )
    queue = JobQueue(database)
    job_id = await queue.enqueue(
        "publish_youtube",
        {
            "path": str(video),
            "title": "Blocked upload",
            "caption": "",
            "privacy": "unlisted",
        },
        approved=True,
    )

    await async_main(
        [
            "run-youtube-publisher",
            "--live",
            "--cooldown-hours",
            "48",
            "--db",
            str(database_path),
        ]
    )
    output = capsys.readouterr().out

    assert "processed=0" in output
    assert "cooldown_seconds=" in output
    job = await queue.get(job_id)
    assert job is not None
    assert job["status"] == "queued"
