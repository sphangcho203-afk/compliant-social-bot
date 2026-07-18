from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .assets import AssetLibrary, AssetRecord
from .db import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot-assets")
    parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser("import", help="Import owned media into the library")
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument("--name")
    import_parser.add_argument("--tag", action="append", default=[])
    import_parser.add_argument("--license", default="owned")
    import_parser.add_argument(
        "--confirm-rights",
        action="store_true",
        help="Confirm that you own the media or have permission to publish it",
    )

    list_parser = commands.add_parser("list", help="Search the asset library")
    list_parser.add_argument("--query", default="")
    list_parser.add_argument("--tag")
    list_parser.add_argument("--favorites", action="store_true")
    list_parser.add_argument("--limit", type=int, default=100)

    show_parser = commands.add_parser("show", help="Show one asset and its usage history")
    show_parser.add_argument("asset_id", type=int)

    tag_parser = commands.add_parser("tag", help="Add tags to an asset")
    tag_parser.add_argument("asset_id", type=int)
    tag_parser.add_argument("tags", nargs="+")

    favorite_parser = commands.add_parser("favorite", help="Mark or unmark an asset as favorite")
    favorite_parser.add_argument("asset_id", type=int)
    favorite_parser.add_argument("value", choices=("on", "off"))
    return parser


def _print_asset(asset: AssetRecord) -> None:
    print(
        f"id={asset.id} name={asset.display_name!r} type={asset.media_type} "
        f"bytes={asset.file_size} favorite={str(asset.favorite).lower()} "
        f"uses={asset.usage_count} tags={','.join(asset.tags) or '-'}"
    )
    print(f"path={asset.local_path}")
    print(f"sha256={asset.content_hash or '-'} license={asset.license} status={asset.status}")


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    library = AssetLibrary(Database(args.db))

    if args.command == "import":
        if not args.confirm_rights:
            raise ValueError("Import requires --confirm-rights")
        asset, created = await library.import_file(
            args.path,
            tags=args.tag,
            license_name=args.license,
            owner_verified=True,
            display_name=args.name,
        )
        print(f"created={str(created).lower()}")
        _print_asset(asset)
        return 0

    if args.command == "list":
        favorite = True if args.favorites else None
        assets = await library.search(
            args.query, tag=args.tag, favorite=favorite, limit=args.limit
        )
        for asset in assets:
            _print_asset(asset)
        print(f"count={len(assets)}")
        return 0

    if args.command == "show":
        asset = await library.get(args.asset_id)
        if asset is None:
            raise LookupError(f"Asset not found: {args.asset_id}")
        _print_asset(asset)
        history = await library.usage_history(args.asset_id)
        for item in history:
            print(
                f"publication={item['id']} platform={item['platform']} "
                f"status={item['status']} published_at={item['published_at'] or '-'}"
            )
        print(f"publications={len(history)}")
        return 0

    if args.command == "tag":
        if not await library.add_tags(args.asset_id, args.tags):
            raise LookupError(f"Asset not found: {args.asset_id}")
        print(f"asset_id={args.asset_id} tagged=true")
        return 0

    if args.command == "favorite":
        if not await library.set_favorite(args.asset_id, args.value == "on"):
            raise LookupError(f"Asset not found: {args.asset_id}")
        print(f"asset_id={args.asset_id} favorite={args.value}")
        return 0

    raise RuntimeError(f"Unsupported command: {args.command}")


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
