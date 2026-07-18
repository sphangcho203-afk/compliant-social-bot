from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import structlog

from .cli import run_youtube_publisher
from .db import Database
from .jobs import JobQueue
from .observability import ObservabilityStore
from .worker import ContinuousWorker, WorkerOptions, install_signal_handlers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot-worker")
    parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    parser.add_argument("--worker-name", default="youtube-publisher")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Seconds to wait when no eligible job is available",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=float,
        default=900.0,
        help="Recover running jobs whose lock is older than this threshold",
    )
    parser.add_argument(
        "--cooldown-hours",
        type=float,
        default=48.0,
        help="Minimum hours between live YouTube publications",
    )
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=Path("secrets/youtube-client.json"),
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=Path("secrets/youtube-token.json"),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform real uploads. Without this flag, the service remains a dry run.",
    )
    return parser


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ]
    )


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cooldown_hours < 0:
        raise ValueError("--cooldown-hours cannot be negative")

    configure_logging()
    database = Database(args.db)
    await database.initialize()
    queue = JobQueue(database)
    observability = ObservabilityStore(database)
    await observability.initialize()

    async def process_once() -> int:
        return await run_youtube_publisher(args)

    async def heartbeat(state: str, details: str | None) -> None:
        await observability.heartbeat(
            args.worker_name,
            state=state,
            pid=os.getpid(),
            details=details,
        )

    worker = ContinuousWorker(
        queue,
        process_once,
        options=WorkerOptions(
            poll_seconds=args.poll_seconds,
            stale_after_seconds=args.stale_after_seconds,
        ),
        heartbeat=heartbeat,
    )
    install_signal_handlers(worker)
    await worker.run()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
