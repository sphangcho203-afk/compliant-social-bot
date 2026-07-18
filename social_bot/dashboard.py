from __future__ import annotations

import argparse
import html
import json
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def load_dashboard_data(database_path: Path, worker_name: str) -> dict[str, Any]:
    if not database_path.exists():
        return {
            "worker": {"name": worker_name, "status": "unknown", "age_seconds": None},
            "queue": {"queued": 0, "running": 0, "done": 0, "failed": 0},
            "failed_jobs": [],
            "publications": [],
            "metrics": [],
        }

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        queue = {"queued": 0, "running": 0, "done": 0, "failed": 0}
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

        failed_jobs = [
            dict(row)
            for row in connection.execute(
                """
                SELECT id, kind, attempts, last_error, updated_at
                FROM jobs WHERE status='failed'
                ORDER BY updated_at DESC, id DESC LIMIT 10
                """
            )
        ]
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
            "failed_jobs": failed_jobs,
            "publications": publications,
            "metrics": metrics,
        }
    finally:
        connection.close()


def render_dashboard(data: dict[str, Any]) -> str:
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
main {{ max-width: 1050px; margin: auto; padding: 20px; }}
h1 {{ margin-bottom: 4px; }} .muted {{ color: #9aa5c4; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 12px; margin: 20px 0; }}
.card, section {{ background: #151c33; border: 1px solid #283252; border-radius: 14px; padding: 16px; }}
.value {{ font-size: 1.7rem; font-weight: 700; margin-top: 6px; }}
.status {{ text-transform: uppercase; letter-spacing: .08em; }}
table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
th, td {{ text-align: left; padding: 9px 7px; border-bottom: 1px solid #283252; word-break: break-word; }}
section {{ margin-top: 14px; overflow-x: auto; }}
.empty {{ color: #9aa5c4; text-align: center; }}
</style>
</head>
<body><main>
<h1>Compliant Social Bot</h1>
<div class="muted">Local dashboard · refreshes every 15 seconds</div>
<div class="grid">
<div class="card"><div class="muted">Worker</div><div class="value status">{status}</div><div class="muted">heartbeat {age}</div></div>
<div class="card"><div class="muted">Queued</div><div class="value">{queue.get('queued', 0)}</div></div>
<div class="card"><div class="muted">Running</div><div class="value">{queue.get('running', 0)}</div></div>
<div class="card"><div class="muted">Completed</div><div class="value">{queue.get('done', 0)}</div></div>
<div class="card"><div class="muted">Failed</div><div class="value">{queue.get('failed', 0)}</div></div>
</div>
<section><h2>Recent publications</h2><table><thead><tr><th>ID</th><th>Platform</th><th>Status</th><th>Published</th><th>Path</th></tr></thead><tbody>{rows(data['publications'], ['id','platform','status','published_at','local_path'])}</tbody></table></section>
<section><h2>Latest analytics</h2><table><thead><tr><th>Video</th><th>Views</th><th>Likes</th><th>Comments</th><th>Captured</th></tr></thead><tbody>{rows(data['metrics'], ['remote_id','views','likes','comments','captured_at'])}</tbody></table></section>
<section><h2>Failed jobs</h2><table><thead><tr><th>ID</th><th>Kind</th><th>Attempts</th><th>Error</th><th>Updated</th></tr></thead><tbody>{rows(data['failed_jobs'], ['id','kind','attempts','last_error','updated_at'])}</tbody></table></section>
</main></body></html>"""


def build_handler(database_path: Path, worker_name: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            data = load_dashboard_data(database_path, worker_name)
            if path == "/api/status":
                body = json.dumps(data, default=str).encode()
                content_type = "application/json; charset=utf-8"
            elif path == "/":
                body = render_dashboard(data).encode()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    server = ThreadingHTTPServer(
        (args.host, args.port), build_handler(args.db, args.worker_name)
    )
    print(f"dashboard=http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
