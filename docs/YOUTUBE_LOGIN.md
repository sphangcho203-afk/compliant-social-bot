# YouTube dashboard login

The local dashboard can connect a YouTube account through Google's official OAuth 2.0 authorization flow. The bot never receives or stores the Google account password.

## Prerequisites

1. Enable the YouTube Data API v3 in the Google Cloud project.
2. Create an OAuth client suitable for a desktop or localhost loopback flow.
3. Download the client JSON to:

```text
secrets/youtube-client.json
```

4. Install the YouTube dependencies:

```bash
pip install -e '.[youtube]'
```

5. Start the dashboard with its existing local control token:

```bash
SOCIAL_BOT_CONTROL_TOKEN="$(cat data/dashboard-token)" social-bot-dashboard
```

Open:

```text
http://127.0.0.1:8765/youtube
```

Enter the dashboard control token and select **Sign in with Google**. Google returns the browser to:

```text
http://127.0.0.1:8765/youtube/callback
```

The resulting refreshable OAuth token is stored privately at:

```text
secrets/youtube-token.json
```

The token file is written with owner-only permissions when the operating system supports them. It remains excluded from Git and must never be copied into issues, screenshots, or chat messages.

## Existing worker compatibility

The dashboard login writes the same token format and default path already used by:

```bash
social-bot-worker --live
social-bot publish-youtube --live
social-bot sync-youtube-analytics
```

No second account configuration is created.

## Reconnect or switch accounts

Open `/youtube`, select **Reconnect or switch account**, and complete Google's consent page again. The local token is replaced atomically.

## Disconnect

Select **Remove local YouTube login**. This deletes the local token file so the worker can no longer make authenticated YouTube requests. It does not delete the YouTube channel or Google account.

## Security model

- The dashboard binds to `127.0.0.1` by default.
- Starting login and removing a token require the dashboard control token.
- The OAuth callback uses a short-lived, single-use state value to prevent request forgery.
- Passwords and recovery codes are entered only on Google's domain.
- Live publishing still requires explicit live worker mode; signing in alone does not upload anything.

When the dashboard is deliberately exposed through HTTPS, pass the browser-visible origin with `--oauth-redirect-base`. Plain HTTP callbacks are accepted only for loopback hosts.
