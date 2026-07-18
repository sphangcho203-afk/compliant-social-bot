from pathlib import Path

import pytest

from social_bot.platforms.youtube import YouTubeAdapter


@pytest.mark.asyncio
async def test_dry_run_publish_returns_synthetic_id(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test-video")

    result = await YouTubeAdapter(dry_run=True).publish_video(video, "A test caption")

    assert result.remote_id == "dry-run:clip"
    assert result.url is None


@pytest.mark.asyncio
async def test_publish_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"

    with pytest.raises(FileNotFoundError):
        await YouTubeAdapter(dry_run=True).publish_video(missing, "caption")


@pytest.mark.asyncio
async def test_dry_run_metrics_are_zeroed() -> None:
    metrics = await YouTubeAdapter(dry_run=True).fetch_metrics("dry-run:clip")

    assert metrics == {"views": 0, "likes": 0, "comments": 0}


@pytest.mark.asyncio
async def test_live_upload_requires_credentials(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test-video")

    with pytest.raises(RuntimeError, match="credentials"):
        await YouTubeAdapter(dry_run=False).publish_video(video, "caption")
