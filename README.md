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

## YouTube adapter

The first official API adapter supports safe dry runs by default. Dry runs require no Google credentials and never upload media.

Install the optional Google client libraries only when preparing a real YouTube integration:

```bash
pip install -e '.[dev,youtube]'
```

Create OAuth credentials in a Google Cloud project with the YouTube Data API v3 enabled. Keep client secrets and refresh tokens outside the repository. Real uploads should initially use `privacy_status="unlisted"` while the workflow is being verified.

```python
from pathlib import Path

from social_bot.platforms.youtube import YouTubeAdapter

adapter = YouTubeAdapter(dry_run=True)
result = await adapter.publish_video(Path("clip.mp4"), "Caption text")
```

## Continuous integration

GitHub Actions runs Ruff and the test suite on Python 3.12 and 3.13 for pushes and pull requests.

## Deployment

See `deploy/social-bot.service`. Run the service as a dedicated, unprivileged operating-system user. Never commit secrets or OAuth tokens.
