# Dashboard queue manager

The dashboard remains read-only unless a control token is supplied. Start it locally with a token of at least 12 characters:

```bash
SOCIAL_BOT_CONTROL_TOKEN='replace-with-a-long-random-token' social-bot-dashboard
```

Open `http://127.0.0.1:8765` on the same device. The queue manager can:

- add an owned or licensed video path as an unapproved YouTube job;
- approve a queued job;
- cancel queued or failed jobs;
- retry failed jobs.

Every write form requires the control token. New jobs still require approval, and the worker remains a dry run unless it was deliberately started with `--live`.

Video paths must refer to files visible inside Termux. For shared Android storage, first run `termux-setup-storage`, then use a path such as:

```text
/data/data/com.termux/files/home/storage/shared/Movies/clip.mp4
```

Scheduled times must be ISO-8601 values with an explicit timezone, for example:

```text
2026-07-20T18:00:00+05:30
```

Keep the dashboard bound to `127.0.0.1`. Do not expose queue controls to the public internet without proper authentication, HTTPS, and network access controls.
