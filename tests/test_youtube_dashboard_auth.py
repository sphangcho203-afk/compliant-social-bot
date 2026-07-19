from __future__ import annotations

import json
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from social_bot.dashboard_app import _resolve_oauth_redirect_base
from social_bot.youtube_auth import save_youtube_credentials
from social_bot.youtube_dashboard_auth import (
    OAuthStateStore,
    begin_youtube_login,
    disconnect_youtube,
    finish_youtube_login,
    render_youtube_login_page,
)


class FakeCredentials:
    def to_json(self) -> str:
        return json.dumps({"refresh_token": "private-refresh-token"})


class FakeFlow:
    credentials = FakeCredentials()
    redirect_uri = ""

    def __init__(self, state: str) -> None:
        self.state = state
        self.fetched_response = ""

    @classmethod
    def from_client_secrets_file(
        cls,
        path: str,
        *,
        scopes: list[str],
        state: str,
    ) -> FakeFlow:
        assert Path(path).is_file()
        assert "https://www.googleapis.com/auth/youtube.upload" in scopes
        return cls(state)

    def authorization_url(self, **kwargs: str) -> tuple[str, str]:
        assert kwargs["access_type"] == "offline"
        assert kwargs["prompt"] == "consent"
        return f"https://accounts.example.test/auth?state={self.state}", self.state

    def fetch_token(self, *, authorization_response: str) -> None:
        self.fetched_response = authorization_response


def test_oauth_state_is_single_use() -> None:
    store = OAuthStateStore()
    state = store.issue()

    assert store.consume(state) is True
    assert store.consume(state) is False
    assert store.consume("") is False


def test_dashboard_oauth_flow_saves_private_token(tmp_path: Path, monkeypatch) -> None:
    client = tmp_path / "client.json"
    token = tmp_path / "youtube-token.json"
    client.write_text("{}", encoding="utf-8")
    store = OAuthStateStore()

    monkeypatch.setattr(
        "social_bot.youtube_dashboard_auth._load_flow_class",
        lambda: FakeFlow,
    )

    authorization_url = begin_youtube_login(
        client,
        "http://127.0.0.1:8765/youtube/callback",
        store,
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    finish_youtube_login(
        client,
        token,
        "http://127.0.0.1:8765/youtube/callback",
        f"http://127.0.0.1:8765/youtube/callback?state={state}&code=test-code",
        store,
    )

    assert json.loads(token.read_text(encoding="utf-8"))["refresh_token"] == (
        "private-refresh-token"
    )
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    with pytest.raises(Exception, match="expired or was already used"):
        finish_youtube_login(
            client,
            token,
            "http://127.0.0.1:8765/youtube/callback",
            f"http://127.0.0.1:8765/youtube/callback?state={state}&code=replay",
            store,
        )


def test_save_credentials_replaces_existing_token(tmp_path: Path) -> None:
    token = tmp_path / "youtube-token.json"
    token.write_text("old", encoding="utf-8")

    save_youtube_credentials(FakeCredentials(), token)

    assert "private-refresh-token" in token.read_text(encoding="utf-8")
    assert not token.with_name(f".{token.name}.tmp").exists()


def test_render_login_page_never_displays_token_contents() -> None:
    page = render_youtube_login_page(
        {
            "connected": True,
            "token_present": True,
            "client_configured": True,
            "channel_id": "channel-123",
            "channel_title": "Test Channel",
            "warning": None,
        },
        controls_enabled=True,
    )

    assert "Sign in with Google" not in page
    assert "Reconnect or switch account" in page
    assert "channel-123" in page
    assert "Dashboard control token" in page
    assert "private-refresh-token" not in page


def test_disconnect_removes_only_local_token(tmp_path: Path) -> None:
    token = tmp_path / "youtube-token.json"
    token.write_text("private", encoding="utf-8")

    assert disconnect_youtube(token) is True
    assert token.exists() is False
    assert disconnect_youtube(token) is False


def test_oauth_redirect_base_accepts_loopback_and_requires_https_elsewhere() -> None:
    assert _resolve_oauth_redirect_base("127.0.0.1", 8765, None) == (
        "http://127.0.0.1:8765"
    )
    assert _resolve_oauth_redirect_base(
        "0.0.0.0",
        8765,
        "https://dashboard.example.test",
    ) == "https://dashboard.example.test"
    with pytest.raises(ValueError, match="loopback"):
        _resolve_oauth_redirect_base("0.0.0.0", 8765, "http://192.168.1.10:8765")
