from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from .db import Database


class JobQueue:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(self, kind: str, payload: dict[str, Any], run_after: str | None = None) -> int:
        async with await self.db.connect() as conn:
            cur = await conn.execute(
                "INSERT INTO jobs(kind, payload_json, run_after) VALUES (?, ?, ?)",
                (kind, json.dumps(payload), run_after),
            )
            await conn.commit()
            return int(cur.lastrowid)

    async def claim(self, kind: str):
        now = datetime.now(timezone.utc).isoformat()
        async with await self.db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                '''SELECT * FROM jobs
                   WHERE kind=? AND status='queued'
                     AND (run_after IS NULL OR run_after <= ?)
                   ORDER BY id LIMIT 1''',
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
            return dict(row)

    async def finish(self, job_id: int) -> None:
        async with await self.db.connect() as conn:
            await conn.execute(
                "UPDATE jobs SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            await conn.commit()

    async def fail(self, job_id: int, error: str, retry: bool = True) -> None:
        status = "queued" if retry else "failed"
        async with await self.db.connect() as conn:
            await conn.execute(
                '''UPDATE jobs SET status=?, attempts=attempts+1,
                   last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                (status, error[:2000], job_id),
            )
            await conn.commit()
