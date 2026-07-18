from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PublishResult:
    remote_id: str
    url: str | None = None


class PlatformAdapter(ABC):
    name: str

    @abstractmethod
    async def publish_video(self, path: Path, caption: str) -> PublishResult:
        raise NotImplementedError

    @abstractmethod
    async def fetch_metrics(self, remote_id: str) -> dict[str, int]:
        raise NotImplementedError
