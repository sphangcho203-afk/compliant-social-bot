from __future__ import annotations

from pathlib import Path

import pytest

from social_bot.assets import AssetLibrary
from social_bot.db import Database


@pytest.mark.asyncio
async def test_import_detects_duplicates_and_merges_tags(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"owned-media")
    library = AssetLibrary(Database(tmp_path / "bot.db"))

    first, created = await library.import_file(
        media, tags=["Football", "short"], owner_verified=True
    )
    duplicate, duplicate_created = await library.import_file(
        media, tags=["highlight"], owner_verified=True
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == first.id
    assert duplicate.tags == ("football", "highlight", "short")
    assert duplicate.content_hash == first.content_hash


@pytest.mark.asyncio
async def test_search_tags_and_favorites(tmp_path: Path) -> None:
    library = AssetLibrary(Database(tmp_path / "bot.db"))
    first_path = tmp_path / "goal.mp4"
    second_path = tmp_path / "training.mp4"
    first_path.write_bytes(b"goal")
    second_path.write_bytes(b"training")

    first, _ = await library.import_file(first_path, tags=["match"], owner_verified=True)
    await library.import_file(second_path, tags=["practice"], owner_verified=True)
    assert await library.set_favorite(first.id, True)

    query_results = await library.search("goal")
    tag_results = await library.search(tag="match")
    favorite_results = await library.search(favorite=True)

    assert [asset.id for asset in query_results] == [first.id]
    assert [asset.id for asset in tag_results] == [first.id]
    assert [asset.id for asset in favorite_results] == [first.id]


@pytest.mark.asyncio
async def test_import_requires_rights_confirmation(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")
    library = AssetLibrary(Database(tmp_path / "bot.db"))

    with pytest.raises(ValueError, match="ownership"):
        await library.import_file(media, owner_verified=False)
