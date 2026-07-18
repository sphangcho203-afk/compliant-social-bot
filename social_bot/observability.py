from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .db import Database


class ObservabilityStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def initialize(self) -> None:
        connection = await self.database.connect()
        try:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_heartbeats (
                    worker_name TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    details TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await connection.commit()
        finally:
            await connection.close()

    async def heartbeat(
        self,
        worker_name: str,
        *,
        state: str,
        pid: int,
        details: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection = await self.database.connect()
        try:
            await connection.execute(
                """
                INSERT INTO worker_heartbeats(worker_name, state, pid, details, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(worker_name) DO UPDATE SET
                    state=excluded.state,
                    pid=excluded.pid,
                    details=excluded.details,
                    updated_at=excluded.updated_at
                """,
                (worker_name, state, pid, details, now),
            )
            await connection.commit()
        finally:
            await connection.close()

    async def queue_summary(self) -> dict[str, int]:
        connection = await self.database.connect()
        try:
            cursor = await connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            )
            rows = await cursor.fetchall()
            summary = {"queued": 0, "running": 0, "done": 0, "failed": 0}
            summary.update({str(row[0]): int(row[1]) for row in rows})
            return summary
        finally:
            await connection.close()

    async def latest_heartbeat(self, worker_name: str) -> dict[str, Any] | None:
        connection = await self.database.connect()
        try:
            cursor = await connection.execute(
                "SELECT * FROM worker_heartbeats WHERE worker_name=?",
                (worker_name,),
            )
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            await connection.close()

    async def failed_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        connection = await self.database.connect()
        try:
            cursor = await connection.execute(
                """
                SELECT id, kind, attempts, last_error, updated_at
                FROM jobs
                WHERE status='failed'
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await connection.close()
