from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database


class JobQueue:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        run_after: str | None = None,
        *,
        approved: bool = False,
        idempotency_key: str | None = None,
    ) -> int:
        conn = await self.db.connect()
        try:
            cur = await conn.execute(
                """
                INSERT INTO jobs(kind, payload_json, run_after, approved, idempotency_key)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, json.dumps(payload), run_after, int(approved), idempotency_key),
            )
            await conn.commit()
            if cur.lastrowid is None:
                raise RuntimeError("Database did not return a job ID")
            return int(cur.lastrowid)
        finally:
            await conn.close()

    async def enqueue_unique(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        run_after: str | None = None,
        *,
        approved: bool = False,
    ) -> tuple[int, bool]:
        conn = await self.db.connect()
        try:
            cur = await conn.execute(
                """
                INSERT OR IGNORE INTO jobs(
                    kind, payload_json, run_after, approved, idempotency_key
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (kind, json.dumps(payload), run_after, int(approved), idempotency_key),
            )
            created = cur.rowcount == 1
            if created:
                if cur.lastrowid is None:
                    raise RuntimeError("Database did not return a job ID")
                job_id = int(cur.lastrowid)
            else:
                existing = await conn.execute(
                    "SELECT id FROM jobs WHERE kind=? AND idempotency_key=?",
                    (kind, idempotency_key),
                )
                row = await existing.fetchone()
                if row is None:
                    raise RuntimeError("Duplicate job exists but could not be loaded")
                job_id = int(row[0])
            await conn.commit()
            return job_id, created
        finally:
            await conn.close()

    async def get(self, job_id: int) -> dict[str, Any] | None:
        conn = await self.db.connect()
        try:
            cur = await conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
            row = await cur.fetchone()
            return dict(row) if row is not None else None
        finally:
            await conn.close()

    async def approve(self, job_id: int) -> bool:
        conn = await self.db.connect()
        try:
            cur = await conn.execute(
                """
                UPDATE jobs
                SET approved=1, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='queued'
                """,
                (job_id,),
            )
            await conn.commit()
            return cur.rowcount == 1
        finally:
            await conn.close()

    async def recover_stale(self, *, stale_after_seconds: float, kind: str | None = None) -> int:
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds cannot be negative")
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat()
        conn = await self.db.connect()
        try:
            kind_clause = "AND kind=?" if kind is not None else ""
            parameters: tuple[Any, ...] = (cutoff, kind) if kind is not None else (cutoff,)
            cur = await conn.execute(
                f"""
                UPDATE jobs
                SET status='queued', locked_at=NULL,
                    last_error=COALESCE(last_error, 'Recovered stale running job'),
                    updated_at=CURRENT_TIMESTAMP
                WHERE status='running' AND locked_at IS NOT NULL AND locked_at <= ?
                {kind_clause}
                """,
                parameters,
            )
            await conn.commit()
            return cur.rowcount
        finally:
            await conn.close()

    async def claim(self, kind: str, *, require_approved: bool = False):
        now = datetime.now(timezone.utc).isoformat()
        conn = await self.db.connect()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            approval_clause = "AND approved=1" if require_approved else ""
            cur = await conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE kind=? AND status='queued'
                  AND (run_after IS NULL OR run_after <= ?)
                  {approval_clause}
                ORDER BY COALESCE(run_after, created_at), id LIMIT 1
                """,
                (kind, now),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback()
                return None
            await conn.execute(
                "UPDATE jobs SET status='running', locked_at=?, updated_at=? WHERE id=?",
                (now, now, row["id"]),
            )
            await conn.commit()
            claimed = dict(row)
            claimed["status"] = "running"
            return claimed
        finally:
            await conn.close()

    async def finish(self, job_id: int) -> None:
        conn = await self.db.connect()
        try:
            await conn.execute(
                "UPDATE jobs SET status='done', locked_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def fail(self, job_id: int, error: str, retry: bool = True) -> None:
        status = "queued" if retry else "failed"
        conn = await self.db.connect()
        try:
            await conn.execute(
                """
                UPDATE jobs SET status=?, attempts=attempts+1,
                   last_error=?, locked_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?
                """,
                (status, error[:2000], job_id),
            )
            await conn.commit()
        finally:
            await conn.close()
