from __future__ import annotations

import argparse
import hmac
import html
import json
import os
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .dashboard_control import (
    QueueActionError,
    approve_job,
    cancel_job,
    create_youtube_job,
    retry_job,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def load_dashboard_data(database_path: Path, worker_name: str) -> dict[str, Any]:
    if not database_path.exists():
        return {
            "worker": {"name": worker_name, "status": "unknown", "age_seconds": None},
            "queue": {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0},
            "jobs": [],
            "failed_jobs": [],
            "publications": [],
            "metrics": [],
        }

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        queue = {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0}
        for row in connection.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"):
            queue[str(row["status"])] = int(row["count"])

        heartbeat = connection.execute(
            "SELECT state, pid, details, updated_at FROM worker_heartbeats WHERE worker_name=?",
            (worker_name,),
        ).fetchone()
        worker: dict[str, Any] = {
            "name": worker_name,
            "status": "unknown",
            "age_seconds": None,
            "pid": None,
            "details": None,
        }
        if heartbeat is not None:
            updated_at = datetime.fromisoformat(str(heartbeat["updated_at"]))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = max(0, int((datetime.now(timezone.utc) - updated_at).total_seconds()))
            state = str(heartbeat["state"])
            worker.update(
                {
                    "status": "stale" if age > 90 else state,
                    "age_seconds": age,
                    "pid": int(heartbeat["pid"]),
                    "details": heartbeat["details"],
                }
            )

        jobs = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, kind, status, approved, attempts, run_after, last_error,
                       created_at, updated_at, payload_json
                FROM jobs
                ORDER BY id DESC LIMIT 25
                """
            )
        ]
        for job in jobs:
            try:
                payload = json.loads(str(job.pop("payload_json")))
            except json.JSONDecodeError:
                payload = {}
            job["path"] = payload.get("path", "")
            job["title"] = payload.get("title", "")

        failed_jobs = [job for job in jobs if job["status"] == "failed"][:10]
        publications = [
            dict(row)
            for row in connection.execute(
                """
                SELECT p.id, p.platform, p.status, p.remote_url, p.published_at,
                       a.local_path, p.caption
                FROM publications p
                JOIN assets a ON a.id = p.asset_id
                ORDER BY p.id DESC LIMIT 10
                """
            )
        ]
        metrics = [
            dict(row)
            for row in connection.execute(
                """
                SELECT remote_id, views, likes, comments, captured_at
                FROM media_performance
                ORDER BY captured_at DESC, id DESC LIMIT 10
                """
            )
        ]
        return {
            "worker": worker,
            "queue": queue,
            "jobs": jobs,
            "failed_jobs": failed_jobs,
            "publications": publications,
            "metrics": metrics,
        }
    finally:
        connection.close()


def render_dashboard(
    data: dict[str, Any], *, controls_enabled: bool = False, message: str = ""
) -> str:
    worker = data["worker"]
    queue = data["queue"]
    status = html.escape(str(worker["status"]))
    age = "n/a" if worker["age_seconds"] is None else f"{worker['age_seconds']}s"

    def rows(items: list[dict[str, Any]], columns: list[str]) -> str:
        if not items:
            return f'<tr><td colspan="{len(columns)}" class="empty">Nothing here yet.</td></tr>'
        return "".join(
            "<tr>"
            + "".join(f"<td>{html.escape(str(item.get(column) or ''))}</td>" for column in columns)
            + "</tr>"
            for item in items
        )

    def job_rows() -> str:
        if not data["jobs"]:
            return '<tr><td colspan="9" class="empty">Nothing here yet.</td></tr>'
        rendered: list[str] = []
        for job in data["jobs"]:
            job_id = int(job["id"])
            action_forms: list[str] = []
            if controls_enabled and job["status"] == "queued" and not job["approved"]:
                action_forms.append(_action_form(job_id, "approve", "Approve"))
            if controls_enabled and job["status"] in {"queued", "failed"}:
                action_forms.append(_action_form(job_id, "cancel", "Cancel"))
            if controls_enabled and job["status"] == "failed":
                action_forms.append(_action_form(job_id, "retry", "Retry"))
            actions = " ".join(action_forms) or '<span class="muted">Read only</span>'
            rendered.append(
                "<tr>"
                f"<td>{job_id}</td>"
                f"<td>{html.escape(str(job['title']))}</td>"
                f"<td>{html.escape(str(job['status']))}</td>"
                f"<td>{'yes' if job['approved'] else 'no'}</td>"
                f"<td>{html.escape(str(job['run_after'] or ''))}</td>"
                f"<td>{job['attempts']}</td>"
                f"<td>{html.escape(str(job['path']))}</td>"
                f"<td>{html.escape(str(job['last_error'] or ''))}</td>"
                f"<td class=\"actions\">{actions}</td>"
                "</tr>"
            )
        return "".join(rendered)

    message_html = f'<div class="notice">{html.escape(message)}</div>' if message else ""
    controls_notice = (
        "Queue controls are enabled. Every write action requires the control token."
        if controls_enabled
        else "Queue controls are disabled. Start with --control-token to enable local writes."
    )
    create_form = ""
    if controls_enabled:
        create_form = """
        <section><h2>Add YouTube job</h2>
        <form method="post" action="/jobs/create" class="create-form">
          <label>Video path<input name="path" required placeholder="/data/data/com.termux/files/home/storage/shared/video.mp4"></label>
          <label>Title<input name="title" required maxlength="100"></label>
          <label>Caption<textarea name="caption" rows="3"></textarea></label>
          <label>Privacy<select name="privacy"><option>unlisted</option><option>private</option><option>public</option></select></label>
          <label>Run after<input name="run_after" placeholder="2026-07-20T18:00:00+05:30"></label>
          <label>Control token<input name="token" type="password" required autocomplete="off"></label>
          <button type="submit">Queue for approval</button>
        </form></section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>Compliant Social Bot</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #0b1020; color: #eef2ff; }}
main {{ max-width: 1200px; margin: auto; padding: 20px; }}
h1 {{ margin-bottom: 4px; }} .muted {{ color: #9aa5c4; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 12px; margin: 20px 0; }}
.card, section {{ background: #151c33; border: 1px solid #283252; border-radius: 14px; padding: 16px; }}
.value {{ font-size: 1.7rem; font-weight: 700; margin-top: 6px; }}
.status {{ text-transform: uppercase; letter-spacing: .08em; }}
table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
th, td {{ text-align: left; padding: 9px 7px; border-bottom: 1px solid #283252; word-break: break-word; vertical-align: top; }}
section {{ margin-top: 14px; overflow-x: auto; }}
.empty {{ color: #9aa5c4; text-align: center; }}
.notice {{ margin: 14px 0; padding: 12px; border-radius: 10px; background: #202a49; }}
.create-form {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); }}
label {{ display: grid; gap: 6px; color: #bac3de; }}
input, textarea, select, button {{ font: inherit; padding: 10px; border-radius: 8px; border: 1px solid #39476f; background: #0f162b; color: #eef2ff; }}
button {{ cursor: pointer; background: #344c91; font-weight: 650; }}
.actions form {{ display: inline-flex; gap: 5px; margin: 2px; }}
.actions input {{ width: 92px; padding: 6px; }}
.actions button {{ padding: 6px 8px; }}
</style>
</head>
<body><main>
<h1>Compliant Social Bot</h1>
<div class="muted">Local dashboard · refreshes every 15 seconds</div>
{message_html}
<div class="notice">{html.escape(controls_notice)}</div>
<div class="grid">
<div class="card"><div class="muted">Worker</div><div class="value status">{status}</div><div class="muted">heartbeat {age}</div></div>
<div class="card"><div class="muted">Queued</div><div class="value">{queue.get('queued', 0)}</div></div>
<div class="card"><div class="muted">Running</div><div class="value">{queue.get('running', 0)}</div></div>
<div class="card"><div class="muted">Completed</div><div class="value">{queue.get('done', 0)}</div></div>
<div class="card"><div class="muted">Failed</div><div class="value">{queue.get('failed', 0)}</div></div>
<div class="card"><div class="muted">Cancelled</div><div class="value">{queue.get('cancelled', 0)}</div></div>
</div>
{create_form}
<section><h2>Queue manager</h2><table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Approved</th><th>Run after</th><th>Attempts</th><th>Path</th><th>Error</th><th>Actions</th></tr></thead><tbody>{job_rows()}</tbody></table></section>
<section><h2>Recent publications</h2><table><thead><tr><th>ID</th><th>Platform</th><th>Status</th><th>Published</th><th>Path</th></tr></thead><tbody>{rows(data['publications'], ['id','platform','status','published_at','local_path'])}</tbody></table></section>
<section><h2>Latest analytics</h2><table><thead><tr><th>Video</th><th>Views</th><th>Likes</th><th>Comments</th><th>Captured</th></tr></thead><tbody>{rows(data['metrics'], ['remote_id','views','likes','comments','captured_at'])}</tbody></table></section>
<section><h2>Failed jobs</h2><table><thead><tr><th>ID</th><th>Kind</th><th>Attempts</th><th>Error</th><th>Updated</th></tr></thead><tbody>{rows(data['failed_jobs'], ['id','kind','attempts','last_error','updated_at'])}</tbody></table></section>
</main></body></html>"""


def _action_form(job_id: int, action: str, label: str) -> str:
    return (
        f'<form method="post" action="/jobs/{job_id}/{action}">'
        '<input name="token" type="password" required placeholder="token" autocomplete="off">'
        f'<button type="submit">{html.escape(label)}</button></form>'
    )


def build_handler(
    database_path: Path, worker_name: str, control_token: str | None = None
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            data = load_dashboard_data(database_path, worker_name)
            if parsed.path == "/api/status":
                body = json.dumps(data, default=str).encode()
                content_type = "application/json; charset=utf-8"
            elif parsed.path == "/":
                message = parse_qs(parsed.query).get("message", [""])[0]
                body = render_dashboard(
                    data, controls_enabled=bool(control_token), message=message
                ).encode()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send(HTTPStatus.OK, body, content_type)

        def do_POST(self) -> None:
            if control_token is None:
                self.send_error(HTTPStatus.FORBIDDEN, "Queue controls are disabled")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid content length")
                return
            if length > 64 * 1024:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            form_data = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            form = {key: values[-1] for key, values in form_data.items()}
            supplied_token = form.pop("token", "")
            if not hmac.compare_digest(supplied_token, control_token):
                self.send_error(HTTPStatus.FORBIDDEN, "Invalid control token")
                return

            path = urlparse(self.path).path
            try:
                if path == "/jobs/create":
                    job_id, created = create_youtube_job(database_path, form)
                    message = f"Job {job_id} {'created' if created else 'already exists'}; approval required"
                else:
                    parts = path.strip("/").split("/")
                    if len(parts) != 3 or parts[0] != "jobs":
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    job_id = int(parts[1])
                    action = parts[2]
                    if action == "approve":
                        approve_job(database_path, job_id)
                    elif action == "cancel":
                        cancel_job(database_path, job_id)
                    elif action == "retry":
                        retry_job(database_path, job_id)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    message = f"Job {job_id} {action}d"
            except (QueueActionError, ValueError) as exc:
                message = f"Action failed: {exc}"

            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/?message={quote(message)}")
            self.end_headers()

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="social-bot-dashboard")
    parser.add_argument("--db", type=Path, default=Path("data/social_bot.db"))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--worker-name", default="youtube-publisher")
    parser.add_argument(
        "--control-token",
        default=os.environ.get("SOCIAL_BOT_CONTROL_TOKEN"),
        help="Enable protected queue write actions with this token",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    if args.control_token is not None and len(args.control_token) < 12:
        raise ValueError("--control-token must be at least 12 characters")
    server = ThreadingHTTPServer(
        (args.host, args.port), build_handler(args.db, args.worker_name, args.control_token)
    )
    mode = "controls-enabled" if args.control_token else "read-only"
    print(f"dashboard=http://{args.host}:{args.port} mode={mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
