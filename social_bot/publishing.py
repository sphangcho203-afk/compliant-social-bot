from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import Database
from .platforms.base import PlatformAdapter, PublishResult


@dataclass(frozen=True)
class PublicationRequest:
    path: Path
    caption: str = ""
    live: bool = False
    asset_id: int | None = None


@dataclass(frozen=True)
class PublicationReceipt:
    publication_id: int
    asset_id: int
    platform: str
    result: PublishResult
    status: str


class Publisher:
    """Platform-neutral publication orchestration.

    Adapters own official API behavior. This service owns shared validation and
    durable publication receipts, preventing every platform integration from
    reimplementing the same database workflow.
    """

    def __init__(self, database: Database, adapter: PlatformAdapter) -> None:
        self._database = database
        self._adapter = adapter

    async def publish(self, request: PublicationRequest) -> PublicationReceipt:
        path = request.path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        asset_id = request.asset_id
        if asset_id is None:
            asset_id = await self._database.find_asset_id_by_path(path)
        if asset_id is not None:
            await self._database.validate_asset_path(asset_id, path)

        result = await self._adapter.publish_video(path, request.caption)
        status = "published" if request.live else "dry_run"
        publication_id = await self._database.record_publication(
            platform=self._adapter.name,
            local_path=path,
            remote_id=result.remote_id,
            remote_url=result.url,
            status=status,
            caption=request.caption,
            asset_id=asset_id,
        )
        receipt_asset_id = (
            asset_id
            if asset_id is not None
            else await self._database.publication_asset_id(publication_id)
        )
        return PublicationReceipt(
            publication_id=publication_id,
            asset_id=receipt_asset_id,
            platform=self._adapter.name,
            result=result,
            status=status,
        )
