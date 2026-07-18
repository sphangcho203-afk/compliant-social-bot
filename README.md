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
- configurable publishing cooldowns;
- scheduled jobs, duplicate protection, dry-run mode, and approval gates;
- continuous worker operation with stale-lock recovery and structured logs;
- persistent worker heartbeats, queue health, and failed-job inspection;
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

## Approved and scheduled publication queue

Queue an owned video. New jobs are unapproved by default and cannot be claimed by the publisher:

```bash
social-bot queue-youtube clip.mp4 \
  --title "Queued upload" \
  --caption "Owned or licensed media"
```

Schedule the earliest eligible processing time with a timezone-aware ISO-8601 timestamp:

```bash
social-bot queue-youtube clip.mp4 \
  --title "Scheduled upload" \
  --run-after 2026-07-20T18:00:00Z
```

The queue creates a SHA-256 idempotency key from the video bytes and publishing metadata. Repeating an identical request returns the existing job instead of creating a duplicate. Use `--allow-duplicate` only when publishing the same media and metadata again is intentional.

Approve the returned job ID, then process one approved job. Omit `--live` to validate the full flow without uploading anything:

```bash
social-bot approve-job JOB_ID
social-bot run-youtube-publisher
```

Live worker runs enforce a 48-hour YouTube cooldown by default and leave the queued job untouched while the cooldown is active:

```bash
social-bot run-youtube-publisher --live
```

Change the interval with `--cooldown-hours HOURS`. A value of `0` disables the cooldown. Failed jobs record their error and retry up to five total attempts.

## Continuous worker

Run the approved publication queue continuously in safe dry-run mode:

```bash
social-bot-worker
```

Enable official API uploads only after OAuth is configured:

```bash
social-bot-worker --live
```

The worker polls every five seconds, emits newline-delimited JSON logs, handles `SIGINT` and `SIGTERM` gracefully, and recovers `running` publication jobs whose locks are older than 15 minutes. Tune these controls with `--poll-seconds`, `--stale-after-seconds`, and `--cooldown-hours`.

The included systemd unit runs the live worker under a dedicated unprivileged user. Review its paths and permissions before installation.

## Health and observability

Inspect the worker heartbeat, queue totals, and the latest failed jobs:

```bash
social-bot-status
```

For monitoring systems, request machine-readable output:

```bash
social-bot-status --json
```

The status command exits non-zero when the worker heartbeat is missing, stale, or degraded. The default heartbeat freshness threshold is 30 seconds and can be changed with `--stale-seconds`. Use `--failed-limit` to control how many failed jobs are displayed.

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
