from __future__ import annotations

import os
from pathlib import Path
from typing import Any

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = (YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READ_SCOPE)


def save_youtube_credentials(credentials: Any, token_path: Path) -> None:
    """Persist Google OAuth credentials as private local state.

    The temporary-file replacement avoids leaving a partially written token if the
    process is interrupted. Permissions are restricted to the current OS user.
    """

    token_path = token_path.expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(token_path.parent, 0o700)
    except OSError:
        pass

    temporary_path = token_path.with_name(f".{token_path.name}.tmp")
    temporary_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        os.chmod(temporary_path, 0o600)
    except OSError:
        pass
    temporary_path.replace(token_path)
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass


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

    scopes = list(YOUTUBE_SCOPES)
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

    save_youtube_credentials(credentials, token_path)
    return credentials
