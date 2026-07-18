from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.platforms.registry import PlatformRegistry
from social_bot.platforms.youtube import YouTubeAdapter, YouTubeUploadOptions
from social_bot.publishing import PublicationRequest, Publisher
from social_bot.youtube_auth import load_youtube_credentials


def add_auth_arguments(parser: argparse.ArgumentParser) -> None:
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


def build_platform_registry() -> PlatformRegistry:
    registry = PlatformRegistry()
    registry.register("youtube", YouTubeAdapter)
    return registry


def create_youtube_adapter(
    *,
    live: bool,
    client_secrets: Path,
    token: Path,
    title: str = "Social Bot Upload",
    privacy: str = "unlisted",
) -> YouTubeAdapter:
    credentials = load_youtube_credentials(client_secrets, token) if live else None
    adapter = build_platform_registry().create(
        "youtube",
        credentials=credentials,
        dry_run=not live,
        options=YouTubeUploadOptions(title=title, privacy_status=privacy),
    )
    if not isinstance(adapter, YouTubeAdapter):
        raise TypeError("YouTube registry factory returned an unexpected adapter type")
    return adapter


def normalize_run_after(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--run-after must include a timezone, such as 2026-07-20T18:00:00Z")
    return parsed.astimezone(timezone.utc).isoformat()


def publication_fingerprint(video: Path, payload: dict[str, str]) -> str:
    digest = hashlib.sha256()
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser(
        "publish-youtube",
        help="Publish a video through YouTube's official API",
    )
    publish.add_argument("video", type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--caption", default="")
    publish.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default="unlisted",
    )
    publish.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    add_auth_arguments(publish)
    publish.add_argument(
        "--live",
        action="store_true",
        help="Perform a real upload. Without this flag, the command is a dry run.",
    )

    queue_parser = subparsers.add_parser(
        "queue-youtube",
        help="Queue an owned video for approval and later publication",
    )
    queue_parser.add_argument("video", type=Path)
    queue_parser.add_argument("--title", required=True)
    queue_parser.add_argument("--caption", default="")
    queue_parser.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default="unlisted",
    )
    queue_parser.add_argument(
        "--run-after",
        help="Earliest publication time as an ISO-8601 timestamp with timezone",
    )
    queue_parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Queue even when identical media and metadata were queued before",
    )
    queue_parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))

    approve = subparsers.add_parser("approve-job", help="Approve one queued publication job")
    approve.add_argument("job_id", type=int)
    approve.add_argument("--db", type=Path, default=Path("data/social_bot.db"))

    worker = subparsers.add_parser(
        "run-youtube-publisher",
        help="Process one approved YouTube publication job",
    )
    worker.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    worker.add_argument(
        "--cooldown-hours",
        type=float,
        default=48.0,
        help="Minimum hours between live YouTube publications; use 0 to disable",
    )
    add_auth_arguments(worker)
    worker.add_argument(
        "--live",
        action="store_true",
        help="Perform a real upload. Without this flag, processing remains a dry run.",
    )

    analytics = subparsers.add_parser(
        "sync-youtube-analytics",
        help="Fetch YouTube metrics and store timestamped SQLite snapshots",
    )
    target = analytics.add_mutually_exclusive_group(required=True)
    target.add_argument("--video-id")
    target.add_argument("--all", action="store_true")
    analytics.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    add_auth_arguments(analytics)
    return parser


async def publish_youtube(args: argparse.Namespace) -> int:
    database = Database(args.db)
    await database.initialize()
    adapter = create_youtube_adapter(
        live=args.live,
        client_secrets=args.client_secrets,
        token=args.token,
        title=args.title,
        privacy=args.privacy,
    )
    receipt = await Publisher(database, adapter).publish(
        PublicationRequest(path=args.video, caption=args.caption, live=args.live)
    )

    print(f"publication_id={receipt.publication_id}")
    print(f"remote_id={receipt.result.remote_id}")
    if receipt.result.url:
        print(f"url={receipt.result.url}")
    return 0


