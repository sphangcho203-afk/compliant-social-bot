from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import PlatformAdapter

AdapterFactory = Callable[..., PlatformAdapter]


class PlatformRegistry:
    """Registry of official platform adapter factories.

    Factories keep platform-specific credentials and options out of the worker
    orchestration layer. Registering a new platform never requires changing the
    publication service itself.
    """

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, name: str, factory: AdapterFactory) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Platform name cannot be empty")
        if normalized in self._factories:
            raise ValueError(f"Platform already registered: {normalized}")
        self._factories[normalized] = factory

    def create(self, name: str, **kwargs: Any) -> PlatformAdapter:
        normalized = name.strip().lower()
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise LookupError(
                f"Unsupported platform: {normalized}. Available platforms: {available}"
            ) from exc
        adapter = factory(**kwargs)
        if adapter.name != normalized:
            raise ValueError(
                f"Adapter factory for {normalized} returned adapter named {adapter.name}"
            )
        return adapter

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
