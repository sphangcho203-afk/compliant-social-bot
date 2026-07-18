from __future__ import annotations

import aiosqlite
import pytest

from social_bot.cli import async_main


@pytest.mark.asyncio
async def test_publish_youtube_dry_run_records_receipt(tmp_path, capsys) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    database_path = tmp_path / "social.db"

    result = await async_main(
        [
            "publish-youtube",
            str(video),
            "--title",
            "Test upload",
            "--caption",
            "A safe dry run",
            "--db",
            str(database_path),
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "remote_id=dry-run:clip" in output

    async with aiosqlite.connect(database_path) as db:
        row = await (
            await db.execute(
                """
                SELECT platform, remote_id, remote_url, status, caption
                FROM publications
                """
            )
        ).fetchone()

    assert row == ("youtube", "dry-run:clip", None, "dry_run", "A safe dry run")


@pytest.mark.asyncio
async def test_publish_youtube_rejects_missing_video(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        await async_main(
            [
                "publish-youtube",
                str(tmp_path / "missing.mp4"),
                "--title",
                "Missing",
                "--db",
                str(tmp_path / "social.db"),
            ]
        )
