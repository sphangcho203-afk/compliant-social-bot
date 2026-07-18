from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from .jobs import JobQueue

log = structlog.get_logger()


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
    ) -> None:
        self.queue = queue
        self.process_once = process_once
        self.options = options or WorkerOptions()
        self.options.validate()
        self.stop_event = stop_event or asyncio.Event()

    def request_stop(self) -> None:
        self.stop_event.set()

    async def run(self) -> None:
        recovered = await self.queue.recover_stale(
            stale_after_seconds=self.options.stale_after_seconds,
            kind="publish_youtube",
        )
        log.info("worker_started", recovered_jobs=recovered)
        try:
            while not self.stop_event.is_set():
                try:
                    processed = await self.process_once()
                except Exception:
                    log.exception("worker_iteration_failed")
                    processed = 0

                if processed:
                    log.info("worker_job_processed", processed=processed)
                    continue

                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(), timeout=self.options.poll_seconds
                    )
                except TimeoutError:
                    pass
        finally:
            log.info("worker_stopped")


def install_signal_handlers(worker: ContinuousWorker) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            # Windows event loops may not support POSIX signal handlers.
            pass
