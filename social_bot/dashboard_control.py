from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class QueueActionError(ValueError):
    pass


def _normalize_run_after(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QueueActionError("Schedule must be an ISO-8601 time with a timezone") from exc
    if parsed.tzinfo is None:
        raise QueueActionError("Schedule must include a timezone, such as +05:30 or Z")
    return parsed.astimezone(timezone.utc).isoformat()


def _fingerprint(video: Path, payload: dict[str, str]) -> str:
    digest = hashlib.sha256()
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def create_youtube_job(database_path: Path, form: dict[str, str]) -> tuple[int, bool]:
    video = Path(form.get("path", "")).expanduser().resolve()
    title = form.get("title", "").strip()
    caption = form.get("caption", "").strip()
    privacy = form.get("privacy", "unlisted").strip()
    run_after = _normalize_run_after(form.get("run_after", ""))

    if not video.is_file():
        raise QueueActionError(f"Video file not found: {video}")
    if not title:
        raise QueueActionError("Title is required")
    if privacy not in {"private", "unlisted", "public"}:
        raise QueueActionError("Privacy must be private, unlisted, or public")

    payload: dict[str, Any] = {
        "path": str(video),
        "title": title,
        "caption": caption,
        "privacy": privacy,
    }
    fingerprint = _fingerprint(
        video,
        {"title": title, "caption": caption, "privacy": privacy},
    )

    connection = sqlite3.connect(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO jobs(
                kind, payload_json, run_after, approved, idempotency_key
            ) VALUES ('publish_youtube', ?, ?, 0, ?)
            """,
            (json.dumps(payload), run_after, fingerprint),
        )
        created = cursor.rowcount == 1
        if created:
            if cursor.lastrowid is None:
                raise RuntimeError("Database did not return a job ID")
            job_id = int(cursor.lastrowid)
        else:
            row = connection.execute(
                "SELECT id FROM jobs WHERE kind='publish_youtube' AND idempotency_key=?",
                (fingerprint,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Duplicate job could not be loaded")
            job_id = int(row[0])
        connection.commit()
        return job_id, created
    finally:
        connection.close()


def approve_job(database_path: Path, job_id: int) -> None:
    _update_one(
        database_path,
        "UPDATE jobs SET approved=1, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",
        job_id,
        "Queued job not found or no longer approvable",
    )


def cancel_job(database_path: Path, job_id: int) -> None:
    _update_one(
        database_path,
        """
        UPDATE jobs SET status='cancelled', locked_at=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status IN ('queued', 'failed')
        """,
        job_id,
        "Job not found or cannot be cancelled",
    )


def retry_job(database_path: Path, job_id: int) -> None:
    _update_one(
        database_path,
        """
        UPDATE jobs SET status='queued', locked_at=NULL, last_error=NULL,
                        updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='failed'
        """,
        job_id,
        "Failed job not found or no longer retryable",
    )


def _update_one(database_path: Path, query: str, job_id: int, error: str) -> None:
    connection = sqlite3.connect(database_path)
    try:
        cursor = connection.execute(query, (job_id,))
        if cursor.rowcount != 1:
            raise QueueActionError(error)
        connection.commit()
    finally:
        connection.close()
