from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import Database


@dataclass(frozen=True)
class AssetRecord:
    id: int
    local_path: str
    display_name: str
    content_hash: str
    file_size: int
    media_type: str
    license: str
    owner_verified: bool
    favorite: bool
    status: str
    tags: tuple[str, ...]
    usage_count: int
    created_at: str
    updated_at: str


class AssetLibrary:
    """Managed, local-only library for media the operator owns or may publish."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def initialize(self) -> None:
        await self.database.initialize()
        db = await self.database.connect()
        try:
            cursor = await db.execute("PRAGMA table_info(assets)")
            columns = {str(row[1]) for row in await cursor.fetchall()}
            migrations = {
                "display_name": "ALTER TABLE assets ADD COLUMN display_name TEXT",
                "content_hash": "ALTER TABLE assets ADD COLUMN content_hash TEXT",
                "file_size": "ALTER TABLE assets ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0",
                "media_type": "ALTER TABLE assets ADD COLUMN media_type TEXT NOT NULL DEFAULT 'application/octet-stream'",
                "favorite": "ALTER TABLE assets ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
                "updated_at": "ALTER TABLE assets ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    await db.execute(statement)

            await db.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS assets_content_hash_unique
                ON assets(content_hash)
                WHERE content_hash IS NOT NULL;

                CREATE TABLE IF NOT EXISTS asset_tags (
                    asset_id INTEGER NOT NULL,
                    tag TEXT NOT NULL COLLATE NOCASE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(asset_id, tag),
                    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS asset_tags_tag_index ON asset_tags(tag);
                """
            )
            await db.commit()
        finally:
            await db.close()

    @staticmethod
    def hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def normalize_tags(tags: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        normalized = {tag.strip().lower() for tag in tags if tag.strip()}
        return tuple(sorted(normalized))

    async def import_file(
        self,
        path: Path,
        *,
        tags: list[str] | tuple[str, ...] = (),
        license_name: str = "owned",
        owner_verified: bool = True,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[AssetRecord, bool]:
        await self.initialize()
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if not owner_verified:
            raise ValueError("Asset imports require ownership or publishing-rights verification")

        content_hash = self.hash_file(resolved)
        file_size = resolved.stat().st_size
        media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        normalized_tags = self.normalize_tags(tags)
        db = await self.database.connect()
        try:
            existing = await db.execute_fetchall(
                "SELECT id FROM assets WHERE content_hash=? LIMIT 1", (content_hash,)
            )
            if existing:
                asset_id = int(existing[0][0])
                for tag in normalized_tags:
                    await db.execute(
                        "INSERT OR IGNORE INTO asset_tags(asset_id, tag) VALUES (?, ?)",
                        (asset_id, tag),
                    )
                await db.commit()
                record = await self._get_with_db(db, asset_id)
                if record is None:
                    raise RuntimeError("Existing asset disappeared during import")
                return record, False

            cursor = await db.execute(
                """
                INSERT INTO assets (
                    local_path, license, owner_verified, niche, status, metadata_json,
                    display_name, content_hash, file_size, media_type, favorite, updated_at
                ) VALUES (?, ?, 1, 'unspecified', 'ready', ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                """,
                (
                    str(resolved),
                    license_name.strip() or "owned",
                    json.dumps(metadata or {}, sort_keys=True),
                    (display_name or resolved.name).strip(),
                    content_hash,
                    file_size,
                    media_type,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Database did not return an asset ID")
            asset_id = int(cursor.lastrowid)
            for tag in normalized_tags:
                await db.execute(
                    "INSERT INTO asset_tags(asset_id, tag) VALUES (?, ?)", (asset_id, tag)
                )
            await db.commit()
            record = await self._get_with_db(db, asset_id)
            if record is None:
                raise RuntimeError("Imported asset could not be reloaded")
            return record, True
        finally:
            await db.close()

    async def get(self, asset_id: int) -> AssetRecord | None:
        await self.initialize()
        db = await self.database.connect()
        try:
            return await self._get_with_db(db, asset_id)
        finally:
            await db.close()

    async def search(
        self,
        query: str = "",
        *,
        tag: str | None = None,
        favorite: bool | None = None,
        limit: int = 100,
    ) -> list[AssetRecord]:
        await self.initialize()
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        clauses = ["1=1"]
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append(
                "(LOWER(COALESCE(a.display_name, '')) LIKE ? OR LOWER(a.local_path) LIKE ? "
                "OR LOWER(a.metadata_json) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        if tag and tag.strip():
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags wanted WHERE wanted.asset_id=a.id "
                "AND wanted.tag = ? COLLATE NOCASE)"
            )
            params.append(tag.strip().lower())
        if favorite is not None:
            clauses.append("a.favorite=?")
            params.append(int(favorite))
        params.append(limit)

        db = await self.database.connect()
        try:
            cursor = await db.execute(
                f"""
                SELECT a.id
                FROM assets a
                WHERE {' AND '.join(clauses)}
                ORDER BY a.favorite DESC, a.updated_at DESC, a.id DESC
                LIMIT ?
                """,
                params,
            )
            records: list[AssetRecord] = []
            for row in await cursor.fetchall():
                record = await self._get_with_db(db, int(row[0]))
                if record is not None:
                    records.append(record)
            return records
        finally:
            await db.close()

    async def set_favorite(self, asset_id: int, favorite: bool) -> bool:
        await self.initialize()
        db = await self.database.connect()
        try:
            cursor = await db.execute(
                "UPDATE assets SET favorite=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(favorite), asset_id),
            )
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def add_tags(self, asset_id: int, tags: list[str] | tuple[str, ...]) -> bool:
        await self.initialize()
        db = await self.database.connect()
        try:
            exists = await db.execute_fetchall("SELECT 1 FROM assets WHERE id=?", (asset_id,))
            if not exists:
                return False
            for tag in self.normalize_tags(tags):
                await db.execute(
                    "INSERT OR IGNORE INTO asset_tags(asset_id, tag) VALUES (?, ?)",
                    (asset_id, tag),
                )
            await db.execute(
                "UPDATE assets SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (asset_id,)
            )
            await db.commit()
            return True
        finally:
            await db.close()

    async def usage_history(self, asset_id: int) -> list[dict[str, Any]]:
        await self.initialize()
        db = await self.database.connect()
        try:
            cursor = await db.execute(
                """
                SELECT id, platform, remote_id, remote_url, status, scheduled_at,
                       published_at, caption
                FROM publications
                WHERE asset_id=?
                ORDER BY id DESC
                """,
                (asset_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

    async def _get_with_db(self, db: Any, asset_id: int) -> AssetRecord | None:
        cursor = await db.execute(
            """
            SELECT a.id, a.local_path, COALESCE(a.display_name, a.local_path) AS display_name,
                   COALESCE(a.content_hash, '') AS content_hash, a.file_size, a.media_type,
                   a.license, a.owner_verified, a.favorite, a.status, a.created_at, a.updated_at,
                   COUNT(DISTINCT p.id) AS usage_count
            FROM assets a
            LEFT JOIN publications p ON p.asset_id=a.id
            WHERE a.id=?
            GROUP BY a.id
            """,
            (asset_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        tags_cursor = await db.execute(
            "SELECT tag FROM asset_tags WHERE asset_id=? ORDER BY tag", (asset_id,)
        )
        tags = tuple(str(tag_row[0]) for tag_row in await tags_cursor.fetchall())
        return AssetRecord(
            id=int(row["id"]),
            local_path=str(row["local_path"]),
            display_name=str(row["display_name"]),
            content_hash=str(row["content_hash"]),
            file_size=int(row["file_size"]),
            media_type=str(row["media_type"]),
            license=str(row["license"]),
            owner_verified=bool(row["owner_verified"]),
            favorite=bool(row["favorite"]),
            status=str(row["status"]),
            tags=tags,
            usage_count=int(row["usage_count"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
