from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

VALID_STATUSES = {"queued", "running", "done", "failed", "cancelled"}
VALID_PERIODS = {"all", "today", "7d", "30d"}


def _cutoff(period: str) -> str | None:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if period == "7d":
        return (now - timedelta(days=7)).isoformat()
    if period == "30d":
        return (now - timedelta(days=30)).isoformat()
    return None


def load_history_data(
    database_path: Path,
    *,
    query: str = "",
    status: str = "",
    period: str = "all",
    limit: int = 100,
) -> dict[str, Any]:
    query = query.strip()
    status = status if status in VALID_STATUSES else ""
    period = period if period in VALID_PERIODS else "all"
    limit = max(1, min(limit, 500))

    empty = {
        "jobs": [],
        "stats": {"total": 0, "done": 0, "failed": 0, "success_rate": 0.0},
        "filters": {"query": query, "status": status, "period": period},
    }
    if not database_path.exists():
        return empty

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        clauses: list[str] = []
        parameters: list[Any] = []
        if status:
            clauses.append("j.status = ?")
            parameters.append(status)
        cutoff = _cutoff(period)
        if cutoff:
            clauses.append("j.created_at >= ?")
            parameters.append(cutoff)
        if query:
            clauses.append(
                "(LOWER(j.kind) LIKE ? OR LOWER(j.payload_json) LIKE ? "
                "OR LOWER(COALESCE(j.last_error, '')) LIKE ?)"
            )
            needle = f"%{query.lower()}%"
            parameters.extend([needle, needle, needle])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = connection.execute(
            f"""
            SELECT j.id, j.kind, j.status, j.approved, j.attempts, j.run_after,
                   j.locked_at, j.last_error, j.created_at, j.updated_at,
                   j.payload_json,
                   p.platform, p.remote_id, p.remote_url, p.published_at
            FROM jobs j
            LEFT JOIN publications p ON p.id = (
                SELECT p2.id FROM publications p2
                JOIN assets a2 ON a2.id = p2.asset_id
                WHERE a2.local_path = json_extract(j.payload_json, '$.path')
                ORDER BY p2.id DESC LIMIT 1
            )
            {where}
            ORDER BY j.id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        jobs: list[dict[str, Any]] = []
        for row in rows:
            job = dict(row)
            try:
                payload = json.loads(str(job.pop("payload_json")))
            except json.JSONDecodeError:
                payload = {}
            job["title"] = payload.get("title", "")
            job["path"] = payload.get("path", "")
            job["privacy"] = payload.get("privacy", "")
            jobs.append(job)

        counts = dict(connection.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"))
        total = sum(int(value) for value in counts.values())
        done = int(counts.get("done", 0))
        failed = int(counts.get("failed", 0))
        stats = {
            "total": total,
            "done": done,
            "failed": failed,
            "success_rate": round((done / total * 100) if total else 0.0, 1),
        }
        return {
            "jobs": jobs,
            "stats": stats,
            "filters": {"query": query, "status": status, "period": period},
        }
    finally:
        connection.close()


def load_job_detail(database_path: Path, job_id: int) -> dict[str, Any] | None:
    if not database_path.exists():
        return None
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        try:
            job["payload"] = json.loads(str(job.pop("payload_json")))
        except json.JSONDecodeError:
            job["payload"] = {}

        path = str(job["payload"].get("path", ""))
        publication = connection.execute(
            """
            SELECT p.*, a.local_path
            FROM publications p
            JOIN assets a ON a.id = p.asset_id
            WHERE a.local_path = ?
            ORDER BY p.id DESC LIMIT 1
            """,
            (path,),
        ).fetchone()
        job["publication"] = dict(publication) if publication else None
        if publication and publication["remote_id"]:
            metrics = connection.execute(
                """
                SELECT views, likes, comments, captured_at
                FROM media_performance
                WHERE remote_id = ?
                ORDER BY captured_at DESC, id DESC LIMIT 1
                """,
                (publication["remote_id"],),
            ).fetchone()
            job["metrics"] = dict(metrics) if metrics else None
        else:
            job["metrics"] = None
        return job
    finally:
        connection.close()


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root {{ color-scheme: dark; font-family: system-ui,sans-serif; }}
body {{ margin:0;background:#0b1020;color:#eef2ff; }}
main {{ max-width:1200px;margin:auto;padding:20px; }}
a {{ color:#9db7ff; }} .muted {{ color:#9aa5c4; }}
.grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0; }}
.card,section {{ background:#151c33;border:1px solid #283252;border-radius:14px;padding:16px; }}
.value {{ font-size:1.7rem;font-weight:700;margin-top:6px; }}
form {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px; }}
input,select,button {{ font:inherit;padding:10px;border-radius:8px;border:1px solid #39476f;background:#0f162b;color:#eef2ff; }}
button {{ cursor:pointer;background:#344c91;font-weight:650; }}
table {{ width:100%;border-collapse:collapse;font-size:.88rem; }}
th,td {{ text-align:left;padding:9px 7px;border-bottom:1px solid #283252;word-break:break-word;vertical-align:top; }}
section {{ margin-top:14px;overflow-x:auto; }}
dl {{ display:grid;grid-template-columns:minmax(110px,180px) 1fr;gap:8px 14px; }}
dt {{ color:#9aa5c4; }} dd {{ margin:0;word-break:break-word; }}
</style></head><body><main>{body}</main></body></html>"""


def render_history(data: dict[str, Any]) -> str:
    filters = data["filters"]
    stats = data["stats"]
    rows = []
    for job in data["jobs"]:
        rows.append(
            "<tr>"
            f'<td><a href="/history/{int(job["id"])}">{int(job["id"])}</a></td>'
            f'<td>{html.escape(str(job.get("title") or ""))}</td>'
            f'<td>{html.escape(str(job.get("status") or ""))}</td>'
            f'<td>{html.escape(str(job.get("kind") or ""))}</td>'
            f'<td>{html.escape(str(job.get("attempts") or 0))}</td>'
            f'<td>{html.escape(str(job.get("run_after") or ""))}</td>'
            f'<td>{html.escape(str(job.get("updated_at") or ""))}</td>'
            f'<td>{html.escape(str(job.get("path") or ""))}</td>'
            "</tr>"
        )
    history_rows = "".join(rows) or '<tr><td colspan="8" class="muted">No matching jobs.</td></tr>'
    status_options = ['<option value="">All statuses</option>'] + [
        f'<option value="{value}"{" selected" if filters["status"] == value else ""}>{value}</option>'
        for value in sorted(VALID_STATUSES)
    ]
    period_options = [
        ("all", "All time"),
        ("today", "Today"),
        ("7d", "Last 7 days"),
        ("30d", "Last 30 days"),
    ]
    periods = "".join(
        f'<option value="{value}"{" selected" if filters["period"] == value else ""}>{label}</option>'
        for value, label in period_options
    )
    clear_url = "/history?" + urlencode({"period": "all"})
    body = f"""
<a href="/">← Dashboard</a><h1>Job history</h1><div class="muted">Searchable publication operations record</div>
<div class="grid">
<div class="card"><div class="muted">Total jobs</div><div class="value">{stats['total']}</div></div>
<div class="card"><div class="muted">Completed</div><div class="value">{stats['done']}</div></div>
<div class="card"><div class="muted">Failed</div><div class="value">{stats['failed']}</div></div>
<div class="card"><div class="muted">Success rate</div><div class="value">{stats['success_rate']}%</div></div>
</div>
<section><form method="get" action="/history">
<input name="q" value="{html.escape(filters['query'])}" placeholder="Search title, filename, kind, or error">
<select name="status">{''.join(status_options)}</select><select name="period">{periods}</select>
<button type="submit">Apply filters</button></form><p><a href="{clear_url}">Clear filters</a></p></section>
<section><table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Kind</th><th>Attempts</th><th>Scheduled</th><th>Updated</th><th>Path</th></tr></thead><tbody>{history_rows}</tbody></table></section>
"""
    return _page("Job history", body)


def render_job_detail(job: dict[str, Any]) -> str:
    payload = job.get("payload") or {}
    publication = job.get("publication") or {}
    metrics = job.get("metrics") or {}
    fields = {
        "Job ID": job.get("id"),
        "Kind": job.get("kind"),
        "Status": job.get("status"),
        "Approved": "yes" if job.get("approved") else "no",
        "Attempts": job.get("attempts"),
        "Created": job.get("created_at"),
        "Updated": job.get("updated_at"),
        "Scheduled": job.get("run_after"),
        "Last error": job.get("last_error"),
        "Title": payload.get("title"),
        "Path": payload.get("path"),
        "Privacy": payload.get("privacy"),
        "Remote ID": publication.get("remote_id"),
        "Remote URL": publication.get("remote_url"),
        "Published": publication.get("published_at"),
        "Views": metrics.get("views"),
        "Likes": metrics.get("likes"),
        "Comments": metrics.get("comments"),
        "Analytics captured": metrics.get("captured_at"),
    }
    details = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value or ''))}</dd>"
        for label, value in fields.items()
    )
    return _page(
        f"Job {job.get('id')}",
        f'<a href="/history">← Job history</a><h1>Job #{int(job["id"])}</h1><section><dl>{details}</dl></section>',
    )
