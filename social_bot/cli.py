from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from social_bot.db import Database
from social_bot.platforms.youtube import YouTubeAdapter, YouTubeUploadOptions
from social_bot.youtube_auth import load_youtube_credentials


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish-youtube", help="Publish a video through YouTube's official API")
    publish.add_argument("video", type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--caption", default="")
    publish.add_argument("--privacy", choices=("private", "unlisted", "public"), default="unlisted")
    publish.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    publish.add_argument("--client-secrets", type=Path, default=Path("secrets/youtube-client.json"))
    publish.add_argument("--token", type=Path, default=Path("secrets/youtube-token.json"))
    publish.add_argument(
        "--live",
        action="store_true",
        help="Perform a real upload. Without this flag, the command is a dry run.",
    )
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


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "publish-youtube":
        return await publish_youtube(args)
    raise RuntimeError(f"Unsupported command: {args.command}")


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
