from __future__ import annotations

import aiosqlite
import pytest

from social_bot.cli import async_main


@pytest.mark.asyncio
async def test_publication_requires_approval(tmp_path, capsys) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"owned-media")
    database_path = tmp_path / "social.db"

    await async_main(
        [
            "queue-youtube",
            str(video),
            "--title",
            "Queued upload",
            "--caption",
            "Approved media",
            "--db",
            str(database_path),
        ]
    )
    queued_output = capsys.readouterr().out
    assert "job_id=1" in queued_output
    assert "approved=false" in queued_output

    await async_main(["run-youtube-publisher", "--db", str(database_path)])
    assert "processed=0" in capsys.readouterr().out

    await async_main(["approve-job", "1", "--db", str(database_path)])
    assert "approved=true" in capsys.readouterr().out

    await async_main(["run-youtube-publisher", "--db", str(database_path)])
    output = capsys.readouterr().out
    assert "processed=1" in output
    assert "remote_id=dry-run:clip" in output

    async with aiosqlite.connect(database_path) as db:
        job = await (await db.execute("SELECT status, approved FROM jobs WHERE id=1")).fetchone()
        publication = await (
            await db.execute(
                "SELECT remote_id, status, caption FROM publications ORDER BY id DESC LIMIT 1"
            )
        ).fetchone()

    assert job == ("done", 1)
    assert publication == ("dry-run:clip", "dry_run", "Approved media")


@pytest.mark.asyncio
async def test_approve_rejects_unknown_job(tmp_path) -> None:
    with pytest.raises(LookupError):
        await async_main(
            ["approve-job", "999", "--db", str(tmp_path / "social.db")]
        )
