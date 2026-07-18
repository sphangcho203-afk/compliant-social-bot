from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from .jobs import JobQueue

log = structlog.get_logger()
Heartbeat = Callable[[str, str | None], Awaitable[None]]


@dataclass(frozen=True)
class WorkerOptions:
    poll_seconds: float = 5.0
    stale_after_seconds: float = 900.0

    def validate(self) -> None:
        if self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than zero")
        if self.stale_after_seconds < 0:
            raise ValueError("stale_after_seconds cannot be negative")


class ContinuousWorker:
    def __init__(
        self,
        queue: JobQueue,
        process_once: Callable[[], Awaitable[int]],
        *,
        options: WorkerOptions | None = None,
        stop_event: asyncio.Event | None = None,
        heartbeat: Heartbeat | None = None,
    ) -> None:
        self.queue = queue
        self.process_once = process_once
        self.options = options or WorkerOptions()
        self.options.validate()
        self.stop_event = stop_event or asyncio.Event()
        self.heartbeat = heartbeat

    def request_stop(self) -> None:
        self.stop_event.set()

    async def _heartbeat(self, state: str, details: str | None = None) -> None:
        if self.heartbeat is not None:
            await self.heartbeat(state, details)

    async def run(self) -> None:
        recovered = await self.queue.recover_stale(
            stale_after_seconds=self.options.stale_after_seconds,
            kind="publish_youtube",
        )
        await self._heartbeat("running", f"recovered_jobs={recovered}")
        log.info("worker_started", recovered_jobs=recovered)
        try:
            while not self.stop_event.is_set():
                try:
                    await self._heartbeat("working")
                    processed = await self.process_once()
                except Exception as exc:
                    await self._heartbeat("degraded", repr(exc)[:500])
                    log.exception("worker_iteration_failed")
                    processed = 0

                if processed:
                    await self._heartbeat("running", f"processed={processed}")
                    log.info("worker_job_processed", processed=processed)
                    continue

                await self._heartbeat("idle")
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), timeout=self.options.poll_seconds
                    )
                except TimeoutError:
                    pass
        finally:
            await self._heartbeat("stopped")
            log.info("worker_stopped")


def install_signal_handlers(worker: ContinuousWorker) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            # Windows event loops may not support POSIX signal handlers.
            pass
