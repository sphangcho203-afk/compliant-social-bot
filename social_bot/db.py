from pathlib import Path

import aiosqlite

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_url TEXT,
 local_path TEXT NOT NULL,
 license TEXT NOT NULL,
 owner_verified INTEGER NOT NULL DEFAULT 0,
 niche TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued',
 metadata_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued',
 approved INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,
 run_after TEXT,
 locked_at TEXT,
 last_error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 platform TEXT NOT NULL,
 asset_id INTEGER NOT NULL,
 remote_id TEXT,
 remote_url TEXT,
 status TEXT NOT NULL,
 scheduled_at TEXT,
 published_at TEXT,
 caption TEXT,
 FOREIGN KEY(asset_id) REFERENCES assets(id)
);
CREATE TABLE IF NOT EXISTS media_performance (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 platform TEXT NOT NULL,
 remote_id TEXT NOT NULL,
 niche TEXT NOT NULL,
 humor_style TEXT NOT NULL,
 views INTEGER NOT NULL DEFAULT 0,
 likes INTEGER NOT NULL DEFAULT 0,
 comments INTEGER NOT NULL DEFAULT 0,
 followers INTEGER NOT NULL DEFAULT 0,
 captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS content_weights (
 key TEXT PRIMARY KEY,
 weight REAL NOT NULL DEFAULT 1.0,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS football_knowledge (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 provider TEXT NOT NULL,
 competition TEXT NOT NULL,
 match_id TEXT NOT NULL,
 event_type TEXT NOT NULL,
 severity REAL NOT NULL DEFAULT 0,
 payload_json TEXT NOT NULL,
 observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def connect(self) -> aiosqlite.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        return db

    async def initialize(self) -> None:
        db = await self.connect()
        try:
            await db.executescript(SCHEMA)

            publication_cursor = await db.execute("PRAGMA table_info(publications)")
            publication_columns = {row[1] for row in await publication_cursor.fetchall()}
            if "remote_url" not in publication_columns:
                await db.execute("ALTER TABLE publications ADD COLUMN remote_url TEXT")

            job_cursor = await db.execute("PRAGMA table_info(jobs)")
            job_columns = {row[1] for row in await job_cursor.fetchall()}
            if "approved" not in job_columns:
                await db.execute(
                    "ALTER TABLE jobs ADD COLUMN approved INTEGER NOT NULL DEFAULT 0"
                )
            await db.commit()
        finally:
            await db.close()

    async def record_publication(
        self,
        *,
        platform: str,
        local_path: Path,
        remote_id: str,
        remote_url: str | None,
        status: str,
        caption: str,
    ) -> int:
        db = await self.connect()
        try:
            asset_cursor = await db.execute(
                """
                INSERT INTO assets (local_path, license, owner_verified, niche, status)
                VALUES (?, 'owned', 1, 'unspecified', 'published')
                """,
                (str(local_path),),
            )
            asset_id = asset_cursor.lastrowid
            publication_cursor = await db.execute(
                """
                INSERT INTO publications (
                    platform, asset_id, remote_id, remote_url, status, published_at, caption
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (platform, asset_id, remote_id, remote_url, status, caption),
            )
            await db.commit()
            if publication_cursor.lastrowid is None:
                raise RuntimeError("Database did not return a publication ID")
            return publication_cursor.lastrowid
        finally:
            await db.close()

    async def list_remote_ids(self, platform: str) -> list[str]:
        db = await self.connect()
        try:
            cursor = await db.execute(
                """
                SELECT DISTINCT remote_id
                FROM publications
                WHERE platform = ?
                  AND status = 'published'
                  AND remote_id IS NOT NULL
                  AND remote_id NOT LIKE 'dry-run:%'
                ORDER BY id
                """,
                (platform,),
            )
            return [str(row[0]) for row in await cursor.fetchall()]
        finally:
            await db.close()

    async def record_metrics(
        self,
        *,
        platform: str,
        remote_id: str,
        views: int,
        likes: int,
        comments: int,
    ) -> int:
        db = await self.connect()
        try:
            cursor = await db.execute(
                """
                INSERT INTO media_performance (
                    platform, remote_id, niche, humor_style, views, likes, comments
                ) VALUES (?, ?, 'unspecified', 'unspecified', ?, ?, ?)
                """,
                (platform, remote_id, views, likes, comments),
            )
            await db.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Database did not return a metrics snapshot ID")
            return cursor.lastrowid
        finally:
            await db.close()
