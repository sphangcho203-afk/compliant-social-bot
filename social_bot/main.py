from __future__ import annotations

import asyncio
import signal
import structlog

from .config import Settings
from .db import Database
from .jobs import JobQueue
from .media.ffmpeg import FFmpegEngine
from .workers import render_worker


async def main() -> None:
    settings = Settings()
    settings.ensure_directories()

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level)
    )
    log = structlog.get_logger()

    db = Database(settings.db_path)
    await db.initialize()
    queue = JobQueue(db)
    engine = FFmpegEngine()

    tasks = [
        asyncio.create_task(render_worker(queue, engine, settings.render_dir)),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("bot_started", dry_run=settings.dry_run)
    await stop.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("bot_stopped")


if __name__ == "__main__":
    asyncio.run(main())
