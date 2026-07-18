from __future__ import annotations

from datetime import datetime, timezone

from social_bot.db import Database
from social_bot.history import (
    load_history_data,
    load_job_detail,
    render_history,
    render_job_detail,
)
from social_bot.jobs import JobQueue


async def test_history_search_filters_and_stats(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)

    cat_id = await queue.enqueue(
        "publish_youtube",
        {"path": "/videos/cat-short.mp4", "title": "Cat short", "privacy": "unlisted"},
        approved=True,
    )
    dog_id = await queue.enqueue(
        "publish_youtube",
        {"path": "/videos/dog-short.mp4", "title": "Dog short", "privacy": "private"},
    )
    await queue.finish(cat_id)
    await queue.fail(dog_id, "network timeout", retry=False)

    data = load_history_data(database_path, query="cat", status="done", period="all")

    assert data["stats"]["total"] == 2
    assert data["stats"]["done"] == 1
    assert data["stats"]["failed"] == 1
    assert data["stats"]["success_rate"] == 50.0
    assert [job["id"] for job in data["jobs"]] == [cat_id]
    assert data["jobs"][0]["title"] == "Cat short"

    page = render_history(data)
    assert "Job history" in page
    assert "Cat short" in page
    assert "dog-short" not in page
    assert f'/history/{cat_id}' in page


async def test_job_detail_includes_publication_and_metrics(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)
    job_id = await queue.enqueue(
        "publish_youtube",
        {"path": "/videos/clip.mp4", "title": "Clip", "privacy": "unlisted"},
        approved=True,
    )
    await queue.finish(job_id)

    connection = await database.connect()
    try:
        asset = await connection.execute(
            """
            INSERT INTO assets(local_path, license, owner_verified, niche, status)
            VALUES (?, 'owned', 1, 'test', 'published')
            """,
            ("/videos/clip.mp4",),
        )
        asset_id = int(asset.lastrowid)
        await connection.execute(
            """
            INSERT INTO publications(
                platform, asset_id, remote_id, remote_url, status, published_at, caption
            ) VALUES ('youtube', ?, 'video-123', 'https://example.invalid/video-123',
                      'published', ?, 'caption')
            """,
            (asset_id, datetime.now(timezone.utc).isoformat()),
        )
        await connection.execute(
            """
            INSERT INTO media_performance(
                platform, remote_id, niche, humor_style, views, likes, comments, captured_at
            ) VALUES ('youtube', 'video-123', 'test', 'none', 120, 8, 2, ?)
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        await connection.commit()
    finally:
        await connection.close()

    detail = load_job_detail(database_path, job_id)

    assert detail is not None
    assert detail["payload"]["title"] == "Clip"
    assert detail["publication"]["remote_id"] == "video-123"
    assert detail["metrics"]["views"] == 120

    page = render_job_detail(detail)
    assert f"Job #{job_id}" in page
    assert "video-123" in page
    assert "120" in page


def test_history_handles_missing_database(tmp_path) -> None:
    data = load_history_data(tmp_path / "missing.db", query="x", status="not-real", period="bad")

    assert data["jobs"] == []
    assert data["stats"]["total"] == 0
    assert data["filters"] == {"query": "x", "status": "", "period": "all"}
    assert load_job_detail(tmp_path / "missing.db", 1) is None
