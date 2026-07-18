# Asset library

The asset library tracks local media that the operator owns or has permission to publish. It does not download media, scrape platforms, or bypass copyright controls.

## Install the updated command

```bash
pip install -e .
```

## Import owned media

```bash
social-bot-assets import ~/storage/shared/video.mp4 \
  --confirm-rights \
  --tag football \
  --tag short \
  --name "Late winner"
```

`--confirm-rights` is mandatory. Imports are identified by a SHA-256 digest, so importing the same bytes twice returns the existing asset and merges any new tags.

## Search

```bash
social-bot-assets list --query winner
social-bot-assets list --tag football
social-bot-assets list --favorites
```

## Organize

```bash
social-bot-assets tag 1 highlight vertical
social-bot-assets favorite 1 on
social-bot-assets show 1
```

The `show` command includes publication usage history when the asset has publication records.

## Dashboard

Start the existing local dashboard and open:

```text
http://127.0.0.1:8765/assets
```

The page is read-only and supports name, path, and tag filters. Importing and modifying assets remains a deliberate terminal action.

## Data model

The library extends the existing `assets` table with:

- display name
- SHA-256 content hash
- file size
- media type
- favorite flag
- updated timestamp

Tags are stored in `asset_tags`. Existing publication records continue to reference `assets.id`, allowing the dashboard and CLI to show usage counts.

## Safety boundaries

Only import files that you created, own, or are licensed to publish. The library stores paths and metadata; it does not copy files or upload anything by itself. Live publishing still requires the existing approval gates, explicit live mode, and official platform credentials.
