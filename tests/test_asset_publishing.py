from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from social_bot.assets import AssetLibrary
from social_bot.assets_dashboard import load_assets, render_assets
from social_bot.dashboard_control import QueueActionError, create_asset_youtube_job
from social_bot.db import Database
from social_bot.platforms.base import PlatformAdapter, PublishResult
from social_bot.publishing import PublicationRequest, Publisher


class FakeAdapter(PlatformAdapter):
    name = "fake"

    async def publish_video(self, path: Path, caption: str) -> PublishResult:
        return PublishResult(remote_id=f"fake:{path.stem}", url="https://example.test/video")

    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        return {"views": 0, "likes": 0, "comments": 0}


def publication_form(**overrides: str) -> dict[str, str]:
    form = {
        "title": "Library clip",
        "caption": "Owned media",
        "privacy": "unlisted",
        "run_after": "",
    }
    form.update(overrides)
    return form


@pytest.mark.asyncio
async def test_asset_queue_stores_asset_id_and_suppresses_duplicates(tmp_path: Path) -> None:
    database_path = tmp_path / "social.db"
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"owned-library-media")
    library = AssetLibrary(Database(database_path))
    asset, _ = await library.import_file(media_path, owner_verified=True)

    job_id, created = create_asset_youtube_job(database_path, asset.id, publication_form())
    duplicate_id, duplicate_created = create_asset_youtube_job(
        database_path, asset.id, publication_form()
    )

    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT payload_json, approved, status FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    finally:
        connection.close()

    assert created is True
    assert duplicate_created is False
    assert duplicate_id == job_id
    assert row is not None
    payload = json.loads(row[0])
    assert payload["asset_id"] == asset.id
    assert payload["path"] == str(media_path.resolve())
    assert row[1:] == (0, "queued")


@pytest.mark.asyncio
async def test_publisher_reuses_asset_and_queue_requires_reuse_confirmation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "social.db"
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"owned-library-media")
    database = Database(database_path)
    library = AssetLibrary(database)
    asset, _ = await library.import_file(media_path, owner_verified=True)

    receipt = await Publisher(database, FakeAdapter()).publish(
        PublicationRequest(
            path=media_path,
            caption="first use",
            live=False,
            asset_id=asset.id,
        )
    )

    assert receipt.asset_id == asset.id
    with pytest.raises(QueueActionError, match="confirm reuse"):
        create_asset_youtube_job(database_path, asset.id, publication_form())

    job_id, created = create_asset_youtube_job(
        database_path,
        asset.id,
        publication_form(allow_reuse="1"),
    )
    assert created is True
    assert job_id > 0

    connection = sqlite3.connect(database_path)
    try:
        asset_count = connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        publication_asset_id = connection.execute(
            "SELECT asset_id FROM publications WHERE id=?",
            (receipt.publication_id,),
        ).fetchone()[0]
    finally:
        connection.close()

    assert asset_count == 1
    assert publication_asset_id == asset.id


@pytest.mark.asyncio
async def test_asset_dashboard_uses_mobile_cards_and_protected_queue_forms(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "social.db"
    media_path = tmp_path / "clip.mp4"
    media_path.write_bytes(b"owned-library-media")
    library = AssetLibrary(Database(database_path))
    asset, _ = await library.import_file(media_path, tags=["short"], owner_verified=True)

    data = load_assets(database_path)
    writable = render_assets(data, controls_enabled=True)
    read_only = render_assets(data, controls_enabled=False)

    assert 'class="asset-card"' in writable
    assert f'action="/assets/{asset.id}/queue"' in writable
    assert "Queue for approval" in writable
    assert "<table" not in writable
    assert "read-only" in read_only.lower()
    assert f'action="/assets/{asset.id}/queue"' not in read_only
