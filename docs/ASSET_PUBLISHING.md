# Publish from the asset library

PR #15 connects managed assets to the existing approval-gated YouTube queue.

## Start the dashboard with queue controls

The asset page remains read-only unless a control token is configured. Use a long local token and keep the dashboard bound to `127.0.0.1`.

```bash
export SOCIAL_BOT_CONTROL_TOKEN='replace-with-a-long-random-local-token'
social-bot-dashboard
```

Open:

```text
http://127.0.0.1:8765/assets
```

Each video asset displays a mobile-friendly card with title, caption, privacy, schedule, and control-token fields.

## Queue an asset

1. Import only media you own or have permission to publish.
2. Open the asset library.
3. Fill in the publication fields.
4. Select **Queue for approval**.
5. Approve the queued job separately from the main dashboard.

Queuing does not upload anything. The existing worker still requires approval, and real YouTube publication still requires explicit live mode and official OAuth credentials.

## Asset identity and usage history

Asset-backed jobs store `asset_id` in their payload. Publication receipts reuse that same asset row, so the usage counter and history represent the actual media item instead of creating duplicate inventory records.

If an asset already has a publication receipt, the dashboard requires an explicit reuse confirmation before another job may be queued. Matching queued jobs are still suppressed by the existing idempotency protection.

## Integrity checks

Before a job is created, the server verifies:

- the asset exists;
- publishing rights are confirmed;
- the asset is a video;
- the local file still exists;
- the file hash still matches the imported asset;
- repeat use has been explicitly confirmed when required.

If the file changed after import, import it again before queuing it.

## Termux update

After merging:

```bash
cd ~/compliant-social-bot
source .venv/bin/activate
git pull
pip install -e .
deploy/termux/workerctl restart
```

Restart the dashboard with a control token to display queue forms on `/assets`.
