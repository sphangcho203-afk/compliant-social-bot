from __future__ import annotations

import html
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .youtube_auth import YOUTUBE_SCOPES, load_youtube_credentials, save_youtube_credentials


class YouTubeOAuthError(RuntimeError):
    """Safe operator-facing OAuth failure."""


class OAuthStateStore:
    """Small in-memory, single-use CSRF state store for the localhost dashboard."""

    def __init__(self, ttl_seconds: float = 600.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        self._ttl_seconds = ttl_seconds
        self._states: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        state = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + self._ttl_seconds
        with self._lock:
            self._purge_locked()
            self._states[state] = expires_at
        return state

    def consume(self, state: str) -> bool:
        if not state:
            return False
        now = time.monotonic()
        with self._lock:
            expires_at = self._states.pop(state, None)
            self._purge_locked(now)
        return expires_at is not None and expires_at >= now

    def _purge_locked(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired = [state for state, expires_at in self._states.items() if expires_at < current]
        for state in expired:
            self._states.pop(state, None)


def _load_flow_class() -> Any:
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as exc:
        raise YouTubeOAuthError(
            "Install the YouTube extra with: pip install -e '.[youtube]'"
        ) from exc
    return Flow


def begin_youtube_login(
    client_secrets_path: Path,
    redirect_uri: str,
    state_store: OAuthStateStore,
) -> str:
    client_secrets_path = client_secrets_path.expanduser()
    if not client_secrets_path.is_file():
        raise YouTubeOAuthError(
            f"YouTube OAuth client file is missing: {client_secrets_path}"
        )

    Flow = _load_flow_class()
    state = state_store.issue()
    try:
        flow = Flow.from_client_secrets_file(
            str(client_secrets_path),
            scopes=list(YOUTUBE_SCOPES),
            state=state,
        )
        flow.redirect_uri = redirect_uri
        authorization_url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
    except Exception as exc:
        raise YouTubeOAuthError("Could not create the Google sign-in request") from exc

    if returned_state != state:
        raise YouTubeOAuthError("Google OAuth state generation failed")
    return str(authorization_url)


def finish_youtube_login(
    client_secrets_path: Path,
    token_path: Path,
    redirect_uri: str,
    authorization_response: str,
    state_store: OAuthStateStore,
) -> None:
    parsed = urlparse(authorization_response)
    params = parse_qs(parsed.query)
    error = params.get("error", [""])[0]
    if error:
        raise YouTubeOAuthError(f"Google sign-in was not completed: {error}")

    state = params.get("state", [""])[0]
    if not state_store.consume(state):
        raise YouTubeOAuthError("The YouTube login request expired or was already used")

    Flow = _load_flow_class()
    try:
        flow = Flow.from_client_secrets_file(
            str(client_secrets_path.expanduser()),
            scopes=list(YOUTUBE_SCOPES),
            state=state,
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(authorization_response=authorization_response)
        save_youtube_credentials(flow.credentials, token_path)
    except YouTubeOAuthError:
        raise
    except Exception as exc:
        raise YouTubeOAuthError("Google returned an invalid or unusable OAuth response") from exc


def disconnect_youtube(token_path: Path) -> bool:
    token_path = token_path.expanduser()
    if not token_path.exists():
        return False
    token_path.unlink()
    return True


def load_youtube_connection(
    client_secrets_path: Path,
    token_path: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "connected": False,
        "token_present": token_path.expanduser().is_file(),
        "client_configured": client_secrets_path.expanduser().is_file(),
        "channel_id": None,
        "channel_title": None,
        "warning": None,
    }
    if not result["token_present"]:
        return result

    try:
        credentials = load_youtube_credentials(
            client_secrets_path.expanduser(),
            token_path.expanduser(),
            allow_browser=False,
        )
    except Exception as exc:
        result["warning"] = f"Stored authorization could not be loaded: {type(exc).__name__}"
        return result

    result["connected"] = True
    try:
        from googleapiclient.discovery import build

        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = service.channels().list(part="snippet", mine=True).execute()
        items = response.get("items", [])
        if items:
            channel = items[0]
            result["channel_id"] = channel.get("id")
            result["channel_title"] = channel.get("snippet", {}).get("title")
        else:
            result["warning"] = "The signed-in Google account does not expose a YouTube channel"
    except Exception as exc:
        result["warning"] = f"Channel details are temporarily unavailable: {type(exc).__name__}"
    return result


def render_youtube_login_page(
    connection: dict[str, Any],
    *,
    controls_enabled: bool,
    message: str = "",
) -> str:
    connected = bool(connection.get("connected"))
    state_label = "Connected" if connected else "Not connected"
    state_class = "good" if connected else "warning"
    message_html = f'<div class="notice">{html.escape(message)}</div>' if message else ""

    channel_title = connection.get("channel_title")
    channel_id = connection.get("channel_id")
    channel_html = ""
    if channel_title or channel_id:
        channel_html = (
            '<div class="detail"><span>Channel</span><strong>'
            f"{html.escape(str(channel_title or 'Unknown'))}</strong></div>"
            '<div class="detail"><span>Channel ID</span><code>'
            f"{html.escape(str(channel_id or 'Unknown'))}</code></div>"
        )

    warning = connection.get("warning")
    warning_html = (
        f'<div class="notice warning">{html.escape(str(warning))}</div>' if warning else ""
    )

    if controls_enabled:
        button_text = "Reconnect or switch account" if connected else "Sign in with Google"
        controls = f"""
        <form method="post" action="/youtube/login">
          <label>Dashboard control token
            <input name="token" type="password" required autocomplete="off">
          </label>
          <button type="submit">{button_text}</button>
        </form>
        """
        if connection.get("token_present"):
            controls += """
            <form method="post" action="/youtube/disconnect" class="danger-zone">
              <label>Dashboard control token
                <input name="token" type="password" required autocomplete="off">
              </label>
              <button type="submit" class="danger">Remove local YouTube login</button>
            </form>
            """
    else:
        controls = (
            '<div class="notice">Restart the dashboard with its control token to enable '
            "YouTube sign-in controls.</div>"
        )

    client_status = "Ready" if connection.get("client_configured") else "Missing"
    token_status = "Saved locally" if connection.get("token_present") else "Not saved"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube Login</title>
<style>
:root {{ color-scheme:dark;font-family:system-ui,sans-serif; }}
* {{ box-sizing:border-box; }}
body {{ margin:0;background:#0b1020;color:#eef2ff; }}
main {{ max-width:760px;margin:auto;padding:18px; }}
a {{ color:#9fc2ff; }}
.card {{ margin-top:18px;background:#151c33;border:1px solid #283252;border-radius:14px;padding:18px; }}
.status {{ display:inline-block;border-radius:999px;padding:6px 10px;background:#202a49;font-weight:700; }}
.good {{ color:#8ee5b2; }} .warning {{ color:#ffd58a; }}
.detail {{ display:grid;gap:4px;margin:14px 0;padding:12px;background:#0f162b;border-radius:10px; }}
.detail span,.muted {{ color:#9aa5c4; }} code {{ word-break:break-all; }}
.notice {{ margin:14px 0;padding:12px;border-radius:10px;background:#202a49; }}
form {{ display:grid;gap:10px;margin-top:16px;padding-top:16px;border-top:1px solid #283252; }}
label {{ display:grid;gap:6px;color:#bac3de; }}
input,button {{ width:100%;font:inherit;padding:11px;border-radius:8px;border:1px solid #39476f;background:#0f162b;color:#eef2ff; }}
button {{ cursor:pointer;background:#344c91;font-weight:700; }}
button.danger {{ background:#713542; }} .danger-zone {{ margin-top:22px; }}
</style></head><body><main>
<a href="/">← Dashboard</a>
<h1>YouTube account</h1>
<div class="muted">Official Google OAuth login. Your password is entered only on Google's page.</div>
{message_html}{warning_html}
<section class="card">
  <div class="status {state_class}">{state_label}</div>
  <div class="detail"><span>OAuth client configuration</span><strong>{client_status}</strong></div>
  <div class="detail"><span>Local OAuth token</span><strong>{token_status}</strong></div>
  {channel_html}
  {controls}
</section>
<div class="notice">The dashboard stores a revocable OAuth token in the local secrets folder. It never stores your Google password.</div>
</main></body></html>"""
