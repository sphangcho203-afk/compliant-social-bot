from __future__ import annotations

import argparse
import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .assets_dashboard import load_assets, render_assets
from .dashboard import load_dashboard_data, render_dashboard
from .dashboard_control import (
    QueueActionError,
    approve_job,
    cancel_job,
    create_asset_youtube_job,
    create_youtube_job,
    retry_job,
)
from .history import load_history_data, load_job_detail, render_history, render_job_detail
from .youtube_dashboard_auth import (
    OAuthStateStore,
    YouTubeOAuthError,
    begin_youtube_login,
    disconnect_youtube,
    finish_youtube_login,
    load_youtube_connection,
    render_youtube_login_page,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_CLIENT_SECRETS = Path("secrets/youtube-client.json")
DEFAULT_YOUTUBE_TOKEN = Path("secrets/youtube-token.json")


def build_handler(
    database_path: Path,
    worker_name: str,
    control_token: str | None = None,
    *,
    client_secrets_path: Path = DEFAULT_CLIENT_SECRETS,
    youtube_token_path: Path = DEFAULT_YOUTUBE_TOKEN,
    oauth_redirect_base: str = "http://127.0.0.1:8765",
    oauth_state_store: OAuthStateStore | None = None,
) -> type[BaseHTTPRequestHandler]:
    state_store = oauth_state_store or OAuthStateStore()
    redirect_uri = f"{oauth_redirect_base.rstrip('/')}/youtube/callback"

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/status":
                data = load_dashboard_data(database_path, worker_name)
                self._send(
                    HTTPStatus.OK,
                    json.dumps(data, default=str).encode(),
                    "application/json; charset=utf-8",
                )
                return
            if parsed.path == "/":
                data = load_dashboard_data(database_path, worker_name)
                message = parse_qs(parsed.query).get("message", [""])[0]
                page = render_dashboard(
                    data, controls_enabled=bool(control_token), message=message
                )
                page = page.replace(
                    '<div class="muted">Local dashboard · refreshes every 15 seconds</div>',
                    '<div class="muted">Local dashboard · refreshes every 15 seconds · '
                    '<a href="/history">Job history</a> · '
                    '<a href="/assets">Asset library</a> · '
                    '<a href="/youtube">YouTube login</a></div>',
                )
                self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
                return
            if parsed.path == "/youtube":
                params = parse_qs(parsed.query)
                connection = load_youtube_connection(client_secrets_path, youtube_token_path)
                page = render_youtube_login_page(
                    connection,
                    controls_enabled=bool(control_token),
                    message=params.get("message", [""])[0],
                )
                self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
                return
            if parsed.path == "/youtube/callback":
                authorization_response = redirect_uri
                if parsed.query:
                    authorization_response += f"?{parsed.query}"
                try:
                    finish_youtube_login(
                        client_secrets_path,
                        youtube_token_path,
                        redirect_uri,
                        authorization_response,
                        state_store,
                    )
                    message = "YouTube account connected successfully"
                except YouTubeOAuthError as exc:
                    message = f"YouTube login failed: {exc}"
                self._redirect(f"/youtube?message={quote(message)}")
                return
            if parsed.path == "/assets":
                params = parse_qs(parsed.query)
                data = load_assets(
                    database_path,
                    query=params.get("q", [""])[0],
                    tag=params.get("tag", [""])[0],
                )
                self._send(
                    HTTPStatus.OK,
                    render_assets(
                        data,
                        controls_enabled=bool(control_token),
                        message=params.get("message", [""])[0],
                    ).encode(),
                    "text/html; charset=utf-8",
                )
                return
            if parsed.path == "/history":
                params = parse_qs(parsed.query)
                data = load_history_data(
                    database_path,
                    query=params.get("q", [""])[0],
                    status=params.get("status", [""])[0],
                    period=params.get("period", ["all"])[0],
                )
                self._send(
                    HTTPStatus.OK,
                    render_history(data).encode(),
                    "text/html; charset=utf-8",
                )
                return
            if parsed.path.startswith("/history/"):
                try:
                    job_id = int(parsed.path.removeprefix("/history/"))
                except ValueError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                job = load_job_detail(database_path, job_id)
                if job is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Job not found")
                    return
                self._send(
                    HTTPStatus.OK,
                    render_job_detail(job).encode(),
                    "text/html; charset=utf-8",
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)

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
            if path == "/youtube/login":
                try:
                    authorization_url = begin_youtube_login(
                        client_secrets_path,
                        redirect_uri,
                        state_store,
                    )
                except YouTubeOAuthError as exc:
                    self._redirect(
                        f"/youtube?message={quote(f'YouTube login failed: {exc}')}"
                    )
                    return
                self._redirect(authorization_url)
                return

            redirect_path = "/"
            try:
                if path == "/youtube/disconnect":
                    removed = disconnect_youtube(youtube_token_path)
                    message = (
                        "Local YouTube login removed"
                        if removed
                        else "No local YouTube login was stored"
                    )
                    redirect_path = "/youtube"
                elif path == "/jobs/create":
                    job_id, created = create_youtube_job(database_path, form)
                    message = (
                        f"Job {job_id} {'created' if created else 'already exists'}; "
                        "approval required"
                    )
                elif path.startswith("/assets/") and path.endswith("/queue"):
                    parts = path.strip("/").split("/")
                    if len(parts) != 3 or parts[0] != "assets" or parts[2] != "queue":
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    asset_id = int(parts[1])
                    job_id, created = create_asset_youtube_job(database_path, asset_id, form)
                    message = (
                        f"Asset {asset_id} queued as job {job_id}"
                        if created
                        else f"Asset {asset_id} already has matching job {job_id}"
                    )
                    message += "; approval required"
                    redirect_path = "/assets"
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
            except (QueueActionError, ValueError, OSError) as exc:
                message = f"Action failed: {exc}"
                if path.startswith("/assets/"):
                    redirect_path = "/assets"
                elif path.startswith("/youtube/"):
                    redirect_path = "/youtube"

            self._redirect(f"{redirect_path}?message={quote(message)}")

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
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
        help="Enable protected queue and OAuth write actions with this token",
    )
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=DEFAULT_CLIENT_SECRETS,
        help="Google OAuth client JSON file",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_YOUTUBE_TOKEN,
        help="Private local YouTube OAuth token file",
    )
    parser.add_argument(
        "--oauth-redirect-base",
        help="Public browser base URL for the OAuth callback; defaults to dashboard host and port",
    )
    return parser


def _resolve_oauth_redirect_base(host: str, port: int, configured: str | None) -> str:
    base = (configured or f"http://{host}:{port}").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--oauth-redirect-base must be an absolute HTTP or HTTPS URL")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("--oauth-redirect-base cannot contain a path, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("HTTP OAuth callbacks are allowed only on a loopback address")
    return base


def main() -> None:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    if args.control_token is not None and len(args.control_token) < 12:
        raise ValueError("--control-token must be at least 12 characters")
    oauth_redirect_base = _resolve_oauth_redirect_base(
        args.host,
        args.port,
        args.oauth_redirect_base,
    )
    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(
            args.db,
            args.worker_name,
            args.control_token,
            client_secrets_path=args.client_secrets,
            youtube_token_path=args.token,
            oauth_redirect_base=oauth_redirect_base,
        ),
    )
    mode = "controls-enabled" if args.control_token else "read-only"
    print(f"dashboard=http://{args.host}:{args.port} mode={mode}")
    print(f"youtube_oauth_callback={oauth_redirect_base}/youtube/callback")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
