# Compliant Social Bot

A production-oriented starter framework for multi-platform social-media automation.

## Safety and platform boundaries

This project does **not** bypass anti-bot systems, use browser-cookie automation, imitate human browsing to evade detection, manufacture engagement, scrape against platform terms, or republish copyrighted creator media without permission.

It supports:

- official OAuth/API adapters;
- licensed or owned source assets;
- asynchronous ingestion and rendering;
- SQLite-backed jobs, assets, publications, football events, and analytics;
- FFmpeg subprocess orchestration;
- HTTP 429 handling with exponential backoff;
- configurable 48–72 hour publishing cooldowns;
- dry-run mode and approval gates;
- gradual performance-based content weighting.

## Development status

This is an architectural starter. Platform OAuth adapters, source-provider integrations, moderation, tests, and deployment hardening are tracked as GitHub issues.

## Run locally

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m social_bot.main
```

FFmpeg must be installed and available on `PATH`.

## YouTube publishing

The official YouTube adapter and CLI are safe dry runs by default. Dry runs require no Google credentials, perform no network upload, and still write a publication receipt to SQLite.

```bash
social-bot publish-youtube clip.mp4 \
  --title "Test upload" \
  --caption "Caption text" \
  --db data/social_bot.db
```

For a real upload, install the optional Google clients:

```bash
pip install -e '.[dev,youtube]'
```

Create an OAuth desktop client in a Google Cloud project with YouTube Data API v3 enabled. Save its downloaded JSON as `secrets/youtube-client.json`. The `secrets/` directory is ignored by Git. Never commit client secrets or generated refresh tokens.

The first live command opens Google's authorization flow, stores the token locally, uploads as **unlisted** by default, and records the returned video ID and URL:

```bash
social-bot publish-youtube clip.mp4 \
  --title "Verified upload" \
  --caption "Owned or licensed media" \
  --live
```

Use `--privacy public` only after verifying the uploaded file, metadata, account, and audience settings. The command never obtains credentials from browser cookies.

## YouTube analytics

Fetch one video's current views, likes, and comments and store a timestamped snapshot:

```bash
social-bot sync-youtube-analytics \
  --video-id VIDEO_ID \
  --db data/social_bot.db
```

Sync every live YouTube publication in the database:

```bash
social-bot sync-youtube-analytics --all --db data/social_bot.db
```

Dry-run publication IDs are automatically excluded. Each execution creates a new historical row in `media_performance`, allowing later trend calculations without overwriting earlier observations.

## Continuous integration

GitHub Actions runs Ruff and the test suite on Python 3.12 and 3.13 for pushes and pull requests.

## Deployment

See `deploy/social-bot.service`. Run the service as a dedicated, unprivileged operating-system user. Never commit secrets or OAuth tokens.
