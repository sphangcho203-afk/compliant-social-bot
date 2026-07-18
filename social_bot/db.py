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
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        return db

    async def initialize(self) -> None:
        async with await self.connect() as db:
            await db.executescript(SCHEMA)
            await db.commit()
