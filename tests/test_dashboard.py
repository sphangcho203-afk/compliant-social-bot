from __future__ import annotations

from datetime import datetime, timezone

from social_bot.dashboard import load_dashboard_data, render_dashboard
from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.observability import ObservabilityStore


async def test_dashboard_loads_worker_and_queue(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    queue = JobQueue(database)
    await queue.enqueue("publish_youtube", {"path": "clip.mp4"})

    observability = ObservabilityStore(database)
    await observability.initialize()
    await observability.heartbeat("youtube-publisher", state="idle", pid=321)

    data = load_dashboard_data(database_path, "youtube-publisher")

    assert data["worker"]["status"] == "idle"
    assert data["worker"]["pid"] == 321
    assert data["queue"]["queued"] == 1


def test_dashboard_renders_safe_mobile_html() -> None:
    data = {
        "worker": {
            "name": "youtube-publisher",
            "status": "idle",
            "age_seconds": 3,
        },
        "queue": {"queued": 1, "running": 0, "done": 2, "failed": 0},
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

    page = render_dashboard(data)

    assert "Compliant Social Bot" in page
    assert "viewport" in page
    assert "&lt;clip&gt;.mp4" in page
    assert "refresh" in page
