from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from social_bot.db import Database
from social_bot.platforms.base import PlatformAdapter, PublishResult
from social_bot.platforms.registry import PlatformRegistry
from social_bot.publishing import PublicationRequest, Publisher


class FakeAdapter(PlatformAdapter):
    name = "fake"

    async def publish_video(self, path: Path, caption: str) -> PublishResult:
        return PublishResult(remote_id=f"fake:{path.stem}", url="https://example.test/item")

    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        return {"views": 1, "likes": 2, "comments": 3}


def test_registry_creates_registered_adapter() -> None:
    registry = PlatformRegistry()
    registry.register("fake", FakeAdapter)

    adapter = registry.create("FAKE")

    assert isinstance(adapter, FakeAdapter)
    assert registry.names() == ("fake",)


def test_registry_rejects_duplicate_and_unknown_platforms() -> None:
    registry = PlatformRegistry()
    registry.register("fake", FakeAdapter)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("fake", FakeAdapter)
    with pytest.raises(LookupError, match="Unsupported platform"):
        registry.create("missing")


async def test_publisher_records_platform_neutral_receipt(tmp_path) -> None:
    database_path = tmp_path / "social.db"
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"owned test media")
    database = Database(database_path)
    await database.initialize()

    receipt = await Publisher(database, FakeAdapter()).publish(
        PublicationRequest(path=media_path, caption="test caption", live=False)
    )

    assert receipt.platform == "fake"
    assert receipt.status == "dry_run"
    assert receipt.result.remote_id == "fake:clip"

    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT platform, status, remote_id, caption FROM publications WHERE id=?",
            (receipt.publication_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row == ("fake", "dry_run", "fake:clip", "test caption")
