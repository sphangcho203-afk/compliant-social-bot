from __future__ import annotations

from pathlib import Path
from typing import Any

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def load_youtube_credentials(
    client_secrets_path: Path,
    token_path: Path,
    *,
    allow_browser: bool = True,
) -> Any:
    """Load, refresh, or obtain OAuth credentials for the official YouTube API.

    The token file is local state and must never be committed. Interactive browser
    authorization is used only when no valid refreshable token is available.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Install the YouTube extra with: pip install -e '.[youtube]'"
        ) from exc

    scopes = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READ_SCOPE]
    credentials = None

    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_path), scopes)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not client_secrets_path.is_file():
            raise FileNotFoundError(client_secrets_path)
        if not allow_browser:
            raise RuntimeError("YouTube authorization is required but browser login is disabled")

        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes)
        credentials = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials
