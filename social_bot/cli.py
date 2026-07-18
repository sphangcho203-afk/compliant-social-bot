from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from social_bot.db import Database
from social_bot.jobs import JobQueue
from social_bot.platforms.youtube import YouTubeAdapter, YouTubeUploadOptions
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
    queue_parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))

    approve = subparsers.add_parser("approve-job", help="Approve one queued publication job")
    approve.add_argument("job_id", type=int)
    approve.add_argument("--db", type=Path, default=Path("data/social_bot.db"))

    worker = subparsers.add_parser(
        "run-youtube-publisher",
        help="Process one approved YouTube publication job",
    )
    worker.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
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
    video = args.video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)

    credentials = None
    if args.live:
        credentials = load_youtube_credentials(args.client_secrets, args.token)

    adapter = YouTubeAdapter(
        credentials=credentials,
        dry_run=not args.live,
        options=YouTubeUploadOptions(title=args.title, privacy_status=args.privacy),
    )
    result = await adapter.publish_video(video, args.caption)

    database = Database(args.db)
    await database.initialize()
    publication_id = await database.record_publication(
        platform=adapter.name,
        local_path=video,
        remote_id=result.remote_id,
        remote_url=result.url,
        status="published" if args.live else "dry_run",
        caption=args.caption,
    )

    print(f"publication_id={publication_id}")
    print(f"remote_id={result.remote_id}")
    if result.url:
        print(f"url={result.url}")
    return 0


async def queue_youtube(args: argparse.Namespace) -> int:
    video = args.video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)

    database = Database(args.db)
    await database.initialize()
    queue = JobQueue(database)
    job_id = await queue.enqueue(
        "publish_youtube",
        {
            "path": str(video),
            "title": args.title,
            "caption": args.caption,
            "privacy": args.privacy,
        },
    )
    print(f"job_id={job_id}")
    print("approved=false")
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
    database = Database(args.db)
    await database.initialize()
    queue = JobQueue(database)
    job = await queue.claim("publish_youtube", require_approved=True)
    if job is None:
        print("processed=0")
        return 0

    try:
        payload = json.loads(job["payload_json"])
        path = Path(payload["path"])
        if not path.is_file():
            raise FileNotFoundError(path)

        credentials = None
        if args.live:
            credentials = load_youtube_credentials(args.client_secrets, args.token)
        adapter = YouTubeAdapter(
            credentials=credentials,
            dry_run=not args.live,
            options=YouTubeUploadOptions(
                title=str(payload["title"]),
                privacy_status=str(payload.get("privacy", "unlisted")),
            ),
        )
        result = await adapter.publish_video(path, str(payload.get("caption", "")))
        publication_id = await database.record_publication(
            platform=adapter.name,
            local_path=path,
            remote_id=result.remote_id,
            remote_url=result.url,
            status="published" if args.live else "dry_run",
            caption=str(payload.get("caption", "")),
        )
        await queue.finish(int(job["id"]))
    except Exception as exc:
        await queue.fail(int(job["id"]), repr(exc), retry=int(job["attempts"]) < 4)
        raise

    print(f"processed=1 job_id={job['id']} publication_id={publication_id}")
    print(f"remote_id={result.remote_id}")
    if result.url:
        print(f"url={result.url}")
    return 0


async def sync_youtube_analytics(args: argparse.Namespace) -> int:
    credentials = load_youtube_credentials(args.client_secrets, args.token)
    adapter = YouTubeAdapter(credentials=credentials, dry_run=False)
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
