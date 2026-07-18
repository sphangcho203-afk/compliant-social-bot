from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from .db import Database
from .observability import ObservabilityStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot-status")
    parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    parser.add_argument("--worker-name", default="youtube-publisher")
    parser.add_argument("--stale-seconds", type=float, default=30.0)
    parser.add_argument("--failed-limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stale_seconds < 0:
        raise ValueError("--stale-seconds cannot be negative")
    if args.failed_limit <= 0:
        raise ValueError("--failed-limit must be greater than zero")

    database = Database(args.db)
    await database.initialize()
    store = ObservabilityStore(database)
    await store.initialize()

    heartbeat = await store.latest_heartbeat(args.worker_name)
    queue = await store.queue_summary()
    failed = await store.failed_jobs(args.failed_limit)

    worker_status = "unknown"
    heartbeat_age_seconds: int | None = None
    if heartbeat is not None:
        updated_at = datetime.fromisoformat(str(heartbeat["updated_at"]))
        heartbeat_age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - updated_at).total_seconds()),
        )
        worker_status = (
            "stale"
            if heartbeat_age_seconds > args.stale_seconds
            else str(heartbeat["state"])
        )

    result = {
        "worker": {
            "name": args.worker_name,
            "status": worker_status,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat": heartbeat,
        },
        "queue": queue,
        "failed_jobs": failed,
    }

    if args.as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"worker={args.worker_name} status={worker_status}")
        if heartbeat_age_seconds is not None:
            print(f"heartbeat_age_seconds={heartbeat_age_seconds}")
        print("queue=" + " ".join(f"{key}:{value}" for key, value in queue.items()))
        for job in failed:
            error = str(job.get("last_error") or "").replace("\n", " ")
            print(
                f"failed_job={job['id']} kind={job['kind']} attempts={job['attempts']} "
                f"error={error[:200]}"
            )
    return 1 if worker_status in {"unknown", "stale", "degraded"} else 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
