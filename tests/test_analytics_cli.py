from __future__ import annotations

import aiosqlite
import pytest

from social_bot import cli
from social_bot.db import Database


class FakeYouTubeAdapter:
    name = "youtube"

    def __init__(self, **_: object) -> None:
        pass

    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        assert remote_id in {"video-one", "video-two"}
        return {"views": 120, "likes": 9, "comments": 3}


@pytest.mark.asyncio
async def test_sync_single_video_records_snapshot(tmp_path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "social.db"
    monkeypatch.setattr(cli, "load_youtube_credentials", lambda *_: object())
    monkeypatch.setattr(cli, "YouTubeAdapter", FakeYouTubeAdapter)

    result = await cli.async_main(
        [
            "sync-youtube-analytics",
            "--video-id",
            "video-one",
            "--db",
            str(database_path),
        ]
    )

    assert result == 0
    assert "synced=1" in capsys.readouterr().out
    async with aiosqlite.connect(database_path) as db:
        row = await (
            await db.execute(
                """
                SELECT platform, remote_id, views, likes, comments
                FROM media_performance
                """
            )
        ).fetchone()
    assert row == ("youtube", "video-one", 120, 9, 3)


@pytest.mark.asyncio
async def test_sync_all_skips_dry_runs(tmp_path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "social.db"
    database = Database(database_path)
    await database.initialize()
    for remote_id, status in (
        ("video-one", "published"),
        ("video-two", "published"),
        ("dry-run:clip", "dry_run"),
    ):
        await database.record_publication(
            platform="youtube",
            local_path=tmp_path / f"{remote_id}.mp4",
            remote_id=remote_id,
            remote_url=None,
            status=status,
            caption="",
        )

    monkeypatch.setattr(cli, "load_youtube_credentials", lambda *_: object())
    monkeypatch.setattr(cli, "YouTubeAdapter", FakeYouTubeAdapter)

    result = await cli.async_main(
        ["sync-youtube-analytics", "--all", "--db", str(database_path)]
    )

    assert result == 0
    assert "synced=2" in capsys.readouterr().out
    async with aiosqlite.connect(database_path) as db:
        count = await (await db.execute("SELECT COUNT(*) FROM media_performance")).fetchone()
    assert count == (2,)
