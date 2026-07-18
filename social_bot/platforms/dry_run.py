from __future__ import annotations

import uuid
from pathlib import Path
from .base import PlatformAdapter, PublishResult


class DryRunAdapter(PlatformAdapter):
    def __init__(self, name: str):
        self.name = name

    async def publish_video(self, path: Path, caption: str) -> PublishResult:
        if not path.exists():
            raise FileNotFoundError(path)
        return PublishResult(remote_id=f"dry-{self.name}-{uuid.uuid4().hex[:12]}")

    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        return {"views": 0, "likes": 0, "comments": 0, "followers": 0}
