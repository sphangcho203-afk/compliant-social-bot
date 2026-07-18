from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from social_bot.platforms.base import PlatformAdapter, PublishResult


@dataclass(frozen=True)
class YouTubeUploadOptions:
    title: str = "Social Bot Upload"
    privacy_status: str = "unlisted"
    category_id: str = "22"
    made_for_kids: bool = False


class YouTubeAdapter(PlatformAdapter):
    """Official YouTube Data API adapter.

    Google client imports are intentionally lazy, keeping dry runs and ordinary
    development usable without OAuth dependencies installed.
    """

    name = "youtube"

    def __init__(
        self,
        credentials: Any | None = None,
        *,
        dry_run: bool = True,
        options: YouTubeUploadOptions | None = None,
    ) -> None:
        self._credentials = credentials
        self._dry_run = dry_run
        self._options = options or YouTubeUploadOptions()

    async def publish_video(self, path: Path, caption: str) -> PublishResult:
        if not path.is_file():
            raise FileNotFoundError(path)

        if self._dry_run:
            return PublishResult(remote_id=f"dry-run:{path.stem}", url=None)

        if self._credentials is None:
            raise RuntimeError("YouTube credentials are required when dry_run is disabled")

        return await asyncio.to_thread(self._upload_sync, path, caption)

    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        if remote_id.startswith("dry-run:"):
            return {"views": 0, "likes": 0, "comments": 0}

        if self._credentials is None:
            raise RuntimeError("YouTube credentials are required to fetch metrics")

        return await asyncio.to_thread(self._fetch_metrics_sync, remote_id)

    def _build_service(self) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Install the YouTube extra with: pip install -e '.[youtube]'"
            ) from exc

        return build("youtube", "v3", credentials=self._credentials, cache_discovery=False)

    def _upload_sync(self, path: Path, caption: str) -> PublishResult:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise RuntimeError(
                "Install the YouTube extra with: pip install -e '.[youtube]'"
            ) from exc

        service = self._build_service()
        body = {
            "snippet": {
                "title": self._options.title,
                "description": caption,
                "categoryId": self._options.category_id,
            },
            "status": {
                "privacyStatus": self._options.privacy_status,
                "selfDeclaredMadeForKids": self._options.made_for_kids,
            },
        }
        media = MediaFileUpload(str(path), chunksize=-1, resumable=True)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = str(response["id"])
        return PublishResult(remote_id=video_id, url=f"https://youtu.be/{video_id}")

    def _fetch_metrics_sync(self, remote_id: str) -> dict[str, int]:
        service = self._build_service()
        response = service.videos().list(part="statistics", id=remote_id).execute()
        items = response.get("items", [])
        if not items:
            raise LookupError(f"YouTube video not found: {remote_id}")

        statistics = items[0].get("statistics", {})
        return {
            "views": int(statistics.get("viewCount", 0)),
            "likes": int(statistics.get("likeCount", 0)),
            "comments": int(statistics.get("commentCount", 0)),
        }
