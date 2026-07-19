from datetime import datetime, timedelta, timezone
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
 idempotency_key TEXT,
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
            if "idempotency_key" not in job_columns:
                await db.execute("ALTER TABLE jobs ADD COLUMN idempotency_key TEXT")
            await db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_kind_idempotency_key
                ON jobs(kind, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
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
        asset_id: int | None = None,
    ) -> int:
        resolved_path = local_path.expanduser().resolve()
        db = await self.connect()
        try:
            publication_asset_id: int
            if asset_id is None:
                asset_cursor = await db.execute(
                    """
                    INSERT INTO assets (local_path, license, owner_verified, niche, status)
                    VALUES (?, 'owned', 1, 'unspecified', 'published')
                    """,
                    (str(resolved_path),),
                )
                if asset_cursor.lastrowid is None:
                    raise RuntimeError("Database did not return an asset ID")
                publication_asset_id = int(asset_cursor.lastrowid)
            else:
                asset_cursor = await db.execute(
                    "SELECT local_path, owner_verified FROM assets WHERE id=?",
                    (asset_id,),
                )
                asset = await asset_cursor.fetchone()
                if asset is None:
                    raise LookupError(f"Asset not found: {asset_id}")
                if not bool(asset["owner_verified"]):
                    raise PermissionError(
                        f"Asset {asset_id} does not have verified publishing rights"
                    )
                stored_path = Path(str(asset["local_path"])).expanduser().resolve()
                if stored_path != resolved_path:
                    raise ValueError(
                        f"Asset {asset_id} path does not match publication path: {resolved_path}"
                    )
                publication_asset_id = asset_id

            publication_cursor = await db.execute(
                """
                INSERT INTO publications (
                    platform, asset_id, remote_id, remote_url, status, published_at, caption
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    platform,
                    publication_asset_id,
                    remote_id,
                    remote_url,
                    status,
                    caption,
                ),
            )
            if status == "published":
                await db.execute(
                    "UPDATE assets SET status='published' WHERE id=?",
                    (publication_asset_id,),
                )
            await db.commit()
            if publication_cursor.lastrowid is None:
                raise RuntimeError("Database did not return a publication ID")
            return int(publication_cursor.lastrowid)
        finally:
            await db.close()

    async def validate_asset_path(self, asset_id: int, local_path: Path) -> None:
        resolved_path = local_path.expanduser().resolve()
        db = await self.connect()
        try:
            cursor = await db.execute(
                "SELECT local_path, owner_verified FROM assets WHERE id=?",
                (asset_id,),
            )
            asset = await cursor.fetchone()
            if asset is None:
                raise LookupError(f"Asset not found: {asset_id}")
            if not bool(asset["owner_verified"]):
                raise PermissionError(
                    f"Asset {asset_id} does not have verified publishing rights"
                )
            stored_path = Path(str(asset["local_path"])).expanduser().resolve()
            if stored_path != resolved_path:
                raise ValueError(
                    f"Asset {asset_id} path does not match publication path: {resolved_path}"
                )
        finally:
            await db.close()

    async def find_asset_id_by_path(self, local_path: Path) -> int | None:
        resolved_path = str(local_path.expanduser().resolve())
        db = await self.connect()
        try:
            columns_cursor = await db.execute("PRAGMA table_info(assets)")
            columns = {str(row[1]) for row in await columns_cursor.fetchall()}
            if "content_hash" not in columns:
                return None
            cursor = await db.execute(
                """
                SELECT id
                FROM assets
                WHERE local_path=? AND owner_verified=1 AND content_hash IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (resolved_path,),
            )
            row = await cursor.fetchone()
            return None if row is None else int(row["id"])
        finally:
            await db.close()

    async def publication_asset_id(self, publication_id: int) -> int:
        db = await self.connect()
        try:
            cursor = await db.execute(
                "SELECT asset_id FROM publications WHERE id=?",
                (publication_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise LookupError(f"Publication not found: {publication_id}")
            return int(row["asset_id"])
        finally:
            await db.close()

    async def seconds_until_platform_available(
        self,
        platform: str,
        cooldown_hours: float,
        *,
        now: datetime | None = None,
    ) -> int:
        if cooldown_hours <= 0:
            return 0

        db = await self.connect()
        try:
            cursor = await db.execute(
                """
                SELECT published_at
                FROM publications
                WHERE platform=? AND status='published' AND published_at IS NOT NULL
                ORDER BY published_at DESC, id DESC
                LIMIT 1
                """,
                (platform,),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()

        if row is None:
            return 0

        published_at = datetime.fromisoformat(str(row[0])).replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        available_at = published_at + timedelta(hours=cooldown_hours)
        remaining = (available_at - current).total_seconds()
        return max(0, int(remaining + 0.999))

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
            return int(cursor.lastrowid)
        finally:
            await db.close()
