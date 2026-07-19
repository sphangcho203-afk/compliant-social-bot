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


def _hash_file(video: Path) -> str:
    digest = hashlib.sha256()
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(content_hash: str, payload: dict[str, str]) -> str:
    digest = hashlib.sha256()
    digest.update(content_hash.encode())
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


def _publication_fields(form: dict[str, str]) -> tuple[str, str, str, str | None]:
    title = form.get("title", "").strip()
    caption = form.get("caption", "").strip()
    privacy = form.get("privacy", "unlisted").strip()
    run_after = _normalize_run_after(form.get("run_after", ""))

    if not title:
        raise QueueActionError("Title is required")
    if len(title) > 100:
        raise QueueActionError("Title must be 100 characters or fewer")
    if privacy not in {"private", "unlisted", "public"}:
        raise QueueActionError("Privacy must be private, unlisted, or public")
    return title, caption, privacy, run_after


def _insert_youtube_job(
    connection: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    run_after: str | None,
    fingerprint: str,
) -> tuple[int, bool]:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO jobs(
            kind, payload_json, run_after, approved, idempotency_key
        ) VALUES ('publish_youtube', ?, ?, 0, ?)
        """,
        (json.dumps(payload, sort_keys=True), run_after, fingerprint),
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


def create_youtube_job(database_path: Path, form: dict[str, str]) -> tuple[int, bool]:
    video = Path(form.get("path", "")).expanduser().resolve()
    title, caption, privacy, run_after = _publication_fields(form)

    if not video.is_file():
        raise QueueActionError(f"Video file not found: {video}")

    payload: dict[str, Any] = {
        "path": str(video),
        "title": title,
        "caption": caption,
        "privacy": privacy,
    }
    fingerprint = _fingerprint(
        _hash_file(video),
        {"title": title, "caption": caption, "privacy": privacy},
    )

    connection = sqlite3.connect(database_path)
    try:
        return _insert_youtube_job(
            connection,
            payload=payload,
            run_after=run_after,
            fingerprint=fingerprint,
        )
    finally:
        connection.close()


def create_asset_youtube_job(
    database_path: Path,
    asset_id: int,
    form: dict[str, str],
) -> tuple[int, bool]:
    if asset_id < 1:
        raise QueueActionError("Asset ID must be positive")
    title, caption, privacy, run_after = _publication_fields(form)
    allow_reuse = form.get("allow_reuse", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        asset = connection.execute(
            """
            SELECT a.id, a.local_path, a.owner_verified, a.status,
                   COALESCE(a.content_hash, '') AS content_hash,
                   COALESCE(a.media_type, '') AS media_type,
                   COUNT(p.id) AS usage_count
            FROM assets a
            LEFT JOIN publications p ON p.asset_id=a.id
            WHERE a.id=?
            GROUP BY a.id
            """,
            (asset_id,),
        ).fetchone()
        if asset is None:
            raise QueueActionError(f"Asset not found: {asset_id}")
        if not bool(asset["owner_verified"]):
            raise QueueActionError("Asset ownership or publishing rights are not verified")
        if str(asset["status"]) not in {"ready", "published"}:
            raise QueueActionError(f"Asset is not publishable while status={asset['status']}")
        if not str(asset["media_type"]).startswith("video/"):
            raise QueueActionError("Only video assets can be queued for YouTube")

        video = Path(str(asset["local_path"])).expanduser().resolve()
        if not video.is_file():
            raise QueueActionError(f"Asset file not found: {video}")

        current_hash = _hash_file(video)
        stored_hash = str(asset["content_hash"])
        if stored_hash and current_hash != stored_hash:
            raise QueueActionError("Asset file changed since import; import it again before queuing")

        usage_count = int(asset["usage_count"])
        if usage_count > 0 and not allow_reuse:
            raise QueueActionError(
                f"Asset {asset_id} was used {usage_count} time(s); confirm reuse to queue it again"
            )

        payload: dict[str, Any] = {
            "asset_id": asset_id,
            "path": str(video),
            "title": title,
            "caption": caption,
            "privacy": privacy,
        }
        fingerprint = _fingerprint(
            current_hash,
            {
                "asset_id": str(asset_id),
                "title": title,
                "caption": caption,
                "privacy": privacy,
            },
        )
        return _insert_youtube_job(
            connection,
            payload=payload,
            run_after=run_after,
            fingerprint=fingerprint,
        )
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