async def queue_youtube(args: argparse.Namespace) -> int:
    video = args.video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)

    payload = {
        "path": str(video),
        "title": args.title,
        "caption": args.caption,
        "privacy": args.privacy,
    }
    run_after = normalize_run_after(args.run_after)
    database = Database(args.db)
    await database.initialize()
    queue = JobQueue(database)

    if args.allow_duplicate:
        job_id = await queue.enqueue("publish_youtube", payload, run_after)
        created = True
    else:
        fingerprint_payload = {
            "title": args.title,
            "caption": args.caption,
            "privacy": args.privacy,
        }
        job_id, created = await queue.enqueue_unique(
            "publish_youtube",
            payload,
            publication_fingerprint(video, fingerprint_payload),
            run_after,
        )

    print(f"job_id={job_id}")
    print(f"created={str(created).lower()}")
    print("approved=false")
    if run_after:
        print(f"run_after={run_after}")
    return 0


async def approve_job(args: argparse.Namespace) -> int:
    database = Database(args.db)
    await database.initialize()
    approved = await JobQueue(database).approve(args.job_id)
    if not approved:
        raise LookupError(f"Queued job not found or no longer approvable: {args.job_id}")
    print(f"job_id={args.job_id}")
    print("approved=true")
    return 0


async def run_youtube_publisher(args: argparse.Namespace) -> int:
    if args.cooldown_hours < 0:
        raise ValueError("--cooldown-hours cannot be negative")

    database = Database(args.db)
    await database.initialize()
    if args.live:
        cooldown_seconds = await database.seconds_until_platform_available(
            "youtube", args.cooldown_hours
        )
        if cooldown_seconds:
            print(f"processed=0 cooldown_seconds={cooldown_seconds}")
            return 0

    queue = JobQueue(database)
    job = await queue.claim("publish_youtube", require_approved=True)
    if job is None:
        print("processed=0")
        return 0

    try:
        payload = json.loads(job["payload_json"])
        adapter = create_youtube_adapter(
            live=args.live,
            client_secrets=args.client_secrets,
            token=args.token,
            title=str(payload["title"]),
            privacy=str(payload.get("privacy", "unlisted")),
        )
        receipt = await Publisher(database, adapter).publish(
            PublicationRequest(
                path=Path(payload["path"]),
                caption=str(payload.get("caption", "")),
                live=args.live,
            )
        )
        await queue.finish(int(job["id"]))
    except Exception as exc:
        await queue.fail(int(job["id"]), repr(exc), retry=int(job["attempts"]) < 4)
        raise

    print(f"processed=1 job_id={job['id']} publication_id={receipt.publication_id}")
    print(f"remote_id={receipt.result.remote_id}")
    if receipt.result.url:
        print(f"url={receipt.result.url}")
    return 0


async def sync_youtube_analytics(args: argparse.Namespace) -> int:
    adapter = create_youtube_adapter(
        live=True,
        client_secrets=args.client_secrets,
        token=args.token,
    )
    database = Database(args.db)
    await database.initialize()

    remote_ids = (
        await database.list_remote_ids(adapter.name)
        if args.all
        else [str(args.video_id)]
    )
    if not remote_ids:
        print("synced=0")
        return 0

    for remote_id in remote_ids:
        metrics = await adapter.fetch_metrics(remote_id)
        snapshot_id = await database.record_metrics(
            platform=adapter.name,
            remote_id=remote_id,
            views=metrics["views"],
            likes=metrics["likes"],
            comments=metrics["comments"],
        )
        print(
            f"video_id={remote_id} snapshot_id={snapshot_id} "
            f"views={metrics['views']} likes={metrics['likes']} "
            f"comments={metrics['comments']}"
        )

    print(f"synced={len(remote_ids)}")
    return 0


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "publish-youtube":
        return await publish_youtube(args)
    if args.command == "queue-youtube":
        return await queue_youtube(args)
    if args.command == "approve-job":
        return await approve_job(args)
    if args.command == "run-youtube-publisher":
        return await run_youtube_publisher(args)
    if args.command == "sync-youtube-analytics":
        return await sync_youtube_analytics(args)
    raise RuntimeError(f"Unsupported command: {args.command}")


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
