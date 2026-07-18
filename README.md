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

## Deployment

See `deploy/social-bot.service`. Run the service as a dedicated, unprivileged operating-system user. Never commit secrets or OAuth tokens.
